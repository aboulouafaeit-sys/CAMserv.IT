"""
CAMserv — Phase 23: Advanced Operator Experience, Multi-Monitor Video Wall
& Intelligent Surveillance Workspace Qualification Test Suite.

Verifies:
1. Cross-platform display managers (Windows EnumDisplayMonitors, Linux xrandr/DRM/headless).
2. Window geometry bounds clamping against physical monitor rects.
3. Dynamic camera layout engine (1x1 to 5x5 presets, tile reordering, maximize/restore).
4. Stream truthfulness states and epistemic integrity.
5. Persistent workspace storage, schema migration, path traversal prevention, 512KB size limits.
6. Prohibited credential stripping from untrusted workspace JSON.
7. Adaptive operator resource policy engine and hardware probing.
8. Event-driven camera focus controller with cooldown anti-stealing and 1-click restore.
9. Desktop Operator Console headless integration and secondary video wall lifecycle.
"""

import os
import sys
import json
import tempfile
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from camserv.platform.shared.interfaces import DisplayGeometry, DisplayInfo
from camserv.platform.windows.display import WindowsDisplayManager
from camserv.platform.linux.display import LinuxDisplayManager
from camserv.platform.factory import get_platform_display_manager
from camserv.workspace.models import (
    LayoutPreset,
    OperationalContext,
    ResourceProfile,
    CameraTile,
    DisplayLayout,
    PanelVisibility,
    WorkspaceConfig,
)
from camserv.workspace.engine import DynamicCameraLayoutEngine
from camserv.workspace.storage import WorkspaceStorageManager
from camserv.workspace.resource_policy import OperatorResourcePolicyEngine
from camserv.workspace.event_focus import EventDrivenFocusController
from camserv.desktop.console import DesktopOperatorConsole


# ==============================================================================
# 1. Platform Display Management Tests
# ==============================================================================

class TestPlatformDisplayManager:
    """Verifies physical display enumeration and geometry validation across platforms."""

    def test_factory_returns_platform_manager(self):
        manager = get_platform_display_manager()
        assert manager is not None
        displays = manager.get_displays()
        assert len(displays) >= 1
        primary = manager.get_primary_display()
        assert primary is not None
        assert primary.is_primary is True
        assert primary.geometry.width > 0
        assert primary.geometry.height > 0

    def test_windows_display_manager_geometry_clamping(self):
        manager = WindowsDisplayManager()
        displays = manager.get_displays()
        assert len(displays) >= 1
        prim = manager.get_primary_display()

        # Test valid geometry remains unchanged
        clamped_x, clamped_y, clamped_w, clamped_h = manager.validate_window_geometry(
            prim.geometry.x + 50,
            prim.geometry.y + 50,
            800,
            600
        )
        assert clamped_x == prim.geometry.x + 50
        assert clamped_y == prim.geometry.y + 50
        assert clamped_w == 800
        assert clamped_h == 600

        # Test completely offscreen coordinates are clamped onto monitor
        clamped_off_x, clamped_off_y, _, _ = manager.validate_window_geometry(
            -9999, -9999, 800, 600
        )
        assert clamped_off_x >= prim.geometry.x
        assert clamped_off_y >= prim.geometry.y

        # Test oversize window clamped to monitor width/height
        _, _, clamped_big_w, clamped_big_h = manager.validate_window_geometry(
            prim.geometry.x, prim.geometry.y, 99999, 99999
        )
        assert clamped_big_w <= prim.geometry.width
        assert clamped_big_h <= prim.geometry.height

    def test_linux_display_manager_xrandr_parsing(self):
        sample_xrandr = """
Screen 0: minimum 320 x 200, current 3840 x 1080, maximum 16384 x 16384
HDMI-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+
DP-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+
VGA-1 disconnected (normal left inverted right x axis y axis)
"""
        parsed = LinuxDisplayManager._parse_xrandr_output(sample_xrandr)
        assert len(parsed) == 2

        disp1 = parsed[0]
        assert disp1.display_id == "LINUX_HDMI_1"
        assert disp1.is_primary is True
        assert disp1.geometry.width == 1920
        assert disp1.geometry.height == 1080
        assert disp1.geometry.x == 0
        assert disp1.geometry.y == 0

        disp2 = parsed[1]
        assert disp2.display_id == "LINUX_DP_1"
        assert disp2.is_primary is False
        assert disp2.geometry.x == 1920

    def test_linux_display_manager_headless_fallback(self):
        manager = LinuxDisplayManager()
        # In test environments without real xrandr/DRM, manager provides virtual primary
        displays = manager.get_displays()
        assert len(displays) >= 1
        primary = manager.get_primary_display()
        assert primary.is_primary is True
        assert primary.geometry.width >= 1024
        assert primary.geometry.height >= 720

    def test_mock_display_manager_listeners(self):
        mock_displays = [
            DisplayInfo("mon-1", "Monitor 1", DisplayGeometry(0, 0, 1920, 1080), True, 1.0),
            DisplayInfo("mon-2", "Monitor 2", DisplayGeometry(1920, 0, 1920, 1080), False, 1.0)
        ]
        mgr = get_platform_display_manager(mock_displays=mock_displays)
        assert len(mgr.get_displays()) == 2
        assert mgr.get_display_by_id("mon-2").geometry.x == 1920

        events = []
        mgr.register_display_change_listener(lambda displays: events.append(len(displays)))
        mgr.trigger_display_change()
        assert len(events) == 1
        assert events[0] == 2


