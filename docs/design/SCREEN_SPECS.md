# CAMserv Enterprise Screen Specifications & Information Architecture
**User Experience & Interface Specification for the 12 Official Platform Screens**  
**Author:** Principal UI/UX Designer & Chief Creative Director

---

## 1. Global Navigation & Information Architecture

The CAMserv interface is organized into five operational domains accessible via a collapsible left-hand primary command rail:

```
[CAMserv Brand Header]
├── Operations
│   ├── [1] Executive Overview (Ctrl+1)
│   ├── [2] Live Monitoring (Ctrl+2)
│   ├── [3] Camera Management (Ctrl+3)
│   └── [4] Intelligent Event Center (Ctrl+4)
├── Forensics & Analytics
│   ├── [5] Anonymous Tracking Visualization (Ctrl+5)
│   ├── [6] Incident Investigation (Ctrl+6)
│   ├── [7] Evidence Vault (Ctrl+7)
│   └── [8] Analytics & Reports (Ctrl+8)
└── Infrastructure & Security
    ├── [9] Device & NVR Integration (Ctrl+9)
    ├── [10] Security & Access Control (Ctrl+0)
    ├── [11] System Health & Diagnostics
    └── [12] Deployment & Configuration
```

---

## 2. Detailed Screen Specifications

### Screen 01: Executive Overview
* **Purpose:** High-level operational summary for Chief Security Officers (CSOs) and facility managers.
* **Key Components:**
  - Active Camera Status KPI (Online / Degraded / Offline).
  - 24-Hour Event Volume Sparkline with severity breakdown (Critical / High / Medium / Low).
  - Open Alerts awaiting Human Verification counter with SLA timer.
  - Hardware VRAM & Pipeline Latency Gauge (P50, P95, P99).
* **States:**
  - *Empty State:* "No cameras configured. Launch Camera Discovery to begin."
  - *Loading State:* Subtle pulsating skeleton shimmer.
  - *Error State:* "Telemetry service unreachable. Retrying in 5s."
* **Permissions:** Accessible to `ADMIN`, `OPERATOR`, `VIEWER`, `AUDITOR`.
* **Backend API:** `GET /api/v1/system/health`, `GET /api/v1/events?limit=100`, `GET /api/v1/cameras`.

### Screen 02: Live Monitoring
* **Purpose:** Multi-stream low-latency video wall for 24/7 security control rooms.
* **Key Components:**
  - Configurable grid (1x1, 2x2, 3x3, 4x4, 1+5 focus mode).
  - Live WebSocket stream cards with frame rate, camera name, and health badge.
  - Real-time overlay toggle: Anonymous Track Boxes, Zone Polygons, Privacy Blurring.
  - Instant Snapshot & Emergency Escalation hotkeys.
* **Backend API:** `WS /api/v1/ws/events`, `GET /api/v1/cameras`.

### Screen 03: Camera Management
* **Purpose:** Register, configure, and calibrate camera streams and privacy zones.
* **Key Components:**
  - Camera list table with RTSP URL, ONVIF Profile, Resolution, FPS, and status.
  - Interactive Geometric Privacy Mask Editor: Canvas allowing operators to draw exclusion polygons that blur or redact sensitive zones before processing.
  - Add Camera Modal supporting RTSP URL direct entry or ONVIF auto-discovery import.
* **Backend API:** `GET/POST /api/v1/cameras`, `PUT/DELETE /api/v1/cameras/{id}`.

### Screen 04: Intelligent Event Center
* **Purpose:** Triage, review, and verify security events and anomalies.
* **Key Components:**
  - Filterable event stream: Type, Severity, Camera, Status (`pending`, `verified`, `dismissed`).
  - **Human-in-the-Loop Verification Drawer:** Displays supporting multi-frame observation sequence, kinematic trajectory graph, explainability reasoning trace, and operator sign-off buttons (`Verify Alert`, `Dismiss as False Positive`).
* **Permissions:** Verification actions restricted to `OPERATOR` and `ADMIN`.
* **Backend API:** `GET /api/v1/events`, `POST /api/v1/events/{id}/verify`.

