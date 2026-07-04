from pathlib import Path
from sqlite3 import Connection


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
CORE_MIGRATIONS = ("001_core_schema.sql",)


def apply_migrations(connection: Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    for migration_name in CORE_MIGRATIONS:
        migration_sql = MIGRATIONS_DIR.joinpath(migration_name).read_text(
            encoding="utf-8"
        )
        connection.executescript(migration_sql)
    connection.execute("PRAGMA foreign_keys = ON")
