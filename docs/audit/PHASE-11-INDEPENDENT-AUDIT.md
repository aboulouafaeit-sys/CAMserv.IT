# CAMserv — Phase 11 Independent System Verification & Security Audit Report
**Stage A: Independent Read-Only Security & Architecture Audit**

- **Audit Date:** 2026-11-15T21:40:00Z
- **Auditing Organization:** Independent Software Verification & Cybersecurity Audit Team
- **Repository:** `aboulouafaeit-sys/CAMserv.IT`
- **Branch:** `main`
- **Verified Git HEAD:** `b35d3009abf5abb2e9cd0d97cf43558e0474baa8`
- **Production Audit Log Baseline (`logs/audit.jsonl`):**
  - **Byte Size:** `20,977 bytes`
  - **SHA-256:** `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525`
  - **Status:** Pristine, intact, strictly unmutated.
- **Reproduced Automated Test Baseline:** 279 passed in 17.12s (100% pass rate).

---

## 1. Executive Summary & Audit Mandate

In accordance with Phase 11 directives, this independent audit conducted a comprehensive, evidence-based review of CAMserv across core subsystems implemented in Phases 5 through 10. Prior claims were independently verified through code inspection, reproducible execution, and architectural boundary analysis.

### Subsystem Verification Overview
1. **Forensics & Cryptography:** Ed25519 asymmetric signatures and AES-256-GCM encryption are strictly separated. However, evidence ZIP packages did not check for extraneous unlisted files in `payload/`.
2. **Dual-Control Quorum:** Dual-control role separation between Primary Actor and Co-Signer is enforced, but co-signer tokens lacked cryptographically bound request scope (`camera_id`, `start_time_utc`, `end_time_utc`), introducing potential replay/scope escalation risks.
3. **Privacy Pipeline:** `StreamingGateway.update_camera_frame` inverted method arguments to `FailClosedPrivacyPipeline.process_frame`, attempted to access a tuple attribute `.derivative_frame`, and dangerously fell back to unmasked raw frames when `privacy_pipeline is None`.
4. **Multi-Tenancy & Central Platform:** Multi-tenant boundaries were implemented in `tenancy.py`, but omitted in `CentralSyncEngine` query routines, permitting cross-tenant visibility of recordings across distributed appliances.
5. **NVR Storage & Retention:** Judicial hold locking protects recordings against deletion, but quota purging unlinked files on disk prior to atomic database updates.
6. **Hardware Acceleration:** Pluggable adapters returned unconditional `True` on `load_model` even when hardware accelerators or drivers (`/dev/apex_0`, `/dev/hailo0`) were absent.
7. **Packaging & Supply Chain:** CycloneDX 1.5 JSON SBOM was successfully generated with 14 components and zero copyleft findings, with a minor version mismatch against Debian packaging control files.

---

## 2. Independent Findings Register (Stage A)

### [FINDING-11-01] CRITICAL: StreamingGateway Parameter Inversion, Runtime Crash & Fail-Closed Privacy Bypass
- **Severity:** CRITICAL
- **Affected File:** `src/camserv/nvr/streaming.py`
- **Function:** `StreamingGateway.update_camera_frame`
- **Technical Explanation:**
  `FailClosedPrivacyPipeline.process_frame` expects signature:
  `process_frame(self, raw_frame: np.ndarray, camera_id: str, ...)` and returns `(masked_frame, manifest, pristine_original)`.
  In `StreamingGateway.update_camera_frame`, the call was written as:
  ```python
  if self.privacy_pipeline is not None:
      privacy_result = self.privacy_pipeline.process_frame(camera_id, frame)
      safe_frame = privacy_result.derivative_frame
  else:
      safe_frame = frame
  ```
  1. `camera_id` (string) was passed as `raw_frame`, and `frame` (numpy array) was passed as `camera_id`.
  2. `privacy_result` is a 3-tuple, causing `AttributeError: 'tuple' object has no attribute 'derivative_frame'`.
  3. When `privacy_pipeline` is `None` (uninitialized or omitted), the `else` branch directly forwarded `safe_frame = frame`, emitting unmasked, unblurred raw footage to MJPEG, WebRTC, and LL-HLS viewers.
