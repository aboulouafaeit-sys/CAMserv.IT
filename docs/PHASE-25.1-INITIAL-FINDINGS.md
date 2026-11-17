# CAMserv — Phase 25.1 Initial Engineering Audit & Findings Register

**Document ID:** AUDIT-P25.1-FINDINGS-2026-001  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25.1 — Reliability Correction & Engineering Hardening  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Systems Architect, Reliability Engineer, Video Pipeline Engineer, Storage Engineer, Hardware Power Engineer & Independent Release Auditor  
**Branch:** `main` | **Git Baseline HEAD:** `bba0681`  

---

## 1. Executive Summary & Audit Mandate

Phase 25 transformed CAMserv into a hardware-adaptive, capability-based appliance architecture. While 456 automated regression and hardware mock tests passed, an independent systems engineering audit of the Phase 25 report and codebase revealed several critical architectural and physical discrepancies:

1. **Enterprise Power Calculation Contradiction (F25.1-01):** The claimed 680W worst-case load for Profile D Enterprise included two NVIDIA RTX 4090 GPUs (450W TDP each), a 32-core AMD EPYC CPU (200W-280W), and 16 spinning HDDs (up to 320W spin-up inrush). Summing these worst-case components yields over $1,200\text{ W}$, completely violating the capacity of a single surviving 800W redundant power supply.
2. **Unsafe Blind CPU Fallback (F25.1-02):** When a hardware accelerator failed or was de-initialized, the system unconditionally transferred all decoding and AI inference tasks to `CPU_UNIVERSAL`. On a host recording 16 to 32 streams, this immediate dump would overwhelm the host CPU, causing frame drops and potential service failure for core recording.
3. **Video Pipeline Ingestion Backpressure Risk (F25.1-03):** Applying synchronous backpressure (`APPLY_BACKPRESSURE`) to an RTSP ingestion producer does not pause camera transmission. Cameras transmit continuously over IP; stalling the consumer fills OS socket buffers, inducing camera disconnections or silent frame drops upstream.
4. **Non-Blocking Thread Cancellation Limitations (F25.1-04):** `NonBlockingExecutor` relied on `threading.Thread(daemon=True)` with timeout waits. If an underlying native C/C++ library (e.g. OpenCV, FFmpeg, driver ioctl, or kernel disk write) hangs, the thread continues running in the background, leaking resources and risking deadlock.
5. **Absence of Dedicated Fault-Injection Stress Suite (F25.1-05):** Automated unit tests verified nominal paths and synthetic state machines, but did not measure UI latency, memory leakage, or recovery dynamics under simulated CPU saturation, slow disks, disk-full conditions, and camera reconnect storms.
6. **Unqualified Camera Capacity Attribution (F25.1-06):** Stream count ranges (e.g., "32–64+ streams up to 128") were presented as general specifications without rigorous attribution distinguishing calculated theoretical capacities from software-tested and physical lab-verified limits.

---

## 2. Baseline Invariants & Repository Verification

Prior to any code modification, the working tree and security invariants were verified:

| Verification Target | Baseline Specification | Actual Measured State | Compliance Status |
| :--- | :--- | :--- | :---: |
| **Active Git Branch** | `main` | `main` | **VERIFIED** |
| **Git Commit Baseline** | `bba0681` | `bba0681` (clean working tree) | **VERIFIED** |
| **Audit Log Byte Length**| 20,977 bytes | **20,977 bytes** | **INVIOLATE** |
| **Audit Log SHA-256** | `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525` | `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525` | **INVIOLATE** |
| **Official Brand Assets**| 34 PNG/SVG/ICO files across `assets/branding/` and `src/camserv/web/assets/` | 34 files intact, zero modifications | **INVIOLATE** |
| **Automated Tests** | 456 passing tests | 456 passed, 0 failed, 1 warning | **VERIFIED** |

---

## 3. Detailed Audit Findings Register

