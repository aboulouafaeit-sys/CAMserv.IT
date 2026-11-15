"""
Integration tests for CAMserv NVR, streaming, PTZ, groups, and analytics REST endpoints.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from camserv.api.app import create_app
from camserv.config.settings import get_settings
from camserv.security.audit import AuditLogger


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = get_settings()
    app = create_app(settings)
    # Direct audit logger to tmp_path to strictly protect production logs/audit.jsonl
    app.state.audit_logger = AuditLogger(log_path=tmp_path / "test_api_audit.jsonl")
    return TestClient(app)


def get_admin_token(client: TestClient) -> str:
    """Helper to acquire valid JWT admin token."""
    res = client.post("/api/v1/auth/token", json={"username": "admin", "password": "admin_password"})
    assert res.status_code == 200
    return res.json()["access_token"]


@pytest.mark.integration
def test_api_camera_groups(client: TestClient) -> None:
    """Test camera group CRUD API endpoints."""
    token = get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Group
    payload = {
        "group_id": "grp_api_test",
        "name": "Perimeter North",
        "description": "Perimeter cameras",
        "camera_ids": ["cam_01", "cam_02"],
        "site_id": "site_hq",
        "tags": ["perimeter", "high_sec"],
    }
    res = client.post("/api/v1/groups", json=payload, headers=headers)
    assert res.status_code == 201
    assert res.json()["name"] == "Perimeter North"

    # 2. List Groups
    res_list = client.get("/api/v1/groups", headers=headers)
    assert res_list.status_code == 200
    groups = res_list.json()
    assert any(g["group_id"] == "grp_api_test" for g in groups)

    # 3. Delete Group
    res_del = client.delete("/api/v1/groups/grp_api_test", headers=headers)
    assert res_del.status_code == 204


@pytest.mark.integration
def test_api_ptz_endpoints(client: TestClient) -> None:
    """Test PTZ capabilities, move, presets, and goto endpoints."""
    token = get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Register camera channel as PTZ capable in app state
    client.app.state.ptz_controller.register_camera_capabilities("cam_dome_api", is_ptz=True)

    # 1. Capabilities
    res_caps = client.get("/api/v1/cameras/cam_dome_api/ptz/capabilities", headers=headers)
    assert res_caps.status_code == 200
    assert res_caps.json()["is_ptz_capable"] is True

    # 2. Move Vector
    res_move = client.post(
        "/api/v1/cameras/cam_dome_api/ptz/move",
        json={"pan": 0.5, "tilt": -0.2, "zoom": 0.1, "timeout_s": 2.0},
        headers=headers,
    )
    assert res_move.status_code == 200
    assert res_move.json()["status"] == "moving"

    # 3. Stop
    res_stop = client.post("/api/v1/cameras/cam_dome_api/ptz/stop", headers=headers)
    assert res_stop.status_code == 200
    assert res_stop.json()["status"] == "stopped"

    # 4. Save and List Presets
    res_preset = client.post(
        "/api/v1/cameras/cam_dome_api/ptz/presets",
        json={"name": "Parking Lot Zoom"},
        headers=headers,
    )
    assert res_preset.status_code == 201
    preset_data = res_preset.json()
    assert preset_data["name"] == "Parking Lot Zoom"

    res_list_pre = client.get("/api/v1/cameras/cam_dome_api/ptz/presets", headers=headers)
    assert res_list_pre.status_code == 200
    assert len(res_list_pre.json()) >= 1

    # 5. Goto Preset
    res_goto = client.post(
        f"/api/v1/cameras/cam_dome_api/ptz/presets/{preset_data['preset_id']}/goto",
        headers=headers,
    )
    assert res_goto.status_code == 200
    assert res_goto.json()["status"] == "recalled"


@pytest.mark.integration
def test_api_streaming_endpoints(client: TestClient) -> None:
    """Test HLS playlist generation and WebRTC SDP offer handshake."""
    cam_id = "cam_live_test"

    # 1. HLS Playlist
    res_hls = client.get(f"/api/v1/stream/{cam_id}/hls/live.m3u8")
    assert res_hls.status_code == 200
    assert "#EXTM3U" in res_hls.text

    # 2. WebRTC Offer Handshake
    offer_payload = {"sdp": "v=0\r\no=- 999 2 IN IP4 127.0.0.1\r\ns=-\r\n"}
    res_rtc = client.post(f"/api/v1/stream/{cam_id}/webrtc/offer", json=offer_payload)
    assert res_rtc.status_code == 200
    assert res_rtc.json()["type"] == "answer"
    assert "m=video" in res_rtc.json()["sdp"]


@pytest.mark.integration
def test_api_analytics_tripwire_and_zone_registration(client: TestClient) -> None:
    """Test tripwire and polygon zone registration via API."""
    token = get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    cam_id = "cam_perimeter"

    # 1. Tripwire
    tw_body = {
        "tripwire_id": "tw_api_01",
        "name": "Fence Line A",
        "start_point": [0.0, 50.0],
        "end_point": [100.0, 50.0],
        "direction": "bidirectional",
    }
    res_tw = client.post(f"/api/v1/analytics/{cam_id}/tripwires", json=tw_body, headers=headers)
    assert res_tw.status_code == 201
    assert res_tw.json()["tripwire_id"] == "tw_api_01"

    # 2. Polygon Zone
    zone_body = {
        "zone_id": "zone_api_01",
        "name": "Secure Vault Perimeter",
        "vertices": [[0.0, 0.0], [50.0, 0.0], [50.0, 50.0], [0.0, 50.0]],
        "loitering_threshold_sec": 15.0,
    }
    res_zone = client.post(f"/api/v1/analytics/{cam_id}/zones", json=zone_body, headers=headers)
    assert res_zone.status_code == 201
    assert res_zone.json()["zone_id"] == "zone_api_01"


@pytest.mark.integration
def test_api_recordings_and_timeline(client: TestClient) -> None:
    """Test recordings list, timeline query, and validation error handling."""
    token = get_admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. List recordings
    res = client.get("/api/v1/recordings", headers=headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # 2. Timeline query (valid window)
    res_time = client.get(
        "/api/v1/recordings/timeline?camera_id=cam_api_01&start_time_utc=2026-11-15T00:00:00Z&end_time_utc=2026-11-15T23:59:59Z",
        headers=headers,
    )
    assert res_time.status_code == 200
    assert res_time.json()["camera_id"] == "cam_api_01"
    assert "spans" in res_time.json()

    # 3. Timeline query with invalid reversed window -> 400 Bad Request
    res_rev = client.get(
        "/api/v1/recordings/timeline?camera_id=cam_api_01&start_time_utc=2026-11-15T23:59:59Z&end_time_utc=2026-11-15T00:00:00Z",
        headers=headers,
    )
    assert res_rev.status_code == 400
    assert "cannot be greater than" in res_rev.json()["detail"]

    # 4. Clipped export for non-existent video -> 404 Not Found
    res_exp = client.post(
        "/api/v1/recordings/export",
        json={
            "camera_id": "cam_nonexistent",
            "start_time_utc": "2026-11-15T10:00:00Z",
            "end_time_utc": "2026-11-15T11:00:00Z",
        },
        headers=headers,
    )
    assert res_exp.status_code == 404
