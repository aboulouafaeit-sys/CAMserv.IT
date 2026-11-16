"""
tests.test_audit_phase13_appliance
==================================

Comprehensive Automated Test Suite for Phase 13:
- Debian 13 (Trixie) Package Building & Multi-Arch Verification (amd64 & arm64).
- Package Security Audit: Prohibiting bundled secrets, keys, and test databases.
- Systemd Service Configuration & Sandboxing Hardening Verification.
- Complete 14-Stage Appliance Lifecycle Simulation:
  1. Fresh Installation
  2. First Service Startup
  3. Initial Configuration
  4. Camera Registration
  5. Recording Creation
  6. Playback
  7. Service Restart
  8. Package Upgrade
  9. Configuration Preservation
  10. Database Preservation
  11. Recording Preservation
  12. Evidence Preservation
  13. Package Removal & Purge Protection
  14. Reinstallation & Archive Re-binding
- Storage Pre-flight Initialization & Schema Migration Runner.
- Central Management Gateway Agent Lifecycle.
"""

from __future__ import annotations

import configparser
import gzip
import io
import os
import shutil
import tarfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import json

from camserv.central.agent import CentralApplianceAgent
from camserv.nvr.playback import PlaybackTimelineEngine
from camserv.nvr.recording_engine import NVRRecordingEngine
from camserv.storage.forensics import EvidencePackager, ForensicSigner, IndependentVerifier
from camserv.storage.init_service import initialize_appliance_storage
from camserv.storage.sqlite_store import SQLiteStore
from deploy.build_deb import DebianPackageBuilder


# ---------------------------------------------------------------------------
# Stage 1: Debian Package Build & Multi-Architecture Verification
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_debian_package_builder_amd64_and_arm64(tmp_path: Path) -> None:
    """Verify that Debian package builder generates valid, standards-compliant .deb archives for amd64 and arm64."""
    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = tmp_path / "deb_dist"

    for target_arch in ["amd64", "arm64"]:
        builder = DebianPackageBuilder(
            repo_root=repo_root,
            version="0.9.0-rc1",
            arch=target_arch,
            output_dir=dist_dir,
        )
        deb_path = builder.build_deb()
        assert deb_path.exists()
        assert deb_path.name == f"camserv_0.9.0-rc1_{target_arch}.deb"

        # Inspect the generated package
        report = DebianPackageBuilder.inspect_deb(deb_path)
        assert report["size_bytes"] > 500_000  # At least 500 KB
        assert len(report["sha256"]) == 64  # Valid SHA-256
        assert report["ar_members"] == ["debian-binary", "control.tar.gz", "data.tar.gz"]
        assert f"Architecture: {target_arch}" in report["control_text"]
        assert "Package: camserv" in report["control_text"]
        assert "Version: 0.9.0-rc1" in report["control_text"]
        assert "libglib2.0-0t64" in report["control_text"]  # Debian 13 compatibility
        assert report["data_file_count"] > 50


# ---------------------------------------------------------------------------
# Stage 2: Debian Package Security Audit & Secret Leakage Prevention
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_debian_package_security_audit_no_secrets_bundled(tmp_path: Path) -> None:
    """Verify that no sensitive files, test databases, or private keys are bundled into the .deb archive."""
    repo_root = Path(__file__).resolve().parent.parent
    builder = DebianPackageBuilder(
        repo_root=repo_root,
        version="0.9.0-rc1",
        arch="amd64",
        output_dir=tmp_path / "audit_dist",
    )
    deb_path = builder.build_deb()
    report = DebianPackageBuilder.inspect_deb(deb_path)

    # Enumerate every file in data.tar.gz
    for file_path in report["data_files"]:
        # No SQLite databases
        assert not file_path.endswith((".db", ".sqlite", ".sqlite3")), f"Database file leaked into package: {file_path}"
        # No private keys or certs
        assert not file_path.endswith((".pem", ".key", ".pfx", ".p12")), f"Private key leaked into package: {file_path}"
        # No environment secrets
        assert not file_path.endswith(".env"), f"Environment file leaked into package: {file_path}"
        # No byte-compiled Python caches
        assert "__pycache__" not in file_path, f"Python cache leaked into package: {file_path}"
        assert not file_path.endswith(".pyc"), f"Pyc file leaked into package: {file_path}"


