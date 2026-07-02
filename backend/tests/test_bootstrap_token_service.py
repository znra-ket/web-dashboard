import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.bootstrap import BootstrapTokenStatus, NodeBootstrapToken
from app.schemas.node import NodeCreate
from app.services.bootstrap_token_service import (
    BOOTSTRAP_WINDOW,
    TOKEN_TTL,
    complete_bootstrap,
    issue_bootstrap_token,
    verify_bootstrap_token,
)
from app.services.exceptions import ValidationError
from app.services.node_service import create_node


class BootstrapTokenServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_raw_token_is_not_persisted_and_expiry_windows_are_set(self) -> None:
        now = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            issued = await issue_bootstrap_token(session, node.id, now=now)
            rows = await _bootstrap_rows(session)

        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0].token_hash, issued.raw_token)
        self.assertNotIn(issued.raw_token, repr(rows[0].__dict__))
        self.assertEqual(_parse(rows[0].expires_at), now + TOKEN_TTL)
        self.assertEqual(_parse(rows[0].bootstrap_window_expires_at), now + BOOTSTRAP_WINDOW)
        self.assertEqual(rows[0].status, BootstrapTokenStatus.PENDING.value)

    async def test_wrong_token_is_rejected(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            await issue_bootstrap_token(session, node.id)

            with self.assertRaises(ValidationError):
                await verify_bootstrap_token(session, node.id, "wrong-token")

    async def test_expired_token_is_rejected_and_marked_expired(self) -> None:
        now = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            issued = await issue_bootstrap_token(session, node.id, now=now)

            with self.assertRaises(ValidationError):
                await verify_bootstrap_token(
                    session,
                    node.id,
                    issued.raw_token,
                    now=now + timedelta(minutes=16),
                )

            rows = await _bootstrap_rows(session)

        self.assertEqual(rows[0].status, BootstrapTokenStatus.EXPIRED.value)

    async def test_complete_bootstrap_consumes_token(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            issued = await issue_bootstrap_token(session, node.id)

            consumed = await complete_bootstrap(session, node.id, issued.raw_token)

        self.assertEqual(consumed.status, BootstrapTokenStatus.CONSUMED.value)


async def _bootstrap_rows(session) -> list[NodeBootstrapToken]:
    result = await session.execute(select(NodeBootstrapToken).order_by(NodeBootstrapToken.id))
    return list(result.scalars().all())


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
