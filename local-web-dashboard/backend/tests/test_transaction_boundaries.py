import asyncio
import sqlite3

import pytest

from backend.app.services.transaction import (
    SQLiteUnitOfWork,
    TransactionContractViolation,
    current_transaction_marker,
    is_db_transaction_active,
)
from backend.tests.helpers import TransactionGuardedFakeAgentClient


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, message TEXT)")
    return connection


async def _bad_dummy_service(
    connection: sqlite3.Connection,
    agent_client: TransactionGuardedFakeAgentClient,
) -> None:
    async with SQLiteUnitOfWork(connection) as uow:
        uow.execute("INSERT INTO audit_log(message) VALUES (?)", ("local change",))
        await asyncio.sleep(0)
        await agent_client.execute("bad dummy service remote call")


async def _good_dummy_service(
    connection: sqlite3.Connection,
    agent_client: TransactionGuardedFakeAgentClient,
) -> dict[str, object]:
    async with SQLiteUnitOfWork(connection) as uow:
        uow.execute("INSERT INTO audit_log(message) VALUES (?)", ("local change",))

    await asyncio.sleep(0)
    return await agent_client.execute("good dummy service remote call")


def test_fake_agent_client_rejects_remote_call_inside_active_transaction() -> None:
    connection = _connection()
    agent_client = TransactionGuardedFakeAgentClient()

    with pytest.raises(TransactionContractViolation):
        asyncio.run(_bad_dummy_service(connection, agent_client))

    assert agent_client.calls == []
    assert is_db_transaction_active() is False
    assert connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_fake_agent_client_allows_remote_call_after_commit() -> None:
    connection = _connection()
    agent_client = TransactionGuardedFakeAgentClient()
    before = current_transaction_marker().commit_sequence

    result = asyncio.run(_good_dummy_service(connection, agent_client))

    assert result["active_transaction"] is False
    assert result["commit_sequence"] > before
    assert agent_client.calls == [result]
    assert connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1


def test_transaction_marker_survives_await_inside_unit_of_work() -> None:
    async def observe_marker_across_await(connection: sqlite3.Connection):
        async with SQLiteUnitOfWork(connection):
            before = current_transaction_marker()
            await asyncio.sleep(0)
            after = current_transaction_marker()
            return before, after

    before, after = asyncio.run(observe_marker_across_await(_connection()))

    assert before.active is True
    assert after.active is True
    assert before.depth == after.depth == 1
