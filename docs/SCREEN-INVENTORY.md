# CAMserv — Complete Screen Inventory & Interface Audit

**Document ID:** AUDIT-SCREEN-INV-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Visual Direction:** Cinematic Dark / Multi-Layer Glassmorphism  
**Date:** November 17, 2026  
**Auditor:** Principal Enterprise UX Architect & Quality Auditor  

---

## 1. Inventory Summary

This inventory catalogs every operational screen in the Web Command & Control Console and Desktop Operator Console, documenting their existing visual state, functional responsibilities, identified weaknesses, and required Phase 22 glassmorphism transformations.

---

## 2. Web Command & Control Console Screens (`src/camserv/web/`)

| # | Screen ID (`data-screen`) | Screen Title | Primary Purpose | Existing Weakness | Phase 22 Overhaul Transformation |
| :-: | :--- | :--- | :--- | :--- | :--- |
| **1** | `overview` | Executive Overview | High-level operational health, camera states, cluster quorum, active alerts, storage utilization | Flat card layout; metrics lack luminous accent hierarchy and glass depth | Redesign with multi-layer glass cards, glowing pulse indicators, sparkline metrics, and quorum verification badge |
| **2** | `live` | Live Monitoring | Real-time multi-camera grid matrix with telemetry overlays and PTZ controls | Basic video borders; telemetry overlays lack clinical precision | Implement $16:9$ glass viewport tiles, cinematic corner reticles, FPS/bitrate HUD, and fail-closed privacy badge |
| **3** | `cameras` | Camera Management | Ingestion stream configuration, ONVIF discovery, RTSP parameters, codec settings | Standard HTML tables; ONVIF scan output is plain text | Translucent data tables with rim borders, interactive ONVIF discovery cards, and health meters |
| **4** | `events` | Intelligent Event Center | Detection candidate queue, human verification desk, alert filtering | Events appear as plain list items without epistemic clarity | Cinematic threat cards displaying probabilistic confidence tags (`is_prediction: true`), verification buttons, and timeline markers |
| **5** | `tracking` | Anonymous Tracking | Spatial trajectory mapping, ground contact points, zero-biometric tracking | Flat SVG canvas; trajectory lines lack depth | Glowing vector trajectory lines, ground contact uncertainty ellipses, and non-biometric spatial indicators |
| **6** | `investigation` | Incident Investigation | Multi-channel incident timeline correlation, synchronized video playback | Basic timeline bar with limited time scrubbing fidelity | Multi-track glass timeline scrubber, incident bookmarking markers, and synchronized segment playback |
| **7** | `evidence` | Evidence Vault | Cryptographic segment bundles, SHA-256 verification, judicial export | Hash displays are cramped; lacks visual distinction for quarantined segments | Deep indigo glass evidence cards, click-to-copy SHA-256 digests, Ed25519 signature badges, and quarantine queue |
| **8** | `analytics` | Analytics & Reports | Occupancy heatmaps, operational throughput, historical trend analysis | Basic static graphs without glass card containment | Translucent analytical charts, glowing peak indicators, and automated CSV/PDF export triggers |
| **9** | `nvr` | Device & NVR | Storage lease monitoring, disk partitioning, NVMe high-IOPS write rates | Monolithic text cards; missing storage lease expiration visual countdown | Real-time storage lease countdown bar, NVMe IOPS gauge, and storage fencing status indicator |
| **10**| `privacy` | Privacy Management | Spatial blurring zones, license plate masking, dual-control quorum policies | Privacy toggle implies client-side defeatability | Clinical privacy enforcement dashboard demonstrating fail-closed kernel blackout and dual-control requirements |
| **11**| `security` | Security & Access | RBAC role assignment, API token issuance, mTLS certificate status | Plain form inputs without security credential styling | Glass security credential cards, role privilege matrix, and active mTLS certificate expiration badges |
| **12**| `health` | System Health & Tiers | CPU/GPU/NPU telemetry, thermal sensors, hardware profile detection | Plain status text; lack of hardware tier distinction | Multi-core temperature gauges ($T_1$ to $T_4$), NPU utilization bar, and hardware acceleration badge (`[HW-VERIFIED]`) |
| **13**| `config` | Deployment Config | Systemd/SCM integration, network firewall rules, retention policies | Simple configuration list without structured categories | Grouped glass accordion panels, instant validation feedback, and configuration export/import |

---

## 3. Desktop Operator Console Tabs (`src/camserv/desktop/console.py`)

| Tab # | Tab Identifier | Tab Title | Operational Role | Phase 22 Desktop Styling Transformation |
| :-: | :--- | :--- | :--- | :--- |
| **1** | `tab_live` | Live Monitor | Native Windows optical capture and camera matrix display | Custom dark ttk styling (`#090d16` canvas, `#111827` frames, cyan rim outlines) |
| **2** | `tab_timeline` | Recordings & Forensics | Local timeline playback and offline cryptographic evidence verification | Monospace SHA-256 displays, evidence integrity status indicators, and export triggers |
| **3** | `tab_alerts` | Alerts & Incidents | SCM alarm dispatch and local incident queue | High-visibility amber/crimson alarm cards with one-click verification |
| **4** | `tab_system` | System Diagnostics & SCM | Service Control Manager status, CPU/RAM telemetry, DirectShow prober | Windows 11 Fluent-inspired dark panels with real-time service heartbeat indicator |
| **5** | `tab_cluster` | Enterprise Cluster | Enterprise cluster federation, quorum state, witness synchronization, and node quarantine (`_build_cluster_tab()`) | Translucent dark cluster treeview, role status pills (LEADER/FOLLOWER/STANDBY), and failover quarantine controls |
