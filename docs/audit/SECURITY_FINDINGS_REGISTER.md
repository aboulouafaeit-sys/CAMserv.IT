# CAMserv — Independent Security Audit: Findings Register

**Document ID:** AUDIT-FINDINGS-POST-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Repository:** `aboulouafaeit-sys/CAMserv.IT`  
**Branch:** `main`  
**Audited Commit Baseline:** `227a3eb`  
**Audit Team:** Independent Security, Red-Team & Digital Forensics Review Board  
**Date:** November 16, 2026  

---

## 1. Executive Summary & Severity Breakdown

This register catalogs all security vulnerabilities, architectural weaknesses, reliability defects, and production-readiness gaps discovered across post-Phase 3, Phase 11, Phase 12, Phase 13, Phase 14, Phase 15, and Phase 16 audits. Findings were independently discovered through static code analysis, architectural threat modeling, hardware testing, and reproduced via deterministic automated test suites.

| Severity | Total Discovered | Resolved / Remediated | Unresolved / Limitations |
| :--- | :---: | :---: | :---: |
| **CRITICAL** | 5 | 5 | 0 |
| **HIGH** | 16 | 16 | 0 |
| **MEDIUM** | 9 | 9 | 0 |
| **LOW / INFORMATIONAL** | 3 | 3 | 0 |
| **HARDWARE / OPERATIONAL LIMITATION** | 4 | N/A (Documented) | 4 (Physical/Environment Gaps) |
| **TOTAL** | **37** | **33 Remediated** | **4 Operational Boundaries** |

---

## 2. Comprehensive Findings Register

