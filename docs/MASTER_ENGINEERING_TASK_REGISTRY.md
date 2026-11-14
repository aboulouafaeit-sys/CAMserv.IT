# CAMserv Master Engineering Task Registry
**Document ID:** TASK-REG-2026-001  
**Author:** Principal Engineering Director & Chief Software Architect  
**Date:** November 14, 2026  
**Status:** ACTIVE IMPLEMENTATION BLUEPRINT  

---

## 1. Verified Completed Tasks (Milestones 1 & 2 Baseline)

| Task ID | Agent Role | Subsystem / Objective | Target Files | Dependencies | Status | Verification & Evidence |
|---|---|---|---|---|---|---|
| **TSK-ARC-01** | Chief Architect | Baseline recovery point & Git repository audit | `docs/governance/`, `README.md` | None | **VERIFIED** | Clean git working tree; tag `pre-v2-adaptation` created. |
| **TSK-BRD-01** | Creative Director | 3 Creative Brand Directions & Concept Rationale | `docs/brand/BRAND_CONCEPTS.md` | None | **VERIFIED** | Conceptual identity & visual philosophy approved. |
| **TSK-BRD-02** | Creative Director | Production Vector Logo Suite Baseline | `docs/brand/BRAND_GUIDELINES.md` | TSK-BRD-01 | **VERIFIED** | Color tokens, typography, and logo clearance rules. |
| **TSK-BRD-03** | AI Visual Specialist | Official Illustrated Logo, Multi-Size PNG Suite, 14 Screen Captures | `assets/branding/`, `docs/screenshots/` | TSK-BRD-02 | **VERIFIED** | 100% transparent PNGs; zero bounding box on GitHub. |
| **TSK-HWA-01** | Hardware Eng | Cross-Platform Hardware Probe (CPU, RAM, GPU, VRAM) | `src/camserv/platform/hardware.py` | None | **VERIFIED** | Verified in `tests/test_hardware.py`. |
| **TSK-HWA-02** | Hardware Eng | 4-Tier Adaptive Operating Profiles (`TIER_1` to `TIER_4`) | `src/camserv/platform/tiers.py` | TSK-HWA-01 | **VERIFIED** | Verified in `tests/test_hardware.py`. |
| **TSK-HWA-03** | Video Pipeline | Adaptive Resource Manager & Pressure Shedding Watchdog | `src/camserv/platform/adaptive_manager.py` | TSK-HWA-02 | **VERIFIED** | Verified in `tests/test_adaptive.py`. |
| **TSK-NVR-01** | NVR Integration | Camera & NVR Compatibility Matrix & Manufacturer Topologies | `docs/NVR_COMPATIBILITY_MATRIX.md` | None | **VERIFIED** | Hikvision, Dahua, Axis, Hanwha RTSP profiles. |
| **TSK-DSN-01** | UI/UX Designer | 14-Screen Information Architecture & Design System Tokens | `docs/design/SCREEN_SPECS.md` | TSK-BRD-02 | **VERIFIED** | WCAG 2.1 AA dual-theme specifications. |
| **TSK-DSN-02** | Frontend Eng | Dual-Theme Web Console Implementation (14 Interactive Screens) | `src/camserv/web/` | TSK-DSN-01 | **VERIFIED** | 14 screens functional with live HUD telemetry. |
| **TSK-AIE-01** | AI Event Intel | Multi-Frame Temporal Analytics & False Alarm Filter | `src/camserv/events/temporal.py` | None | **VERIFIED** | Verified in `tests/test_temporal.py`. |
| **TSK-SEC-01** | Security Eng | Forensic Chain-of-Custody, Asymmetric Signatures & Privacy | `src/camserv/storage/forensics.py` | None | **VERIFIED** | Verified in `tests/test_forensics.py`. |
| **TSK-HUD-01** | Vision Engineer | Cinematic Visual HUD & Contouring (Polygons, 3D Rings, Cards) | `src/camserv/inference/hud_renderer.py` | None | **VERIFIED** | Verified in `tests/test_hud_renderer.py`. |
| **TSK-ISP-01** | Video Pipeline | Software ISP Stream Profiler (LAB CLAHE & Denoising) | `src/camserv/acquisition/isp.py` | None | **VERIFIED** | Verified in `tests/test_isp.py`. |
| **TSK-THR-01** | AI Event Intel | Zero-API Threat Scoring, Pose Kinematics & Dual Narratives | `src/camserv/events/threat_engine.py` | TSK-HUD-01 | **VERIFIED** | Verified in `tests/test_threat_engine.py`. |
| **TSK-VLT-01** | Forensic Storage | Adaptive Retention Vault (15s RAM Pre-Roll, AES-GCM, WORM) | `src/camserv/storage/adaptive_vault.py` | None | **VERIFIED** | Verified in `tests/test_adaptive_vault.py`. |
| **TSK-QAR-01** | Independent QA | Multi-Layer Test Suite Expansion (136 Baseline Tests) | `tests/` | All | **VERIFIED** | 136/136 automated tests passing in 8.31s. |
| **TSK-P1A-01** | Security Eng | Test Environment Audit Isolation (Condition C1) | `src/camserv/api/app.py`, `tests/conftest.py` | None | **VERIFIED** | Verified in `tests/test_audit_isolation.py`; zero audit log writes during test runs. |
| **TSK-P1A-02** | Security Eng | Persistent Cryptographic KeyManager & Envelope Wrap (Condition C3) | `src/camserv/security/keys.py`, `src/camserv/storage/adaptive_vault.py` | None | **VERIFIED** | Atomic writes (0600), HKDF derivation; verified in `tests/test_key_manager.py`. |
| **TSK-P1B-01** | Video Systems Eng | Video Ingestion Re-Architecture & Supervised Worker Abstraction | `src/camserv/acquisition/supervisor.py`, `src/camserv/acquisition/ingestion_manager.py` | None | **VERIFIED** | Verified in `tests/test_ingestion_supervisor.py`. |
| **TSK-P1C-01** | Shared Memory Eng | Shared Memory Ring Buffer & IPC Overrun Protection | `src/camserv/acquisition/shared_memory.py`, `src/camserv/acquisition/camera.py` | TSK-P1B-01 | **VERIFIED** | Bounded circular slots, drop-oldest overrun, sub-150ms worker crash recovery. |
| **TSK-P1D-01** | Resource Architect | Adaptive Multi-Rate Analytical Scheduler (Condition C4) | `src/camserv/pipeline/adaptive_scheduler.py` | None | **VERIFIED** | 5 FPS baseline, 30 FPS incident burst, 16-cam capacity governor; verified in `tests/test_adaptive_scheduler.py`. |
| **TSK-P1E-01** | Hardware Eng | Hardware Capability Discovery & 5-Tier DiagnosticState Taxonomy | `src/camserv/platform/hardware.py` | None | **VERIFIED** | Standardized DiagnosticState taxonomy, NVDEC/DXVA2/VAAPI probe; verified in `tests/test_hardware_diagnostics.py`. |
| **TSK-P1-QAR** | Independent QA | Phase 1 Comprehensive Regression Acceptance (158 Passing Tests) | `tests/` | All | **VERIFIED** | **158/158 automated tests passing in 10.40s**. |
| **TSK-P2A-01** | AI Infrastructure | Certified ModelRegistry & Cryptographic SHA-256 Verification | `src/camserv/inference/models.py` | None | **VERIFIED** | ModelRegistry with SHA-256 validation, unverified weights rejection; verified in `tests/test_inference_engine.py`. |
| **TSK-P2A-02** | AI Infrastructure | Hardware-Adaptive Inference Engine & Transparent CPU Fallback | `src/camserv/inference/engine.py` | TSK-P2A-01 | **VERIFIED** | Provider hierarchy (TRT/CUDA/CPU), bounded queue, LatencyTracker P50/P95/P99; verified in `tests/test_inference_engine.py`. |
| **TSK-P2B-01** | Computer Vision | Camera-Isolated Multi-Object Tracking Coordinator & Kinematics | `src/camserv/tracking/coordinator.py` | None | **VERIFIED** | Scoped track IDs, TENTATIVE/CONFIRMED/OCCLUDED states, velocity/speed, cross-cam forbidden; verified in `tests/test_object_tracking_phase2.py`. |
| **TSK-P2C-01** | Privacy Eng | Fail-Closed Privacy Pipeline & Cryptographic Evidence Separation | `src/camserv/inference/privacy_pipeline.py` | None | **VERIFIED** | Fail-closed full blackout under error, raw evidence preserved, PrivacyEvidenceManifest; verified in `tests/test_privacy_pipeline.py`. |
| **TSK-P2D-01** | AI Event Intel | Behavioral Scenario Engine & Human-in-the-Loop Review Workflow | `src/camserv/events/behavioral_engine.py` | TSK-P2B-01 | **VERIFIED** | 5 security scenarios, DETECTED->UNDER_REVIEW->CONFIRMED state machine, operator audit; verified in `tests/test_behavioral_engine.py`. |
| **TSK-P2E-01** | Forensic Vision | Non-Destructive Forensic Image Enhancement Pipeline | `src/camserv/acquisition/enhancement.py` | None | **VERIFIED** | LAB CLAHE, dynamic contrast stretch, bilateral denoise, side-by-side comparison; verified in `tests/test_image_enhancement.py`. |
| **TSK-P2F-01** | UI/UX Systems | Live Stream Telemetry HUD & Glassmorphic Operations Interface | `src/camserv/inference/hud_renderer.py` | None | **VERIFIED** | Live stream telemetry cards, 3D ground perspective rings, threat aura hierarchy; verified in `tests/test_hud_segmentation.py`. |
| **TSK-P2-QAR** | Independent QA | Phase 2 Comprehensive Regression Acceptance (180 Passing Tests) | `tests/` | All | **VERIFIED** | **180/180 automated tests passing in 10.62s** (100% pass rate, zero audit log modification). |

