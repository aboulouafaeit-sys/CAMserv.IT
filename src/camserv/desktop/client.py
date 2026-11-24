"""
camserv.desktop.client
======================

REST and WebSocket client for the CAMserv Windows Desktop Operator Console.
Communicates securely over local loopback (http://127.0.0.1:8080) with the
background Windows Service using JWT authentication.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DesktopServiceClient:
    """Decoupled HTTP/REST client for interacting with the CAMserv Windows Service."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080") -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self._is_connected = False
        self._last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any] | list[Any] | None:
        """Perform an HTTP request with JSON payload and bearer authentication."""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "CAMserv-Desktop-Console/0.10.0-rc7 (Windows NT 10.0; Win64; x64)",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                self._is_connected = True
                self._last_error = None
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return json.loads(resp.read().decode("utf-8"))
                return {"status": resp.status, "content": resp.read().decode("utf-8")}
        except urllib.error.HTTPError as exc:
            self._is_connected = False
            self._last_error = f"HTTP {exc.code}: {exc.reason}"
            logger.warning("desktop.client_http_error", endpoint=endpoint, code=exc.code, reason=exc.reason)
            return None
        except urllib.error.URLError as exc:
            self._is_connected = False
            self._last_error = f"Connection failed: {exc.reason}"
            logger.debug("desktop.client_connection_failed", endpoint=endpoint, reason=str(exc.reason))
            return None
        except Exception as exc:
            self._is_connected = False
            self._last_error = str(exc)
            logger.error("desktop.client_error", endpoint=endpoint, error=str(exc))
            return None

    def authenticate(self, username: str = "admin", password: str = "admin") -> bool:
        """Authenticate with the CAMserv background service and store JWT token."""
        res = self._request(
            "/api/v1/auth/token",
            method="POST",
            data={"username": username, "password": password},
        )
        if isinstance(res, dict) and "access_token" in res:
            self.token = str(res["access_token"])
            self._is_connected = True
            logger.info("desktop.client_authenticated", username=username)
            return True
        return False

    def check_health(self) -> dict[str, Any] | None:
        """Query system health status from the service."""
        res = self._request("/health", method="GET")
        if res is None:
            res = self._request("/api/v1/health", method="GET")
        return res if isinstance(res, dict) else None

    def get_cameras(self) -> list[dict[str, Any]]:
        """Retrieve list of configured cameras."""
        res = self._request("/api/v1/cameras", method="GET")
        if isinstance(res, list):
            return res
        elif isinstance(res, dict) and "items" in res:
            return res["items"]
        return []

    def get_recordings(self, camera_id: str | None = None) -> list[dict[str, Any]]:
        """Retrieve recordings list."""
        query = f"?camera_id={urllib.parse.quote(camera_id)}" if camera_id else ""
        res = self._request(f"/api/v1/recordings{query}", method="GET")
        if isinstance(res, list):
            return res
        elif isinstance(res, dict) and "recordings" in res:
            return res["recordings"]
        return []

    def get_events(self, limit: int = 50, severity: str | None = None) -> list[dict[str, Any]]:
        """Query detected events from the intelligence pipeline."""
        params: dict[str, Any] = {"limit": limit}
        if severity:
            params["severity"] = severity
        query = f"?{urllib.parse.urlencode(params)}"
        res = self._request(f"/api/v1/events{query}", method="GET")
        if isinstance(res, list):
            return res
        elif isinstance(res, dict) and "events" in res:
            return res["events"]
        return []

    def acknowledge_event(self, event_id: str, operator_notes: str = "") -> bool:
        """Acknowledge a security event."""
        res = self._request(
            f"/api/v1/events/{event_id}/acknowledge",
            method="POST",
            data={"notes": operator_notes},
        )
        return res is not None

    def get_cluster_status(self) -> dict[str, Any] | None:
        """Query enterprise cluster topology and node health."""
        res = self._request("/api/v1/central/cluster/status", method="GET")
        return res if isinstance(res, dict) else None

    def quarantine_cluster_node(self, node_id: str, reason: str = "Operator Manual Quarantine") -> bool:
        """Command cluster coordinator to quarantine a rogue or compromised node."""
        res = self._request(
            f"/api/v1/central/cluster/nodes/{node_id}/quarantine",
            method="POST",
            data={"reason": reason},
        )
        return res is not None

    def get_system_telemetry(self) -> dict[str, Any]:
        """Collect platform and hardware diagnostics via platform layer."""
        from camserv.platform.factory import get_platform_hardware_prober, get_platform_service_manager

        hw = get_platform_hardware_prober()
        scm = get_platform_service_manager()

        cpu_ram = hw.probe_cpu_and_ram()
        gpus = hw.probe_gpus()
        status = scm.query_status("CAMservCore")

        return {
            "service_name": status.name,
            "service_state": status.state.value,
            "os": cpu_ram.get("os", "Windows"),
            "logical_cores": cpu_ram.get("logical_cores", 1),
            "ram_total_mb": cpu_ram.get("ram_total_mb", 0),
            "ram_available_mb": cpu_ram.get("ram_available_mb", 0),
            "gpus": gpus,
            "connected_to_api": self._is_connected,
            "last_error": self._last_error,
        }
