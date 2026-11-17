"""camserv.platform package exports."""
from camserv.platform.accelerator import (
    AcceleratorAbstractionManager,
    AcceleratorBackendType,
    AcceleratorDevice,
    AcceleratorLifecycleState,
)
from camserv.platform.adaptive_manager import (
    AdaptationAction,
    AdaptiveResourceManager,
    ResourceOperatingState,
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
from camserv.platform.hardware import GPUCapability, HardwareDetector, HardwareProfile
from camserv.platform.shared.paths import PathResolver, PlatformPaths
from camserv.platform.stability import (
    BoundedPipelineQueue,
    NonBlockingExecutor,
    QueueOverflowPolicy,
    QueueTelemetry,
    ServicePriority,
    WorkerCrashSupervisor,
    calculate_backoff_with_jitter,
)
from camserv.platform.tiers import HardwareTier, TierConfiguration, TierPolicyEngine

__all__ = [
    "AcceleratorAbstractionManager",
    "AcceleratorBackendType",
    "AcceleratorDevice",
    "AcceleratorLifecycleState",
    "AdaptationAction",
    "AdaptiveResourceManager",
    "ApplianceCatalog",
    "ApplianceCapabilityProfile",
    "ApplianceHardwareManager",
    "ApplianceProfileType",
    "ApplianceSpecification",
    "BoundedPipelineQueue",
    "GPUCapability",
    "HardwareDetector",
    "HardwareProfile",
    "HardwareTier",
    "NonBlockingExecutor",
    "PathResolver",
    "PlatformPaths",
    "QueueOverflowPolicy",
    "QueueTelemetry",
    "ResourceOperatingState",
    "ResourceSnapshot",
    "ServicePriority",
    "StorageEnduranceMetrics",
    "ThermalState",
    "ThermalStatus",
    "TierConfiguration",
    "TierPolicyEngine",
    "WorkerCrashSupervisor",
    "calculate_backoff_with_jitter",
    "get_active_platform_name",
    "get_platform_camera_backend",
    "get_platform_credential_vault",
    "get_platform_filesystem",
    "get_platform_hardware_prober",
    "get_platform_service_manager",
    "is_linux",
    "is_windows",
]
