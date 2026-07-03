import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent_client.schemas import AgentScriptExecuteResponse, AgentScriptUploadResponse
from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.bootstrap import BootstrapTokenStatus
from app.models.folder import FolderNode
from app.models.node import Node, NodeLifecycleStatus
from app.models.node_hash_gc import NodeHashGc, NodeHashGcStatus
from app.models.node_script import NodeScript
from app.models.pipeline import PipelineRunStatus, PipelineRunStep, PipelineRunStepStatus, PipelineStepArgSourceType
from app.models.script import Script
from app.models.trigger import Trigger, TriggerSchedule
from app.schemas.folder import FolderCreate, NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.onboarding import SshOnboardingCreate
from app.schemas.pipeline import PipelineCreate, PipelineStepArgCreate, PipelineStepCreate
from app.schemas.script import ScriptCreate, ScriptUpdateContent
from app.services.folder_service import add_node_to_folder, add_script_to_folder, create_folder, create_node_script
from app.services.gc_service import HashGcService
from app.services.hash import calculate_script_hash
from app.services.metrics_onboarding_service import (
    METRICS_SCRIPTS,
    METRICS_TRIGGER_INTERVAL_SECONDS,
    Stage3MetricsOnboardingService,
)
from app.services.mtls_onboarding_service import Stage2MtlsOnboardingService
from app.services.node_deletion_service import OFFLINE_DELETE_WARNING, NodeDeletionService
from app.services.node_service import create_node
from app.services.onboarding_service import Stage1OnboardingService
from app.services.pipeline_run_service import PipelineRunService
from app.services.pipeline_service import create_pipeline, create_pipeline_step, create_pipeline_step_arg
from app.services.scheduler_service import TriggerExecutionScheduler
from app.services.script_execution_service import DashboardScriptExecutionService
from app.services.script_service import create_script, update_script_content
from app.services.ssh_installer import SshConnection
from app.services.trigger_service import create_schedule_trigger, set_schedule_trigger_on_node_script


class BackendIntegrationHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self._suffix = 0

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_create_node_script_execute_update_gc_and_scheduler_flow(self) -> None:
        async with self.session_maker() as session:
            node = await self._create_node(session, "flow")
            script = await create_script(
                session,
                ScriptCreate(name="flow-script", content="#!/usr/bin/env bash\necho ok\n"),
            )
            node_script = await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id),
            )
            old_hash = script.current_hash
            agent = RecordingAgentClient(
                execute_responses=[
                    ("missing", None),
                    ("ok", _execute_response(0, stdout="executed\n")),
                    ("ok", _execute_response(0, stdout="scheduled\n")),
                ],
                upload_hashes=[old_hash, calculate_script_hash("#!/usr/bin/env bash\necho new\n")],
                inspect_upload=CommittedScriptInspect(self.session_maker, script.id),
            )
            execution_service = DashboardScriptExecutionService(session, agent)

            response = await execution_service.execute_node_script(node_script.id)
            trigger_count_after_manual_execute = await _count(session, Trigger)
            updated = await update_script_content(
                session,
                script.id,
                ScriptUpdateContent(content="#!/usr/bin/env bash\necho new\n"),
                agent_client=agent,
            )
            gc_rows = await _all(session, NodeHashGc)
            gc_snapshot = [(item.node_id, item.hash, item.status) for item in gc_rows]
            gc_service = HashGcService(session, agent)
            await gc_service.process_pending()
            gc_after_delete = await _all(session, NodeHashGc)
            scheduled_link = await set_schedule_trigger_on_node_script(session, node_script.id, 60)

        scheduler = TriggerExecutionScheduler(self.session_maker, agent)
        await scheduler.run_schedule_fire(scheduled_link.id, request_id=uuid4())

        self.assertEqual(response.stdout, "executed\n")
        self.assertEqual(trigger_count_after_manual_execute, 0)
        self.assertEqual(updated.current_hash, calculate_script_hash("#!/usr/bin/env bash\necho new\n"))
        self.assertTrue(agent.inspect_uploads_saw_committed_state)
        self.assertEqual(gc_snapshot, [(node.id, old_hash, "pending")])
        self.assertEqual(gc_after_delete[0].status, NodeHashGcStatus.DONE.value)
        self.assertIn(("delete_hash", node.id, old_hash), agent.calls)
        self.assertEqual(
            [call[0] for call in agent.calls if call[0] in {"execute", "upload", "delete_hash"}],
            ["execute", "upload", "execute", "upload", "delete_hash", "execute"],
        )

    async def test_folder_fanout_with_schedule_trigger_materializes_independent_desired_state(self) -> None:
        async with self.session_maker() as session:
            node_a = await self._create_node(session, "folder-a")
            node_b = await self._create_node(session, "folder-b")
            script = await create_script(session, ScriptCreate(name="folder-script", content="echo folder"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            template = await create_schedule_trigger(session, 300)

            await add_node_to_folder(session, folder.id, node_a.id)
            await add_node_to_folder(session, folder.id, node_b.id)
            await add_script_to_folder(session, folder.id, script.id, template_trigger_id=template.id)
            links = await _all_node_scripts(session)
            schedules = await _all(session, TriggerSchedule)

        self.assertEqual({(link.node_id, link.script_id, link.folder_id) for link in links}, {
            (node_a.id, script.id, folder.id),
            (node_b.id, script.id, folder.id),
        })
        materialized_trigger_ids = {link.trigger_id for link in links}
        self.assertEqual(len(materialized_trigger_ids), 2)
        self.assertNotIn(template.id, materialized_trigger_ids)
        self.assertTrue(all(schedule.interval_seconds == 300 for schedule in schedules))

    async def test_onboarding_stage1_stage2_and_metrics_stage3_happy_path(self) -> None:
        async with self.session_maker() as session:
            ssh = FakeSshConnector()
            installer = FakeInstaller()
            stage1 = Stage1OnboardingService(session, ssh_connector=ssh, installer=installer)

            installed = await stage1.install_agent_over_ssh(
                SshOnboardingCreate(
                    name="onboarded",
                    host="203.0.113.80",
                    root_password=SecretStr("root-password"),
                )
            )
            token_hash_in_db = installed.bootstrap_record.token_hash
            agent = MetricsCommitInspectingAgent(self.session_maker, installed.node.id)
            paired = await Stage2MtlsOnboardingService(session, agent).establish_mtls(
                installed.node.id,
                installed.raw_bootstrap_token,
            )
            active = await Stage3MetricsOnboardingService(session, agent).upload_metrics_and_create_links(
                paired.id
            )
            token = await session.get(type(installed.bootstrap_record), installed.bootstrap_record.id)
            links = await _all_node_scripts(session)
            schedules = await _all(session, TriggerSchedule)

        self.assertEqual(installed.warning, "SSH host key fingerprint accepted via TOFU")
        self.assertEqual(installed.node.ssh_host_key_fingerprint, "sha256:ssh-host")
        self.assertNotEqual(installed.raw_bootstrap_token, token_hash_in_db)
        self.assertEqual(installer.installs[0]["bootstrap_token_hash"], token_hash_in_db)
        self.assertEqual(token.status, BootstrapTokenStatus.CONSUMED.value)
        self.assertEqual(active.lifecycle_status, NodeLifecycleStatus.ACTIVE.value)
        self.assertEqual([call[0] for call in agent.calls], ["bootstrap_csr", "bootstrap_certificate", "upload", "upload", "upload"])
        self.assertTrue(agent.metrics_uploads_saw_committed_links)
        self.assertEqual(len(links), 3)
        self.assertEqual(len({link.trigger_id for link in links}), 3)
        self.assertEqual({schedule.interval_seconds for schedule in schedules}, {METRICS_TRIGGER_INTERVAL_SECONDS})

    async def test_pipeline_run_passes_json_stdout_to_next_step_args(self) -> None:
        async with self.session_maker() as session:
            node_a = await self._create_node(session, "pipeline-a")
            node_b = await self._create_node(session, "pipeline-b")
            script_a = await create_script(session, ScriptCreate(name="pipe-a", content="echo a"))
            script_b = await create_script(session, ScriptCreate(name="pipe-b", content="echo b"))
            pipeline = await create_pipeline(session, PipelineCreate(name="pipe"))
            first_step = await create_pipeline_step(
                session,
                pipeline.id,
                PipelineStepCreate(position=1, node_id=node_a.id, script_id=script_a.id),
            )
            second_step = await create_pipeline_step(
                session,
                pipeline.id,
                PipelineStepCreate(position=2, node_id=node_b.id, script_id=script_b.id),
            )
            await create_pipeline_step_arg(
                session,
                second_step.id,
                PipelineStepArgCreate(
                    arg_index=0,
                    source_type=PipelineStepArgSourceType.STEP_OUTPUT,
                    source_step_id=first_step.id,
                    json_field="target",
                ),
            )
            agent = RecordingAgentClient(
                execute_responses=[
                    ("ok", _execute_response(0, stdout='{"target":"node-b"}')),
                    ("ok", _execute_response(0, stdout="done")),
                ]
            )
            run_service = PipelineRunService(session, DashboardScriptExecutionService(session, agent))

            run = await run_service.run_pipeline(pipeline.id)
            run_steps = await _run_steps(session, run.id)

        self.assertEqual(run.status, PipelineRunStatus.SUCCEEDED.value)
        self.assertEqual(json.loads(run_steps[1].resolved_args), ["node-b"])
        self.assertEqual(agent.execute_args, [[], ["node-b"]])
        self.assertEqual([step.status for step in run_steps], [PipelineRunStepStatus.SUCCEEDED.value] * 2)

    async def test_node_delete_modes_cover_unpair_warning_and_uninstall(self) -> None:
        async with self.session_maker() as session:
            online = await self._create_node(session, "online-delete")
            offline = await self._create_node(session, "offline-delete")
            uninstall = await self._create_node(session, "uninstall-delete")
            agent = RecordingAgentClient()
            deletion = NodeDeletionService(session, agent)

            online_result = await deletion.delete_online(online.id)
            offline_result = await deletion.delete_offline(offline.id)
            uninstall_result = await deletion.uninstall_online(uninstall.id)
            remaining_nodes = await _all(session, Node)

        self.assertTrue(online_result.deleted)
        self.assertTrue(offline_result.deleted)
        self.assertEqual(offline_result.warnings, (OFFLINE_DELETE_WARNING,))
        self.assertTrue(uninstall_result.deleted)
        self.assertEqual(remaining_nodes, [])
        self.assertEqual([call[0] for call in agent.calls], ["unpair", "uninstall"])

    async def test_architecture_invariants_remain_enforced(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        agent_source = "\n".join(path.read_text(encoding="utf-8") for path in (repo_root / "agent" / "webxray_agent").glob("*.py"))
        api_source = "\n".join(path.read_text(encoding="utf-8") for path in (repo_root / "backend" / "app" / "api").rglob("*.py"))
        backend_source = "\n".join(path.read_text(encoding="utf-8") for path in (repo_root / "backend" / "app").rglob("*.py"))

        self.assertNotIn("httpx", agent_source)
        self.assertNotIn("requests", agent_source)
        self.assertNotIn("aiohttp", agent_source)
        self.assertNotIn("socket.create_connection", agent_source)
        self.assertNotIn("pipeline", agent_source.lower())
        self.assertNotIn("/triggers", api_source)
        self.assertNotIn("CertificateRevocationList", backend_source)
        self.assertNotIn("crl", backend_source.lower())

    async def _create_node(self, session, suffix: str) -> Node:
        self._suffix += 1
        return await create_node(
            session,
            NodeCreate(
                name=f"node-{suffix}-{self._suffix}",
                host=f"203.0.113.{self._suffix}",
                lifecycle_status=NodeLifecycleStatus.ACTIVE,
                agent_cert_fingerprint=f"sha256:{suffix}-{self._suffix}",
            ),
        )


class RecordingAgentClient:
    def __init__(
        self,
        execute_responses: list[tuple[str, AgentScriptExecuteResponse | None]] | None = None,
        upload_hashes: list[str] | None = None,
        inspect_upload=None,
    ) -> None:
        self._execute_responses = execute_responses or []
        self._upload_hashes = upload_hashes or []
        self._inspect_upload = inspect_upload
        self.calls = []
        self.execute_args = []
        self.inspect_uploads_saw_committed_state = False

    async def execute_script(
        self,
        node: Node,
        script_hash: str,
        request_id: UUID,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> AgentScriptExecuteResponse:
        self.calls.append(("execute", node.id, script_hash, request_id, args or [], env or {}, timeout_seconds))
        self.execute_args.append(args or [])
        mode, response = self._execute_responses.pop(0)
        if mode == "missing":
            from app.services.exceptions import AgentScriptHashMissingError

            raise AgentScriptHashMissingError("missing")
        return response

    async def upload_script(self, node: Node, script_source: str) -> AgentScriptUploadResponse:
        self.calls.append(("upload", node.id, script_source))
        if self._inspect_upload is not None:
            self.inspect_uploads_saw_committed_state = await self._inspect_upload(script_source)
        if self._upload_hashes:
            return AgentScriptUploadResponse(hash=self._upload_hashes.pop(0))
        return AgentScriptUploadResponse(hash=calculate_script_hash(script_source))

    async def delete_script_hash(self, node: Node, script_hash: str) -> None:
        self.calls.append(("delete_hash", node.id, script_hash))

    async def unpair(self, node: Node):
        self.calls.append(("unpair", node.id, node.lifecycle_status))
        return type("UnpairResponse", (), {"agent_state": "unpaired", "removed_paths": []})()

    async def uninstall(self, node: Node):
        self.calls.append(("uninstall", node.id, node.lifecycle_status))
        return type(
            "UninstallResponse",
            (),
            {"agent_state": "unpaired", "dry_run": True, "planned_paths": [], "removed_paths": []},
        )()


class CommittedScriptInspect:
    def __init__(self, session_maker, script_id: int) -> None:
        self._session_maker = session_maker
        self._script_id = script_id

    async def __call__(self, script_source: str) -> bool:
        async with self._session_maker() as session:
            script = await session.get(Script, self._script_id)
            return script.content == script_source and script.current_hash == calculate_script_hash(script_source)


class MetricsCommitInspectingAgent(RecordingAgentClient):
    def __init__(self, session_maker, node_id: int) -> None:
        super().__init__()
        self._session_maker = session_maker
        self._node_id = node_id
        self._csr = _generate_csr()
        self.metrics_uploads_saw_committed_links = False

    async def bootstrap_csr(self, node: Node, bootstrap_token: str):
        self.calls.append(("bootstrap_csr", node.id, bootstrap_token))
        return type("CsrResponse", (), {"csr": self._csr})()

    async def bootstrap_certificate(self, node: Node, bootstrap_token: str, certificate_pem: str):
        self.calls.append(("bootstrap_certificate", node.id, bootstrap_token, certificate_pem))
        return type("CertificateResponse", (), {"status": "completed"})()

    async def upload_script(self, node: Node, script_source: str) -> AgentScriptUploadResponse:
        async with self._session_maker() as session:
            links = await _all_node_scripts(session)
            schedules = await _all(session, TriggerSchedule)
        if len([link for link in links if link.node_id == self._node_id]) == len(METRICS_SCRIPTS):
            if len(schedules) == len(METRICS_SCRIPTS):
                self.metrics_uploads_saw_committed_links = True
        return await super().upload_script(node, script_source)


class FakeSshConnector:
    async def connect_root(
        self,
        host: str,
        root_password: str,
        expected_host_key_fingerprint: str | None,
    ) -> SshConnection:
        return SshConnection(
            session=FakeSshSession(),
            host_key_fingerprint="sha256:ssh-host",
            warning="SSH host key fingerprint accepted via TOFU",
        )


class FakeSshSession:
    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None

    async def run(self, command: str, input: str | None = None, check: bool = True):
        return type("Result", (), {"exit_status": 0})()


class FakeInstaller:
    def __init__(self) -> None:
        self.installs = []

    async def install(self, session, bootstrap_token_hash: str, bootstrap_expires_at: str) -> None:
        self.installs.append(
            {
                "bootstrap_token_hash": bootstrap_token_hash,
                "bootstrap_expires_at": bootstrap_expires_at,
            }
        )


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


def _generate_csr() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "integration-agent")]))
        .sign(private_key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode("ascii")


async def _count(session, model) -> int:
    result = await session.execute(select(model))
    return len(result.scalars().all())


async def _all(session, model):
    order_column = getattr(model, "id", None) or getattr(model, "trigger_id")
    result = await session.execute(select(model).order_by(order_column))
    return list(result.scalars().all())


async def _all_node_scripts(session) -> list[NodeScript]:
    result = await session.execute(select(NodeScript).order_by(NodeScript.id))
    return list(result.scalars().all())


async def _run_steps(session, run_id: int) -> list[PipelineRunStep]:
    result = await session.execute(
        select(PipelineRunStep).where(PipelineRunStep.pipeline_run_id == run_id).order_by(PipelineRunStep.id)
    )
    return list(result.scalars().all())
