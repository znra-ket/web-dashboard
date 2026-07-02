import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from webxray_agent.config import Settings
from webxray_agent.bootstrap import configure_bootstrap_token
from webxray_agent.main import create_app


class AgentApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name) / "scripts"
        self.workdir_root = Path(self.temp_dir.name) / "work"
        self.pairing_state_dir = Path(self.temp_dir.name) / "pairing"
        self.bootstrap_state_dir = Path(self.temp_dir.name) / "bootstrap"
        self.app = create_app(
            Settings(
                script_storage_dir=self.storage_dir,
                workdir_root=self.workdir_root,
                pairing_state_dir=self.pairing_state_dir,
                bootstrap_state_dir=self.bootstrap_state_dir,
                install_root=Path(self.temp_dir.name),
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
        self.assertEqual(response.json()["limits"]["max_args_count"], 64)
        self.assertEqual(response.json()["limits"]["max_stdout_bytes"], 256 * 1024)
        self.assertEqual(response.json()["limits"]["request_id_cache_max_entries"], 1024)

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
                pairing_state_dir=self.pairing_state_dir,
                bootstrap_state_dir=self.bootstrap_state_dir,
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
        self.assertIsNone(response.json()["error_class"])
        self.assertFalse(response.json()["stderr_truncated"])
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

    async def test_execute_rejects_input_limits(self) -> None:
        script_hash = await self._upload_script("#!/usr/bin/env python3\nprint('ok')\n")
        cases = [
            (self._settings(max_args_count=1), {"args": ["a", "b"]}),
            (self._settings(max_single_arg_bytes=4), {"args": ["12345"]}),
            (self._settings(max_args_total_bytes=4), {"args": ["12", "345"]}),
            (self._settings(max_env_count=1), {"env": {"A": "1", "B": "2"}}),
            (self._settings(max_env_key_bytes=3), {"env": {"ABCD": "1"}}),
            (self._settings(max_single_env_value_bytes=4), {"env": {"A": "12345"}}),
            (self._settings(max_env_total_bytes=4), {"env": {"AB": "CD", "E": "F"}}),
            (self._settings(max_timeout_seconds=1), {"timeout_seconds": 2}),
        ]

        for settings, payload_extra in cases:
            app = create_app(settings)
            async with self._client(app) as client:
                response = await client.post(
                    "/v1/scripts/execute",
                    json={
                        "hash": script_hash,
                        "request_id": str(uuid4()),
                        **payload_extra,
                    },
                )

            self.assertEqual(response.status_code, 422)

    async def test_execute_stdout_limit_returns_failed_result(self) -> None:
        app = create_app(
            Settings(
                script_storage_dir=self.storage_dir,
                workdir_root=self.workdir_root,
                pairing_state_dir=self.pairing_state_dir,
                bootstrap_state_dir=self.bootstrap_state_dir,
                max_stdout_bytes=4,
            )
        )
        script_hash = await self._upload_script(
            "#!/usr/bin/env python3\nimport sys\nsys.stdout.write('12345')\n",
            app,
        )

        async with self._client(app) as client:
            response = await client.post(
                "/v1/scripts/execute",
                json={"hash": script_hash, "request_id": str(uuid4())},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["exit_code"])
        self.assertEqual(response.json()["stdout"], "")
        self.assertEqual(response.json()["error_class"], "stdout_limit_exceeded")

    async def test_execute_stderr_truncation(self) -> None:
        app = create_app(
            Settings(
                script_storage_dir=self.storage_dir,
                workdir_root=self.workdir_root,
                pairing_state_dir=self.pairing_state_dir,
                bootstrap_state_dir=self.bootstrap_state_dir,
                max_stderr_bytes=4,
            )
        )
        script_hash = await self._upload_script(
            "#!/usr/bin/env python3\nimport sys\nsys.stderr.write('abcdef')\n",
            app,
        )

        async with self._client(app) as client:
            response = await client.post(
                "/v1/scripts/execute",
                json={"hash": script_hash, "request_id": str(uuid4())},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stderr"], "abcd")
        self.assertTrue(response.json()["stderr_truncated"])

    async def test_execute_global_concurrency_limit(self) -> None:
        app = create_app(
            Settings(
                script_storage_dir=self.storage_dir,
                workdir_root=self.workdir_root,
                pairing_state_dir=self.pairing_state_dir,
                bootstrap_state_dir=self.bootstrap_state_dir,
                max_concurrent_executions_global=1,
                max_concurrent_executions_per_hash=2,
            )
        )
        script_source = "#!/usr/bin/env python3\nimport time\ntime.sleep(0.6)\nprint('done')\n"
        first_hash = await self._upload_script(script_source + "# first\n", app)
        second_hash = await self._upload_script(script_source + "# second\n", app)

        async with self._client(app) as client:
            first_task = asyncio.create_task(
                client.post(
                    "/v1/scripts/execute",
                    json={"hash": first_hash, "request_id": str(uuid4())},
                )
            )
            await asyncio.sleep(0.1)
            second = await client.post(
                "/v1/scripts/execute",
                json={"hash": second_hash, "request_id": str(uuid4())},
            )
            first = await first_task

        self.assertEqual(second.status_code, 429)
        self.assertEqual(first.status_code, 200)

    async def test_execute_per_hash_concurrency_limit(self) -> None:
        app = create_app(
            Settings(
                script_storage_dir=self.storage_dir,
                workdir_root=self.workdir_root,
                pairing_state_dir=self.pairing_state_dir,
                bootstrap_state_dir=self.bootstrap_state_dir,
                max_concurrent_executions_global=2,
                max_concurrent_executions_per_hash=1,
            )
        )
        script_hash = await self._upload_script(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(0.6)\nprint('done')\n",
            app,
        )

        async with self._client(app) as client:
            first_task = asyncio.create_task(
                client.post(
                    "/v1/scripts/execute",
                    json={"hash": script_hash, "request_id": str(uuid4())},
                )
            )
            await asyncio.sleep(0.1)
            second = await client.post(
                "/v1/scripts/execute",
                json={"hash": script_hash, "request_id": str(uuid4())},
            )
            first = await first_task

        self.assertEqual(second.status_code, 429)
        self.assertEqual(first.status_code, 200)

    async def test_execute_request_id_cache_returns_cached_response(self) -> None:
        counter_path = Path(self.temp_dir.name) / "counter.txt"
        script_source = (
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            f"path = Path({str(counter_path)!r})\n"
            "value = int(path.read_text()) + 1 if path.exists() else 1\n"
            "path.write_text(str(value))\n"
            "print(value)\n"
        )
        script_hash = await self._upload_script(script_source)
        request_id = str(uuid4())

        async with self._client() as client:
            first = await client.post(
                "/v1/scripts/execute",
                json={"hash": script_hash, "request_id": request_id},
            )
            second = await client.post(
                "/v1/scripts/execute",
                json={"hash": script_hash, "request_id": request_id},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(_normalized_newlines(first.json()["stdout"]), "1\n")
        self.assertEqual(first.json(), second.json())
        self.assertEqual(counter_path.read_text(), "1")

    async def test_execute_request_id_conflict(self) -> None:
        script_hash = await self._upload_script(
            "#!/usr/bin/env python3\nimport sys\nprint(sys.argv[1:])\n"
        )
        request_id = str(uuid4())

        async with self._client() as client:
            first = await client.post(
                "/v1/scripts/execute",
                json={"hash": script_hash, "request_id": request_id, "args": ["first"]},
            )
            second = await client.post(
                "/v1/scripts/execute",
                json={"hash": script_hash, "request_id": request_id, "args": ["second"]},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

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

    async def test_admin_unpair_cleans_pairing_state(self) -> None:
        self._write_pairing_state()

        async with self._client() as client:
            response = await client.post("/v1/admin/unpair")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_state"], "unpaired")
        for file_name in _PAIRING_STATE_FILES:
            self.assertFalse((self.pairing_state_dir / file_name).exists())
        self.assertEqual((self.pairing_state_dir / "agent_state").read_text(), "unpaired")

    async def test_scripts_endpoints_are_forbidden_after_unpair(self) -> None:
        script_hash = await self._upload_script("#!/usr/bin/env python3\nprint('ok')\n")

        async with self._client() as client:
            unpair = await client.post("/v1/admin/unpair")
            upload = await client.post(
                "/v1/scripts/upload",
                json={"script_source": "#!/usr/bin/env python3\nprint('blocked')\n"},
            )
            execute = await client.post(
                "/v1/scripts/execute",
                json={"hash": script_hash, "request_id": str(uuid4())},
            )
            delete = await client.delete(f"/v1/scripts/{script_hash}")

        self.assertEqual(unpair.status_code, 200)
        self.assertEqual(upload.status_code, 403)
        self.assertEqual(execute.status_code, 403)
        self.assertEqual(delete.status_code, 403)

    async def test_admin_uninstall_calls_unpair_and_returns_dry_run_plan(self) -> None:
        self._write_pairing_state()
        self.storage_dir.mkdir(parents=True)
        self.workdir_root.mkdir(parents=True)
        (self.storage_dir / "owned-script").write_text("content")

        async with self._client() as client:
            response = await client.post("/v1/admin/uninstall")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_state"], "unpaired")
        self.assertTrue(response.json()["dry_run"])
        self.assertEqual(response.json()["removed_paths"], [])
        self.assertIn(str(self.storage_dir), response.json()["planned_paths"])
        self.assertIn(str(self.workdir_root), response.json()["planned_paths"])
        self.assertIn(str(self.pairing_state_dir), response.json()["planned_paths"])
        self.assertFalse((self.pairing_state_dir / "agent_cert.pem").exists())
        self.assertTrue((self.storage_dir / "owned-script").exists())

    async def test_bootstrap_status_requires_valid_token(self) -> None:
        configure_bootstrap_token(self.app.state.settings, "raw-token")

        async with self._client() as client:
            missing = await client.get("/bootstrap/v1/status")
            wrong = await client.get(
                "/bootstrap/v1/status",
                headers={"Authorization": "Bootstrap wrong-token"},
            )
            ok = await client.get(
                "/bootstrap/v1/status",
                headers={"Authorization": "Bootstrap raw-token"},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["status"], "pending")

    async def test_bootstrap_expired_token_is_rejected(self) -> None:
        configure_bootstrap_token(
            self.app.state.settings,
            "raw-token",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        async with self._client() as client:
            response = await client.get(
                "/bootstrap/v1/status",
                headers={"Authorization": "Bootstrap raw-token"},
            )

        self.assertEqual(response.status_code, 401)

    async def test_bootstrap_endpoints_close_after_certificate(self) -> None:
        configure_bootstrap_token(self.app.state.settings, "raw-token")
        headers = {"Authorization": "Bootstrap raw-token"}

        async with self._client() as client:
            csr = await client.get("/bootstrap/v1/csr", headers=headers)
            certificate_pem = _sign_csr(csr.json()["csr"])
            certificate = await client.post(
                "/bootstrap/v1/certificate",
                headers=headers,
                json={"certificate_pem": certificate_pem},
            )
            status_after = await client.get("/bootstrap/v1/status", headers=headers)

        self.assertEqual(csr.status_code, 200)
        self.assertIn("BEGIN CERTIFICATE REQUEST", csr.json()["csr"])
        self.assertEqual(certificate.status_code, 200)
        self.assertEqual(certificate.json()["status"], "completed")
        self.assertEqual(status_after.status_code, 403)
        self.assertTrue((self.pairing_state_dir / "agent_cert.pem").exists())
        self.assertTrue((self.pairing_state_dir / "agent_private_key.pem").exists())
        self.assertEqual((self.pairing_state_dir / "pairing_status").read_text(), "paired")
        self.assertFalse((self.bootstrap_state_dir / "bootstrap_token_hash").exists())

    async def test_agent_stores_only_bootstrap_token_hash(self) -> None:
        configure_bootstrap_token(self.app.state.settings, "raw-token")

        state_files = [path.read_text() for path in self.bootstrap_state_dir.iterdir()]

        self.assertNotIn("raw-token", "\n".join(state_files))
        self.assertTrue((self.bootstrap_state_dir / "bootstrap_token_hash").exists())

    async def test_startup_sweeps_old_workdirs(self) -> None:
        old_workdir = self.workdir_root / "old"
        old_workdir.mkdir(parents=True)
        (old_workdir / "leftover.txt").write_text("stale")

        async with self.app.router.lifespan_context(self.app):
            self.assertEqual(list(self.workdir_root.iterdir()), [])

    def _client(self, app=None) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=app or self.app),
            base_url="http://testserver",
        )

    async def _upload_script(self, script_source: str, app=None) -> str:
        async with self._client(app) as client:
            response = await client.post("/v1/scripts/upload", json={"script_source": script_source})

        self.assertEqual(response.status_code, 200)
        return response.json()["hash"]

    def _write_pairing_state(self) -> None:
        self.pairing_state_dir.mkdir(parents=True, exist_ok=True)
        for file_name in _PAIRING_STATE_FILES:
            (self.pairing_state_dir / file_name).write_text(file_name)
        (self.pairing_state_dir / "agent_state").write_text("paired")

    def _settings(self, **overrides) -> Settings:
        defaults = {
            "script_storage_dir": self.storage_dir,
            "workdir_root": self.workdir_root,
            "pairing_state_dir": self.pairing_state_dir,
            "bootstrap_state_dir": self.bootstrap_state_dir,
            "install_root": Path(self.temp_dir.name),
        }
        defaults.update(overrides)
        return Settings(**defaults)


def _normalized_newlines(value: str) -> str:
    return value.replace("\r\n", "\n")


_PAIRING_STATE_FILES = (
    "dashboard_ca.pem",
    "pinned_dashboard_cert.pem",
    "agent_cert.pem",
    "agent_private_key.pem",
    "bootstrap_token_hash",
    "bootstrap_token_expires_at",
    "bootstrap_status",
    "pairing_status",
)


def _sign_csr(csr_pem: str) -> str:
    csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    now = datetime.now(UTC)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