### Finding F25.1-01: Enterprise GPU & Power Budget Physical Contradiction
- **Severity:** HIGH (Hardware Electrical Reliability & Safety)
- **Component:** `ApplianceCatalog._SPEC_ENTERPRISE`, `docs/PHASE-25-POWER-AND-CAPACITY-MODEL.md`
- **Root Cause:**
  - An unconstrained NVIDIA GeForce RTX 4090 has a default board power rating of $450\text{ W}$. Dual RTX 4090 accelerators alone draw up to $900\text{ W}$ at full load.
  - An AMD EPYC 7003/9004 socket draws $155\text{ W}$ to $280\text{ W}$ under maximum AVX-512/dense computation.
  - 16x 3.5" enterprise HDDs exhibit simultaneous 12V inrush spin-up current of $\approx 1.8\text{A}$ per drive ($21.6\text{ W} \times 16 = 345.6\text{ W}$).
  - Summing: $900\text{W (GPUs)} + 250\text{W (CPU)} + 345\text{W (HDDs)} + 50\text{W (Fans/Motherboard)} = \mathbf{1,545\text{ W}}$.
  - Claiming a worst-case power of 680W with dual 800W PSUs where a single surviving PSU carries 680W is mathematically impossible if dual RTX 4090s are installed unthrottled with un-staggered drive spin-up.
- **Required Remediation:**
  1. De-couple discrete GPUs completely from the Enterprise base configuration. Base Enterprise NVR must be CPU-only / distributed inference nodes.
  2. For optional enterprise analytical acceleration, select realistic power-efficient enterprise GPUs: e.g., Dual NVIDIA RTX 4000 Ada Generation SFF (70W TGP each = 140W total) or NVIDIA L4 (72W TGP each = 144W total), or explicitly clamp dual RTX 4090 power targets to $175\text{ W}$ via `nvidia-smi -pl 175` with mandatory firmware enforcement.
  3. Enforce staggered drive spin-up (maximum 2 drives simultaneously, reducing spin-up inrush to $43.2\text{ W}$).
  4. Recalculate true worst-case electrical budgets and verify single-PSU capacity ($P_{\text{surviving}} \ge P_{\text{worst-case}} \times 1.15$).

---

### Finding F25.1-02: Unsafe Blind CPU Fallback Admission
- **Severity:** CRITICAL (System Stability & Evidence Recording Integrity)
- **Component:** `AcceleratorAbstractionManager.handle_accelerator_failure`, `src/camserv/platform/accelerator.py`
- **Root Cause:**
  - Upon accelerator failure or de-initialization, `active_decode_backend` and `active_inference_backend` were immediately switched to `CPU_UNIVERSAL`.
  - No check was performed on host CPU utilization, run queue depth, thermal throttling, or current active stream count.
  - If a 16-channel appliance running at 70% CPU encounters a GPU driver timeout, moving 16 decode pipelines and neural object detection models to CPU immediately causes 100% CPU lockup, buffer overflow, and catastrophic recording loss.
- **Required Remediation:**
  1. Engineer a `CPUFallbackAdmissionController` evaluating:
     - 5-second moving average CPU load
     - Available logical core headroom
     - Active recording stream count
     - Current thermal state and RAM pressure
     - Estimated CPU cost per fallback task
  2. Implement 5 deterministic fallback admission decisions:
     - `FALLBACK_ACCEPTED`: Ample headroom ($< 65\%$ CPU); task admitted at full capability.
     - `FALLBACK_REDUCED`: Moderate headroom ($65\% - 80\%$ CPU); task admitted with downscaled sampling rate.
     - `FALLBACK_DEFERRED`: Elevated headroom ($80\% - 90\%$ CPU); analytical task queued or deferred; recording preserved.
     - `FALLBACK_REJECTED`: Heavy load ($> 90\%$ CPU); analytical task completely rejected; raw video recording strictly protected.
     - `FALLBACK_UNAVAILABLE`: CPU or host resources insufficient to safely host task.
  3. Implement gradual, phased recovery when the accelerator returns to health, preventing thundering herd migration.

---

### Finding F25.1-03: Video Pipeline Backpressure & Discontinuity Accounting
- **Severity:** HIGH (Video Evidence Completeness)
- **Component:** `BoundedPipelineQueue`, `src/camserv/platform/stability.py`
- **Root Cause:**
  - The `BoundedPipelineQueue` applied `APPLY_BACKPRESSURE` uniformly for recording queues.
  - While backpressure is appropriate for local disk writing pipelines, blocking an RTSP network ingest thread does not pause IP cameras. Instead, network buffers overflow and packets drop unpredictably without audit logs.
