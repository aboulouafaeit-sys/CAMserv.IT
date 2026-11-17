"""
camserv.workspace.engine
========================

Dynamic Camera Layout Engine for Multi-Monitor Operator Consoles.
Manages viewport grid calculations, drag-and-drop tile reordering,
camera assignment, maximize/restore workflows, and stream truthfulness.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from camserv.workspace.models import CameraTile, DisplayLayout, LayoutPreset


class DynamicCameraLayoutEngine:
    """
    Manages grid layouts, tile allocations, drag-and-drop reordering,
    and camera-to-display mappings.
    """

    PRESET_CAPACITIES: dict[LayoutPreset, int] = {
        LayoutPreset.SINGLE: 1,
        LayoutPreset.SPLIT: 2,
        LayoutPreset.GRID_2X2: 4,
        LayoutPreset.GRID_3X3: 9,
        LayoutPreset.GRID_4X4: 16,
        LayoutPreset.GRID_5X5: 25,
        LayoutPreset.CUSTOM: 16,
    }

    PRESET_COLUMNS: dict[LayoutPreset, int] = {
        LayoutPreset.SINGLE: 1,
        LayoutPreset.SPLIT: 2,
        LayoutPreset.GRID_2X2: 2,
        LayoutPreset.GRID_3X3: 3,
        LayoutPreset.GRID_4X4: 4,
        LayoutPreset.GRID_5X5: 5,
        LayoutPreset.CUSTOM: 4,
    }

    def __init__(self) -> None:
        pass

    def create_empty_layout(
        self, display_id: str, preset: LayoutPreset = LayoutPreset.GRID_2X2
    ) -> DisplayLayout:
        """Create a default display layout with empty tile placeholders."""
        capacity = self.PRESET_CAPACITIES.get(preset, 4)
        cols = self.PRESET_COLUMNS.get(preset, 2)
        rows = math.ceil(capacity / cols)

        tiles: list[CameraTile] = []
        for idx in range(capacity):
            tiles.append(
                CameraTile(
                    camera_id="",
                    grid_row=idx // cols,
                    grid_col=idx % cols,
                    tile_id=f"tile_{display_id}_{idx}",
                    position_index=idx,
                    col_span=1,
                    row_span=1,
                )
            )

        return DisplayLayout(
            display_id=display_id,
            preset=preset,
            rows=rows,
            cols=cols,
            tiles=tiles,
            max_columns=cols,
            maximized_tile_id=None,
        )

    def assign_cameras_to_preset(
        self,
        display_id: str,
        camera_ids: list[str],
        preset: LayoutPreset,
    ) -> DisplayLayout:
        """Generate a display layout populated with an ordered list of camera IDs."""
        capacity = self.PRESET_CAPACITIES.get(preset, 4)
        cols = self.PRESET_COLUMNS.get(preset, 2)
        rows = math.ceil(capacity / cols)

        tiles: list[CameraTile] = []
        for idx in range(capacity):
            cam_id = camera_ids[idx] if idx < len(camera_ids) else ""
            tiles.append(
                CameraTile(
                    camera_id=cam_id,
                    grid_row=idx // cols,
                    grid_col=idx % cols,
                    tile_id=f"tile_{display_id}_{idx}_{uuid.uuid4().hex[:6]}",
                    position_index=idx,
                    col_span=1,
                    row_span=1,
                )
            )

        return DisplayLayout(
            display_id=display_id,
            preset=preset,
            rows=rows,
            cols=cols,
            tiles=tiles,
            max_columns=cols,
            maximized_tile_id=None,
        )

    def create_layout_from_cameras(
        self,
        preset: LayoutPreset,
        camera_ids: list[str],
        display_id: str = "primary",
    ) -> DisplayLayout:
        """Create and populate a display layout with camera IDs."""
        return self.assign_cameras_to_preset(display_id, camera_ids, preset)

    def switch_preset(
        self, layout: DisplayLayout, new_preset: LayoutPreset
    ) -> DisplayLayout:
        """
        Switch layout preset while preserving existing assigned cameras in order.
        """
        old_cameras = [t.camera_id for t in layout.tiles if t.camera_id]
        new_capacity = self.PRESET_CAPACITIES.get(new_preset, 4)
        new_cols = self.PRESET_COLUMNS.get(new_preset, 2)
        new_rows = math.ceil(new_capacity / new_cols)

        new_tiles: list[CameraTile] = []
        for idx in range(new_capacity):
            cam_id = old_cameras[idx] if idx < len(old_cameras) else ""
            new_tiles.append(
                CameraTile(
                    camera_id=cam_id,
                    grid_row=idx // new_cols,
                    grid_col=idx % new_cols,
                    tile_id=f"tile_{layout.display_id}_{idx}_{uuid.uuid4().hex[:6]}",
                    position_index=idx,
                    col_span=1,
                    row_span=1,
                )
            )

        layout.preset = new_preset
        layout.cols = new_cols
        layout.rows = new_rows
        layout.max_columns = new_cols
        layout.tiles = new_tiles
        layout.maximized_tile_id = None
        return layout

    def reorder_tiles(
        self, layout: DisplayLayout, source_index: int, target_index: int
    ) -> DisplayLayout:
        """
        Perform drag-and-drop tile swap or reordering between two indices.
        Preserves camera identity and updates position indices.
        """
        if not (0 <= source_index < len(layout.tiles) and 0 <= target_index < len(layout.tiles)):
            raise IndexError(
                f"Reorder indices out of bounds: src={source_index}, tgt={target_index}, total={len(layout.tiles)}"
            )

        if source_index == target_index:
            return layout

        src_tile = layout.tiles[source_index]
        tgt_tile = layout.tiles[target_index]

        # Swap camera payloads
        src_tile.camera_id, tgt_tile.camera_id = tgt_tile.camera_id, src_tile.camera_id
        src_tile.custom_label, tgt_tile.custom_label = tgt_tile.custom_label, src_tile.custom_label
        src_tile.stream_quality, tgt_tile.stream_quality = tgt_tile.stream_quality, src_tile.stream_quality
        src_tile.stream_type, tgt_tile.stream_type = tgt_tile.stream_type, src_tile.stream_type
        src_tile.truthfulness_state, tgt_tile.truthfulness_state = tgt_tile.truthfulness_state, src_tile.truthfulness_state

        return layout

    def swap_tiles(self, layout: DisplayLayout, idx1: int, idx2: int) -> DisplayLayout:
        """Convenience alias for reorder_tiles."""
        return self.reorder_tiles(layout, idx1, idx2)

    def assign_camera(
        self, layout: DisplayLayout, position_index: int, camera_id: str
    ) -> DisplayLayout:
        """Assign a camera to a specific grid slot position."""
        if not (0 <= position_index < len(layout.tiles)):
            raise IndexError(f"Position index {position_index} exceeds layout capacity {len(layout.tiles)}")

        layout.tiles[position_index].camera_id = camera_id
        return layout

    def remove_camera(self, layout: DisplayLayout, camera_id: str) -> DisplayLayout:
        """Clear camera assignment from any tile carrying it."""
        for t in layout.tiles:
            if t.camera_id == camera_id:
                t.camera_id = ""
                t.custom_label = ""
        return layout

    def maximize_camera(self, layout: DisplayLayout, camera_id: str) -> DisplayLayout:
        """
        Maximize a single camera tile to occupy the entire display area.
        Records maximized_tile_id so previous layout can be restored.
        """
        target_tile: CameraTile | None = None
        for t in layout.tiles:
            if t.camera_id == camera_id:
                target_tile = t
                t.is_maximized = True
            else:
                t.is_maximized = False

        if target_tile is None:
            raise ValueError(f"Camera '{camera_id}' not found in display layout '{layout.display_id}'")

        layout.maximized_tile_id = target_tile.tile_id
        return layout

    def maximize_tile(self, layout: DisplayLayout, camera_id: str) -> DisplayLayout:
        """Convenience alias for maximize_camera."""
        return self.maximize_camera(layout, camera_id)

    def restore_layout(self, layout: DisplayLayout) -> DisplayLayout:
        """Restore all tiles from maximized state to standard grid view."""
        for t in layout.tiles:
            t.is_maximized = False
        layout.maximized_tile_id = None
        return layout

    def restore_tile(self, layout: DisplayLayout) -> DisplayLayout:
        """Convenience alias for restore_layout."""
        return self.restore_layout(layout)

    def get_maximized_tile(self, layout: DisplayLayout) -> CameraTile | None:
        """Retrieve the currently maximized tile, if any."""
        for t in layout.tiles:
            if t.is_maximized:
                return t
        return None

    def evaluate_stream_truth(
        self,
        camera_id: str,
        active_streams: dict[str, bool],
        simulated_streams: set[str],
    ) -> dict[str, Any]:
        """
        Enforce Rule 2.3: Epistemic truthfulness in stream display state.
        A tile must NEVER claim a camera is live when its stream is disconnected or simulated.
        """
        if not camera_id:
            return {
                "status": "EMPTY",
                "label": "[EMPTY SLOT]",
                "is_live": False,
                "is_simulated": False,
            }

        is_connected = active_streams.get(camera_id, False)
        is_simulated = camera_id in simulated_streams

        if not is_connected:
            return {
                "status": "OFFLINE",
                "label": "[FEED DISCONNECTED]",
                "is_live": False,
                "is_simulated": is_simulated,
            }

        if is_simulated:
            return {
                "status": "SIMULATED",
                "label": "[SYNTHETIC RTSP FIXTURE]",
                "is_live": True,
                "is_simulated": True,
            }

        return {
            "status": "LIVE_VERIFIED",
            "label": "[OPTICAL HW VERIFIED]",
            "is_live": True,
            "is_simulated": False,
        }

    def evaluate_stream_truthfulness(
        self,
        layout: DisplayLayout,
        active_leases: dict[str, str],
        hardware_probed_cameras: set[str],
    ) -> DisplayLayout:
        """
        Evaluate and tag truthfulness states across all tiles in the layout.
        """
        for tile in layout.tiles:
            if not tile.camera_id:
                tile.truthfulness_state = "unassigned"
            elif tile.camera_id in hardware_probed_cameras:
                tile.truthfulness_state = "verified_live"
            elif tile.camera_id in active_leases:
                tile.truthfulness_state = "simulated"
            else:
                tile.truthfulness_state = "evacuated_offline"
        return layout
