import json
import unittest
from uuid import uuid4

import httpx

from app.agent_client import AgentClient
from app.models.node import Node, NodeLifecycleStatus
from app.services.exceptions import (
    AgentHttpError,
    AgentIntegrityMismatchError,
    AgentNetworkError,
    AgentRateLimitError,
    AgentScriptHashMissingError,
    AgentServerError,
    AgentTimeoutError,
)


class AgentClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_responses_are_parsed(self) -> None:
        seen_requests: list[tuple[str, str, dict | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else None
            seen_requests.append((request.method, request.url.path, body))
            if request.url.path == "/v1/info":
                return httpx.Response(
                    200,
                    json={
                        "agent_version": "0.1.0",
                        "api_version": 1,
                        "supported_features": ["script_execute"],
                        "limits": {"max_stdout_bytes": 262144},
                    },
                )
            if request.url.path == "/v1/scripts/upload":
                self.assertEqual(body, {"script_source": "echo ok"})
                return httpx.Response(200, json={"hash": "a" * 64})
            if request.url.path == "/v1/scripts/execute":
                self.assertEqual(body["hash"], "a" * 64)
                self.assertEqual(body["args"], ["one"])
                self.assertEqual(body["env"], {"A": "B"})
                self.assertEqual(body["timeout_seconds"], 5)
                return httpx.Response(
                    200,
                    json={
                        "exit_code": 0,
                        "stdout": "ok\n",
                        "stderr": "",
                        "duration_ms": 12,
                        "timed_out": False,
                        "error_class": None,
                        "stderr_truncated": False,
                    },
                )
            if request.url.path == "/v1/scripts/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa":
                return httpx.Response(204)
            if request.url.path == "/v1/admin/unpair":
                return httpx.Response(200, json={"agent_state": "unpaired", "removed_paths": ["cert"]})
            if request.url.path == "/v1/admin/uninstall":
                return httpx.Response(
                    200,
                    json={
                        "agent_state": "unpaired",
                        "dry_run": True,
                        "planned_paths": ["scripts"],
                        "removed_paths": [],
                    },
                )
            if request.url.path == "/bootstrap/v1/status":
                self.assertEqual(request.headers["authorization"], "Bootstrap token")
                return httpx.Response(200, json={"status": "pending", "expires_at": "2026-07-02T10:15:00Z"})
            if request.url.path == "/bootstrap/v1/csr":
                self.assertEqual(request.headers["authorization"], "Bootstrap token")
                return httpx.Response(200, json={"csr": "csr-pem"})
            if request.url.path == "/bootstrap/v1/certificate":
                self.assertEqual(request.headers["authorization"], "Bootstrap token")
                self.assertEqual(body, {"certificate_pem": "cert-pem"})
                return httpx.Response(200, json={"status": "completed"})
            return httpx.Response(500)

        client = AgentClient(transport=httpx.MockTransport(handler))
        node = _node()
        request_id = uuid4()

        info = await client.info(node)
        upload = await client.upload_script(node, "echo ok")
        execute = await client.execute_script(
            node,
            "a" * 64,
            request_id,
            args=["one"],
            env={"A": "B"},
            timeout_seconds=5,
        )
        delete = await client.delete_script_hash(node, "a" * 64)
        unpair = await client.unpair(node)
        uninstall = await client.uninstall(node)
        bootstrap_status = await client.bootstrap_status(node, "token")
        bootstrap_csr = await client.bootstrap_csr(node, "token")
        bootstrap_certificate = await client.bootstrap_certificate(node, "token", "cert-pem")

        self.assertEqual(info.api_version, 1)
        self.assertEqual(upload.hash, "a" * 64)
        self.assertEqual(execute.stdout, "ok\n")
        self.assertIsNone(delete)
        self.assertEqual(unpair.agent_state, "unpaired")
        self.assertTrue(uninstall.dry_run)
        self.assertEqual(bootstrap_status.status, "pending")
        self.assertEqual(bootstrap_csr.csr, "csr-pem")
        self.assertEqual(bootstrap_certificate.status, "completed")
        self.assertEqual(
            [(method, path) for method, path, _ in seen_requests],
            [
                ("GET", "/v1/info"),
                ("POST", "/v1/scripts/upload"),
                ("POST", "/v1/scripts/execute"),
                ("DELETE", "/v1/scripts/" + "a" * 64),
                ("POST", "/v1/admin/unpair"),
                ("POST", "/v1/admin/uninstall"),
                ("GET", "/bootstrap/v1/status"),
                ("GET", "/bootstrap/v1/csr"),
                ("POST", "/bootstrap/v1/certificate"),
            ],
        )

    async def test_execute_maps_404_to_script_hash_missing(self) -> None:
        client = _client_for_status(404, {"detail": "Script hash not found"})

        with self.assertRaises(AgentScriptHashMissingError):
            await client.execute_script(_node(), "a" * 64, uuid4())

    async def test_execute_maps_409_to_integrity_mismatch(self) -> None:
        client = _client_for_status(409, {"detail": "request_id body conflict"})

        with self.assertRaises(AgentIntegrityMismatchError):
            await client.execute_script(_node(), "a" * 64, uuid4())

    async def test_execute_maps_429_to_rate_limit(self) -> None:
        client = _client_for_status(429, {"detail": "Execution concurrency limit exceeded"})

        with self.assertRaises(AgentRateLimitError):
            await client.execute_script(_node(), "a" * 64, uuid4())

    async def test_execute_maps_5xx_to_server_error(self) -> None:
        client = _client_for_status(503, {"detail": "unavailable"})

        with self.assertRaises(AgentServerError):
            await client.execute_script(_node(), "a" * 64, uuid4())

    async def test_generic_http_error_is_normalized(self) -> None:
        client = _client_for_status(403, {"detail": "Agent is unpaired"})

        with self.assertRaises(AgentHttpError):
            await client.info(_node())

    async def test_network_error_is_normalized(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("cannot connect", request=request)

        client = AgentClient(transport=httpx.MockTransport(handler))

        with self.assertRaises(AgentNetworkError):
            await client.info(_node())

    async def test_timeout_error_is_normalized(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        client = AgentClient(transport=httpx.MockTransport(handler))

        with self.assertRaises(AgentTimeoutError):
            await client.info(_node())

    async def test_response_schema_mismatch_is_integrity_error(self) -> None:
        client = _client_for_status(200, {"unexpected": "shape"})

        with self.assertRaises(AgentIntegrityMismatchError):
            await client.info(_node())


def _client_for_status(status_code: int, body: dict) -> AgentClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return AgentClient(transport=httpx.MockTransport(handler))


def _node() -> Node:
    return Node(
        id=1,
        name="node-1",
        host="127.0.0.1",
        agent_port=8766,
        lifecycle_status=NodeLifecycleStatus.ACTIVE,
    )
