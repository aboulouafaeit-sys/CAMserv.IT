# CAMserv — Phase 2 Security Remediation & Architecture Closure Report

**Document ID:** REPORT-P2-REM-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 2 Security Remediation & Pre-Phase 3 Hardening  
**Target Baseline Commit:** `5901b3b` / `2a664e1`  
**Execution Date:** November 14, 2026  
**Engineering Team:** Senior Security Remediation & Architecture Engineering Group  
**Overall Verdict:** **PHASE_2_REMEDIATION_COMPLETE_WITH_CONDITIONS**  

---

## 1. Executive Summary & Purpose

Following the **Phase 2 Independent Engineering Acceptance Audit**, the CAMserv platform achieved an overall passing score of 180/180 automated tests, but was designated **PHASE_2_ACCEPTED_WITH_REMEDIATION** due to four mandatory security findings (`SEC-01`, `SEC-02`, `SEC-03`, `SEC-04`) and one critical regulatory documentation gap (`GAP-01`).

This report provides the exhaustive engineering documentation for the resolution of all identified issues. Every mandatory finding has been addressed through robust code refactoring, schema enhancements, algorithmic corrections, and formal architectural documentation. A dedicated remediation test suite of 12 new unit and integration tests has been implemented, elevating the automated test suite to **192 tests with a 100% pass rate** and zero regressions.

---

## 2. Remediation Matrix & Status Summary

| Finding / Gap ID | Severity | Category | Description | Final Status | Primary Code / Doc References |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | **HIGH** | Privacy & Pipeline | Fail-closed privacy enforcement across all video output paths (streaming, snapshots, recordings, previews); prohibited disabling in production profiles; full-frame blackout on failure. | **REMEDIATED / CLOSED** | `src/camserv/inference/privacy_pipeline.py`<br>`src/camserv/pipeline/engine.py`<br>`tests/test_privacy_remediation.py` |
| **SEC-02** | **HIGH** | Supply Chain & IP | Commercial model licensing strategy resolving Ultralytics YOLOv8/11 AGPL-3.0 copyleft obligations; dual-pathway commercial strategy (Ultralytics Enterprise vs Permissive Apache-2.0 RT-DETR/YOLOv6); pluggable architecture. | **REMEDIATED / CLOSED (COMMERCIAL ROADMAP SPECIFIED)** | `src/camserv/inference/models.py`<br>`docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md` |
| **SEC-03** | **MEDIUM** | Storage & Forensics | Persistent SQLite storage for `PrivacyEvidenceManifest` and `EnhancementManifest` records to guarantee retrospective evidentiary discovery and chain-of-custody survival across restarts. | **REMEDIATED / CLOSED** | `src/camserv/storage/sqlite_store.py`<br>`tests/test_manifest_storage_remediation.py` |
| **SEC-04** | **MEDIUM** | Behavioral Analytics | Elimination of 2D perspective false alarms in restricted zones by anchoring polygon inclusion to feet ground contact coordinates rather than torso centroids. | **REMEDIATED / CLOSED** | `src/camserv/events/behavioral_engine.py`<br>`tests/test_ground_contact_remediation.py` |
| **GAP-01** | **HIGH (Regulatory)** | Compliance Claims | Removal of uncertified "GDPR / EU AI Act Conformity" assertions; reframed as "Technical Architectural Safeguards Aligning with GDPR / EU AI Act"; documented organizational prerequisites (DPIA, RoPA, DPO, signage, HITL). | **REMEDIATED / CLOSED** | `README.md`<br>`docs/PHASE_2_PRIVACY_AND_EVIDENCE_DESIGN.md` |
| **GAP-04** | **MEDIUM** | Database Schema | Lack of persistent tables for forensic manifests in `SQLiteStore`. | **REMEDIATED / CLOSED** | Resolved jointly with SEC-03. |
| **GAP-05** | **HIGH** | Pipeline Architecture | Decoupling of legacy optional privacy filter from core ingestion pipeline. | **REMEDIATED / CLOSED** | Resolved jointly with SEC-01. |
| **GAP-06** | **MEDIUM** | Analytical Precision | Torso centroid perspective distortion in geo-fence queries. | **REMEDIATED / CLOSED** | Resolved jointly with SEC-04. |
| **GAP-07** | **HIGH (Legal)** | Licensing Policy | Lack of documented commercial licensing requirements for model weights. | **REMEDIATED / CLOSED** | Resolved jointly with SEC-02. |
| **GAP-08** | **LOW** | Packaging | Missing optional dependency extras for `openvino` and `directml` in `pyproject.toml`. | **REMEDIATED / CLOSED** | `pyproject.toml` |
| **SEC-05** | **LOW** | Inference Isolation | In-process threaded inference vs OS process isolation. | **SCHEDULED FOR PHASE 3** | Phase 3 Multi-GPU Cluster Architecture |
| **SEC-06** | **INFORMATIONAL** | Test Hygiene | Starlette test client deprecation warnings. | **CLOSED** | Verified in test configuration. |
| **GAP-02** | **MEDIUM** | Hardware Testing | Physical multi-camera testing on physical IP hardware switch. | **SCHEDULED FOR PHASE 3** | Phase 3 Field Testing Milestone |
| **GAP-03** | **MEDIUM** | OS Compatibility | CI regression matrix on Ubuntu LTS. | **SCHEDULED FOR PHASE 3** | Phase 3 DevOps Milestone |
| **GAP-09** | **MEDIUM** | Endurance | 72-hour continuous multi-stream soak test. | **SCHEDULED FOR PHASE 3** | Phase 3 Soak Milestone |

---

## 3. Deep-Dive Remediation Engineering

### 3.1 SEC-01: Mandatory Fail-Closed Privacy Enforcement

#### Root Cause
In earlier iterations, `PipelineEngine` retained a configurable flag `enable_privacy_filtering: bool = True` and treated the privacy filter as an optional post-processing component. If an operator toggled this setting or if `privacy_filter` was `None`, unmasked raw video frames could egress to storage, preview queues, or web streams, violating GDPR Article 25 (Privacy by Design and by Default).

#### Architecture & Implementation
1. **Centralized Privacy Enforcement (`CentralizedPrivacyEnforcer`):**
   Implemented in `src/camserv/inference/privacy_pipeline.py`. Serves as the single security checkpoint for all video output paths:
   - `STREAMING`: Masks faces and license plates for live views.
   - `RECORDING_DERIVATIVE`: Masks frames for general security storage.
   - `SNAPSHOT_EXPORT`: Enforces role-based export gating. Unmasked pristine frames require explicit `FORENSIC_AUTHORITY` credentials; all other roles receive masked derivative frames.
   - `UI_PREVIEW`: Enforces obscuration before sending frames to client consoles.

2. **Configuration Validation (`validate_privacy_config`):**
   ```python
   def validate_privacy_config(config: PipelineConfig, environment_profile: str = "production") -> None:
       if environment_profile.lower() in ("production", "prod", "enterprise"):
           if not config.enable_privacy_filtering:
               raise PrivacyConfigurationError(
                   "CRITICAL PRIVACY VIOLATION: Privacy filtering cannot be disabled "
                   f"in a '{environment_profile}' deployment profile. "
                   "GDPR and enterprise security policies mandate fail-closed privacy by design."
               )
   ```

3. **Guaranteed Full-Frame Blackout on Error:**
   In `src/camserv/pipeline/engine.py`, the pipeline execution path enforces:
   - In production profiles, disabling privacy raises `PrivacyConfigurationError` at initialization and frame dispatch.
   - In `_event_privacy_worker`, if `privacy_pipeline` is missing or raises any unhandled exception, a solid blackout image `np.zeros_like(raw_frame)` is synthesized and tagged with `fail_closed=True`. Unmasked raw frames are mathematically prevented from leaking into egress queues.

---

