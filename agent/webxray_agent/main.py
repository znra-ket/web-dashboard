from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request

from webxray_agent.admin import is_unpaired, unpair_agent, uninstall_agent
from webxray_agent.bootstrap import (
    BootstrapAuthError,
    BootstrapClosedError,
    get_or_create_agent_csr,
    install_agent_certificate,
    read_bootstrap_state,
    require_bootstrap_authorization,
)
from webxray_agent.config import Settings, get_settings
from webxray_agent.executor import ScriptExecutionError, execute_script, sweep_workdirs
from webxray_agent.runtime import ExecutionLimiter, RequestIdCache, execution_fingerprint
from webxray_agent.schemas import (
    AdminUninstallResponse,
    AdminUnpairResponse,
    BootstrapCertificateRequest,
    BootstrapCertificateResponse,
    BootstrapCsrResponse,
    BootstrapStatusResponse,
    InfoResponse,
    ScriptExecuteRequest,
    ScriptExecuteResponse,
    ScriptUploadRequest,
    ScriptUploadResponse,
)
from webxray_agent.storage import (
    InvalidHashError,
    ScriptTooLargeError,
    delete_script,
    script_path,
    store_script_atomically,
    validate_hash,
)

SUPPORTED_FEATURES = [
    "script_upload",
    "script_execute",
    "script_delete",
    "agent_info",
    "admin_unpair",
    "admin_uninstall",
    "bootstrap_v1",
]


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sweep_workdirs(app.state.settings.workdir_root)
        yield

    app = FastAPI(title="webxray-agent", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.execution_limiter = ExecutionLimiter(
        app_settings.max_concurrent_executions_global,
        app_settings.max_concurrent_executions_per_hash,
    )
    app.state.request_id_cache = RequestIdCache(
        app_settings.request_id_cache_ttl_seconds,
        app_settings.request_id_cache_max_entries,
    )

    @app.get("/v1/info", response_model=InfoResponse)
    async def info(request: Request) -> InfoResponse:
        app_settings = request.app.state.settings
        return InfoResponse(
            agent_version=app_settings.agent_version,
            api_version=1,
            supported_features=SUPPORTED_FEATURES,
            limits={
                "max_script_upload_bytes": app_settings.max_script_upload_bytes,
                "default_timeout_seconds": app_settings.default_timeout_seconds,
                "max_timeout_seconds": app_settings.max_timeout_seconds,
                "max_args_count": app_settings.max_args_count,
                "max_single_arg_bytes": app_settings.max_single_arg_bytes,
                "max_args_total_bytes": app_settings.max_args_total_bytes,
                "max_env_count": app_settings.max_env_count,
                "max_env_key_bytes": app_settings.max_env_key_bytes,
                "max_single_env_value_bytes": app_settings.max_single_env_value_bytes,
                "max_env_total_bytes": app_settings.max_env_total_bytes,
                "max_stdout_bytes": app_settings.max_stdout_bytes,
                "max_stderr_bytes": app_settings.max_stderr_bytes,
                "max_concurrent_executions_global": app_settings.max_concurrent_executions_global,
                "max_concurrent_executions_per_hash": app_settings.max_concurrent_executions_per_hash,
                "request_id_cache_ttl_seconds": app_settings.request_id_cache_ttl_seconds,
                "request_id_cache_max_entries": app_settings.request_id_cache_max_entries,
            },
        )

    @app.post("/v1/scripts/upload", response_model=ScriptUploadResponse)
    async def upload_script(
        request: Request,
        payload: ScriptUploadRequest,
    ) -> ScriptUploadResponse:
        app_settings = request.app.state.settings
        _require_paired(app_settings)
        try:
            script_hash = store_script_atomically(
                app_settings.script_storage_dir,
                payload.script_source,
                app_settings.max_script_upload_bytes,
            )
        except ScriptTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc

        return ScriptUploadResponse(hash=script_hash)

    @app.post("/v1/scripts/execute", response_model=ScriptExecuteResponse)
    async def execute_script_endpoint(
        request: Request,
        payload: ScriptExecuteRequest,
    ) -> ScriptExecuteResponse:
        app_settings = request.app.state.settings
        _require_paired(app_settings)
        try:
            validate_hash(payload.hash)
        except InvalidHashError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        timeout_seconds = payload.timeout_seconds or app_settings.default_timeout_seconds
        if timeout_seconds <= 0 or timeout_seconds > app_settings.max_timeout_seconds:
            raise HTTPException(status_code=422, detail="Invalid timeout_seconds")
        _validate_execute_limits(payload, app_settings)

        path = script_path(app_settings.script_storage_dir, payload.hash)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Script hash not found")

        fingerprint = execution_fingerprint(payload, timeout_seconds)
        cache_status, cached_response = await request.app.state.request_id_cache.get(
            payload.request_id,
            fingerprint,
        )
        if cache_status == "hit" and cached_response is not None:
            return cached_response
        if cache_status == "conflict":
            raise HTTPException(status_code=409, detail="request_id body conflict")

        limiter = request.app.state.execution_limiter
        if not await limiter.acquire(payload.hash):
            raise HTTPException(status_code=429, detail="Execution concurrency limit exceeded")

        try:
            result = await execute_script(
                path,
                app_settings.workdir_root,
                payload.args,
                payload.env,
                timeout_seconds,
                app_settings.max_stdout_bytes,
                app_settings.max_stderr_bytes,
                app_settings.shutdown_grace_seconds,
            )
        except ScriptExecutionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            await limiter.release(payload.hash)

        response = ScriptExecuteResponse(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            error_class=result.error_class,
            stderr_truncated=result.stderr_truncated,
        )
        await request.app.state.request_id_cache.store(payload.request_id, fingerprint, response)
        return response

    @app.delete("/v1/scripts/{script_hash}", status_code=204)
    async def delete_script_endpoint(request: Request, script_hash: str) -> None:
        app_settings = request.app.state.settings
        _require_paired(app_settings)
        try:
            delete_script(app_settings.script_storage_dir, script_hash)
        except InvalidHashError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/admin/unpair", response_model=AdminUnpairResponse)
    async def unpair_endpoint(request: Request) -> AdminUnpairResponse:
        result = unpair_agent(request.app.state.settings)
        return AdminUnpairResponse(
            agent_state=result.agent_state,
            removed_paths=result.removed_paths,
        )

    @app.post("/v1/admin/uninstall", response_model=AdminUninstallResponse)
    async def uninstall_endpoint(request: Request) -> AdminUninstallResponse:
        result = uninstall_agent(request.app.state.settings)
        return AdminUninstallResponse(
            agent_state=result.agent_state,
            dry_run=result.dry_run,
            planned_paths=result.planned_paths,
            removed_paths=result.removed_paths,
        )

    @app.get("/bootstrap/v1/status", response_model=BootstrapStatusResponse)
    async def bootstrap_status(request: Request) -> BootstrapStatusResponse:
        _require_bootstrap(request)
        state = read_bootstrap_state(request.app.state.settings)
        return BootstrapStatusResponse(status=state.status, expires_at=state.expires_at)

    @app.get("/bootstrap/v1/csr", response_model=BootstrapCsrResponse)
    async def bootstrap_csr(request: Request) -> BootstrapCsrResponse:
        _require_bootstrap(request)
        return BootstrapCsrResponse(csr=get_or_create_agent_csr(request.app.state.settings))

    @app.post("/bootstrap/v1/certificate", response_model=BootstrapCertificateResponse)
    async def bootstrap_certificate(
        request: Request,
        payload: BootstrapCertificateRequest,
    ) -> BootstrapCertificateResponse:
        _require_bootstrap(request)
        state = install_agent_certificate(request.app.state.settings, payload.certificate_pem)
        return BootstrapCertificateResponse(status=state.status)

    return app


def _require_paired(settings: Settings) -> None:
    if is_unpaired(settings):
        raise HTTPException(status_code=403, detail="Agent is unpaired")


def _require_bootstrap(request: Request) -> None:
    try:
        require_bootstrap_authorization(
            request.app.state.settings,
            request.headers.get("authorization"),
        )
    except BootstrapClosedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BootstrapAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _validate_execute_limits(payload: ScriptExecuteRequest, settings: Settings) -> None:
    if len(payload.args) > settings.max_args_count:
        raise HTTPException(status_code=422, detail="Too many args")

    args_total_bytes = 0
    for arg in payload.args:
        arg_size = len(arg.encode("utf-8"))
        if arg_size > settings.max_single_arg_bytes:
            raise HTTPException(status_code=422, detail="Arg exceeds byte limit")
        args_total_bytes += arg_size
    if args_total_bytes > settings.max_args_total_bytes:
        raise HTTPException(status_code=422, detail="Args exceed total byte limit")

    if len(payload.env) > settings.max_env_count:
        raise HTTPException(status_code=422, detail="Too many env keys")

    env_total_bytes = 0
    for key, value in payload.env.items():
        key_size = len(key.encode("utf-8"))
        value_size = len(value.encode("utf-8"))
        if key_size > settings.max_env_key_bytes:
            raise HTTPException(status_code=422, detail="Env key exceeds byte limit")
        if value_size > settings.max_single_env_value_bytes:
            raise HTTPException(status_code=422, detail="Env value exceeds byte limit")
        env_total_bytes += key_size + value_size
    if env_total_bytes > settings.max_env_total_bytes:
        raise HTTPException(status_code=422, detail="Env exceeds total byte limit")


app = create_app()
