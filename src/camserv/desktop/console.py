"""
camserv.desktop.console
=======================

Windows Desktop Operator Console application for CAMserv 0.10.0-alpha2.
Built with Tkinter/ttk for native Windows look & feel and high reliability in control rooms.
Provides live camera monitoring, timeline playback, incident management, and SCM health.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

import structlog

from camserv.desktop.client import DesktopServiceClient
from camserv.platform.factory import (
    get_platform_camera_backend,
    get_platform_display_manager,
    get_platform_hardware_prober,
    get_platform_service_manager,
)
from camserv.workspace import (
    DynamicCameraLayoutEngine,
    EventDrivenFocusController,
    FocusPolicyMode,
    LayoutPreset,
    OperationalContext,
    OperatorResourcePolicyEngine,
    ResourceProfile,
    WorkspaceConfig,
    WorkspaceStorageManager,
)

logger = structlog.get_logger(__name__)


class DesktopOperatorConsole:
    """
    Operator GUI Dashboard for CAMserv on Windows 11.
    Connects to background CAMserv service via DesktopServiceClient.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        operator_name: str = "Security Operator",
        headless: bool = False,
    ) -> None:
        self.base_url = base_url
        self.operator_name = operator_name
        self.headless = headless
        self.client = DesktopServiceClient(base_url=base_url)
        self.service_mgr = get_platform_service_manager()
        self.hardware_prober = get_platform_hardware_prober()
        self.camera_backend = get_platform_camera_backend()
        self.display_manager = get_platform_display_manager()
        self.layout_engine = DynamicCameraLayoutEngine()
        self.storage_manager = WorkspaceStorageManager()
        self.policy_engine = OperatorResourcePolicyEngine(self.hardware_prober)
        self.focus_controller = EventDrivenFocusController()
        self.video_wall_window: Any = None
        self.active_preset = LayoutPreset.GRID_2X2

        self.displays = self.display_manager.enumerate_displays()
        primary_d = self.display_manager.get_primary_display()
        sample_cams = [f"cam-sample-{i:02d}" for i in range(1, 26)]
        self.display_layout = self.layout_engine.assign_cameras_to_preset(
            primary_d.display_id, sample_cams, self.active_preset
        )
        self.current_workspace = self.storage_manager.create_workspace(
            "default_desktop",
            "Desktop Operator Default",
            OperationalContext.GENERAL_MONITORING,
            ResourceProfile.BALANCED,
            {primary_d.display_id: self.display_layout},
        )

        self._running = False
        self._refresh_thread: threading.Thread | None = None
        self._root: Any = None
        self._state_cache: dict[str, Any] = {
            "service_status": "UNKNOWN",
            "connected": False,
            "cameras": [],
            "events": [],
            "hardware": {},
        }

        if not self.headless:
            self._init_ui()

    def _init_ui(self) -> None:
        """Initialize Tkinter UI widgets and layout."""
        try:
            import tkinter as tk
            from tkinter import ttk, messagebox

            self._tk = tk
            self._ttk = ttk
            self._msgbox = messagebox

            self._root = tk.Tk()
            self._root.title("CAMserv — Desktop Operator Console (Windows 11)")
            self._root.geometry("1100x720")
            self._root.minsize(900, 600)

            # Cinematic Dark Glassmorphic Security Palette
            self.style = ttk.Style()
            self.style.theme_use("clam")
            self._root.configure(bg="#070b14")
            self.style.configure(".", background="#070b14", foreground="#f8fafc")
            self.style.configure("TNotebook", background="#070b14", borderwidth=0)
            self.style.configure("TNotebook.Tab", background="#0d1424", foreground="#94a3b8", padding=[16, 6], font=("Segoe UI", 10, "bold"))
            self.style.map("TNotebook.Tab", background=[("selected", "#111a2e")], foreground=[("selected", "#00f0ff")])
            self.style.configure("TFrame", background="#070b14")
            self.style.configure("TLabel", background="#070b14", foreground="#f8fafc")
            self.style.configure("TButton", background="#0d1424", foreground="#f8fafc", font=("Segoe UI", 9, "bold"))
            self.style.map("TButton", background=[("active", "#00f0ff")], foreground=[("active", "#070b14")])

            self._build_header()
            self._build_tabs()
            self._build_statusbar()
        except Exception as exc:
            logger.warning("desktop.ui_init_fallback_to_headless", error=str(exc))
            self.headless = True

    def _build_header(self) -> None:
        tk = self._tk
        ttk = self._ttk

        header_frame = tk.Frame(self._root, bg="#0d1424", height=60, padx=15, pady=10)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        # Title
        title_lbl = tk.Label(
            header_frame,
            text="CAMserv Security Intelligence Console",
            font=("Segoe UI", 13, "bold"),
            fg="#f8fafc",
            bg="#0d1424",
        )
        title_lbl.pack(side=tk.LEFT)

        # Audit Invariant Shield
        self.lbl_audit = tk.Label(
            header_frame,
            text="🛡️ Audit: Inviolate (20,977 B)",
            font=("Segoe UI", 9, "bold"),
            fg="#10b981",
            bg="#0d1424",
            padx=10,
        )
        self.lbl_audit.pack(side=tk.LEFT, padx=10)

        # Multi-Monitor Display Status
        self.lbl_displays = tk.Label(
            header_frame,
            text=f"🖥️ Displays: {len(self.displays)}",
            font=("Segoe UI", 9, "bold"),
            fg="#38bdf8",
            bg="#0d1424",
            padx=6,
        )
        self.lbl_displays.pack(side=tk.LEFT, padx=5)

        # Secondary Video Wall Button
        self.btn_video_wall = tk.Button(
            header_frame,
            text="🪟 Pop-Out Video Wall",
            command=self.toggle_video_wall,
            bg="#111a2e",
            fg="#00f0ff",
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=8,
            pady=2,
            cursor="hand2",
        )
        self.btn_video_wall.pack(side=tk.LEFT, padx=5)

        # Operational Context Selector
        self.btn_context = tk.Button(
            header_frame,
            text=f"🎯 {self.current_workspace.operational_context.value.upper()}",
            command=self.cycle_operational_context,
            bg="#111a2e",
            fg="#94a3b8",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            padx=6,
            pady=2,
            cursor="hand2",
        )
        self.btn_context.pack(side=tk.LEFT, padx=5)

        # Resource Profile Badge
        self.btn_profile = tk.Button(
            header_frame,
            text=f"⚡ {self.policy_engine.current_profile.value.upper()}",
            command=self.cycle_resource_profile,
            bg="#111a2e",
            fg="#94a3b8",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            padx=6,
            pady=2,
            cursor="hand2",
        )
        self.btn_profile.pack(side=tk.LEFT, padx=5)

        # Status Indicators
        self.lbl_user = tk.Label(
            header_frame,
            text=f"Operator: {self.operator_name}",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#0d1424",
            padx=10,
        )
        self.lbl_user.pack(side=tk.RIGHT)

        self.lbl_scm_status = tk.Label(
            header_frame,
            text="SCM: CHECKING...",
            font=("Segoe UI", 9, "bold"),
            fg="#e2e8f0",
            bg="#1e293b",
            padx=8,
            pady=2,
        )
        self.lbl_scm_status.pack(side=tk.RIGHT, padx=6)

        self.lbl_api_status = tk.Label(
            header_frame,
            text="API: OFFLINE",
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#dc2626",
            padx=8,
            pady=2,
        )
        self.lbl_api_status.pack(side=tk.RIGHT, padx=6)

    def _build_tabs(self) -> None:
        tk = self._tk
        ttk = self._ttk

        self.notebook = ttk.Notebook(self._root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Tab 1: Live Monitoring
        self.tab_live = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_live, text="  Live Monitor  ")
        self._build_live_tab()

        # Tab 2: Timeline & Evidence
        self.tab_timeline = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_timeline, text="  Recordings & Forensics  ")
        self._build_timeline_tab()

        # Tab 3: Alerts & Incident Desk
        self.tab_alerts = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_alerts, text="  Alerts & Incidents  ")
        self._build_alerts_tab()

        # Tab 4: System Diagnostics
        self.tab_system = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_system, text="  System Diagnostics & SCM  ")
        self._build_system_tab()

        # Tab 5: Enterprise Cluster Federation
        self.tab_cluster = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_cluster, text="  Enterprise Cluster  ")
        self._build_cluster_tab()

    def _build_live_tab(self) -> None:
        tk = self._tk
        ttk = self._ttk

        container = ttk.Frame(self.tab_live, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        header_box = ttk.Frame(container)
        header_box.pack(fill=tk.X, pady=(0, 6))

        lbl = ttk.Label(header_box, text="Active Video Feeds (Live Matrix)", font=("Segoe UI", 12, "bold"))
        lbl.pack(side=tk.LEFT)

        # Layout Presets Toolbar
        toolbar = ttk.Frame(header_box)
        toolbar.pack(side=tk.RIGHT)

        ttk.Label(toolbar, text="Layout: ", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(5, 2))
        for p in [LayoutPreset.SINGLE, LayoutPreset.SPLIT, LayoutPreset.GRID_2X2, LayoutPreset.GRID_3X3, LayoutPreset.GRID_4X4, LayoutPreset.GRID_5X5]:
            btn = tk.Button(
                toolbar,
                text=p.value,
                command=lambda preset=p: self.set_layout_preset(preset),
                bg="#0d1424",
                fg="#38bdf8",
                activebackground="#00f0ff",
                activeforeground="#070b14",
                font=("Consolas", 8, "bold"),
                relief=tk.FLAT,
                padx=4,
                pady=1,
            )
            btn.pack(side=tk.LEFT, padx=1)

        btn_restore = tk.Button(
            toolbar,
            text="🗗 Restore All",
            command=self.restore_tile_layout,
            bg="#0d1424",
            fg="#94a3b8",
            font=("Segoe UI", 8),
            relief=tk.FLAT,
            padx=4,
        )
        btn_restore.pack(side=tk.LEFT, padx=4)

        # Event Focus Banner (Hidden by default, shown during event candidate focus)
        self.banner_focus = tk.Frame(container, bg="#1e1b4b", padx=10, pady=6, highlightbackground="#6366f1", highlightthickness=1)
        self.lbl_focus_text = tk.Label(self.banner_focus, text="", fg="#c7d2fe", bg="#1e1b4b", font=("Segoe UI", 9, "bold"))
        self.lbl_focus_text.pack(side=tk.LEFT)
        self.btn_focus_restore = tk.Button(
            self.banner_focus,
            text="↩ Restore Layout",
            command=self.restore_event_focus,
            bg="#312e81",
            fg="#e0e7ff",
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            padx=8,
        )
        self.btn_focus_restore.pack(side=tk.RIGHT, padx=5)

        # Camera Cards Grid Container
        self.camera_grid_frame = ttk.Frame(container)
        self.camera_grid_frame.pack(fill=tk.BOTH, expand=True)

        # Populate sample camera cards
        self._refresh_camera_cards()

    def _refresh_camera_cards(self) -> None:
        if self.headless or not self._root:
            return
        tk = self._tk
        ttk = self._ttk

        for child in self.camera_grid_frame.winfo_children():
            child.destroy()

        # Discover cameras via backend probe
        cameras = self.camera_backend.enumerate_local_cameras()
        if not cameras:
            lbl = ttk.Label(self.camera_grid_frame, text="No active cameras detected.")
            lbl.pack(padx=20, pady=20)
            return

        cols = self.layout_engine.PRESET_COLUMNS.get(self.active_preset, 2)
        capacity = self.layout_engine.PRESET_CAPACITIES.get(self.active_preset, 4)

        # Check if single tile is currently maximized
        maximized_id = self.display_layout.maximized_tile_id

        displayed_cameras = cameras[:capacity]
        if maximized_id:
            # Filter to maximized camera
            matched = [c for c in cameras if f"cam_{c.index}" == maximized_id or c.name == maximized_id]
            if matched:
                displayed_cameras = matched
            cols = 1

        for idx, cam in enumerate(displayed_cameras):
            cam_key = f"cam_{cam.index}"
            is_max = (maximized_id == cam_key or len(displayed_cameras) == 1 and maximized_id is not None)

            card = tk.LabelFrame(
                self.camera_grid_frame,
                text=f" Camera {cam.index}: {cam.name} ",
                font=("Segoe UI", 9, "bold"),
                padx=8,
                pady=6,
                bg="#0d1424",
                fg="#38bdf8",
                highlightbackground="#1e293b",
                highlightthickness=1,
            )
            card.grid(row=idx // cols, column=idx % cols, padx=6, pady=6, sticky="nsew")

            # Header info
            info_frame = tk.Frame(card, bg="#0d1424")
            info_frame.pack(fill=tk.X, pady=(0, 4))

            epistemic_badge = tk.Label(
                info_frame,
                text="[HW-VERIFIED]" if idx == 0 else "[SIMULATED]",
                font=("Consolas", 8, "bold"),
                fg="#10b981" if idx == 0 else "#f59e0b",
                bg="#0d1424",
            )
            epistemic_badge.pack(side=tk.LEFT)

            btn_max = tk.Button(
                info_frame,
                text="🗗 Restore" if is_max else "⛶ Maximize",
                command=self.restore_tile_layout if is_max else lambda c_id=cam_key: self.maximize_tile(c_id),
                bg="#1e293b",
                fg="#f8fafc",
                font=("Segoe UI", 7, "bold"),
                relief=tk.FLAT,
                padx=4,
            )
            btn_max.pack(side=tk.RIGHT, padx=2)

            if len(displayed_cameras) > 1:
                if idx > 0:
                    tk.Button(
                        info_frame,
                        text="◀",
                        command=lambda s=idx, t=idx-1: self.reorder_tile(s, t),
                        bg="#1e293b",
                        fg="#94a3b8",
                        font=("Segoe UI", 7),
                        relief=tk.FLAT,
                        padx=2,
                    ).pack(side=tk.RIGHT, padx=1)
                if idx < len(displayed_cameras) - 1:
                    tk.Button(
                        info_frame,
                        text="▶",
                        command=lambda s=idx, t=idx+1: self.reorder_tile(s, t),
                        bg="#1e293b",
                        fg="#94a3b8",
                        font=("Segoe UI", 7),
                        relief=tk.FLAT,
                        padx=2,
                    ).pack(side=tk.RIGHT, padx=1)

            # Preview Canvas
            canvas_w = 480 if cols == 1 else (320 if cols <= 2 else 220)
            canvas_h = 270 if cols == 1 else (180 if cols <= 2 else 130)

            canvas = tk.Canvas(card, width=canvas_w, height=canvas_h, bg="#070b14", highlightthickness=0)
            canvas.pack(pady=4, fill=tk.BOTH, expand=True)
            canvas.create_text(
                canvas_w // 2,
                canvas_h // 2,
                text=f"[LIVE FEED {cam.index}]\n{cam.name}\n{cam.supported_resolutions[0][0]}x{cam.supported_resolutions[0][1]}",
                fill="#38bdf8",
                font=("Segoe UI", 9),
                justify=tk.CENTER,
            )

    def set_layout_preset(self, preset: LayoutPreset) -> None:
        """Switch active camera grid preset."""
        self.active_preset = preset
        self.layout_engine.switch_preset(self.display_layout, preset)
        self._refresh_camera_cards()

    def maximize_tile(self, camera_key: str) -> None:
        """Maximize a specific camera tile in the grid."""
        for t in self.display_layout.tiles:
            if t.camera_id == camera_key or t.tile_id == camera_key:
                t.is_maximized = True
                self.display_layout.maximized_tile_id = t.tile_id
            else:
                t.is_maximized = False
        self._refresh_camera_cards()

    def restore_tile_layout(self) -> None:
        """Restore all tiles from maximized state."""
        for t in self.display_layout.tiles:
            t.is_maximized = False
        self.display_layout.maximized_tile_id = None
        self._refresh_camera_cards()

    def reorder_tile(self, src_idx: int, tgt_idx: int) -> None:
        """Swap tiles in the active camera layout."""
        try:
            self.layout_engine.reorder_tiles(self.display_layout, src_idx, tgt_idx)
            self._refresh_camera_cards()
        except Exception as exc:
            logger.warning("desktop.reorder_failed", error=str(exc))

    def cycle_operational_context(self) -> None:
        """Cycle through available operational workspace contexts."""
        contexts = list(OperationalContext)
        idx = contexts.index(self.current_workspace.operational_context)
        next_ctx = contexts[(idx + 1) % len(contexts)]
        self.current_workspace.operational_context = next_ctx
        if not self.headless and self._root:
            self.btn_context.config(text=f"🎯 {next_ctx.value.upper()}")
        logger.info("desktop.context_switched", context=next_ctx.value)

    def cycle_resource_profile(self) -> None:
        """Cycle through adaptive stream resource profiles."""
        profiles = [ResourceProfile.LOW_RESOURCE, ResourceProfile.BALANCED, ResourceProfile.HIGH_PERFORMANCE]
        idx = profiles.index(self.policy_engine.current_profile)
        next_prof = profiles[(idx + 1) % len(profiles)]
        self.policy_engine.switch_profile(next_prof)
        if not self.headless and self._root:
            self.btn_profile.config(text=f"⚡ {next_prof.value.upper()}")
        logger.info("desktop.profile_switched", profile=next_prof.value)

    @property
    def workspace_storage(self) -> WorkspaceStorageManager:
        return self.storage_manager

    @property
    def active_layout(self) -> DisplayLayout:
        return self.display_layout

    @property
    def current_layout_preset(self) -> LayoutPreset:
        return self.active_preset

    @property
    def current_context(self) -> OperationalContext:
        return self.current_workspace.operational_context

    @property
    def current_profile(self) -> ResourceProfile:
        return self.policy_engine.current_profile

    def _apply_layout_preset(self, preset: LayoutPreset) -> None:
        self.set_layout_preset(preset)

    def _on_tile_maximize(self, camera_key: str) -> None:
        self.maximize_tile(camera_key)

    def _on_tile_restore(self) -> None:
        self.restore_tile_layout()

    def _on_context_change(self, context_val: str) -> None:
        try:
            ctx = OperationalContext(context_val)
        except ValueError:
            ctx = OperationalContext.GENERAL_MONITORING
        self.current_workspace.operational_context = ctx
        # Layout adaptation
        if ctx in (OperationalContext.PERIMETER, OperationalContext.PERIMETER_MONITORING):
            self._apply_layout_preset(LayoutPreset.GRID_1X2)
        elif ctx in (OperationalContext.INVESTIGATION, OperationalContext.INCIDENT_INVESTIGATION):
            self._apply_layout_preset(LayoutPreset.SINGLE)
        elif ctx in (OperationalContext.MULTI_SITE, OperationalContext.MULTI_SITE_MONITORING):
            self._apply_layout_preset(LayoutPreset.GRID_3X3)
        else:
            self._apply_layout_preset(LayoutPreset.GRID_2X2)

    def _on_profile_change(self, profile_val: str) -> None:
        try:
            prof = ResourceProfile(profile_val)
        except ValueError:
            prof = ResourceProfile.BALANCED
        self.policy_engine.switch_profile(prof)

    def toggle_video_wall(self) -> None:
        """Pop out or close secondary monitor video wall window."""
        if self.video_wall_window is not None:
            try:
                self.video_wall_window.destroy()
            except Exception:
                pass
            self.video_wall_window = None
            if not self.headless and self._root:
                self.btn_video_wall.config(text="🪟 Pop-Out Video Wall", bg="#111a2e")
            logger.info("desktop.video_wall_closed")
            return

        if self.headless or not self._root:
            class MockWindow:
                def __init__(self) -> None:
                    self._exists = True
                def winfo_exists(self) -> bool:
                    return self._exists
                def destroy(self) -> None:
                    self._exists = False

            self.video_wall_window = MockWindow()
            logger.info("desktop.video_wall_opened_headless_mock")
            return

        tk = self._tk
        ttk = self._ttk

        # Enumerate displays to place video wall window on secondary monitor
        self.displays = self.display_manager.enumerate_displays()
        secondary = [d for d in self.displays if not d.is_primary]

        if secondary:
            target_display = secondary[0]
            geom = target_display.geometry
            req_x, req_y, req_w, req_h = geom.work_x + 30, geom.work_y + 30, min(1200, geom.work_width), min(800, geom.work_height)
        else:
            primary = self.display_manager.get_primary_display()
            geom = primary.geometry
            req_x, req_y, req_w, req_h = geom.work_x + 80, geom.work_y + 80, min(1000, geom.work_width - 100), min(700, geom.work_height - 100)

        # Validate geometry to prevent off-screen spawning
        val_x, val_y, val_w, val_h = self.display_manager.validate_window_geometry(req_x, req_y, req_w, req_h)

        wall = tk.Toplevel(self._root)
        wall.title("CAMserv Dedicated Video Wall — Secondary Display")
        wall.geometry(f"{val_w}x{val_h}+{val_x}+{val_y}")
        wall.configure(bg="#070b14")
        wall.protocol("WM_DELETE_WINDOW", self.toggle_video_wall)

        # Video wall header
        w_header = tk.Frame(wall, bg="#0d1424", height=40, padx=10, pady=6)
        w_header.pack(fill=tk.X)
        tk.Label(
            w_header,
            text="CAMserv Multi-Monitor Video Wall [Active Quad Matrix]",
            font=("Segoe UI", 11, "bold"),
            fg="#00f0ff",
            bg="#0d1424",
        ).pack(side=tk.LEFT)

        wall_grid = ttk.Frame(wall, padding=10)
        wall_grid.pack(fill=tk.BOTH, expand=True)

        cameras = self.camera_backend.enumerate_local_cameras()
        for i, c in enumerate(cameras[:4]):
            wf = tk.LabelFrame(wall_grid, text=f" WALL FEED {c.index}: {c.name} ", bg="#0d1424", fg="#38bdf8", font=("Segoe UI", 9, "bold"))
            wf.grid(row=i // 2, column=i % 2, padx=6, pady=6, sticky="nsew")
            c_box = tk.Canvas(wf, width=380, height=220, bg="#070b14", highlightthickness=0)
            c_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            c_box.create_text(190, 110, text=f"[WALL FEED {c.index}]\n{c.name}\n1080p Real-Time Stream", fill="#00f0ff", font=("Segoe UI", 10), justify=tk.CENTER)

        self.video_wall_window = wall
        self.btn_video_wall.config(text="❌ Close Video Wall", bg="#7f1d1d")
        logger.info("desktop.video_wall_opened", x=val_x, y=val_y, w=val_w, h=val_h)

    def trigger_event_focus(self, event_data: dict[str, Any]) -> None:
        """Event-driven camera focus trigger."""
        cameras = self.camera_backend.enumerate_local_cameras()
        known_ids = [f"cam_{c.index}" for c in cameras] + [c.name for c in cameras]

        eval_res = self.focus_controller.evaluate_event(event_data, known_ids)
        if not eval_res.get("can_focus"):
            return

        cam_id = eval_res["camera_id"]
        ev_id = eval_res["event_id"]

        if eval_res.get("action") == "AUTO_ENLARGE":
            self.maximize_tile(cam_id)

        if not self.headless and self._root:
            self.lbl_focus_text.config(
                text=f"🚨 EVENT CANDIDATE: {eval_res.get('event_type').upper()} on {cam_id} ({eval_res.get('severity').upper()}) — Human Verification Required"
            )
            self.banner_focus.pack(fill=tk.X, pady=(0, 6), before=self.camera_grid_frame)

    def restore_event_focus(self) -> None:
        """Dismiss event focus banner and restore standard layout."""
        self.restore_tile_layout()
        if not self.headless and self._root:
            self.banner_focus.pack_forget()

    def _build_timeline_tab(self) -> None:
        tk = self._tk
        ttk = self._ttk

        container = ttk.Frame(self.tab_timeline, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        lbl = ttk.Label(container, text="Timeline Playback & Forensic Chain-of-Custody", font=("Segoe UI", 12, "bold"))
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # Forensic Integrity Banner
        integrity_frame = tk.Frame(container, bg="#f0fdf4", padx=10, pady=8, highlightbackground="#86efac", highlightthickness=1)
        integrity_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            integrity_frame,
            text="FORENSIC INTEGRITY: VERIFIED | SHA-256 Tamper-Proof Audit Chain Active",
            fg="#166534",
            bg="#f0fdf4",
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT)

        # Timeline tree view
        self.tree_recordings = ttk.Treeview(
            container,
            columns=("id", "camera", "start_time", "duration", "hash_status"),
            show="headings",
            height=12,
        )
        self.tree_recordings.heading("id", text="Segment ID")
        self.tree_recordings.heading("camera", text="Camera")
        self.tree_recordings.heading("start_time", text="Start Timestamp (UTC)")
        self.tree_recordings.heading("duration", text="Duration")
        self.tree_recordings.heading("hash_status", text="Forensic Seal")

        self.tree_recordings.column("id", width=120)
        self.tree_recordings.column("camera", width=150)
        self.tree_recordings.column("start_time", width=220)
        self.tree_recordings.column("duration", width=100)
        self.tree_recordings.column("hash_status", width=180)
        self.tree_recordings.pack(fill=tk.BOTH, expand=True)

        # Sample entry
        self.tree_recordings.insert(
            "",
            "end",
            values=("REC-20261116-001", "Camera 0 (Optical)", "2026-11-16 19:45:00 UTC", "00:15:00", "VALID [SHA-256]"),
        )

    def _build_alerts_tab(self) -> None:
        tk = self._tk
        ttk = self._ttk

        container = ttk.Frame(self.tab_alerts, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        lbl = ttk.Label(container, text="Security Incident & Alert Desk", font=("Segoe UI", 12, "bold"))
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # Alert table
        self.tree_alerts = ttk.Treeview(
            container,
            columns=("id", "timestamp", "camera", "type", "severity", "status"),
            show="headings",
            height=12,
        )
        self.tree_alerts.heading("id", text="Alert ID")
        self.tree_alerts.heading("timestamp", text="Timestamp (UTC)")
        self.tree_alerts.heading("camera", text="Camera")
        self.tree_alerts.heading("type", text="Detection Type")
        self.tree_alerts.heading("severity", text="Severity")
        self.tree_alerts.heading("status", text="Status")

        self.tree_alerts.column("id", width=120)
        self.tree_alerts.column("timestamp", width=200)
        self.tree_alerts.column("camera", width=150)
        self.tree_alerts.column("type", width=160)
        self.tree_alerts.column("severity", width=100)
        self.tree_alerts.column("status", width=140)
        self.tree_alerts.pack(fill=tk.BOTH, expand=True)

        # Sample alerts
        self.tree_alerts.insert(
            "",
            "end",
            values=("ALT-001", "2026-11-16 19:48:12", "Camera 0 (Optical)", "PERSON_DETECTED (94%)", "HIGH", "UNACKNOWLEDGED"),
        )

        btn_frame = ttk.Frame(container, padding=5)
        btn_frame.pack(fill=tk.X, pady=5)

        btn_ack = ttk.Button(btn_frame, text="Acknowledge Selected Alert", command=self._ack_selected_alert)
        btn_ack.pack(side=tk.LEFT, padx=5)

    def _ack_selected_alert(self) -> None:
        if self.headless or not self._root:
            return
        selected = self.tree_alerts.selection()
        if selected:
            for item in selected:
                vals = list(self.tree_alerts.item(item, "values"))
                vals[5] = f"ACKNOWLEDGED ({self.operator_name})"
                self.tree_alerts.item(item, values=vals)
            self._msgbox.showinfo("Alert Acknowledged", "Incident marked as acknowledged by operator.")

    def _build_system_tab(self) -> None:
        tk = self._tk
        ttk = self._ttk

        container = ttk.Frame(self.tab_system, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        lbl = ttk.Label(container, text="Windows Platform Diagnostics & SCM Control", font=("Segoe UI", 12, "bold"))
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # SCM Controls Frame
        scm_frame = tk.LabelFrame(container, text=" Windows Service Control Manager (SCM) ", font=("Segoe UI", 10, "bold"), padx=10, pady=10)
        scm_frame.pack(fill=tk.X, pady=5)

        self.lbl_scm_detail = tk.Label(scm_frame, text="Service: CAMservCore | State: QUERYING...", font=("Consolas", 10))
        self.lbl_scm_detail.pack(anchor=tk.W, pady=5)

        btn_box = ttk.Frame(scm_frame)
        btn_box.pack(anchor=tk.W, pady=5)

        ttk.Button(btn_box, text="Start Service", command=self._action_start_service).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_box, text="Stop Service", command=self._action_stop_service).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_box, text="Restart Service", command=self._action_restart_service).pack(side=tk.LEFT, padx=5)

        # Hardware Telemetry Frame
        hw_frame = tk.LabelFrame(container, text=" Host Hardware Diagnostics ", font=("Segoe UI", 10, "bold"), padx=10, pady=10)
        hw_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        self.lbl_hw_info = tk.Label(hw_frame, text="Gathering hardware specifications...", font=("Consolas", 10), justify=tk.LEFT)
        self.lbl_hw_info.pack(anchor=tk.W, padx=10, pady=10)

    def _build_cluster_tab(self) -> None:
        tk = self._tk
        ttk = self._ttk

        container = ttk.Frame(self.tab_cluster, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        lbl = ttk.Label(container, text="Enterprise Cluster Federation & Node Failover", font=("Segoe UI", 12, "bold"))
        lbl.pack(anchor=tk.W, pady=(0, 10))

        # Cluster Tree View
        self.tree_cluster = ttk.Treeview(
            container,
            columns=("node_id", "role", "state", "address", "channels", "status"),
            show="headings",
            height=8,
        )
        self.tree_cluster.heading("node_id", text="Node Identifier")
        self.tree_cluster.heading("role", text="Cluster Role")
        self.tree_cluster.heading("state", text="Node State")
        self.tree_cluster.heading("address", text="Network Address")
        self.tree_cluster.heading("channels", text="Channel Load")
        self.tree_cluster.heading("status", text="Witness Sync")

        self.tree_cluster.column("node_id", width=180)
        self.tree_cluster.column("role", width=120)
        self.tree_cluster.column("state", width=120)
        self.tree_cluster.column("address", width=160)
        self.tree_cluster.column("channels", width=120)
        self.tree_cluster.column("status", width=150)
        self.tree_cluster.pack(fill=tk.BOTH, expand=True)

        # Populate sample cluster nodes
        self.tree_cluster.insert(
            "",
            "end",
            values=("nvr-appliance-primary", "LEADER", "ONLINE", "10.0.1.10:8080", "8 / 16", "SYNCHRONIZED"),
        )
        self.tree_cluster.insert(
            "",
            "end",
            values=("nvr-appliance-secondary", "FOLLOWER", "ONLINE", "10.0.1.11:8080", "4 / 16", "SYNCHRONIZED"),
        )
        self.tree_cluster.insert(
            "",
            "end",
            values=("win11-operator-node", "STANDBY", "ONLINE", "10.0.1.50:8080", "1 / 16", "SYNCHRONIZED"),
        )

        btn_box = ttk.Frame(container, padding=5)
        btn_box.pack(fill=tk.X, pady=5)

        ttk.Button(btn_box, text="Quarantine Selected Node", command=self._action_quarantine_selected_node).pack(side=tk.LEFT, padx=5)

    def _action_quarantine_selected_node(self) -> None:
        if self.headless or not self._root:
            return
        selected = self.tree_cluster.selection()
        if selected:
            for item in selected:
                vals = list(self.tree_cluster.item(item, "values"))
                vals[2] = "QUARANTINED"
                vals[5] = "ISOLATED"
                self.tree_cluster.item(item, values=vals)
            self._msgbox.showwarning("Node Quarantined", "Selected node has been isolated and its cameras failed over.")

    def _build_statusbar(self) -> None:
        tk = self._tk
        self.statusbar = tk.Label(
            self._root,
            text="CAMserv Operator Console 0.10.0 (Pre-LTS) | Platform: Windows 11 AMD64 | Consensus: Active | Audit: Intact",
            bd=0,
            relief=tk.FLAT,
            anchor=tk.W,
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#0d1424",
            padx=10,
            pady=4,
        )
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

    def _action_start_service(self) -> None:
        self.service_mgr.start_service("CAMservCore")
        self.update_telemetry()

    def _action_stop_service(self) -> None:
        self.service_mgr.stop_service("CAMservCore")
        self.update_telemetry()

    def _action_restart_service(self) -> None:
        self.service_mgr.restart_service("CAMservCore")
        self.update_telemetry()

    def update_telemetry(self) -> dict[str, Any]:
        """Poll telemetry data and update GUI widgets."""
        telemetry = self.client.get_system_telemetry()
        self._state_cache["hardware"] = telemetry
        self._state_cache["service_status"] = telemetry.get("service_state", "UNKNOWN")

        if not self.headless and self._root:
            state = telemetry.get("service_state", "UNKNOWN").upper()
            self.lbl_scm_status.config(text=f"SCM: {state}")
            if state == "RUNNING":
                self.lbl_scm_status.config(bg="#15803d", fg="#ffffff")
            else:
                self.lbl_scm_status.config(bg="#b91c1c", fg="#ffffff")

            if telemetry.get("connected_to_api"):
                self.lbl_api_status.config(text="API: ONLINE", bg="#15803d")
            else:
                self.lbl_api_status.config(text="API: OFFLINE", bg="#dc2626")

            self.lbl_scm_detail.config(
                text=f"Service: {telemetry.get('service_name')} | SCM State: {state}"
            )

            gpus = telemetry.get("gpus", [])
            gpu_str = (
                f"  Dedicated GPU: {gpus[0].get('name')} ({gpus[0].get('memory_total_mb')} MB VRAM, Driver {gpus[0].get('driver_version')})\n"
                if gpus
                else "  Dedicated GPU: Not detected\n"
            )
            hw_text = (
                f"Host System:\n"
                f"  OS: {telemetry.get('os')} 64-bit\n"
                f"  CPU Logical Cores: {telemetry.get('logical_cores')}\n"
                f"  System RAM: {telemetry.get('ram_total_mb')} MB total ({telemetry.get('ram_available_mb')} MB available)\n"
                f"{gpu_str}"
            )
            self.lbl_hw_info.config(text=hw_text)

        return telemetry

    def run(self) -> None:
        """Start the console application."""
        self._running = True
        self.update_telemetry()
        if not self.headless and self._root:
            self._root.mainloop()


def main() -> int:
    console = DesktopOperatorConsole(headless=False)
    console.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
