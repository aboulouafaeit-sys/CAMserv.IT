"""
Unit tests for CAMserv NVR encrypted credentials vault and camera groups.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from camserv.nvr.credentials import CameraCredential, CameraCredentialVault
from camserv.nvr.groups import CameraGroup, CameraGroupManager


@pytest.mark.unit
def test_camera_credential_vault_encryption(tmp_path: Path) -> None:
    """Test encrypting, persisting, and decrypting camera credentials."""
    vault_file = tmp_path / "creds.enc"
    master_key = b"01234567890123456789012345678901"  # 32 bytes

    vault = CameraCredentialVault(vault_path=vault_file, master_key=master_key)

    cred = CameraCredential(
        camera_id="cam_front_gate",
        username="admin",
        password="super_secret_camera_password",
        auth_type="digest",
        onvif_username="onvif_admin",
        onvif_password="onvif_password_123",
    )
    vault.store_credential(cred)

    # Verify encrypted file on disk does NOT contain plaintext password
    raw_disk = vault_file.read_bytes()
    assert b"super_secret_camera_password" not in raw_disk
    assert b"onvif_password_123" not in raw_disk

    # Reload vault from disk with same key
    vault2 = CameraCredentialVault(vault_path=vault_file, master_key=master_key)
    retrieved = vault2.get_credential("cam_front_gate")
    assert retrieved is not None
    assert retrieved.camera_id == "cam_front_gate"
    assert retrieved.password == "super_secret_camera_password"
    assert retrieved.onvif_password == "onvif_password_123"

    # Test listing
    assert "cam_front_gate" in vault2.list_cameras_with_credentials()

    # Test delete
    assert vault2.delete_credential("cam_front_gate") is True
    assert vault2.get_credential("cam_front_gate") is None


@pytest.mark.unit
def test_camera_credential_vault_wrong_key(tmp_path: Path) -> None:
    """Test that loading vault with incorrect key raises ValueError."""
    vault_file = tmp_path / "creds_wrong.enc"
    key1 = b"01234567890123456789012345678901"
    key2 = b"abcdefghijklmnopqrstuvwxyz012345"

    vault = CameraCredentialVault(vault_path=vault_file, master_key=key1)
    vault.store_credential(CameraCredential(camera_id="cam1", username="u", password="p"))

    with pytest.raises(ValueError, match="Failed to decrypt"):
        CameraCredentialVault(vault_path=vault_file, master_key=key2)


@pytest.mark.unit
def test_camera_group_manager() -> None:
    """Test camera group creation, update, camera assignment, and deletion."""
    mgr = CameraGroupManager()

    group = mgr.create_group(
        group_id="grp_perimeter",
        name="Perimeter Fence",
        description="Outer perimeter monitoring",
        camera_ids=["cam_01", "cam_02"],
        site_id="site_hq",
        tags=["external", "high_priority"],
    )
    assert group.group_id == "grp_perimeter"
    assert len(group.camera_ids) == 2

    # Duplicate group creation raises ValueError
    with pytest.raises(ValueError, match="already exists"):
        mgr.create_group(group_id="grp_perimeter", name="Duplicate")

    # Add camera to group
    mgr.add_camera_to_group("grp_perimeter", "cam_03")
    assert "cam_03" in mgr.get_group("grp_perimeter").camera_ids

    # Remove camera from group
    mgr.remove_camera_from_group("grp_perimeter", "cam_01")
    assert "cam_01" not in mgr.get_group("grp_perimeter").camera_ids

    # Update group
    mgr.update_group("grp_perimeter", name="Main Perimeter", tags=["external", "critical"])
    updated = mgr.get_group("grp_perimeter")
    assert updated.name == "Main Perimeter"
    assert "critical" in updated.tags

    # List groups by site
    groups = mgr.list_groups(site_id="site_hq")
    assert len(groups) == 1
    assert groups[0].group_id == "grp_perimeter"

    # Delete group
    assert mgr.delete_group("grp_perimeter") is True
    assert mgr.get_group("grp_perimeter") is None