- **Actual Impact:** Runtime crash on active streams when privacy pipeline is attached, and catastrophic leak of unmasked PII/faces when unconfigured, violating the Non-Negotiable Fail-Closed Privacy rule.
- **Recommended Remediation:**
  1. Pass arguments correctly: `self.privacy_pipeline.process_frame(raw_frame=frame, camera_id=camera_id)`.
  2. Extract `masked_frame` from the returned tuple: `safe_frame, _, _ = ...`.
  3. Enforce fail-closed default: if `privacy_pipeline is None`, generate a fail-closed solid frame or require active privacy enforcer.
- **Regression Test Required:** Unit test passing an active `FailClosedPrivacyPipeline` to `StreamingGateway` and asserting output is masked, and verifying fail-closed behavior when pipeline is absent.

---

### [FINDING-11-02] HIGH: Unlisted File Injection Bypass in Forensic Evidence Packages
- **Severity:** HIGH
- **Affected File:** `src/camserv/storage/forensics.py`
- **Function:** `IndependentVerifier.verify_package`
- **Technical Explanation:**
  The verification loop strictly iterated over keys present in `metadata.json["manifest"]`:
  ```python
  for fname, expected_hash in manifest.items():
      zip_entry = f"payload/{fname}"
      ...
  ```
  If an adversary inserts extraneous files (e.g., `payload/backdoor.sh` or `payload/unauthorized_clip.mp4`) into the ZIP archive, the verifier validates all manifest entries, observes zero hash mismatches, and reports `is_valid: True` without detecting unlisted payload files.
- **Actual Impact:** Forensic archive integrity cannot guarantee that unverified artifacts have not been introduced into the evidence container.
- **Recommended Remediation:**
  Scan `zf.namelist()` for all entries matching `payload/*`. If any file in `payload/` is not declared in `manifest`, append to `tampered_files` and flag `is_valid: False`.
- **Regression Test Required:** Inject an unlisted file into a valid signed forensic package and assert that `IndependentVerifier.verify_package` returns `is_valid: False` with `UNLISTED_FILE_INJECTED`.

---

### [FINDING-11-03] HIGH: Dual-Control Quorum Scope Unbound (Replay & Scope Escalation Risk)
- **Severity:** HIGH
- **Affected File:** `src/camserv/api/routes.py`
- **Function:** `export_forensic_evidence`
- **Technical Explanation:**
  `co_signer_token` in `ForensicExportRequest` only verified that the token belonged to an authenticated user with an authorized role (`Role.FORENSIC_INVESTIGATOR` or `Role.SUPER_ADMIN`) and that `primary_user_id != co_signer_user_id`.
  The token did not verify request-bound scope (`camera_id`, `start_time_utc`, `end_time_utc`). An approval token issued for a 5-minute review on `cam_entrance` could be submitted to export a 24-hour unmasked feed for `cam_restricted_vault`.
- **Actual Impact:** Replay of dual-control approval tokens across unauthorized cameras and expanded temporal windows.
- **Recommended Remediation:**
  If `co_signer_token` contains scoped claims (`approved_camera_id`, `approved_start_time`, `approved_end_time`), validate that they match the export request payload. If claims mismatch, reject with HTTP 403 Forbidden.
- **Regression Test Required:** Attempt to submit a co-signer token with mismatched `approved_camera_id` and assert HTTP 403 Forbidden response.

---

### [FINDING-11-04] HIGH: Missing Multi-Tenant Boundary Isolation in Central Recording Queries
- **Severity:** HIGH
- **Affected File:** `src/camserv/central/sync.py`
- **Class / Function:** `CentralSyncEngine.query_fleet_recordings` & `FleetRecordingRecord`
- **Technical Explanation:**
  `FleetRecordingRecord` and `FleetCameraInfo` schemas omitted `tenant_id`. `CentralSyncEngine.query_fleet_recordings` allowed callers to filter by `site_id`, `camera_id`, and `has_event`, but lacked mandatory `tenant_id` partitioning. In a multi-tenant central deployment, an operator belonging to Tenant A could list and query recordings registered by edge appliances belonging to Tenant B.
- **Actual Impact:** Cross-tenant surveillance metadata leakage.
- **Recommended Remediation:**
  Add `tenant_id: str = "default"` to `FleetRecordingRecord` and `FleetCameraInfo`. Accept `tenant_id` in queries and reject cross-tenant queries when `MultiTenantEnforcer` is enabled.
- **Regression Test Required:** Register recordings for Tenant 1 and Tenant 2; verify that querying as Tenant 1 returns strictly Tenant 1 data.

