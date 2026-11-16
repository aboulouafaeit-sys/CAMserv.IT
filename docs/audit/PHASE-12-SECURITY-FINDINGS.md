# CAMserv — Phase 12 Security Findings Register

**Document ID:** SEC-FINDINGS-P12-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Date:** November 16, 2026  
**Auditor:** Independent Application Security & Red-Team Specialist  

---

## 1. Executive Summary

During Phase 12 real-world hardware, camera compatibility, and edge AI validation, the independent audit team identified **5 security and integrity findings**:
- **0 CRITICAL** vulnerabilities
- **2 HIGH** severity findings
- **3 MEDIUM** severity findings
- **0 LOW / INFORMATIONAL** findings

All 5 findings were reproduced via automated unit tests, remediated in application source code, and verified via the Phase 12 regression test suite (`tests/test_audit_phase12_regressions.py`).

| Finding ID | Severity | CWE | CVSS v3.1 | Affected Component | Status |
| :--- | :---: | :---: | :---: | :--- | :---: |
| **SEC-P12-01** | **HIGH** | CWE-532 / CWE-312 | **7.5** | `camserv.acquisition.camera`, `camserv.api.routes`, `camserv.nvr.credentials` | **REMEDIATED & VERIFIED** |
| **SEC-P12-02** | **HIGH** | CWE-392 / CWE-254 | **7.2** | `camserv.acquisition.onvif.NVRCompatibilityTester` | **REMEDIATED & VERIFIED** |
| **SEC-P12-03** | **MEDIUM** | CWE-20 | **5.3** | `camserv.acquisition.camera._open_capture`, `supervisor.py` | **REMEDIATED & VERIFIED** |
| **SEC-P12-04** | **MEDIUM** | CWE-392 | **5.3** | `camserv.analytics.adapters.cuda.CUDABackendAdapter` | **REMEDIATED & VERIFIED** |
| **SEC-P12-05** | **MEDIUM** | CWE-392 | **4.3** | `camserv.platform.adaptive_manager.AdaptiveResourceManager` | **REMEDIATED & VERIFIED** |

---

## 2. Detailed Findings & Vulnerability Analysis

### SEC-P12-01: Plaintext RTSP Credentials Leakage in Acquisition Logs, Frame Metadata & API Responses
* **Severity:** **HIGH** (CWE-532: Insertion of Sensitive Information into Log File / CWE-312: Cleartext Storage of Sensitive Information / CVSS: 7.5 `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N`)
* **Affected Files & Lines:**
  - `src/camserv/nvr/credentials.py:65-98`
  - `src/camserv/acquisition/camera.py:102-108`, `152-160`
  - `src/camserv/api/routes.py:136-160`, `380-420`
* **Vulnerability Analysis:**
  When RTSP URLs containing embedded credentials (e.g. `rtsp://admin:P@ssword123@192.168.1.100:554/ch0`) were configured in `StreamConfig`, the unscrubbed string was stored directly. This resulted in:
  1. Plaintext passwords logged directly into structlog output (`source=rtsp://admin:P@ssword123@...`).
  2. Unmasked RTSP URLs attached to every `Frame.metadata["source"]` propagated through the privacy pipeline.
  3. API endpoints (`/api/v1/cameras`, `/api/v1/cameras/{id}`) returning unredacted RTSP URLs and raw password fields to callers.
* **Impact:** Any user with read-only API access or system log access could extract camera credentials, allowing unauthorized direct access to IP camera video streams and administrative interfaces on the local surveillance VLAN.
* **Remediation:**
  1. Implemented robust regex redaction `redact_url_credentials(url: str) -> str` using greedy userinfo matching `r'://([^/:]+):.*@([^/@]+)'` replacing passwords with `***`.
  2. Added `CameraCredential.to_safe_dict()` masking `password`, `onvif_password`, and `api_token` with `******`.
  3. Enforced URL credential scrubbing on logger binding and frame metadata in `CameraStream`.
  4. Enforced safe dictionary serialization across all camera API endpoints in `src/camserv/api/routes.py`.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_redact_url_credentials_comprehensive` and `test_camera_stream_redacts_credentials_in_logs_and_metadata`.

---

### SEC-P12-02: Unconditional False Success Reporting in `NVRCompatibilityTester`
* **Severity:** **HIGH** (CWE-392: Failure to Report Error Condition / CWE-254: 7.2 `CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N`)
* **Affected Files & Lines:**
  - `src/camserv/acquisition/onvif.py:270-285`
* **Vulnerability Analysis:**
  `NVRCompatibilityTester.test_camera_compatibility` contained logic that set `connection_successful = allow_simulation` when real network connection checks failed. It reported compatibility test success and logged `"NVR is fully compatible"` even when an IP camera was completely unreachable or refused connection.
* **Impact:** System installers and automated deployment pipelines were falsely led to believe that physical cameras were verified, operational, and streaming, causing silent deployment failures in live production installations.
* **Remediation:**
  1. Decoupled physical connection verification (`conn_ok`) from simulation fallback.
  2. Introduced explicit `validation_classification` ("VERIFIED_ON_REAL_CAMERA" when physically verified, "SIMULATED" when running under synthetic emulation, and "FAILED" when unreachable).
  3. Refactored output so `allow_simulation` does not report false positive hardware success.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_nvr_compatibility_tester_honest_reporting`.

