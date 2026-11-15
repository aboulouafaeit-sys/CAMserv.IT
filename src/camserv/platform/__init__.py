"""camserv.platform package exports."""
from camserv.platform.adaptive_manager import (
    AdaptationAction,
    AdaptiveResourceManager,
    ResourceSnapshot,
)
from camserv.platform.appliance import (
    ApplianceCatalog,
    ApplianceCapabilityProfile,
    ApplianceHardwareManager,
    ApplianceProfileType,
    ApplianceSpecification,
    StorageEnduranceMetrics,
    ThermalState,
    ThermalStatus,
)
from camserv.platform.hardware import GPUCapability, HardwareDetector, HardwareProfile
from camserv.platform.tiers import HardwareTier, TierConfiguration, TierPolicyEngine

__all__ = [
    "AdaptationAction",
    "AdaptiveResourceManager",
    "ApplianceCatalog",
    "ApplianceCapabilityProfile",
    "ApplianceHardwareManager",
    "ApplianceProfileType",
    "ApplianceSpecification",
    "GPUCapability",
    "HardwareDetector",
    "HardwareProfile",
    "HardwareTier",
    "ResourceSnapshot",
    "StorageEnduranceMetrics",
    "ThermalState",
    "ThermalStatus",
    "TierConfiguration",
    "TierPolicyEngine",
]