- **Required Remediation:**
  1. Separate queue policies strictly by pipeline type:
     - **Recording Ingest Pipeline:** Dedicated ring buffer with discontinuity detection. Never block network consumer indefinitely. Track sequence continuity, frame timestamps, and record explicit gap metadata.
     - **Live Preview Pipeline:** Bounded queue with `DROP_OLDEST` to maintain sub-second operator latency.
     - **AI Analytics Pipeline:** Bounded queue with `DROP_OLDEST` and documented downsampling reasons.
     - **Storage Writer Pipeline:** Bounded buffering with explicit disk-full and slow-disk alarms.
  2. Implement recording health and continuity metadata (`RecordingContinuityLedger`):
     - Camera ID, stream ID, segment ID, start/end timestamps.
     - Expected vs. observed frame counts.
     - Discontinuity events and reconnection timestamps.
     - Storage flush latency and integrity verification status.

---

### Finding F25.1-04: Inadequate Non-Blocking Execution & Hung Native Isolation
- **Severity:** MEDIUM (Process Reliability)
- **Component:** `NonBlockingExecutor`, `WorkerCrashSupervisor`
- **Root Cause:**
  - Python `threading.Thread` cannot be forcefully terminated if trapped inside an un-interruptible native system call (e.g., blocking `read()` on network socket or slow disk NFS/SATA hang).
- **Required Remediation:**
  1. Implement worker heartbeat monitoring and hung-worker detection in `WorkerCrashSupervisor`.
  2. Implement process-isolated execution boundaries with watchdog deadlines for native tasks.
  3. Ensure that terminated workers leave partial recordings in a recoverable state (`RECOVERED_PARTIAL`) and that restarts never launch duplicate recording writers for the same camera channel.

---

### Finding F25.1-05: Absence of Automated Stress & Zero-Freeze Injection Tests
- **Severity:** MEDIUM (Quality Assurance & Formal Proof)
- **Component:** `tests/test_phase25_hardware_appliance.py`
- **Root Cause:**
  - Existing Phase 25 tests verified happy paths, formulas, and simulated discrete steps, but did not inject simultaneous resource pressure (CPU spike + disk full + network timeout).
- **Required Remediation:**
  1. Author a dedicated Phase 25.1 test module (`tests/test_phase25_1_reliability_hardening.py`) containing at least 24 targeted stress and fault-injection tests.
  2. Validate CPU fallback admission, queue overflow boundaries, slow storage, disk-full handling, hung worker detection, and evidence durability.

---

### Finding F25.1-06: Unqualified Camera Capacity Claims
- **Severity:** MEDIUM (Specification Truthfulness)
- **Component:** `docs/PHASE-25-HARDWARE-PROFILES.md`, `docs/PHASE-25-CAMERA-WORKLOAD-POLICY.md`
- **Root Cause:**
  - Stated stream counts were presented as absolute appliance specifications without clearly delineating theoretical calculation vs. software-tested vs. physical lab qualification.
- **Required Remediation:**
  1. Update all documentation to categorize every capacity figure into:
     - *Design Target*
     - *Calculated Theoretical Capacity*
     - *Synthetic Benchmark Capacity*
     - *Software Integration-Tested Capacity*
     - *Physical Camera-Tested Capacity* (Lab Gated)
     - *Long-Duration Qualified Capacity* (Lab Gated)
  2. Emphasize that actual achievable stream count depends heavily on bitrate, codec, resolution, and AI sampling frequency.

---

## 4. Stage 1 Verdict & Handoff to Stage 2

- **Audit Result:** **FINDINGS CONFIRMED AND DOCUMENTED**
- **Risks Identified:** High electrical power discrepancy on Enterprise profile; potential host lockup during blind CPU failover; evidence gap risk on network backpressure.
- **Authorization:** Safe to proceed to **Stage 2: Power and BOM Correction**.
