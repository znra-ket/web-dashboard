from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from webxray_agent.config import Settings

BOOTSTRAP_STATUS_PENDING = "pending"
BOOTSTRAP_STATUS_COMPLETED = "completed"


class BootstrapAuthError(ValueError):
    pass


class BootstrapClosedError(ValueError):
    pass


@dataclass(frozen=True)
class BootstrapState:
    status: str
    expires_at: str | None


def configure_bootstrap_token(
    settings: Settings,
    raw_token: str,
    expires_at: datetime | None = None,
) -> BootstrapState:
    state_dir = _state_dir(settings)
    state_dir.mkdir(parents=True, exist_ok=True)
    resolved_expires_at = expires_at or datetime.now(UTC) + timedelta(minutes=15)
    (_token_hash_path(settings)).write_text(_hash_token(raw_token), encoding="utf-8")
    (_expires_at_path(settings)).write_text(_serialize_datetime(resolved_expires_at), encoding="utf-8")
    (_status_path(settings)).write_text(BOOTSTRAP_STATUS_PENDING, encoding="utf-8")
    return read_bootstrap_state(settings)


def read_bootstrap_state(settings: Settings) -> BootstrapState:
    status_path = _status_path(settings)
    expires_at_path = _expires_at_path(settings)
    status = status_path.read_text(encoding="utf-8").strip() if status_path.exists() else "missing"
    expires_at = expires_at_path.read_text(encoding="utf-8").strip() if expires_at_path.exists() else None
    return BootstrapState(status=status, expires_at=expires_at)


def require_bootstrap_authorization(settings: Settings, authorization: str | None) -> BootstrapState:
    state = read_bootstrap_state(settings)
    if state.status != BOOTSTRAP_STATUS_PENDING:
        raise BootstrapClosedError("Bootstrap is not open")

    token_hash_path = _token_hash_path(settings)
    if not token_hash_path.exists() or state.expires_at is None:
        raise BootstrapClosedError("Bootstrap token is not configured")

    if datetime.now(UTC) >= _parse_datetime(state.expires_at):
        raise BootstrapAuthError("Bootstrap token expired")

    raw_token = _extract_token(authorization)
    expected_hash = token_hash_path.read_text(encoding="utf-8").strip()
    if not secrets.compare_digest(expected_hash, _hash_token(raw_token)):
        raise BootstrapAuthError("Invalid bootstrap token")

    return state


def complete_bootstrap(settings: Settings) -> BootstrapState:
    _token_hash_path(settings).unlink(missing_ok=True)
    _expires_at_path(settings).unlink(missing_ok=True)
    _status_path(settings).write_text(BOOTSTRAP_STATUS_COMPLETED, encoding="utf-8")
    return read_bootstrap_state(settings)


def get_or_create_agent_csr(settings: Settings) -> str:
    private_key_path = _agent_private_key_path(settings)
    csr_path = _csr_path(settings)
    _state_dir(settings).mkdir(parents=True, exist_ok=True)
    private_key_path.parent.mkdir(parents=True, exist_ok=True)

    if private_key_path.exists() and csr_path.exists():
        return csr_path.read_text(encoding="utf-8")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_key_path.write_bytes(private_key_pem)

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "webxray-agent")]))
        .sign(private_key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("ascii")
    csr_path.write_text(csr_pem, encoding="utf-8")
    return csr_pem


def install_agent_certificate(settings: Settings, certificate_pem: str) -> BootstrapState:
    certificate = x509.load_pem_x509_certificate(certificate_pem.encode("utf-8"))
    private_key = serialization.load_pem_private_key(_agent_private_key_path(settings).read_bytes(), password=None)
    if certificate.public_key().public_numbers() != private_key.public_key().public_numbers():
        raise BootstrapAuthError("Certificate public key does not match agent private key")

    _agent_certificate_path(settings).write_text(certificate_pem, encoding="utf-8")
    (settings.pairing_state_dir / "pairing_status").parent.mkdir(parents=True, exist_ok=True)
    (settings.pairing_state_dir / "pairing_status").write_text("paired", encoding="utf-8")
    (settings.pairing_state_dir / "agent_state").write_text("paired", encoding="utf-8")
    return complete_bootstrap(settings)


def _extract_token(authorization: str | None) -> str:
    if authorization is None or not authorization.startswith("Bootstrap "):
        raise BootstrapAuthError("Missing bootstrap authorization")
    token = authorization.removeprefix("Bootstrap ").strip()
    if not token:
        raise BootstrapAuthError("Missing bootstrap token")
    return token


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _state_dir(settings: Settings) -> Path:
    return settings.bootstrap_state_dir or settings.pairing_state_dir


def _token_hash_path(settings: Settings) -> Path:
    return _state_dir(settings) / "bootstrap_token_hash"


def _expires_at_path(settings: Settings) -> Path:
    return _state_dir(settings) / "bootstrap_token_expires_at"


def _status_path(settings: Settings) -> Path:
    return _state_dir(settings) / "bootstrap_status"


def _csr_path(settings: Settings) -> Path:
    return _state_dir(settings) / "agent.csr.pem"


def _agent_private_key_path(settings: Settings) -> Path:
    return settings.pairing_state_dir / "agent_private_key.pem"


def _agent_certificate_path(settings: Settings) -> Path:
    return settings.pairing_state_dir / "agent_cert.pem"


def _serialize_datetime(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
