"""
tests/test_commercial_editions.py
=================================

Unit and contract tests for CAMserv Commercial Editions, Feature Gating,
Capacity Limits, and SBOM Generation (Phase 3 Stage 10).
"""

import pytest

from camserv.config.editions import (
    EditionCapabilityExceededError,
    EditionRegistry,
    ProductEdition,
)
from scripts.generate_sbom import generate_sbom


def test_edition_capabilities_matrix() -> None:
    """Verify capabilities across Community, Professional, and Enterprise editions."""
    comm = EditionRegistry.get_capabilities(ProductEdition.COMMUNITY)
    pro = EditionRegistry.get_capabilities(ProductEdition.PROFESSIONAL)
    ent = EditionRegistry.get_capabilities(ProductEdition.ENTERPRISE)

    # Camera capacity bounds
    assert comm.max_cameras == 4
    assert pro.max_cameras == 16
    assert ent.max_cameras == 1024

    # Hardware acceleration
    assert comm.allow_hardware_acceleration is False
    assert pro.allow_hardware_acceleration is True
    assert ent.allow_hardware_acceleration is True

    # Multi-site central management
    assert comm.allow_multi_site_central is False
    assert pro.allow_multi_site_central is False
    assert ent.allow_multi_site_central is True

    # Multi-tenancy
    assert comm.allow_multi_tenancy is False
    assert pro.allow_multi_tenancy is False
    assert ent.allow_multi_tenancy is True

    # Dual-control quorum
    assert comm.allow_dual_control_quorum is False
    assert pro.allow_dual_control_quorum is True
    assert ent.allow_dual_control_quorum is True

    # Critical invariant: Fail-closed privacy MUST be enforced on ALL editions
    assert comm.fail_closed_privacy_enforced is True
    assert pro.fail_closed_privacy_enforced is True
    assert ent.fail_closed_privacy_enforced is True


def test_camera_allocation_limits() -> None:
    """Verify camera allocation enforcement against edition limits."""
    # Community: 4 is ok, 5 raises
    EditionRegistry.validate_camera_allocation(ProductEdition.COMMUNITY, 4)
    with pytest.raises(EditionCapabilityExceededError, match="permits up to 4 cameras"):
        EditionRegistry.validate_camera_allocation(ProductEdition.COMMUNITY, 5)

    # Professional: 16 is ok, 17 raises
    EditionRegistry.validate_camera_allocation(ProductEdition.PROFESSIONAL, 16)
    with pytest.raises(EditionCapabilityExceededError, match="permits up to 16 cameras"):
        EditionRegistry.validate_camera_allocation(ProductEdition.PROFESSIONAL, 17)

    # Enterprise: 1000 is ok, 1025 raises
    EditionRegistry.validate_camera_allocation(ProductEdition.ENTERPRISE, 1000)
    with pytest.raises(EditionCapabilityExceededError, match="permits up to 1024 cameras"):
        EditionRegistry.validate_camera_allocation(ProductEdition.ENTERPRISE, 1025)


def test_feature_access_gating() -> None:
    """Verify enterprise feature gating prevents unauthorized activation."""
    # Community denies multi_site, multi_tenancy, dual_control_quorum
    with pytest.raises(EditionCapabilityExceededError, match="Feature 'multi_site' is not available"):
        EditionRegistry.validate_feature_access(ProductEdition.COMMUNITY, "multi_site")

    with pytest.raises(EditionCapabilityExceededError, match="Feature 'multi_tenancy' is not available"):
        EditionRegistry.validate_feature_access(ProductEdition.COMMUNITY, "multi_tenancy")

    # Pro allows dual_control_quorum and hardware_acceleration, but denies multi_site
    EditionRegistry.validate_feature_access(ProductEdition.PROFESSIONAL, "dual_control_quorum")
    EditionRegistry.validate_feature_access(ProductEdition.PROFESSIONAL, "hardware_acceleration")
    with pytest.raises(EditionCapabilityExceededError, match="Feature 'multi_site' is not available"):
        EditionRegistry.validate_feature_access(ProductEdition.PROFESSIONAL, "multi_site")

    # Enterprise allows all enterprise features
    EditionRegistry.validate_feature_access(ProductEdition.ENTERPRISE, "multi_site")
    EditionRegistry.validate_feature_access(ProductEdition.ENTERPRISE, "multi_tenancy")
    EditionRegistry.validate_feature_access(ProductEdition.ENTERPRISE, "dual_control_quorum")
    EditionRegistry.validate_feature_access(ProductEdition.ENTERPRISE, "signed_ota_updates")


def test_sbom_generation_and_compliance(tmp_path) -> None:
    """Verify CycloneDX SBOM generation and permissive commercial licensing compliance."""
    sbom_path = tmp_path / "test-sbom.json"
    sbom = generate_sbom(output_path=sbom_path, format_type="cyclonedx")

    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert len(sbom["components"]) > 0

    # Ensure output file was written and is valid JSON
    assert sbom_path.exists()

    # Verify licensing audit
    audit = sbom["audit_summary"]
    assert audit["is_permissive_compliant"] is True
    assert len(audit["copyleft_findings"]) == 0
