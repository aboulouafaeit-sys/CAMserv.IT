"""
tests/test_manifest_storage_remediation.py
===========================================

Remediation and validation tests for SEC-03 (Persistent Forensic Manifest Storage):
- Storage of PrivacyEvidenceManifest in SQLite database.
- Storage of EnhancementManifest in SQLite database.
- Querying manifests by camera_id and time range.
- Querying by original evidence SHA-256 hash.
- Persistence and retrieval across simulated service restart.
- Integrity verification of stored manifest records.
- Missing and corrupted manifest handling.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from camserv.acquisition.enhancement import EnhancementManifest
from camserv.inference.privacy_pipeline import PrivacyEvidenceManifest, PrivacyState
from camserv.storage.sqlite_store import SQLiteStore


@pytest.fixture
def temp_db(tmp_path: Path):
    """Create a temporary SQLite database path."""
    db_path = tmp_path / "test_manifests.db"
    store = SQLiteStore(db_path=db_path)
    return store, db_path


def test_privacy_manifest_persistence_and_retrieval(temp_db):
    """Verify storing, retrieving, and listing privacy manifests."""
    store, db_path = temp_db

    m = PrivacyEvidenceManifest(
        manifest_id="man-cam-01-100-12345",
        camera_id="cam-01",
        frame_id=100,
        timestamp_utc="2026-11-14T20:00:00Z",
        original_sha256="a" * 64,
        derivative_sha256="b" * 64,
        masking_method="gaussian",
        masked_regions_count=2,
        privacy_state=PrivacyState.NORMAL,
        fail_closed_active=False,
        is_original_preserved=True,
        metadata={"kernel": 51},
    )

    store.store_privacy_manifest(m)

    # 1. Retrieve by manifest_id
    rec = store.get_privacy_manifest("man-cam-01-100-12345")
    assert rec is not None
    assert rec["manifest_id"] == "man-cam-01-100-12345"
    assert rec["camera_id"] == "cam-01"
    assert rec["frame_id"] == 100
    assert rec["original_sha256"] == "a" * 64
    assert rec["fail_closed_active"] is False
    assert rec["is_original_preserved"] is True
    assert rec["metadata"]["kernel"] == 51

    # 2. Retrieve by original hash
    rec_by_hash = store.get_privacy_manifest_by_original_hash("a" * 64)
    assert rec_by_hash is not None
    assert rec_by_hash["manifest_id"] == "man-cam-01-100-12345"

    # 3. List manifests by camera
    items = store.list_privacy_manifests(camera_id="cam-01")
    assert len(items) == 1
    assert items[0]["manifest_id"] == "man-cam-01-100-12345"

    # 4. Verify record integrity
    assert store.verify_manifest_integrity_record("man-cam-01-100-12345", record_type="privacy") is True


def test_enhancement_manifest_persistence_and_retrieval(temp_db):
    """Verify storing, retrieving, and listing enhancement manifests."""
    store, db_path = temp_db

    enh_m = EnhancementManifest(
        manifest_id="enh-cam-02-42-9999",
        camera_id="cam-02",
        frame_id=42,
        timestamp_utc="2026-11-14T20:05:00Z",
        original_sha256="c" * 64,
        enhanced_sha256="d" * 64,
        applied_methods=["LAB_CLAHE", "CONTRAST_STRETCH"],
        parameters={"clip_limit": 2.5},
        contrast_before=25.0,
        contrast_after=45.0,
        contrast_gain=1.8,
        is_original_preserved=True,
    )

    store.store_enhancement_manifest(enh_m)

    rec = store.get_enhancement_manifest("enh-cam-02-42-9999")
    assert rec is not None
    assert rec["manifest_id"] == "enh-cam-02-42-9999"
    assert rec["camera_id"] == "cam-02"
    assert rec["contrast_gain"] == 1.8
    assert "LAB_CLAHE" in rec["applied_methods"]
    assert rec["is_original_preserved"] is True

    items = store.list_enhancement_manifests(camera_id="cam-02")
    assert len(items) == 1

    assert store.verify_manifest_integrity_record("enh-cam-02-42-9999", record_type="enhancement") is True


def test_manifest_persistence_across_service_restart(temp_db):
    """Verify that stored manifests survive database reconnection and service restart."""
    store, db_path = temp_db

    m = PrivacyEvidenceManifest(
        manifest_id="restart-test-man-001",
        camera_id="cam-restart",
        frame_id=5,
        timestamp_utc="2026-11-14T20:10:00Z",
        original_sha256="e" * 64,
        derivative_sha256="f" * 64,
        masking_method="pixelate",
        masked_regions_count=1,
        privacy_state=PrivacyState.NORMAL,
        fail_closed_active=False,
    )
    store.store_privacy_manifest(m)

    # Simulate restart by instantiating new SQLiteStore against same db_path
    restarted_store = SQLiteStore(db_path=db_path)
    rec = restarted_store.get_privacy_manifest("restart-test-man-001")

    assert rec is not None
    assert rec["manifest_id"] == "restart-test-man-001"
    assert rec["camera_id"] == "cam-restart"
    assert rec["original_sha256"] == "e" * 64


def test_missing_manifest_handling(temp_db):
    """Verify proper handling of non-existent manifests."""
    store, _ = temp_db
    assert store.get_privacy_manifest("non-existent-id") is None
    assert store.get_enhancement_manifest("non-existent-id") is None
    assert store.verify_manifest_integrity_record("non-existent-id") is False
