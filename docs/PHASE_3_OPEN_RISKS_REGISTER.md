# CAMserv — Phase 3 Open Risks & Technical Debt Register

**Document ID:** RISK-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 3 Entry Governance (Stage 0)  
**Date:** November 15, 2026  
**Auditor / Authority:** Chief Software Architect & Cybersecurity Architect  

---

## 1. Overview & Risk Management Methodology

Phase 2 was accepted with remediation (`PHASE_2_ACCEPTED_WITH_REMEDIATION`). The Phase 2 remediation directive successfully implemented code and documentation closures for `SEC-01` through `SEC-04` and `GAP-01`.

However, transitioning to distributed enterprise infrastructure, dedicated appliance engineering, and commercial software packaging introduces new operational, legal, and hardware dependencies.

This register formally tracks all open risks, technical debts, commercial dependencies, and architectural constraints. **No open risk may be silently marked as closed without demonstrable technical proof or authorized legal sign-off.**

---

## 2. Master Risk & Findings Status Matrix

| ID | Category | Severity | Current Status | Description & Operational Boundary | Remediation Milestone |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | Privacy & Pipeline | **HIGH** | **REMEDIATED (CODE) / ACTIVE GOVERNANCE** | Centralized fail-closed privacy enforcer implemented (`CentralizedPrivacyEnforcer`). Boundary: Remote streams to CAMserv Central must strictly enforce masked derivatives; raw frame egress requires local quorum. | Stage 4 (Distributed Security) |
| **SEC-02** | Supply Chain / IP | **HIGH** | **DECISION PENDING / SAFE BOUNDARY ACTIVE** | Ultralytics YOLOv8/11 weights licensed under AGPL-3.0. Safe boundary implemented: Pluggable `ModelBackendType` supports Apache-2.0 RT-DETR and YOLOv6. Commercial closed-source appliance deployment requires executive procurement of Ultralytics Enterprise License or default to Apache-2.0. | Stage 10 (Commercial Packaging) |
| **SEC-03** | Storage & Forensics | **MEDIUM** | **REMEDIATED (CODE) / SCALING ACTIVE** | `privacy_manifests` and `enhancement_manifests` tables persistent in SQLite with WAL mode. Boundary: High-velocity continuous 24/7 logging requires automated index maintenance and retention pruning in multi-camera appliances. | Stage 6 (Storage Infrastructure) |
| **SEC-04** | Behavioral Precision | **MEDIUM** | **REMEDIATED (CODE) / CALIBRATION ACTIVE** | Ground contact point $((x_1+x_2)/2, y_2)$ eliminates perspective false alarms for upright persons. Boundary: Multi-level complex facilities require camera-specific homography calibration matrices to map 2D image coordinates to physical site blueprints. | Stage 1 & Stage 8 |
| **SEC-05** | Inference Isolation | **LOW / ARCHITECTURAL** | **OPEN / SCHEDULED FOR PHASE 3** | `InferenceEngine` utilizes Python `threading.Thread`. A deep native C++ crash in ONNX Runtime or NVIDIA CUDA driver terminates the server process. Boundary: Wrap inference in dedicated isolated worker processes with shared-memory tensor IPC. | Stage 1 (Appliance Architecture) |
| **SEC-06** | Dependency Hygiene | **INFORMATIONAL** | **CLOSED** | Starlette `TestClient` deprecation warnings cleanly filtered in test configuration without masking production exceptions. | Completed |
| **GAP-01** | Regulatory Claims | **HIGH (Compliance)** | **REMEDIATED (DOCS) / CLIENT BOUNDARY** | Reframed from "Conformity" to "Technical Safeguards Aligning with GDPR/EU AI Act". Boundary: Technical features do not replace statutory controller duties. Appliance admin console must embed DPIA, RoPA, and statutory signage setup checklists. | Stage 5 & Stage 8 |
| **GAP-02** | Hardware Validation | **MEDIUM** | **OPEN / SCHEDULED FOR PHASE 3** | Scalability benchmarks across 1, 4, 8, 16 streams are currently verified using simulated frame generators. Boundary: Perform empirical validation with physical ONVIF/RTSP cameras across a gigabit switch before appliance shipping. | Stage 1 (Appliance Gate) |
| **GAP-03** | Operating System Scope | **MEDIUM** | **OPEN / SCHEDULED FOR PHASE 3** | Regression test suite executed on Windows 11 Enterprise (win32). Linux POSIX execution unverified in current local session. Boundary: Integrate GitHub Actions matrix on `ubuntu-22.04` and `ubuntu-24.04` runners. | Stage 2 (Deployment Environment) |
| **GAP-04** | Database Schemas | **MEDIUM** | **CLOSED** | `privacy_manifests` and `enhancement_manifests` implemented in `src/camserv/storage/sqlite_store.py` and verified by unit tests. | Completed |
| **GAP-05** | Pipeline Decoupling | **HIGH** | **CLOSED** | Legacy optional privacy flag refactored; fail-closed enforcer is mandatory on all video paths. | Completed |
| **GAP-06** | Perspective Centroid | **MEDIUM** | **CLOSED** | Bottom-center ground contact points implemented in `behavioral_engine.py` and verified by unit tests. | Completed |
| **GAP-07** | Commercial Model Policy | **HIGH (Legal)** | **CLOSED** | Dual-pathway strategy formulated in `PHASE_2_MODEL_AND_LICENSE_REGISTER.md`. | Completed |
| **GAP-08** | Packaging Extras | **LOW** | **CLOSED** | Added `openvino` and `directml` extra dependency definitions in `pyproject.toml`. | Completed |
| **GAP-09** | Endurance Soak Testing | **MEDIUM** | **OPEN / SCHEDULED FOR PHASE 3** | Absence of 72-hour continuous multi-stream soak test under sustained memory leak profiling. Boundary: Implement long-running soak test script in Stage 9. | Stage 9 (Reliability Engineering) |

