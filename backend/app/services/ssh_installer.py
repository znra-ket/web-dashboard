from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import asyncssh

from app.services.exceptions import SshHostKeyMismatchError


class SshInstallSession(Protocol):
    async def run(self, command: str, input: str | None = None, check: bool = True): ...

    def close(self) -> None: ...

    async def wait_closed(self) -> None: ...


class SshConnector(Protocol):
    async def connect_root(
        self,
        host: str,
        root_password: str,
        expected_host_key_fingerprint: str | None,
    ) -> "SshConnection": ...


class AgentInstaller(Protocol):
    async def install(
        self,
        session: SshInstallSession,
        bootstrap_token_hash: str,
        bootstrap_expires_at: str,
    ) -> None: ...


@dataclass(frozen=True)
class SshConnection:
    session: SshInstallSession
    host_key_fingerprint: str
    warning: str | None = None


class AsyncSshConnector:
    async def connect_root(
        self,
        host: str,
        root_password: str,
        expected_host_key_fingerprint: str | None,
    ) -> SshConnection:
        host_key_checker = _HostKeyCheckingClient(expected_host_key_fingerprint)
        connection = await asyncssh.connect(
            host,
            username="root",
            password=root_password,
            known_hosts=[],
            client_factory=lambda: host_key_checker,
        )
        fingerprint = host_key_checker.fingerprint
        if fingerprint is None:
            server_key = connection.get_server_host_key()
            fingerprint = server_key.get_fingerprint("sha256")

        warning = None
        if expected_host_key_fingerprint is None:
            warning = "SSH host key fingerprint accepted via TOFU"

        return SshConnection(
            session=connection,
            host_key_fingerprint=fingerprint,
            warning=warning,
        )


class ShellAgentInstaller:
    def __init__(self, install_script: str | None = None) -> None:
        self._install_script = install_script or DEFAULT_INSTALL_SCRIPT

    async def install(
        self,
        session: SshInstallSession,
        bootstrap_token_hash: str,
        bootstrap_expires_at: str,
    ) -> None:
        script = (
            f"WEBXRAY_BOOTSTRAP_TOKEN_HASH='{bootstrap_token_hash}'\n"
            f"WEBXRAY_BOOTSTRAP_EXPIRES_AT='{bootstrap_expires_at}'\n"
            f"{self._install_script}"
        )
        await session.run("sh -s", input=script, check=True)


class _HostKeyCheckingClient(asyncssh.SSHClient):
    def __init__(self, expected_fingerprint: str | None) -> None:
        self._expected_fingerprint = expected_fingerprint
        self.fingerprint: str | None = None

    def validate_host_public_key(self, host: str, addr: str, port: int, key) -> bool:  # noqa: ANN001
        fingerprint = key.get_fingerprint("sha256")
        self.fingerprint = fingerprint
        if self._expected_fingerprint is None:
            return True
        if fingerprint != self._expected_fingerprint:
            raise SshHostKeyMismatchError(
                f"SSH host key mismatch for {host}: expected {self._expected_fingerprint}, got {fingerprint}"
            )
        return True


DEFAULT_INSTALL_SCRIPT = """
set -eu
mkdir -p /opt/webxray-agent
printf '%s\n' 'webxray-agent stage1 install placeholder' > /opt/webxray-agent/install_stage1.txt
"""
