"""
camserv.workspace.models
========================

Domain models and schemas for Multi-Monitor Workspaces, Dynamic Camera Layouts,
and Operator Operational Contexts.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class LayoutPreset(str, enum.Enum):
    """Supported grid layout presets for multi-camera viewports."""

    SINGLE = "1x1"       # 1 camera (focused)
    SPLIT = "1x2"        # 2 cameras (side by side)
    GRID_1X1 = "1x1"
    GRID_1X2 = "1x2"
    GRID_2X2 = "2x2"     # 4 cameras (2x2 quad)
    GRID_3X3 = "3x3"     # 9 cameras (3x3 standard)
    GRID_4X4 = "4x4"     # 16 cameras (4x4 high density)
    GRID_5X5 = "5x5"     # 25 cameras (5x5 enterprise video wall)
    CUSTOM = "custom"    # Custom arrangement (e.g. 1 major + 5 minor)


class OperationalContext(str, enum.Enum):
    """Operational monitoring context preset for operator desks."""

    GENERAL_MONITORING = "general"
    PERIMETER_MONITORING = "perimeter"
    INCIDENT_INVESTIGATION = "investigation"
    TECHNICAL_DIAGNOSTICS = "diagnostics"
    MULTI_SITE_MONITORING = "multi_site"

    # Convenient aliases
    GENERAL = "general"
    PERIMETER = "perimeter"
    INVESTIGATION = "investigation"
    DIAGNOSTICS = "diagnostics"
    MULTI_SITE = "multi_site"


class ResourceProfile(str, enum.Enum):
    """Capability-aware resource consumption and stream quality profile."""

    LOW_RESOURCE = "low"
    BALANCED = "balanced"
    HIGH_PERFORMANCE = "high"
    OPERATOR_CONFIGURED = "custom"

    # Convenient aliases
    LOW = "low"
    HIGH = "high"
    CUSTOM = "custom"


@dataclass
class CameraTile:
    """A single viewport slot within a display layout grid."""

    camera_id: str
    grid_row: int = 0
    grid_col: int = 0
    stream_type: str = "main"  # "main", "sub", "paused"
    tile_id: str = ""
    position_index: int = 0
    col_span: int = 1
    row_span: int = 1
    is_maximized: bool = False
    is_focused: bool = False
    is_muted: bool = True
    custom_label: str = ""
    stream_quality: str = "main"
    truthfulness_state: str = "unverified"

    def __post_init__(self) -> None:
        if not self.tile_id:
            self.tile_id = f"tile_{self.camera_id or 'empty'}_{self.grid_row}_{self.grid_col}"
        if not self.stream_type:
            self.stream_type = self.stream_quality or "main"


@dataclass
class DisplayLayout:
    """The camera tile grid assigned to a specific physical display monitor."""

    display_id: str
    preset: LayoutPreset
    rows: int = 2
    cols: int = 2
    tiles: list[CameraTile] = field(default_factory=list)
    max_columns: int = 2
    maximized_tile_id: str | None = None
    custom_ratios: list[float] | None = None

    def __post_init__(self) -> None:
        if self.cols != self.max_columns and self.max_columns == 2 and self.cols != 2:
            self.max_columns = self.cols


@dataclass
class PanelVisibility:
    """Visibility states of peripheral operator desk panels."""

    show_camera_inventory: bool = True
    show_alert_panel: bool = True
    show_timeline_panel: bool = True
    show_cluster_panel: bool = True
    show_diagnostics_panel: bool = False
    show_resource_meters: bool = True


@dataclass
class WorkspaceConfig:
    """
    Complete configuration for an operator workspace session.
    Persisted safely without secrets, passwords, or authentication tokens.
    """

    workspace_id: str
    name: str
    description: str = ""
    operational_context: OperationalContext = OperationalContext.GENERAL_MONITORING
    resource_profile: ResourceProfile = ResourceProfile.BALANCED
    display_layouts: dict[str, DisplayLayout] = field(default_factory=dict)
    displays: list[DisplayLayout] = field(default_factory=list)
    panels: PanelVisibility = field(default_factory=PanelVisibility)
    panel_visibility: PanelVisibility = field(default_factory=PanelVisibility)
    version: int = 2
    schema_version: str = "2.0"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.displays and not self.display_layouts:
            self.display_layouts = {d.display_id: d for d in self.displays}
        elif self.display_layouts and not self.displays:
            self.displays = list(self.display_layouts.values())
        if self.panel_visibility and not self.panels:
            self.panels = self.panel_visibility

    def to_dict(self) -> dict[str, Any]:
        """Convert workspace configuration to clean dictionary for JSON serialization."""
        return {
            "version": self.version,
            "schema_version": self.schema_version,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "operational_context": self.operational_context.value,
            "resource_profile": self.resource_profile.value,
            "displays": [
                {
                    "display_id": dl.display_id,
                    "preset": dl.preset.value,
                    "rows": dl.rows,
                    "cols": dl.cols,
                    "max_columns": dl.max_columns,
                    "maximized_tile_id": dl.maximized_tile_id,
                    "custom_ratios": dl.custom_ratios,
                    "tiles": [
                        {
                            "tile_id": t.tile_id,
                            "camera_id": t.camera_id,
                            "grid_row": t.grid_row,
                            "grid_col": t.grid_col,
                            "position_index": t.position_index,
                            "col_span": t.col_span,
                            "row_span": t.row_span,
                            "is_maximized": t.is_maximized,
                            "is_focused": t.is_focused,
                            "is_muted": t.is_muted,
                            "custom_label": t.custom_label,
                            "stream_quality": t.stream_quality,
                            "stream_type": t.stream_type,
                            "truthfulness_state": t.truthfulness_state,
                        }
                        for t in dl.tiles
                    ],
                }
                for dl in self.displays
            ],
            "display_layouts": {
                d_id: {
                    "display_id": dl.display_id,
                    "preset": dl.preset.value,
                    "rows": dl.rows,
                    "cols": dl.cols,
                    "max_columns": dl.max_columns,
                    "maximized_tile_id": dl.maximized_tile_id,
                    "custom_ratios": dl.custom_ratios,
                    "tiles": [
                        {
                            "tile_id": t.tile_id,
                            "camera_id": t.camera_id,
                            "grid_row": t.grid_row,
                            "grid_col": t.grid_col,
                            "position_index": t.position_index,
                            "col_span": t.col_span,
                            "row_span": t.row_span,
                            "is_maximized": t.is_maximized,
                            "is_focused": t.is_focused,
                            "is_muted": t.is_muted,
                            "custom_label": t.custom_label,
                            "stream_quality": t.stream_quality,
                            "stream_type": t.stream_type,
                            "truthfulness_state": t.truthfulness_state,
                        }
                        for t in dl.tiles
                    ],
                }
                for d_id, dl in self.display_layouts.items()
            },
            "panels": {
                "show_camera_inventory": self.panels.show_camera_inventory,
                "show_alert_panel": self.panels.show_alert_panel,
                "show_timeline_panel": self.panels.show_timeline_panel,
                "show_cluster_panel": self.panels.show_cluster_panel,
                "show_diagnostics_panel": self.panels.show_diagnostics_panel,
                "show_resource_meters": self.panels.show_resource_meters,
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceConfig:
        """Parse validated dictionary into WorkspaceConfig domain model with schema migration."""
        # 1. Handle legacy format / schema migration
        raw_version = data.get("version", data.get("schema_version", 2))
        try:
            version = int(float(str(raw_version).replace("v", "")))
        except Exception:
            version = 2

        ws_id = str(data.get("workspace_id") or data.get("id") or "ws_default")
        name = str(data.get("name") or data.get("title") or "Workspace")
        desc = str(data.get("description", ""))

        ctx_val = data.get("operational_context", data.get("context", "general"))
        try:
            op_context = OperationalContext(ctx_val)
        except ValueError:
            op_context = OperationalContext.GENERAL_MONITORING

        prof_val = data.get("resource_profile", data.get("profile", "balanced"))
        try:
            res_profile = ResourceProfile(prof_val)
        except ValueError:
            res_profile = ResourceProfile.BALANCED

        # Parse panels
        p_raw = data.get("panels") or data.get("panel_visibility", {})
        panels = PanelVisibility(
            show_camera_inventory=bool(p_raw.get("show_camera_inventory", True)),
            show_alert_panel=bool(p_raw.get("show_alert_panel", True)),
            show_timeline_panel=bool(p_raw.get("show_timeline_panel", True)),
            show_cluster_panel=bool(p_raw.get("show_cluster_panel", True)),
            show_diagnostics_panel=bool(p_raw.get("show_diagnostics_panel", False)),
            show_resource_meters=bool(p_raw.get("show_resource_meters", True)),
        )

        # Parse display layouts
        d_layouts: dict[str, DisplayLayout] = {}
        displays_list: list[DisplayLayout] = []

        raw_displays = data.get("displays")
        if isinstance(raw_displays, list) and raw_displays:
            for dl_data in raw_displays:
                p_str = dl_data.get("preset", "2x2")
                try:
                    preset = LayoutPreset(p_str)
                except ValueError:
                    preset = LayoutPreset.GRID_2X2

                tiles: list[CameraTile] = []
                for idx, t_data in enumerate(dl_data.get("tiles", [])):
                    tile = CameraTile(
                        camera_id=str(t_data.get("camera_id", "")),
                        grid_row=int(t_data.get("grid_row", idx // 2)),
                        grid_col=int(t_data.get("grid_col", idx % 2)),
                        stream_type=str(t_data.get("stream_type", "main")),
                        tile_id=str(t_data.get("tile_id", f"tile_{idx}")),
                        position_index=int(t_data.get("position_index", idx)),
                        col_span=int(t_data.get("col_span", 1)),
                        row_span=int(t_data.get("row_span", 1)),
                        is_maximized=bool(t_data.get("is_maximized", False)),
                        is_focused=bool(t_data.get("is_focused", False)),
                        is_muted=bool(t_data.get("is_muted", True)),
                        custom_label=str(t_data.get("custom_label", "")),
                        stream_quality=str(t_data.get("stream_quality", "main")),
                        truthfulness_state=str(t_data.get("truthfulness_state", "unverified")),
                    )
                    tiles.append(tile)

                d_obj = DisplayLayout(
                    display_id=str(dl_data.get("display_id", f"mon_{len(displays_list)}")),
                    preset=preset,
                    rows=int(dl_data.get("rows", 2)),
                    cols=int(dl_data.get("cols", dl_data.get("max_columns", 2))),
                    tiles=tiles,
                    max_columns=int(dl_data.get("max_columns", 2)),
                    maximized_tile_id=dl_data.get("maximized_tile_id"),
                    custom_ratios=dl_data.get("custom_ratios"),
                )
                displays_list.append(d_obj)
                d_layouts[d_obj.display_id] = d_obj

        elif isinstance(data.get("display_layouts"), dict) and data.get("display_layouts"):
            for d_id, dl_data in data["display_layouts"].items():
                p_str = dl_data.get("preset", "2x2")
                try:
                    preset = LayoutPreset(p_str)
                except ValueError:
                    preset = LayoutPreset.GRID_2X2

                tiles = []
                for idx, t_data in enumerate(dl_data.get("tiles", [])):
                    tile = CameraTile(
                        camera_id=str(t_data.get("camera_id", "")),
                        grid_row=int(t_data.get("grid_row", idx // 2)),
                        grid_col=int(t_data.get("grid_col", idx % 2)),
                        stream_type=str(t_data.get("stream_type", "main")),
                        tile_id=str(t_data.get("tile_id", f"tile_{d_id}_{idx}")),
                        position_index=int(t_data.get("position_index", idx)),
                        col_span=int(t_data.get("col_span", 1)),
                        row_span=int(t_data.get("row_span", 1)),
                        is_maximized=bool(t_data.get("is_maximized", False)),
                        is_focused=bool(t_data.get("is_focused", False)),
                        is_muted=bool(t_data.get("is_muted", True)),
                        custom_label=str(t_data.get("custom_label", "")),
                        stream_quality=str(t_data.get("stream_quality", "main")),
                        truthfulness_state=str(t_data.get("truthfulness_state", "unverified")),
                    )
                    tiles.append(tile)

                d_obj = DisplayLayout(
                    display_id=d_id,
                    preset=preset,
                    rows=int(dl_data.get("rows", 2)),
                    cols=int(dl_data.get("cols", dl_data.get("max_columns", 2))),
                    tiles=tiles,
                    max_columns=int(dl_data.get("max_columns", 2)),
                    maximized_tile_id=dl_data.get("maximized_tile_id"),
                    custom_ratios=dl_data.get("custom_ratios"),
                )
                displays_list.append(d_obj)
                d_layouts[d_id] = d_obj

        elif "cameras" in data:
            # Legacy v1 migration from flat cameras array
            legacy_cams = data["cameras"]
            p_map = {
                "grid_1": LayoutPreset.SINGLE,
                "grid_2": LayoutPreset.SPLIT,
                "grid_4": LayoutPreset.GRID_2X2,
                "grid_9": LayoutPreset.GRID_3X3,
                "grid_16": LayoutPreset.GRID_4X4,
            }
            preset = p_map.get(str(data.get("layout", "grid_4")), LayoutPreset.GRID_2X2)
            cols = 2 if preset == LayoutPreset.GRID_2X2 else (3 if preset == LayoutPreset.GRID_3X3 else 2)
            tiles = [
                CameraTile(
                    camera_id=cid,
                    grid_row=i // cols,
                    grid_col=i % cols,
                    position_index=i,
                )
                for i, cid in enumerate(legacy_cams)
            ]
            d_obj = DisplayLayout(
                display_id="primary",
                preset=preset,
                rows=max(1, len(tiles) // cols),
                cols=cols,
                tiles=tiles,
            )
            displays_list.append(d_obj)
            d_layouts["primary"] = d_obj

        return cls(
            workspace_id=ws_id,
            name=name,
            description=desc,
            operational_context=op_context,
            resource_profile=res_profile,
            display_layouts=d_layouts,
            displays=displays_list,
            panels=panels,
            panel_visibility=panels,
            version=2,
            schema_version="2.0",
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )
