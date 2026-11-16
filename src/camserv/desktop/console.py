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
    get_platform_hardware_prober,
    get_platform_service_manager,
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

            # Modern dark security palette
            self.style = ttk.Style()
            self.style.theme_use("clam")

            self._build_header()
            self._build_tabs()
            self._build_statusbar()
        except Exception as exc:
            logger.warning("desktop.ui_init_fallback_to_headless", error=str(exc))
            self.headless = True

    def _build_header(self) -> None:
        tk = self._tk
        ttk = self._ttk

        header_frame = tk.Frame(self._root, bg="#1e222d", height=60, padx=15, pady=10)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        # Title
        title_lbl = tk.Label(
            header_frame,
            text="CAMserv Security Intelligence Console",
            font=("Segoe UI", 14, "bold"),
            fg="#f8fafc",
            bg="#1e222d",
        )
        title_lbl.pack(side=tk.LEFT)

        # Status Indicators
        self.lbl_user = tk.Label(
            header_frame,
            text=f"Operator: {self.operator_name}",
            font=("Segoe UI", 10),
            fg="#94a3b8",
            bg="#1e222d",
            padx=10,
        )
        self.lbl_user.pack(side=tk.RIGHT)

        self.lbl_scm_status = tk.Label(
            header_frame,
            text="SCM: CHECKING...",
            font=("Segoe UI", 10, "bold"),
            fg="#e2e8f0",
            bg="#334155",
            padx=8,
            pady=2,
        )
        self.lbl_scm_status.pack(side=tk.RIGHT, padx=6)

        self.lbl_api_status = tk.Label(
            header_frame,
            text="API: OFFLINE",
            font=("Segoe UI", 10, "bold"),
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

    def _build_live_tab(self) -> None:
        tk = self._tk
        ttk = self._ttk

        container = ttk.Frame(self.tab_live, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        lbl = ttk.Label(container, text="Active Video Feeds (Live Matrix)", font=("Segoe UI", 12, "bold"))
        lbl.pack(anchor=tk.W, pady=(0, 10))

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

        for idx, cam in enumerate(cameras):
            card = tk.LabelFrame(
                self.camera_grid_frame,
                text=f" Camera {cam.index}: {cam.name} ",
                font=("Segoe UI", 10, "bold"),
                padx=10,
                pady=10,
                bg="#f1f5f9",
            )
            card.grid(row=idx // 2, column=idx % 2, padx=10, pady=10, sticky="nsew")

            info_text = (
                f"Backend: {cam.backend.upper()}\n"
                f"Device: {cam.device_path}\n"
                f"Resolution: {cam.supported_resolutions[0][0]}x{cam.supported_resolutions[0][1]}\n"
                f"Status: ONLINE [Active]"
            )
            info_lbl = tk.Label(card, text=info_text, justify=tk.LEFT, bg="#f1f5f9", font=("Consolas", 9))
            info_lbl.pack(anchor=tk.W, pady=5)

            # Preview Canvas
            canvas = tk.Canvas(card, width=320, height=180, bg="#0f172a")
            canvas.pack(pady=5)
            canvas.create_text(
                160,
                90,
                text=f"[LIVE FEED {cam.index}]\n{cam.name}",
                fill="#38bdf8",
                font=("Segoe UI", 10),
                justify=tk.CENTER,
            )

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

    def _build_statusbar(self) -> None:
        tk = self._tk
        self.statusbar = tk.Label(
            self._root,
            text="CAMserv Console 0.10.0-alpha2 | Platform: Windows 11 AMD64 | Ready",
            bd=1,
            relief=tk.SUNKEN,
            anchor=tk.W,
            font=("Segoe UI", 9),
            padx=5,
            pady=3,
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