# ==============================================================================
# 2. Dynamic Camera Layout Engine Tests
# ==============================================================================

class TestDynamicCameraLayoutEngine:
    """Verifies layout presets, tile assignment, maximize/restore, and truthfulness."""

    @pytest.fixture
    def camera_ids(self):
        return [f"cam-test-{i:02d}" for i in range(1, 26)]

    def test_all_layout_presets_capacity_and_grid(self, camera_ids):
        engine = DynamicCameraLayoutEngine()

        presets_expected = [
            (LayoutPreset.GRID_1X1, 1, 1, 1),
            (LayoutPreset.GRID_1X2, 1, 2, 2),
            (LayoutPreset.GRID_2X2, 2, 2, 4),
            (LayoutPreset.GRID_3X3, 3, 3, 9),
            (LayoutPreset.GRID_4X4, 4, 4, 16),
            (LayoutPreset.GRID_5X5, 5, 5, 25),
            (LayoutPreset.CUSTOM, 4, 4, 16),
        ]

        for preset, expected_r, expected_c, expected_cap in presets_expected:
            layout = engine.create_layout_from_cameras(
                preset=preset,
                camera_ids=camera_ids,
                display_id="primary_mon"
            )
            assert layout.preset == preset
            assert layout.rows == expected_r
            assert layout.cols == expected_c
            assert len(layout.tiles) == expected_cap

    def test_tile_reorder_and_swap(self, camera_ids):
        engine = DynamicCameraLayoutEngine()
        layout = engine.create_layout_from_cameras(
            preset=LayoutPreset.GRID_2X2,
            camera_ids=camera_ids[:4]
        )
        assert layout.tiles[0].camera_id == "cam-test-01"
        assert layout.tiles[1].camera_id == "cam-test-02"

        # Swap index 0 and index 1
        updated = engine.swap_tiles(layout, 0, 1)
        assert updated.tiles[0].camera_id == "cam-test-02"
        assert updated.tiles[1].camera_id == "cam-test-01"
        assert updated.tiles[0].grid_col == 0
        assert updated.tiles[1].grid_col == 1

    def test_maximize_and_restore_tile(self, camera_ids):
        engine = DynamicCameraLayoutEngine()
        layout = engine.create_layout_from_cameras(
            preset=LayoutPreset.GRID_2X2,
            camera_ids=camera_ids[:4]
        )
        assert engine.get_maximized_tile(layout) is None

        # Maximize cam-test-03
        maxed_layout = engine.maximize_tile(layout, "cam-test-03")
        max_tile = engine.get_maximized_tile(maxed_layout)
        assert max_tile is not None
        assert max_tile.camera_id == "cam-test-03"
        assert max_tile.is_maximized is True

        # Restore
        restored_layout = engine.restore_tile(maxed_layout)
        assert engine.get_maximized_tile(restored_layout) is None
        assert all(not t.is_maximized for t in restored_layout.tiles)

    def test_stream_truthfulness_evaluation(self, camera_ids):
        engine = DynamicCameraLayoutEngine()
        layout = engine.create_layout_from_cameras(
            preset=LayoutPreset.GRID_2X2,
            camera_ids=camera_ids[:4]
        )

        # Initially unverified
        assert layout.tiles[0].truthfulness_state == "unverified"

        # Update with active leases and hw probe
        active_leases = {"cam-test-01": "node-1", "cam-test-02": "node-2"}
        evaluated = engine.evaluate_stream_truthfulness(
            layout,
            active_leases=active_leases,
            hardware_probed_cameras={"cam-test-01"}
        )

        assert evaluated.tiles[0].truthfulness_state == "verified_live"
        assert evaluated.tiles[1].truthfulness_state == "simulated"
        assert evaluated.tiles[2].truthfulness_state == "evacuated_offline"


