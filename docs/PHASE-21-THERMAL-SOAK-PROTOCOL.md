# CAMserv — Phase 21 72-Hour Environmental Thermal Soak Protocol

**Document ID:** PROTOCOL-THERMAL-SOAK-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Hardware:** Profile A — Industrial Edge NVR (Rockchip RK3588, Fanless Aluminum Chassis)  
**Environmental Target:** 72 Hours Continuous Operation at $45^\circ\text{C}$ Ambient  
**Target Software Release:** CAMserv `0.10.0` (Pre-LTS)  
**Date:** November 17, 2026  
**Auditor:** Independent Reliability & Environmental Qualification Authority  

---

## 1. Objective & Regulatory Scope

The objective of this protocol is to establish the formal test methodology for verifying that CAMserv operates reliably under extreme industrial thermal conditions without thermal runaway, CPU frequency collapse, memory leakage, frame loss, evidence corruption, or failure of fail-closed privacy redaction.

This protocol fulfills the criteria for **`GATE-HW-03`**, a mandatory prerequisite before CAMserv can be promoted to `v1.0.0-LTS` General Availability.

---

## 2. Test Environment & Apparatus

### 2.1 Environmental Test Chamber
* **Chamber Type:** Calibrated walk-in or reach-in environmental chamber (Tenney, Espec, or Weiss Technik).
* **Control Parameters:**
  - Ambient Air Temperature: $45.0^\circ\text{C} \pm 1.0^\circ\text{C}$ ($113^\circ\text{F}$).
  - Relative Humidity: $60\% \pm 5\% \text{ RH}$ (non-condensing).
  - Airflow Circulation: Uniform horizontal laminar airflow ($0.5\text{ m/s}$ to simulate sealed cabinet ventilation).

### 2.2 Physical Device Under Test (DUT)
* **Chassis:** Industrial fanless extruded aluminum enclosure with passive heat pipe dissipation fins.
* **Processor:** Rockchip RK3588 (8 cores: 4x Cortex-A76 @ up to 2.4 GHz, 4x Cortex-A55 @ up to 1.8 GHz).
* **Memory:** 16 GB LPDDR4x (rated $-40^\circ\text{C} \text{ to } +85^\circ\text{C}$).
* **Storage:** 1 TB M.2 2280 PCIe NVMe SSD with passive copper heatsink.
* **Thermocouple Instrumentation:**
  - Channel 1 ($T_1$): RK3588 SoC die heat spreader.
  - Channel 2 ($T_2$): NVMe SSD flash controller.
  - Channel 3 ($T_3$): LPDDR4x package.
  - Channel 4 ($T_4$): External chassis heatsink fin surface.
  - Channel 5 ($T_5$): Chamber ambient reference.

```
       +-----------------------------------------------------------+
       |           CALIBRATED THERMAL CHAMBER (45°C / 60% RH)      |
       |                                                           |
       |   +---------------------------------------------------+   |
       |   |      FANLESS INDUSTRIAL APPLIANCE ENCLOSURE       |   |
       |   |                                                   |   |
       |   |   [T4 Heatsink Fin]                               |   |
       |   |         |                                         |   |
       |   |   +-----+-------------------------------------+   |   |
       |   |   | [T1 SoC RK3588]   [T3 LPDDR4x]            |   |   |
       |   |   |  - 4x A76 + 4xA55  - 16GB RAM             |   |   |
       |   |   |  - 6 TOPS NPU                             |   |   |
       |   |   |  - Rockchip MPP                           |   |   |
       |   |   |                                           |   |   |
       |   |   | [T2 NVMe Controller]                      |   |   |
       |   |   |  - 1TB High-IOPS M.2 SSD                  |   |   |
       |   |   +-------------------------------------------+   |   |
       |   +---------------------------------------------------+   |
       |                                                           |
       |   [T5 Chamber Ambient = 45.0°C]                           |
       +-----------------------------------------------------------+
```

---

## 3. Workload Definition (Multi-Channel Stress Load)

The DUT shall execute a continuous, production-equivalent high-density workload throughout the entire 72-hour window (259,200 seconds):

1. **Ingestion:** 16 concurrent RTSP video streams:
   - 8 streams: H.265 (HEVC), 1080p @ 30 fps, 4.0 Mbps constant bitrate (CBR).
   - 8 streams: H.264 (AVC), 1080p @ 30 fps, 4.0 Mbps constant bitrate (CBR).
   - Total network ingestion throughput: $\sim 64\text{ Mbps}$.
2. **Video Decoding & Hardware Acceleration:**
   - Multi-channel decoding handled via Rockchip MPP `/dev/mpp_service`.
3. **AI Pipeline & Privacy Redaction:**
   - Tri-core NPU active at 1000 MHz.
   - Continuous facial and license plate detection at 15 fps per channel.
   - Continuous fail-closed spatial Gaussian blurring on detected regions.
4. **Storage & Forensic Cryptography:**
   - Continuous MP4 segment rotation every 300 seconds across all 16 channels.
   - Ingestion writer fencing validated via active `StorageLease` renewals.
   - Cryptographic SHA-256 digest computation and Ed25519 signature manifest generation for every closed segment.
   - SQLite WAL transaction commits for evidence indexing.

