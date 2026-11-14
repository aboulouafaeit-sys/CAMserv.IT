# CAMserv — Phase 2 Security & Privacy Findings Register
**Audit Standard:** High-Assurance Edge Security, Zero-Trust Architecture, GDPR Privacy Safeguards  
**Assessment Date:** November 14, 2026  
**Auditor:** Independent Cybersecurity & Digital Forensics Engineering Team  

---

## 1. Security Findings Summary

| Finding ID | Severity | Subsystem | Description | Status |
| :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | **HIGH** | Pipeline Orchestration | Legacy `PipelineEngine` treats privacy filtering as optional; bypass allows unmasked raw frames to reach storage. | **OPEN** |
| **SEC-02** | **HIGH** | Software Supply Chain | Ultralytics YOLOv8/11 AGPL-3.0 copyleft obligations pose legal and network distribution risks for commercial deployments. | **OPEN** |
| **SEC-03** | **MEDIUM** | Evidence Storage | `PrivacyEvidenceManifest` and `EnhancementManifest` exist only in transient memory; missing SQLite table prevents retrospective legal discovery. | **OPEN** |
| **SEC-04** | **MEDIUM** | Behavioral Analytics | Polygon containment in `BehavioralEngine` tests torso centroid `(cx, cy)` rather than ground foot position `(cx, y2)`, risking perspective false alarms. | **OPEN** |
| **SEC-05** | **LOW** | Inference Concurrency | `InferenceEngine` utilizes Python `threading.Thread` rather than process isolation; native C++ ONNX runtime crash would terminate entire server. | **OPEN** |
| **SEC-06** | **INFORMATIONAL** | Dependency Health | Starlette `TestClient` emits deprecation warning regarding legacy httpx transport bindings. | **OPEN** |

---

## 2. Detailed Technical Findings

### SEC-01: Legacy PipelineEngine Decoupled from Fail-Closed Privacy Pipeline
* **Severity:** **HIGH**
* **Location:** `src/camserv/pipeline/engine.py` (lines 568-572)
* **Vulnerability Analysis:**  
  In Phase 2, `FailClosedPrivacyPipeline` was introduced to guarantee that any detection failure causes an immediate full-frame blackout overlay (`FAIL_CLOSED_FULL_SOLID`).  
  However, the main asynchronous orchestrator `PipelineEngine` still contains:
  ```python
  processed_frame = frame
  if self.config.enable_privacy_filtering and self.privacy_filter is not None:
      processed_frame = await self.privacy_filter.apply(frame, detections)
  ```
  If `enable_privacy_filtering` is toggled `False`, or if `privacy_filter` is not passed to the constructor, the engine passes unmasked raw frames into `StoragePayload`.
* **Remediation:**  
  Refactor `PipelineEngine` to mandate `FailClosedPrivacyPipeline`. The configuration must fail-closed: if the privacy pipeline is absent or disabled in a production profile, the pipeline must reject frame egress to non-vault storage.

---

### SEC-02: Ultralytics YOLOv8/11 AGPL-3.0 Copyleft Implications
* **Severity:** **HIGH (Legal / Commercial)**
* **Location:** `docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md`
* **Vulnerability Analysis:**  
  The official weights and codebase for YOLOv8 and YOLO11 are licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). AGPL-3.0 contains a strict "Remote Network Interaction" clause (Section 13): if CAMserv is operated as a networked service or commercial proprietary appliance, licensees may be legally obligated to disclose the entire proprietary application source code under AGPL-3.0.
* **Remediation:**  
  1. For closed-source commercial deployments, CAMserv must advise customers to obtain an **Ultralytics Commercial Enterprise License**.
  2. Implement an alternative model provider pathway using **Apache-2.0 or MIT licensed architectures** (e.g., RT-DETR, YOLOv6, or custom-trained edge models).

---

### SEC-03: Absence of Persistent `privacy_manifests` Table in SQLite Store
* **Severity:** **MEDIUM**
* **Location:** `src/camserv/storage/sqlite_store.py`
* **Vulnerability Analysis:**  
  The `PrivacyEvidenceManifest` and `EnhancementManifest` dataclasses generate valid cryptographic SHA-256 bindings between pristine raw evidence and derivative files. However, `SQLiteStore` does not define an explicit schema for persisting and indexing these manifests. In the event of a courtroom subpoena or legal investigation, auditors cannot retrospectively query the manifest catalog by `camera_id` or `timestamp` from the database.
* **Remediation:**  
  Create tables `privacy_manifests` and `enhancement_manifests` in `sqlite_store.py` with indexed columns for `manifest_id`, `camera_id`, `frame_id`, `original_sha256`, `derivative_sha256`, and `timestamp_utc`.

---

### SEC-04: Perspective Bounding Box Centroid False-Alarm Risk
* **Severity:** **MEDIUM**
* **Location:** `src/camserv/events/behavioral_engine.py` (lines 124-126)
* **Vulnerability Analysis:**  
  In `evaluate_restricted_area`, `BehavioralEngine` tests whether `(cx, cy)` falls inside the restricted zone polygon. In angled surveillance cameras, a person walking outside a perimeter fence whose upper torso leans or projects into the camera's line-of-sight will have their centroid `(cx, cy)` fall inside the 2D polygon, generating false-positive alarms.
* **Remediation:**  
  Anchor polygon geo-fence tests to the bottom-center ground contact coordinates:
  ```python
  ground_x = (track.bbox.x1 + track.bbox.x2) / 2.0
  ground_y = track.bbox.y2
  if self._point_in_polygon((ground_x, ground_y), restricted_polygon): ...
  ```

---

### SEC-05: In-Process Threaded Inference vs Crash Containment
* **Severity:** **LOW**
* **Location:** `src/camserv/inference/engine.py`
* **Vulnerability Analysis:**  
  While video ingestion workers in `src/camserv/acquisition/supervisor.py` run in isolated OS processes, `InferenceEngine` utilizes `threading.Thread`. If a deep native C++ crash occurs inside ONNX Runtime or NVIDIA CUDA driver libraries (e.g., GPU memory corruption or segmentation fault), it will terminate the entire parent Python process, interrupting all active camera streams.
* **Remediation:**  
  In Phase 3 enterprise multi-GPU clustering, wrap `InferenceEngine` in a supervised worker process architecture matching `CameraWorkerSupervisor`.
