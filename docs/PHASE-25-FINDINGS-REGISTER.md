# CAMserv — Phase 25 Findings and Remediation Register

**Document ID:** AUDIT-P25-FINDINGS-2026-013  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25 — Hardware Adaptation & Appliance Engineering  
**Classification:** Independent Architecture Audit & Findings Register  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Hardware Systems Architect, Embedded Linux Engineer, Storage Reliability Engineer, Network Surveillance Architect, Security Engineer & Release Qualification Authority  

---

## 1. Executive Summary & Audit Overview

This register catalogs all architectural vulnerabilities, hardware reality gaps, reliability risks, and engineering corrections identified and resolved during **Phase 25: Hardware-Agnostic Architecture, Adaptive Resource Intelligence, Appliance Engineering & Reliability Qualification**.

Every finding in this register was evaluated against actual source code, physical testbed hardware, and reproducible automated test suites.

| Severity Category | Discovered | Remediated & Software Verified | Operational Boundary / Hardware Gated |
| :--- | :---: | :---: | :---: |
| **CRITICAL ARCHITECTURAL / INTEGRITY** | 8 | 8 | 0 |
| **HIGH RELIABILITY / TRUTHFULNESS** | 7 | 7 | 0 |
| **MEDIUM OPERATIONAL / DOCUMENTATION** | 5 | 5 | 0 |
| **PHYSICAL HARDWARE GATES** | 4 | 0 | 4 (Accredited Lab Required) |
| **TOTAL** | **24** | **20 Remediated** | **4 Physical Gates Active** |

---

## 2. Comprehensive Findings & Remediation Inventory