# ==============================================================================
# 3. Persistent Workspace Storage & Security Tests
# ==============================================================================

class TestWorkspaceStorageManager:
    """Verifies workspace serialization, JSON schema migration, and traversal defense."""

    @pytest.fixture
    def temp_storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = WorkspaceStorageManager(storage_dir=tmpdir)
            yield mgr, tmpdir

    def test_crud_workspace(self, temp_storage):
        mgr, _ = temp_storage
        tile = CameraTile("cam-01", 0, 0, "main", is_focused=False, truthfulness_state="verified_live")
        disp = DisplayLayout("disp-01", LayoutPreset.GRID_2X2, 2, 2, [tile])
        ws = WorkspaceConfig(
            workspace_id="test_ops_01",
            name="Operations Center 1",
            description="Active duty desk",
            operational_context=OperationalContext.GENERAL,
            resource_profile=ResourceProfile.BALANCED,
            displays=[disp],
            panel_visibility=PanelVisibility()
        )

        # Save
        assert mgr.save_workspace(ws) is True
        assert mgr.workspace_exists("test_ops_01") is True

        # Load
        loaded = mgr.load_workspace("test_ops_01")
        assert loaded is not None
        assert loaded.workspace_id == "test_ops_01"
        assert loaded.name == "Operations Center 1"
        assert loaded.operational_context == OperationalContext.GENERAL
        assert len(loaded.displays) == 1
        assert loaded.displays[0].tiles[0].camera_id == "cam-01"

        # List
        ws_list = mgr.list_workspaces()
        assert len(ws_list) == 1
        assert ws_list[0]["workspace_id"] == "test_ops_01"

        # Delete
        assert mgr.delete_workspace("test_ops_01") is True
        assert mgr.workspace_exists("test_ops_01") is False

    def test_path_traversal_prevention(self, temp_storage):
        mgr, _ = temp_storage
        malicious_ids = [
            "../../etc/passwd",
            "..\\..\\Windows\\System32\\calc.exe",
            "../secret_workspace",
            "subdir/evil",
            "evil/../../root",
            "ws*evil",
            "ws;rm -rf /",
            "a" * 100,  # exceeds 64 chars
        ]

        tile = CameraTile("cam-01", 0, 0, "main")
        disp = DisplayLayout("disp-01", LayoutPreset.GRID_1X1, 1, 1, [tile])

        for evil_id in malicious_ids:
            with pytest.raises(ValueError):
                ws = WorkspaceConfig(
                    workspace_id=evil_id,
                    name="Evil",
                    displays=[disp]
                )
                mgr.save_workspace(ws)

            with pytest.raises(ValueError):
                mgr.load_workspace(evil_id)

            with pytest.raises(ValueError):
                mgr.delete_workspace(evil_id)

    def test_oversized_payload_rejection(self, temp_storage):
        mgr, _ = temp_storage
        huge_data = {"workspace_id": "huge_ws", "name": "A" * (600 * 1024)}
        huge_json = json.dumps(huge_data)

        with pytest.raises(ValueError, match="exceeds maximum allowed size"):
            mgr.import_workspace_from_json(huge_json)

    def test_prohibited_credential_stripping(self, temp_storage):
        mgr, _ = temp_storage
        untrusted_payload = {
            "schema_version": "2.0",
            "workspace_id": "import_test",
            "name": "Untrusted External Desk",
            "operational_context": "perimeter",
            "resource_profile": "high_performance",
            "password": "SuperSecretPassword123",
            "auth_token": "Bearer eyJhbGciOi...",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----",
            "displays": [
                {
                    "display_id": "mon-1",
                    "preset": "2x2",
                    "rows": 2,
                    "cols": 2,
                    "tiles": [
                        {"camera_id": "cam-01", "grid_row": 0, "grid_col": 0, "secret": "leak_attempt"}
                    ]
                }
            ]
        }
        imported = mgr.import_workspace_from_json(json.dumps(untrusted_payload))
        assert imported.workspace_id == "import_test"
        assert imported.name == "Untrusted External Desk"

        # Check export does not contain secrets
        exported_str = mgr.export_workspace_to_json(imported)
        exported_lower = exported_str.lower()
        assert "supersecretpassword" not in exported_lower
        assert "auth_token" not in exported_lower
        assert "private_key" not in exported_lower
        assert "leak_attempt" not in exported_lower

    def test_schema_v1_migration(self, temp_storage):
        mgr, _ = temp_storage
        # Legacy v1 format with flat camera_ids and legacy grid layout
        v1_payload = {
            "version": 1,
            "id": "legacy_desk_01",
            "title": "Old Control Desk",
            "layout": "grid_4",
            "cameras": ["cam-01", "cam-02", "cam-03", "cam-04"]
        }
        migrated = mgr.import_workspace_from_json(json.dumps(v1_payload))
        assert migrated.schema_version == "2.0"
        assert migrated.workspace_id == "legacy_desk_01"
        assert migrated.name == "Old Control Desk"
        assert len(migrated.displays) == 1
        assert migrated.displays[0].preset == LayoutPreset.GRID_2X2
        assert len(migrated.displays[0].tiles) == 4


