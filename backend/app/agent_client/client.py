from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.agent_client.schemas import (
    AgentAdminUninstallResponse,
    AgentAdminUnpairResponse,
    AgentBootstrapCertificateRequest,
    AgentBootstrapCertificateResponse,
    AgentBootstrapCsrResponse,
    AgentBootstrapStatusResponse,
    AgentInfoResponse,
    AgentScriptExecuteRequest,
    AgentScriptExecuteResponse,
    AgentScriptUploadRequest,
    AgentScriptUploadResponse,
)
from app.models.node import Node
from app.services.exceptions import (
    AgentHttpError,
    AgentIntegrityMismatchError,
    AgentNetworkError,
    AgentRateLimitError,
    AgentScriptHashMissingError,
    AgentServerError,
    AgentTimeoutError,
)


@dataclass(frozen=True)
class AgentTLSConfig:
    ca_bundle_path: str | None = None
    client_cert_path: str | None = None
    client_key_path: str | None = None


@dataclass(frozen=True)
class AgentClientConfig:
    scheme: str = "http"
    timeout_seconds: float = 10.0
    tls: AgentTLSConfig | None = None


class AgentClient:
    def __init__(
        self,
        config: AgentClientConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config or AgentClientConfig()
        self._transport = transport

    async def info(self, node: Node) -> AgentInfoResponse:
        return await self._request(
            "GET",
            node,
            "/v1/info",
            response_model=AgentInfoResponse,
        )

    async def upload_script(self, node: Node, script_source: str) -> AgentScriptUploadResponse:
        payload = AgentScriptUploadRequest(script_source=script_source)
        return await self._request(
            "POST",
            node,
            "/v1/scripts/upload",
            response_model=AgentScriptUploadResponse,
            json=payload.model_dump(mode="json"),
        )

    async def execute_script(
        self,
        node: Node,
        script_hash: str,
        request_id: UUID,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> AgentScriptExecuteResponse:
        payload = AgentScriptExecuteRequest(
            hash=script_hash,
            request_id=request_id,
            args=args or [],
            env=env or {},
            timeout_seconds=timeout_seconds,
        )
        return await self._request(
            "POST",
            node,
            "/v1/scripts/execute",
            response_model=AgentScriptExecuteResponse,
            json=payload.model_dump(mode="json"),
            script_hash_missing=True,
        )

    async def delete_script_hash(self, node: Node, script_hash: str) -> None:
        await self._request(
            "DELETE",
            node,
            f"/v1/scripts/{script_hash}",
            response_model=None,
            script_hash_missing=True,
        )

    async def unpair(self, node: Node) -> AgentAdminUnpairResponse:
        return await self._request(
            "POST",
            node,
            "/v1/admin/unpair",
            response_model=AgentAdminUnpairResponse,
        )

    async def uninstall(self, node: Node) -> AgentAdminUninstallResponse:
        return await self._request(
            "POST",
            node,
            "/v1/admin/uninstall",
            response_model=AgentAdminUninstallResponse,
        )

    async def bootstrap_status(self, node: Node, bootstrap_token: str) -> AgentBootstrapStatusResponse:
        return await self._request(
            "GET",
            node,
            "/bootstrap/v1/status",
            response_model=AgentBootstrapStatusResponse,
            bootstrap_token=bootstrap_token,
        )

    async def bootstrap_csr(self, node: Node, bootstrap_token: str) -> AgentBootstrapCsrResponse:
        return await self._request(
            "GET",
            node,
            "/bootstrap/v1/csr",
            response_model=AgentBootstrapCsrResponse,
            bootstrap_token=bootstrap_token,
        )

    async def bootstrap_certificate(
        self,
        node: Node,
        bootstrap_token: str,
        certificate_pem: str,
    ) -> AgentBootstrapCertificateResponse:
        payload = AgentBootstrapCertificateRequest(certificate_pem=certificate_pem)
        return await self._request(
            "POST",
            node,
            "/bootstrap/v1/certificate",
            response_model=AgentBootstrapCertificateResponse,
            json=payload.model_dump(mode="json"),
            bootstrap_token=bootstrap_token,
        )

    async def _request(
        self,
        method: str,
        node: Node,
        path: str,
        response_model: type[BaseModel] | None,
        json: dict[str, Any] | None = None,
        script_hash_missing: bool = False,
        bootstrap_token: str | None = None,
    ) -> BaseModel | None:
        try:
            async with self._client_for(node) as client:
                headers = None
                if bootstrap_token is not None:
                    headers = {"Authorization": f"Bootstrap {bootstrap_token}"}
                response = await client.request(method, path, json=json, headers=headers)
        except httpx.TimeoutException as exc:
            raise AgentTimeoutError(f"Agent request timed out: {node.host}:{node.agent_port}") from exc
        except httpx.NetworkError as exc:
            raise AgentNetworkError(f"Agent network error: {node.host}:{node.agent_port}") from exc
        except httpx.HTTPError as exc:
            raise AgentNetworkError(f"Agent HTTP transport error: {node.host}:{node.agent_port}") from exc

        self._raise_for_status(response, script_hash_missing)
        if response_model is None:
            return None

        try:
            return response_model.model_validate(response.json())
        except (ValueError, PydanticValidationError) as exc:
            raise AgentIntegrityMismatchError("Agent response schema mismatch") from exc

    def _client_for(self, node: Node) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url(node),
            timeout=self._config.timeout_seconds,
            transport=self._transport,
            verify=self._verify_config(),
            cert=self._cert_config(),
        )

    def _base_url(self, node: Node) -> str:
        host = node.host.rstrip("/")
        if host.startswith("http://") or host.startswith("https://"):
            url = httpx.URL(host)
            if url.port is None:
                url = url.copy_with(port=node.agent_port)
            return str(url).rstrip("/")
        return f"{self._config.scheme}://{host}:{node.agent_port}"

    def _verify_config(self) -> bool | str:
        if self._config.tls is None or self._config.tls.ca_bundle_path is None:
            return True
        return self._config.tls.ca_bundle_path

    def _cert_config(self) -> str | tuple[str, str] | None:
        if self._config.tls is None or self._config.tls.client_cert_path is None:
            return None
        if self._config.tls.client_key_path is None:
            return self._config.tls.client_cert_path
        return (self._config.tls.client_cert_path, self._config.tls.client_key_path)

    def _raise_for_status(self, response: httpx.Response, script_hash_missing: bool) -> None:
        if response.status_code < 400:
            return
        detail = _response_detail(response)
        if response.status_code == 404 and script_hash_missing:
            raise AgentScriptHashMissingError(detail or "Agent script hash missing")
        if response.status_code == 409:
            raise AgentIntegrityMismatchError(detail or "Agent integrity or security mismatch")
        if response.status_code == 429:
            raise AgentRateLimitError(detail or "Agent rate limit exceeded")
        if response.status_code >= 500:
            raise AgentServerError(detail or f"Agent server error: {response.status_code}")
        raise AgentHttpError(detail or f"Agent HTTP error: {response.status_code}")


def _response_detail(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return body["detail"]
    if response.text:
        return response.text
    return None
