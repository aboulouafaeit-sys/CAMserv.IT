"""Tests for camserv.storage.sqlite_store."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pytest

from camserv.pipeline.interfaces import Event, EventSeverity
from camserv.security.auth import Role
from camserv.storage.sqlite_store import SQLiteStore


@pytest.fixture
def temp_sqlite_store(tmp_path: Path) -> SQLiteStore:
    """Fixture providing an isolated SQLiteStore."""
    db_file = tmp_path / "test_camserv.db"
    return SQLiteStore(db_path=db_file)


@pytest.mark.unit
def test_camera_crud_lifecycle(temp_sqlite_store: SQLiteStore) -> None:
    """Test full create, read, update, list, and delete lifecycle for cameras."""
    cam = {
        "id": "cam-test-01",
        "name": "North Gate Test",
        "url": "rtsp://192.168.1.50:554/live",
        "enabled": True,
        "fps": 20,
        "width": 1920,
        "height": 1080,
        "privacy_zones": [{"name": "Zone A", "points": [[0, 0], [100, 100]]}],
    }

    # Insert
    temp_sqlite_store.upsert_camera(cam)

    # Read
    retrieved = temp_sqlite_store.get_camera("cam-test-01")
    assert retrieved is not None
    assert retrieved["name"] == "North Gate Test"
    assert retrieved["fps"] == 20
    assert len(retrieved["privacy_zones"]) == 1

    # Update
    cam["name"] = "North Gate Updated"
    temp_sqlite_store.upsert_camera(cam)
    updated = temp_sqlite_store.get_camera("cam-test-01")
    assert updated is not None
    assert updated["name"] == "North Gate Updated"

    # List
    all_cams = temp_sqlite_store.list_cameras()
    assert len(all_cams) == 1

    # Delete
    deleted = temp_sqlite_store.delete_camera("cam-test-01")
    assert deleted is True
    assert temp_sqlite_store.get_camera("cam-test-01") is None


@pytest.mark.unit
def test_event_persistence_and_verification(temp_sqlite_store: SQLiteStore) -> None:
    """Test event recording and human verification state updates."""
    ev = Event(
        event_id="evt_test_001",
        event_type="zone_intrusion",
        severity=EventSeverity.CRITICAL,
        confidence=0.91,
        camera_id="cam-01",
        timestamp=datetime.now(timezone.utc),
        requires_verification=True,
        description="Perimeter breach detected",
        metadata={
            "reasoning_trace": "Track crossed perimeter boundary at 21:00 UTC",
            "supporting_observations": [{"frame_id": 1, "desc": "Footage match"}],
        },
    )

    temp_sqlite_store.store_event(ev)

    events = temp_sqlite_store.query_events(camera_id="cam-01")
    assert len(events) == 1
    assert events[0]["event_id"] == "evt_test_001"
    assert events[0]["verification_status"] == "pending"
    assert events[0]["requires_verification"] is True

    # Human operator verifies event
    ok = temp_sqlite_store.verify_event(
        event_id="evt_test_001",
        verified_by="security_analyst_01",
        status="verified",
        notes="Confirmed breach via secondary sensor",
    )
    assert ok is True

    updated_events = temp_sqlite_store.query_events(camera_id="cam-01", status="verified")
    assert len(updated_events) == 1
    assert updated_events[0]["verified_by"] == "security_analyst_01"
    assert updated_events[0]["notes"] == "Confirmed breach via secondary sensor"


@pytest.mark.unit
def test_user_management(temp_sqlite_store: SQLiteStore) -> None:
    """Test user account upsert and role persistence."""
    temp_sqlite_store.upsert_user("operator_bob", "hashed_secret_pw", Role.OPERATOR)
    user = temp_sqlite_store.get_user("operator_bob")
    assert user is not None
    assert user["role"] == "operator"
    assert user["password_hash"] == "hashed_secret_pw"
