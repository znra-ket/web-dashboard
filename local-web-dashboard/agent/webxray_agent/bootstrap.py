from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from webxray_agent.config import (
    AgentLocalState,
    AgentState,
    AgentStateStore,
    SECRET_FILE_MODE,
    PUBLIC_FILE_MODE,
    atomic_write_text,
)


def bootstrap_token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_bootstrap_app(state_store: AgentStateStore | None = None) -> FastAPI:
    app = FastAPI(title="web-xray-agent bootstrap")
    app.state.agent_state_store = state_store

    @app.get("/bootstrap/v1/status")
    async def bootstrap_status(request: Request) -> JSONResponse:
        auth = _authorize_bootstrap_request(request, state_store)
        if isinstance(auth, JSONResponse):
            return auth
        return JSONResponse(
            {
                "agent_state": auth.state.value,
                "bootstrap_state": "pending",
            }
        )

    @app.get("/bootstrap/v1/csr")
    async def bootstrap_csr(request: Request) -> JSONResponse:
        auth = _authorize_bootstrap_request(request, state_store)
        if isinstance(auth, JSONResponse):
            return auth
        assert state_store is not None
        key_path = state_store.paths.config_dir / "agent.key"
        csr_path = state_store.paths.config_dir / "agent.csr"
        if not key_path.exists() or not csr_path.exists():
            _generate_private_key_and_csr(key_path, csr_path)
            return JSONResponse(
                {"status": "csr_not_ready"},
                status_code=202,
            )
        return JSONResponse(
            {
                "status": "csr_ready",
                "csr": csr_path.read_text(encoding="utf-8"),
            }
        )

    @app.post("/bootstrap/v1/certificate")
    async def bootstrap_certificate(request: Request) -> JSONResponse:
        auth = _authorize_bootstrap_request(request, state_store)
        if isinstance(auth, JSONResponse):
            return auth
        assert state_store is not None
        key_path = state_store.paths.config_dir / "agent.key"
        csr_path = state_store.paths.config_dir / "agent.csr"
        if not key_path.exists() or not csr_path.exists():
            return JSONResponse(
                {
                    "error_class": "csr_not_ready",
                    "status": "csr_not_ready",
                    "detail": "agent CSR is not ready",
                },
                status_code=409,
            )
        payload = await _optional_json_payload(request)
        certificate = str(payload.get("certificate") or "")
        dashboard_ca = str(payload.get("dashboard_ca") or payload.get("dashboard_ca_certificate") or "")
        if not certificate:
            return JSONResponse(
                {
                    "error_class": "invalid_certificate",
                    "detail": "certificate is required",
                },
                status_code=422,
            )
        atomic_write_text(
            state_store.paths.config_dir / "agent.crt",
            certificate,
            PUBLIC_FILE_MODE,
        )
        if dashboard_ca:
            atomic_write_text(
                state_store.paths.config_dir / "dashboard_ca.pem",
                dashboard_ca,
                PUBLIC_FILE_MODE,
            )
        state_store.mark_paired(
            dashboard_ca_fingerprint=hashlib.sha256(
                dashboard_ca.encode("utf-8")
            ).hexdigest(),
            agent_cert_fingerprint=hashlib.sha256(
                certificate.encode("utf-8")
            ).hexdigest(),
        )
        return JSONResponse(
            {
                "status": "certificate_installed",
                "agent_state": AgentState.PAIRED.value,
            }
        )

    return app


def _authorize_bootstrap_request(
    request: Request,
    state_store: AgentStateStore | None,
) -> AgentLocalState | JSONResponse:
    if state_store is None:
        return _bootstrap_closed()
    local_state = state_store.load()
    if local_state.state != AgentState.BOOTSTRAP_PENDING:
        return _bootstrap_closed()
    raw_token = _extract_bootstrap_token(request)
    if raw_token is None:
        return _invalid_bootstrap_token()
    if local_state.bootstrap_token_hash is None:
        return _invalid_bootstrap_token()
    if _bootstrap_token_expired(local_state):
        return _invalid_bootstrap_token()
    actual_hash = bootstrap_token_hash(raw_token)
    if not hmac.compare_digest(actual_hash, local_state.bootstrap_token_hash):
        return _invalid_bootstrap_token()
    return local_state


def _extract_bootstrap_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme != "Bootstrap" or not token:
        return None
    return token


def _bootstrap_token_expired(local_state: AgentLocalState) -> bool:
    now = datetime.now(UTC)
    for timestamp in (
        local_state.bootstrap_expires_at,
        local_state.bootstrap_absolute_expires_at,
    ):
        if timestamp is None:
            return True
        if now > _parse_datetime(timestamp):
            return True
    return False


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _generate_private_key_and_csr(key_path: Path, csr_path: Path) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, "web-xray-agent"),
                ]
            )
        )
        .sign(private_key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    atomic_write_text(key_path, private_key_pem, SECRET_FILE_MODE)
    atomic_write_text(csr_path, csr_pem, PUBLIC_FILE_MODE)


def _invalid_bootstrap_token() -> JSONResponse:
    return JSONResponse(
        {
            "error_class": "invalid_bootstrap_token",
            "detail": "bootstrap token is missing, invalid, or expired",
        },
        status_code=401,
    )


def _bootstrap_closed() -> JSONResponse:
    return JSONResponse(
        {
            "error_class": "bootstrap_closed",
            "detail": "bootstrap endpoint is closed",
        },
        status_code=410,
    )


async def _optional_json_payload(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        return {}
    payload = await request.json()
    return payload if isinstance(payload, dict) else {}


bootstrap_app = create_bootstrap_app()
