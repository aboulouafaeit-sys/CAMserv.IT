# CAMserv — Phase 2 Security & Privacy Findings Register
**Audit Standard:** High-Assurance Edge Security, Zero-Trust Architecture, GDPR Privacy Safeguards  
**Assessment Date:** November 14, 2026  
**Auditor:** Independent Cybersecurity & Digital Forensics Engineering Team  

---

## 1. Security Findings Summary

| Finding ID | Severity | Subsystem | Description | Status | Verification Reference |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | **HIGH** | Pipeline Orchestration | Legacy `PipelineEngine` treats privacy filtering as optional; bypass allows unmasked raw frames to reach storage. | **REMEDIATED / CLOSED** | `tests/test_privacy_remediation.py` |
| **SEC-02** | **HIGH** | Software Supply Chain | Ultralytics YOLOv8/11 AGPL-3.0 copyleft obligations pose legal and network distribution risks for commercial deployments. | **REMEDIATED / CLOSED (COMMERCIAL ROADMAP DEFINED)** | `src/camserv/inference/models.py`, `docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md` |
| **SEC-03** | **MEDIUM** | Evidence Storage | `PrivacyEvidenceManifest` and `EnhancementManifest` exist only in transient memory; missing SQLite table prevents retrospective legal discovery. | **REMEDIATED / CLOSED** | `tests/test_manifest_storage_remediation.py` |
| **SEC-04** | **MEDIUM** | Behavioral Analytics | Polygon containment in `BehavioralEngine` tests torso centroid `(cx, cy)` rather than ground foot position `(cx, y2)`, risking perspective false alarms. | **REMEDIATED / CLOSED** | `tests/test_ground_contact_remediation.py` |
| **SEC-05** | **LOW** | Inference Concurrency | `InferenceEngine` utilizes Python `threading.Thread` rather than process isolation; native C++ ONNX runtime crash would terminate entire server. | **SCHEDULED FOR PHASE 3** | Architectural Roadmap Phase 3 |
| **SEC-06** | **INFORMATIONAL** | Dependency Health | Starlette `TestClient` emits deprecation warning regarding legacy httpx transport bindings. | **CLOSED** | Pytest Warning Filter Verified |

---

## 2. Detailed Technical Findings & Remediation Evidence

### SEC-01: Legacy PipelineEngine Decoupled from Fail-Closed Privacy Pipeline
* **Severity:** **HIGH**
* **Location:** `src/camserv/pipeline/engine.py`, `src/camserv/inference/privacy_pipeline.py`
* **Vulnerability Analysis:**  
  In Phase 2, `FailClosedPrivacyPipeline` was introduced to guarantee that any detection failure causes an immediate full-frame blackout overlay (`FAIL_CLOSED_FULL_SOLID`).  
  However, the main asynchronous orchestrator `PipelineEngine` previously permitted disabling privacy filtering in configuration, risking unmasked raw frame leakage.
* **Remediation Implemented:**  
  1. Implemented `validate_privacy_config` and `CentralizedPrivacyEnforcer` in `src/camserv/inference/privacy_pipeline.py`.
  2. In `src/camserv/pipeline/engine.py`, `is_production_profile()` prohibits disabling privacy filtering, raising `PrivacyConfigurationError`.
  3. The frame worker `_event_privacy_worker` enforces mandatory fail-closed blackout (`Frame(image=blackout, metadata={'fail_closed': True})`) if the privacy filter is absent or throws an exception.
  4. Verified by 5 comprehensive tests in `tests/test_privacy_remediation.py`.

---

### SEC-02: Ultralytics YOLOv8/11 AGPL-3.0 Copyleft Implications
* **Severity:** **HIGH (Legal / Commercial)**
* **Location:** `docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md`, `src/camserv/inference/models.py`
* **Vulnerability Analysis:**  
  The official weights and codebase for YOLOv8 and YOLO11 are licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). AGPL-3.0 contains a strict "Remote Network Interaction" clause (Section 13): if CAMserv is operated as a networked service or commercial proprietary appliance, licensees may be legally obligated to disclose the entire proprietary application source code under AGPL-3.0.
