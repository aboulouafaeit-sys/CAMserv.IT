"""
camserv.config.editions
=======================

Product edition definitions, feature gating, camera capacity limits,
and licensing validation for CAMserv Community, Professional, and Enterprise tiers.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ProductEdition(str, enum.Enum):
    """Officially supported commercial and open-source product editions."""

    COMMUNITY = "community"        # Free / Open Source, single-node, up to 4 cameras, Apache-2.0 models
    PROFESSIONAL = "professional"  # Turnkey appliance edition, up to 16 cameras, hardware acceleration
    ENTERPRISE = "enterprise"      # Clustered multi-site edition, unlimited cameras, RBAC, Central fleet


class EditionCapabilityExceededError(PermissionError):
    """Raised when an operation or camera count exceeds the licensed product edition."""


@dataclass(slots=True)
class EditionCapabilities:
    """Feature matrix and operational boundaries for an edition tier."""

    edition: ProductEdition
    display_name: str
    max_cameras: int
    allow_hardware_acceleration: bool
    allow_multi_site_central: bool
    allow_multi_tenancy: bool
    allow_dual_control_quorum: bool
    allow_signed_ota_updates: bool
    fail_closed_privacy_enforced: bool = True  # Non-negotiable across ALL editions!
    model_backend_default: str = "permissive_onnx_apache"

    def to_dict(self) -> dict[str, Any]:
        """Serialize edition specifications."""
        return {
            "edition": self.edition.value,
            "display_name": self.display_name,
            "max_cameras": self.max_cameras,
            "allow_hardware_acceleration": self.allow_hardware_acceleration,
            "allow_multi_site_central": self.allow_multi_site_central,
            "allow_multi_tenancy": self.allow_multi_tenancy,
            "allow_dual_control_quorum": self.allow_dual_control_quorum,
            "allow_signed_ota_updates": self.allow_signed_ota_updates,
            "fail_closed_privacy_enforced": self.fail_closed_privacy_enforced,
            "model_backend_default": self.model_backend_default,
        }


class EditionRegistry:
    """Standardized product edition capability definitions."""

    EDITIONS: dict[ProductEdition, EditionCapabilities] = {
        ProductEdition.COMMUNITY: EditionCapabilities(
            edition=ProductEdition.COMMUNITY,
            display_name="CAMserv Community Edition",
            max_cameras=4,
            allow_hardware_acceleration=False,
            allow_multi_site_central=False,
            allow_multi_tenancy=False,
            allow_dual_control_quorum=False,
            allow_signed_ota_updates=False,
            fail_closed_privacy_enforced=True,
            model_backend_default="permissive_onnx_apache",
        ),
        ProductEdition.PROFESSIONAL: EditionCapabilities(
            edition=ProductEdition.PROFESSIONAL,
            display_name="CAMserv Professional Appliance Edition",
            max_cameras=16,
            allow_hardware_acceleration=True,
            allow_multi_site_central=False,
            allow_multi_tenancy=False,
            allow_dual_control_quorum=True,
            allow_signed_ota_updates=True,
            fail_closed_privacy_enforced=True,
            model_backend_default="permissive_onnx_apache",
        ),
        ProductEdition.ENTERPRISE: EditionCapabilities(
            edition=ProductEdition.ENTERPRISE,
            display_name="CAMserv Enterprise Clustered Edition",
            max_cameras=1024,
            allow_hardware_acceleration=True,
            allow_multi_site_central=True,
            allow_multi_tenancy=True,
            allow_dual_control_quorum=True,
            allow_signed_ota_updates=True,
            fail_closed_privacy_enforced=True,
            model_backend_default="permissive_onnx_apache",
        ),
    }

    @classmethod
    def get_capabilities(cls, edition: ProductEdition | str) -> EditionCapabilities:
        """Retrieve capabilities for a given edition."""
        e = ProductEdition(edition) if isinstance(edition, str) else edition
        return cls.EDITIONS.get(e, cls.EDITIONS[ProductEdition.COMMUNITY])

    @classmethod
    def validate_camera_allocation(cls, edition: ProductEdition | str, requested_cameras: int) -> None:
        """Validate that requested camera count does not exceed edition limit."""
        caps = cls.get_capabilities(edition)
        if requested_cameras > caps.max_cameras:
            logger.warning(
                "editions.camera_limit_exceeded",
                edition=caps.edition.value,
                requested=requested_cameras,
                limit=caps.max_cameras,
            )
            raise EditionCapabilityExceededError(
                f"LICENSE LIMIT EXCEEDED: {caps.display_name} permits up to {caps.max_cameras} cameras. "
                f"Requested {requested_cameras} streams. Upgrade to a higher edition to expand capacity."
            )

    @classmethod
    def validate_feature_access(cls, edition: ProductEdition | str, feature_name: str) -> None:
        """Validate that the edition supports the requested enterprise feature."""
        caps = cls.get_capabilities(edition)
        feature_map = {
            "multi_site": caps.allow_multi_site_central,
            "multi_tenancy": caps.allow_multi_tenancy,
            "dual_control_quorum": caps.allow_dual_control_quorum,
            "signed_ota_updates": caps.allow_signed_ota_updates,
            "hardware_acceleration": caps.allow_hardware_acceleration,
        }

        if feature_name in feature_map and not feature_map[feature_name]:
            logger.warning("editions.feature_denied", edition=caps.edition.value, feature=feature_name)
            raise EditionCapabilityExceededError(
                f"FEATURE RESTRICTED: Feature '{feature_name}' is not available in {caps.display_name}. "
                "Upgrade to CAMserv Enterprise to activate this capability."
            )
