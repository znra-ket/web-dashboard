from dataclasses import dataclass

from app.models.node import NodeLifecycleStatus


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    statements: tuple[str, ...]


NODE_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in NodeLifecycleStatus)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version="0001_foundation",
        description="Create foundation tables",
        statements=(
            f"""
            CREATE TABLE IF NOT EXISTS node (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              address TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN ({NODE_STATUS_VALUES})),
              agent_cert_fingerprint TEXT UNIQUE,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
        ),
    ),
)
