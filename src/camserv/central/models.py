"""
camserv.central.models
======================

Data models, role taxonomies, and telemetry schemas for CAMserv Central
multi-site fleet and device registry.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


class DeviceRole(str, enum.Enum):
    """Functional role of an appliance within the CAMserv fleet."""

    EDGE_NODE = "edge_node"                  # Distributed lightweight camera ingestion node
    PRO_APPLIANCE = "pro_appliance"          # Standard multi-stream turnkey smart NVR
    ENTERPRISE_CLUSTER = "enterprise_cluster"# Clustered high-throughput multi-GPU node
    CENTRAL_GATEWAY = "central_gateway"      # Central management & aggregation plane


class DeviceStatus(str, enum.Enum):
    """Network and operational status of a registered device."""

    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    PENDING_ENROLLMENT = "pending_enrollment"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class SecurityState(str, enum.Enum):
    """Cryptographic certificate and enrollment trust status."""

    PENDING_VERIFICATION = "pending_verification"
    ENROLLED_AUTHENTICATED = "enrolled_authenticated"
    CERT_EXPIRED = "cert_expired"
    QUARANTINED = "quarantined"


@dataclass(slots=True)
class DeviceTelemetry:
    """Real-time operational health telemetry reported by an edge appliance."""

    cpu_load_percent: float = 0.0
    ram_used_mb: int = 0
    ram_total_mb: int = 0
    storage_free_gb: float = 0.0
    storage_total_gb: float = 0.0
    gpu_temp_celsius: float | None = None
    active_cameras: int = 0
    active_threat_alerts: int = 0
    reported_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize telemetry metrics."""
        return {
            "cpu_load_percent": round(self.cpu_load_percent, 1),
            "ram_used_mb": self.ram_used_mb,
            "ram_total_mb": self.ram_total_mb,
            "storage_free_gb": round(self.storage_free_gb, 1),
            "storage_total_gb": round(self.storage_total_gb, 1),
            "gpu_temp_celsius": self.gpu_temp_celsius,
            "active_cameras": self.active_cameras,
            "active_threat_alerts": self.active_threat_alerts,
            "reported_at": self.reported_at,
        }


@dataclass(slots=True)
class DeviceRegistrationRecord:
    """Complete cryptographic and operational registry record for an appliance."""

    device_id: str
    device_name: str
    device_role: DeviceRole
    site_id: str
    public_key_hex: str
    hardware_profile: str
    software_version: str
    status: DeviceStatus = DeviceStatus.PENDING_ENROLLMENT
    security_state: SecurityState = SecurityState.PENDING_VERIFICATION
    telemetry: DeviceTelemetry = field(default_factory=DeviceTelemetry)
    enrolled_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize device record for management APIs."""
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_role": self.device_role.value,
            "site_id": self.site_id,
            "public_key_hex": self.public_key_hex,
            "hardware_profile": self.hardware_profile,
            "software_version": self.software_version,
            "status": self.status.value,
            "security_state": self.security_state.value,
            "telemetry": self.telemetry.to_dict(),
            "enrolled_at": self.enrolled_at,
            "last_seen_at": self.last_seen_at,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class SiteRecord:
    """Logical multi-site separation entity within CAMserv Central."""

    site_id: str
    site_name: str
    location: str
    assigned_operators: list[str] = field(default_factory=list)
    enrolled_devices: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize site entity."""
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "location": self.location,
            "assigned_operators": self.assigned_operators,
            "enrolled_devices": self.enrolled_devices,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class CentralFleetOverview:
    """Aggregated global telemetry summary across all managed installations."""

    total_sites: int = 0
    total_devices: int = 0
    online_devices: int = 0
    offline_devices: int = 0
    degraded_devices: int = 0
    total_active_cameras: int = 0
    total_active_threat_alerts: int = 0
    aggregate_storage_free_tb: float = 0.0
    pending_software_updates: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize fleet dashboard summary."""
        return {
            "total_sites": self.total_sites,
            "total_devices": self.total_devices,
            "online_devices": self.online_devices,
            "offline_devices": self.offline_devices,
            "degraded_devices": self.degraded_devices,
            "total_active_cameras": self.total_active_cameras,
            "total_active_threat_alerts": self.total_active_threat_alerts,
            "aggregate_storage_free_tb": round(self.aggregate_storage_free_tb, 2),
            "pending_software_updates": self.pending_software_updates,
        }
