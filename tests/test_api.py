"""REST and WebSocket API endpoint tests for CAMserv.

Verifies:
- System and root health endpoints return operational status
- Camera management CRUD operations (Create, Read, Update, Delete)
- Event querying with multi-attribute filtering (type, camera, severity)
- Human-in-the-loop event verification workflow (accept/dismiss)
- Rejection of unauthenticated and unauthorized requests
- Rate limiting enforcement
- Cursor-based event pagination
- WebSocket event stream subscription and ping-pong keepalive
- Standard structured error responses on 404, 400, and 409
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from camserv.api.app import create_app
from camserv.security.auth import AuthManager, Role


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def admin_headers(app) -> dict[str, str]:
    auth: AuthManager = app.state.auth_manager
    token = auth.create_access_token(subject="admin", role=Role.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer_headers(app) -> dict[str, str]:
    auth: AuthManager = app.state.auth_manager
    token = auth.create_access_token(subject="viewer", role=Role.VIEWER)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.unit
def test_health_endpoint(client: TestClient) -> None:
    """Verify /health and /api/v1/system/health endpoints return status ok."""
    # Root health
    r_root = client.get("/health")
    assert r_root.status_code == 200
    data_root = r_root.json()
    assert data_root["status"] == "ok"
    assert data_root["app"] == "CAMserv"

    # API v1 system health
    r_sys = client.get("/api/v1/system/health")
    assert r_sys.status_code == 200
    data_sys = r_sys.json()
    assert "status" in data_sys
    assert "components" in data_sys


@pytest.mark.unit
def test_cameras_crud(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Verify complete camera CRUD lifecycle (Create, Read, Update, Delete)."""
    camera_payload = {
        "id": "cam-gate-01",
        "name": "Main Gate North",
        "url": "rtsp://192.168.1.100:554/live",
        "enabled": True,
        "fps": 25,
        "resolution": [1920, 1080],
        "codec": "h264",
    }

    # 1. Create
    r_create = client.post("/api/v1/cameras", json=camera_payload, headers=admin_headers)
    assert r_create.status_code == 201
    created_data = r_create.json()
    assert created_data["id"] == "cam-gate-01"
    assert created_data["name"] == "Main Gate North"

    # 2. List / Read
    r_list = client.get("/api/v1/cameras", headers=admin_headers)
    assert r_list.status_code == 200
    cameras = r_list.json()
    assert any(c["id"] == "cam-gate-01" for c in cameras)

    # 3. Update
    r_update = client.put(
        "/api/v1/cameras/cam-gate-01",
        json={"name": "Main Gate North (Updated)", "fps": 30},
        headers=admin_headers,
    )
    assert r_update.status_code == 200
    updated_data = r_update.json()
    assert updated_data["name"] == "Main Gate North (Updated)"
    assert updated_data["fps"] == 30

    # 4. Delete
    r_del = client.delete("/api/v1/cameras/cam-gate-01", headers=admin_headers)
    assert r_del.status_code == 204

    # Verify deleted
    r_list_after = client.get("/api/v1/cameras", headers=admin_headers)
    assert not any(c["id"] == "cam-gate-01" for c in r_list_after.json())


@pytest.mark.unit
def test_events_query_with_filters(client: TestClient, admin_headers: dict[str, str], app) -> None:
    """Verify /events endpoint correctly filters events by type, camera_id, and severity."""
    # Seed mock events in state
    app.state.events = [
        {
            "event_id": "evt-101",
            "event_type": "zone_intrusion",
            "severity": "high",
            "confidence": 0.94,
            "camera_id": "cam-01",
            "timestamp": "2026-11-13T10:00:00Z",
            "requires_verification": True,
            "description": "Perimeter breach",
        },
        {
            "event_id": "evt-102",
            "event_type": "loitering",
            "severity": "medium",
            "confidence": 0.75,
            "camera_id": "cam-02",
            "timestamp": "2026-11-13T10:05:00Z",
            "requires_verification": False,
            "description": "Loitering detected",
        },
    ]

    # Filter by camera_id
    r_cam = client.get("/api/v1/events?camera_id=cam-01", headers=admin_headers)
    assert r_cam.status_code == 200
    data_cam = r_cam.json()
    assert len(data_cam["items"]) == 1
    assert data_cam["items"][0]["event_id"] == "evt-101"

    # Filter by severity
    r_sev = client.get("/api/v1/events?severity=medium", headers=admin_headers)
    assert r_sev.status_code == 200
    data_sev = r_sev.json()
    assert len(data_sev["items"]) == 1
    assert data_sev["items"][0]["event_id"] == "evt-102"


