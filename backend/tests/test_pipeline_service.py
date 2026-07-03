import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node import NodeLifecycleStatus
from app.models.node_script import NodeScript
from app.models.pipeline import PipelineStepArgSourceType
from app.schemas.node import NodeCreate
from app.schemas.pipeline import (
    PipelineCreate,
    PipelineStepArgCreate,
    PipelineStepCreate,
    PipelineStepUpdate,
    PipelineUpdate,
)
from app.schemas.script import ScriptCreate
from app.services.exceptions import ConflictError, ValidationError
from app.services.node_service import create_node
from app.services.pipeline_service import (
    archive_pipeline,
    create_pipeline,
    create_pipeline_step,
    create_pipeline_step_arg,
    list_pipeline_step_args,
    list_pipeline_steps,
    list_pipelines,
    read_pipeline,
    update_pipeline,
    update_pipeline_step,
)
from app.services.script_service import create_script


class PipelineServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_pipeline_crud_and_archived_uniqueness(self) -> None:
        async with self.session_maker() as session:
            pipeline = await create_pipeline(session, PipelineCreate(name="deploy"))
            pipeline_id = pipeline.id
            loaded = await read_pipeline(session, pipeline.id)
            listed = await list_pipelines(session)
            updated = await update_pipeline(session, pipeline.id, PipelineUpdate(name="deploy-main"))

            with self.assertRaises(ConflictError):
                await create_pipeline(session, PipelineCreate(name="deploy-main"))

            archived = await archive_pipeline(session, pipeline_id)
            replacement = await create_pipeline(session, PipelineCreate(name="deploy-main"))
            active = await list_pipelines(session)
            all_pipelines = await list_pipelines(session, include_archived=True)

        self.assertEqual(loaded.id, pipeline.id)
        self.assertEqual([item.id for item in listed], [pipeline.id])
        self.assertEqual(updated.name, "deploy-main")
        self.assertTrue(archived.archived)
        self.assertFalse(replacement.archived)
        self.assertEqual([item.id for item in active], [replacement.id])
        self.assertEqual([item.id for item in all_pipelines], [pipeline_id, replacement.id])

    async def test_pipeline_step_materializes_manual_node_script(self) -> None:
        async with self.session_maker() as session:
            node_id, script_id = await self._create_node_and_script(session)
            pipeline = await create_pipeline(session, PipelineCreate(name="ops"))

            step = await create_pipeline_step(
                session,
                pipeline.id,
                PipelineStepCreate(position=1, node_id=node_id, script_id=script_id),
            )
            links = await _node_scripts(session)

        self.assertEqual(step.pipeline_id, pipeline.id)
        self.assertEqual(
            [(link.node_id, link.script_id, link.folder_id, link.trigger_id) for link in links],
            [(node_id, script_id, None, None)],
        )

    async def test_pipeline_step_position_is_unique(self) -> None:
        async with self.session_maker() as session:
            node_id, script_id = await self._create_node_and_script(session)
            pipeline = await create_pipeline(session, PipelineCreate(name="ops"))
            await create_pipeline_step(
                session,
                pipeline.id,
                PipelineStepCreate(position=1, node_id=node_id, script_id=script_id),
            )

            with self.assertRaises(ConflictError):
                await create_pipeline_step(
                    session,
                    pipeline.id,
                    PipelineStepCreate(position=1, node_id=node_id, script_id=script_id),
                )

    async def test_step_output_arg_can_reference_previous_step(self) -> None:
        async with self.session_maker() as session:
            pipeline, first_step, second_step = await self._create_two_step_pipeline(session)

            arg = await create_pipeline_step_arg(
                session,
                second_step.id,
                PipelineStepArgCreate(
                    arg_index=0,
                    source_type=PipelineStepArgSourceType.STEP_OUTPUT,
                    source_step_id=first_step.id,
                    json_field="ip",
                ),
            )
            args = await list_pipeline_step_args(session, second_step.id)
            steps = await list_pipeline_steps(session, pipeline.id)

        self.assertEqual(arg.source_step_id, first_step.id)
        self.assertEqual([item.id for item in args], [arg.id])
        self.assertEqual([step.id for step in steps], [first_step.id, second_step.id])

    async def test_forward_refs_are_rejected(self) -> None:
        async with self.session_maker() as session:
            _, first_step, second_step = await self._create_two_step_pipeline(session)

            with self.assertRaises(ValidationError):
                await create_pipeline_step_arg(
                    session,
                    first_step.id,
                    PipelineStepArgCreate(
                        arg_index=0,
                        source_type=PipelineStepArgSourceType.STEP_OUTPUT,
                        source_step_id=second_step.id,
                    ),
                )

    async def test_source_step_must_belong_to_same_pipeline(self) -> None:
        async with self.session_maker() as session:
            _, first_step, _ = await self._create_two_step_pipeline(session)
            other_pipeline, other_first_step, _ = await self._create_two_step_pipeline(session, "other")

            with self.assertRaises(ValidationError):
                await create_pipeline_step_arg(
                    session,
                    other_first_step.id,
                    PipelineStepArgCreate(
                        arg_index=0,
                        source_type=PipelineStepArgSourceType.STEP_OUTPUT,
                        source_step_id=first_step.id,
                    ),
                )

        self.assertEqual(other_pipeline.name, "other")

    async def test_reordering_steps_cannot_create_forward_ref_cycle(self) -> None:
        async with self.session_maker() as session:
            _, first_step, second_step = await self._create_two_step_pipeline(session)
            await create_pipeline_step_arg(
                session,
                second_step.id,
                PipelineStepArgCreate(
                    arg_index=0,
                    source_type=PipelineStepArgSourceType.STEP_OUTPUT,
                    source_step_id=first_step.id,
                ),
            )

            with self.assertRaises(ValidationError):
                await update_pipeline_step(
                    session,
                    first_step.id,
                    PipelineStepUpdate(
                        position=3,
                        node_id=first_step.node_id,
                        script_id=first_step.script_id,
                    ),
                )

    async def _create_two_step_pipeline(self, session, name: str = "pipeline"):
        first_node_id, first_script_id = await self._create_node_and_script(session, f"{name}-a")
        second_node_id, second_script_id = await self._create_node_and_script(session, f"{name}-b")
        pipeline = await create_pipeline(session, PipelineCreate(name=name))
        first_step = await create_pipeline_step(
            session,
            pipeline.id,
            PipelineStepCreate(position=1, node_id=first_node_id, script_id=first_script_id),
        )
        second_step = await create_pipeline_step(
            session,
            pipeline.id,
            PipelineStepCreate(position=2, node_id=second_node_id, script_id=second_script_id),
        )
        return pipeline, first_step, second_step

    async def _create_node_and_script(self, session, suffix: str = "main") -> tuple[int, int]:
        node = await create_node(
            session,
            NodeCreate(
                name=f"node-{suffix}",
                host=f"203.0.113.{len(suffix) + 10}",
                lifecycle_status=NodeLifecycleStatus.ACTIVE,
            ),
        )
        script = await create_script(
            session,
            ScriptCreate(name=f"script-{suffix}", content=f"echo {suffix}"),
        )
        return node.id, script.id


async def _node_scripts(session) -> list[NodeScript]:
    result = await session.execute(select(NodeScript).order_by(NodeScript.id))
    return list(result.scalars().all())