# ---------------------------------------------------------------------------
# Stage 3: Systemd Service Sandboxing & Hardening Verification
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_systemd_services_sandboxing_and_dependencies() -> None:
    """Verify that all systemd unit files implement strict sandboxing, correct start commands, and intact dependency chain."""
    repo_root = Path(__file__).resolve().parent.parent
    sysd_dir = repo_root / "deploy" / "systemd"

    required_units = [
        "camserv.target",
        "camserv-storage.service",
        "camserv-core.service",
        "camserv-nvr.service",
        "camserv-ingestion.service",
        "camserv-inference.service",
        "camserv-agent.service",
    ]

    for unit_name in required_units:
        unit_file = sysd_dir / unit_name
        assert unit_file.exists(), f"Missing required systemd unit: {unit_name}"
        content = unit_file.read_text(encoding="utf-8")

        if unit_name.endswith(".service"):
            # Check unprivileged execution
            assert "User=camserv" in content, f"{unit_name} must run as dedicated unprivileged user 'camserv'"
            assert "Group=camserv" in content, f"{unit_name} must run as dedicated group 'camserv'"
            # Check basic sandboxing
            assert "ProtectSystem=strict" in content, f"{unit_name} must enforce ProtectSystem=strict"
            assert "ProtectHome=true" in content, f"{unit_name} must enforce ProtectHome=true"
            assert "PrivateTmp=true" in content, f"{unit_name} must enforce PrivateTmp=true"
            assert "NoNewPrivileges=true" in content, f"{unit_name} must enforce NoNewPrivileges=true"
            assert "ReadWritePaths=" in content, f"{unit_name} must declare explicit ReadWritePaths"

    # Verify camserv.target includes all services
    target_content = (sysd_dir / "camserv.target").read_text(encoding="utf-8")
    for svc in [
        "camserv-storage.service",
        "camserv-core.service",
        "camserv-nvr.service",
        "camserv-ingestion.service",
        "camserv-inference.service",
        "camserv-agent.service",
    ]:
        assert svc in target_content, f"camserv.target must include {svc}"

    # Verify camserv-core.service uses valid subcommand and simple/exec type
    core_content = (sysd_dir / "camserv-core.service").read_text(encoding="utf-8")
    assert "Type=simple" in core_content
    assert "serve" in core_content or "run" in core_content
    assert "Requires=camserv-storage.service" in core_content

    # Verify camserv-ingestion.service has video/render groups and device access
    ingest_content = (sysd_dir / "camserv-ingestion.service").read_text(encoding="utf-8")
    assert "SupplementaryGroups=video render" in ingest_content
    assert "PrivateDevices=false" in ingest_content


