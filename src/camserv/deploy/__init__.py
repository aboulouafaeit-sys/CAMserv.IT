"""camserv.deploy package exports."""
from camserv.deploy.supervisor import (
    ApplianceServiceConfig,
    ApplianceServiceState,
    ApplianceServiceSupervisor,
    DisasterRecoveryManager,
    WatchdogNotifier,
)
from camserv.deploy.updater import (
    DeploymentChannel,
    PackageIntegrityError,
    SignedUpdateManager,
    UpdatePackageManifest,
    UpdateSignatureError,
    VersionIncompatibilityError,
)

__all__ = [
    "ApplianceServiceConfig",
    "ApplianceServiceState",
    "ApplianceServiceSupervisor",
    "DeploymentChannel",
    "DisasterRecoveryManager",
    "PackageIntegrityError",
    "SignedUpdateManager",
    "UpdatePackageManifest",
    "UpdateSignatureError",
    "VersionIncompatibilityError",
    "WatchdogNotifier",
]