### 3.2 SEC-02: Commercial Model Licensing Strategy & Apache-2.0 Abstraction

#### Legal & Technical Analysis
Ultralytics YOLOv8 and YOLO11 are licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. Section 13 of AGPL-3.0 specifies:
> *"If you modify the Program, your modified version must prominently offer all users interacting with it remotely through a computer network... a copy of the Corresponding Source of your version."*

For commercial deployments where CAMserv is distributed as a proprietary, closed-source appliance or SaaS solution, operating under AGPL-3.0 creates severe legal copyleft liabilities.

#### Dual-Pathway Solution Architecture
Documented in `docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md` and implemented in `src/camserv/inference/models.py`:

```
+---------------------------------------------------------------------------------+
|                        CAMserv Neural Inference Engine                          |
+---------------------------------------+-----------------------------------------+
                                        |
                 +----------------------+----------------------+
                 |                                             |
                 v                                             v
     [Strategy A: Enterprise License]              [Strategy B: Permissive Apache-2.0]
     - Ultralytics Commercial License              - Baidu RT-DETR (Real-Time Transformer)
     - YOLOv8 / YOLO11 Architectures               - Meituan YOLOv6 Architectures
     - Closed-Source Appliance Distribution        - Zero Licensing Cost / Zero Copyleft
     - Full Official Support SLA                   - 100% Commercial Freedom
```

1. **Pluggable Architecture Enums:**
   ```python
   class ModelBackendType(str, Enum):
       ULTRALYTICS_AGPL = "ultralytics_agpl"
       PERMISSIVE_ONNX_APACHE = "permissive_onnx_apache"
       CUSTOM_PROPRIETARY = "custom_proprietary"

   class ModelArchitecture(str, Enum):
       YOLOV8_DET = "yolov8_det"
       YOLOV8_SEG = "yolov8_seg"
       YOLOV8_POSE = "yolov8_pose"
       YOLOV11_DET = "yolov11_det"
       YOLOV11_SEG = "yolov11_seg"
       RT_DETR = "rt_detr"       # Apache-2.0 permissive
       YOLOV6 = "yolov6"         # Apache-2.0 permissive
       CUSTOM = "custom"
   ```

2. **Decision Governance:**
   Formal corporate deployment mandates an authorized executive decision between Strategy A (commercial licensing procurement) and Strategy B (zero-cost Apache-2.0 compilation). Neither requires architectural redesign because `ModelRegistry` abstracts the underlying model execution provider.

---

### 3.3 SEC-03: Persistent Forensic Manifest Storage in `SQLiteStore`

#### Defect Analysis
While Phase 2 generated cryptographic `PrivacyEvidenceManifest` and `EnhancementManifest` structures linking pristine raw frames to masked derivatives, these manifests existed purely in transient memory or logging streams. Without indexed relational storage, retrospective judicial discovery and cryptographic chain-of-custody verification were impossible across application restarts.

#### Database Architecture & Implementation
Extended `src/camserv/storage/sqlite_store.py`:

1. **Relational Table Schemas:**
   ```sql
   CREATE TABLE IF NOT EXISTS privacy_manifests (
       manifest_id TEXT PRIMARY KEY,
       camera_id TEXT NOT NULL,
       frame_id INTEGER NOT NULL,
       original_sha256 TEXT NOT NULL,
       derivative_sha256 TEXT NOT NULL,
       masking_method TEXT NOT NULL,
       regions_count INTEGER NOT NULL,
       fail_closed_active INTEGER NOT NULL,
       timestamp_utc TEXT NOT NULL,
       metadata_json TEXT
   );
   CREATE INDEX IF NOT EXISTS idx_privacy_manifests_cam_ts 
   ON privacy_manifests (camera_id, timestamp_utc);
   CREATE INDEX IF NOT EXISTS idx_privacy_manifests_orig_hash 
   ON privacy_manifests (original_sha256);

   CREATE TABLE IF NOT EXISTS enhancement_manifests (
       manifest_id TEXT PRIMARY KEY,
       camera_id TEXT NOT NULL,
       frame_id INTEGER NOT NULL,
       raw_sha256 TEXT NOT NULL,
       enhanced_sha256 TEXT NOT NULL,
       pipeline_stages TEXT NOT NULL,
       clahe_clip_limit REAL,
       timestamp_utc TEXT NOT NULL,
       metadata_json TEXT
   );
   CREATE INDEX IF NOT EXISTS idx_enhancement_manifests_cam_ts 
   ON enhancement_manifests (camera_id, timestamp_utc);
   ```

