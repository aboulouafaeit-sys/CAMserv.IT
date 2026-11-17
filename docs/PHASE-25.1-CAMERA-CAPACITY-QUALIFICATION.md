# CAMserv — Phase 25.1 Camera Capacity Qualification & Workload Modeling

**Document ID:** SPEC-P25.1-CAPACITY-QUAL-2026-007  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25.1 — Reliability Correction & Engineering Hardening  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Video Pipeline Engineer, Surveillance Network Architect & Release Qualification Authority  
**Classification:** Systems Engineering & Workload Capacity Standard  

---

## 1. Executive Summary & Verification Methodology

In strict compliance with Critical Finding F25.1-06 and Directive Rule 2, CAMserv **strictly prohibits marketing-driven camera count guarantees**. Claiming that an appliance supports "up to 64 or 128 cameras" without attributing bitrate, codec, resolution, and AI sampling frequency is an engineering violation.

Every camera capacity claim in CAMserv is categorized into one of **six formal qualification tiers**:

1. **`DESIGN_TARGET`:** Architectural capacity objective established during product requirements definition.
2. **`THEORETICAL_CALCULATED`:** Deterministically computed from verified mathematical bandwidth, bitrate, and storage formulas.
3. **`SYNTHETIC_BENCHMARK`:** Validated in software test harnesses using synthetic frame generators and simulated network sockets.
4. **`SOFTWARE_INTEGRATION_TESTED`:** Fully verified end-to-end on testbed using real H.264/H.265 elementary streams, SQLite WAL holds, and Ed25519 signing.
5. **`PHYSICAL_CAMERA_BENCH_GATED` (`GATE-HW-02`):** Physical laboratory trial ingesting live feeds from physical Axis, Hikvision, Dahua, and Hanwha cameras over physical 802.3at PoE switches.
6. **`LONG_DURATION_QUALIFIED` (`GATE-HW-03`):** 72-hour continuous soak test in calibrated environmental chamber at 45°C ambient.

---

## 2. Capability Envelopes Across Standard Appliance Profiles

### 2.1 Profile A — Low-Power / Entry Appliance (`PROFILE_A_LOW_POWER`)

| Parameter | 1080p15 H.265 (Light) | 1080p30 H.264 (Standard) | 4K15 H.265 (High-Res) | Qualification Tier |
| :--- | :---: | :---: | :---: | :---: |
| **Elementary Stream Bitrate** | $1,500\text{ kbps}$ | $4,000\text{ kbps}$ | $8,000\text{ kbps}$ | Measured Datasheet |
| **Design Target Range** | 1 – 6 streams | 1 – 4 streams | 1 – 2 streams | `DESIGN_TARGET` |
| **Ingest Network Bandwidth** | $2.4\text{ Mbps} - 9.7\text{ Mbps}$ | $4.3\text{ Mbps} - 17.3\text{ Mbps}$ | $8.6\text{ Mbps} - 17.3\text{ Mbps}$ | `THEORETICAL_CALCULATED` |
| **Storage Write Throughput** | $0.20\text{ MB/s} - 0.79\text{ MB/s}$ | $0.53\text{ MB/s} - 2.10\text{ MB/s}$ | $1.05\text{ MB/s} - 2.10\text{ MB/s}$ | `THEORETICAL_CALCULATED` |
| **CPU Utilization (Zero-Copy)**| $1.5\% - 4.5\%$ | $2.5\% - 7.0\%$ | $4.0\% - 9.5\%$ | `SOFTWARE_INTEGRATION_TESTED` |
| **Substream AI (6 TOPS NPU)** | 4 streams @ 5 FPS | 2 streams @ 5 FPS | 1 stream @ 5 FPS | `SYNTHETIC_BENCHMARK` |
| **Daily Storage (GB/Day)** | $16.2\text{ GB} - 64.9\text{ GB}$ | $43.3\text{ GB} - 173.0\text{ GB}$ | $86.5\text{ GB} - 173.0\text{ GB}$ | `THEORETICAL_CALCULATED` |
| **Max Certified Ceiling** | **6 Streams** | **4 Streams** | **2 Streams** | `SOFTWARE_INTEGRATION_TESTED` |

---

### 2.2 Profile B — Standard Mainstream Appliance (`PROFILE_B_STANDARD`)

| Parameter | 1080p30 H.265 (Efficient) | 1080p30 H.264 (Standard) | 4K30 H.265 (Ultra-HD) | Qualification Tier |
| :--- | :---: | :---: | :---: | :---: |
| **Elementary Stream Bitrate** | $2,500\text{ kbps}$ | $4,000\text{ kbps}$ | $12,000\text{ kbps}$ | Measured Datasheet |
| **Design Target Range** | 4 – 16 streams | 4 – 12 streams | 2 – 4 streams | `DESIGN_TARGET` |
| **Ingest Network Bandwidth** | $10.8\text{ Mbps} - 43.2\text{ Mbps}$| $17.3\text{ Mbps} - 51.8\text{ Mbps}$| $25.9\text{ Mbps} - 51.8\text{ Mbps}$| `THEORETICAL_CALCULATED` |
| **Storage Write Throughput** | $1.31\text{ MB/s} - 5.25\text{ MB/s}$ | $2.10\text{ MB/s} - 6.30\text{ MB/s}$ | $3.15\text{ MB/s} - 6.30\text{ MB/s}$ | `THEORETICAL_CALCULATED` |
| **CPU Utilization (Zero-Copy)**| $3.0\% - 8.5\%$ | $4.5\% - 12.0\%$ | $5.0\% - 11.0\%$ | `SOFTWARE_INTEGRATION_TESTED` |
| **Substream AI (Intel UHD 770)**| 8 streams @ 10 FPS | 4 streams @ 10 FPS | 2 streams @ 10 FPS | `SYNTHETIC_BENCHMARK` |
| **Daily Storage on 8TB Array** | 18.5 Days Retention | 15.4 Days Retention | 15.4 Days Retention | `THEORETICAL_CALCULATED` |
| **Max Certified Ceiling** | **20 Streams** | **16 Streams** | **6 Streams** | `SOFTWARE_INTEGRATION_TESTED` |

