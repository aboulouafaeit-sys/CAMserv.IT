"""Tests for CAMserv Enterprise Web Console mounting and asset delivery."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from camserv.api.app import create_app
from camserv.config.settings import CamservSettings


@pytest.fixture
def client(platform_settings: CamservSettings) -> TestClient:
    """Fixture providing a test client for the full FastAPI application."""
    app = create_app(platform_settings)
    return TestClient(app)


@pytest.mark.unit
def test_web_console_index_html(client: TestClient) -> None:
    """Verify that root URL '/' serves the CAMserv Enterprise Web Console HTML shell."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "CAMserv" in resp.text
    assert "Executive Overview" in resp.text
    assert "Intelligent Event Center" in resp.text
    assert "text/html" in resp.headers.get("content-type", "")


@pytest.mark.unit
def test_web_console_static_assets(client: TestClient) -> None:
    """Verify that design system CSS, JS runtime, and brand SVGs are accessible."""
    # CSS
    resp_css = client.get("/styles.css")
    assert resp_css.status_code == 200
    assert "--bg-canvas" in resp_css.text

    # JS
    resp_js = client.get("/app.js")
    assert resp_js.status_code == 200
    assert "CAMservClient" in resp_js.text

    # Brand PNG assets (official AI-generated suite)
    resp_sym = client.get("/assets/camserv-logo-transparent.png")
    assert resp_sym.status_code == 200
    assert len(resp_sym.content) > 1000

    # Favicon
    resp_fav = client.get("/assets/favicon.png")
    assert resp_fav.status_code == 200
    assert len(resp_fav.content) > 100


@pytest.mark.unit
def test_api_routes_remain_functional_with_mounted_console(client: TestClient) -> None:
    """Ensure mounting the web console at root does not shadow or break /api/v1/ endpoints."""
    # Health endpoint
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] == "ok"

    # API v1 system health
    resp_api = client.get("/api/v1/system/health")
    assert resp_api.status_code == 200
    data = resp_api.json()
    assert "status" in data
