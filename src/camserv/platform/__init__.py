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
from camserv.platform.factory import (
    get_active_platform_name,
    get_platform_camera_backend,
    get_platform_credential_vault,
    get_platform_filesystem,
    get_platform_hardware_prober,
    get_platform_service_manager,
    is_linux,
    is_windows,
)
from camserv.platform.shared.paths import PathResolver, PlatformPaths

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
    "PathResolver",
    "PlatformPaths",
    "ResourceSnapshot",
    "StorageEnduranceMetrics",
    "ThermalState",
    "ThermalStatus",
    "TierConfiguration",
    "TierPolicyEngine",
    "get_active_platform_name",
    "get_platform_camera_backend",
    "get_platform_credential_vault",
    "get_platform_filesystem",
    "get_platform_hardware_prober",
    "get_platform_service_manager",
    "is_linux",
    "is_windows",
]
