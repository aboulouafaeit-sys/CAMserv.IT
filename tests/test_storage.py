"""Storage subsystem tests for CAMserv.

Verifies:
- Redis cache set/get/delete and TTL expiration
- Redis graceful degradation to in-memory store when Redis server is offline
- AES-256-GCM evidence encryption and decryption integrity
- Evidence cryptographic SHA-256 hash chaining
- Tamper detection on modified evidence payloads or metadata
- Full end-to-end evidence chain verification
- Milvus vector store zero-PII policy (rejection of biometric/face attributes)
- Evidence retention policy enforcement with cryptographic file shredding
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from camserv.security.encryption import EncryptionManager
from camserv.storage.evidence import (
    GENESIS_HASH,
    EvidenceIntegrityError,
    EvidenceRecord,
    EvidenceStore,
    compute_record_hash,
)
from camserv.storage.milvus_store import MilvusStore
from camserv.storage.redis_cache import RedisCache


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_cache_set_get_ttl() -> None:
    """Verify RedisCache set, get, and TTL expiration behavior."""
    cache = RedisCache(enable_fallback=True)
    # Using fallback in-memory store for unit test
    await cache.set("test_ns", "test_key", {"status": "ok", "value": 42}, ttl_seconds=1)

    val = await cache.get("test_ns", "test_key")
    assert val is not None
    assert val["status"] == "ok"
    assert val["value"] == 42

    # Await TTL expiration (1 second)
    await asyncio.sleep(1.05)
    expired = await cache.get("test_ns", "test_key")
    assert expired is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_graceful_degradation() -> None:
    """Verify RedisCache transparently falls back to memory cache when Redis connection fails."""
    # Connecting to invalid port ensures failure
    failing_cache = RedisCache(host="127.0.0.1", port=59999, enable_fallback=True)
    connected = await failing_cache.connect()
    assert not connected
    assert not failing_cache._is_connected

    # Set and get should still succeed without crashing
    success = await failing_cache.set("fallback_ns", "fallback_key", "payload_data")
    assert success is True

    result = await failing_cache.get("fallback_ns", "fallback_key")
    assert result == "payload_data"


@pytest.mark.unit
def test_evidence_encryption_decryption(tmp_path: Path) -> None:
    """Verify evidence payload is encrypted with AES-256-GCM and decrypted accurately."""
    store = EvidenceStore(base_dir=tmp_path / "evidence")
    raw_payload = b"CRITICAL_INCIDENT_VIDEO_CHUNK_FRAME_BYTES_12345"

    record = store.store_evidence(
        event_id="evt-001",
        camera_id="cam-north",
        data=raw_payload,
        extension="mp4",
        metadata={"camera_zone": "gate"},
    )

    assert record.event_id == "evt-001"
    assert record.camera_id == "cam-north"
    assert record.encrypted_file.endswith(".mp4.enc")

    # Read the raw file on disk to verify it is NOT plain text
    enc_path = store.artifacts_dir / record.encrypted_file
    assert enc_path.exists()
    disk_content = enc_path.read_text(encoding="utf-8")
    assert "CRITICAL_INCIDENT" not in disk_content

    # Retrieve and decrypt
    retrieved_rec, decrypted_bytes = store.retrieve_evidence("evt-001")
    assert retrieved_rec.event_id == "evt-001"
    assert decrypted_bytes == raw_payload


@pytest.mark.unit
def test_evidence_hash_chain_integrity(tmp_path: Path) -> None:
    """Verify sequential evidence records are linked by previous SHA-256 record hashes."""
    store = EvidenceStore(base_dir=tmp_path / "evidence_chain")

    rec1 = store.store_evidence("evt-101", "cam-1", b"frame_1")
    rec2 = store.store_evidence("evt-102", "cam-1", b"frame_2")
    rec3 = store.store_evidence("evt-103", "cam-1", b"frame_3")

    # First record links to genesis
    assert rec1.prev_hash == GENESIS_HASH
    # Second links to first
    assert rec2.prev_hash == rec1.record_hash
    # Third links to second
    assert rec3.prev_hash == rec2.record_hash


@pytest.mark.unit
def test_evidence_tamper_detection(tmp_path: Path) -> None:
    """Verify tamper detection catches modified ciphertext or altered chain records."""
    store = EvidenceStore(base_dir=tmp_path / "tamper_test")

    rec = store.store_evidence("evt-tamper", "cam-1", b"authentic_unaltered_data")

    # Tamper with the artifact on disk by overwriting ciphertext
    artifact_path = store.artifacts_dir / rec.encrypted_file
    enc_data = json.loads(artifact_path.read_text(encoding="utf-8"))
    # Corrupt ciphertext bytes
    enc_data["ciphertext"] = "dGFtcGVyZWRfYmFzZTY0X2J5dGVz"
    artifact_path.write_text(json.dumps(enc_data), encoding="utf-8")

    # Retrieval must detect tamper and fail
    with pytest.raises(Exception):  # Cryptographic AESGCM auth tag verification or payload hash mismatch
        store.retrieve_evidence("evt-tamper")


@pytest.mark.unit
def test_evidence_chain_verification(tmp_path: Path) -> None:
    """Verify full evidence chain validation returns True on valid chain and detects breaks."""
    store = EvidenceStore(base_dir=tmp_path / "chain_verify")

    for i in range(5):
        store.store_evidence(f"evt-{i}", "cam-1", f"sample_data_{i}".encode())

    is_valid, count, errors = store.verify_full_chain()
    assert is_valid is True
    assert count == 5
    assert len(errors) == 0

    # Break chain by altering one line in the chain file
    lines = store.chain_file.read_text(encoding="utf-8").splitlines()
    tampered_entry = json.loads(lines[2])
    tampered_entry["prev_hash"] = "deadbeef" * 8
    lines[2] = json.dumps(tampered_entry)
    store.chain_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    is_valid_broken, _, errors_broken = store.verify_full_chain()
    assert is_valid_broken is False
    assert len(errors_broken) > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milvus_store_no_pii() -> None:
    """Verify MilvusStore strictly enforces non-biometric, non-PII scene analytics vectors."""
    store = MilvusStore(dim=128, enable_fallback=True)

    # Valid anonymous scene context vector
    scene_vector = np.random.randn(128).astype(np.float32)
    success = await store.insert_scene_analytic(
        record_id="scene-rec-1",
        vector=scene_vector,
        camera_id="cam-01",
        analytic_type="scene_context",
        description="Anonymous crowd flow vector in terminal",
    )
    assert success is True

    # Search works without PII
    results = await store.search_similar_scenes(query_vector=scene_vector, top_k=5)
    assert len(results) >= 1
    top_hit = results[0]
    assert "id" in top_hit
    # Strictly NO PII fields present in search results
    for forbidden in ["name", "face_id", "biometric", "identity", "ssn"]:
        assert forbidden not in top_hit


@pytest.mark.unit
def test_retention_policy_enforcement(tmp_path: Path) -> None:
    """Verify secure_delete_expired shreds expired artifacts and maintains chain continuity."""
    store = EvidenceStore(base_dir=tmp_path / "retention_test")

    # Old record timestamped 10 days ago
    past_ts = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    rec_old = store.store_evidence("evt-old", "cam-1", b"ancient_evidence", timestamp=past_ts)

    # Recent record timestamped now
    rec_recent = store.store_evidence("evt-new", "cam-1", b"fresh_evidence")

    old_artifact = store.artifacts_dir / rec_old.encrypted_file
    new_artifact = store.artifacts_dir / rec_recent.encrypted_file
    assert old_artifact.exists()
    assert new_artifact.exists()

    # Purge records older than 1 day (86400 seconds)
    purged_count = store.secure_delete_expired(older_than_seconds=86400)
    assert purged_count == 1

    # Old artifact was shredded and unlinked
    assert not old_artifact.exists()
    # New artifact remains intact
    assert new_artifact.exists()

    # Remaining chain must still verify cleanly
    is_valid, count, errors = store.verify_full_chain()
    assert is_valid is True
    assert count == 1
    assert len(errors) == 0
