from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_client import AgentClient
from app.agent_client.schemas import AgentScriptExecuteResponse
from app.models.node import Node
from app.models.node_script import NodeScript
from app.models.script import Script
from app.services.exceptions import (
    AgentClientError,
    AgentIntegrityMismatchError,
    AgentScriptHashMissingError,
    ConflictError,
    NotFoundError,
)


class DashboardScriptExecutionService:
    def __init__(self, session: AsyncSession, agent_client: AgentClient) -> None:
        self._session = session
        self._agent_client = agent_client

    async def execute_node_script(
        self,
        node_script_id: int,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        request_id: UUID | None = None,
    ) -> AgentScriptExecuteResponse:
        node_script, node, script = await self._load_node_script(node_script_id)
        return await self._execute_and_record(
            node_script,
            node,
            script,
            args or [],
            env or {},
            timeout_seconds,
            request_id,
        )

    async def execute_script_on_node(
        self,
        node_id: int,
        script_id: int,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        request_id: UUID | None = None,
    ) -> AgentScriptExecuteResponse:
        result = await self._session.execute(
            select(NodeScript.id)
            .where(NodeScript.node_id == node_id, NodeScript.script_id == script_id)
            .order_by(NodeScript.id)
        )
        node_script_ids = list(result.scalars().all())
        if not node_script_ids:
            raise NotFoundError(f"Node-script link not found for node={node_id}, script={script_id}")
        if len(node_script_ids) > 1:
            raise ConflictError(f"Multiple node-script links exist for node={node_id}, script={script_id}")

        return await self.execute_node_script(
            node_script_ids[0],
            args=args,
            env=env,
            timeout_seconds=timeout_seconds,
            request_id=request_id,
        )

    async def _load_node_script(self, node_script_id: int) -> tuple[NodeScript, Node, Script]:
        result = await self._session.execute(
            select(NodeScript, Node, Script)
            .join(Node, Node.id == NodeScript.node_id)
            .join(Script, Script.id == NodeScript.script_id)
            .where(NodeScript.id == node_script_id)
        )
        row = result.one_or_none()
        if row is None:
            raise NotFoundError(f"Node-script link {node_script_id} not found")
        return row

    async def _execute_and_record(
        self,
        node_script: NodeScript,
        node: Node,
        script: Script,
        args: list[str],
        env: dict[str, str],
        timeout_seconds: int | None,
        request_id: UUID | None,
    ) -> AgentScriptExecuteResponse:
        try:
            response = await self._execute_with_upload_retry(
                node,
                script,
                args,
                env,
                timeout_seconds,
                request_id or uuid4(),
            )
        except AgentClientError as exc:
            await self._record_failure(node_script, str(exc))
            raise

        await self._record_response(node_script, response)
        return response

    async def _execute_with_upload_retry(
        self,
        node: Node,
        script: Script,
        args: list[str],
        env: dict[str, str],
        timeout_seconds: int | None,
        request_id: UUID,
    ) -> AgentScriptExecuteResponse:
        try:
            return await self._execute_once(node, script, args, env, timeout_seconds, request_id)
        except AgentScriptHashMissingError:
            uploaded = await self._agent_client.upload_script(node, script.content)
            if uploaded.hash != script.current_hash:
                raise AgentIntegrityMismatchError("Agent upload returned unexpected script hash")
            return await self._execute_once(node, script, args, env, timeout_seconds, request_id)

    async def _execute_once(
        self,
        node: Node,
        script: Script,
        args: list[str],
        env: dict[str, str],
        timeout_seconds: int | None,
        request_id: UUID,
    ) -> AgentScriptExecuteResponse:
        return await self._agent_client.execute_script(
            node,
            script.current_hash,
            request_id,
            args=args,
            env=env,
            timeout_seconds=timeout_seconds,
        )

    async def _record_response(
        self,
        node_script: NodeScript,
        response: AgentScriptExecuteResponse,
    ) -> None:
        now = await _current_sqlite_timestamp(self._session)
        node_script.last_run_at = now
        node_script.last_duration_ms = response.duration_ms
        error = _execution_error(response)
        node_script.last_error = error
        if error is None:
            node_script.last_success_at = now
        await self._session.commit()
        await self._session.refresh(node_script)

    async def _record_failure(self, node_script: NodeScript, error: str) -> None:
        node_script.last_run_at = await _current_sqlite_timestamp(self._session)
        node_script.last_error = error
        node_script.last_duration_ms = None
        await self._session.commit()
        await self._session.refresh(node_script)


def _execution_error(response: AgentScriptExecuteResponse) -> str | None:
    if response.error_class is not None:
        return response.error_class
    if response.timed_out:
        return "timed_out"
    if response.exit_code != 0:
        return f"exit_code={response.exit_code}"
    return None


async def _current_sqlite_timestamp(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT datetime('now')"))
    return str(result.scalar_one())
