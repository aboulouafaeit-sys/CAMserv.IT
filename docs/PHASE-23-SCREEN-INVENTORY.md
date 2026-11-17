# CAMserv Phase 23 — Screen & Interface Inventory

**Platform**: CAMserv — Advanced Security Intelligence Platform  
**Target Release**: `0.10.0-rc5`  
**Phase**: 23  
**Status**: Comprehensive Interface Audit  

---

## 1. Desktop Operator Console (Tkinter / Windows 11 Native)

The native Windows Desktop Operator Console provides hardware-integrated surveillance monitoring across multiple physical displays.

### Primary Application Windows & Tabs

```
Desktop Operator Console
├── Application Header
│   ├── Platform Branding ("CAMserv Security Intelligence Console")
│   ├── Multi-Monitor Indicator ("🖥️ Monitors: N")
│   ├── Pop-Out Video Wall Button ("🪟 Pop-Out Video Wall")
│   ├── Operational Context Selector ("🎯 CONTEXT: GENERAL / PERIMETER / ...")
│   ├── Resource Profile Selector ("⚡ BALANCED / HIGH / LOW")
│   ├── Operator Identity Badge ("Operator: Security Operator")
│   ├── SCM Service Status Indicator ("SCM: RUNNING / STOPPED")
│   └── API Connectivity Indicator ("API: ONLINE / OFFLINE")
│
├── Tab 1: Live Monitor Matrix
│   ├── Layout Presets Toolbar (1x1, 1x2, 2x2, 3x3, 4x4, 5x5, Restore All)
│   ├── Event Candidate Focus Banner (Notification + 1-Click Focus & Restore)
│   └── Camera Feed Quad/Matrix Cards
│       ├── Header (Camera Index, Name, HW-Verified Badge, ISP Tier, FPS)
│       ├── Reorder Controls (◀ / ▶ Drag/Shift Buttons)
│       ├── Maximize / Restore Controls (⤢ / 🗗 Buttons)
│       └── Stream Preview Canvas (Synthetic / Media Foundation Hardware)
│
├── Tab 2: Recordings & Forensics (Timeline Playback)
│   ├── Date & Time Range Pickers
│   ├── Timeline Slider with Microsecond Resolution
│   └── Evidence Export & Chain-of-Custody Hashing Controls
│
├── Tab 3: Alerts & Incident Desk
│   ├── Priority Alert Table (Critical, High, Medium, Low)
│   ├── Candidate Hypothesis Indicators (Human Verification Pill)
│   └── Incident Dispatch & Acknowledgment Controls
│
├── Tab 4: System Diagnostics & SCM
│   ├── Windows Service Control Manager Integration (Start, Stop, Restart)
│   ├── Hardware Telemetry Gauges (CPU Cores, RAM, GPU VRAM, Disk)
│   └── Active Pipeline Health Indicators
│
├── Tab 5: Enterprise Cluster Federation
│   ├── Raft Monotonic Term & Leader Status Display
│   ├── Node Quorum & Topology Table
│   └── Forensic Replication & Stream Evacuation Status
│
└── Secondary Window: Dedicated Video Wall Pop-Out
    ├── Coordinate Space: Positioned on Secondary Physical Monitor
    ├── Geometry Clamping: Clamped within Visible Monitor Boundaries (`rcWork`)
    ├── Independent Fullscreen / Maximized Quad Viewport
    └── Window Manager Close Protocol (Clean Lifecycle Reclamation)
```

---

## 2. Web Console SPA (Cinematic Dark Glassmorphism)

The single-page web console operates in modern browsers with dark glassmorphic styling, responsive layout transitions, and GPU-accelerated rendering.

### Primary Screens & Components

```
Enterprise Web Console SPA
├── Global Glassmorphic Sidebar
│   ├── Brand Header (Official CAMserv Symbol & Wordmark)
│   ├── Epistemic Telemetry Pill ([HW-VERIFIED] / [SIMULATED])
│   ├── Navigation Items (8 Screens)
│   └── Theme Toggle (Cinematic Dark / Daylight Mode)
│
├── Screen 01: Overview Dashboard
│   ├── System Vital Stat Cards (Active Streams, Storage, Quorum, FPS)
│   ├── Incident Priority Trend Chart
│   └── Recent High-Priority Anomalies Table
│
├── Screen 02: Live Monitoring (Phase 23 Upgraded)
│   ├── Zero-API Live Narrative Banner (Bilingual English / Arabic)
│   ├── Layout Presets Toolbar (1x1, 1x2, 2x2, 3x3, 4x4, 5x5, Restore)
│   ├── Pop-Out Video Wall Button (Spawns Dedicated Browser Popout)
│   ├── Workspaces Button (Opens Modal Workspace Manager)
│   ├── Context Selector (General, Perimeter, Investigation, Diagnostics, Multi-Site)
│   ├── Feature Toggles (Cinematic Contours, Skeletal Pose, Software ISP, Privacy)
│   ├── Event Candidate Focus Banner (🚨 Candidate Alert, Focus, Dismiss/Restore)
│   └── Dynamic Video Grid (.layout-1x1 through .layout-5x5)
│       └── Video Cards (HTML5 Drag-and-Drop, HUD Overlays, Maximize/Restore)
│
├── Screen 03: Camera Management & Onboarding
│   ├── Active Endpoints Table
│   ├── ONVIF WS-Discovery Scanner
│   └── Camera Capability & Resolution Profiles
│
├── Screen 04: Event Intelligence & Alerts
│   ├── Filtering & Search Controls
│   ├── Candidate Hypothesis Verification Modal
│   └── False-Positive Operator Feedback Loop
│
├── Screen 05: Behavioral Tracking & Trajectories
│   ├── Spatial Ground Rings & Directional Vectors
│   └── Multi-Target Track ID Association Matrix
│
├── Screen 06: Forensic Evidence Locker
│   ├── Tamper-Evident SHA-256 Bundle Inventory
│   ├── Judicial Dual-Control Decryption Authorization Modal
│   └── Offline Verification Tooling Handoff
│
├── Screen 07: Immutable Audit Trail
│   ├── Hash-Chained Forensic Ledger Display
│   └── Invariant Verification (Byte Count & SHA-256 Audit Seal)
│
├── Screen 08: System Infrastructure & SCM
│   ├── Cross-Platform Hardware Gauges (CPU, RAM, GPU, Storage)
│   └── Cluster Node Topology & Lease Term Table
│
└── Modal Dialog: Operator Workspace & Multi-Monitor Manager (Phase 23)
    ├── Active Workspace Indicator
    ├── Save Current Workspace Prompt
    ├── Saved Workspaces Inventory (Load & Delete Controls)
    └── Schema-Validated JSON Import/Export Area (512KB Limit & Traversal Defense)
```
