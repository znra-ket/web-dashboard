import pytest
from fastapi import FastAPI

import webxray_agent.runtime as runtime
from webxray_agent.config import AgentState
from webxray_agent.runtime import RuntimeMTLSContext, create_runtime_app


def test_runtime_module_does_not_export_plain_asgi_app() -> None:
    assert not hasattr(runtime, "app")


def test_runtime_app_requires_mtls_context() -> None:
    with pytest.raises(RuntimeError, match="mTLS context"):
        create_runtime_app()


def test_runtime_app_rejects_context_without_client_cert_auth() -> None:
    context = RuntimeMTLSContext(
        ca_cert_path="ca.pem",
        server_cert_path="server.pem",
        server_key_path="server.key",
        require_client_certificate=False,
    )

    with pytest.raises(RuntimeError, match="client certificate"):
        create_runtime_app(context)


def test_runtime_app_rejects_unpaired_agent_state() -> None:
    context = RuntimeMTLSContext(
        ca_cert_path="ca.pem",
        server_cert_path="server.pem",
        server_key_path="server.key",
        agent_state=AgentState.UNPAIRED,
    )

    with pytest.raises(RuntimeError, match="paired agent state"):
        create_runtime_app(context)


def test_runtime_app_exposes_runtime_v1_routes_only_with_mtls_context() -> None:
    context = RuntimeMTLSContext(
        ca_cert_path="ca.pem",
        server_cert_path="server.pem",
        server_key_path="server.key",
    )

    app = create_runtime_app(context)

    assert isinstance(app, FastAPI)
    assert app.state.mtls_context == context
    route_paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/v1/")
    }
    assert route_paths == {
        "/v1/scripts/upload",
        "/v1/scripts/execute",
        "/v1/scripts/{script_hash}",
        "/v1/info",
        "/v1/admin/unpair",
        "/v1/admin/uninstall",
    }
