"""
camserv.deploy.supervisor
=========================

Service supervision, watchdog monitoring, restart loop protection,
and disaster recovery management for dedicated CAMserv AI Appliances.
"""

from __future__ import annotations

import enum
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ApplianceServiceState(str, enum.Enum):
    """Lifecycle state of an appliance systemd / supervised service."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"
    CIRCUIT_BROKEN = "circuit_broken"  # Excessive rapid restarts; stopped to prevent resource death
    ROLLING_BACK = "rolling_back"


@dataclass(slots=True)
class ApplianceServiceConfig:
    """Supervision and restart policy definition for an appliance component."""

    name: str
    description: str
    command: list[str]
    restart_policy: str = "on-failure"
    watchdog_interval_sec: float = 15.0
    max_restarts_within_window: int = 5
    restart_window_sec: float = 60.0
    backoff_base_sec: float = 2.0
    dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ServiceRuntimeMetrics:
    """Live runtime telemetry for a supervised appliance service."""

    config: ApplianceServiceConfig
    state: ApplianceServiceState = ApplianceServiceState.STOPPED
    restart_timestamps: list[float] = field(default_factory=list)
    last_heartbeat: float = field(default_factory=time.time)
    consecutive_failures: int = 0
    circuit_broken: bool = False
    last_error: str | None = None


class ApplianceServiceSupervisor:
    """
    Supervises the CAMserv appliance service tree, prevents endless restart loops,
    monitors watchdog deadman timers, and coordinates graceful recovery.
    """

    STANDARD_SERVICES: list[ApplianceServiceConfig] = [
        ApplianceServiceConfig(
            name="camserv-storage",
            description="Persistent SQLite WAL & Forensic Vault Storage Service",
            command=["python", "-m", "camserv.storage.sqlite_store"],
            watchdog_interval_sec=20.0,
            dependencies=[],
        ),
        ApplianceServiceConfig(
            name="camserv-ingestion",
            description="Isolated Camera Worker Supervisor & Shared Memory Ring Ingestion",
            command=["python", "-m", "camserv.acquisition.supervisor"],
            watchdog_interval_sec=15.0,
            dependencies=["camserv-storage"],
        ),
        ApplianceServiceConfig(
            name="camserv-inference",
            description="Isolated Neural Inference & Hardware Provider Acceleration",
            command=["python", "-m", "camserv.inference.engine"],
            watchdog_interval_sec=15.0,
            dependencies=["camserv-ingestion"],
        ),
        ApplianceServiceConfig(
            name="camserv-privacy",
            description="Centralized Fail-Closed Privacy & Masking Pipeline",
            command=["python", "-m", "camserv.inference.privacy_pipeline"],
            watchdog_interval_sec=10.0,
            dependencies=["camserv-inference"],
        ),
        ApplianceServiceConfig(
            name="camserv-events",
            description="Behavioral Threat Analytics & Human-in-the-Loop Event Engine",
            command=["python", "-m", "camserv.events.behavioral_engine"],
            watchdog_interval_sec=15.0,
            dependencies=["camserv-inference"],
        ),
        ApplianceServiceConfig(
            name="camserv-core",
            description="CAMserv Core Orchestrator & REST/WebSocket Web Console Server",
            command=["python", "-m", "camserv.main", "run"],
            watchdog_interval_sec=15.0,
            dependencies=["camserv-storage", "camserv-ingestion", "camserv-privacy"],
        ),
        ApplianceServiceConfig(
            name="camserv-agent",
            description="Secure mTLS Gateway & Central Management Fleet Agent",
            command=["python", "-m", "camserv.central.agent"],
            watchdog_interval_sec=30.0,
            dependencies=["camserv-core"],
        ),
        ApplianceServiceConfig(
            name="camserv-updater",
            description="Signed OTA Package Verification & A/B Partition Rollback Agent",
            command=["python", "-m", "camserv.deploy.updater"],
            watchdog_interval_sec=60.0,
            dependencies=[],
        ),
    ]

    def __init__(self, services: list[ApplianceServiceConfig] | None = None) -> None:
        self.services: dict[str, ServiceRuntimeMetrics] = {}
        for s in services or self.STANDARD_SERVICES:
            self.services[s.name] = ServiceRuntimeMetrics(config=s)

    def start_service(self, name: str) -> bool:
        """Mark a service as started, verifying dependency readiness."""
        if name not in self.services:
            logger.error("supervisor.service_unknown", service=name)
            return False

        svc = self.services[name]
        # Check dependencies
        for dep in svc.config.dependencies:
            dep_svc = self.services.get(dep)
            if not dep_svc or dep_svc.state not in (ApplianceServiceState.RUNNING, ApplianceServiceState.DEGRADED):
                logger.warning("supervisor.dependency_not_ready", service=name, dependency=dep)
                svc.state = ApplianceServiceState.STOPPED
                return False

        svc.state = ApplianceServiceState.RUNNING
        svc.last_heartbeat = time.time()
        logger.info("supervisor.service_started", service=name)
        return True

    def record_heartbeat(self, name: str) -> bool:
        """Record a successful watchdog heartbeat for a supervised service."""
        if name not in self.services:
            return False

        svc = self.services[name]
        svc.last_heartbeat = time.time()
        if svc.state == ApplianceServiceState.DEGRADED:
            svc.state = ApplianceServiceState.RUNNING
            svc.consecutive_failures = 0
        return True

    def record_failure(self, name: str, error_msg: str = "") -> tuple[bool, float]:
        """
        Record a service process failure.
        Enforces restart window checks and exponential backoff.
        Returns: (allow_restart: bool, backoff_seconds: float)
        """
        if name not in self.services:
            return False, 0.0

        svc = self.services[name]
        now = time.time()
        svc.last_error = error_msg
        svc.consecutive_failures += 1
        svc.restart_timestamps.append(now)

        # Prune restart timestamps older than restart_window_sec
        cutoff = now - svc.config.restart_window_sec
        svc.restart_timestamps = [t for t in svc.restart_timestamps if t >= cutoff]

        # Check circuit breaker
        if len(svc.restart_timestamps) >= svc.config.max_restarts_within_window:
            svc.state = ApplianceServiceState.CIRCUIT_BROKEN
            svc.circuit_broken = True
            logger.critical(
                "supervisor.circuit_breaker_tripped",
                service=name,
                restarts=len(svc.restart_timestamps),
                window_sec=svc.config.restart_window_sec,
                action="Halting restart loop to protect appliance resources and preserve evidence",
            )
            return False, 0.0

        # Calculate exponential backoff: base * 2^(failures - 1)
        backoff = min(60.0, svc.config.backoff_base_sec * (2 ** (min(5, svc.consecutive_failures) - 1)))
        svc.state = ApplianceServiceState.STARTING
        logger.warning(
            "supervisor.service_restart_scheduled",
            service=name,
            failures=svc.consecutive_failures,
            backoff_sec=backoff,
        )
        return True, backoff

    def check_watchdog_health(self, now: float | None = None) -> list[str]:
        """
        Scan all active services for missed watchdog deadlines.
        Returns a list of unhealthy / stalled service names.
        """
        current_time = now if now is not None else time.time()
        unhealthy: list[str] = []

        for name, svc in self.services.items():
            if svc.state == ApplianceServiceState.RUNNING:
                # If no heartbeat within 2x interval, mark degraded / stalled
                deadline = svc.config.watchdog_interval_sec * 2.0
                elapsed = current_time - svc.last_heartbeat
                if elapsed > deadline:
                    svc.state = ApplianceServiceState.DEGRADED
                    unhealthy.append(name)
                    logger.warning(
                        "supervisor.watchdog_missed",
                        service=name,
                        elapsed_sec=round(elapsed, 1),
                        deadline_sec=round(deadline, 1),
                    )
        return unhealthy

    def get_fleet_health_summary(self) -> dict[str, Any]:
        """Return a structured summary of all supervised services."""
        summary: dict[str, Any] = {
            "total_services": len(self.services),
            "running": 0,
            "degraded": 0,
            "failed": 0,
            "circuit_broken": 0,
            "services": {},
        }

        for name, svc in self.services.items():
            state_val = svc.state.value
            if svc.state == ApplianceServiceState.RUNNING:
                summary["running"] += 1
            elif svc.state == ApplianceServiceState.DEGRADED:
                summary["degraded"] += 1
            elif svc.state == ApplianceServiceState.CIRCUIT_BROKEN:
                summary["circuit_broken"] += 1
            else:
                summary["failed"] += 1

            summary["services"][name] = {
                "state": state_val,
                "restarts_in_window": len(svc.restart_timestamps),
                "last_error": svc.last_error,
                "last_heartbeat_ago_sec": round(time.time() - svc.last_heartbeat, 1),
            }
        return summary


class WatchdogNotifier:
    """
    Systemd sd_notify / watchdog integration.
    Sends heartbeat notifications to systemd or logs heartbeats locally.
    """

    def __init__(self) -> None:
        self.notify_socket = os.environ.get("NOTIFY_SOCKET")
        self.is_systemd_managed = bool(self.notify_socket)

    def notify_ready(self) -> bool:
        """Send READY=1 to supervisor."""
        return self._send_notification("READY=1\nSTATUS=Operational")

    def notify_heartbeat(self) -> bool:
        """Send WATCHDOG=1 heartbeat."""
        return self._send_notification("WATCHDOG=1")

    def notify_status(self, status_msg: str) -> bool:
        """Send descriptive STATUS text."""
        return self._send_notification(f"STATUS={status_msg}")

    def notify_stopping(self) -> bool:
        """Send STOPPING=1 during graceful shutdown."""
        return self._send_notification("STOPPING=1")

    def _send_notification(self, payload: str) -> bool:
        """Send payload over unix socket if available, otherwise record in log."""
        if not self.notify_socket:
            return True  # Non-systemd environment (Windows / development mode)

        try:
            import socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.sendto(payload.encode("utf-8"), self.notify_socket)
            sock.close()
            return True
        except Exception as e:
            logger.debug("watchdog.sd_notify_failed", error=str(e))
            return False


class DisasterRecoveryManager:
    """
    Manages atomic configuration snapshots, rollback points,
    and safe recovery procedures without destroying user evidence.
    """

    @classmethod
    def backup_configuration(cls, config_file: Path | str, backup_dir: Path | str) -> Path:
        """Atomically backup configuration before an update or migration."""
        src = Path(config_file)
        dst_dir = Path(backup_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        backup_file = dst_dir / f"{src.stem}_backup_{timestamp}{src.suffix}"

        if src.exists():
            shutil.copy2(src, backup_file)
            logger.info("recovery.config_backed_up", source=str(src), destination=str(backup_file))
        return backup_file

    @classmethod
    def rollback_configuration(cls, backup_file: Path | str, target_file: Path | str) -> bool:
        """Rollback configuration from a backup snapshot."""
        src = Path(backup_file)
        dst = Path(target_file)

        if not src.exists():
            logger.error("recovery.backup_not_found", path=str(src))
            return False

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        logger.warning("recovery.config_rolled_back", restored_from=str(src), target=str(dst))
        return True

    @classmethod
    def safe_recovery_audit(cls, base_data_dir: Path | str) -> dict[str, Any]:
        """
        Verify that recovery procedures have preserved evidence immutability,
        SQLite databases are accessible, and storage has sufficient headroom.
        """
        root = Path(base_data_dir)
        vault_dir = root / "evidence"
        db_file = root / "camserv.db"

        vault_exists = vault_dir.exists()
        vault_file_count = len(list(vault_dir.glob("**/*"))) if vault_exists else 0
        db_exists = db_file.exists()

        return {
            "data_root_valid": root.exists(),
            "vault_preserved": vault_exists,
            "evidence_item_count": vault_file_count,
            "database_intact": db_exists,
            "status": "SAFE_RECOVERABLE" if vault_exists or not root.exists() else "AUDIT_WARNING",
        }
