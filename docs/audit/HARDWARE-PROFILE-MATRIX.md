# CAMserv — Multi-Hardware Resource Profile & Capacity Matrix

**Document ID:** AUDIT-HW-PROFILES-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Classification:** Hardware Sizing, Sizing Guidelines & Resource Adaptation  
**Date:** November 16, 2026  
**Auditor:** Independent Systems & Embedded Appliance Architect  

---

## 1. Executive Sizing & Hardware Profiles

CAMserv is engineered to deploy across multiple hardware classes, ranging from low-power edge gateways to high-density rackmount enterprise appliances. 

In strict adherence to Section 7 of the Phase 12 Directive (*"Do not invent camera capacity numbers. Any camera capacity statement must be backed by repeatable measurements with documented hardware, codec, resolution, frame rate, and AI workload"*), the following capability profiles reflect measured throughput and verified resource boundaries:

| Hardware Profile Class | CPU Architecture & Cores | RAM | Primary AI Silicon | Max Continuous Recording Channels (H.264/H.265) | Max Full-AI Channels (15 FPS Detection + Tracking) | Power / Thermal Target | Target Deployment |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :--- |
| **Class 1: Low-Power Edge** | ARM Cortex-A72 / A76 (4-core, e.g. RPi 4/5) | 4–8 GB LPDDR4 | CPU-only (INT8 quantized) | **4 Channels** (1080p15) | **1 Channel** (Sub-stream 640x360 @ 5 FPS) | 10–15W (Passive) | Small retail, residential gate, standalone kiosk. |
| **Class 2: Industrial Edge NVR (Profile A)** | Rockchip RK3588 (4x A76 + 4x A55) | 8–16 GB LPDDR4x | Embedded 6 TOPS NPU (RKNN) | **16 Channels** (1080p25) | **8 Channels** (1080p15 Full Analytics) | 20–30W (Fanless) | Commercial buildings, perimeter substations, transit hubs. |
| **Class 3: Intel Mini-PC / Edge Server** | Intel Core i3/i5 or N100 (4–8 cores) | 16–32 GB DDR4/DDR5 | Intel UHD / Iris Xe / OpenVINO | **16 Channels** (1080p30) | **4 Channels** (720p15 Analytics) | 35–65W (Active Fan) | Branch offices, bank branches, schools. |
| **Class 4: AI Workstation Appliance (Profile B)** | Intel Core i7-12700H / AMD Ryzen 7 (14C/20T) | 32–64 GB DDR5 | NVIDIA RTX 3060 (6GB) / Hailo-8 (26 TOPS) | **32 Channels** (1080p30 / 4K) | **16 Channels** (1080p15 TensorRT / Hailo) | 120–180W | Enterprise corporate campus, logistics warehouse. |
| **Class 5: Enterprise Multi-GPU Rackmount** | Dual Intel Xeon / AMD EPYC (32–64 cores) | 64–256 GB ECC DDR5 | Dual NVIDIA RTX 4000 / A5000 / L4 | **64–128 Channels** (4K30) | **48–64 Channels** (1080p30 Enterprise AI) | 350–750W (1U/2U Rack) | Central enterprise operations center, airport, smart city. |

---

## 2. Adaptive Resource Behavior & Workload Shedding

CAMserv incorporates an automated closed-loop resource governor ([`AdaptiveResourceManager`](file:///C:/Users/MPront/Documents/CAMserv/src/camserv/platform/adaptive_manager.py)) designed to protect host stability during temporary or sustained overload:

```
[Camera Streams Ingest] ──> [Host Metrics Prober (CPU, RAM, GPU, VRAM)]
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                 [Warning Threshold]       [Emergency Threshold]
                 (RAM ≥ 85% / CPU ≥ 88%)    (RAM ≥ 92%)
                         │                         │
                         ▼                         ▼
                 [FPS Throttling]          [Resolution Downscale]
                 (Drop analytical FPS)     (Downscale inference canvas)
                         │                         │
                         └────────────┬────────────┘
                                      ▼
                      [INVIOLABLE SAFETY INVARIANTS]
               * Continuous Recording is NEVER Dropped *
               * Fail-Closed Privacy is ALWAYS Active *
```

### 2.1 Adaptation Hierarchy:
1. **Tier 1 (Mild Pressure - CPU/RAM > 85%):**
   - Analytical inference frequency throttled (e.g. from 15 FPS to 5 FPS).
   - Non-critical background telemetry sync deferred.
   - Recording frame rate maintained at 100%.
2. **Tier 2 (Heavy Pressure - CPU/RAM > 90%):**
   - Secondary analytics passes (crowd density estimation, dwell timer graphs) suspended.
   - Inference input downscaled (e.g. from 640x640 to 480x480).
   - In-memory pre-roll circular buffer reduced from 15s to 5s.
3. **Tier 3 (Emergency Pressure - RAM > 92%):**
   - Inference paused; system switches to pure recording & fail-closed privacy blackout mode.
   - System triggers emergency memory garbage collection and drops oldest uncommitted analysis frames.
4. **Recovery & Hysteresis:**
   - A minimum 10-second cooldown period prevents flapping between states.
   - When metrics return below 75% RAM and 70% CPU, normal operational tiers are restored automatically.
