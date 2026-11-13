"""Configuration validation tests for CAMserv.

Verifies:
- Default configuration settings instantiate and validate cleanly
- Environment variable overrides using CAMSERV_ prefix and __ delimiter
- Camera source configuration URL schema and ID regex validation
- Detection confidence threshold bounds enforcement (0.01 - 1.0)
- Privacy settings defaults and constraints (odd blur kernel, retention periods)
- Security configuration validation (TLS cert/key requirements, JWT secret length)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from camserv.config.settings import (
    CamerasSettings,
    CameraSource,
    CamservSettings,
    InferenceDevice,
    InferenceSettings,
    JWTSettings,
    PrivacySettings,
    PrivacyZone,
    SecuritySettings,
)

VALID_JWT_SECRET = "test-jwt-secret-key-that-is-at-least-32-chars-long"


@pytest.mark.unit
def test_default_settings_valid() -> None:
    """Verify that complete platform settings instantiate and validate successfully with test defaults."""
    settings = CamservSettings(
        security=SecuritySettings(
            jwt=JWTSettings(secret_key=VALID_JWT_SECRET),
        )
    )

    assert settings.app_name == "CAMserv"
    assert settings.environment == "development"
    assert settings.inference.confidence_threshold == 0.45
    assert settings.tracking.max_age == 70
    assert settings.storage.milvus.dim == settings.tracking.embedding_dim


@pytest.mark.unit
def test_env_var_override() -> None:
    """Verify environment variables override configuration parameters via CAMSERV_ prefix."""
    env_overrides = {
        "CAMSERV_APP_NAME": "CAMserv_Production_Node",
        "CAMSERV_ENVIRONMENT": "staging",
        "CAMSERV_INFERENCE__CONFIDENCE_THRESHOLD": "0.72",
        "CAMSERV_SECURITY__JWT__SECRET_KEY": VALID_JWT_SECRET,
    }

    with patch.dict(os.environ, env_overrides, clear=False):
        settings = CamservSettings(
            security=SecuritySettings(
                jwt=JWTSettings(secret_key=VALID_JWT_SECRET),
            )
        )
        assert settings.app_name == "CAMserv_Production_Node"
        assert settings.environment == "staging"
        assert settings.inference.confidence_threshold == 0.72


@pytest.mark.unit
def test_camera_config_validation() -> None:
    """Verify camera configuration rejects invalid URLs and malformed camera IDs."""
    # Valid camera
    cam = CameraSource(
        id="gate_north-01",
        name="Gate North",
        url="rtsp://admin:pass@10.0.0.1:554/stream1",
    )
    assert cam.id == "gate_north-01"

    # Invalid URL scheme (ftp:// not allowed)
    with pytest.raises(ValidationError):
        CameraSource(
            id="cam1",
            name="Cam 1",
            url="ftp://10.0.0.1/video",
        )

    # Invalid ID with disallowed special characters
    with pytest.raises(ValidationError):
        CameraSource(
            id="cam#invalid!",
            name="Cam Bad ID",
            url="rtsp://10.0.0.1/live",
        )


@pytest.mark.unit
def test_invalid_confidence_threshold_rejected() -> None:
    """Verify that inference confidence thresholds outside [0.01, 1.0] are rejected."""
    # Too low (< 0.01)
    with pytest.raises(ValidationError):
        InferenceSettings(confidence_threshold=0.0)

    # Too high (> 1.0)
    with pytest.raises(ValidationError):
        InferenceSettings(confidence_threshold=1.05)


@pytest.mark.unit
def test_privacy_config_defaults() -> None:
    """Verify privacy settings defaults adhere to GDPR requirements and blur kernel rules."""
    privacy = PrivacySettings()

    # Kernel size must be an odd number for Gaussian blur
    assert privacy.face_blur_strength % 2 == 1
    assert privacy.auto_purge_enabled is True
    assert privacy.gdpr_erasure_enabled is True
    assert privacy.data_retention_hours > 0

    # Even kernel size must fail validation
    with pytest.raises(ValidationError):
        PrivacySettings(face_blur_strength=30)  # Even number


@pytest.mark.unit
def test_security_config_validation() -> None:
    """Verify security configuration enforces TLS path completeness and JWT secret length."""
    # JWT secret too short (< 32 chars)
    with pytest.raises(ValidationError):
        JWTSettings(secret_key="short-key")

    # TLS enabled without cert or key paths must fail validation
    with pytest.raises(ValidationError):
        SecuritySettings(
            jwt=JWTSettings(secret_key=VALID_JWT_SECRET),
            tls_enabled=True,
            tls_cert_path=None,
            tls_key_path=None,
        )
