from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.architecture.constants import AGENT_FEATURES_V1, AGENT_LIMITS_V1
from webxray_agent.admin import AdminLifecycleService, UnsafeCleanupPath
from webxray_agent.config import AgentPaths, AgentState, AgentStateStore
from webxray_agent.constants import MAX_SCRIPT_UPLOAD_BYTES
from webxray_agent.executor import (
    ConcurrencyLimitExceeded,
    ExecuteRequest,
    ExecuteResult,
    ExecuteValidationError,
    RequestIdConflict,
    ScriptExecutor,
    ScriptNotFound,
)
from webxray_agent.storage import (
    InvalidScriptHash,
    ScriptStorage,
    ScriptStorageQuotaExceeded,
    ScriptUploadTooLarge,
)


@dataclass(frozen=True)
class RuntimeMTLSContext:
    ca_cert_path: str
    server_cert_path: str
    server_key_path: str
    require_client_certificate: bool = True
    agent_state: AgentState = AgentState.PAIRED


class RequestBodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int,
        route_body_limits: dict[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.route_body_limits = route_body_limits or {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        max_body_bytes = self.route_body_limits.get(scope.get("path", ""), self.max_body_bytes)
        headers = {
            name.lower(): value
            for name, value in scope.get("headers", [])
        }
        content_length = headers.get(b"content-length")
        if content_length is not None and int(content_length) > max_body_bytes:
            response = PlainTextResponse("request body too large", status_code=413)
            await response(scope, receive, send)
            return

        received = 0
        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] != "http.request":
                return message
            body = message.get("body", b"")
            received += len(body)
            if received > max_body_bytes:
                raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            response = PlainTextResponse("request body too large", status_code=413)
            await response(scope, receive, send)


class RequestBodyTooLarge(Exception):
    pass


def create_runtime_app(
    mtls_context: RuntimeMTLSContext | None = None,
    *,
    storage: ScriptStorage | None = None,
    executor: ScriptExecutor | None = None,
    state_store: AgentStateStore | None = None,
    admin_service: AdminLifecycleService | None = None,
) -> FastAPI:
    if mtls_context is None:
        raise RuntimeError("runtime /v1 app requires an explicit mTLS context")
    if not mtls_context.require_client_certificate:
        raise RuntimeError("runtime /v1 app requires client certificate authentication")
    if mtls_context.agent_state != AgentState.PAIRED:
        raise RuntimeError("runtime /v1 app requires paired agent state")

    app = FastAPI(title="web-xray-agent runtime")
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=MAX_SCRIPT_UPLOAD_BYTES,
        route_body_limits={
            "/v1/scripts/execute": AGENT_LIMITS_V1.max_execute_body_bytes,
        },
    )
    app.state.mtls_context = mtls_context
    app.state.script_storage = storage or ScriptStorage(
        AgentPaths.from_install_root(Path.cwd() / ".webxray-agent")
    )
    app.state.agent_state = mtls_context.agent_state
    app.state.agent_state_store = state_store
    app.state.script_executor = executor or ScriptExecutor(
        storage=app.state.script_storage,
        workdir_root=app.state.script_storage.paths.workdir_root,
        limits=AGENT_LIMITS_V1,
    )
    app.state.admin_service = admin_service or AdminLifecycleService(
        app.state.script_storage.paths,
        state_store=state_store,
    )

    @app.middleware("http")
    async def reject_unpaired_runtime_commands(request: Request, call_next):
        if request.url.path.startswith("/v1/") and not request.url.path.startswith("/v1/admin/"):
            if app.state.agent_state != AgentState.PAIRED:
                return JSONResponse(
                    {
                        "error_class": "agent_unpaired",
                        "detail": "agent is not paired with a dashboard",
                    },
                    status_code=410,
                )
        return await call_next(request)

    @app.post("/v1/scripts/upload")
    async def upload_script(request: Request) -> dict[str, str]:
        content = await request.body()
        if len(content) > MAX_SCRIPT_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="script upload too large")
        try:
            script_hash = app.state.script_storage.store_script(content)
        except ScriptUploadTooLarge as exc:
            raise HTTPException(status_code=413, detail="script upload too large") from exc
        except ScriptStorageQuotaExceeded as exc:
            raise HTTPException(status_code=507, detail="script storage quota exceeded") from exc
        return {"hash": script_hash}

    @app.delete("/v1/scripts/{script_hash}")
    async def delete_script(script_hash: str) -> Response:
        try:
            app.state.script_storage.delete_script(script_hash)
        except InvalidScriptHash as exc:
            raise HTTPException(status_code=422, detail="invalid script hash") from exc
        return Response(status_code=204)

    @app.post("/v1/scripts/execute")
    async def execute_script(request: Request) -> JSONResponse:
        payload = await request.json()
        try:
            execute_request = ExecuteRequest(
                script_hash=payload.get("hash") or payload.get("script_hash"),
                request_id=payload.get("request_id"),
                args=payload.get("args") or [],
                env=payload.get("env") or {},
                timeout_seconds=payload.get("timeout_seconds"),
            )
            result = await app.state.script_executor.execute(execute_request)
        except ScriptNotFound as exc:
            return JSONResponse(
                {"error_class": exc.error_class, "detail": str(exc)},
                status_code=exc.status_code,
            )
        except ExecuteValidationError as exc:
            return JSONResponse(
                {"error_class": exc.error_class, "detail": str(exc)},
                status_code=exc.status_code,
            )
        except ConcurrencyLimitExceeded as exc:
            return JSONResponse(
                {"error_class": exc.error_class, "queued": exc.queued, "detail": str(exc)},
                status_code=exc.status_code,
            )
        except RequestIdConflict as exc:
            return JSONResponse(
                {"error_class": exc.error_class, "detail": str(exc)},
                status_code=exc.status_code,
            )
        return JSONResponse(_execute_result_to_response(result))

    @app.get("/v1/info")
    async def info() -> dict[str, Any]:
        return {
            "agent_version": "0.1.0",
            "api_version": 1,
            "supported_features": list(AGENT_FEATURES_V1),
            "limits": dict(AGENT_LIMITS_V1.as_mapping()),
        }

    @app.post("/v1/admin/unpair")
    async def unpair(request: Request) -> JSONResponse:
        payload = await _optional_json_payload(request)
        try:
            result = app.state.admin_service.unpair(dry_run=bool(payload.get("dry_run", False)))
        except UnsafeCleanupPath as exc:
            return JSONResponse(
                {"error_class": exc.error_class, "detail": str(exc)},
                status_code=exc.status_code,
            )
        if not result.dry_run:
            app.state.agent_state = AgentState.UNPAIRED
        return JSONResponse(result.to_response())

    @app.post("/v1/admin/uninstall")
    async def uninstall(request: Request) -> JSONResponse:
        payload = await _optional_json_payload(request)
        try:
            result = app.state.admin_service.uninstall(
                dry_run=bool(payload.get("dry_run", False))
            )
        except UnsafeCleanupPath as exc:
            return JSONResponse(
                {"error_class": exc.error_class, "detail": str(exc)},
                status_code=exc.status_code,
            )
        if not result.dry_run:
            app.state.agent_state = AgentState.UNPAIRED
        return JSONResponse(result.to_response())

    return app


async def _optional_json_payload(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        return {}
    payload = await request.json()
    return payload if isinstance(payload, dict) else {}


def _execute_result_to_response(result: ExecuteResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "exit_code": result.exit_code,
        "stdout": result.stdout.decode("utf-8", errors="replace"),
        "stderr": result.stderr.decode("utf-8", errors="replace"),
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
        "timeout_seconds": result.timeout_seconds,
        "error": result.error_class,
        "error_class": result.error_class,
        "stderr_truncated": result.stderr_truncated,
    }
