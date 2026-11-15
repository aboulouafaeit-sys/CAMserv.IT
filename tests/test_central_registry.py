"""
tests.test_central_registry
===========================

Unit and integration tests for CAMserv Central device registry, Ed25519 cryptographic
enrollment and authentication, health telemetry ingestion, and multi-site isolation.
"""

import time
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv.central.models import (
    DeviceRole,
    DeviceStatus,
    DeviceTelemetry,
    SecurityState,
)
from camserv.central.registry import (
    DeviceAuthenticationError,
    DeviceEnrollmentError,
    DeviceRegistry,
    SiteAccessDeniedError,
)


def test_site_registration_and_multi_site_isolation():
    """Verify logical site boundaries and server-side access enforcement."""
    reg = DeviceRegistry()
    reg.register_site("site-alpha", "Airport Terminal 1", "Frankfurt", ["alice"])
    reg.register_site("site-beta", "Logistics Hub 4", "Hamburg", ["bob"])

    assert reg.get_site("site-alpha") is not None
    assert reg.get_site("site-beta") is not None

    # Super admin can query all sites
    assert reg.query_devices_by_site("site-alpha", user_role="SUPER_ADMIN") == []

    # Alice assigned to site-alpha can query site-alpha
    assert reg.query_devices_by_site("site-alpha", user_role="SITE_OPERATOR", user_assigned_sites=["site-alpha"]) == []

    # Alice attempting to query site-beta MUST raise SiteAccessDeniedError!
    with pytest.raises(SiteAccessDeniedError, match="ACCESS DENIED"):
        reg.query_devices_by_site("site-beta", user_role="SITE_OPERATOR", user_assigned_sites=["site-alpha"])


def test_cryptographic_device_enrollment():
    """Verify Ed25519 device enrollment with token validation and error boundaries."""
    reg = DeviceRegistry()
    reg.register_site("site-alpha", "Airport Terminal 1", "Frankfurt")

    # Issue enrollment token for site-alpha
    reg.create_enrollment_token("VALID_TOKEN_123", "site-alpha", expires_in_sec=60.0)

    # Generate device Ed25519 keypair
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key_hex = priv_key.public_key().public_bytes_raw().hex()

    # Successful enrollment
    dev = reg.enroll_device(
        device_id="appliance-001",
        device_name="North Gate NVR",
        device_role=DeviceRole.PRO_APPLIANCE,
        site_id="site-alpha",
        public_key_hex=pub_key_hex,
        hardware_profile="profile_b_professional",
        software_version="3.0.0",
        enrollment_token="VALID_TOKEN_123",
        authorized_by="admin_secops",
    )
    assert dev.device_id == "appliance-001"
    assert dev.status == DeviceStatus.ONLINE
    assert dev.security_state == SecurityState.ENROLLED_AUTHENTICATED

    # Reusing the consumed token MUST fail
    with pytest.raises(DeviceEnrollmentError, match="already been consumed"):
        reg.enroll_device(
            device_id="appliance-002",
            device_name="South Gate NVR",
            device_role=DeviceRole.EDGE_NODE,
            site_id="site-alpha",
            public_key_hex=pub_key_hex,
            hardware_profile="profile_a_edge",
            software_version="3.0.0",
            enrollment_token="VALID_TOKEN_123",
            authorized_by="admin_secops",
        )

    # Invalid token MUST fail
    with pytest.raises(DeviceEnrollmentError, match="Unknown or invalid"):
        reg.enroll_device(
            device_id="appliance-003",
            device_name="Fake NVR",
            device_role=DeviceRole.EDGE_NODE,
            site_id="site-alpha",
            public_key_hex=pub_key_hex,
            hardware_profile="profile_a_edge",
            software_version="3.0.0",
            enrollment_token="FAKE_TOKEN_999",
            authorized_by="attacker",
        )