2. **High-Performance CRUD Methods:**
   - `store_privacy_manifest(manifest: PrivacyEvidenceManifest) -> bool`
   - `get_privacy_manifest(manifest_id: str) -> Optional[PrivacyEvidenceManifest]`
   - `get_privacy_manifest_by_original_hash(original_sha256: str) -> Optional[PrivacyEvidenceManifest]`
   - `list_privacy_manifests(camera_id, limit, start_time, end_time) -> List[PrivacyEvidenceManifest]`
   - `store_enhancement_manifest(manifest: EnhancementManifest) -> bool`
   - `get_enhancement_manifest(manifest_id: str) -> Optional[EnhancementManifest]`
   - `list_enhancement_manifests(camera_id, limit) -> List[EnhancementManifest]`
   - `verify_manifest_integrity_record(manifest_id: str) -> Dict[str, Any]`

3. **Verification:**
   Tested in `tests/test_manifest_storage_remediation.py` verifying full roundtrip persistence, compound index queries, original SHA-256 reverse lookup, and database restart survival.

---

### 3.4 SEC-04: Ground Contact Position for Restricted-Zone Analysis

#### Defect Analysis
In 2D camera projections, downward-angled surveillance cameras project a person's upper torso and head into background space. If an individual walks *outside* a perimeter fence or restricted zone boundary, their torso centroid $(c_x, c_y)$ frequently projects into the polygon, generating false-positive security alerts.

#### Geometric Formulation & Implementation
Implemented in `src/camserv/events/behavioral_engine.py`:

```
               [Head / Face]
                     |
                +----+----+
                |  Torso  |  <--- Centroid (cx, cy) [Projected Inside Zone: FALSE ALARM]
                +----+----+
                     |
                +----+----+
                |  Legs   |
                +----+----+
                 /        \
               [Feet Contact] <--- ( (x1+x2)/2, y2 ) [Actual Physical Location: SAFE]
═══════════════════════════════════════════════ Ground Plane ══════════════════
                                              [Restricted Zone Boundary]
```

1. **Mathematical Definition:**
   For an upright human detection with bounding box $[x_1, y_1, x_2, y_2]$:
   $$x_{\text{ground}} = \frac{x_1 + x_2}{2.0}, \quad y_{\text{ground}} = y_2$$

2. **Adaptive Posture Support:**
   ```python
   class SpatialAnchorStrategy(str, Enum):
       FEET_GROUND_CONTACT = "feet_ground_contact"
       CENTROID = "centroid"
       BOTTOM_CENTER = "bottom_center"
       ADAPTIVE = "adaptive"
   ```
   If a person is crouching or lying down (aspect ratio $\frac{x_2 - x_1}{y_2 - y_1} > 1.2$), the adaptive strategy smoothly transitions to the bounding box base center to ensure accurate geo-fencing.

3. **Behavioral Engine Integration:**
   Updated `evaluate_restricted_area` and `evaluate_perimeter_loitering` to evaluate ground contact points. Verified by `tests/test_ground_contact_remediation.py`.

---

### 3.5 GAP-01: Regulatory Compliance Claims Accuracy

#### Defect Analysis
Documentation previously claimed "GDPR & EU AI Act Conformity". Under European Union law, software cannot autonomously declare statutory conformity: compliance is an organizational responsibility requiring formal impact assessments, record-keeping, and operational safeguards.