---

## 2. Prioritized Roadmap Implementation Registry (P0 to P4)

### Priority P0: Critical Infrastructure, Resilience & Process Isolation
| Task ID | Component | Task Objective | Effort | Assigned Role | Acceptance Criteria |
|---|---|---|---|---|---|
| **TSK-P0-01** | Video Ingestion | Implement dedicated OS worker subprocesses for camera capture with POSIX shared memory ring buffers (`/dev/shm`). | 5 Days | Video Systems Eng | Subprocess SIGKILL recovers in $< 500\text{ms}$; zero GIL contention on 16 streams. |
| **TSK-P0-02** | Hardware Dec | Supervised FFmpeg/NVDEC subprocess pipeline replacing `cv2.VideoCapture` with strict TCP transport. | 4 Days | Video Pipeline Eng | Zero packet drop on lossy networks; NVDEC offload verified on NVIDIA GPU. |
| **TSK-P0-03** | Vault Integrity | OS-level WORM immutable enforcement using Linux `chattr +i` and TPM 2.0 key storage. | 3 Days | Cryptographic Eng | Root user cannot delete or truncate sealed `.vault` archives. |
| **TSK-P0-04** | Concurrency | Bounded spillover memory queue for SQLite transaction locks during burst alert volumes. | 2 Days | Database Architect | Zero lost events under 10,000 concurrent alerts/second burst. |

