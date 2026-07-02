import tempfile
import unittest
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.session import get_session_maker
from app.main import create_app
from app.models.node import NodeLifecycleStatus
from app.models.node_script import NodeScript
from app.models.trigger import TriggerSchedule
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate
from app.services.node_service import create_node
from app.services.script_service import create_script
from app.services.trigger_service import create_schedule_trigger


class FolderApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.settings = Settings(
            environment="test",
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        )
        self.app = create_app(self.settings)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.session_maker = get_session_maker(self.settings.database_url)

    async def asyncTearDown(self) -> None:
        await self.lifespan.__aexit__(None, None, None)
        self.temp_dir.cleanup()

    async def test_folder_crud_endpoints(self) -> None:
        async with self._client() as client:
            created = await client.post("/folders", json={"name": "ops"})
            folder_id = created.json()["id"]
            listed = await client.get("/folders")
            loaded = await client.get(f"/folders/{folder_id}")
            updated = await client.patch(f"/folders/{folder_id}", json={"name": "core"})
            deleted = await client.delete(f"/folders/{folder_id}")
            missing = await client.get(f"/folders/{folder_id}")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], "ops")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([folder["id"] for folder in listed.json()], [folder_id])
        self.assertEqual(loaded.json()["name"], "ops")
        self.assertEqual(updated.json()["name"], "core")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(missing.status_code, 404)

    async def test_folder_membership_materializes_node_script(self) -> None:
        node_id, script_id = await self._create_node_and_script()
        async with self._client() as client:
            folder = await client.post("/folders", json={"name": "ops"})
            folder_id = folder.json()["id"]
            add_node = await client.post(f"/folders/{folder_id}/nodes", json={"node_id": node_id})
            add_script = await client.post(f"/folders/{folder_id}/scripts", json={"script_id": script_id})

        async with self.session_maker() as session:
            links = await _node_scripts(session)

        self.assertEqual(add_node.status_code, 201)
        self.assertEqual(add_script.status_code, 201)
        self.assertEqual(
            [(link.node_id, link.script_id, link.folder_id, link.trigger_id) for link in links],
            [(node_id, script_id, folder_id, None)],
        )

    async def test_remove_membership_revokes_materialized_links(self) -> None:
        node_id, script_id = await self._create_node_and_script()
        async with self._client() as client:
            folder = await client.post("/folders", json={"name": "ops"})
            folder_id = folder.json()["id"]
            await client.post(f"/folders/{folder_id}/nodes", json={"node_id": node_id})
            await client.post(f"/folders/{folder_id}/scripts", json={"script_id": script_id})
            remove_node = await client.delete(f"/folders/{folder_id}/nodes/{node_id}")

        async with self.session_maker() as session:
            links_after_node_remove = await _node_scripts(session)

        self.assertEqual(remove_node.status_code, 204)
        self.assertEqual(links_after_node_remove, [])

        async with self._client() as client:
            await client.post(f"/folders/{folder_id}/nodes", json={"node_id": node_id})
            remove_script = await client.delete(f"/folders/{folder_id}/scripts/{script_id}")

        async with self.session_maker() as session:
            links_after_script_remove = await _node_scripts(session)

        self.assertEqual(remove_script.status_code, 204)
        self.assertEqual(links_after_script_remove, [])

    async def test_template_trigger_clones_only_for_future_fanout(self) -> None:
        async with self.session_maker() as session:
            node_a = await create_node(
                session,
                NodeCreate(
                    name="node-a",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.ACTIVE,
                ),
            )
            node_b = await create_node(
                session,
                NodeCreate(
                    name="node-b",
                    host="203.0.113.11",
                    lifecycle_status=NodeLifecycleStatus.ACTIVE,
                ),
            )
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            template = await create_schedule_trigger(session, interval_seconds=60)
            node_a_id = node_a.id
            node_b_id = node_b.id
            script_id = script.id
            template_id = template.id

        async with self._client() as client:
            folder = await client.post("/folders", json={"name": "ops"})
            folder_id = folder.json()["id"]
            await client.post(f"/folders/{folder_id}/nodes", json={"node_id": node_a_id})
            add_script = await client.post(
                f"/folders/{folder_id}/scripts",
                json={"script_id": script_id, "template_trigger_id": template_id},
            )

        async with self.session_maker() as session:
            first_links = await _node_scripts(session)
            first_trigger_id = first_links[0].trigger_id
            template_schedule = await session.get(TriggerSchedule, template_id)
            template_schedule.interval_seconds = 120
            await session.commit()

        async with self._client() as client:
            await client.post(f"/folders/{folder_id}/nodes", json={"node_id": node_b_id})

        async with self.session_maker() as session:
            links = await _node_scripts(session)
            schedules = {
                link.node_id: (await session.get(TriggerSchedule, link.trigger_id)).interval_seconds
                for link in links
            }

        self.assertEqual(add_script.status_code, 201)
        self.assertNotEqual(first_trigger_id, template_id)
        self.assertEqual(schedules, {node_a_id: 60, node_b_id: 120})

    async def test_delete_folder_preserve_bindings_flag(self) -> None:
        node_id, script_id = await self._create_node_and_script()
        async with self._client() as client:
            folder = await client.post("/folders", json={"name": "ops"})
            folder_id = folder.json()["id"]
            await client.post(f"/folders/{folder_id}/nodes", json={"node_id": node_id})
            await client.post(f"/folders/{folder_id}/scripts", json={"script_id": script_id})
            deleted = await client.delete(f"/folders/{folder_id}?preserve_bindings=true")

        async with self.session_maker() as session:
            links = await _node_scripts(session)

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].folder_id, None)
        self.assertEqual(links[0].trigger_id, None)

    async def _create_node_and_script(self) -> tuple[int, int]:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.ACTIVE,
                ),
            )
            script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))
            return node.id, script.id

    def _client(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://testserver",
        )


async def _node_scripts(session) -> list[NodeScript]:
    result = await session.execute(select(NodeScript).order_by(NodeScript.id))
    return list(result.scalars().all())