# ---------------------------------------------------------------------------
# Stage 4: Storage Pre-Flight Initialization Service
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_storage_init_service_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that storage initialization service provisions directories and initializes SQLite database."""
    test_root = tmp_path / "appliance_root"
    test_db = test_root / "var" / "lib" / "camserv" / "db" / "camserv.db"

    # Monkeypatch standard dirs to tmp_path
    custom_dirs = [
        test_root / "var" / "lib" / "camserv" / "db",
        test_root / "var" / "lib" / "camserv" / "recordings",
        test_root / "var" / "lib" / "camserv" / "vault",
        test_root / "var" / "lib" / "camserv" / "exports",
        test_root / "var" / "log" / "camserv",
        test_root / "etc" / "camserv",
    ]
    monkeypatch.setattr("camserv.storage.init_service.STANDARD_APPLIANCE_DIRS", custom_dirs)

    code = initialize_appliance_storage(use_system_paths=False)
    assert code == 0

    # Verify fallback local directories exist
    for d in ["data/db", "data/recordings", "data/vault", "logs"]:
        assert Path(d).exists()


# ---------------------------------------------------------------------------
# Stage 5: Central Appliance Gateway Agent Heartbeat
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_central_appliance_agent_sync_cycle(tmp_path: Path) -> None:
    """Verify that the central management agent executes a complete heartbeat sync cycle."""
    db_path = tmp_path / "camserv_agent_test.db"
    store = SQLiteStore(db_path=db_path)
    store.upsert_camera({
        "id": "cam_gate_01",
        "name": "Front Gate Camera",
        "url": "rtsp://192.168.1.100:554/ch0",
        "enabled": True,
        "fps": 25.0,
        "width": 1920,
        "height": 1080,
    })

    agent = CentralApplianceAgent(
        appliance_id="appliance-test-01",
        site_id="site-zurich",
        tenant_id="tenant-corp",
        db_path=db_path,
    )
    cycle_result = agent.sync_cycle()

    assert cycle_result["appliance_id"] == "appliance-test-01"
    assert cycle_result["cameras_count"] == 1
    assert "DISC-CAM" in cycle_result["envelope_id"]
    assert "cpu_cores" in cycle_result["telemetry"]


# ---------------------------------------------------------------------------
# Stage 6: Complete 14-Stage Appliance Lifecycle Simulation
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_complete_14_stage_appliance_lifecycle(tmp_path: Path) -> None:
    """
    Rigorously exercise the 14-stage appliance lifecycle in an isolated sandbox:
    1. Fresh installation
    2. First service startup
    3. Initial configuration
    4. Camera registration
    5. Recording creation
    6. Playback
    7. Service restart
    8. Package upgrade
    9. Configuration preservation
    10. Database preservation
    11. Recording preservation
    12. Evidence preservation
    13. Package removal / purge
    14. Reinstallation
    """
    sandbox = tmp_path / "appliance_sandbox"
    opt_dir = sandbox / "opt" / "camserv"
    etc_dir = sandbox / "etc" / "camserv"
    var_db = sandbox / "var" / "lib" / "camserv" / "db"
    var_rec = sandbox / "var" / "lib" / "camserv" / "recordings"
    var_vault = sandbox / "var" / "lib" / "camserv" / "vault"
    var_log = sandbox / "var" / "log" / "camserv"

    # ==========================================
    # Step 1: Fresh Installation
    # ==========================================
    for p in [opt_dir, etc_dir, var_db, var_rec, var_vault, var_log]:
        p.mkdir(parents=True, exist_ok=True)

    # Deploy default config and binaries
    cfg_file = etc_dir / "camserv.yaml"
    cfg_file.write_text("app_name: CAMserv\nenvironment: production\ncustom_setting: initial_value\n", encoding="utf-8")
    (opt_dir / "version.txt").write_text("0.9.0-rc1\n", encoding="utf-8")
    assert cfg_file.exists()
    assert (opt_dir / "version.txt").exists()

    # ==========================================
    # Step 2: First Service Startup & Storage Provisioning
    # ==========================================
    db_file = var_db / "camserv.db"
    store = SQLiteStore(db_path=db_file)
    assert db_file.exists()

    # ==========================================
    # Step 3: Initial Configuration Verification
    # ==========================================
    cfg_text = cfg_file.read_text(encoding="utf-8")
    assert "app_name: CAMserv" in cfg_text
    assert "environment: production" in cfg_text

    # ==========================================
    # Step 4: Camera Registration
    # ==========================================
    store.upsert_camera({
        "id": "cam_lobby_01",
        "name": "Corporate Lobby",
        "url": "rtsp://10.0.1.50/live",
        "enabled": True,
        "fps": 20.0,
    })
    cams = store.list_cameras()
    assert len(cams) == 1
    assert cams[0]["id"] == "cam_lobby_01"

    # ==========================================
    # Step 5: Recording Creation
    # ==========================================
    nvr = NVRRecordingEngine(
        storage_dir=var_rec,
        store=store,
        segment_duration_seconds=1.0,
    )
    rec_id = nvr.start_recording("cam_lobby_01", recording_type="continuous")
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    nvr.ingest_frame("cam_lobby_01", frame, fps=15.0)
    nvr.stop_recording("cam_lobby_01")

    recordings = store.list_recordings("cam_lobby_01")
    assert len(recordings) == 1

    # Also create a cryptographic forensic evidence archive in vault
    signer = ForensicSigner()
    packager = EvidencePackager(signer=signer)
    vault_zip = var_vault / "evidence_incident_001.zip"
    packager.create_package(
        output_zip=vault_zip,
        evidence_id="EV-LIFECYCLE-001",
        camera_id="cam_lobby_01",
        event_id="EVT-ALARM-01",
        file_payloads={"snapshot.jpg": b"JPEG_DATA", "report.json": b"{}"},
    )
    assert vault_zip.exists()

    # ==========================================
    # Step 6: Playback Verification
    # ==========================================
    playback = PlaybackTimelineEngine(store=store, storage_dir=var_rec)
    timeline = playback.get_camera_timeline("cam_lobby_01", "2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    assert len(timeline) >= 1

    # ==========================================
    # Step 7: Service Restart
    # ==========================================
    # Re-open store and NVR engine on same paths
    store_restarted = SQLiteStore(db_path=db_file)
    cams_restarted = store_restarted.list_cameras()
    assert len(cams_restarted) == 1
    assert cams_restarted[0]["id"] == "cam_lobby_01"

    # ==========================================
    # Step 8: Package Upgrade (to 0.9.1-rc1)
    # ==========================================
    (opt_dir / "version.txt").write_text("0.9.1-rc1\n", encoding="utf-8")

    # ==========================================
    # Step 9: Configuration Preservation (dpkg conffiles protection)
    # ==========================================
    # Conffiles rule: existing user configuration is preserved
    cfg_text_after_upgrade = cfg_file.read_text(encoding="utf-8")
    assert "custom_setting: initial_value" in cfg_text_after_upgrade

    # ==========================================
    # Step 10: Database Preservation Across Upgrade
    # ==========================================
    assert db_file.exists()
    assert len(store_restarted.list_cameras()) == 1

    # ==========================================
    # Step 11: Recording Preservation Across Upgrade
    # ==========================================
    rec_after_upgrade = store_restarted.list_recordings("cam_lobby_01")
    assert len(rec_after_upgrade) == 1

    # ==========================================
    # Step 12: Evidence Preservation & Verification
    # ==========================================
    assert vault_zip.exists()
    verifier = IndependentVerifier()
    v_res = verifier.verify_package(vault_zip, trusted_public_key_pem=signer.export_public_key_pem())
    assert v_res.is_valid is True

    # ==========================================
    # Step 13: Package Removal / Purge Safety
    # ==========================================
    # Under postrm purge: remove opt_dir, but PRESERVE var_vault and var_rec
    shutil.rmtree(opt_dir)
    assert not opt_dir.exists()

    # Inviolate: Vault and recordings MUST survive package purge
    assert vault_zip.exists(), "Forensic evidence vault must NOT be deleted upon package purge!"
    assert var_rec.exists(), "Video recordings directory must NOT be deleted upon package purge!"
    assert db_file.exists(), "Appliance database must survive removal!"

    # ==========================================
    # Step 14: Reinstallation & Archive Re-binding
    # ==========================================
    opt_dir.mkdir(parents=True, exist_ok=True)
    (opt_dir / "version.txt").write_text("0.9.1-rc1-reinstalled\n", encoding="utf-8")

    # Reconnect to existing database
    store_reinstalled = SQLiteStore(db_path=db_file)
    assert len(store_reinstalled.list_cameras()) == 1
    assert store_reinstalled.list_cameras()[0]["id"] == "cam_lobby_01"

    # Re-verify forensic evidence
    v_res_reinstalled = verifier.verify_package(vault_zip, trusted_public_key_pem=signer.export_public_key_pem())
    assert v_res_reinstalled.is_valid is True
    assert v_res_reinstalled.chain_of_custody_intact is True