---

## 4. Telemetry Collection & Automated Logging

A dedicated external monitoring daemon (`soak_monitor.py`) connects via the serial console and isolated management Ethernet port, recording metrics every 10 seconds into a persistent append-only TSV ledger:

| Metric | Source / Sysfs Path | Expected Nominal Range | Critical Limit |
| :--- | :--- | :---: | :---: |
| **SoC Junction Temp** | `/sys/class/thermal/thermal_zone0/temp` | $65^\circ\text{C} - 78^\circ\text{C}$ | $> 85.0^\circ\text{C}$ |
| **NPU Core Temp** | `/sys/class/thermal/thermal_zone1/temp` | $62^\circ\text{C} - 75^\circ\text{C}$ | $> 85.0^\circ\text{C}$ |
| **NVMe Temp** | `smartctl -a /dev/nvme0n1` | $50^\circ\text{C} - 68^\circ\text{C}$ | $> 75.0^\circ\text{C}$ |
| **CPU Core Frequency** | `/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq` | $1.8\text{ GHz} - 2.4\text{ GHz}$ | $< 1.2\text{ GHz}$ (Thermal Throttled) |
| **Process RSS Memory** | `/proc/<pid>/statm` (resident pages) | $420\text{ MB} \pm 20\text{ MB}$ | Drift $> 5\text{ MB}$ over 72h |
| **System Free RAM** | `/proc/meminfo` (`MemAvailable`) | $> 12\text{ GB}$ available | $< 1.0\text{ GB}$ (OOM risk) |
| **Frame Loss Ratio** | Ingestion pipeline metrics | $0.000\%$ | $> 0.010\%$ ($> 1\text{ drop} / 10\text{k frames}$) |
| **Storage Lease Validity** | `/system/telemetry` | `true` | `false` (Stale lease) |

---

## 5. Pass / Fail Acceptance Criteria

To achieve certification for **`GATE-HW-03`**, the run must strictly satisfy all of the following criteria over the full 72 continuous hours:

| Requirement ID | Verification Metric | Mandatory Threshold | Result Status |
| :--- | :--- | :--- | :---: |
| **SOAK-AC-01** | Process Continuity | Exactly 0 crashes, panics, or restarts across 259,200 seconds | Mandatory |
| **SOAK-AC-02** | Thermal Headroom | Maximum recorded SoC temperature $\le 85.0^\circ\text{C}$ | Mandatory |
| **SOAK-AC-03** | No Frequency Collapse | Zero occurrences of CPU thermal throttling below 1.4 GHz on big cores | Mandatory |
| **SOAK-AC-04** | Memory Leak Invariant | Total process RSS drift between hour 1 and hour 72 $\le 5.0\text{ MB}$ | Mandatory |
| **SOAK-AC-05** | Frame Delivery Integrity | Dropped frame ratio $\le 0.010\%$ across all 16 streams ($\ge 99.99\%$ delivered) | Mandatory |
| **SOAK-AC-06** | Evidence Cryptographic Integrity| 100% of recorded segments (approx. 2,304 segments) pass SHA-256 and Ed25519 verification | Mandatory |
| **SOAK-AC-07** | Fail-Closed Privacy | 0 unblurred frames leaked; zero privacy bypass events | Mandatory |
| **SOAK-AC-08** | Audit Log Baseline | `logs/audit.jsonl` verified unchanged at 20,977 bytes / SHA-256 invariant intact | Mandatory |

---

## 6. Execution Protocol & Step-by-Step Procedure

### 6.1 Phase 1: Pre-Soak Baseline Calibration (Hours -2 to 0)
1. Mount the DUT in the thermal chamber rack.
2. Connect thermocouple probes $T_1$ through $T_5$ to the data logger.
3. Power on the appliance at room temperature ($21^\circ\text{C}$).
4. Verify all 16 video channels are streaming and recording cleanly.
5. Ramp chamber temperature from $21^\circ\text{C}$ to $45^\circ\text{C}$ at a rate of $1.0^\circ\text{C}/\text{minute}$.
6. Allow DUT to thermally stabilize at $45^\circ\text{C}$ for 60 minutes before initiating formal timing.

### 6.2 Phase 2: 72-Hour Continuous Soak (Hours 0 to 72)
1. Trigger formal soak recording at $T = 00:00:00$.
2. Telemetry daemon logs temperatures, frequencies, memory, and frame rates every 10 seconds.
3. Chamber operator inspects physical ambient temperature and humidity every 4 hours.
4. Continuous automated verification that `StorageLease` heartbeats remain valid.

### 6.3 Phase 3: Post-Soak Verification & Ramp-Down (Hours 72 to 74)
1. Conclude formal 72-hour window at $T = 72:00:00$.
2. Ramp chamber temperature down to $21^\circ\text{C}$ at $1.0^\circ\text{C}/\text{minute}$.
3. Execute forensic validation script on all generated MP4 segments and cryptographic manifests.
4. Verify SQLite database integrity using `PRAGMA integrity_check;`.
5. Verify SHA-256 and byte size of `logs/audit.jsonl`.
6. Compile final telemetry charts and sign off on test report.