---

### SEC-P12-03: Device Index Numeric String Parse Failure on Physical UVC/USB Webcams
* **Severity:** **MEDIUM** (CWE-20: Improper Input Validation / CVSS: 5.3 `CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L`)
* **Affected Files & Lines:**
  - `src/camserv/acquisition/camera.py:175-182`
  - `src/camserv/acquisition/supervisor.py:112-118`
* **Vulnerability Analysis:**
  On Windows with OpenCV DirectShow / MSMF backends, passing a string `"0"` to `cv2.VideoCapture("0")` causes OpenCV to interpret the parameter as a video file name rather than a hardware device index, returning `isOpened() == False`. Real USB webcams and laptop integrated sensors could not be ingested if `source_url` was specified as `"0"` or `"1"` via configuration or CLI.
* **Impact:** Denial of camera ingestion service when attempting to bind physical USB or built-in camera hardware using standard device index notation.
* **Remediation:**
  Added automatic numeric string detection: if `source_url.isdigit()`, the parameter is converted to `int(source_url)` before invocation of `cv2.VideoCapture`.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_camera_stream_device_index_parsing` and verified live with physical Integrated Camera index 0.

---

### SEC-P12-04: False CUDA Adapter Availability on Hosts with Physical GPU but Missing Python Runtime
* **Severity:** **MEDIUM** (CWE-392: Failure to Report Error Condition / CVSS: 5.3 `CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:N/I:L/A:N`)
* **Affected Files & Lines:**
  - `src/camserv/analytics/adapters/cuda.py:45-92`
* **Vulnerability Analysis:**
  `CUDABackendAdapter` checked `shutil.which("nvidia-smi")` and reported `is_available() = True` based purely on the presence of the NVIDIA driver utility, even when the current Python environment lacked CUDA execution libraries (`onnxruntime-gpu`, `torch.cuda`, `cupy`). In such environments, model loading failed with unhandled import errors during execution.
* **Impact:** False advertisement of hardware AI acceleration capabilities in enterprise deployments, causing unexpected runtime crashes during pipeline initialization.
* **Remediation:**
  1. Separated physical hardware presence detection (`is_device_detected()`) from execution runtime availability (`is_runtime_available()`).
  2. Enforced that `is_available()` returns `True` only when BOTH physical hardware AND working Python execution runtime are present.
  3. Added honest profile status: `"NVIDIA Hardware Present (No Python Runtime)"`, cleanly falling back to `onnx_cpu`.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_cuda_adapter_honest_reporting`.

---

### SEC-P12-05: Missing GPU and VRAM Telemetry in `AdaptiveResourceManager` Under Real Hardware Execution
* **Severity:** **MEDIUM** (CWE-392: Failure to Report Error Condition / CVSS: 4.3 `CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L`)
* **Affected Files & Lines:**
  - `src/camserv/platform/adaptive_manager.py:82-115`
* **Vulnerability Analysis:**
  `AdaptiveResourceManager` only polled psutil CPU and RAM metrics, leaving `gpu_percent`, `vram_used_mb`, and `vram_total_mb` hardcoded to zero or unpopulated. Consequently, adaptive workload throttling and tier degradation could not react to GPU thermal throttling or VRAM exhaustion.
* **Impact:** Inability of the platform to dynamically shed AI workloads or adjust stream resolutions when GPU memory approached saturation, leading to unhandled CUDA out-of-memory errors.
* **Remediation:**
  Integrated live telemetry sampling via `nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits`, dynamically populating real GPU and VRAM metrics into `ResourceSnapshot`.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_adaptive_resource_manager_metrics` on host RTX 3060 Laptop GPU.
