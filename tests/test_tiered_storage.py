"""
tests.test_tiered_storage
=========================

Unit tests for CAMserv storage and evidence infrastructure:
database schema migration manager, tiered storage engine, automated retention purging,
judicial hold preservation, and court-admissible evidence export packaging.
"""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv.storage.migrations import Migration, MigrationError, MigrationManager
from camserv.storage.tiered_storage import (
    ExportAuthorizationError,
    RetentionPolicy,
    StorageTier,
    TieredStorageManager,
)


def test_migration_manager_forward_and_rollback(tmp_path: Path):
    """Verify forward schema migrations, version tracking, and atomic rollback."""
    db_file = tmp_path / "test_migration.db"
    manager = MigrationManager(db_file)

    # Register Migration 1
    m1 = Migration(
        version=1,
        name="create_tenants_table",
        up_sql="CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT);",
        down_sql="DROP TABLE tenants;",
    )
    # Register Migration 2
    m2 = Migration(
        version=2,
        name="create_sites_table",
        up_sql="CREATE TABLE sites (id TEXT PRIMARY KEY, tenant_id TEXT, name TEXT);",
        down_sql="DROP TABLE sites;",
    )
    manager.register_migration(m1)
    manager.register_migration(m2)

    assert manager.get_current_version() == 0

    # Migrate forward to latest
    applied = manager.migrate()
    assert applied == [1, 2]
    assert manager.get_current_version() == 2

    # Rollback to version 1
    reverted = manager.rollback(target_version=1)
    assert reverted == [2]
    assert manager.get_current_version() == 1


def test_migration_checksum_tamper_detection(tmp_path: Path):
    """Verify that modifying a migration's SQL after it was applied is rejected."""
    db_file = tmp_path / "test_tamper.db"
    manager = MigrationManager(db_file)

    m1 = Migration(
        version=1,
        name="create_devices",
        up_sql="CREATE TABLE devices (id TEXT PRIMARY KEY);",
    )
    manager.register_migration(m1)
    manager.migrate()

    # Re-initialize manager with a tampered m1 definition
    tampered_manager = MigrationManager(db_file)
    m1_tampered = Migration(
        version=1,
        name="create_devices",
        up_sql="CREATE TABLE devices (id TEXT PRIMARY KEY, malicious_col TEXT);",
    )
    tampered_manager.register_migration(m1_tampered)

    with pytest.raises(MigrationError, match="modified after being applied"):
        tampered_manager.migrate()


def test_tiered_storage_recording_and_retention_purging(tmp_path: Path):
    """Verify that standard surveillance purges after 48h while judicial holds survive."""
    store = TieredStorageManager(
        base_dir=tmp_path / "storage",
        retention_policy=RetentionPolicy(continuous_retention_hours=48.0, incident_retention_days=30.0),
    )

    t_now = 1000000.0

    # 1. Standard chunk aged 60h (> 48h) -> Should be purged
    store.store_chunk(
        chunk_id="chunk_old_std",
        camera_id="cam1",
        data=b"VIDEO_PAYLOAD_STANDARD_OLD",
        is_incident=False,
        timestamp=t_now - (60.0 * 3600.0),
    )

    # 2. Standard chunk aged 10h (< 48h) -> Preserved
    store.store_chunk(
        chunk_id="chunk_fresh_std",
        camera_id="cam1",
        data=b"VIDEO_PAYLOAD_STANDARD_FRESH",
        is_incident=False,
        timestamp=t_now - (10.0 * 3600.0),
    )

    # 3. Incident chunk aged 15 days (< 30 days) -> Preserved
    store.store_chunk(
        chunk_id="chunk_incident_fresh",
        camera_id="cam1",
        data=b"VIDEO_PAYLOAD_INCIDENT_RECENT",
        is_incident=True,
        timestamp=t_now - (15.0 * 86400.0),
    )

    # 4. Old incident chunk aged 40 days (> 30 days) but with JUDICIAL HOLD -> Preserved!
    hold_chunk = store.store_chunk(
        chunk_id="chunk_incident_hold",
        camera_id="cam1",
        data=b"VIDEO_PAYLOAD_INCIDENT_COURT_HOLD",
        is_incident=True,
        timestamp=t_now - (40.0 * 86400.0),
    )
    store.set_judicial_hold("chunk_incident_hold", hold=True, reason="Court Subpoena #4501", operator_id="legal_lead")

    # Run purge evaluation
    purge_summary = store.evaluate_retention_and_purge(now=t_now)
    assert purge_summary["purged_count"] == 1  # Only chunk_old_std purged
    assert "chunk_old_std" not in store.chunks
    assert "chunk_fresh_std" in store.chunks
    assert "chunk_incident_fresh" in store.chunks
    assert "chunk_incident_hold" in store.chunks


def test_evidence_export_package_dual_quorum_enforcement(tmp_path: Path):
    """Verify evidence packaging and dual-quorum gate for raw pristine visual export."""
    store = TieredStorageManager(base_dir=tmp_path / "storage")

    store.store_chunk(
        chunk_id="inc_99",
        camera_id="cam_main",
        data=b"CRITICAL_INCIDENT_SECURITY_FOOTAGE_BYTES",
        is_incident=True,
    )

    out_zip = tmp_path / "export_test.zip"
    signing_key = ed25519.Ed25519PrivateKey.generate()

    # 1. Attempting raw unmasked export WITHOUT dual quorum MUST raise ExportAuthorizationError
    with pytest.raises(ExportAuthorizationError, match="UNAUTHORIZED EXPORT"):
        store.export_courtroom_evidence_package(
            chunk_id="inc_99",
            output_zip_path=out_zip,
            operator_id="operator_bob",
            include_raw=True,
            dual_quorum_approved=False,
        )

    # 2. Derivative export (without raw) succeeds with single operator
    store.export_courtroom_evidence_package(
        chunk_id="inc_99",
        output_zip_path=out_zip,
        operator_id="operator_bob",
        include_raw=False,
        signing_key=signing_key,
    )
    assert out_zip.exists()
    assert out_zip.stat().st_size > 0

    # 3. Raw export WITH dual quorum approval succeeds
    out_zip_raw = tmp_path / "export_test_raw.zip"
    store.export_courtroom_evidence_package(
        chunk_id="inc_99",
        output_zip_path=out_zip_raw,
        operator_id="investigator_dave",
        include_raw=True,
        dual_quorum_approved=True,
        signing_key=signing_key,
    )
    assert out_zip_raw.exists()
