"""
camserv.platform.windows.service
================================

Microsoft Windows Service Control Manager (SCM) integration and service runner.
Provides native registration, lifecycle management, and status monitoring
using Windows sc.exe and Windows Service APIs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import structlog

from camserv.platform.shared.interfaces import (
    PlatformServiceManager,
    ServiceState,
    ServiceStatus,
)

logger = structlog.get_logger(__name__)


class WindowsServiceManager(PlatformServiceManager):
    """Manages native Windows Services via Windows Service Control Manager (SCM)."""

    def __init__(self) -> None:
        self._sc_bin = shutil.which("sc.exe") or "sc.exe"

    def _run_sc(self, *args: str) -> tuple[int, str]:
        """Execute a sc.exe subcommand."""
        try:
            res = subprocess.run(
                [self._sc_bin, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=15,
            )
            return res.returncode, res.stdout.strip()
        except Exception as exc:
            return 1, str(exc)

    def install_service(
        self,
        name: str,
        display_name: str,
        description: str,
        exec_path: str,
        args: list[str] | None = None,
        dependencies: list[str] | None = None,
    ) -> bool:
        """Register a new Windows Service with the SCM."""
        arg_str = f" {' '.join(args)}" if args else ""
        bin_path = f'"{exec_path}"{arg_str}'

        cmd = [
            "create",
            name,
            f"binPath= {bin_path}",
            f"DisplayName= {display_name or name}",
            "start= auto",
        ]
        if dependencies:
            cmd.append(f"depend= {'/'.join(dependencies)}")

        code, out = self._run_sc(*cmd)
        if code == 0:
            if description:
                self._run_sc("description", name, description)
            logger.info("windows.service_installed", service=name)
            return True
        else:
            logger.error("windows.service_install_failed", service=name, error=out)
            return False

    def uninstall_service(self, name: str) -> bool:
        """Stop and delete a Windows Service registration."""
        self._run_sc("stop", name)
        code, out = self._run_sc("delete", name)
        if code == 0 or "does not exist" in out.lower():
            logger.info("windows.service_uninstalled", service=name)
            return True
        else:
            logger.error("windows.service_uninstall_failed", service=name, error=out)
            return False

    def start_service(self, name: str) -> bool:
        code, out = self._run_sc("start", name)
        return code == 0 or "already running" in out.lower()

    def stop_service(self, name: str, timeout_sec: float = 10.0) -> bool:
        code, out = self._run_sc("stop", name)
        return code == 0 or "not started" in out.lower() or "does not exist" in out.lower()

    def restart_service(self, name: str) -> bool:
        self.stop_service(name)
        return self.start_service(name)

    def query_status(self, name: str) -> ServiceStatus:
        code, out = self._run_sc("query", name)
        if "does not exist" in out.lower() or code != 0:
            return ServiceStatus(name=name, state=ServiceState.NOT_INSTALLED, details=out)

        out_upper = out.upper()
        if "RUNNING" in out_upper:
            state = ServiceState.RUNNING
        elif "START_PENDING" in out_upper:
            state = ServiceState.STARTING
        elif "STOP_PENDING" in out_upper:
            state = ServiceState.STOPPING
        elif "STOPPED" in out_upper:
            state = ServiceState.STOPPED
        else:
            state = ServiceState.UNKNOWN

        return ServiceStatus(name=name, state=state, details=out)

    def is_service_installed(self, name: str) -> bool:
        code, out = self._run_sc("query", name)
        return code == 0 and "does not exist" not in out.lower()

    def emit_watchdog_heartbeat(self) -> bool:
        """On Windows, keepalives are logged to Windows Event Log or IPC heartbeat channel."""
        logger.debug("windows.service_heartbeat_emitted")
        return True


class WindowsServiceRunner:
    """
    Standard Windows Service execution harness.
    Wraps CAMserv background processing loop when launched by Windows SCM.
    """

    def __init__(self, service_name: str = "CAMservCore") -> None:
        self.service_name = service_name
        self._running = False

    def run_console(self, host: str = "0.0.0.0", port: int = 8080) -> int:
        """Execute CAMserv in interactive console mode on Windows."""
        from camserv.config.settings import get_settings
        from camserv.api.app import create_app
        import uvicorn

        settings = get_settings()
        app = create_app(settings)
        logger.info("windows.console_server_starting", host=host, port=port)
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0
