import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from webxray_agent.config import Settings
from webxray_agent.main import create_app


class AgentApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name) / "scripts"
        self.workdir_root = Path(self.temp_dir.name) / "work"
        self.app = create_app(
            Settings(
                script_storage_dir=self.storage_dir,
                workdir_root=self.workdir_root,
                max_script_upload_bytes=1024 * 1024,
                default_timeout_seconds=60,
                max_timeout_seconds=600,
            )
        )

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_info_endpoint(self) -> None:
        async with self._client() as client:
            response = await client.get("/v1/info")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["api_version"], 1)
        self.assertIn("script_upload", response.json()["supported_features"])
        self.assertIn("script_execute", response.json()["supported_features"])
        self.assertEqual(response.json()["limits"]["max_script_upload_bytes"], 1024 * 1024)
        self.assertEqual(response.json()["limits"]["default_timeout_seconds"], 60)
        self.assertEqual(response.json()["limits"]["max_timeout_seconds"], 600)

    async def test_upload_saves_script_by_sha256_hash(self) -> None:
        script_source = "#!/usr/bin/env bash\necho ok\n"
        expected_hash = sha256(script_source.encode("utf-8")).hexdigest()

        async with self._client() as client:
            response = await client.post(
                "/v1/scripts/upload",
                json={"script_source": script_source, "hash": "ignored"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"hash": expected_hash})
        self.assertEqual((self.storage_dir / expected_hash).read_bytes(), script_source.encode("utf-8"))

    async def test_repeated_upload_is_idempotent(self) -> None:
        script_source = "echo ok\n"
        expected_hash = sha256(script_source.encode("utf-8")).hexdigest()

        async with self._client() as client:
            first = await client.post("/v1/scripts/upload", json={"script_source": script_source})
            stored_path = self.storage_dir / expected_hash
            first_mtime = stored_path.stat().st_mtime_ns
            second = await client.post("/v1/scripts/upload", json={"script_source": script_source})
            second_mtime = stored_path.stat().st_mtime_ns

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first_mtime, second_mtime)

    async def test_upload_rejects_payload_over_limit(self) -> None:
        app = create_app(
            Settings(
                script_storage_dir=self.storage_dir,
                max_script_upload_bytes=4,
            )
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post("/v1/scripts/upload", json={"script_source": "12345"})

        self.assertEqual(response.status_code, 413)

    async def test_delete_is_idempotent(self) -> None:
        script_source = "echo ok\n"
        script_hash = sha256(script_source.encode("utf-8")).hexdigest()

        async with self._client() as client:
            await client.post("/v1/scripts/upload", json={"script_source": script_source})
            first_delete = await client.delete(f"/v1/scripts/{script_hash}")
            second_delete = await client.delete(f"/v1/scripts/{script_hash}")

        self.assertEqual(first_delete.status_code, 204)
        self.assertEqual(second_delete.status_code, 204)
        self.assertFalse((self.storage_dir / script_hash).exists())

    async def test_delete_validates_hash_format(self) -> None:
        async with self._client() as client:
            response = await client.delete("/v1/scripts/not-a-valid-hash")

        self.assertEqual(response.status_code, 422)

    async def test_execute_successful_script(self) -> None:
        script_source = (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.stdout.write('hello from script\\n')\n"
        )
        script_hash = await self._upload_script(script_source)

        async with self._client() as client:
            response = await client.post(
                "/v1/scripts/execute",
                json={
                    "hash": script_hash,
                    "request_id": str(uuid4()),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exit_code"], 0)
        self.assertEqual(_normalized_newlines(response.json()["stdout"]), "hello from script\n")
        self.assertEqual(response.json()["stderr"], "")
        self.assertFalse(response.json()["timed_out"])
        self.assertIsInstance(response.json()["duration_ms"], int)

    async def test_execute_passes_args(self) -> None:
        script_source = (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.stdout.write('|'.join(sys.argv[1:]) + '\\n')\n"
        )
        script_hash = await self._upload_script(script_source)

        async with self._client() as client:
            response = await client.post(
                "/v1/scripts/execute",
                json={
                    "hash": script_hash,
                    "request_id": str(uuid4()),
                    "args": ["alpha", "beta"],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_normalized_newlines(response.json()["stdout"]), "alpha|beta\n")

    async def test_execute_passes_env(self) -> None:
        script_source = (
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "sys.stdout.write(os.environ['WEBXRAY_TEST_VALUE'] + '\\n')\n"
        )
        script_hash = await self._upload_script(script_source)

        async with self._client() as client:
            response = await client.post(
                "/v1/scripts/execute",
                json={
                    "hash": script_hash,
                    "request_id": str(uuid4()),
                    "env": {"WEBXRAY_TEST_VALUE": "works"},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_normalized_newlines(response.json()["stdout"]), "works\n")

    async def test_execute_unknown_hash_returns_404(self) -> None:
        unknown_hash = "0" * 64

        async with self._client() as client:
            response = await client.post(
                "/v1/scripts/execute",
                json={
                    "hash": unknown_hash,
                    "request_id": str(uuid4()),
                },
            )

        self.assertEqual(response.status_code, 404)

    async def test_execute_timeout(self) -> None:
        script_source = (
            "#!/usr/bin/env python3\n"
            "import time\n"
            "time.sleep(2)\n"
            "print('late')\n"
        )
        script_hash = await self._upload_script(script_source)

        async with self._client() as client:
            response = await client.post(
                "/v1/scripts/execute",
                json={
                    "hash": script_hash,
                    "request_id": str(uuid4()),
                    "timeout_seconds": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["exit_code"])
        self.assertTrue(response.json()["timed_out"])

    async def test_execute_removes_workdir(self) -> None:
        script_source = (
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import sys\n"
            "Path('created-by-script.txt').write_text('temporary')\n"
            "sys.stdout.write('done\\n')\n"
        )
        script_hash = await self._upload_script(script_source)

        async with self._client() as client:
            response = await client.post(
                "/v1/scripts/execute",
                json={
                    "hash": script_hash,
                    "request_id": str(uuid4()),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_normalized_newlines(response.json()["stdout"]), "done\n")
        self.assertEqual(list(self.workdir_root.iterdir()), [])

    async def test_startup_sweeps_old_workdirs(self) -> None:
        old_workdir = self.workdir_root / "old"
        old_workdir.mkdir(parents=True)
        (old_workdir / "leftover.txt").write_text("stale")

        async with self.app.router.lifespan_context(self.app):
            self.assertEqual(list(self.workdir_root.iterdir()), [])

    def _client(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def _upload_script(self, script_source: str) -> str:
        async with self._client() as client:
            response = await client.post("/v1/scripts/upload", json={"script_source": script_source})

        self.assertEqual(response.status_code, 200)
        return response.json()["hash"]


def _normalized_newlines(value: str) -> str:
    return value.replace("\r\n", "\n")