def test_challenge_response_authentication():
    """Verify Ed25519 challenge-response handshake authentication."""
    reg = DeviceRegistry()
    reg.register_site("site-alpha", "Airport Terminal 1", "Frankfurt")
    reg.create_enrollment_token("TOK_99", "site-alpha")

    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key_hex = priv_key.public_key().public_bytes_raw().hex()

    reg.enroll_device(
        device_id="appliance-auth-test",
        device_name="Server 1",
        device_role=DeviceRole.ENTERPRISE_CLUSTER,
        site_id="site-alpha",
        public_key_hex=pub_key_hex,
        hardware_profile="profile_c_enterprise",
        software_version="3.0.0",
        enrollment_token="TOK_99",
        authorized_by="admin",
    )

    # Valid challenge signed by private key
    challenge = b"CAMSERV_CENTRAL_AUTH_CHALLENGE_NONCE_789123"
    valid_sig_hex = priv_key.sign(challenge).hex()
    assert reg.authenticate_challenge("appliance-auth-test", challenge, valid_sig_hex) is True

    # Forged challenge / invalid signature MUST fail
    invalid_sig_hex = b"\x00" * 64
    with pytest.raises(DeviceAuthenticationError, match="Cryptographic signature verification failed"):
        reg.authenticate_challenge("appliance-auth-test", challenge, invalid_sig_hex.hex())


def test_device_lifecycle_and_suspension_revocation():
    """Verify telemetry updates, device suspension, and revocation rejection."""
    reg = DeviceRegistry()
    reg.register_site("site-alpha", "Terminal 1", "Frankfurt")
    reg.create_enrollment_token("TOK_LC", "site-alpha")

    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key_hex = priv_key.public_key().public_bytes_raw().hex()

    reg.enroll_device(
        device_id="appliance-lc",
        device_name="Terminal Cam Hub",
        device_role=DeviceRole.PRO_APPLIANCE,
        site_id="site-alpha",
        public_key_hex=pub_key_hex,
        hardware_profile="profile_b_professional",
        software_version="3.0.0",
        enrollment_token="TOK_LC",
        authorized_by="admin",
    )

    # Report telemetry
    telemetry = DeviceTelemetry(
        cpu_load_percent=34.5,
        ram_used_mb=4096,
        ram_total_mb=32768,
        storage_free_gb=1250.0,
        active_cameras=8,
        active_threat_alerts=1,
    )
    assert reg.report_telemetry("appliance-lc", telemetry) is True
    assert reg.devices["appliance-lc"].telemetry.active_cameras == 8

    # Suspend device
    reg.suspend_device("appliance-lc", reason="Scheduled Maintenance", operator_id="admin")
    challenge = b"CHALLENGE_LC"
    sig_hex = priv_key.sign(challenge).hex()

    with pytest.raises(DeviceAuthenticationError, match="status is 'suspended'"):
        reg.authenticate_challenge("appliance-lc", challenge, sig_hex)

    # Revoke device permanently
    reg.revoke_device("appliance-lc", reason="Compromised Enclosure", operator_id="security_officer")
    with pytest.raises(DeviceAuthenticationError, match="status is 'revoked'"):
        reg.authenticate_challenge("appliance-lc", challenge, sig_hex)


def test_fleet_overview_dashboard_aggregation():
    """Verify executive fleet telemetry aggregation and site authorization filtering."""
    reg = DeviceRegistry()
    reg.register_site("site-alpha", "Terminal 1", "Frankfurt")
    reg.register_site("site-beta", "Hub 4", "Hamburg")

    # Enroll device on alpha
    reg.create_enrollment_token("TOK_A", "site-alpha")
    p1 = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    reg.enroll_device("dev-1", "A1", DeviceRole.PRO_APPLIANCE, "site-alpha", p1, "pro", "3.0", "TOK_A", "admin")
    reg.report_telemetry("dev-1", DeviceTelemetry(active_cameras=12, active_threat_alerts=2, storage_free_gb=2048.0))

    # Enroll device on beta
    reg.create_enrollment_token("TOK_B", "site-beta")
    p2 = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    reg.enroll_device("dev-2", "B1", DeviceRole.EDGE_NODE, "site-beta", p2, "edge", "3.0", "TOK_B", "admin")
    reg.report_telemetry("dev-2", DeviceTelemetry(active_cameras=4, active_threat_alerts=0, storage_free_gb=500.0))

    # Super admin sees all 2 sites and 16 total cameras
    full_overview = reg.get_fleet_overview(user_role="SUPER_ADMIN")
    assert full_overview.total_sites == 2
    assert full_overview.total_devices == 2
    assert full_overview.total_active_cameras == 16
    assert full_overview.total_active_threat_alerts == 2

    # Operator Bob restricted to site-beta sees only 1 site and 4 cameras!
    bob_overview = reg.get_fleet_overview(user_role="SITE_OPERATOR", user_assigned_sites=["site-beta"])
    assert bob_overview.total_sites == 1
    assert bob_overview.total_devices == 1
    assert bob_overview.total_active_cameras == 4
    assert bob_overview.total_active_threat_alerts == 0