### Screen 05: Anonymous Tracking Visualization
* **Purpose:** Real-time spatial tracking without collecting or displaying PII.
* **Key Components:**
  - Top-down 2D spatial radar / camera perspective view showing active tracks.
  - Kinematic metrics: Track ID, Velocity, Aspect Ratio, Dwell Duration, Track State.
  - Tracking Quality HUD: MOTA (Multi-Object Tracking Accuracy), ID switches, and fragmentation count.
* **Backend API:** `GET /api/v1/tracking/active`.

### Screen 06: Incident Investigation
* **Purpose:** Reconstruct multi-camera timeline of security incidents.
* **Key Components:**
  - Synchronized multi-camera timeline scrubber.
  - Spatio-temporal event correlation graph linking triggers across overlapping cameras.
  - Export Incident Package button (triggers creation of signed forensic package).
* **Backend API:** `GET /api/v1/events`, `GET /api/v1/detections/recent`.

### Screen 07: Evidence Vault
* **Purpose:** Manage cryptographically sealed, tamper-evident video evidence packages.
* **Key Components:**
  - Evidence package table with Package ID, Camera, Time, File Size, and SHA-256 Digest.
  - Integrated Cryptographic Chain Verifier: Instant audit of hash continuity and Ed25519 signature.
  - Secure Export: Download signed `.zip` bundle for external legal proceedings.
* **Permissions:** Export requires `OPERATOR`, `ADMIN`, or `AUDITOR` role.
* **Backend API:** `GET /api/v1/system/health`, Evidence Store internal endpoints.

### Screen 08: Analytics & Reports
* **Purpose:** Aggregated visual intelligence, crowd trends, and environmental metrics.
* **Key Components:**
  - Hourly crowd density distribution heatmaps.
  - Vehicle flow volume by classification (car, truck, motorcycle, bicycle).
  - Compliance audit report generator (GDPR/EU AI Act data retention summaries).
* **Backend API:** `GET /api/v1/system/metrics`, `GET /api/v1/events`.

### Screen 09: Device and NVR Integration
* **Purpose:** Manage physical hardware connections and third-party NVR systems.
* **Key Components:**
  - ONVIF WS-Discovery Scanner: One-click scan of local subnet for cameras.
  - Topology Mode Selector: Topology A (NVR Interconnect), Topology B (Edge Co-located), Topology C (Standalone Primary).
  - Stream Health Diagnostic Tool: RTSP latency, dropped frame counter, codec compatibility report.
* **Backend API:** `GET /api/v1/system/health`, ONVIF Discovery module.

### Screen 10: Security and Access Control
* **Purpose:** User management, RBAC enforcement, and cryptographic audit log inspection.
* **Key Components:**
  - User Directory: Username, Role (`ADMIN`, `OPERATOR`, `VIEWER`, `AUDITOR`), Status.
  - Immutable Audit Log Inspector: Live view of `logs/audit.jsonl` with real-time hash chain validation status badge.
  - Master Key & TLS Certificate Status card.
* **Permissions:** Restricted to `ADMIN` and `AUDITOR`.
* **Backend API:** `GET /api/v1/audit`, `POST /api/v1/auth/token`.

### Screen 11: System Health
* **Purpose:** Low-level pipeline telemetry and infrastructure diagnostics.
* **Key Components:**
  - Pipeline Stage Latency DDSketch: P50, P95, and P99 latency per stage (Acquisition -> Decode -> Inference -> Tracking -> Events -> Storage).
  - Host Hardware HUD: CPU physical/logical cores, RAM usage, GPU VRAM, CUDA temperature.
  - Bounded Queue Fill Ratios and Frame Drop Counters.
* **Backend API:** `GET /api/v1/system/health`, `GET /api/v1/system/metrics`.

### Screen 12: Deployment and Configuration
* **Purpose:** Runtime configuration tuning and environment management.
* **Key Components:**
  - Config editor with live validation for Detection thresholds, Tracking params, Privacy retention rules.
  - Hardware Acceleration Selector (TensorRT / ONNX GPU / ONNX CPU).
  - Backup & Recovery trigger.
* **Permissions:** Restricted to `ADMIN`.
* **Backend API:** `GET/PUT /api/v1/config`.
