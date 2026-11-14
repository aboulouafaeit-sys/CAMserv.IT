# CAMserv — Phase 2 Production Gaps & Technical Debt Catalog
**Document ID:** GAP-CATALOG-2026-P2  
**Audit Standard:** Commercial Production Readiness & Enterprise Assurance  
**Assessment Date:** November 14, 2026  

---

## 1. Overview & Gap Taxonomy

This catalog records all technical debt, architectural gaps, unverified claims, and operational limitations identified during the Phase 2 Independent Acceptance Audit. Each gap is classified with an urgency rating and actionable remediation path.

---

## 2. Production Gaps Matrix

| Gap ID | Category | Gap Description | Current Status | Remediation Required | Target Milestone |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GAP-01** | Regulatory Claims | Documentation asserts "GDPR & EU AI Act Conformity" based solely on technical code implementations. | **UNVERIFIED CLAIM** | Refine wording to "Technical Privacy Safeguards Aligning with GDPR/EU AI Act"; disclaim formal legal compliance without organizational DPIA, RoPA, and DPO oversight. | Pre-Phase 3 |
| **GAP-02** | Hardware Scope | Scalability benchmarks across 1, 4, 8, 16 streams are entirely SIMULATED using synthetic frame generators. | **TEST LIMITATION** | Conduct empirical hardware benchmarks with physical ONVIF/RTSP IP cameras across a dedicated gigabit network switch. | Phase 3 |
| **GAP-03** | OS Validation | Full 180-test suite executed exclusively on Windows 11 Enterprise (win32). Linux POSIX execution is unverified in this session. | **ENVIRONMENT GAP** | Configure GitHub Actions CI matrix to execute full regression suite on `ubuntu-22.04` and `ubuntu-24.04` runners. | Pre-Phase 3 |
| **GAP-04** | Database Schema | `PrivacyEvidenceManifest` and `EnhancementManifest` lack persistent database tables in `SQLiteStore`. | **TECHNICAL DEBT** | Implement `privacy_manifests` and `enhancement_manifests` tables with compound indexes on `camera_id` and `timestamp_utc`. | Phase 3A |
| **GAP-05** | Pipeline Decoupling | `PipelineEngine` retains legacy optional `PrivacyFilter` rather than enforcing `FailClosedPrivacyPipeline`. | **ARCHITECTURAL DEBT** | Refactor `camserv.pipeline.engine` to mandate `FailClosedPrivacyPipeline` as a non-bypassable stage. | Phase 3A |
| **GAP-06** | Perspective Distortion | Behavioral engine polygon intrusion checks torso centroid `(cx, cy)` rather than ground foot position `(cx, y2)`. | **ANALYTICAL PRECISION** | Modify `evaluate_restricted_area` to anchor inclusion tests to the bottom-center of the bounding box. | Pre-Phase 3 |
| **GAP-07** | Licensing / Supply Chain| AGPL-3.0 licensing of YOLOv8/11 weights requires commercial license for proprietary distribution. | **LEGAL PREREQUISITE** | Add commercial licensing advisory to documentation and provide Apache-2.0 model fallback configuration. | Pre-Phase 3 |
| **GAP-08** | Packaging Extras | `pyproject.toml` lacks explicit `[project.optional-dependencies]` for `onnxruntime-gpu`, `openvino`, and `directml`. | **PACKAGING GAP** | Add optional extras `gpu`, `openvino`, `tensorrt` to `pyproject.toml`. | Pre-Phase 3 |
| **GAP-09** | Endurance Testing | No 72-hour sustained multi-stream endurance/soak test under continuous memory leak profiling. | **TEST GAP** | Author long-running soak test script profiling RSS memory growth over 100,000 continuous frames. | Phase 3 |

---

## 3. Prioritized Remediation Roadmap

1. **Immediate (Pre-Phase 3 Prerequisite):**
   - Correct regulatory compliance claims in documentation (GAP-01).
   - Add model licensing commercial advisory (GAP-07).
   - Update bounding box ground anchor points in behavioral engine (GAP-06).
   - Add optional GPU dependencies to `pyproject.toml` (GAP-08).
2. **Phase 3 Milestone Integration:**
   - Integrate `FailClosedPrivacyPipeline` directly into `PipelineEngine` (GAP-05).
   - Expand `SQLiteStore` schema to persist manifests (GAP-04).
   - Execute physical IP camera benchmarks (GAP-02).
   - Execute 72-hour multi-stream soak testing (GAP-09).
