import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node import NodeLifecycleStatus
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate, ScriptUpdateContent
from app.services.exceptions import ConflictError
from app.services.node_service import create_node, list_nodes, read_node
from app.services.script_service import (
    create_script,
    list_scripts,
    read_script,
    update_script_content,
)


class NodeAndScriptServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_node_crud(self) -> None:
        async with self.session_maker() as session:
            created = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    agent_port=9443,
                    lifecycle_status=NodeLifecycleStatus.ACTIVE,
                    ssh_host_key_fingerprint="ssh-ed25519:abc",
                ),
            )

            loaded = await read_node(session, created.id)
            nodes = await list_nodes(session)

        self.assertEqual(loaded.name, "node-1")
        self.assertEqual(loaded.host, "203.0.113.10")
        self.assertEqual(loaded.agent_port, 9443)
        self.assertEqual(loaded.lifecycle_status, "active")
        self.assertEqual(loaded.ssh_host_key_fingerprint, "ssh-ed25519:abc")
        self.assertEqual([node.id for node in nodes], [created.id])

    async def test_script_crud_and_hash_recalculation(self) -> None:
        original_content = "#!/usr/bin/env bash\necho one\n"
        updated_content = "#!/usr/bin/env bash\necho two\n"

        async with self.session_maker() as session:
            created = await create_script(
                session,
                ScriptCreate(name="xray_status", content=original_content),
            )

            self.assertEqual(created.current_hash, _sha256(original_content))

            updated = await update_script_content(
                session,
                created.id,
                ScriptUpdateContent(content=updated_content),
            )
            loaded = await read_script(session, created.id)
            scripts = await list_scripts(session)

        self.assertEqual(updated.current_hash, _sha256(updated_content))
        self.assertEqual(loaded.content, updated_content)
        self.assertEqual(loaded.current_hash, _sha256(updated_content))
        self.assertEqual([script.id for script in scripts], [created.id])

    async def test_script_name_is_unique(self) -> None:
        async with self.session_maker() as session:
            await create_script(session, ScriptCreate(name="speedtest", content="echo one"))

            with self.assertRaises(ConflictError):
                await create_script(session, ScriptCreate(name="speedtest", content="echo two"))


def _sha256(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()
