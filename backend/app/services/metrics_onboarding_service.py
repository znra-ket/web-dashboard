from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeLifecycleStatus
from app.models.node_script import NodeScript
from app.models.script import Script
from app.models.trigger import Trigger, TriggerSchedule, TriggerType
from app.services.exceptions import (
    AgentClientError,
    AgentIntegrityMismatchError,
    ConflictError,
    NotFoundError,
)
from app.services.hash import calculate_script_hash

if TYPE_CHECKING:
    from app.agent_client import AgentClient

METRICS_TRIGGER_INTERVAL_SECONDS = 21600


@dataclass(frozen=True)
class MetricsScriptDefinition:
    name: str
    content: str


METRICS_SCRIPTS: tuple[MetricsScriptDefinition, ...] = (
    MetricsScriptDefinition(
        name="xray_status",
        content="#!/usr/bin/env bash\nset -eu\nsystemctl is-active xray || true\n",
    ),
    MetricsScriptDefinition(
        name="detect_stack",
        content="#!/usr/bin/env bash\nset -eu\ncommand -v docker >/dev/null && echo docker || echo systemd\n",
    ),
    MetricsScriptDefinition(
        name="speedtest",
        content="#!/usr/bin/env bash\nset -eu\necho speedtest_placeholder\n",
    ),
)


async def seed_metrics_scripts(session: AsyncSession) -> list[Script]:
    scripts: list[Script] = []
    for definition in METRICS_SCRIPTS:
        script = await _script_by_name(session, definition.name)
        if script is None:
            script = Script(
                name=definition.name,
                content=definition.content,
                current_hash=calculate_script_hash(definition.content),
            )
            session.add(script)
            await session.flush()
        scripts.append(script)

    await session.commit()
    for script in scripts:
        await session.refresh(script)
    return scripts


class Stage3MetricsOnboardingService:
    def __init__(self, session: AsyncSession, agent_client: AgentClient) -> None:
        self._session = session
        self._agent_client = agent_client

    async def upload_metrics_and_create_links(self, node_id: int) -> Node:
        node = await self._session.get(Node, node_id)
        if node is None:
            raise NotFoundError(f"Node {node_id} not found")

        node.lifecycle_status = NodeLifecycleStatus.METRICS_UPLOADING.value
        await self._session.commit()
        await self._session.refresh(node)

        try:
            scripts = await seed_metrics_scripts(self._session)
            await self._create_metric_bindings(node, scripts)
            for script in scripts:
                uploaded = await self._agent_client.upload_script(node, script.content)
                if uploaded.hash != script.current_hash:
                    raise AgentIntegrityMismatchError(
                        f"Metrics script upload hash mismatch: {script.name}"
                    )
        except (AgentClientError, ConflictError, IntegrityError) as exc:
            await self._mark_failed(node)
            if isinstance(exc, IntegrityError):
                raise ConflictError("Could not create metrics node-script bindings") from exc
            raise

        node.lifecycle_status = NodeLifecycleStatus.ACTIVE.value
        await self._session.commit()
        await self._session.refresh(node)
        return node

    async def _create_metric_bindings(self, node: Node, scripts: list[Script]) -> None:
        try:
            for script in scripts:
                trigger = Trigger(type=TriggerType.SCHEDULE.value)
                self._session.add(trigger)
                await self._session.flush()
                self._session.add(
                    TriggerSchedule(
                        trigger_id=trigger.id,
                        interval_seconds=METRICS_TRIGGER_INTERVAL_SECONDS,
                    )
                )
                self._session.add(
                    NodeScript(
                        node_id=node.id,
                        script_id=script.id,
                        folder_id=None,
                        trigger_id=trigger.id,
                    )
                )
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise

    async def _mark_failed(self, node: Node) -> None:
        node.lifecycle_status = NodeLifecycleStatus.FAILED_METRICS_UPLOAD.value
        await self._session.commit()
        await self._session.refresh(node)


async def _script_by_name(session: AsyncSession, name: str) -> Script | None:
    result = await session.execute(select(Script).where(Script.name == name))
    return result.scalar_one_or_none()