---

### [FINDING-11-05] MEDIUM: Non-Atomic Storage Quota Purging & Stale Judicial Hold Check
- **Severity:** MEDIUM
- **Affected File:** `src/camserv/nvr/recording_engine.py`
- **Function:** `NVRRecordingEngine.enforce_storage_quota`
- **Technical Explanation:**
  `enforce_storage_quota` queried recordings via `self.store.list_recordings()` at loop start. In the loop, it unlinked segment files on disk *before* invoking `self.store.delete_recording(rec_id)`.
  If an operator placed a judicial hold on `rec_id` concurrently between `list_recordings` and file unlinking, the disk files were permanently deleted, but `delete_recording` rejected the database deletion, leaving the database pointing to missing files.
- **Actual Impact:** Premature deletion of files under concurrent judicial hold, and orphaned database records upon crash.
- **Recommended Remediation:**
  Re-verify `self.store.get_recording(rec_id)` atomically before unlinking. If `judicial_hold` is active, immediately skip deletion.
- **Regression Test Required:** Unit test simulating concurrent judicial hold during quota evaluation and proving files remain untouched.

---

### [FINDING-11-06] MEDIUM: AI Hardware Accelerators Returning False Success When Absent
- **Severity:** MEDIUM
- **Affected File:** `src/camserv/analytics/adapters/` (`coral.py`, `hailo.py`, `cuda.py`, `openvino.py`)
- **Function:** `InferenceBackendAdapter.load_model`
- **Technical Explanation:**
  In `CoralEdgeTPUAdapter` and `HailoNPUAdapter`, `load_model` returned `True` unconditionally, regardless of whether `self.is_available()` was `False`. If called on hardware without `/dev/apex_0` or `/dev/hailo0`, it reported successful model loading despite being completely unable to perform hardware inference.
- **Actual Impact:** False sense of hardware acceleration and diagnostic reporting errors.
- **Recommended Remediation:**
  In `load_model`, check `if not self.is_available(): raise RuntimeError(...)` or return `False` so system falls back gracefully to CPU.
- **Regression Test Required:** Instantiate `CoralEdgeTPUAdapter` on system without Coral device, verify `load_model` raises `RuntimeError` or returns `False`.

---

### [FINDING-11-07] LOW / INFORMATIONAL: Package Version and Regulatory Citation Precision
- **Severity:** INFORMATIONAL
- **Affected File:** `pyproject.toml`, `src/camserv/__init__.py`, `deploy/debian/control`, `docs/RECORDING_AND_STORAGE_ARCHITECTURE.md`
- **Technical Explanation:**
  `__version__` was set to `0.1.0` in `__init__.py` and `pyproject.toml`, while Debian control specified `0.9.0-rc1`. In addition, error strings referenced "GDPR Article 25" as mandating dual-control cryptographic signatures; while Article 25 requires data protection by design and default, dual-control signatures are a platform architectural policy implementing this principle, not a statutory requirement.
- **Recommended Remediation:**
  Align version numbers to `0.9.0-rc1` and refine error messages to clarify that dual-control authorization is an organizational policy control implementing GDPR Art. 25 data protection by design.

---

## 3. Stage A Verification Verdict

| Finding ID | Title | Severity | Remediation Priority |
| :--- | :--- | :--- | :--- |
| **FINDING-11-01** | `StreamingGateway` Argument Inversion & Privacy Bypass | **CRITICAL** | Immediate (Stage B) |
| **FINDING-11-02** | Unlisted File Injection in Forensic Evidence Package | **HIGH** | Immediate (Stage B) |
| **FINDING-11-03** | Dual-Control Quorum Token Scope Unbound | **HIGH** | Immediate (Stage B) |
| **FINDING-11-04** | Missing Multi-Tenant Boundary in Central Sync | **HIGH** | Immediate (Stage B) |
| **FINDING-11-05** | Non-Atomic Quota Purge & Stale Judicial Hold Check | **MEDIUM** | Immediate (Stage B) |
| **FINDING-11-06** | Hardware AI Adapters False Success on Absent Hardware | **MEDIUM** | Immediate (Stage B) |
| **FINDING-11-07** | Version Discrepancies & Regulatory Citation Phrasing | **INFORMATIONAL** | Immediate (Stage B) |

**Stage A Status: COMPLETE.** Ready to proceed with Stage B Controlled Remediation.
