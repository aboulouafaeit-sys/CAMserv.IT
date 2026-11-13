# CAMserv Commercial Release Checklist
**Gatekeeper: Independent Quality Assurance & Chief Systems Architect**

All criteria must be marked **VERIFIED** prior to signing off on any production release candidate (v0.2.0+).

## 1. Engineering & Code Quality
- [ ] **Type Safety:** 100% type annotations on all public methods and functions; verified via mypy/pyright.
- [ ] **Docstrings:** Comprehensive Google/Sphinx style docstrings on all public classes, methods, and modules.
- [ ] **Protocol Adhesion:** Pipeline components strictly implement `typing.Protocol` classes defined in `interfaces.py`.
- [ ] **Exception Handling:** Zero bare `except:` blocks; all pipeline and subsystem exceptions inherit from `PipelineError` or domain-specific roots.
- [ ] **Structured Logging:** No raw `print()` statements in library code; `structlog` used with contextual key-value fields.

## 2. Epistemic Transparency & Privacy
- [ ] **Prediction Tagging:** Every detection and inferred event carries `is_prediction: bool = True` and confidence $p \in [0.0, 1.0]$.
- [ ] **Anonymity:** Multi-object tracking outputs use transient integer identifiers only; zero persistent biometric linkage.
- [ ] **Privacy Masking:** Geometric exclusion zones and face/body blur filters applied prior to video disk persistence or public streaming.
- [ ] **Vector Cleanliness:** Vector database (Milvus) schemas verified to contain zero biometric feature vectors or facial embeddings.

## 3. Security & Forensics
- [ ] **Authentication:** RS256 JWT tokens with active expiration and refresh mechanisms; API keys hashed with constant-time verification.
- [ ] **Authorization:** RBAC permissions enforced on all API routes (`ADMIN`, `OPERATOR`, `VIEWER`, `AUDITOR`).
- [ ] **Data at Rest:** Evidence files encrypted using AES-256-GCM with HKDF key derivation.
- [ ] **Audit Trail:** Append-only audit log with verified SHA-256 hash chaining from genesis.
- [ ] **Evidence Integrity:** Standalone CLI tool independently verifies evidence zip packages and hash chains without requiring server access.

## 4. Hardware & Platform Interoperability
- [ ] **Hardware Detection:** Automated detection of CPU cores, RAM, GPU architecture, VRAM, and CUDA compute capability.
- [ ] **Fallback Verification:** Seamless automatic fallback to ONNX CPU when CUDA/TensorRT is absent.
- [ ] **NVR & ONVIF Compatibility:** Verified interoperability with ONVIF Profile S/T discovery and RTSP streaming.

## 5. UI/UX & Design System
- [ ] **Brand Identity:** Original vector SVG assets (primary logo, icon mark, monochrome variants) deployed.
- [ ] **12 Core Screens:** Executive Overview, Live Monitoring, Camera Management, Event Center, Anonymous Tracking, Incident Investigation, Evidence Vault, Analytics & Reports, Device & NVR, Security & Access, System Health, Deployment & Config implemented.
- [ ] **Operational States:** Defined empty, loading, error, and permission-restricted states for every dashboard view.
- [ ] **Accessibility:** High contrast, keyboard navigation, and reduced-motion support implemented.

## 6. Testing & Benchmarking
- [ ] **Automated Tests:** 100% test pass rate across unit, adversarial, and integration suites.
- [ ] **Adversarial Robustness:** Pass rate verified against corrupted video streams, inverted bounding boxes, and adversarial noise frames.
- [ ] **Performance Evidence:** Empirical P50, P95, and P99 latency benchmarks documented without fabricated or synthetic zeroes.