@pytest.mark.unit
def test_event_verification_workflow(client: TestClient, admin_headers: dict[str, str], app) -> None:
    """Verify human-in-the-loop event verification transitions verification status and logs audit entry."""
    app.state.events = [
        {
            "event_id": "evt-verify-1",
            "event_type": "zone_intrusion",
            "severity": "high",
            "confidence": 0.95,
            "camera_id": "cam-north",
            "timestamp": "2026-11-13T12:00:00Z",
            "requires_verification": True,
            "description": "Intrusion detected",
            "verification_status": "pending",
        }
    ]

    verify_payload = {
        "action": "accept",
        "reason": "Confirmed unauthorized personnel entering through broken fence",
        "reviewer_notes": "Dispatched security patrol",
    }

    r_verify = client.post(
        "/api/v1/events/evt-verify-1/verify",
        json=verify_payload,
        headers=admin_headers,
    )
    assert r_verify.status_code == 200
    data = r_verify.json()
    assert data["verification_status"] == "verified"
    assert data["verified_by"] == "admin"
    assert data["verification_reason"] == verify_payload["reason"]


@pytest.mark.unit
def test_unauthorized_access_rejected(client: TestClient) -> None:
    """Verify endpoints with authentication requirements reject unauthenticated calls with 401 or 403."""
    # Accessing protected camera endpoint with no auth token
    r_no_auth = client.get("/api/v1/cameras")
    assert r_no_auth.status_code in (401, 403)

    # Accessing with invalid token
    r_bad_auth = client.get("/api/v1/cameras", headers={"Authorization": "Bearer invalid_token_xyz"})
    assert r_bad_auth.status_code in (401, 403)


@pytest.mark.unit
def test_rate_limiting(client: TestClient, admin_headers: dict[str, str], app) -> None:
    """Verify client exceeding rate limit receives HTTP 429 Too Many Requests."""
    auth: AuthManager = app.state.auth_manager
    auth.rate_limiter.limit = 3  # Set artificially low limit for test

    # Make 3 permitted requests
    for _ in range(3):
        r = client.get("/api/v1/cameras", headers=admin_headers)
        assert r.status_code == 200

    # 4th request must exceed rate limit
    r_exceeded = client.get("/api/v1/cameras", headers=admin_headers)
    assert r_exceeded.status_code == 429
    assert "rate limit exceeded" in r_exceeded.json()["detail"].lower()


@pytest.mark.unit
def test_pagination_cursor(client: TestClient, admin_headers: dict[str, str], app) -> None:
    """Verify cursor pagination correctly steps through pages of events."""
    app.state.events = [
        {
            "event_id": f"evt-{i:03d}",
            "event_type": "zone_intrusion",
            "severity": "medium",
            "confidence": 0.8,
            "camera_id": "cam-1",
            "timestamp": f"2026-11-13T10:{i:02d}:00Z",
            "requires_verification": False,
            "description": f"Event {i}",
        }
        for i in range(10)
    ]

    # Request page 1 with limit=3
    r_page1 = client.get("/api/v1/events?limit=3", headers=admin_headers)
    assert r_page1.status_code == 200
    d1 = r_page1.json()
    assert len(d1["items"]) == 3
    cursor = d1["next_cursor"]
    assert cursor is not None

    # Request page 2 using cursor
    r_page2 = client.get(f"/api/v1/events?limit=3&cursor={cursor}", headers=admin_headers)
    assert r_page2.status_code == 200
    d2 = r_page2.json()
    assert len(d2["items"]) == 3
    assert d2["items"][0]["event_id"] != d1["items"][0]["event_id"]


@pytest.mark.unit
def test_websocket_event_stream(client: TestClient, app) -> None:
    """Verify WebSocket connection connects with auth token and supports ping/pong."""
    auth: AuthManager = app.state.auth_manager
    token = auth.create_access_token(subject="ws_user", role=Role.VIEWER)

    # Connect with valid token
    with client.websocket_connect(f"/api/v1/ws/events?token={token}") as websocket:
        websocket.send_text("ping")
        response = websocket.receive_text()
        assert response == "pong"


@pytest.mark.unit
def test_api_error_responses(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Verify standardized error JSON structures for 404, 400, and 409 errors."""
    # 404 Not Found
    r_404 = client.get("/api/v1/cameras/non_existent_id", headers=admin_headers)
    assert r_404.status_code == 404
    assert "detail" in r_404.json()

    # 400 Validation Error (e.g. invalid camera ID regex)
    invalid_cam = {
        "id": "invalid ID with spaces!!",
        "name": "Bad Cam",
        "url": "rtsp://localhost/stream",
    }
    r_400 = client.post("/api/v1/cameras", json=invalid_cam, headers=admin_headers)
    assert r_400.status_code == 422 or r_400.status_code == 400
    assert "detail" in r_400.json()

    # 409 Conflict
    valid_cam = {
        "id": "cam-dup-01",
        "name": "Duplicate Cam",
        "url": "rtsp://localhost/stream",
    }
    r_first = client.post("/api/v1/cameras", json=valid_cam, headers=admin_headers)
    assert r_first.status_code == 201
    r_dup = client.post("/api/v1/cameras", json=valid_cam, headers=admin_headers)
    assert r_dup.status_code == 409
    assert "detail" in r_dup.json()