### Priority P1: Vision Accuracy, Calibration & Tracking
| Task ID | Component | Task Objective | Effort | Assigned Role | Acceptance Criteria |
|---|---|---|---|---|---|
| **TSK-P1-01** | Neural Inference | Native TensorRT FP16/INT8 compilation for YOLOv8n-seg and YOLOv8n-pose. | 4 Days | Computer Vision Eng | Latency $< 5.0\text{ ms}$ per 1080p frame on RTX 3060. |
| **TSK-P1-02** | Tracking Core | Full BoT-SORT integration with Camera Motion Compensation (GMC) for PTZ cameras. | 3 Days | Tracking Specialist | ID switches reduced by $> 40\%$ during camera pan/tilt transitions. |
| **TSK-P1-03** | AI Calibration | Platt temperature scaling and 95% confidence bounds on threat probabilities. | 3 Days | AI Research Scientist | Brier calibration score $< 0.08$; false alarm rejection $> 92\%$. |

### Priority P2: Enterprise Security, Observability & Supply Chain
| Task ID | Component | Task Objective | Effort | Assigned Role | Acceptance Criteria |
|---|---|---|---|---|---|
| **TSK-P2-01** | Observability | Native Prometheus `/metrics` exposition and OpenTelemetry W3C distributed tracing. | 3 Days | SRE / DevOps Lead | Grafana dashboard visualization of stream FPS, latency, and VRAM. |
| **TSK-P2-02** | Supply Chain | CycloneDX / SPDX SBOM automation, `pip-audit` CI gate, and Cosign container signing. | 2 Days | DevSecOps Eng | Zero Critical/High CVEs; verified Cosign cryptographic signature. |
| **TSK-P2-03** | Auth Hardening | Argon2id credential hashing with automated account lockout and IP rate limiting. | 2 Days | Security Architect | OWASP ASVS v4.0.3 Level 2 authentication compliance verified. |