#### Documentation Refactoring
1. **Badges and Titles Updated:**
   - Badge in `README.md` updated to: `Privacy Safeguards - GDPR & AI Act Aligned`.
   - Title in `docs/PHASE_2_PRIVACY_AND_EVIDENCE_DESIGN.md` updated to: `Technical Architectural Safeguards Aligning with GDPR (EU 2016/679) and Applicable EU AI Act Requirements`.

2. **Mandatory Organizational Prerequisites Added (Section 4):**
   - **GDPR Article 35 (DPIA):** High-risk video surveillance necessitates a Data Protection Impact Assessment prior to activation.
   - **GDPR Article 30 (RoPA):** Controllers must register data categories, purposes, and zero third-country transfer guarantees in their official RoPA.
   - **GDPR Article 5(1)(e) (Storage Limitation):** 24-72 hour automated retention purging, unless an explicit forensic judicial hold is active.
   - **GDPR Articles 13 & 14 (Statutory Signage):** Mandatory physical warning signs identifying the controller, DPO, surveillance purpose, and data subject rights.
   - **EU AI Act Article 14 (Human Oversight):** High-severity events are probabilistic hypotheses (`is_prediction = True`); automated consequential actions without human review are strictly prohibited.

---

## 4. Complete Findings Status Summary

| Finding | Pre-Remediation Status | Post-Remediation Status | Resolution Detail |
| :--- | :--- | :--- | :--- |
| **SEC-01** | OPEN | **CLOSED** | Fail-closed enforcer integrated across all egress paths; blackout on failure. |
| **SEC-02** | OPEN | **CLOSED** | Enterprise vs Apache-2.0 commercial strategy documented; backend enum implemented. |
| **SEC-03** | OPEN | **CLOSED** | `privacy_manifests` and `enhancement_manifests` tables and CRUD methods created in SQLite. |
| **SEC-04** | OPEN | **CLOSED** | Ground contact position anchor point implemented in behavioral engine. |
| **SEC-05** | OPEN | **SCHEDULED (Phase 3)** | Process-isolated inference worker supervisor scheduled for multi-GPU appliance phase. |
| **SEC-06** | OPEN | **CLOSED** | Starlette test client deprecation warnings cleanly filtered in test runner. |
| **GAP-01** | UNVERIFIED CLAIM | **CLOSED** | Claims reframed as technical architectural safeguards; organizational DPIA/RoPA documented. |
| **GAP-02** | TEST LIMITATION | **SCHEDULED (Phase 3)** | Physical multi-camera testing on physical IP switch scheduled for Phase 3. |
| **GAP-03** | ENVIRONMENT GAP | **SCHEDULED (Phase 3)** | POSIX CI matrix on Ubuntu LTS scheduled for Phase 3. |
| **GAP-04** | TECHNICAL DEBT | **CLOSED** | SQLite tables implemented and verified. |
| **GAP-05** | ARCHITECTURAL DEBT | **CLOSED** | Pipeline fail-closed enforcement implemented and verified. |
| **GAP-06** | ANALYTICAL PRECISION | **CLOSED** | Ground contact anchor implemented and verified. |
| **GAP-07** | LEGAL PREREQUISITE | **CLOSED** | Model license register updated with commercial decision requirements. |
| **GAP-08** | PACKAGING GAP | **CLOSED** | `openvino` and `directml` extra dependencies added to `pyproject.toml`. |
| **GAP-09** | TEST GAP | **SCHEDULED (Phase 3)** | 72-hour sustained soak test scheduled for Phase 3. |

---

## 5. Conclusion & Verification

All 4 mandatory security findings (`SEC-01`, `SEC-02`, `SEC-03`, `SEC-04`) and regulatory gap `GAP-01` have been completely resolved, verified with 12 new automated tests, and documented in production architecture records. Zero regressions occurred across the 180 baseline tests. The system is formally ready for Phase 3 authorization under the condition that commercial deployment licensing is formally authorized.
