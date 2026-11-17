"""
camserv.workspace
=================

Phase 23 Advanced Operator Experience & Multi-Monitor Workspace Package.
"""

from camserv.workspace.engine import DynamicCameraLayoutEngine
from camserv.workspace.event_focus import (
    EventDrivenFocusController,
    FocusPolicyMode,
    FocusState,
)
from camserv.workspace.models import (
    CameraTile,
    DisplayLayout,
    LayoutPreset,
    OperationalContext,
    PanelVisibility,
    ResourceProfile,
    WorkspaceConfig,
)
from camserv.workspace.resource_policy import (
    OperatorResourcePolicyEngine,
    StreamAllocationPolicy,
)
from camserv.workspace.storage import (
    WorkspaceSecurityError,
    WorkspaceStorageManager,
)

__all__ = [
    "CameraTile",
    "DisplayLayout",
    "DynamicCameraLayoutEngine",
    "EventDrivenFocusController",
    "FocusPolicyMode",
    "FocusState",
    "LayoutPreset",
    "OperationalContext",
    "OperatorResourcePolicyEngine",
    "PanelVisibility",
    "ResourceProfile",
    "StreamAllocationPolicy",
    "WorkspaceConfig",
    "WorkspaceSecurityError",
    "WorkspaceStorageManager",
]