---

## 3. Detailed Risk Characterization & Safe Implementation Boundaries

### 3.1 Risk R-01: Commercial Distribution Under AGPL-3.0 (SEC-02 / GAP-07)
* **Risk Nature:** Legal / Commercial Copyleft Liability.
* **Impact:** Potential requirement to open-source proprietary appliance management software if distributed with AGPL-3.0 YOLOv8/11 weights.
* **Safe Implementation Boundary:**
  1. **Strict Default Setting:** The default appliance configuration must compile and load **Permissive Apache-2.0 models** (Baidu RT-DETR and Meituan YOLOv6) for object detection and instance segmentation.
  2. **Commercial Key Injection:** Support for Ultralytics YOLOv8/11 will be treated as an enterprise pluggable module requiring an explicit customer-provided commercial enterprise license key.
  3. **No Closed-Source Appliance Distribution with AGPL Weights:** CAMserv AI Appliances will ship exclusively with Apache-2.0 weights unless customer signs an enterprise licensing agreement.

### 3.2 Risk R-02: Native C++ Inference Crash Propagation (SEC-05)
* **Risk Nature:** Process Stability / Reliability.
* **Impact:** Deep GPU memory faults or driver panics in ONNX Runtime / CUDA cause unhandled process termination, dropping all camera streams.
* **Safe Implementation Boundary:**
  1. Build `InferenceWorkerSupervisor` in Stage 1, mirroring the proven `CameraWorkerSupervisor` from Phase 1.
  2. Run inference in an independent OS child process communicating via shared memory rings.
  3. If the inference worker crashes, the supervisor restarts it within $< 500\text{ms}$ while the camera ingestion workers continue buffering raw video into RAM.

### 3.3 Risk R-03: Centralized Privacy Leakage Across Distributed WAN (SEC-01)
* **Risk Nature:** Privacy Violation / GDPR Art. 25 Breach.
* **Impact:** Misconfigured central management could stream raw unmasked frames over public networks or to unauthorized remote viewers.
* **Safe Implementation Boundary:**
  1. In CAMserv Central communication protocols (Stage 4), edge appliances are **cryptographically barred** from transmitting pristine raw video over WAN connections.
  2. Remote live previews receive **only derivative masked frames** signed with the edge appliance's private key.
  3. Unmasked evidence export requires physical on-premise dual-key quorum authorization on the local appliance itself.

### 3.4 Risk R-04: Database Migration Failure During Appliance OTA Updates
* **Risk Nature:** Data Loss / Service Interruption.
* **Impact:** Schema migrations during automatic over-the-air (OTA) updates corrupt SQLite database, resulting in lost forensic records.
* **Safe Implementation Boundary:**
  1. Implement transactional database migration scripts with pre-migration atomic SQLite backups (`.backup` API).
  2. If a migration step fails, automatically roll back the database file and restore the previous application release.

---

## 4. Phase 3 Risk Acceptance Gates

To advance through Phase 3 stages, each stage must verify compliance against this risk register:
1. **Appliance Gate (Stage 1):** Capability profiles must not assume a physical GPU is present.
2. **OS Deployment Gate (Stage 2):** Linux deployment must never touch the host developer's personal bootloader or OS.
3. **Central Management Gate (Stage 3):** Central must reject any unregistered or untrusted node attempting enrollment.
4. **Distributed Security Gate (Stage 4):** Mutual TLS and cryptographic message integrity must be mathematically verified.
5. **Storage Gate (Stage 6):** Original evidence immutability and manifest transaction survival must be proven across simulated power-loss events.
6. **Commercial Gate (Stage 10):** A complete Software Bill of Materials (SBOM) and licensing audit must confirm zero copyleft conflicts.
