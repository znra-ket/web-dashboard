from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from sqlite3 import Connection


_active_transaction_depth: ContextVar[int] = ContextVar(
    "active_sqlite_transaction_depth",
    default=0,
)
_commit_sequence: ContextVar[int] = ContextVar(
    "sqlite_transaction_commit_sequence",
    default=0,
)


class TransactionContractViolation(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TransactionMarker:
    active: bool
    depth: int
    commit_sequence: int


def current_transaction_marker() -> TransactionMarker:
    depth = _active_transaction_depth.get()
    return TransactionMarker(
        active=depth > 0,
        depth=depth,
        commit_sequence=_commit_sequence.get(),
    )


def is_db_transaction_active() -> bool:
    return current_transaction_marker().active


def assert_remote_call_allowed(operation: str = "remote agent call") -> None:
    marker = current_transaction_marker()
    if marker.active:
        raise TransactionContractViolation(
            f"{operation} attempted inside an active SQLite transaction"
        )


class SQLiteUnitOfWork:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._finished = False

    async def __aenter__(self) -> SQLiteUnitOfWork:
        if is_db_transaction_active():
            raise TransactionContractViolation("nested SQLite unit-of-work is unsupported")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("BEGIN")
        _active_transaction_depth.set(1)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if exc_type is None:
                self.connection.commit()
                _commit_sequence.set(_commit_sequence.get() + 1)
            else:
                self.connection.rollback()
        finally:
            _active_transaction_depth.set(0)
            self._finished = True

    def execute(self, sql: str, parameters: tuple[object, ...] = ()):
        if self._finished:
            raise TransactionContractViolation("unit-of-work is already closed")
        return self.connection.execute(sql, parameters)
