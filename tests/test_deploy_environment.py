"""
tests.test_deploy_environment
=============================

Unit and integration tests for CAMserv dedicated appliance operating environment:
service supervision, restart circuit breaker, watchdog monitoring, disaster recovery,
and systemd unit configurations.
"""

from pathlib import Path

import pytest

from camserv.deploy.supervisor import (
    ApplianceServiceConfig,
    ApplianceServiceState,
    ApplianceServiceSupervisor,
    DisasterRecoveryManager,
    WatchdogNotifier,
)


def test_supervisor_initialization_and_dependencies():
    """Verify standard service registration and dependency enforcement."""
    supervisor = ApplianceServiceSupervisor()
    assert len(supervisor.services) >= 7

    # camserv-core requires camserv-storage and camserv-ingestion
    core_started = supervisor.start_service("camserv-core")
    assert core_started is False  # Fails because dependencies are not started yet

    # Start storage first, then ingestion, then core
    assert supervisor.start_service("camserv-storage") is True
    assert supervisor.start_service("camserv-ingestion") is True
    assert supervisor.start_service("camserv-inference") is True
    assert supervisor.start_service("camserv-privacy") is True
    assert supervisor.start_service("camserv-core") is True

    summary = supervisor.get_fleet_health_summary()
    assert summary["running"] == 5


def test_watchdog_heartbeat_and_deadman_timer():
    """Verify watchdog heartbeat recording and deadman timer expiration."""
    supervisor = ApplianceServiceSupervisor()
    supervisor.start_service("camserv-storage")

    # Immediate check should report zero unhealthy
    unhealthy = supervisor.check_watchdog_health(now=100.0)
    # Simulate time jumping forward past 2x watchdog interval (watchdog=20s -> deadline=40s)
    supervisor.services["camserv-storage"].last_heartbeat = 100.0
    unhealthy = supervisor.check_watchdog_health(now=150.0)
    assert "camserv-storage" in unhealthy
    assert supervisor.services["camserv-storage"].state == ApplianceServiceState.DEGRADED

    # Refresh heartbeat restores running state
    supervisor.record_heartbeat("camserv-storage")
    assert supervisor.services["camserv-storage"].state == ApplianceServiceState.RUNNING


def test_restart_circuit_breaker_prevents_endless_loop():
    """Verify that rapid repeated crashes trip the circuit breaker."""
    cfg = ApplianceServiceConfig(
        name="test-worker",
        description="Crashing Worker",
        command=["python", "worker.py"],
        max_restarts_within_window=3,
        restart_window_sec=10.0,
        backoff_base_sec=1.0,
    )
    supervisor = ApplianceServiceSupervisor(services=[cfg])
    supervisor.start_service("test-worker")

    # Failure 1
    allow1, backoff1 = supervisor.record_failure("test-worker", "Crash 1")
    assert allow1 is True
    assert backoff1 == 1.0

    # Failure 2
    allow2, backoff2 = supervisor.record_failure("test-worker", "Crash 2")
    assert allow2 is True
    assert backoff2 == 2.0

    # Failure 3 -> Trips circuit breaker!
    allow3, backoff3 = supervisor.record_failure("test-worker", "Crash 3")
    assert allow3 is False
    assert supervisor.services["test-worker"].state == ApplianceServiceState.CIRCUIT_BROKEN
    assert supervisor.services["test-worker"].circuit_broken is True


def test_disaster_recovery_config_backup_and_audit(tmp_path: Path):
    """Verify atomic configuration backup, rollback, and evidence preservation audit."""
    conf_dir = tmp_path / "conf"
    backup_dir = tmp_path / "backup"
    data_dir = tmp_path / "data"
    conf_dir.mkdir()
    data_dir.mkdir()
    (data_dir / "evidence").mkdir()

    # Create dummy config and evidence
    test_conf = conf_dir / "settings.yaml"
    test_conf.write_text("environment: production\nversion: 1.0.0", encoding="utf-8")
    (data_dir / "evidence" / "incident_001.vault").write_bytes(b"\x00" * 64)
    (data_dir / "camserv.db").write_bytes(b"\x00" * 32)

    # Backup config
    backup_path = DisasterRecoveryManager.backup_configuration(test_conf, backup_dir)
    assert backup_path.exists()

    # Modify config and rollback
    test_conf.write_text("environment: corrupted", encoding="utf-8")
    restored = DisasterRecoveryManager.rollback_configuration(backup_path, test_conf)
    assert restored is True
    assert "environment: production" in test_conf.read_text(encoding="utf-8")

    # Audit preservation of evidence
    audit = DisasterRecoveryManager.safe_recovery_audit(data_dir)
    assert audit["vault_preserved"] is True
    assert audit["evidence_item_count"] == 1
    assert audit["database_intact"] is True
    assert audit["status"] == "SAFE_RECOVERABLE"


def test_systemd_unit_templates_validation():
    """Verify that systemd service unit templates are valid and contain hardening flags."""
    systemd_dir = Path("deploy/systemd")
    assert systemd_dir.exists()

    core_unit = (systemd_dir / "camserv-core.service").read_text(encoding="utf-8")
    assert "[Unit]" in core_unit
    assert "[Service]" in core_unit
    assert "[Install]" in core_unit
    assert "ProtectSystem=strict" in core_unit
    assert "WatchdogSec=15s" in core_unit
    assert "Restart=on-failure" in core_unit

    ingest_unit = (systemd_dir / "camserv-ingestion.service").read_text(encoding="utf-8")
    assert "ReadWritePaths=/dev/shm" in ingest_unit
    assert "WatchdogSec=15s" in ingest_unit
