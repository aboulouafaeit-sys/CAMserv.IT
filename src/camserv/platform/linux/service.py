"""
camserv.platform.linux.service
==============================

Linux systemd background service management and watchdog integration.
Interacts with systemd via systemctl CLI and UNIX notify sockets (sd_notify).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import structlog

from camserv.platform.shared.interfaces import (
    PlatformServiceManager,
    ServiceState,
    ServiceStatus,
)

logger = structlog.get_logger(__name__)


class LinuxSystemdManager(PlatformServiceManager):
    """Manages systemd background units on Debian Linux appliances."""

    def __init__(self, unit_dir: Path | str = "/usr/lib/systemd/system") -> None:
        self.unit_dir = Path(unit_dir)
        self._systemctl = shutil.which("systemctl")

    def _run_systemctl(self, *args: str) -> tuple[int, str]:
        """Execute a systemctl subcommand if systemctl is available."""
        if not self._systemctl:
            return 127, "systemctl binary not found on host."
        try:
            res = subprocess.run(
                [self._systemctl, *args],
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
        """Create and register a systemd service unit file."""
        unit_name = f"{name}.service" if not name.endswith(".service") else name
        unit_path = self.unit_dir / unit_name

        deps_str = " ".join(dependencies or ["network.target"])
        cmd_str = f"{exec_path} {' '.join(args or [])}".strip()

        unit_content = f"""[Unit]
Description={description or display_name}
After={deps_str}

[Service]
Type=simple
User=camserv
Group=camserv
ExecStart={cmd_str}
Restart=on-failure
RestartSec=5s
WatchdogSec=15s
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
"""
        try:
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(unit_content, encoding="utf-8")
            self._run_systemctl("daemon-reload")
            self._run_systemctl("enable", unit_name)
            logger.info("systemd.unit_installed", unit=unit_name)
            return True
        except Exception as exc:
            logger.error("systemd.install_failed", unit=unit_name, error=str(exc))
            return False

    def uninstall_service(self, name: str) -> bool:
        """Disable and remove a systemd service unit."""
        unit_name = f"{name}.service" if not name.endswith(".service") else name
        unit_path = self.unit_dir / unit_name

        self._run_systemctl("stop", unit_name)
        self._run_systemctl("disable", unit_name)

        if unit_path.exists():
            try:
                unit_path.unlink()
                self._run_systemctl("daemon-reload")
                logger.info("systemd.unit_uninstalled", unit=unit_name)
                return True
            except OSError as exc:
                logger.error("systemd.uninstall_failed", unit=unit_name, error=str(exc))
                return False
        return True

    def start_service(self, name: str) -> bool:
        unit_name = f"{name}.service" if not name.endswith(".service") else name
        code, out = self._run_systemctl("start", unit_name)
        return code == 0

    def stop_service(self, name: str, timeout_sec: float = 10.0) -> bool:
        unit_name = f"{name}.service" if not name.endswith(".service") else name
        code, out = self._run_systemctl("stop", unit_name)
        return code == 0

    def restart_service(self, name: str) -> bool:
        unit_name = f"{name}.service" if not name.endswith(".service") else name
        code, out = self._run_systemctl("restart", unit_name)
        return code == 0

    def query_status(self, name: str) -> ServiceStatus:
        unit_name = f"{name}.service" if not name.endswith(".service") else name
        code, out = self._run_systemctl("is-active", unit_name)

        if not self.is_service_installed(name):
            return ServiceStatus(name=name, state=ServiceState.NOT_INSTALLED, details="Unit file not found")

        if code == 0 and out == "active":
            state = ServiceState.RUNNING
        elif out == "activating":
            state = ServiceState.STARTING
        elif out == "deactivating":
            state = ServiceState.STOPPING
        elif out == "failed":
            state = ServiceState.FAILED
        else:
            state = ServiceState.STOPPED

        return ServiceStatus(name=name, state=state, details=out)

    def is_service_installed(self, name: str) -> bool:
        unit_name = f"{name}.service" if not name.endswith(".service") else name
        return (self.unit_dir / unit_name).exists()

    def emit_watchdog_heartbeat(self) -> bool:
        """Send WATCHDOG=1 heartbeat via Linux NOTIFY_SOCKET."""
        notify_socket = os.environ.get("NOTIFY_SOCKET")
        if not notify_socket:
            return False

        try:
            if notify_socket.startswith("@"):
                notify_socket = "\0" + notify_socket[1:]
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                sock.sendto(b"WATCHDOG=1", notify_socket)
                return True
            finally:
                sock.close()
        except Exception as exc:
            logger.debug("systemd.watchdog_emit_failed", error=str(exc))
            return False
