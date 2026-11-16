# Phase 16: Defect Remediation & Technical Debt Report

**Target Release:** 0.10.0-alpha2  
**Reporting Period:** Phase 16 Engineering  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Executive Summary

During Phase 16 engineering, several Windows-specific technical issues, API discrepancies, and test assertions were identified and successfully remediated. This report records each defect, its root cause, the remediation applied, and the verification status.

---

## 2. Remediated Defects & Improvements

### REM-16-01: Optical Camera Probe Stalling on MSMF
- **Symptom:** On certain physical laptop webcams, calling `cv2.VideoCapture(0, cv2.CAP_MSMF)` fails to initialize if the privacy shutter is closed or if the OEM driver requires DirectShow negotiation.
- **Root Cause:** Single-backend probe assumed MSMF was universally compatible with all Windows optical webcams.
- **Remediation:** Refactored `WindowsMediaFoundationCameraBackend` to perform a dual-backend probe: try `cv2.CAP_MSMF` first; if uninitialized or fails `isOpened()`, automatically fallback to `cv2.CAP_DSHOW`.
- **Verification:** Successfully detected and captured 640x480 video frames from the host webcam via DirectShow fallback.

### REM-16-02: Interactive Invocation of SCM Service Dispatcher
- **Symptom:** Running `WindowsServiceRunner.run_scm_dispatcher()` directly from CLI or test suites resulted in Win32 error 1063 (`ERROR_FAILED_SERVICE_CONTROLLER_CONNECT`).
- **Root Cause:** Win32 `StartServiceCtrlDispatcherW` requires the calling process to be spawned by SCM inside Session 0.
- **Remediation:** Implemented error trap in `WindowsServiceRunner`: if `GetLastError() == 1063`, log informational diagnostic and automatically fall back to interactive console mode (`run_console()`).
- **Verification:** Verified in `test_windows_service_runner_interactive_fallback`.

### REM-16-03: Deprecation of `msilib` in Python 3.13+
- **Symptom:** Standard library `msilib` was removed in Python 3.13+, preventing Python 3.14 from generating Windows MSI packages using legacy Python scripts.
- **Root Cause:** Standard library modernization in CPython 3.13+.
- **Remediation:** Engineered `deploy/windows/build_msi.py` to directly interface with native Windows `msi.dll` via `ctypes.windll.msi`. Authoring standard SQL views and tables (`Property`, `Directory`, `Component`, `Feature`, `File`, `ServiceInstall`, `ServiceControl`).
- **Verification:** Successfully generated `camserv_0.10.0-alpha2_win64.msi` (24,576 bytes) and verified database schema.

### REM-16-04: Permanent Flag on Evidence Directories in MSI
- **Symptom:** Standard MSI uninstallation deletes all files and folders installed by the package, posing catastrophic risk to user recordings and judicial evidence vaults.
- **Root Cause:** Default component uninstall sequence removes installed components.
- **Remediation:** Set `msidbComponentAttributesPermanent` (`0x0010`) on `cmp_recordings`, `cmp_vault`, and `cmp_data`.
- **Verification:** Verified in `test_windows_msi_tables_and_service_schema` that permanent flags are set.

---

## 3. Residual Technical Debt & Future Milestones

- **Code Signing:** The generated MSI package is currently unsigned. A production certificate from a trusted CA (e.g. DigiCert / Sectigo) should be integrated into the CI/CD pipeline using `signtool.exe sign /fd SHA256`.
- **DirectML Acceleration Wheels:** Microsoft DirectML acceleration requires `onnxruntime-directml` which is not currently packaged by default on Python 3.14 (due to Python 3.14 prerelease status). Fallback to multi-threaded CPU is active and verified.