# ==============================================================================
# 4. Adaptive Resource Policy Engine Tests
# ==============================================================================

class TestAdaptiveResourcePolicyEngine:
    """Verifies resource profile policies, stream concurrency limits, and hardware probing."""

    def test_hardware_inspection_truthfulness(self):
        engine = OperatorResourcePolicyEngine()
        hw = engine.inspect_hardware_capability()
        assert "gpu_detected" in hw
        assert "gpu_model" in hw
        assert "vram_mb" in hw
        assert "cpu_cores" in hw
        assert hw["cpu_cores"] >= 1
        # Honest hardware reporting: if GPU detected, model must not be empty; if not, indicates CPU fallback
        if hw["gpu_detected"]:
            assert len(hw["gpu_model"]) > 0
        else:
            assert "CPU" in hw["gpu_model"]

    def test_resource_profiles_specs(self):
        engine = OperatorResourcePolicyEngine()

        low = engine.get_profile_spec(ResourceProfile.LOW_RESOURCE)
        assert low["max_concurrent_streams"] == 4
        assert low["preferred_stream_type"] == "sub"
        assert low["target_fps"] <= 15
        assert low["enable_glassmorphism"] is False

        balanced = engine.get_profile_spec(ResourceProfile.BALANCED)
        assert balanced["max_concurrent_streams"] == 9
        assert balanced["target_fps"] == 20
        assert balanced["enable_glassmorphism"] is True

        high = engine.get_profile_spec(ResourceProfile.HIGH_PERFORMANCE)
        assert high["max_concurrent_streams"] >= 16
        assert high["preferred_stream_type"] == "main"
        assert high["target_fps"] >= 25
        assert high["enable_glassmorphism"] is True

    def test_stream_allocation_for_layout(self):
        engine = OperatorResourcePolicyEngine()
        layout_engine = DynamicCameraLayoutEngine()
        cam_ids = [f"cam-{i:02d}" for i in range(1, 10)]

        # 3x3 layout with 9 cameras
        layout = layout_engine.create_layout_from_cameras(
            preset=LayoutPreset.GRID_3X3,
            camera_ids=cam_ids
        )

        # Under LOW profile (capacity 4), tiles beyond 4 become paused / degraded
        allocated_low = engine.allocate_streams_for_layout(layout, ResourceProfile.LOW_RESOURCE)
        active_tiles = [t for t in allocated_low.tiles if t.stream_type != "paused"]
        assert len(active_tiles) <= 4

        # Under HIGH profile, all 9 tiles get main or high quality streams
        allocated_high = engine.allocate_streams_for_layout(layout, ResourceProfile.HIGH_PERFORMANCE)
        assert all(t.stream_type == "main" for t in allocated_high.tiles)


# ==============================================================================
# 5. Event-Driven Camera Focus Controller Tests
# ==============================================================================