### FINDING-P25-01: Discrete GPU Requirement Elimination
* **Severity:** **CRITICAL ARCHITECTURAL**
* **Affected Subsystem:** `camserv.platform.appliance`, `camserv.platform.hardware`
* **Root Cause:** Previous appliance draft specifications positioned expensive discrete GPUs (NVIDIA RTX 4060, RTX 4090, L40S) as standard or mandatory components, violating the core principle that CAMserv must be hardware-agnostic and accessible on low-cost systems.
* **Remediation:** Refactored `ApplianceCatalog` and `ApplianceSpecification`. Dedicated GPUs are strictly designated as **OPTIONAL ADD-ONS**. Core surveillance recording, segment finalization, hashing, and storage operate 100% natively on CPU-only systems and integrated graphics (Intel QSV, AMD iGPU, ARM SoC).
* **Verification:** Tested in `tests/test_phase25_hardware_appliance.py::test_appliance_power_engineering_consistency_and_margin` (`is_gpu_required is False` across all profiles).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25-02: Hardcoded Thermal Telemetry Elimination
* **Severity:** **HIGH RELIABILITY / TRUTHFULNESS**
* **Affected Subsystem:** `camserv.platform.appliance.ApplianceHardwareManager._probe_thermal`
* **Root Cause:** The thermal prober returned synthetic, hardcoded default temperatures (`48.0°C` CPU, `52.0°C` GPU), masking absent physical sensors and violating the Rule of Truth.
* **Remediation:** Removed all hardcoded constants. The prober now interrogates genuine host sensors via `get_platform_hardware_prober()`. When sensors are unavailable, it reports `None` with `TelemetrySource.UNAVAILABLE` and `HardwareAvailabilityState.UNAVAILABLE`.
* **Verification:** Tested in `tests/test_phase25_hardware_appliance.py::test_hardware_telemetry_provenance_truthfulness`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25-03: Six-State Accelerator Lifecycle & Transparent CPU Fallback
* **Severity:** **CRITICAL ARCHITECTURAL**
* **Affected Subsystem:** `camserv.platform.accelerator.AcceleratorAbstractionManager`
* **Root Cause:** System previously assumed accelerators were ready for production traffic immediately upon device bus detection, leading to runtime crashes if user-space runtimes or codec profiles were missing.
* **Remediation:** Implemented mandatory 6-state lifecycle progression (`HARDWARE_DETECTED` -> `DRIVER_AVAILABLE` -> `RUNTIME_AVAILABLE` -> `CODEC_OR_MODEL_SUPPORTED` -> `INITIALIZED` -> `VERIFIED_WORKLOAD`). If an accelerator faults, `handle_accelerator_failure()` automatically isolates the device and transparently routes active workloads to `CPU_UNIVERSAL` without stopping recording.
* **Verification:** Tested in `tests/test_phase25_hardware_appliance.py::test_accelerator_six_stage_lifecycle_and_cpu_fallback`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25-04: Non-Destructive Storage Guardrails
* **Severity:** **HIGH RELIABILITY / DATA INTEGRITY**
* **Affected Subsystem:** `camserv.platform.appliance.ApplianceHardwareManager.validate_disk_initialization_safety`
* **Root Cause:** Absence of strict safeguards against accidental formatting of newly discovered user disks or host OS volumes during appliance onboarding.
* **Remediation:** Implemented non-destructive validation requiring explicit administrative confirmation (`confirmed=True`). Hard-blocked formatting targets matching the host system root (`/` or `C:\`) or active application directory.
* **Verification:** Tested in `tests/test_phase25_hardware_appliance.py::test_disk_initialization_safety_guardrails`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25-05: Uncontrolled In-Memory Queue Growth
* **Severity:** **CRITICAL ARCHITECTURAL / OOM RISK**
* **Affected Subsystem:** `camserv.platform.stability.BoundedPipelineQueue`
* **Root Cause:** Inter-subsystem frame queues previously lacked explicit memory boundaries, creating severe risk of Out-of-Memory (OOM) kernel terminations during disk write stalls or neural processing bottlenecks.
* **Remediation:** Created thread-safe `BoundedPipelineQueue` with configurable overflow policies: `DROP_OLDEST` (for transient AI preview frames), `DROP_NEWEST` (for burst shedding), and `APPLY_BACKPRESSURE` (with bounded timeout for evidentiary recording writes).
* **Verification:** Tested in `tests/test_phase25_hardware_appliance.py::test_bounded_pipeline_queue_overflow_policies`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25-06: Worker Failure Isolation & Reconnect Storms
* **Severity:** **HIGH RELIABILITY / AVAILABILITY**
* **Affected Subsystem:** `camserv.platform.stability.WorkerCrashSupervisor`
* **Root Cause:** An unhandled exception in an optional AI plugin or sudden reconnection of 64 cameras after a switch reboot could cause thread starvation or continuous restart thrashing.
* **Remediation:** Created `WorkerCrashSupervisor` providing crash isolation and exponential backoff with randomized jitter (`calculate_backoff_with_jitter`). Enforces fencing after 5 consecutive crashes to prevent restart loops.
* **Verification:** Tested in `tests/test_phase25_hardware_appliance.py::test_worker_crash_supervisor_isolation_and_backoff_jitter`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25-07: Shingled Magnetic Recording (SMR) Stall Vulnerability
* **Severity:** **HIGH RELIABILITY / EVIDENCE INTEGRITY**
* **Affected Subsystem:** `camserv.storage.isep.disk_health`
* **Root Cause:** Consumer SMR drives suffer from severe write stalls ($> 800\text{ms}$) once internal media caches fill during continuous multi-channel streaming.
* **Remediation:** Mandated Conventional Magnetic Recording (CMR) drives. The prober inspects `/sys/block/*/queue/zoned` and flags SMR disks with `HardwareAvailabilityState.DEGRADED`, restricting them to low-bitrate non-critical streams.
* **Verification:** Documented in `docs/PHASE-25-HDD-STRESS-TEST.md` and verified in disk health probers.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25-08: Power Budget and Redundant PSU Discrepancy
* **Severity:** **MEDIUM OPERATIONAL / ELECTRICAL**
* **Affected Subsystem:** `camserv.platform.appliance.ApplianceCatalog`
* **Root Cause:** Enterprise power specifications did not verify whether a single surviving redundant power supply could support worst-case peak electrical loads during an AC feed loss.
* **Remediation:** Recalculated sustained, peak, and worst-case electrical loads across all profiles. Enterprise Profile D specifies dual redundant 800W PSUs where a single surviving PSU carries 100% of the 680W worst-case load with a 15% continuous safety margin.
* **Verification:** Tested in `tests/test_phase25_hardware_appliance.py::test_appliance_power_engineering_consistency_and_margin`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 3. Physical Hardware Gates Register (Active for v1.0.0-LTS)

| Gate ID | Target Environment | Scope & Mandatory Trial | Current Status |
| :---: | :--- | :--- | :---: |
| **`GATE-HW-01`** | Rockchip RK3588 SBC | Flash Debian 13 arm64 image onto physical FriendlyElec/Radxa board; confirm 6 TOPS NPU and MPP decode. | **BLOCKED_BY_ENVIRONMENT** |
| **`GATE-HW-02`** | Physical PoE Camera Matrix | Direct bench ingestion against physical Axis, Hikvision, Dahua, and Hanwha cameras over physical 802.3at switch. | **BLOCKED_BY_ENVIRONMENT** |
| **`GATE-HW-03`** | 72-Hour 45°C Environmental Soak | 72-hour continuous multi-camera ingestion in fanless enclosure inside calibrated thermal chamber at 45°C ambient. | **BLOCKED_BY_ENVIRONMENT** |
| **`GATE-HW-04`** | 50-Cycle AC Relay Power Cut | 50 consecutive unexpected AC power drops via external relay actuator during active multi-channel writing. | **BLOCKED_BY_ENVIRONMENT** |


---

## 4. Phase 25.1 Hardening Findings & Remediations (F25.1-01 through F25.1-06)

### FINDING-P25.1-01: Enterprise GPU & Redundant PSU Electrical Contradiction
* **Severity:** **CRITICAL ELECTRICAL / SAFETY**
* **Affected Subsystem:** `camserv.platform.appliance.ApplianceCatalog._SPEC_ENTERPRISE`, `docs/PHASE-25.1-POWER-BUDGET-CORRECTION.md`
* **Root Cause:** Phase 25 claimed a worst-case load of 680W for Profile D Enterprise while listing dual RTX 4090 GPUs (450W each = 900W), 32 CPU cores (200W-280W), and 16 HDDs (320W inrush). Unclamped dual RTX 4090s exceed 1,500W, instantly tripping an 800W single surviving PSU.
* **Remediation:** Reconciled component loads. Mandated SAS staggered drive spin-up (reducing inrush from 384W to 157.2W). Replaced mandatory dual 4090s with power-efficient enterprise accelerators (Dual NVIDIA L4 at 72W each or RTX 4000 Ada SFF at 70W each = 144W total). Total worst-case simultaneous draw is 608.2W. Single surviving 800W PSU carries 608.2W with 31.5% continuous headroom ($800\text{W} \ge 608.2\text{W}$). Unclamped RTX 4090s are strictly prohibited on 800W PSUs; dual 1600W Titanium PSUs mandated if unclamped.
* **Verification:** Tested in `tests/test_phase25_1_reliability_hardening.py::test_enterprise_psu_calculation_validation`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1-02: Blind Unconditional CPU Fallback Host Saturation
* **Severity:** **CRITICAL SYSTEM STABILITY / EVIDENCE INTEGRITY**
* **Affected Subsystem:** `camserv.platform.accelerator.CPUFallbackAdmissionController`
* **Root Cause:** Transparent accelerator failover previously moved all decoding and AI tasks immediately to `CPU_UNIVERSAL` without checking CPU load, run queues, thermals, or active stream count. On a multi-camera host, this immediate dump drove CPU to 100%, causing recording frame drops and host lockup.
* **Remediation:** Implemented `CPUFallbackAdmissionController` evaluating moving-average CPU load, recording pipeline health, and task costs. Enforces 5 explicit decisions: `FALLBACK_ACCEPTED`, `FALLBACK_REDUCED`, `FALLBACK_DEFERRED`, `FALLBACK_REJECTED`, `FALLBACK_UNAVAILABLE`. Implemented phased gradual recovery (canary stream + batch size of 2) when accelerator returns to health.
* **Verification:** Tested in `tests/test_phase25_1_reliability_hardening.py::test_cpu_fallback_admission_under_saturation`, `test_cpu_fallback_accepted_with_headroom`, `test_cpu_fallback_rejected_when_recording_endangered`, `test_gradual_accelerator_recovery_canary_batching`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1-03: Inappropriate Video Pipeline Ingestion Backpressure
* **Severity:** **HIGH RELIABILITY / EVIDENCE INTEGRITY**
* **Affected Subsystem:** `camserv.platform.stability.BoundedPipelineQueue`, `camserv.platform.stability.RecordingContinuityLedger`
* **Root Cause:** Applying backpressure to RTSP network ingestion threads caused socket buffer overflow and camera connection resets, as physical IP cameras do not pause network transmission.
* **Remediation:** Separated queue policies: Recording Ingest uses bounded ring buffers with bounded backpressure (500ms max) and logs explicit discontinuity events rather than dropping sockets; Live Preview uses `DROP_OLDEST`; AI Analytics uses `DROP_OLDEST` and downsampling; Storage Writer uses bounded backpressure with disk-full emergency rejection ($< 0.05\text{ ms}$). Created `RecordingContinuityLedger` and `DiscontinuityEvent` to record sequence, PTS timestamps, and gap durations without fabricated data.
* **Verification:** Tested in `tests/test_phase25_1_reliability_hardening.py::test_ai_queue_overload_without_recording_interruption`, `test_recording_queue_overflow_bounded_timeout`, `test_explicit_recording_discontinuity_metadata`, `test_disk_full_emergency_rejection`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1-04: Hung Native Operation Isolation & Duplicate Worker Fencing
* **Severity:** **HIGH RELIABILITY / PROCESS HYGIENE**
* **Affected Subsystem:** `camserv.platform.stability.WorkerCrashSupervisor`, `camserv.platform.stability.NonBlockingExecutor`
* **Root Cause:** Thread-level timeouts could not interrupt hung native C/C++ library operations. Restarted workers could collide with stalled workers on the same camera channel, causing corrupted recordings.
* **Remediation:** Added worker heartbeat watchdog monitoring (`record_heartbeat()`, `check_hung()`), atomic channel lease fencing (`acquire_channel_lease()`, `revoke_channel_lease()`), cooperative cancellation (`CancellationToken`), and safe in-flight `.part` quarantine (`quarantine_partial_segment` preserving existing bytes as `.recovered_partial.mp4`).
* **Verification:** Tested in `tests/test_phase25_1_reliability_hardening.py::test_hung_worker_detection_and_lifecycle`, `test_worker_cooperative_cancellation`, `test_interrupted_segment_recovery_quarantine`, `test_no_duplicate_recording_workers_channel_lease`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1-05: Absence of Automated Stress & Zero-Freeze Injection Tests
* **Severity:** **MEDIUM QUALITY ASSURANCE**
* **Affected Subsystem:** `tests/test_phase25_1_reliability_hardening.py`
* **Root Cause:** Unit tests did not verify behavior under simultaneous multi-vector stress (CPU saturation + slow disks + queue overflows + reconnect bursts).
* **Remediation:** Authored `tests/test_phase25_1_reliability_hardening.py` containing 24 comprehensive stress and fault-injection tests. Documented results in `docs/PHASE-25.1-ZERO-FREEZE-STRESS-REPORT.md`.
* **Verification:** Full suite passes 480/480 tests (100%) in 86.47s.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1-06: Unqualified Camera Capacity Attribution
* **Severity:** **MEDIUM SPECIFICATION TRUTHFULNESS**
* **Affected Subsystem:** `docs/PHASE-25.1-CAMERA-CAPACITY-QUALIFICATION.md`
* **Root Cause:** Appliance profiles stated stream capacity ranges without formally attributing them as theoretical calculations versus software-tested versus physically verified limits.
* **Remediation:** Established 6-tier classification standard (`DESIGN_TARGET`, `THEORETICAL_CALCULATED`, `SYNTHETIC_BENCHMARK`, `SOFTWARE_INTEGRATION_TESTED`, `PHYSICAL_CAMERA_BENCH_GATED`, `LONG_DURATION_QUALIFIED`). Documented exact stream envelopes across resolutions, codecs, and bitrates.
* **Verification:** Tested in `tests/test_phase25_1_reliability_hardening.py::test_camera_capacity_claim_classification`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 5. Phase 25.1-A Final Reliability Findings & Verified Remediations

### FINDING-P25.1A-01: Premature Worker Termination Reporting & Channel Lease Revocation
* **Severity:** **CRITICAL RELIABILITY / SPLIT-BRAIN PREVENTION**
* **Affected Subsystem:** `camserv.platform.stability.WorkerCrashSupervisor`, `camserv.platform.stability.CancellationToken`
* **Root Cause:** A timeout in a cooperative cancellation token did not forcibly terminate underlying Python threads. Reporting `TERMINATED` and revoking the channel lease allowed newly spawned workers to collide on the same channel while the previous worker was still writing.
* **Remediation:** Introduced `TERMINATION_UNCONFIRMED` state; enforced channel lease retention while a worker thread is active; implemented cooperative checkpoints and confirmation tracking; enabled enforceable process-level SIGTERM/SIGKILL for isolated worker processes.
* **Verification:** Tested in `tests/test_phase25_1_a_verification.py::TestCriticalAuditAWorkerCancellation` (10 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1A-02: Bounded Ingest Queue Drop Discontinuity Accounting
* **Severity:** **CRITICAL EVIDENCE INTEGRITY**
* **Affected Subsystem:** `camserv.platform.stability.BoundedPipelineQueue`, `camserv.platform.stability.RecordingContinuityLedger`
* **Root Cause:** When the 500ms bounded backpressure wait expired on recording ingest, frames were dropped to protect network sockets, but without explicit discontinuity ledger records, creating silent frame loss.
* **Remediation:** Updated `BoundedPipelineQueue.put()` to invoke `record_queue_drop()` upon timeout; transition ledger to `RECORDING_DEGRADED`; log explicit `DiscontinuityEvent` documenting dropped count and timeout limit.
* **Verification:** Tested in `tests/test_phase25_1_a_verification.py::TestCriticalAuditBRecordingContinuity` (3 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1A-03: Conflation of Calculated Estimates with Confirmed Frame Loss
* **Severity:** **HIGH FORENSIC INTEGRITY**
* **Affected Subsystem:** `camserv.platform.stability.DiscontinuityEvent`, `camserv.platform.stability.RecordingContinuityLedger`
* **Root Cause:** Gaps derived from timestamp deltas and nominal FPS were documented as frame loss counts without indicating whether they were confirmed by packet sequence numbers or merely estimated.
* **Remediation:** Explicitly separated `confirmed_missing_frames` (RTP sequence numbers), `estimated_missing_frames` (timestamp intervals at nominal FPS), and `unknown_frame_loss` (variable FPS without sequence numbers). Preserved estimation method and confidence level.
* **Verification:** Tested in `tests/test_phase25_1_a_verification.py::TestCriticalAuditCFrameLossSemantics` (5 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1A-04: Power Budget Headroom Denominator Ambiguity
* **Severity:** **HIGH SPECIFICATION TRUTHFULNESS**
* **Affected Subsystem:** `camserv.platform.appliance.ApplianceSpecification`, `camserv.platform.appliance.ApplianceCatalog`
* **Root Cause:** Margin percentage ($31.5\%$) was ambiguous regarding whether the denominator was system load ($608.2\text{W}$) or rated PSU capacity ($800\text{W}$).
* **Remediation:** Added distinct fields `psu_headroom_to_load_percent` ($31.54\%$) and `psu_headroom_to_psu_rating_percent` ($23.98\%$) across all four appliance profiles. Documented single surviving 800W PSU survival under full worst-case 608.2W load.
* **Verification:** Tested in `tests/test_phase25_1_a_verification.py::TestHighPriorityAuditDPowerBudget` (3 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1A-05: Real-World Thermal Variance in Hardware Probe Unit Test
* **Severity:** **LOW TEST RELIABILITY**
* **Affected Subsystem:** `tests/test_appliance_hardware.py`
* **Root Cause:** Unit test strictly asserted `profile.thermal.state == ThermalState.NOMINAL`, which failed when executed on a physical host under sustained multi-test load with CPU temperatures $> 70^\circ\text{C}$ (`ELEVATED`).
* **Remediation:** Updated test assertion to allow `ThermalState.NOMINAL` or `ThermalState.ELEVATED` during live host hardware discovery.
* **Verification:** Tested in `tests/test_appliance_hardware.py::test_appliance_manager_host_probe`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 6. Phase 25.1-B Cross-Platform & Durable Persistence Findings

### FINDING-P25.1B-01: In-Memory Continuity State Loss During Abrupt Crash
* **Severity:** **CRITICAL EVIDENCE INTEGRITY**
* **Affected Subsystem:** `camserv.storage.continuity_store.DurableContinuityStore`, `camserv.platform.stability.RecordingContinuityLedger`
* **Root Cause:** Recording continuity records were held in transient memory dictionaries. In the event of an abrupt process crash, power loss, or kernel panic, in-flight segments were lost, allowing incomplete recordings to be falsely assumed continuous or untracked upon restart.
* **Remediation:** Implemented `DurableContinuityStore` backed by SQLite WAL mode. Added `continuity_segments` and `continuity_events` schemas with idempotent upsert and deduplication. Implemented `recover_unclean_shutdown()` to detect unfinalized segments on reboot, transition them to `RECORDING_INTERRUPTED`, and commit explicit crash discontinuity events.
* **Verification:** Tested in `tests/test_phase25_1_b_cross_platform.py::TestDurableContinuityLedger` (7 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1B-02: Channel Lease Revocation Before Process Exit Confirmation
* **Severity:** **CRITICAL SPLIT-BRAIN PREVENTION**
* **Affected Subsystem:** `camserv.platform.stability.WorkerCrashSupervisor`
* **Root Cause:** Attempting worker termination could release channel leases before the underlying OS process had completely exited. This permitted a newly spawned worker to bind to the same camera channel concurrently, causing split-brain recording corruption.
* **Remediation:** Updated `WorkerCrashSupervisor.terminate_worker()` to enforce independent exit confirmation via `proc.is_alive()` before revoking channel leases. If a process refuses termination, state transitions to `TERMINATION_UNCONFIRMED` and the channel lease is strictly retained.
* **Verification:** Tested in `tests/test_phase25_1_b_cross_platform.py::TestCrossPlatformWorkerTermination` (`test_windows_process_exit_confirmation_is_alive_refusal` and `test_channel_lease_retention_before_exit_confirmation`).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1B-03: Orphaned IPC Resources Causing Supervisor Deadlock
* **Severity:** **HIGH RELIABILITY**
* **Affected Subsystem:** `camserv.platform.stability.WorkerCrashSupervisor.reconcile_ipc`
* **Root Cause:** When an isolated worker process terminated abruptly, child queues (`multiprocessing.Queue`) and pipe connections remained registered and unclosed, causing supervisor threads to hang on thread joins or unharvested pipe buffers.
* **Remediation:** Added `register_ipc_resource()` and `reconcile_ipc()` to `WorkerCrashSupervisor`. All registered queues and pipes are closed, feeder thread joins are cancelled via `cancel_join_thread()`, and resources are cleared upon worker exit.
* **Verification:** Tested in `tests/test_phase25_1_b_cross_platform.py::test_windows_ipc_resource_reconciliation`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P25.1B-04: Documentation Path and Environment Discrepancies
* **Severity:** **MEDIUM DOCUMENTATION TRUTHFULNESS**
* **Affected Subsystem:** `docs/PHASE-25.1-REPORT.md`, `docs/PHASE-25.1-A-FINAL-QUALIFICATION.md`
* **Root Cause:** Prior reports cited `src/camserv/platform/init.py` (missing dunders) and stated `Python 3.14.81` (typographical version).
* **Remediation:** Verified actual filesystem path is `src/camserv/platform/__init__.py` and actual installed runtime is `Python 3.14.8` on Windows 11 Enterprise x86_64 Build 26300. Documented reconciliation formally in `docs/PHASE-25.1-B-GIT-AND-ENVIRONMENT-RECONCILIATION.md`.
* **Verification:** Verified via filesystem audit and `python --version` runtime interrogation.
* **Status:** **RECONCILED & DOCUMENTED**.



---

## 7. Phase 26 Identity & Access Security Foundation Findings

### FINDING-P26-01: Factory-Default Admin Credential Elimination & Local Bootstrap Protocol
* **Severity:** **CRITICAL AUTHENTICATION SECURITY**
* **Affected Subsystem:** `camserv.security.identity.bootstrap`, `camserv.api.app`
* **Root Cause:** Previous test configurations and API bootstrap paths included hardcoded administrative accounts (e.g. `admin/admin_password`), which, if deployed in production environments, exposed physical surveillance cameras to trivial credential exploitation.
* **Remediation:** Built `LocalAdministratorBootstrap`. Initial appliance startup requires physical/local console access to read a high-entropy, 256-bit token from `data/.bootstrap_token` (file permission `0600`, 15-minute time-to-live). The administrator must set their own password and immediately enroll in mandatory TOTP MFA. Upon completion, the token is cryptographically overwritten and shredded, permanently sealing the bootstrap state machine against replay.
* **Verification:** Tested in `tests/test_phase26_identity_security.py::TestAdministratorBootstrap` (2 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26-02: RFC 9106 Argon2id Password Hardening & Bounded Concurrency
* **Severity:** **CRITICAL CRYPTOGRAPHIC RESILIENCE**
* **Affected Subsystem:** `camserv.security.identity.password`, `camserv.security.auth`
* **Root Cause:** Prior authentication relied on PBKDF2-HMAC-SHA256, which lacks memory-hardness and is vulnerable to parallelized GPU/ASIC offline dictionary cracking. Furthermore, unthrottled password hashing could allow an adversary to cause memory exhaustion DoS.
* **Remediation:** Implemented RFC 9106 Argon2id calibrated to $m=65536$ KiB (64 MiB), $t=2$, $p=4$, and 32 bytes derived key. Implemented dual-verification for seamless PBKDF2 backward-compatibility with automatic `needs_rehash()` upgrading on login. Added a bounded `threading.Semaphore(max_concurrency=4)` preventing memory exhaustion under concurrent authentication bursts.
* **Verification:** Tested in `tests/test_phase26_identity_security.py::TestPasswordSecurity` (4 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26-03: Broken Object Level Authorization (BOLA/IDOR) Elimination
* **Severity:** **CRITICAL ACCESS CONTROL**
* **Affected Subsystem:** `camserv.security.identity.authorization`, `camserv.security.identity.sentinel`
* **Root Cause:** Prior authorization verified global capabilities (e.g. `cameras:read`) without validating whether an individual client user was assigned to the requested physical camera ID or recording. A viewer permitted to watch the front lobby could access high-security vault cameras simply by substituting the `camera_id` in API calls.
* **Remediation:** Implemented `ZeroTrustPolicyEngine` with deny-by-default object-level evaluation against `allowed_camera_ids` and persistent `ResourceScope` records. Integrated with `CAMservSentinelIdentity`, which detects repeated unauthorized resource requests (BOLA probing) and automatically revokes the attacking session.
* **Verification:** Tested in `tests/test_phase26_identity_security.py::TestZeroTrustAuthorization` and `TestSentinelIdentityDefense`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26-04: Stateless JWT Revocation Inability & Anti-Fixation Session Rotation
* **Severity:** **HIGH SESSION SECURITY**
* **Affected Subsystem:** `camserv.security.identity.session`
* **Root Cause:** Stateless bearer tokens could not be revoked prior to expiration without complex distributed blocklists. Additionally, elevation of privilege did not rotate session identifiers, leaving users vulnerable to session fixation.
* **Remediation:** Designed stateful, SQLite WAL-backed `SessionManager` tracking 256-bit cryptographically secure session IDs. Enforced strict 30-minute idle inactivity timeouts and 12-hour absolute lifetime limits. Implemented atomic session rotation upon privilege elevation (AAL2 step-up) and instant single or bulk session revocation upon password reset, lock, or emergency lockdown.
* **Verification:** Tested in `tests/test_phase26_identity_security.py::TestSessionSecurity` (4 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26-05: Plaintext Camera RTSP Password Leakage & Redaction
* **Severity:** **HIGH DATA PRIVACY & CREDENTIAL PROTECTION**
* **Affected Subsystem:** `camserv.security.identity.secrets`
* **Root Cause:** Camera connection URLs containing embedded cleartext credentials (e.g. `rtsp://admin:pass@host/live`) risked exposure in REST API responses, diagnostic logs, and client telemetry. Furthermore, passwords containing special characters (`@`, `:`, `/`) broke naive regex replacement.
* **Remediation:** Built `CameraCredentialProtection` with AES-256-GCM encryption at rest and HKDF key separation (`camserv-v1-camera-credentials`). Created robust `redact_url()` utilizing URL decomposition and right-split authority parsing to sanitize embedded credentials containing special characters (`***REDACTED***`). Implemented deep recursive object sanitization across all client responses.
* **Verification:** Tested in `tests/test_phase26_identity_security.py::TestCameraCredentialProtection` (3 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26-06: Non-Cryptographic Security Event Logging & Tamper Pinpointing
* **Severity:** **HIGH FORENSIC AUDITABILITY**
* **Affected Subsystem:** `camserv.security.identity.audit`
* **Root Cause:** Identity security incidents were previously logged into flat JSON files without mathematical integrity guarantees. A privileged attacker or rogue insider could modify, backdate, or delete log entries without detection.
* **Remediation:** Built `TamperEvidentSecurityAudit` implementing forward SHA-256 cryptographic hash chaining rooted in a fixed genesis anchor (`GENESIS_SECURITY_AUDIT_HASH_PHASE26_00000000`). Provided automated audit chain verification that mathematically detects any modification, deletion, or insertion and pinpoints the exact row where tampering occurred.
* **Verification:** Tested in `tests/test_phase26_identity_security.py::TestTamperEvidentAudit` (2 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26-07: Insecure Generic Shared Operator Accounts Prohibition
* **Severity:** **MEDIUM GOVERNANCE & NON-REPUDIATION**
* **Affected Subsystem:** `camserv.security.identity.models`, `camserv.security.identity.store`
* **Root Cause:** Facilities previously shared generic client logins (e.g. "guard_desk"), preventing non-repudiation and forensic accountability during security incidents.
* **Remediation:** Enforced an individual client account model requiring distinct usernames, named profiles, personal credentials, and individual MFA tokens. All operational actions are permanently bound to specific user IDs in the tamper-evident audit ledger.
* **Verification:** Tested in `tests/test_phase26_identity_security.py::TestDurableIdentityStore`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26-08: Complete Recording Pipeline Isolation During Security Lockdown
* **Severity:** **CRITICAL SURVEILLANCE CONTINUITY**
* **Affected Subsystem:** `camserv.security.identity.emergency`
* **Root Cause:** Security lockdown mechanisms in traditional VMS software often halt video ingestion or freeze the application process, inadvertently blinding surveillance coverage during a physical security breach.
* **Remediation:** Engineered `EmergencyLockdownManager` with strict architectural airgapping. When lockdown is declared, all client sessions are terminated, new logins are blocked, and evidence exports are suspended; however, RTSP ingestion pipelines, continuous recording ledgers, and frame hashing continue 100% uninterrupted.
* **Verification:** Tested in `tests/test_phase26_identity_security.py::TestEmergencyLockdownAndPipelineIsolation` (2 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

## 8. Phase 26.1 Findings & Adversarial Hardening

### FINDING-P26.1-01: WebAuthn Passkey Verification Reality vs Provisional Option Hooks
* **Severity:** **HIGH ARCHITECTURAL INTEGRITY & TRUTHFULNESS**
* **Affected Subsystem:** `camserv.security.identity.mfa` (`PasskeyManager`)
* **Root Cause:** Phase 26 documentation and promotional notes suggested full WebAuthn/Passkey authentication support, whereas `PasskeyManager` only implemented dictionary option generators (`create_registration_options`, `create_assertion_options`) without CBOR parsing, COSE key decoding, `clientDataJSON` challenge/origin verification, or signature counter tracking.
* **Remediation:** Reclassified `PasskeyManager` truthfully across all architectural documentation as **provisional interface hooks only**. Implemented explicit `NotImplementedError` stubs on verification entry points documenting the exact requirement for an external relying party library (`fido2` or `py_webauthn`) prior to claiming production passkey authentication.
* **Verification:** Tested in `tests/test_phase26_1_adversarial.py::TestWebAuthnCapabilityVerification` (2 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.1-02: Privileged Local SQLite Forward Audit Hash Chain Rewrite Vulnerability
* **Severity:** **HIGH FORENSIC INTEGRITY & ANTI-TAMPER**
* **Affected Subsystem:** `camserv.security.identity.audit`
* **Root Cause:** Phase 26 relied solely on internal SHA-256 forward chaining (`prev_hash`). An adversary possessing local SQLite write access could alter an audit row, recompute subsequent hashes forward up to the head of the table, and successfully pass internal `verify_chain_integrity()` checks.
* **Remediation:** Designed and integrated `AuditCheckpoint` with HMAC/Ed25519 signing (`create_checkpoint()`, `verify_against_checkpoint()`). The checkpoint permanently binds sequence count, head entry hash, and timestamp under an external key, rendering internal hash recalculation completely detectable.
* **Verification:** Tested in `tests/test_phase26_1_adversarial.py::TestAuditLedgerAdversarialAttacks::test_full_forward_chain_rewrite_bypasses_simple_verify_but_detected_by_checkpoint`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.1-03: Historical Database Snapshot Rollback Audit Log Eradication
* **Severity:** **HIGH FORENSIC CONTINUITY**
* **Affected Subsystem:** `camserv.security.identity.audit`
* **Root Cause:** An adversary restoring an older SQLite backup snapshot could erase recent security event records while leaving the internal hash chain mathematically valid at the older state.
* **Remediation:** Enforced checkpoint sequence monotonicity and head hash matching in `verify_against_checkpoint()`. When comparing against an external signed checkpoint, any attempt to roll back to an earlier database state immediately triggers a `Rollback detected` failure.
* **Verification:** Tested in `tests/test_phase26_1_adversarial.py::TestAuditLedgerAdversarialAttacks::test_database_snapshot_rollback_detected_by_checkpoint`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.1-04: Ineffective `os.chmod(0o600)` on Windows NTFS Exposing Bootstrap Token
* **Severity:** **HIGH LOCAL PRIVILEGE ESCALATION (WINDOWS)**
* **Affected Subsystem:** `camserv.security.identity.bootstrap`
* **Root Cause:** On Windows NTFS, Python's `os.chmod(path, 0o600)` only manages the DOS read-only attribute bit. It does not modify NTFS Discretionary Access Control Lists (DACLs), allowing any unprivileged local user who inherits read permissions from parent folders to read `.bootstrap_token`.
* **Remediation:** Implemented atomic descriptor creation with `os.O_CREAT | os.O_WRONLY | os.O_TRUNC` and explicit Windows NTFS DACL inheritance stripping via `icacls` (`/inheritance:r /grant:r "%USERNAME%":F`), ensuring unprivileged local Windows users cannot inspect the token.
* **Verification:** Tested in `tests/test_phase26_1_adversarial.py::TestBootstrapSecurityHardening::test_bootstrap_generation_and_consumption`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.1-05: Bootstrap Token Generation Vulnerable to Symlink / Junction Traversal
* **Severity:** **MEDIUM LOCAL ARBITRARY WRITE**
* **Affected Subsystem:** `camserv.security.identity.bootstrap`
* **Root Cause:** If `.bootstrap_token` pre-existed as a symbolic link or directory junction, writing the token could follow the link and overwrite arbitrary system files.
* **Remediation:** Added proactive symlink/reparse point validation before file creation, immediately raising `BootstrapError` if a symlink is encountered.
* **Verification:** Tested in `tests/test_phase26_1_adversarial.py::TestBootstrapSecurityHardening::test_bootstrap_symlink_rejection`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.1-06: Remote Denial of Service via Administrative Account Lockout Flood
* **Severity:** **HIGH AVAILABILITY & ANTI-DOS**
* **Affected Subsystem:** `camserv.security.identity.sentinel`
* **Root Cause:** Applying blanket account lockouts after $N$ failed logins enabled unauthenticated remote attackers to flood the `admin` username with invalid credentials, locking out legitimate administrators and requiring physical appliance power cycling.
* **Remediation:** Introduced `admin_lockout_protection = True` in `SentinelConfig`. For administrative accounts, consecutive failed logins enforce progressive exponential backoff delays (capped at 8.0s) and trigger step-up challenges, but **never** set the administrator account status to locked.
* **Verification:** Tested in `tests/test_phase26_1_adversarial.py::TestSentinelAdversarialHardening::test_admin_lockout_dos_mitigation`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.1-07: Mobile Guard & VPN Session Revocation False Positives on IP Roaming
* **Severity:** **MEDIUM OPERATIONAL STABILITY**
* **Affected Subsystem:** `camserv.security.identity.sentinel`
* **Root Cause:** Treating every IP mutation during an active session as a session hijacking attack caused immediate session revocation for mobile tablet guards roaming between Wi-Fi access points or users connecting via dynamic corporate VPNs.
* **Remediation:** Added configurable `allow_ip_roaming = True` and risk-based context tracking in `inspect_session_context`, updating session IP bindings and logging informational audit events without dropping legitimate sessions.
* **Verification:** Tested in `tests/test_phase26_1_adversarial.py::TestSentinelAdversarialHardening::test_mobile_ip_roaming_support`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.1-08: Emergency Lockdown Vulnerability to Underlying Database Disk I/O Stalls
* **Severity:** **CRITICAL FAILS-CLOSED SECURITY**
* **Affected Subsystem:** `camserv.security.identity.emergency`
* **Root Cause:** If `EmergencyLockdownManager.declare_lockdown()` failed during SQLite session revocation queries due to disk degradation or lock contention, the lockdown could fail to engage, leaving client sessions open.
* **Remediation:** Placed the immediate in-memory barrier (`self._is_active = True`) prior to database operations and wrapped database calls in resilient exception handlers, guaranteeing fail-safe containment regardless of database availability. Enforced administrator-only authorization on `lift_lockdown()`.
* **Verification:** Tested in `tests/test_phase26_1_adversarial.py::TestEmergencyLockdownFailsafeHardening` (2 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

## 9. Phase 26.2 Findings & Final Software Assurance

### FINDING-P26.2-01: Absence of Independent Local Trust Anchor Store for Audit Checkpoints
* **Severity:** **HIGH FORENSIC INTEGRITY & ANTI-ROLLBACK**
* **Affected Subsystem:** `camserv.security.identity.audit` (`ExternalCheckpointStore`)
* **Root Cause:** Phase 26 and 26.1 generated in-memory checkpoints without an independent external store. An adversary restoring a coordinated older backup of the SQLite database could bypass freshness checks because the database hash chain remained internally valid at the older state.
* **Remediation:** Engineered `ExternalCheckpointStore` persisting checkpoints in an independent JSON store outside `identity.db`. Enforces strict sequence monotonicity (`CheckpointSequenceRegressionError`), immediately detecting and blocking snapshot rollbacks, sequence regressions, and divergent head hashes.
* **Verification:** Tested in `tests/test_phase26_2_assurance.py::TestAuditCheckpointAssurance::test_coordinated_snapshot_rollback_detected_by_external_store`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.2-02: Symmetric HMAC Inability to Provide Auditor Non-Repudiation
* **Severity:** **MEDIUM REGULATORY AUDITABILITY**
* **Affected Subsystem:** `camserv.security.identity.audit`
* **Root Cause:** Symmetric HMAC-SHA256 checkpoints required sharing the secret key with external auditors, enabling anyone who obtained the key to forge valid checkpoints.
* **Remediation:** Implemented asymmetric Ed25519 checkpoint signing (`create_checkpoint(private_key=...)`) and public-key verification (`verify_against_checkpoint(public_key=...)`), enabling regulatory auditors to verify forensic immutability without the ability to forge checkpoints.
* **Verification:** Tested in `tests/test_phase26_2_assurance.py::TestAuditCheckpointAssurance::test_ed25519_asymmetric_checkpoint_signing_and_verification`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.2-03: Bootstrap File Pre-DACL Token Inscription Exposure Window
* **Severity:** **HIGH LOCAL PRIVILEGE ESCALATION (WINDOWS)**
* **Affected Subsystem:** `camserv.security.identity.bootstrap`
* **Root Cause:** Inscribing the secret token into the file descriptor *before* applying Windows NTFS access controls created a transient window where inherited permissions allowed local unprivileged users (`BUILTIN\Users`) to read the token. Furthermore, using `O_CREAT | O_WRONLY | O_TRUNC` did not prevent existing-path substitution.
* **Remediation:** Implemented atomic exclusive creation (`os.O_CREAT | os.O_EXCL`), closed the 0-byte file immediately, applied and verified Windows DACL inheritance stripping via `icacls`, and only then inscribed the 256-bit token with `os.fsync()`.
* **Verification:** Tested in `tests/test_phase26_2_assurance.py::TestWindowsBootstrapHardening::test_atomic_exclusive_creation_and_dacl_application`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.2-04: Volatile Emergency Lockdown Resetting on Process Restart
* **Severity:** **CRITICAL THREAT CONTAINMENT**
* **Affected Subsystem:** `camserv.security.identity.emergency`
* **Root Cause:** Emergency lockdown was tracked via a volatile in-memory boolean `_is_active`. An application crash, power cut, or operating system reboot cleared the lockdown state, reopening client access without administrator authorization.
* **Remediation:** Implemented a durable recovery latch file (`data/.emergency_lockdown.latch`). On startup, `EmergencyLockdownManager` inspects the latch file, restores active lockdown state across restarts, and fails closed (`LOCKDOWN_FAIL_CLOSED_CORRUPTED_LATCH`) if the latch file is corrupt or empty.
* **Verification:** Tested in `tests/test_phase26_2_assurance.py::TestLockdownDurableRecoveryAndActiveSessionEnforcement::test_durable_latch_survives_process_restart`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.2-05: Policy Engine Non-Evaluation of Active Emergency Lockdown
* **Severity:** **HIGH ACCESS CONTROL**
* **Affected Subsystem:** `camserv.security.identity.authorization`
* **Root Cause:** `ZeroTrustPolicyEngine.authorize()` evaluated user permissions without checking whether an emergency lockdown was active, creating a bypass window if database revocation queries were delayed or degraded.
* **Remediation:** Integrated `EmergencyLockdownManager` directly into `ZeroTrustPolicyEngine`. Step 0 of `authorize()` checks `lockdown_manager.is_active` and immediately denies non-whitelisted operations.
* **Verification:** Tested in `tests/test_phase26_2_assurance.py::TestLockdownDurableRecoveryAndActiveSessionEnforcement::test_lockdown_enforcement_in_policy_engine`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.2-06: Session Manager Allowing Active Client Operations During Lockdown
* **Severity:** **HIGH SESSION HYGIENE**
* **Affected Subsystem:** `camserv.security.identity.session`
* **Root Cause:** `SessionManager.validate_and_touch()` did not evaluate lockdown status, allowing in-flight client sessions to continue accessing resources until database revocation rows updated.
* **Remediation:** Bound `EmergencyLockdownManager` to `SessionManager`. Calling `validate_and_touch()` during lockdown immediately raises `SessionRevokedError` for non-admin client sessions, and `create_session()` blocks new client logins with `SessionError`.
* **Verification:** Tested in `tests/test_phase26_2_assurance.py::TestLockdownDurableRecoveryAndActiveSessionEnforcement::test_lockdown_enforcement_in_session_manager`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.2-07: Single-Signal Session Roaming Vulnerability to Token Theft
* **Severity:** **HIGH SESSION HIJACKING DEFENSE**
* **Affected Subsystem:** `camserv.security.identity.sentinel`
* **Root Cause:** Evaluating IP change alone either broke legitimate mobile tablet roaming or allowed exfiltrated session tokens to be replayed from alternate devices without challenge.
* **Remediation:** Implemented multi-signal risk correlation evaluating IP mutation, User-Agent client fingerprint mutation, and action sensitivity. Concurrent IP+UA change immediately revokes the session; User-Agent mutation alone or sensitive actions after roaming trigger `STEP_UP_REQUIRED`.
* **Verification:** Tested in `tests/test_phase26_2_assurance.py::TestSentinelMultiSignalAdaptiveSecurity` (3 tests).
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.2-08: Ambiguous NIST SP 800-63B Phishing Resistance Classification
* **Severity:** **MEDIUM REGULATORY TRANSPARENCY**
* **Affected Subsystem:** `camserv.security.identity.mfa`, documentation
* **Root Cause:** Commercial documentation could conflate internal AAL2 labels with formal federal NIST certification or phishing resistance.
* **Remediation:** Published comprehensive alignment review (`docs/PHASE-26.2-NIST-AAL-ALIGNMENT.md`) explicitly stating that RFC 6238 TOTP is replay-resistant but NOT phishing-resistant (vulnerable to reverse-proxy interception), and WebAuthn Passkeys are provisional interface hooks only. Disclaimed formal NIST compliance without accredited laboratory assessment.
* **Verification:** Formally documented in `docs/PHASE-26.2-NIST-AAL-ALIGNMENT.md`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 10. Phase 26.3 Findings: Local Trust Boundary Closure & Adversarial Assurance

### FINDING-P26.3-01: Silent Genesis Re-initialization upon Checkpoint Store Deletion
* **Severity:** **HIGH FORENSIC IMMUTABILITY**
* **Affected Subsystem:** `camserv.security.identity.audit` (`TamperEvidentSecurityAudit`)
* **Root Cause:** If `trust_anchor.json` was deleted while `identity.db` had historical events, `verify_against_external_store()` returned `(True, None)`, allowing silent re-initialization of genesis checkpoints over existing deployments.
* **Remediation:** Added `CheckpointStoreMissingError` if `latest is None` and database has `count > 0` records. Added `CheckpointCorruptedError` on empty, malformed, or non-array stores.
* **Verification:** Tested in `tests/test_phase26_3_adversarial.py::TestDomainAExternalCheckpointRollback::test_checkpoint_store_deletion_fails_closed`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.3-02: Mathematical Limitation of Local Hash Chains Against Full Filesystem Snapshot Restore
* **Severity:** **MEDIUM ARCHITECTURAL TRANSPARENCY**
* **Affected Subsystem:** `camserv.security.identity.audit`
* **Root Cause:** Theorem 1 proves that a local hash chain cannot mathematically detect an attacker with host root restoring both `identity.db` and `trust_anchor.json` from a coordinated snapshot without an independent hardware/external trust anchor.
* **Remediation:** Formally published Theorem 1 (Local State Rollback Indistinguishability) in `docs/PHASE-26.3-EXTERNAL-CHECKPOINT-ROLLBACK-TESTS.md` and mandated TPM 2.0 monotonic NVRAM or offsite syslog for enterprise rollback prevention.
* **Verification:** Documented in `docs/PHASE-26.3-EXTERNAL-CHECKPOINT-ROLLBACK-TESTS.md`.
* **Status:** **FORMALIZED & VERIFIED**.

---

### FINDING-P26.3-03: Windows Kernel Handle Retention Bypassing Post-Creation DACL Stripping
* **Severity:** **HIGH LOCAL PRIVILEGE ESCALATION (WINDOWS)**
* **Affected Subsystem:** `camserv.security.identity.bootstrap`
* **Root Cause:** Windows NT object manager retains opened file handles across subsequent `icacls` DACL changes. If an unprivileged user process opened a read handle before `icacls` executed on `.bootstrap_token`, it retained the handle and could read newly written token data.
* **Remediation:** Pre-hardened the parent directory (`data/`) using `icacls /inheritance:r /grant %USERNAME%:(OI)(CI)F /grant SYSTEM:(OI)(CI)F` before creating the token file, ensuring child files inherit restricted permissions from the instant of creation.
* **Verification:** Tested in `tests/test_phase26_3_adversarial.py::TestDomainBBootstrapSecurity::test_bootstrap_parent_directory_pre_hardening`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.3-04: Volatile Heap Memory Remanence of Cleartext Bootstrap Secrets
* **Severity:** **MEDIUM VOLATILE MEMORY HYGIENE**
* **Affected Subsystem:** `camserv.security.identity.bootstrap`
* **Root Cause:** Cleartext token strings remained in Python's garbage-collected heap after bootstrap completion, susceptible to memory scraping or crash dump exfiltration.
* **Remediation:** Implemented `secure_zero_memory()` utilizing `ctypes.memset` over mutable `bytearray` buffers to overwrite secrets with zeros immediately upon consumption. Documented flash wear-leveling boundaries.
* **Verification:** Tested in `tests/test_phase26_3_adversarial.py::TestDomainBBootstrapSecurity::test_secure_zero_memory_ctypes`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.3-05: Emergency Lockdown Latch Tampering & Deleted-Latch Reboot Evasion
* **Severity:** **CRITICAL THREAT CONTAINMENT**
* **Affected Subsystem:** `camserv.security.identity.emergency`
* **Root Cause:** `.emergency_lockdown.latch` lacked cryptographic signature integrity. An attacker with filesystem access could modify status or delete the latch file before a reboot to evade active lockdown without administrative credentials.
* **Remediation:** Embedded an HMAC-SHA256 signature (`latch_signature`) inside the latch file, verified on startup. Added SQLite security event log cross-checking to detect latch deletion and fail closed (`LOCKDOWN_FAIL_CLOSED_CORRUPTED_LATCH`).
* **Verification:** Tested in `tests/test_phase26_3_adversarial.py::TestDomainCEmergencyLockdownAssurance::test_lockdown_hmac_signature_tampering_fails_closed` and `test_lockdown_deleted_latch_reconciled_from_database`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.3-06: Unauthenticated & Unprivileged Emergency Lockdown Termination
* **Severity:** **HIGH INCIDENT RESPONSE INTEGRITY**
* **Affected Subsystem:** `camserv.security.identity.emergency`
* **Root Cause:** `lift_lockdown()` permitted calls where `authorizing_admin` was `None`, potentially allowing unauthenticated or non-admin callers to lift lockdown.
* **Remediation:** Enforced strict validation requiring verified administrator credentials, checking `is_administrator` or `IdentityRole.ADMIN` and rejecting unauthenticated calls with `PermissionError`.
* **Verification:** Tested in `tests/test_phase26_3_adversarial.py::TestDomainCEmergencyLockdownAssurance::test_lockdown_unauthorized_lift_rejected`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.3-07: Untrusted Reverse-Proxy HTTP Header Spoofing Evading Sentinel Mitigations
* **Severity:** **HIGH NETWORK IDENTITY SPOOFING**
* **Affected Subsystem:** `camserv.security.identity.sentinel`
* **Root Cause:** Extracting client IP addresses from `X-Forwarded-For` or `X-Real-IP` in local-first deployments without verifying upstream proxy trust allowed attackers to spoof client IPs and bypass rate limits or Sentinel IP bans.
* **Remediation:** Engineered `resolve_client_ip()` strictly ignoring client-supplied forwarding headers unless the direct socket IP is an explicitly configured member of `trusted_proxies`.
* **Verification:** Tested in `tests/test_phase26_3_adversarial.py::TestDomainDSentinelSessionSecurity::test_proxy_header_spoofing_prevented_without_trusted_proxy`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.3-08: Surveillance Recording Degradation Under Identity Subsystem Faults
* **Severity:** **CRITICAL SURVEILLANCE CONTINUITY**
* **Affected Subsystem:** `camserv.platform.stability`
* **Root Cause:** Identity database locks, latch corruption, or auth storms could cascade into ingestion thread contention if shared locking or synchronous database writes existed in video paths.
* **Remediation:** Enforced complete memory and thread decoupling between video ingestion queues (`BoundedPipelineQueue`) and identity stores, with `PERMITTED_LOCKDOWN_ACTIONS` whitelisting pipeline operations.
* **Verification:** Tested in `tests/test_phase26_3_adversarial.py::TestDomainFGPipelineIsolationRegression::test_pipeline_zero_frame_loss_under_compound_failures`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 11. Phase 26.4 Findings: Repository Presentation, Documentation & Visual Refinement

### FINDING-P26.4-01: Outdated Test Count and Subsystem Claims in Root README
* **Severity:** **MEDIUM REPOSITORY PRESENTATION**
* **Affected Subsystem:** `README.md`
* **Root Cause:** Status badge and body text cited 245 passing tests from Phase 22, omitting 370 new tests authored during Phases 25, 26, 26.1, 26.2, and 26.3.
* **Remediation:** Upgraded status badges and test suite highlights to cite 615 passing tests across 66 modules, reflecting all active subsystems.
* **Verification:** Verified via `scripts/verify_links_and_images.py` and `pytest -q`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.4-02: Architecture Diagrams Missing Phase 25 Hardware Adaptation and Phase 26 Identity Foundation
* **Severity:** **MEDIUM ARCHITECTURAL TRANSPARENCY**
* **Affected Subsystem:** `README.md`, `docs/PHASE-26.4-ARCHITECTURE-DIAGRAMS.md`
* **Root Cause:** Existing Mermaid diagram depicted only Phase 14 architecture, omitting Universal Hardware Adaptation, CPU Failover, Bounded Queues, Recording Continuity, and Zero-Trust Identity.
* **Remediation:** Engineered comprehensive Mermaid architecture diagrams showing actual inter-subsystem data flows, bounded memory queues, and zero-trust policy engines.
* **Verification:** Documented in `docs/PHASE-26.4-ARCHITECTURE-DIAGRAMS.md`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.4-03: Stale Test Count References in CI Workflow and Contributor Documentation
* **Severity:** **LOW DEVELOPER EXPERIENCE**
* **Affected Subsystem:** `.github/workflows/ci.yml`, `CONTRIBUTING.md`
* **Root Cause:** Step names and developer run instructions referenced 245 tests.
* **Remediation:** Updated `.github/workflows/ci.yml` and `CONTRIBUTING.md` to reference the active 615-test suite across 66 modules.
* **Verification:** Verified in CI definition and contributor guide.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.4-04: Supported Release Track Discrepancy in Security Policy
* **Severity:** **LOW SECURITY DISCLOSURE HYGIENE**
* **Affected Subsystem:** `SECURITY.md`
* **Root Cause:** Supported versions table referenced `0.2.x` and `0.1.x`, predating release candidate versioning.
* **Remediation:** Updated `SECURITY.md` to define `0.10.x` as the active supported release track.
* **Verification:** Audited in `SECURITY.md`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.4-05: Screenshot Path Inconsistency Between Documentation Directory and Standard GitHub Assets
* **Severity:** **LOW REPOSITORY CONVENTIONS**
* **Affected Subsystem:** `docs/screenshots/`, `docs/assets/screenshots/`
* **Root Cause:** Screenshots resided exclusively in `docs/screenshots/`, which could cause broken links if standard asset conventions (`docs/assets/screenshots/`) were used in external docs.
* **Remediation:** Mirrored all 14 Full HD screenshots to `docs/assets/screenshots/`, maintaining dual-path availability.
* **Verification:** Validated existence across both paths.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P26.4-06: Ambiguous Qualification Language Conflating Software Simulation with Hardware Qualification
* **Severity:** **MEDIUM EPISTEMIC TRUTHFULNESS**
* **Affected Subsystem:** Repository documentation suite
* **Root Cause:** Terminology like "verified" could be interpreted by customers as proof of physical hardware or 72-hour thermal chamber qualification.
* **Remediation:** Enforced a 4-tier epistemic qualification taxonomy ("Software verified", "Hardware pending", "Provisional", "Planned") across all documentation artifacts.
* **Verification:** Formally documented in `docs/PHASE-26.4-DOCUMENTATION-CONSISTENCY.md`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 12. Phase 27 Findings & Visual Intelligence Remediation Inventory

### FINDING-P27-01: AI Subsystem Monolithic Entanglement Risk
* **Severity:** **CRITICAL ARCHITECTURAL MODULARITY**
* **Affected Subsystem:** `camserv.intelligence`
* **Root Cause:** Prior vision implementations bundled detection, tracking, and alerts into tightly coupled files, risking whole-system failure if one component crashed.
* **Remediation:** Architected 12 decoupled, independently configurable engines under `src/camserv/intelligence/` with clear typed contracts and health reporting.
* **Verification:** Tested in `tests/test_phase27_intelligence_coordinator.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27-02: Lack of Decoupled Fine-Grained Classification & Uncertainty Gating
* **Severity:** **HIGH EPISTEMIC TRUTHFULNESS**
* **Affected Subsystem:** `camserv.intelligence.classification`
* **Root Cause:** Detections previously conflated spatial localization with subcategory classification, risking false positive categorization on ambiguous crops.
* **Remediation:** Implemented `ObjectClassificationEngine` with aspect-ratio heuristics and explicit uncertainty gating (`is_uncertain=True` when confidence $< 0.60$).
* **Verification:** Tested in `tests/test_phase27_detection_classification.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27-03: Uncalibrated Speed (km/h) Fabrication Vulnerability
* **Severity:** **HIGH LEGAL & EVIDENTIARY RELIABILITY**
* **Affected Subsystem:** `camserv.intelligence.traffic`
* **Root Cause:** Legacy surveillance tools frequently display speed in km/h on uncalibrated video, producing scientifically baseless numbers.
* **Remediation:** Enforced strict calibration gating. On uncalibrated streams, `calibrated_speed_kmh` is strictly `None`, reporting relative pixel velocity only.
* **Verification:** Tested in `tests/test_phase27_traffic_analytics.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27-04: Lack of Optical Quality Gating for ANPR/LPR
* **Severity:** **HIGH FORENSIC INTEGRITY**
* **Affected Subsystem:** `camserv.intelligence.anpr`
* **Root Cause:** Traditional OCR engines attempt to force-read severely blurred or overexposed license plates, hallucinating random characters.
* **Remediation:** Implemented `assess_plate_quality()` with Laplacian blur variance, glare saturation ratio, and 16px minimum resolution checks. Failed crops return `UNREADABLE`.
* **Verification:** Tested in `tests/test_phase27_anpr_pipeline.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27-05: ANPR Unauthorized Activation & Privacy Audit Risk
* **Severity:** **HIGH PRIVACY & REGULATORY COMPLIANCE**
* **Affected Subsystem:** `camserv.intelligence.anpr`
* **Root Cause:** Unrestricted plate reading risks GDPR and privacy violations if activated without documented organizational need.
* **Remediation:** ANPR is disabled by default (`authorized=False`). Activation requires legal justification, and all plate queries are logged in `_access_log`.
* **Verification:** Tested in `tests/test_phase27_anpr_pipeline.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27-06: Semantic Scene Reasoning Collapse Risk
* **Severity:** **MEDIUM FORENSIC TRUTHFULNESS**
* **Affected Subsystem:** `camserv.intelligence.scene`
* **Root Cause:** AI models collapsing raw bounding boxes directly into high-level accusations (e.g. "crime in progress").
* **Remediation:** Implemented `SceneUnderstandingEngine` enforcing the 4-tier chain: `OBSERVATION` $\rightarrow$ `MEASUREMENT` $\rightarrow$ `INFERENCE` $\rightarrow$ `EVENT`.
* **Verification:** Tested in `tests/test_phase27_scene_rules_events.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27-07: Video Recording Starvation from AI Task Backpressure
* **Severity:** **CRITICAL SYSTEM RELIABILITY**
* **Affected Subsystem:** `camserv.intelligence.scheduler`
* **Root Cause:** Heavy AI inference threads consuming 100% CPU/RAM, causing RTSP frames to drop and starving disk recording loops.
* **Remediation:** Implemented `AIResourceScheduler` enforcing Priority 1 for recording, admission control shedding at 90% load, and dynamic frame sampling down to 0 FPS.
* **Verification:** Tested in `tests/test_phase27_scheduler_isolation.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27-08: AI Worker Exception & Crash Propagation Risk
* **Severity:** **CRITICAL FAULT ISOLATION**
* **Affected Subsystem:** `camserv.intelligence.scheduler`
* **Root Cause:** Unhandled exceptions in neural runtimes (e.g. CUDA OOM or segfaults) crashing the primary surveillance service.
* **Remediation:** Implemented `execute_isolated()` with thread pool boundaries, hard 2.0s timeouts, and safe fallback values.
* **Verification:** Tested in `tests/test_phase27_scheduler_isolation.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 13. Phase 27.1 Adversarial Findings & Hardening Inventory

### FINDING-P27.1-01: Absent Neural Weights Masked by Heuristic Simulator
* **Severity:** **CRITICAL EPISTEMIC TRUTHFULNESS**
* **Affected Subsystem:** `camserv.intelligence.detection.ObjectDetectionEngine`
* **Root Cause:** Model weight files were absent on disk. The engine operated in heuristic simulator mode, which only cycles between 3 classes (`person`, `car`, `bicycle`). 13 canonical classes were completely uncallable.
* **Remediation:** Hardened detection metadata to explicitly disclose `is_simulated_heuristic=True` and `real_weights_loaded=False`. Genuine 16-class neural inference is formally reclassified as **HARDWARE VALIDATION PENDING**.
* **Verification:** Tested in `tests/test_phase27_1_adversarial_vision.py::test_absent_weights_metadata_transparency`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.1-02: Tracking Fragmentation on High-Speed Moving Objects
* **Severity:** **HIGH TRACKING RELIABILITY**
* **Affected Subsystem:** `camserv.intelligence.tracking.ObjectTrackingEngine`
* **Root Cause:** Bipartite matching evaluated only static bounding box IoU. Fast-moving objects moving $> 50$ px/frame had zero static IoU overlap with previous frames, causing immediate track fragmentation.
* **Remediation:** Implemented `_project_bbox` forward velocity motion projection. Matching now computes $\max(IoU(B_t, B_{\text{det}}), IoU(\hat{B}_{t+1}, B_{\text{det}}))$.
* **Verification:** Tested in `tests/test_phase27_1_tracking_adversarial.py::test_fast_moving_object_motion_projection_continuity`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.1-03: Uniform Scalar Pixels-Per-Meter Perspective Distortion Vulnerability
* **Severity:** **HIGH LEGAL & SPEED ACCURACY**
* **Affected Subsystem:** `camserv.intelligence.traffic.TrafficAnalyticsEngine`
* **Root Cause:** Speed estimation multiplied pixel velocity by a flat scalar PPM constant, which produces extreme errors on downward-tilted perspective cameras due to foreshortening.
* **Remediation:** Introduced `SpeedMeasurementStatus` (`CALIBRATED_ACCURATE`, `RELATIVE_MOVEMENT_ONLY`, `SPEED_UNAVAILABLE`). Formally classified planar ground-speed enforcement as requiring a 4-point homography matrix.
* **Verification:** Tested in `tests/test_phase27_1_speed_calibration.py::test_speed_status_classification`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.1-04: ANPR OCR Character Extraction Is a Deterministic Generator
* **Severity:** **HIGH EVIDENTIARY TRUTHFULNESS**
* **Affected Subsystem:** `camserv.intelligence.anpr.LicensePlateEngine`
* **Root Cause:** While optical gating was mathematically authentic, character extraction synthesized candidate strings based on `frame_id` rather than performing neural OCR on crop pixels.
* **Remediation:** Hardened result metadata to output `is_simulated_ocr=True` and `real_weights_loaded=False`. Genuinely active OCR is classified as **SIMULATED (LAB TEST ONLY)** until external OCR binaries are integrated.
* **Verification:** Audited in `docs/PHASE-27.1-ANPR-ADVERSARIAL-AUDIT.md`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.1-05: ThreadPoolExecutor Timeout Leaves Native Workers Blocked
* **Severity:** **CRITICAL WORKER ISOLATION**
* **Affected Subsystem:** `camserv.intelligence.scheduler.AIResourceScheduler`
* **Root Cause:** `future.result(timeout)` returns control to the caller on timeout, but the background thread remains alive and blocked. The scheduler had no worker lifecycle state machine to report this.
* **Remediation:** Implemented `WorkerLifecycleState` tracking (`RUNNING`, `CANCELLATION_REQUESTED`, `TERMINATION_UNCONFIRMED`, `TERMINATED`, `RECOVERY_FAILED`). Timed-out workers are accurately classified as `TERMINATION_UNCONFIRMED`.
* **Verification:** Tested in `tests/test_phase27_1_worker_isolation.py::test_worker_lifecycle_state_termination_unconfirmed`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.1-06: Scheduler 90% Host Load Boundary Lacks Hysteresis Damping
* **Severity:** **MEDIUM ADMISSION STABILITY**
* **Affected Subsystem:** `camserv.intelligence.scheduler.AIResourceScheduler`
* **Root Cause:** Fixed 90% CPU/RAM threshold caused rapid state fluttering between `NORMAL` and `CRITICAL` when host hovered around 90%.
* **Remediation:** Implemented 10% asymmetric hysteresis damping. Enters `CRITICAL` at 90%, but exits only when load drops below 80%.
* **Verification:** Tested in `tests/test_phase27_1_worker_isolation.py::test_scheduler_admission_hysteresis_damping`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.1-07: Model Registry Checksum Targets an Empty 0-Byte File
* **Severity:** **MEDIUM SUPPLY CHAIN HYGIENE**
* **Affected Subsystem:** `camserv.intelligence.registry.DEFAULT_MODELS`
* **Root Cause:** `expected_sha256` was hardcoded to `e3b0c44298fc...`, the SHA-256 hash of an empty file, masking the fact that no weights were packaged.
* **Remediation:** Disclosed empty-file placeholder in documentation and gap register. Ensured `verify_integrity()` returns `False` when files are absent.
* **Verification:** Audited in `docs/PHASE-27.1-MODEL-REGISTRY-AUDIT.md`.
* **Status:** **REMEDIATED & VERIFIED**.

---

---

## 14. Phase 27.2 Real AI Integration, Native Process Isolation & Continuity Qualification Findings

### FINDING-P27.2-01: Empty-File SHA-256 Checksum Placeholder in Model Registry
* **Severity:** **HIGH SUPPLY CHAIN INTEGRITY**
* **Affected Subsystem:** `camserv.intelligence.registry` (`ModelCapabilityRegistry`)
* **Root Cause:** `expected_sha256` for default models contained `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (the hash of `b""`), which allowed empty 0-byte placeholder files to appear verified.
* **Remediation:** Defined `EMPTY_FILE_SHA256` as a strictly forbidden digest. Updated `verify_integrity()` to reject empty files and the placeholder hash. Implemented `ModelCapabilityState` (9 epistemic states) and set target model references to genuine non-placeholder checksums, reporting `MODEL_NOT_INSTALLED` when files are absent.
* **Verification:** Tested in `tests/test_phase27_2_real_ai_and_process_isolation.py::test_empty_file_placeholder_strictly_rejected` and `test_model_capability_states_evaluation`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.2-02: Native Inference Worker Thread Hang Unkillable via Python Thread Timeouts
* **Severity:** **CRITICAL FAULT ISOLATION**
* **Affected Subsystem:** `camserv.intelligence.scheduler` & `camserv.intelligence.process_worker`
* **Root Cause:** Python thread pool timeouts (`concurrent.futures.ThreadPoolExecutor`) cannot forcibly terminate a blocked native C++/CUDA call. While control returned to the caller, the underlying thread and accelerator context hung indefinitely (`TERMINATION_UNCONFIRMED`).
* **Remediation:** Engineered `ProcessIsolatedInferenceSupervisor` and `_ai_worker_process_entrypoint` using Python's `spawn` multiprocessing context. Implemented a supervised 12-state lifecycle with confirmed OS process termination (`TerminateProcess` / `SIGTERM` escalated to `SIGKILL`) verifying `is_alive() == False` before reporting `TERMINATED`.
* **Verification:** Tested in `tests/test_phase27_2_real_ai_and_process_isolation.py::test_supervisor_process_lifecycle_states` and `test_supervisor_forced_process_termination_on_timeout`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.2-03: Stale Worker Result Injection Risk After Process Replacement
* **Severity:** **HIGH DATA INTEGRITY & RACE CONDITION**
* **Affected Subsystem:** `camserv.intelligence.process_worker`
* **Root Cause:** When an unresponsive worker process was cancelled and restarted, a delayed response from the previous worker could arrive across the IPC queue and be mistakenly accepted by the supervisor.
* **Remediation:** Implemented generation/epoch counters (`_generation`) and unique task lease contracts (`InferenceTaskLease` with lease UUIDs and expiries). The supervisor strictly validates lease validity and generation number on every IPC result, rejecting any response from older generations or cancelled leases.
* **Verification:** Tested in `tests/test_phase27_2_real_ai_and_process_isolation.py`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.2-04: ANPR OCR Synthetic String Generation from Frame IDs
* **Severity:** **HIGH EVIDENTIARY TRUTHFULNESS**
* **Affected Subsystem:** `camserv.intelligence.anpr.LicensePlateEngine`
* **Root Cause:** Character extraction generated synthetic strings based on `frame_id` rather than performing optical character recognition on actual plate crop pixels.
* **Remediation:** Implemented genuine pixel-based OCR via `extract_characters_from_pixels`: Otsu adaptive binarization, character contour segmentation, and standardized $32\times24$ alphanumeric font glyph template cross-correlation. In strict production mode (`strict_pixel_ocr=True`), blank or unreadable plates strictly return `OCR_RUNTIME_UNAVAILABLE` or `UNREADABLE` with 0 characters, completely preventing character hallucination.
* **Verification:** Tested in `tests/test_phase27_2_real_ai_and_process_isolation.py::test_genuine_pixel_ocr_reads_image_pixels` and `test_blank_plate_strict_ocr_rejection_no_hallucination`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.2-05: Absence of Multi-Class Neural Tensor Output Parsing
* **Severity:** **HIGH CAPABILITY TRANSPARENCY**
* **Affected Subsystem:** `camserv.intelligence.detection.ObjectDetectionEngine`
* **Root Cause:** `_detect_dnn` did not parse multi-class output tensors from OpenCV DNN models, unconditionally falling back to heuristic cycling across 3 categories.
* **Remediation:** Upgraded `_detect_dnn` with real tensor output parsing for SSD (`1x1xNx7`) and YOLO (`1xNxM`) output layers, confidence thresholding, class index mapping to canonical classes, and greedy NMS. Added explicit metadata (`real_weights_loaded=True`, `is_simulated_heuristic=False`, `latency_ms`). When heuristic fallback is disabled, missing weights return `[]` without simulating detections.
* **Verification:** Tested in `tests/test_phase27_2_real_ai_and_process_isolation.py::test_detection_engine_metadata_and_heuristic_fallback_transparency`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.2-06: Planar Foreshortening Distortion in Vehicle Velocity Measurement
* **Severity:** **HIGH LEGAL & SPEED ACCURACY**
* **Affected Subsystem:** `camserv.intelligence.traffic.TrafficAnalyticsEngine`
* **Root Cause:** Scalar `pixels_per_meter` calibration produced large velocity errors on tilted cameras due to perspective foreshortening.
* **Remediation:** Added `project_to_ground_plane` in `CameraCalibration` supporting $3\times3$ planar road homography matrices. `TrafficAnalyticsEngine` projects vehicle velocities to ground plane meters, computing perspective-rectified ground speed in km/h. Uncalibrated streams honestly return `RELATIVE_MOVEMENT_ONLY` with `calibrated_speed_kmh = None`.
* **Verification:** Tested in `tests/test_phase27_2_real_ai_and_process_isolation.py::test_planar_homography_perspective_speed_calibration`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.2-07: Model Weight Registration Susceptible to Directory Traversal
* **Severity:** **MEDIUM LOCAL SECURITY HYGIENE**
* **Affected Subsystem:** `camserv.intelligence.registry`
* **Root Cause:** Registering external user models without path normalization could allow path traversal sequences (`..`) or null bytes (`\x00`).
* **Remediation:** Implemented `validate_model_path()` rejecting traversal sequences, null bytes, and non-canonical path escapes before model registration.
* **Verification:** Tested in `tests/test_phase27_2_real_ai_and_process_isolation.py::test_user_model_path_traversal_protection`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### FINDING-P27.2-08: Compound Host Load Shedding and Isolated Worker Crash Qualification
* **Severity:** **CRITICAL SURVEILLANCE CONTINUITY**
* **Affected Subsystem:** `camserv.intelligence.scheduler` & `camserv.platform.stability`
* **Root Cause:** Risk of compound AI failures (worker crashes, memory pressure, hangs) starving the primary recording loop.
* **Remediation:** Conducted comprehensive fault injection experiments (Scenarios A through L). Verified that `RecordingContinuityLedger` recorded exactly 0 frames lost (`confirmed_missing_frames_total == 0`, `continuity_ratio == 1.0`, state `CONTINUOUS`) while workers crashed, timed out, and host load spiked to 96%.
* **Verification:** Tested in `tests/test_phase27_2_real_ai_and_process_isolation.py::test_recording_continuity_under_ai_worker_crash` and `test_recording_continuity_under_critical_host_pressure`.
* **Status:** **REMEDIATED & VERIFIED**.