### Priority P3: Enterprise Fleet Clustering & External Integrations
| Task ID | Component | Task Objective | Effort | Assigned Role | Acceptance Criteria |
|---|---|---|---|---|---|
| **TSK-P3-01** | Fleet Control | Multi-node cluster coordination via optional PostgreSQL / TimescaleDB and Redis pub/sub. | 6 Days | Systems Architect | 64-camera multi-server fleet aggregated on central management console. |
| **TSK-P3-02** | Integrations | Encrypted Webhook, Syslog (RFC 5424), and MQTT alert dispatchers with retry cooldown. | 3 Days | Integration Eng | Verified SIEM ingestion (Splunk, Elastic) with zero lost alert payloads. |

### Priority P4: Long-Term Advanced Research
| Task ID | Component | Task Objective | Effort | Assigned Role | Acceptance Criteria |
|---|---|---|---|---|---|
| **TSK-P4-01** | Multi-Camera | Cross-camera 3D coordinate projection using ground-plane homography matrices. | 10 Days | CV Research Scientist | Target trajectory continuity maintained across non-overlapping camera FOVs. |
| **TSK-P4-02** | Audio Analytics | Edge acoustic anomaly detection (glass break, gunshot acoustics, industrial alarms). | 8 Days | Audio DSP Specialist | Multi-modal fusion elevating threat confidence under visual occlusion. |

---

### Phase 2 Audit Remediation Tasks (Completed)
| Task ID | Finding Ref | Task Objective | Effort | Assigned Role | Status & Acceptance Criteria |
|---|---|---|---|---|---|
| **TSK-REM-01** | SEC-01, GAP-05 | Implement `CentralizedPrivacyEnforcer` and fail-closed privacy gating in `PipelineEngine`; enforce full-frame blackout on failure; disallow disabling in production. | 2 Days | Privacy & Pipeline Lead | **COMPLETED** — Verified by 5 passing tests in `tests/test_privacy_remediation.py`. |
| **TSK-REM-02** | SEC-02, GAP-07 | Implement dual-pathway commercial model strategy (Ultralytics Enterprise vs Permissive Apache-2.0 RT-DETR/YOLOv6) with pluggable `ModelBackendType` abstraction. | 1.5 Days | AI & Compliance Lead | **COMPLETED** — `src/camserv/inference/models.py`, `docs/PHASE_2_MODEL_AND_LICENSE_REGISTER.md`. |
| **TSK-REM-03** | SEC-03, GAP-04 | Add `privacy_manifests` and `enhancement_manifests` tables to `SQLiteStore` with compound indexes, SHA-256 lookups, and CRUD methods. | 1.5 Days | Storage & Forensics Lead | **COMPLETED** — Verified by 4 passing tests in `tests/test_manifest_storage_remediation.py`. |
| **TSK-REM-04** | SEC-04, GAP-06 | Implement `SpatialAnchorStrategy.FEET_GROUND_CONTACT` in `BehavioralEngine` for ground-plane containment, eliminating perspective false alarms. | 1 Day | Computer Vision Lead | **COMPLETED** — Verified by 3 passing tests in `tests/test_ground_contact_remediation.py`. |
| **TSK-REM-05** | GAP-01 | Refactor all regulatory assertions from "Conformity" to "Technical Safeguards Aligning with GDPR/EU AI Act"; document mandatory DPIA, RoPA, DPO, and human oversight prerequisites. | 1 Day | Legal & Compliance Specialist | **COMPLETED** — Verified in `README.md` and `docs/PHASE_2_PRIVACY_AND_EVIDENCE_DESIGN.md`. |
| **TSK-REM-06** | GAP-08 | Add `openvino` and `directml` extra dependency sections to `pyproject.toml`. | 0.5 Day | Systems Packaging Eng | **COMPLETED** — Verified in `pyproject.toml`. |
