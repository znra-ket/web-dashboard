from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request

from webxray_agent.config import Settings, get_settings
from webxray_agent.executor import ScriptExecutionError, execute_script, sweep_workdirs
from webxray_agent.schemas import (
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

SUPPORTED_FEATURES = ["script_upload", "script_execute", "script_delete", "agent_info"]


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sweep_workdirs(app.state.settings.workdir_root)
        yield

    app = FastAPI(title="webxray-agent", lifespan=lifespan)
    app.state.settings = app_settings

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
            },
        )

    @app.post("/v1/scripts/upload", response_model=ScriptUploadResponse)
    async def upload_script(
        request: Request,
        payload: ScriptUploadRequest,
    ) -> ScriptUploadResponse:
        app_settings = request.app.state.settings
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
        try:
            validate_hash(payload.hash)
        except InvalidHashError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        timeout_seconds = payload.timeout_seconds or app_settings.default_timeout_seconds
        if timeout_seconds <= 0 or timeout_seconds > app_settings.max_timeout_seconds:
            raise HTTPException(status_code=422, detail="Invalid timeout_seconds")

        path = script_path(app_settings.script_storage_dir, payload.hash)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Script hash not found")

        try:
            result = await execute_script(
                path,
                app_settings.workdir_root,
                payload.args,
                payload.env,
                timeout_seconds,
            )
        except ScriptExecutionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return ScriptExecuteResponse(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
        )

    @app.delete("/v1/scripts/{script_hash}", status_code=204)
    async def delete_script_endpoint(request: Request, script_hash: str) -> None:
        app_settings = request.app.state.settings
        try:
            delete_script(app_settings.script_storage_dir, script_hash)
        except InvalidHashError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