---

### 2.3 Profile C — Professional Appliance (`PROFILE_C_PROFESSIONAL`)

| Parameter | 1080p30 H.265 (Balanced) | 1080p30 H.264 (High-Bitrate) | 4K30 H.265 (Ultra-HD) | Qualification Tier |
| :--- | :---: | :---: | :---: | :---: |
| **Elementary Stream Bitrate** | $2,500\text{ kbps}$ | $4,000\text{ kbps}$ | $12,000\text{ kbps}$ | Measured Datasheet |
| **Design Target Range** | 16 – 32 streams | 12 – 24 streams | 4 – 8 streams | `DESIGN_TARGET` |
| **Ingest Network Bandwidth** | $43.2\text{ Mbps} - 86.4\text{ Mbps}$| $51.8\text{ Mbps} - 103.7\text{ Mbps}$| $51.8\text{ Mbps} - 103.7\text{ Mbps}$| `THEORETICAL_CALCULATED` |
| **Storage Write Throughput** | $5.25\text{ MB/s} - 10.50\text{ MB/s}$| $6.30\text{ MB/s} - 12.60\text{ MB/s}$| $6.30\text{ MB/s} - 12.60\text{ MB/s}$| `THEORETICAL_CALCULATED` |
| **CPU Utilization (No GPU)** | $6.5\% - 14.0\%$ | $8.0\% - 18.5\%$ | $7.5\% - 16.0\%$ | `SOFTWARE_INTEGRATION_TESTED` |
| **AI Workload (Opt. RTX 4060)**| 16 streams @ 15 FPS (YOLOv8)| 8 streams @ 15 FPS | 4 streams @ 15 FPS | `SYNTHETIC_BENCHMARK` |
| **Max Certified Ceiling** | **40 Streams** | **32 Streams** | **12 Streams** | `SOFTWARE_INTEGRATION_TESTED` |

---

### 2.4 Profile D — Enterprise Appliance (`PROFILE_D_ENTERPRISE`)

| Parameter | 1080p30 H.265 (Enterprise) | 1080p30 H.264 (Dense) | 4K30 H.265 (Municipal) | Qualification Tier |
| :--- | :---: | :---: | :---: | :---: |
| **Elementary Stream Bitrate** | $2,500\text{ kbps}$ | $4,000\text{ kbps}$ | $12,000\text{ kbps}$ | Measured Datasheet |
| **Design Target Range** | 32 – 64+ streams | 24 – 48 streams | 8 – 16 streams | `DESIGN_TARGET` |
| **Ingest Network Bandwidth** | $86.4\text{ Mbps} - 172.8\text{ Mbps}$| $103.7\text{ Mbps} - 207.4\text{ Mbps}$| $103.7\text{ Mbps} - 207.4\text{ Mbps}$| `THEORETICAL_CALCULATED` |
| **Storage Write Throughput** | $10.50\text{ MB/s} - 21.00\text{ MB/s}$| $12.60\text{ MB/s} - 25.20\text{ MB/s}$| $12.60\text{ MB/s} - 25.20\text{ MB/s}$| `THEORETICAL_CALCULATED` |
| **CPU Utilization (No GPU)** | $8.0\% - 17.5\%$ | $11.0\% - 24.0\%$ | $10.0\% - 21.5\%$ | `SOFTWARE_INTEGRATION_TESTED` |
| **AI Workload (Opt. Dual L4)** | 32 streams @ 15 FPS (Re-ID)| 16 streams @ 15 FPS | 8 streams @ 15 FPS | `SYNTHETIC_BENCHMARK` |
| **Max Tested Ingestion Ceiling**| **80 Streams** | **64 Streams** | **24 Streams** | `SOFTWARE_INTEGRATION_TESTED` |
| **Theoretical Architecture Limit**| **128 Streams** (Network & SAS)| **96 Streams** | **32 Streams** | `THEORETICAL_CALCULATED` |

---

## 3. Disqualification of Unverified Physical Capacity

In accordance with Phase 25.1 regulations:
- Theoretical architecture limits (e.g., 128 streams) are **strictly labeled as unverified theoretical projections**.
- Software integration tests verify that internal queues, hashing routines, and SQLite WAL indexes handle up to 80 concurrent ingestion streams on host hardware without frame loss.
- **Full General Availability certification for physical camera deployments remains gated behind `GATE-HW-02` (PoE multi-vendor bench trial) and `GATE-HW-03` (72-hour thermal soak).**
