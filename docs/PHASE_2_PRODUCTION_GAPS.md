# CAMserv — Phase 2 Production Gaps & Technical Debt Catalog
**Document ID:** GAP-CATALOG-2026-P2  
**Audit Standard:** Commercial Production Readiness & Enterprise Assurance  
**Assessment Date:** November 14, 2026  

---

## 1. Overview & Gap Taxonomy

This catalog records all technical debt, architectural gaps, unverified claims, and operational limitations identified during the Phase 2 Independent Acceptance Audit. Each gap is classified with an urgency rating and actionable remediation path.

---

## 2. Production Gaps Matrix

| Gap ID | Category | Gap Description | Current Status | Remediation Implemented | Verification Reference |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GAP-01** | Regulatory Claims | Documentation asserts "GDPR & EU AI Act Conformity" based solely on technical code implementations. | **RESOLVED / REMEDIATED** | Documentation updated across README.md and PHASE_2_PRIVACY_AND_EVIDENCE_DESIGN.md Section 4; explicitly details organizational prerequisites (DPIA, RoPA, retention limits, DPO, signage, and human oversight). | `docs/PHASE_2_PRIVACY_AND_EVIDENCE_DESIGN.md` |
| **GAP-02** | Hardware Scope | Scalability benchmarks across 1, 4, 8, 16 streams are entirely SIMULATED using synthetic frame generators. | **SCHEDULED FOR PHASE 3** | Conduct empirical hardware benchmarks with physical ONVIF/RTSP IP cameras across a dedicated gigabit network switch. | Phase 3 Roadmap |
| **GAP-03** | OS Validation | Full 180-test suite executed exclusively on Windows 11 Enterprise (win32). Linux POSIX execution is unverified in this session. | **SCHEDULED FOR PHASE 3** | Configure GitHub Actions CI matrix to execute full regression suite on `ubuntu-22.04` and `ubuntu-24.04` runners. | CI Integration Plan |
| **GAP-04** | Database Schema | `PrivacyEvidenceManifest` and `EnhancementManifest` lack persistent database tables in `SQLiteStore`. | **RESOLVED / REMEDIATED** | Created `privacy_manifests` and `enhancement_manifests` tables in `sqlite_store.py` with compound indexes on `(camera_id, timestamp_utc)` and full CRUD methods. | `tests/test_manifest_storage_remediation.py` |
| **GAP-05** | Pipeline Decoupling | `PipelineEngine` retains legacy optional `PrivacyFilter` rather than enforcing `FailClosedPrivacyPipeline`. | **RESOLVED / REMEDIATED** | Integrated `CentralizedPrivacyEnforcer` and fail-closed mandatory blackout gating in `engine.py`. Prohibits disabling privacy in production profile. | `tests/test_privacy_remediation.py` |
| **GAP-06** | Perspective Distortion | Behavioral engine polygon intrusion checks torso centroid `(cx, cy)` rather than ground foot position `(cx, y2)`. | **RESOLVED / REMEDIATED** | Implemented `SpatialAnchorStrategy.FEET_GROUND_CONTACT` in `behavioral_engine.py` anchoring person tracks at feet contact point. | `tests/test_ground_contact_remediation.py` |
| **GAP-07** | Licensing / Supply Chain| AGPL-3.0 licensing of YOLOv8/11 weights requires commercial license for proprietary distribution. | **RESOLVED / REMEDIATED** | Added comprehensive commercial licensing advisory and Apache-2.0 fallback model specifications (RT-DETR, YOLOv6) in `docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md` and `src/camserv/inference/models.py`. | `docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md` |
| **GAP-08** | Packaging Extras | `pyproject.toml` lacks explicit `[project.optional-dependencies]` for `onnxruntime-gpu`, `openvino`, and `directml`. | **RESOLVED / REMEDIATED** | Added explicit `openvino` and `directml` extra dependency sections in `pyproject.toml`. | `pyproject.toml` |
| **GAP-09** | Endurance Testing | No 72-hour sustained multi-stream endurance/soak test under continuous memory leak profiling. | **SCHEDULED FOR PHASE 3** | Author long-running soak test script profiling RSS memory growth over 100,000 continuous frames. | Phase 3 Verification |

---

## 3. Remediation Status Summary

1. **Pre-Phase 3 Security & Compliance Remediations (Completed):**
   - Corrected regulatory compliance terminology and detailed organizational prerequisites (GAP-01).
   - Expanded `SQLiteStore` schema to persist and index forensic privacy & enhancement manifests (GAP-04).
   - Integrated fail-closed privacy enforcement into `PipelineEngine` with production profile protection (GAP-05).
   - Replaced centroid containment with feet ground contact anchor points in behavioral engine (GAP-06).
   - Formulated dual-pathway commercial licensing strategy and Apache-2.0 model abstraction (GAP-07).
   - Enriched `pyproject.toml` with `openvino` and `directml` hardware acceleration extras (GAP-08).

2. **Phase 3 Field & Physical Scaling Scope:**
   - Execute physical IP camera benchmarks with live network cameras (GAP-02).
   - Linux POSIX CI automation on Ubuntu LTS runners (GAP-03).
   - 72-hour sustained multi-stream soak testing (GAP-09).
