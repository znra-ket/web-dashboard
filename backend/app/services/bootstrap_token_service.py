from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bootstrap import BootstrapTokenStatus, NodeBootstrapToken
from app.services.exceptions import NotFoundError, ValidationError

TOKEN_TTL = timedelta(minutes=15)
BOOTSTRAP_WINDOW = timedelta(minutes=30)


@dataclass(frozen=True)
class BootstrapTokenIssue:
    raw_token: str
    record: NodeBootstrapToken


async def issue_bootstrap_token(
    session: AsyncSession,
    node_id: int,
    now: datetime | None = None,
) -> BootstrapTokenIssue:
    issued_at = now or _utcnow()
    raw_token = _new_raw_token()
    token = NodeBootstrapToken(
        node_id=node_id,
        token_hash=hash_bootstrap_token(raw_token),
        expires_at=_serialize_datetime(issued_at + TOKEN_TTL),
        bootstrap_window_expires_at=_serialize_datetime(issued_at + BOOTSTRAP_WINDOW),
        status=BootstrapTokenStatus.PENDING.value,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return BootstrapTokenIssue(raw_token=raw_token, record=token)


async def verify_bootstrap_token(
    session: AsyncSession,
    node_id: int,
    raw_token: str,
    now: datetime | None = None,
) -> NodeBootstrapToken:
    token = await _latest_pending_token(session, node_id)
    checked_at = now or _utcnow()
    if token is None:
        raise NotFoundError("Bootstrap token not found")

    if _is_expired(token, checked_at):
        token.status = BootstrapTokenStatus.EXPIRED.value
        token.updated_at = _serialize_datetime(checked_at)
        await session.commit()
        raise ValidationError("Bootstrap token expired")

    if not secrets.compare_digest(token.token_hash, hash_bootstrap_token(raw_token)):
        raise ValidationError("Invalid bootstrap token")

    return token


async def complete_bootstrap(
    session: AsyncSession,
    node_id: int,
    raw_token: str,
    now: datetime | None = None,
) -> NodeBootstrapToken:
    completed_at = now or _utcnow()
    token = await verify_bootstrap_token(session, node_id, raw_token, completed_at)
    token.status = BootstrapTokenStatus.CONSUMED.value
    token.updated_at = _serialize_datetime(completed_at)
    await session.commit()
    await session.refresh(token)
    return token


def hash_bootstrap_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _new_raw_token() -> str:
    token_bytes = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(token_bytes).rstrip(b"=").decode("ascii")


async def _latest_pending_token(session: AsyncSession, node_id: int) -> NodeBootstrapToken | None:
    result = await session.execute(
        select(NodeBootstrapToken)
        .where(
            NodeBootstrapToken.node_id == node_id,
            NodeBootstrapToken.status == BootstrapTokenStatus.PENDING.value,
        )
        .order_by(NodeBootstrapToken.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _is_expired(token: NodeBootstrapToken, now: datetime) -> bool:
    return now >= _parse_datetime(token.expires_at) or now >= _parse_datetime(token.bootstrap_window_expires_at)


def _serialize_datetime(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _utcnow() -> datetime:
    return datetime.now(UTC)
