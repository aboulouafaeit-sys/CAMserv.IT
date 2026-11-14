"""Tests for Persistent Cryptographic Key Management (Phase 1A Condition C3)."""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from camserv.security.keys import (
    KeyIntegrityError,
    KeyManager,
    KeyMetadata,
    KeyType,
)
from camserv.storage.adaptive_vault import AdaptiveRetentionVault


@pytest.mark.unit
def test_key_manager_persistence_and_reloading(tmp_path: Path) -> None:
    """Verify that generated keys persist across restarts and reload identical values."""
    key_dir = tmp_path / "keys"
    km1 = KeyManager(key_dir=key_dir, master_secret="test-master-secret-32-chars-long")

    aes_key_1 = km1.get_or_create_encryption_key("vault-aes", version=1)
    sign_key_1 = km1.get_or_create_signing_key("vault-sign", version=1)

    # Re-instantiate from the same directory (simulating server reboot)
    km2 = KeyManager(key_dir=key_dir, master_secret="test-master-secret-32-chars-long")
    aes_key_2 = km2.get_or_create_encryption_key("vault-aes", version=1)
    sign_key_2 = km2.get_or_create_signing_key("vault-sign", version=1)

    assert aes_key_1 == aes_key_2, "Encryption key must be identical across restarts"
    
    # Verify signing key produces identical signatures
    msg = b"forensic-evidence-payload"
    sig1 = sign_key_1.sign(msg)
    sig2 = sign_key_2.sign(msg)
    assert sig1 == sig2, "Signing key must be identical across restarts"


@pytest.mark.unit
def test_key_manager_rotation(tmp_path: Path) -> None:
    """Verify that rotating keys increments the version and preserves access to older versions."""
    key_dir = tmp_path / "keys"
    km = KeyManager(key_dir=key_dir, master_secret="test-master-secret-32-chars-long")

    v1_key = km.get_or_create_encryption_key("vault-aes", version=1)
    new_v, v2_key = km.rotate_encryption_key("vault-aes")

    assert new_v == 2
    assert v1_key != v2_key

    # Old version remains retrievable
    retrieved_v1 = km.get_or_create_encryption_key("vault-aes", version=1)
    assert retrieved_v1 == v1_key


@pytest.mark.unit
def test_adaptive_vault_persistent_verification(tmp_path: Path) -> None:
    """Verify that evidence sealed by vault instance 1 can be verified by vault instance 2 after reboot."""
    vault_dir = tmp_path / "vault"
    
    # Instance 1: seals evidence
    v1 = AdaptiveRetentionVault(vault_root=vault_dir)
    seal, enc_bytes = v1.seal_forensic_chunk("cam-01", b"critical_incident_stream")

    # Instance 2: rebooted server verifying previous chunk
    v2 = AdaptiveRetentionVault(vault_root=vault_dir)
    verified = v2.verify_chunk_seal(seal, enc_bytes)
    assert verified is True, "Evidence must be verifiable across vault restarts with persistent keys"


@pytest.mark.unit
def test_key_manager_integrity_tampering(tmp_path: Path) -> None:
    """Verify that tampering with an encrypted key file raises KeyIntegrityError."""
    key_dir = tmp_path / "keys"
    km = KeyManager(key_dir=key_dir, master_secret="test-secret")
    km.get_or_create_encryption_key("vault-aes", version=1)

    key_file = key_dir / "vault-aes_v1.key"
    assert key_file.exists()

    # Corrupt key file content
    with open(key_file, "r+b") as f:
        content = bytearray(f.read())
        content[-1] ^= 0xFF  # Flip bit
        f.seek(0)
        f.write(content)

    km_tampered = KeyManager(key_dir=key_dir, master_secret="test-secret")
    with pytest.raises(KeyIntegrityError):
        km_tampered.get_or_create_encryption_key("vault-aes", version=1)