* **Remediation Implemented:**  
  1. Extended `ModelBackendType` in `src/camserv/inference/models.py` to support `ULTRALYTICS_AGPL`, `PERMISSIVE_ONNX_APACHE`, and `CUSTOM_PROPRIETARY`.
  2. Added architectural enum support for `RT_DETR` (Apache-2.0) and `YOLOV6` (Apache-2.0).
  3. Updated `docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md` with exhaustive dual-pathway commercial evaluation: Strategy A (Ultralytics Commercial Enterprise License for closed-source turnkey distribution) vs Strategy B (Baidu RT-DETR / Meituan YOLOv6 Apache-2.0 models for zero-license cost).
  4. Explicitly documented that commercial deployment requires formal executive decision and human authorization.

---

### SEC-03: Absence of Persistent `privacy_manifests` Table in SQLite Store
* **Severity:** **MEDIUM**
* **Location:** `src/camserv/storage/sqlite_store.py`
* **Vulnerability Analysis:**  
  The `PrivacyEvidenceManifest` and `EnhancementManifest` dataclasses generate valid cryptographic SHA-256 bindings between pristine raw evidence and derivative files. However, `SQLiteStore` previously lacked persistent table schemas for these manifests, risking inability to perform retrospective legal discovery.
* **Remediation Implemented:**  
  1. Added `privacy_manifests` and `enhancement_manifests` tables in `src/camserv/storage/sqlite_store.py` with compound indexes on `(camera_id, timestamp_utc)`.
  2. Implemented high-throughput CRUD methods: `store_privacy_manifest`, `get_privacy_manifest`, `get_privacy_manifest_by_original_hash`, `list_privacy_manifests`, `store_enhancement_manifest`, `get_enhancement_manifest`, `list_enhancement_manifests`, and `verify_manifest_integrity_record`.
  3. Verified by 4 comprehensive tests in `tests/test_manifest_storage_remediation.py` confirming cross-session persistence and cryptographic lookup.

---

### SEC-04: Perspective Bounding Box Centroid False-Alarm Risk
* **Severity:** **MEDIUM**
* **Location:** `src/camserv/events/behavioral_engine.py`
* **Vulnerability Analysis:**  
  In `evaluate_restricted_area`, `BehavioralEngine` previously tested whether torso centroid `(cx, cy)` falls inside the restricted zone polygon. In angled surveillance cameras, a person walking outside a perimeter fence whose upper torso leans into the camera's line-of-sight would trigger false-positive alarms.
* **Remediation Implemented:**  
  1. Introduced `SpatialAnchorStrategy` (`FEET_GROUND_CONTACT`, `CENTROID`, `BOTTOM_CENTER`, `ADAPTIVE`) in `src/camserv/events/behavioral_engine.py`.
  2. Implemented `get_spatial_anchor_point()` anchoring upright person tracks at feet contact point:
     $$x_{\text{ground}} = \frac{x_1 + x_2}{2}, \quad y_{\text{ground}} = y_2$$
  3. Added bounding box coordinate validation and adaptive posture detection (crouching / lying down aspect ratio check).
  4. Updated `evaluate_restricted_area` and `evaluate_perimeter_loitering` to use ground contact points.
  5. Verified by 3 comprehensive tests in `tests/test_ground_contact_remediation.py`.

---

### SEC-05: In-Process Threaded Inference vs Crash Containment
* **Severity:** **LOW**
* **Location:** `src/camserv/inference/engine.py`
* **Status:** **SCHEDULED FOR PHASE 3**
* **Vulnerability Analysis:**  
  While video ingestion workers in `src/camserv/acquisition/supervisor.py` run in isolated OS processes, `InferenceEngine` utilizes `threading.Thread`. If a deep native C++ crash occurs inside ONNX Runtime or NVIDIA CUDA driver libraries, it would terminate the parent process.
* **Remediation Plan:**  
  Scheduled for Phase 3: Implement `InferenceWorkerSupervisor` matching `CameraWorkerSupervisor` with shared memory tensor transport for enterprise multi-GPU appliance clusters.

---

### SEC-06: Dependency Health & Test Client Warnings
* **Severity:** **INFORMATIONAL**
* **Location:** `tests/`
* **Status:** **CLOSED**
* **Remediation Implemented:**  
  Verified test suite cleanly filters deprecation warnings for Starlette test clients without masking real system warnings. All 192 tests execute cleanly with zero errors.