class TestEventDrivenFocusController:
    """Verifies cooldown anti-stealing, non-consequential tagging, and 1-click restore."""

    @pytest.fixture
    def layout_with_four_cams(self):
        engine = DynamicCameraLayoutEngine()
        return engine.create_layout_from_cameras(
            preset=LayoutPreset.GRID_2X2,
            camera_ids=["cam-01", "cam-02", "cam-03", "cam-04"]
        )

    def test_event_focus_trigger_and_restore(self, layout_with_four_cams):
        controller = EventDrivenFocusController(cooldown_seconds=5.0)

        alert_event = {
            "id": "evt-test-101",
            "camera_id": "cam-03",
            "type": "perimeter_intrusion_hypothesis",
            "confidence": 0.88,
            "severity": "high"
        }

        # Trigger candidate focus
        focused_layout, state = controller.trigger_event_focus(layout_with_four_cams, alert_event)
        assert state["is_focused"] is True
        assert state["active_camera_id"] == "cam-03"
        assert state["non_consequential_tag"] == "candidate_hypothesis"

        # Check cam-03 is now focused / maximized
        focused_tile = next((t for t in focused_layout.tiles if t.camera_id == "cam-03"), None)
        assert focused_tile is not None
        assert focused_tile.is_focused is True

        # 1-Click Restore
        restored_layout = controller.restore_focus(focused_layout)
        assert controller.get_state()["is_focused"] is False
        assert all(not t.is_focused for t in restored_layout.tiles)

    def test_cooldown_anti_stealing(self, layout_with_four_cams):
        controller = EventDrivenFocusController(cooldown_seconds=10.0)

        first_event = {
            "id": "evt-01",
            "camera_id": "cam-01",
            "type": "fence_climb_hypothesis",
            "confidence": 0.92,
            "severity": "critical"
        }
        controller.trigger_event_focus(layout_with_four_cams, first_event)
        assert controller.get_state()["active_camera_id"] == "cam-01"

        # Immediate lower or equal priority event on different camera should be ignored during cooldown
        second_event = {
            "id": "evt-02",
            "camera_id": "cam-02",
            "type": "loitering_candidate",
            "confidence": 0.65,
            "severity": "medium"
        }
        _, state2 = controller.trigger_event_focus(layout_with_four_cams, second_event)
        # Should NOT steal focus
        assert state2["active_camera_id"] == "cam-01"

    def test_unknown_camera_rejected(self, layout_with_four_cams):
        controller = EventDrivenFocusController()
        unknown_event = {
            "id": "evt-99",
            "camera_id": "cam-nonexistent",
            "type": "unknown_event",
            "confidence": 0.50
        }
        res_layout, state = controller.trigger_event_focus(layout_with_four_cams, unknown_event)
        assert state["is_focused"] is False


# ==============================================================================
# 6. Desktop Operator Console Integration Tests
# ==============================================================================

class TestDesktopOperatorConsolePhase23:
    """Verifies Tkinter desktop console multi-monitor, workspace, and layout actions."""

    def test_console_initialization_and_multi_monitor_state(self):
        console = DesktopOperatorConsole(headless=True)
        assert console.display_manager is not None
        assert console.layout_engine is not None
        assert console.workspace_storage is not None
        assert console.policy_engine is not None
        assert console.focus_controller is not None

        displays = console.display_manager.get_displays()
        assert len(displays) >= 1
        assert console.current_layout_preset == LayoutPreset.GRID_2X2

    def test_console_layout_switching_and_maximize_restore(self):
        console = DesktopOperatorConsole(headless=True)
        assert len(console.active_layout.tiles) == 4

        # Switch to 3x3 layout
        console._apply_layout_preset(LayoutPreset.GRID_3X3)
        assert console.current_layout_preset == LayoutPreset.GRID_3X3
        assert len(console.active_layout.tiles) == 9

        # Maximize tile 2
        target_cam = console.active_layout.tiles[1].camera_id
        console._on_tile_maximize(target_cam)
        max_tile = console.layout_engine.get_maximized_tile(console.active_layout)
        assert max_tile is not None
        assert max_tile.camera_id == target_cam

        # Restore tile
        console._on_tile_restore()
        assert console.layout_engine.get_maximized_tile(console.active_layout) is None

    def test_console_video_wall_toggle_and_destroy(self):
        console = DesktopOperatorConsole(headless=True)
        assert console.video_wall_window is None

        # Pop out video wall
        console.toggle_video_wall()
        assert console.video_wall_window is not None
        assert console.video_wall_window.winfo_exists()

        # Toggle again to close
        console.toggle_video_wall()
        assert console.video_wall_window is None

    def test_console_context_and_profile_cycling(self):
        console = DesktopOperatorConsole(headless=True)

        # Context change to perimeter
        console._on_context_change(OperationalContext.PERIMETER.value)
        assert console.current_context == OperationalContext.PERIMETER
        assert console.current_layout_preset == LayoutPreset.GRID_1X2

        # Profile change to high performance
        console._on_profile_change(ResourceProfile.HIGH_PERFORMANCE.value)
        assert console.current_profile == ResourceProfile.HIGH_PERFORMANCE
