"""
camserv.central.registry
========================

Cryptographic device enrollment, lifecycle management, health telemetry ingestion,
and strict multi-site authorization isolation for CAMserv Central.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv.central.models import (
    CentralFleetOverview,
    DeviceRegistrationRecord,
    DeviceRole,
    DeviceStatus,
    DeviceTelemetry,
    SecurityState,
    SiteRecord,
)

logger = structlog.get_logger(__name__)


class SiteAccessDeniedError(PermissionError):
    """Raised when an operator attempts to access a site beyond their authorization."""


class DeviceEnrollmentError(ValueError):
    """Raised when device enrollment validation or token verification fails."""


class DeviceAuthenticationError(PermissionError):
    """Raised when cryptographic challenge-response signature verification fails."""


class DeviceRegistry:
    """
    Central management registry governing appliance identities, cryptographic keys,
    health telemetry, and multi-site isolation boundaries.
    """

    def __init__(self) -> None:
        self.sites: dict[str, SiteRecord] = {}
        self.devices: dict[str, DeviceRegistrationRecord] = {}
        self._enrollment_tokens: dict[str, dict[str, Any]] = {}

    # ---------------------------------------------------------------------------
    # Site Management & Multi-Site Isolation
    # ---------------------------------------------------------------------------

    def register_site(self, site_id: str, site_name: str, location: str, assigned_operators: list[str] | None = None) -> SiteRecord:
        """Register a new logical facility site."""
        site = SiteRecord(
            site_id=site_id,
            site_name=site_name,
            location=location,
            assigned_operators=assigned_operators or [],
        )
        self.sites[site_id] = site
        logger.info("central.site_registered", site_id=site_id, name=site_name)
        return site

    def get_site(self, site_id: str) -> SiteRecord | None:
        """Retrieve a site record."""
        return self.sites.get(site_id)

    def _verify_site_access(self, site_id: str, user_role: str, user_assigned_sites: list[str]) -> None:
        """
        Enforce strict server-side site isolation boundary.
        SUPER_ADMIN can access all sites.
        SITE_OPERATOR or SITE_ADMIN can only access sites explicitly listed in user_assigned_sites.
        """
        if user_role.upper() == "SUPER_ADMIN":
            return

        if site_id not in user_assigned_sites:
            logger.warning(
                "central.site_access_denied",
                site_id=site_id,
                user_role=user_role,
                allowed_sites=user_assigned_sites,
            )
            raise SiteAccessDeniedError(
                f"ACCESS DENIED: User role '{user_role}' is not authorized to access site '{site_id}'."
            )

    # ---------------------------------------------------------------------------
    # Device Enrollment & Authentication
    # ---------------------------------------------------------------------------

    def create_enrollment_token(self, token: str, site_id: str, expires_in_sec: float = 3600.0) -> None:
        """Issue a temporary cryptographically scoped token for device commissioning."""
        if site_id not in self.sites:
            raise ValueError(f"Site '{site_id}' does not exist in registry.")

        self._enrollment_tokens[token] = {
            "site_id": site_id,
            "expires_at": time.time() + expires_in_sec,
            "used": False,
        }
        logger.info("central.enrollment_token_created", site_id=site_id)

    def enroll_device(
        self,
        device_id: str,
        device_name: str,
        device_role: DeviceRole,
        site_id: str,
        public_key_hex: str,
        hardware_profile: str,
        software_version: str,
        enrollment_token: str,
        authorized_by: str,
    ) -> DeviceRegistrationRecord:
        """
        Commission a new appliance into the central registry.
        Requires explicit enrollment authorization via valid token.
        """
        # Validate enrollment token
        token_info = self._enrollment_tokens.get(enrollment_token)
        if not token_info:
            logger.error("central.enrollment_rejected_invalid_token", device_id=device_id)
            raise DeviceEnrollmentError("REJECTED: Unknown or invalid enrollment token.")

        if token_info["used"]:
            logger.error("central.enrollment_rejected_reused_token", device_id=device_id)
            raise DeviceEnrollmentError("REJECTED: Enrollment token has already been consumed.")

        if time.time() > token_info["expires_at"]:
            logger.error("central.enrollment_rejected_expired_token", device_id=device_id)
            raise DeviceEnrollmentError("REJECTED: Enrollment token has expired.")

        if token_info["site_id"] != site_id:
            logger.error("central.enrollment_rejected_site_mismatch", token_site=token_info["site_id"], request_site=site_id)
            raise DeviceEnrollmentError("REJECTED: Enrollment token was not issued for the specified site.")

        # Validate Ed25519 public key format
        try:
            pub_bytes = bytes.fromhex(public_key_hex)
            if len(pub_bytes) != 32:
                raise ValueError("Ed25519 public key must be exactly 32 bytes.")
            ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        except Exception as e:
            logger.error("central.invalid_public_key", device_id=device_id, error=str(e))
            raise DeviceEnrollmentError(f"REJECTED: Malformed Ed25519 public key: {e}")

        # Mark token consumed
        token_info["used"] = True

        # Create device record
        now = time.time()
        record = DeviceRegistrationRecord(
            device_id=device_id,
            device_name=device_name,
            device_role=device_role,
            site_id=site_id,
            public_key_hex=public_key_hex,
            hardware_profile=hardware_profile,
            software_version=software_version,
            status=DeviceStatus.ONLINE,
            security_state=SecurityState.ENROLLED_AUTHENTICATED,
            enrolled_at=now,
            last_seen_at=now,
            metadata={"enrolled_by": authorized_by},
        )
        self.devices[device_id] = record

        # Add to site list
        if device_id not in self.sites[site_id].enrolled_devices:
            self.sites[site_id].enrolled_devices.append(device_id)

        logger.info(
            "central.device_enrolled_successfully",
            device_id=device_id,
            site_id=site_id,
            role=device_role.value,
        )
        return record

    def authenticate_challenge(self, device_id: str, challenge: bytes, signature_hex: str) -> bool:
        """
        Verify that an incoming connection is genuinely signed by the device's private key.
        Prevents device identity spoofing and unauthorized connections.
        """
        if device_id not in self.devices:
            raise DeviceAuthenticationError(f"Device '{device_id}' is not enrolled in registry.")

        device = self.devices[device_id]
        if device.status in (DeviceStatus.SUSPENDED, DeviceStatus.REVOKED):
            logger.warning("central.auth_rejected_device_status", device_id=device_id, status=device.status.value)
            raise DeviceAuthenticationError(f"Authentication rejected: Device status is '{device.status.value}'.")

        try:
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(device.public_key_hex))
            sig_bytes = bytes.fromhex(signature_hex)
            pub_key.verify(sig_bytes, challenge)
            device.last_seen_at = time.time()
            device.status = DeviceStatus.ONLINE
            return True
        except Exception as e:
            logger.error("central.challenge_verification_failed", device_id=device_id, error=str(e))
            raise DeviceAuthenticationError("Cryptographic signature verification failed.")

    # ---------------------------------------------------------------------------
    # Telemetry Ingestion & Lifecycle Control
    # ---------------------------------------------------------------------------

    def report_telemetry(self, device_id: str, telemetry: DeviceTelemetry) -> bool:
        """Ingest live health metrics reported by an appliance."""
        if device_id not in self.devices:
            return False

        device = self.devices[device_id]
        device.telemetry = telemetry
        device.last_seen_at = time.time()
        device.status = DeviceStatus.ONLINE
        return True

    def suspend_device(
        self,
        device_id: str,
        reason: str,
        operator_id: str,
        user_role: str = "SUPER_ADMIN",
        user_assigned_sites: list[str] | None = None,
    ) -> bool:
        """Temporarily suspend a device from fleet operations with server-side authorization check."""
        if device_id not in self.devices:
            return False

        device = self.devices[device_id]
        self._verify_site_access(device.site_id, user_role, user_assigned_sites or [])

        device.status = DeviceStatus.SUSPENDED
        device.metadata["suspended_by"] = operator_id
        device.metadata["suspend_reason"] = reason
        logger.warning("central.device_suspended", device_id=device_id, reason=reason)
        return True

    def revoke_device(
        self,
        device_id: str,
        reason: str,
        operator_id: str,
        user_role: str = "SUPER_ADMIN",
        user_assigned_sites: list[str] | None = None,
    ) -> bool:
        """Permanently revoke trust and invalidate credentials with server-side authorization check."""
        if device_id not in self.devices:
            return False

        device = self.devices[device_id]
        self._verify_site_access(device.site_id, user_role, user_assigned_sites or [])

        device.status = DeviceStatus.REVOKED
        device.security_state = SecurityState.QUARANTINED
        device.metadata["revoked_by"] = operator_id
        device.metadata["revoke_reason"] = reason
        logger.critical("central.device_revoked", device_id=device_id, reason=reason)
        return True

    def query_devices_by_site(
        self,
        site_id: str,
        user_role: str = "SUPER_ADMIN",
        user_assigned_sites: list[str] | None = None,
    ) -> list[DeviceRegistrationRecord]:
        """Query devices for a site with strict multi-site authorization check."""
        self._verify_site_access(site_id, user_role, user_assigned_sites or [])
        return [dev for dev in self.devices.values() if dev.site_id == site_id]

    def get_fleet_overview(
        self,
        user_role: str = "SUPER_ADMIN",
        user_assigned_sites: list[str] | None = None,
    ) -> CentralFleetOverview:
        """Aggregate real device telemetry into an executive fleet dashboard."""
        allowed_sites = set(user_assigned_sites or []) if user_role.upper() != "SUPER_ADMIN" else set(self.sites.keys())

        overview = CentralFleetOverview(total_sites=len(allowed_sites))
        now = time.time()

        for dev in self.devices.values():
            if dev.site_id not in allowed_sites:
                continue

            overview.total_devices += 1

            # Check online / offline status (offline if no contact for > 90 seconds)
            if dev.status == DeviceStatus.REVOKED or dev.status == DeviceStatus.SUSPENDED:
                overview.degraded_devices += 1
            elif (now - dev.last_seen_at) > 90.0:
                overview.offline_devices += 1
            else:
                overview.online_devices += 1

            # Sum actual telemetry
            overview.total_active_cameras += dev.telemetry.active_cameras
            overview.total_active_threat_alerts += dev.telemetry.active_threat_alerts
            overview.aggregate_storage_free_tb += (dev.telemetry.storage_free_gb / 1024.0)

        return overview