### SEC-P3-01: Zip Slip / Arbitrary File Overwrite via Path Traversal in OTA Updater
* **Severity:** **CRITICAL** (CWE-22 / CVSS 9.3)
* **Affected Component:** `camserv.deploy.updater.SignedUpdateManager`
* **File & Lines:** `src/camserv/deploy/updater.py:233-238`
* **Root Cause:** In `apply_update_with_atomic_rollback`, payload files were extracted using `dest / rel_path` without checking if `rel_path` contained directory traversal sequences (`..`) or leading slashes. Furthermore, archive entries were extracted directly from `zf.namelist()` rather than restricting strictly to manifested and cryptographically verified entries.
* **Impact:** An attacker who compromised release signing credentials or exploited an archive could overwrite critical system files (`/etc/shadow`, `/etc/cron.d/`, systemd units) leading to complete appliance compromise.
* **Remediation:** Added path containment enforcement `out_path.resolve().relative_to(dest.resolve())`, path traversal validation on manifest entries, and strict rejection of unmanifested payload files.
* **Verification:** Tested in `tests/test_audit_vulnerabilities.py::test_sec_p3_01_zip_slip_rejection`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P3-02: Bypass of Dual-Control Quorum in Centralized Privacy Snapshot Export
* **Severity:** **CRITICAL** (CWE-285 / CVSS 9.1)
* **Affected Component:** `camserv.inference.privacy_pipeline.CentralizedPrivacyEnforcer`
* **File & Lines:** `src/camserv/inference/privacy_pipeline.py:347-355`
* **Root Cause:** The snapshot export function previously allowed any single caller with `user_role="FORENSIC_AUTHORITY"` or `"JUDICIAL_EXPORT"` to extract pristine unmasked raw video frames without requiring co-signer authorization or cryptographic dual-control verification.
* **Impact:** Direct violation of GDPR Article 25 (Data Protection by Design) and CAMserv Phase 3 Non-Negotiable Privacy Policy. A compromised or rogue operator could exfiltrate unmasked footage without administrative dual-control oversight.
* **Remediation:** Updated `process_snapshot_export` to mandate dual-control quorum co-signing (`co_signer_role` + `co_signer_id`) when `require_dual_control=True` or when using enterprise roles (`FORENSIC_INVESTIGATOR`), rejecting self-approval.
* **Verification:** Tested in `tests/test_audit_vulnerabilities.py::test_sec_p3_02_snapshot_export_requires_quorum`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P3-03: Path Traversal Vulnerability in Video Storage & Incident Vault Chunks
* **Severity:** **HIGH** (CWE-22 / CVSS 7.5)
* **Affected Component:** `camserv.storage.tiered_storage.TieredStorageManager` & `AdaptiveRetentionVault`
* **File & Lines:** `src/camserv/storage/tiered_storage.py:101`, `src/camserv/storage/adaptive_vault.py:158`
* **Root Cause:** Identifiers `camera_id`, `chunk_id`, and `event_id` were incorporated directly into filesystem paths without validating or sanitizing against traversal sequences (`..`, `/`, `\`).
* **Impact:** Untrusted camera stream metadata or forged event IDs could escape the designated storage directory and write or overwrite files outside the storage vault.
* **Remediation:** Implemented `_validate_safe_identifier` and destination directory containment checks (`chunk_path.relative_to(target_dir.resolve())`).
* **Verification:** Tested in `tests/test_audit_vulnerabilities.py::test_sec_p3_03_storage_chunk_path_traversal`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P3-04: Unauthenticated Denial-of-Service (DoS) via Sender ID Spoofing in Distributed Gateway
* **Severity:** **HIGH** (CWE-400 / CVSS 7.5)
* **Affected Component:** `camserv.central.comm.DistributedGateway`
* **File & Lines:** `src/camserv/central/comm.py:131-139`
* **Root Cause:** Rate-limit counters (`_check_rate_limit(envelope.sender_id, now)`) were evaluated and updated *before* the envelope's cryptographic signature was verified.
* **Impact:** An unauthenticated external attacker on the network could send spoofed packets claiming to originate from a legitimate appliance (`sender_id="device-victim"`), exhausting the victim's 120 msgs/min quota and locking out all genuine telemetry and alerts from the victim.
* **Remediation:** Re-ordered verification pipeline so that Ed25519 digital signature validation is executed *before* updating rate-limit counters or processing nonces.
* **Verification:** Tested in `tests/test_audit_vulnerabilities.py::test_sec_p3_04_unauthenticated_rate_limit_spoofing`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P3-05: Missing Site & Role Authorization in Device Suspension and Revocation (IDOR)
* **Severity:** **HIGH** (CWE-284 / CVSS 7.2)
* **Affected Component:** `camserv.central.registry.DeviceRegistry`
* **File & Lines:** `src/camserv/central/registry.py:225-249`
* **Root Cause:** Methods `suspend_device` and `revoke_device` accepted arbitrary `operator_id` strings without verifying whether the caller held administrative permissions or was authorized to administer the specific facility site where the device resided.
* **Impact:** An operator assigned to Site A could unilaterally suspend or permanently revoke critical edge cameras and appliances deployed at Site B.
* **Remediation:** Added `_verify_site_access` checks in `suspend_device` and `revoke_device` validating caller role and assigned site boundaries.
* **Verification:** Tested in `tests/test_audit_vulnerabilities.py::test_sec_p3_05_device_lifecycle_authorization`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P3-06: Credential and Token Leakage in Audit Trail via Nested Collections
* **Severity:** **MEDIUM** (CWE-532 / CVSS 5.3)
* **Affected Component:** `camserv.security.audit_trail.SecurityAuditLogger`
* **File & Lines:** `src/camserv/security/audit_trail.py:103-115`
* **Root Cause:** `sanitize_details` recursively sanitized dictionaries, but did not handle nested lists, tuples, or sets containing dictionaries with sensitive fields (`password`, `token`, `jwt`).
* **Impact:** Logging operations containing lists of user or session records could leak unredacted authentication tokens or credentials into persistent audit logs.
* **Remediation:** Added recursive sanitization for `isinstance(v, (list, tuple, set))`.
* **Verification:** Tested in `tests/test_audit_vulnerabilities.py::test_sec_p3_06_audit_logger_nested_redaction`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P3-07: Single-User Self-Approval Gap in Dual-Control Quorum Enforcement
* **Severity:** **MEDIUM** (CWE-285 / CVSS 5.1)
* **Affected Component:** `camserv.security.rbac.RBACPolicyEngine`
* **File & Lines:** `src/camserv/security/rbac.py:135-176`
* **Root Cause:** `enforce_quorum_authorization` verified that two distinct roles were provided, but did not require or verify that the primary actor and co-signer were distinct physical/logical user identities.
* **Impact:** A privileged user assigned multiple roles (e.g. holding both Investigator and Tenant Admin permissions) could co-sign their own request, circumventing the dual-person integrity requirement.
* **Remediation:** Added `primary_user_id` and `co_signer_user_id` validation ensuring identities are non-identical.
* **Verification:** Tested in `tests/test_audit_vulnerabilities.py::test_sec_p3_07_quorum_distinct_user_identities`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P3-08: Missing Inactive Tenant Enforcement in MultiTenantEnforcer
* **Severity:** **MEDIUM** (CWE-284 / CVSS 5.0)
* **Affected Component:** `camserv.security.tenancy.MultiTenantEnforcer`
* **File & Lines:** `src/camserv/security/tenancy.py:69-89`
* **Root Cause:** `enforce_tenant_boundary` validated that caller tenant matched resource tenant, but did not check whether the tenant's record was active (`tenant.is_active`).
* **Impact:** Users belonging to suspended or terminated tenant accounts could continue executing operations against resources.
* **Remediation:** Added active status validation in `enforce_tenant_boundary`.
* **Verification:** Tested in `tests/test_audit_vulnerabilities.py::test_sec_p3_08_inactive_tenant_rejection`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P3-09: Imprecise Cryptographic Terminology in Audit Trail Documentation
* **Severity:** **LOW / INFO**
* **Affected Component:** `camserv.security.audit_trail.SecurityAuditLogger`
* **File & Lines:** `src/camserv/security/audit_trail.py:159`
* **Finding:** The docstring claimed a "cryptographic SHA-256 Merkle hash chain". In reality, the implementation is a sequential linear hash chain (blockchain-style $H_n = \text{SHA256}(R_n \parallel H_{n-1})$), not a Merkle tree with logarithmic inclusion proofs.
* **Remediation:** Clarified documentation to accurately describe the linear hash chain and its tamper-evident guarantees.
* **Status:** **REMEDIATED & CLARIFIED**.

---

### SEC-P3-10: Hardcoded Default Master Secret Fallback in KeyManager
* **Severity:** **LOW / HARDENING**
* **Affected Component:** `camserv.security.keys.KeyManager`
* **File & Lines:** `src/camserv/security/keys.py:82`
* **Finding:** When `CAMSERV_MASTER_KEY` environment variable was absent, the system fell back to a hardcoded string `"camserv-default-master-key-32b-min"` without warning.
* **Remediation:** Added explicit security warning logging when the default development master key is used, prompting deployment engineers to configure high-entropy keys in production.
* **Status:** **REMEDIATED & LOGGED**.

---

## 3. Phase 11 Verification & Independent Audit Findings

### SEC-P11-01: StreamingGateway Argument Inversion & Fail-Closed Privacy Bypass
* **Severity:** **CRITICAL** (CWE-284 / CWE-687 / CVSS 9.3)
* **Affected Component:** `camserv.nvr.streaming.StreamingGateway`
* **File & Lines:** `src/camserv/nvr/streaming.py:96-130`
* **Root Cause:** When ingesting operational frames, `StreamingGateway` invoked `self.privacy_pipeline.process_frame(camera_id, frame)`. However, `process_frame` expects `(raw_frame, camera_id)`. Passing arguments inverted caused a type mismatch or crash. Furthermore, calling code attempted `.derivative_frame` on a 3-tuple `(masked_frame, manifest, pristine_original)`. Most critically, when `self.privacy_pipeline` was unconfigured (`None`), unmasked surveillance frames were distributed directly if `allow_unmasked` was improperly set or defaulted.
* **Impact:** Immediate privacy failure: either uncaught runtime crashes breaking video distribution, or silent leakage of unmasked biometric faces across browser MJPEG/WebRTC streaming endpoints.
* **Remediation:** Standardized keyword arguments `process_frame(raw_frame=frame, camera_id=camera_id)`, unpacked the 3-tuple cleanly, added `_generate_fail_closed_frame(frame)` watermark blackout, and enforced fail-closed blackout if the pipeline is omitted.
* **Verification:** Tested in `tests/test_audit_phase11_regressions.py::test_streaming_gateway_fail_closed_pipeline_configured` and `test_streaming_gateway_fail_closed_pipeline_none_returns_blackout`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P11-02: Forensic Evidence ZIP Archive Unlisted File Injection Bypass
* **Severity:** **HIGH** (CWE-345 / CWE-494 / CVSS 7.8)
* **Affected Component:** `camserv.storage.forensics.IndependentVerifier`
* **File & Lines:** `src/camserv/storage/forensics.py:190-230`
* **Root Cause:** `verify_package` iterated solely over keys manifested inside `metadata.json` (`for fname, expected_hash in manifest.items()`). It failed to enumerate the actual contents of the ZIP container (`zf.namelist()`).
* **Impact:** An attacker in possession of a valid, signed forensic export ZIP could inject arbitrary malicious executables (e.g. root exploits, malware, altered investigative reports) into `payload/` or archive root without invalidating the cryptographic Ed25519 signature.
* **Remediation:** Added strict archive container validation asserting that every entry in `zf.namelist()` belongs to `metadata.json`, `signature.sig`, or matches an explicitly signed manifest hash inside `payload/`. Extraneous files are flagged as `UNLISTED_INJECTED_FILE` or `UNAUTHORIZED_ARCHIVE_ENTRY`, failing verification.
* **Verification:** Tested in `tests/test_audit_phase11_regressions.py::test_forensic_verifier_rejects_unlisted_file_injection`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P11-03: Dual-Control Quorum Co-Signer Scope Unbound & Replay Vulnerability
* **Severity:** **HIGH** (CWE-285 / CWE-294 / CVSS 7.5)
* **Affected Component:** `camserv.api.routes` (`/api/forensics/unmask-stream` and `/api/evidence/export`)
* **File & Lines:** `src/camserv/api/routes.py:800-845`
* **Root Cause:** Quorum verification validated that the co-signer header provided a valid JWT bearing a compliant role (e.g. `COMPLIANCE_OFFICER` or `FORENSIC_INVESTIGATOR`), but did not cryptographically bind the token to the specific `camera_id` or temporal window requested. Additionally, single-use approval tokens lacked replay tracking.
* **Impact:** A co-signer token granted for low-sensitivity Camera A could be maliciously reused to unmask highly sensitive Camera B (cross-camera privilege escalation), or replayed multiple times across different days.
* **Remediation:** Enforced scoped claim validation (`approved_camera_id`, `approved_start_time`, `approved_end_time`) against the request body, and added single-use token tracking via `consumed_quorum_jtis`.
* **Verification:** Tested in `tests/test_audit_phase11_regressions.py::test_dual_control_token_validation_scope_and_replay`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P11-04: Multi-Tenant Boundary Isolation Gap in Central Fleet Synchronization
* **Severity:** **HIGH** (CWE-284 / CWE-200 / CVSS 7.4)
* **Affected Component:** `camserv.central.sync.CentralSyncEngine`
* **File & Lines:** `src/camserv/central/sync.py:36-78`, `260-385`
* **Root Cause:** `FleetCameraInfo` and `FleetRecordingRecord` did not encapsulate a `tenant_id` field. Query methods `query_fleet_recordings` and `discover_fleet_cameras` had no parameter to filter records by organizational tenant.
* **Impact:** In a multi-tenant cloud or central management deployment, Tenant A could query and view recording metadata, timelines, and camera inventories belonging to Tenant B.
* **Remediation:** Added `tenant_id` to `FleetCameraInfo`, `FleetRecordingRecord`, `EdgeSyncClient`, and `CentralSyncEngine`, enforcing strict tenant boundary filtering on all fleet-wide queries.
* **Verification:** Tested in `tests/test_audit_phase11_regressions.py::test_central_sync_multi_tenant_boundary_isolation`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P11-05: Non-Atomic Quota Purge & TOCTOU Judicial Hold Race Condition
* **Severity:** **MEDIUM** (CWE-367 / CVSS 6.8)
* **Affected Component:** `camserv.nvr.recording_engine.NVRRecordingEngine`
* **File & Lines:** `src/camserv/nvr/recording_engine.py:510-545`
* **Root Cause:** `enforce_storage_quota` fetched candidate continuous recordings in bulk, sorted them, and then iterated through the list unlinking segment files. If a judicial hold was applied concurrently via API or background task after the query was executed, the stale in-memory record resulted in the held recording segments being unlinked.
* **Impact:** Irreversible destruction of legally protected forensic surveillance evidence during storage space exhaustion.
* **Remediation:** Implemented atomic verification immediately before unlinking: `current_rec = self.store.get_recording(rec_id)` re-validates `judicial_hold` and `is_incident` flags directly against persistent storage before any file deletion occurs.
* **Verification:** Tested in `tests/test_audit_phase11_regressions.py::test_quota_purge_preserves_concurrent_judicial_holds`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P11-06: Hardware AI Accelerator False Success on Missing Physical Devices
* **Severity:** **MEDIUM** (CWE-392 / CVSS 5.3)
* **Affected Component:** `camserv.analytics.adapters` (`coral.py`, `hailo.py`, `cuda.py`, `openvino.py`)
* **File & Lines:** `src/camserv/analytics/adapters/*.py`
* **Root Cause:** Adapter classes for Google Coral, Hailo-8, NVIDIA CUDA, and Intel OpenVINO implemented `is_available()`, but `load_model` unconditionally logged success and returned `True` even when `is_available() == False`. Additionally, `infer()` returned an empty list `[]` instead of signaling hardware absence.
* **Impact:** System administrators and pipeline orchestrators were falsely led to believe that AI inference was running on high-efficiency dedicated silicon (Edge TPU / NPU / GPU) when the system was unaccelerated or failing to detect the hardware.
* **Remediation:** Updated all accelerator adapters: `load_model` checks `self.is_available()` and returns `False` if the device/driver is missing; `infer()` raises `RuntimeError` if invoked on an unavailable backend.
* **Verification:** Tested in `tests/test_audit_phase11_regressions.py::test_hardware_adapters_fail_cleanly_when_device_absent`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P11-07: Version Manifest Discrepancy & GDPR Policy Terminology Precision
* **Severity:** **INFORMATIONAL / TRACEABILITY**
* **Affected Component:** Release packaging and documentation
* **File & Lines:** `src/camserv/__init__.py`, `pyproject.toml`, `deploy/sbom/camserv-sbom.json`, `src/camserv/api/routes.py`
* **Finding:** Discrepancies existed between `__version__ = "0.1.0"` in `__init__.py` and the target Release Candidate `0.9.0-rc1` documented in `RELEASE_ROADMAP.md`. Additionally, docstrings previously described dual-control quorum as a statutory mandate of GDPR Art. 25 rather than an engineering policy implementing Data Protection by Design.
* **Remediation:** Synchronized version `0.9.0-rc1` across `__init__.py`, `pyproject.toml`, and regenerated CycloneDX SBOM. Refined API docstrings to accurately state that dual-control quorum is an engineering measure realizing GDPR Article 25 requirements.
* **Verification:** Tested in `tests/test_audit_phase11_regressions.py::test_version_manifest_alignment`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 4. Phase 12 Real-World Hardware & Camera Compatibility Findings

### SEC-P12-01: Plaintext RTSP Credentials Leakage in Logs, Metadata & APIs
* **Severity:** **HIGH** (CWE-532 / CWE-312 / CVSS 7.5)
* **Affected Component:** `camserv.acquisition.camera`, `camserv.api.routes`, `camserv.nvr.credentials`
* **File & Lines:** `src/camserv/nvr/credentials.py:65-98`, `src/camserv/acquisition/camera.py:102-108`, `src/camserv/api/routes.py:136-160`
* **Root Cause:** Ingestion configurations stored RTSP URLs containing embedded plaintext credentials (`rtsp://admin:pass@host/live`). This URL was bound directly to logger contexts, attached to raw `Frame.metadata["source"]`, and returned in REST API responses (`/api/v1/cameras`).
* **Impact:** Operators with log access or read-only API tokens could harvest plaintext surveillance camera credentials and gain unauthorized access to camera feeds and configuration interfaces.
* **Remediation:** Implemented `redact_url_credentials(url: str) -> str` using greedy userinfo regex, masked credentials in `CameraCredential.to_safe_dict()`, and sanitized all logger bindings, frame metadata, and API responses.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_redact_url_credentials_comprehensive` and `test_camera_stream_redacts_credentials_in_logs_and_metadata`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P12-02: Unconditional False Success Reporting in NVRCompatibilityTester
* **Severity:** **HIGH** (CWE-392 / CVSS 7.2)
* **Affected Component:** `camserv.acquisition.onvif.NVRCompatibilityTester`
* **File & Lines:** `src/camserv/acquisition/onvif.py:270-285`
* **Root Cause:** When checking camera network reachability, `NVRCompatibilityTester` substituted `allow_simulation` into the connection success flag when the TCP socket connection failed, reporting `"NVR is fully compatible"` for offline or unreachable cameras.
* **Impact:** Automated pre-flight installation checks reported success on failed camera setups, leading to silent failures during field deployment.
* **Remediation:** Decoupled physical socket connection status (`conn_ok`) from simulation fallback, enforcing explicit validation classification (`VERIFIED_ON_REAL_CAMERA` vs `SIMULATED` vs `FAILED`).
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_nvr_compatibility_tester_honest_reporting`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P12-03: Device Index Numeric String Parse Failure on Physical UVC Webcams
* **Severity:** **MEDIUM** (CWE-20 / CVSS 5.3)
* **Affected Component:** `camserv.acquisition.camera._open_capture`, `supervisor.py`
* **File & Lines:** `src/camserv/acquisition/camera.py:175-182`
* **Root Cause:** Passing string `"0"` to `cv2.VideoCapture("0")` causes OpenCV on Windows MSMF/DirectShow to treat the source as a file path rather than a hardware device index, returning `isOpened() == False`.
* **Impact:** Inability to ingest real USB and integrated webcam streams when configured via string identifiers (`source_url="0"`).
* **Remediation:** Added automated numeric string detection converting `source_url` to `int` when `.isdigit()` is true.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_camera_stream_device_index_parsing` and verified with physical Integrated Camera index 0.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P12-04: False CUDA Adapter Availability on Hosts with Physical GPU but Missing Python Runtime
* **Severity:** **MEDIUM** (CWE-392 / CVSS 5.3)
* **Affected Component:** `camserv.analytics.adapters.cuda.CUDABackendAdapter`
* **File & Lines:** `src/camserv/analytics/adapters/cuda.py:45-92`
* **Root Cause:** `CUDABackendAdapter.is_available()` checked only for the presence of `nvidia-smi` binary, ignoring whether the Python environment possessed a working CUDA execution runtime (`onnxruntime-gpu`, `torch.cuda`).
* **Impact:** System falsely claimed GPU hardware acceleration when running on CPU fallback, misleading administrators and risking runtime crashes during model loading.
* **Remediation:** Separated physical device detection (`is_device_detected()`) from execution runtime availability (`is_runtime_available()`). Returns `is_available()=False` and cleanly falls back to `onnx_cpu` when Python runtime is missing.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_cuda_adapter_honest_reporting`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P12-05: Missing GPU and VRAM Telemetry in AdaptiveResourceManager
* **Severity:** **MEDIUM** (CWE-392 / CVSS 4.3)
* **Affected Component:** `camserv.platform.adaptive_manager.AdaptiveResourceManager`
* **File & Lines:** `src/camserv/platform/adaptive_manager.py:82-115`
* **Root Cause:** `AdaptiveResourceManager` lacked telemetry collection for GPU utilization and VRAM consumption on host systems equipped with dedicated graphics cards.
* **Impact:** Adaptive workload shedding and hardware tier policies were blind to GPU saturation and VRAM exhaustion.
* **Remediation:** Integrated live `nvidia-smi` query parsing, extracting real-time GPU load, VRAM used, and VRAM total into `ResourceSnapshot`.
* **Verification:** Tested in `tests/test_audit_phase12_regressions.py::test_adaptive_resource_manager_metrics` on host RTX 3060 Laptop GPU.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 5. Phase 13 Debian Appliance Engineering & Packaging Findings

### SEC-P13-01: Broken Systemd Dependency Graph & Missing Storage Unit
* **Severity:** **CRITICAL** (CWE-665 / CVSS 9.1)
* **Affected Component:** `deploy/systemd/camserv-core.service`, `deploy/systemd/camserv.target`
* **File & Lines:** `deploy/systemd/camserv-core.service:6`, `deploy/systemd/camserv.target:5`
* **Root Cause:** `camserv-core.service` declared `Requires=camserv-storage.service`, but `camserv-storage.service` was completely absent from the deployment definitions. Furthermore, `camserv-nvr.service` was omitted from `camserv.target`.
* **Impact:** Instant service startup failure: systemd refused to start `camserv-core.service`, completely breaking appliance initialization.
* **Remediation:** Created `deploy/systemd/camserv-storage.service` (`Type=oneshot`, `RemainAfterExit=yes`), implemented `src/camserv/storage/init_service.py` for pre-flight directory and schema migrations, and added `camserv-nvr.service` to `camserv.target`.
* **Verification:** Tested in `tests/test_audit_phase13_appliance.py::test_systemd_services_sandboxing_and_dependencies`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P13-02: Invalid CLI Subcommand in `camserv-core.service`
* **Severity:** **HIGH** (CWE-20 / CVSS 7.5)
* **Affected Component:** `deploy/systemd/camserv-core.service`, `src/camserv/main.py`
* **File & Lines:** `deploy/systemd/camserv-core.service:13`, `src/camserv/main.py:168-204`
* **Root Cause:** `camserv-core.service` invoked `python -m camserv.main run --host 0.0.0.0 --port 8000`. However, `camserv.main` defined the command as `serve`, lacking a `run` parser.
* **Impact:** Immediate crash on service launch: `camserv: error: argument command: invalid choice: 'run'`.
* **Remediation:** Added `run` as a first-class alias for `serve` in `camserv.main`, and updated `camserv-core.service` to explicitly invoke `serve`.
* **Verification:** Tested in `tests/test_audit_phase13_appliance.py::test_systemd_services_sandboxing_and_dependencies`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P13-03: `Type=notify` Misconfiguration Without `sd_notify` Signaling
* **Severity:** **MEDIUM** (CWE-392 / CVSS 5.3)
* **Affected Component:** `deploy/systemd/camserv-core.service`, `camserv-ingestion.service`, `camserv-inference.service`
* **File & Lines:** `deploy/systemd/*.service`
* **Root Cause:** Services declared `Type=notify` in their service headers, but neither FastAPI/Uvicorn nor Python worker scripts implemented systemd notify socket signaling.
* **Impact:** Systemd timed out after 90 seconds waiting for `READY=1` notification and terminated the processes with `SIGKILL`.
* **Remediation:** Configured `Type=simple` across all continuous background services, ensuring deterministic startup without notification socket hangs.
* **Verification:** Tested in `tests/test_audit_phase13_appliance.py::test_systemd_services_sandboxing_and_dependencies`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P13-04: Missing `video` and `render` Group Membership for Appliance Account
* **Severity:** **MEDIUM** (CWE-284 / CVSS 5.3)
* **Affected Component:** `deploy/debian/postinst`, `deploy/systemd/camserv-ingestion.service`
* **File & Lines:** `deploy/debian/postinst:11-14`, `deploy/systemd/camserv-ingestion.service:12-28`
* **Root Cause:** The unprivileged `camserv` system account created during `postinst` was not granted membership in `video` or `render` groups, and `camserv-ingestion.service` lacked device permissions for optical video capture nodes.
* **Impact:** Access to local USB/V4L2 webcams (`/dev/video*`) and GPU acceleration nodes (`/dev/dri/*`) failed with Permission Denied.
* **Remediation:** Added automated group addition to `video` and `render` in `postinst`, declared `SupplementaryGroups=video render` in services, and added `DeviceAllow=/dev/video* rwm`.
* **Verification:** Tested in `tests/test_audit_phase13_appliance.py::test_systemd_services_sandboxing_and_dependencies`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P13-05: Nonexistent Daemon Module Entrypoints in Systemd Services
* **Severity:** **HIGH** (CWE-665 / CVSS 7.5)
* **Affected Component:** `camserv.central.agent`, `camserv.nvr.recording_engine`, `camserv.acquisition.supervisor`, `camserv.inference.engine`
* **File & Lines:** `deploy/systemd/*.service`
* **Root Cause:** `camserv-agent.service` targeted `camserv.central.agent` which did not exist. Furthermore, `recording_engine.py`, `supervisor.py`, and `engine.py` lacked `__main__` entry points and exited immediately with code 0 when run by systemd.
* **Impact:** Inability to run modular background daemons under systemd.
* **Remediation:** Implemented `src/camserv/central/agent.py` (CentralApplianceAgent), and added robust `run_daemon()` loops with `SIGINT`/`SIGTERM` handlers to `recording_engine.py`, `supervisor.py`, and `engine.py`.
* **Verification:** Tested in `tests/test_audit_phase13_appliance.py::test_central_appliance_agent_sync_cycle`.
* **Status:** **REMEDIATED & VERIFIED**.

---

## 6. Phase 14 Release Candidate Qualification Findings

### SEC-P14-01: Complex Password Scrubbing in RTSP / HTTP Connection Strings
* **Severity:** **HIGH** (CWE-532 / CVSS 7.1)
* **Affected Component:** `camserv.nvr.credentials.redact_url_credentials`
* **File & Lines:** `src/camserv/nvr/credentials.py:30-35`
* **Root Cause:** Standard URL parsing often broke when passwords contained multiple `@` symbols, colons, or URL-encoded entities (e.g., `rtsp://admin:P@ss@word@@cam/live`).
* **Impact:** Plaintext camera passwords could be emitted into diagnostic logs, crash reports, or REST management endpoints.
* **Remediation:** Upgraded the redaction regex to greedy prefix matching (`r"://([^/:]+):.*@([^/@]+)"`), ensuring that all characters between the first colon and the final `@` preceding the host are scrubbed into `***`.
* **Verification:** Tested in `tests/test_audit_phase14_qualification.py::test_stage_f_credential_scrubbing_edge_cases`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P14-02: Evidence Vault Destruction Risk on Administrative Package Purge
* **Severity:** **HIGH** (CWE-404 / CVSS 7.8)
* **Affected Component:** `deploy/debian/postrm`
* **File & Lines:** `deploy/debian/postrm:14-22`
* **Root Cause:** Standard Debian maintainer purge scripts typically delete `/var/lib/<package>`.
* **Impact:** Running `apt purge camserv` would permanently delete video recordings and court-ordered forensic evidence archives, violating chain-of-custody and GDPR retention mandates.
* **Remediation:** Hardened `postrm` to explicitly preserve `/var/lib/camserv/vault` and `/var/lib/camserv/recordings` during package purge operations.
* **Verification:** Tested in `tests/test_audit_phase14_qualification.py::test_stage_g_and_h_18_stage_lifecycle_upgrade_rollback_and_concurrent_hold` (Scenario 15).
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P14-03: Concurrent Judicial Hold vs. Quota Purge Race Condition
* **Severity:** **HIGH** (CWE-362 / CVSS 7.4)
* **Affected Component:** `camserv.storage.tiered_storage` & `camserv.storage.adaptive_vault`
* **File & Lines:** `src/camserv/storage/tiered_storage.py:145-180`, `src/camserv/storage/adaptive_vault.py:160-195`
* **Root Cause:** Background disk quota managers could mark an old video segment for deletion during the exact microsecond an operator flagged it for judicial retention.
* **Impact:** Irreversible destruction of legally held video evidence.
* **Remediation:** Enforced synchronized locking and active `judicial_hold=True` exclusion before disk unlinking.
* **Verification:** Tested in `tests/test_audit_phase14_qualification.py::test_stage_g_and_h_18_stage_lifecycle_upgrade_rollback_and_concurrent_hold` (Scenario 18).
* **Status:** **REMEDIATED & VERIFIED**.

---

## 7. Phase 16 Windows 11 Implementation Findings

### SEC-P16-01: Windows MSI Uninstallation Evidence Destruction Prevention
* **Severity:** **HIGH** (CWE-404 / CVSS 7.8)
* **Affected Component:** `deploy/windows/build_msi.py`
* **Root Cause:** Standard Windows Installer component lifecycles remove all authored directory paths on package uninstall (`MsiInstallProduct` / `REMOVE=ALL`).
* **Impact:** Uninstalling or upgrading the Windows package would erase recorded video files and signed digital forensic vaults.
* **Remediation:** Configured `msidbComponentAttributesPermanent` (`0x0010`) on components `cmp_recordings`, `cmp_vault`, and `cmp_data`.
* **Verification:** Tested in `tests/test_windows_phase16_qualification.py::test_windows_msi_tables_and_service_schema`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P16-02: Plaintext Windows Credential Storage Elimination via DPAPI
* **Severity:** **HIGH** (CWE-312 / CVSS 7.5)
* **Affected Component:** `camserv.platform.windows.credentials.WindowsDPAPIVault`
* **Root Cause:** Windows services often store credentials in plaintext YAML or registry keys vulnerable to unprivileged inspection.
* **Impact:** Local privilege escalation or credential theft by malicious local users.
* **Remediation:** Integrated Win32 `CryptProtectData` with `_CRYPTPROTECT_LOCAL_MACHINE` and `_CRYPTPROTECT_UI_FORBIDDEN` to encrypt all camera passwords and signing keys bound to local machine hardware context.
* **Verification:** Tested in `tests/test_windows_phase16_qualification.py::test_windows_dpapi_machine_protection`.
* **Status:** **REMEDIATED & VERIFIED**.

---

### SEC-P16-03: Session 0 Shatter Attack Mitigation via Decoupled Console Architecture
* **Severity:** **HIGH** (CWE-250 / CVSS 7.4)
* **Affected Component:** `camserv.platform.windows.service.WindowsServiceRunner` & `camserv.desktop.console.DesktopOperatorConsole`
* **Root Cause:** Running GUI widgets directly inside Session 0 Windows Services exposes the process to shatter attacks and GUI isolation failures.
* **Impact:** Compromise of elevated service process from unprivileged desktop session.
* **Remediation:** Strictly decoupled the architecture: `WindowsServiceRunner` contains zero windowing or GUI code; `DesktopOperatorConsole` operates exclusively in user desktop sessions communicating via loopback REST/WebSocket (`127.0.0.1:8080`) with JWT authentication.
* **Verification:** Tested in `tests/test_windows_phase16_qualification.py::test_desktop_client_mock_api_interaction` and Session 0 inspection.
* **Status:** **REMEDIATED & VERIFIED**.
