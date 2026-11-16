"""
camserv.platform.windows.service
================================

Microsoft Windows Service Control Manager (SCM) integration and service runner.
Provides native registration, lifecycle management, SCM dispatching, and status monitoring
using Windows sc.exe and Win32 Service APIs via advapi32.dll.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import structlog

from camserv.platform.shared.interfaces import (
    PlatformServiceManager,
    ServiceState,
    ServiceStatus,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Win32 SCM Constants
# ---------------------------------------------------------------------------
SERVICE_STOPPED = 0x00000001
SERVICE_START_PENDING = 0x00000002
SERVICE_STOP_PENDING = 0x00000003
SERVICE_RUNNING = 0x00000004
SERVICE_CONTINUE_PENDING = 0x00000005
SERVICE_PAUSE_PENDING = 0x00000006
SERVICE_PAUSED = 0x00000007

SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONTROL_PAUSE = 0x00000002
SERVICE_CONTROL_CONTINUE = 0x00000003
SERVICE_CONTROL_INTERROGATE = 0x00000004
SERVICE_CONTROL_SHUTDOWN = 0x00000005

SERVICE_ACCEPT_STOP = 0x00000001
SERVICE_ACCEPT_PAUSE_CONTINUE = 0x00000002
SERVICE_ACCEPT_SHUTDOWN = 0x00000004

SERVICE_WIN32_OWN_PROCESS = 0x00000010
NO_ERROR = 0


class SERVICE_STATUS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
    ]


class SERVICE_TABLE_ENTRYW(ctypes.Structure):
    _fields_ = [
        ("lpServiceName", wintypes.LPWSTR),
        ("lpServiceProc", ctypes.c_void_p),
    ]


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
        name: str = "CAMservCore",
        display_name: str = "CAMserv Core Security Service",
        description: str = "CAMserv Video Surveillance, Security Intelligence & Forensics Service",
        exec_path: str | None = None,
        args: list[str] | None = None,
        dependencies: list[str] | None = None,
    ) -> bool:
        """Register a new Windows Service with the SCM."""
        if exec_path is None:
            exec_path = sys.executable
            if args is None:
                args = ["-m", "camserv.platform.windows.service", "dispatch"]

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
            # Configure recovery actions: restart on failure
            self._run_sc("failure", name, "reset=", "86400", "actions=", "restart/60000/restart/60000/none/0")
            logger.info("windows.service_installed", service=name)
            return True
        else:
            logger.error("windows.service_install_failed", service=name, error=out)
            return False

    def uninstall_service(self, name: str = "CAMservCore") -> bool:
        """Stop and delete a Windows Service registration."""
        self._run_sc("stop", name)
        code, out = self._run_sc("delete", name)
        if code == 0 or "does not exist" in out.lower():
            logger.info("windows.service_uninstalled", service=name)
            return True
        else:
            logger.error("windows.service_uninstall_failed", service=name, error=out)
            return False

    def start_service(self, name: str = "CAMservCore") -> bool:
        code, out = self._run_sc("start", name)
        return code == 0 or "already running" in out.lower()

    def stop_service(self, name: str = "CAMservCore", timeout_sec: float = 10.0) -> bool:
        code, out = self._run_sc("stop", name)
        return code == 0 or "not started" in out.lower() or "does not exist" in out.lower()

    def restart_service(self, name: str = "CAMservCore") -> bool:
        self.stop_service(name)
        time.sleep(1.0)
        return self.start_service(name)

    def query_status(self, name: str = "CAMservCore") -> ServiceStatus:
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

    def is_service_installed(self, name: str = "CAMservCore") -> bool:
        code, out = self._run_sc("query", name)
        return code == 0 and "does not exist" not in out.lower()

    def emit_watchdog_heartbeat(self) -> bool:
        """On Windows, keepalives are logged to Windows Event Log or IPC heartbeat channel."""
        logger.debug("windows.service_heartbeat_emitted")
        return True


class WindowsServiceRunner:
    """
    Standard Windows Service execution harness.
    Wraps CAMserv background processing loop when launched by Windows SCM or interactive CLI.
    """

    def __init__(self, service_name: str = "CAMservCore") -> None:
        self.service_name = service_name
        self._running = False
        self._stop_event = threading.Event()
        self._status_handle: int = 0
        self._current_state: int = SERVICE_STOPPED

    def _set_status(self, state: int, checkpoint: int = 0, wait_hint: int = 0) -> None:
        self._current_state = state
        if not self._status_handle:
            return

        status = SERVICE_STATUS()
        status.dwServiceType = SERVICE_WIN32_OWN_PROCESS
        status.dwCurrentState = state
        status.dwControlsAccepted = (
            (SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN)
            if state == SERVICE_RUNNING
            else 0
        )
        status.dwWin32ExitCode = NO_ERROR
        status.dwServiceSpecificExitCode = 0
        status.dwCheckPoint = checkpoint
        status.dwWaitHint = wait_hint

        try:
            advapi32 = ctypes.windll.advapi32
            advapi32.SetServiceStatus(self._status_handle, ctypes.byref(status))
        except Exception as exc:
            logger.debug("windows.service.set_status_failed", error=str(exc))

    def _service_handler(self, control: int) -> int:
        if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
            logger.info("windows.service.stop_requested", control=control)
            self._set_status(SERVICE_STOP_PENDING, wait_hint=10000)
            self._stop_event.set()
            self._running = False
            return NO_ERROR
        elif control == SERVICE_CONTROL_INTERROGATE:
            self._set_status(self._current_state)
            return NO_ERROR
        return NO_ERROR

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

    def run_scm_dispatcher(self) -> int:
        """Connect to Windows Service Control Manager (SCM)."""
        advapi32 = ctypes.windll.advapi32

        # Define handler callback type
        HANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD)
        SERVICE_MAIN_ROUTINE = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))

        def service_handler(control: int) -> int:
            return self._service_handler(control)

        c_handler = HANDLER_ROUTINE(service_handler)

        def service_main(argc: int, argv_ptr: Any) -> None:
            try:
                # Register Handler
                self._status_handle = advapi32.RegisterServiceCtrlHandlerW(
                    self.service_name,
                    c_handler,
                )
                if not self._status_handle:
                    logger.error("windows.service.register_handler_failed")
                    return

                self._set_status(SERVICE_START_PENDING, checkpoint=1, wait_hint=15000)

                # Initialize server
                self._running = True
                self._set_status(SERVICE_RUNNING)
                logger.info("windows.service.running", service=self.service_name)

                # Execute background server in worker thread
                worker_thread = threading.Thread(
                    target=self._run_service_payload,
                    daemon=True,
                )
                worker_thread.start()

                # Wait for stop signal
                self._stop_event.wait()

                # Stopping
                self._set_status(SERVICE_STOP_PENDING, wait_hint=5000)
                logger.info("windows.service.stopping", service=self.service_name)
                self._set_status(SERVICE_STOPPED)
            except Exception as exc:
                logger.error("windows.service.main_error", error=str(exc))
                self._set_status(SERVICE_STOPPED)

        c_main = SERVICE_MAIN_ROUTINE(service_main)

        table = (SERVICE_TABLE_ENTRYW * 2)()
        table[0].lpServiceName = self.service_name
        table[0].lpServiceProc = ctypes.cast(c_main, ctypes.c_void_p).value
        table[1].lpServiceName = None
        table[1].lpServiceProc = None

        ret = advapi32.StartServiceCtrlDispatcherW(ctypes.byref(table[0]))
        if not ret:
            err = ctypes.GetLastError()
            # 1063: ERROR_FAILED_SERVICE_CONTROLLER_CONNECT (not run by SCM)
            if err == 1063:
                logger.info("windows.service.interactive_fallback", code=err)
                return self.run_console()
            else:
                logger.error("windows.service.dispatcher_error", code=err)
                return err
        return 0

    def _run_service_payload(self) -> None:
        """Background server payload running inside Windows Service."""
        try:
            from camserv.config.settings import get_settings
            from camserv.api.app import create_app
            import uvicorn

            settings = get_settings()
            app = create_app(settings)
            server = uvicorn.Server(
                config=uvicorn.Config(
                    app=app,
                    host="0.0.0.0",
                    port=8080,
                    log_level="info",
                )
            )
            # Run until stopped
            server.run()
        except Exception as exc:
            logger.error("windows.service.payload_error", error=str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="CAMserv Windows Service Host")
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "start", "stop", "restart", "status", "run", "dispatch"],
        nargs="?",
        default="status",
        help="Action to perform",
    )
    args = parser.parse_args()

    mgr = WindowsServiceManager()
    runner = WindowsServiceRunner()

    if args.action == "install":
        ok = mgr.install_service()
        print("Install success:" if ok else "Install failed:", ok)
        return 0 if ok else 1
    elif args.action == "uninstall":
        ok = mgr.uninstall_service()
        print("Uninstall success:" if ok else "Uninstall failed:", ok)
        return 0 if ok else 1
    elif args.action == "start":
        ok = mgr.start_service()
        print("Start success:" if ok else "Start failed:", ok)
        return 0 if ok else 1
    elif args.action == "stop":
        ok = mgr.stop_service()
        print("Stop success:" if ok else "Stop failed:", ok)
        return 0 if ok else 1
    elif args.action == "restart":
        ok = mgr.restart_service()
        print("Restart success:" if ok else "Restart failed:", ok)
        return 0 if ok else 1
    elif args.action == "status":
        st = mgr.query_status()
        print(f"Service: {st.name} | State: {st.state.value} | Installed: {st.state != ServiceState.NOT_INSTALLED}")
        return 0
    elif args.action == "run":
        return runner.run_console()
    elif args.action == "dispatch":
        return runner.run_scm_dispatcher()

    return 0


if __name__ == "__main__":
    sys.exit(main())
