import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent_client.schemas import AgentScriptExecuteResponse, AgentScriptUploadResponse
from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node_script import NodeScript
from app.models.node import NodeLifecycleStatus
from app.schemas.folder import NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate
from app.services.exceptions import AgentIntegrityMismatchError, AgentScriptHashMissingError
from app.services.folder_service import create_node_script
from app.services.node_service import create_node
from app.services.script_execution_service import DashboardScriptExecutionService
from app.services.script_service import create_script


class DashboardScriptExecutionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_execute_happy_path(self) -> None:
        async with self.session_maker() as session:
            node_script_id, script_hash = await self._create_binding(session)
            agent = FakeAgentClient(
                execute_responses=[
                    _execute_response(exit_code=0, stdout="ok\n", duration_ms=14),
                ]
            )
            service = DashboardScriptExecutionService(session, agent)

            response = await service.execute_script_on_node(
                1,
                1,
                args=["alpha"],
                env={"A": "B"},
                timeout_seconds=5,
            )
            node_script = await session.get(NodeScript, node_script_id)

        self.assertEqual(response.stdout, "ok\n")
        self.assertEqual(agent.calls, [("execute", script_hash, ["alpha"], {"A": "B"}, 5)])
        self.assertIsNotNone(node_script.last_run_at)
        self.assertEqual(node_script.last_success_at, node_script.last_run_at)
        self.assertIsNone(node_script.last_error)
        self.assertEqual(node_script.last_duration_ms, 14)

    async def test_execute_missing_hash_uploads_script_then_retries(self) -> None:
        script_content = "#!/usr/bin/env bash\necho retry\n"
        async with self.session_maker() as session:
            node_script_id, script_hash = await self._create_binding(session, script_content)
            agent = FakeAgentClient(
                execute_responses=[
                    AgentScriptHashMissingError("missing"),
                    _execute_response(exit_code=0, stdout="retry\n", duration_ms=22),
                ],
                upload_hash=script_hash,
            )
            service = DashboardScriptExecutionService(session, agent)

            response = await service.execute_node_script(node_script_id)
            node_script = await session.get(NodeScript, node_script_id)

        self.assertEqual(response.stdout, "retry\n")
        self.assertEqual(
            agent.calls,
            [
                ("execute", script_hash, [], {}, None),
                ("upload", script_content),
                ("execute", script_hash, [], {}, None),
            ],
        )
        self.assertEqual(node_script.last_success_at, node_script.last_run_at)
        self.assertIsNone(node_script.last_error)

    async def test_upload_hash_mismatch_is_integrity_error(self) -> None:
        async with self.session_maker() as session:
            node_script_id, script_hash = await self._create_binding(session)
            agent = FakeAgentClient(
                execute_responses=[AgentScriptHashMissingError("missing")],
                upload_hash="b" * 64,
            )
            service = DashboardScriptExecutionService(session, agent)

            with self.assertRaises(AgentIntegrityMismatchError):
                await service.execute_node_script(node_script_id)

            node_script = await session.get(NodeScript, node_script_id)

        self.assertEqual(
            agent.calls,
            [
                ("execute", script_hash, [], {}, None),
                ("upload", "#!/usr/bin/env bash\necho ok\n"),
            ],
        )
        self.assertIsNotNone(node_script.last_run_at)
        self.assertIsNone(node_script.last_success_at)
        self.assertIn("unexpected script hash", node_script.last_error)
        self.assertIsNone(node_script.last_duration_ms)

    async def test_failed_execute_records_last_run_and_error(self) -> None:
        async with self.session_maker() as session:
            node_script_id, _ = await self._create_binding(session)
            agent = FakeAgentClient(
                execute_responses=[
                    _execute_response(exit_code=7, stderr="bad\n", duration_ms=31),
                ]
            )
            service = DashboardScriptExecutionService(session, agent)

            response = await service.execute_node_script(node_script_id)
            node_script = await session.get(NodeScript, node_script_id)

        self.assertEqual(response.exit_code, 7)
        self.assertIsNotNone(node_script.last_run_at)
        self.assertIsNone(node_script.last_success_at)
        self.assertEqual(node_script.last_error, "exit_code=7")
        self.assertEqual(node_script.last_duration_ms, 31)

    async def _create_binding(
        self,
        session,
        script_content: str = "#!/usr/bin/env bash\necho ok\n",
    ) -> tuple[int, str]:
        node = await create_node(
            session,
            NodeCreate(
                name="node-1",
                host="127.0.0.1",
                agent_port=8766,
                lifecycle_status=NodeLifecycleStatus.ACTIVE,
            ),
        )
        script = await create_script(session, ScriptCreate(name="script-1", content=script_content))
        node_script = await create_node_script(
            session,
            NodeScriptCreate(node_id=node.id, script_id=script.id),
        )
        return node_script.id, script.current_hash


class FakeAgentClient:
    def __init__(
        self,
        execute_responses: list[AgentScriptExecuteResponse | Exception],
        upload_hash: str | None = None,
    ) -> None:
        self._execute_responses = execute_responses
        self._upload_hash = upload_hash
        self.calls = []

    async def execute_script(
        self,
        node,
        script_hash: str,
        request_id: UUID,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> AgentScriptExecuteResponse:
        self.calls.append(("execute", script_hash, args or [], env or {}, timeout_seconds))
        response = self._execute_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def upload_script(self, node, script_source: str) -> AgentScriptUploadResponse:
        self.calls.append(("upload", script_source))
        return AgentScriptUploadResponse(hash=self._upload_hash or "a" * 64)


def _execute_response(
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
    duration_ms: int = 1,
    timed_out: bool = False,
    error_class: str | None = None,
) -> AgentScriptExecuteResponse:
    return AgentScriptExecuteResponse(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        timed_out=timed_out,
        error_class=error_class,
        stderr_truncated=False,
    )
