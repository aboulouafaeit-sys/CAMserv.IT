# Changelog
All notable changes to the CAMserv platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.0-rc7] - 2026-11-23
### Added
- **Ed25519-signed model-weight installer** (`camserv.deploy.model_installer`, console script `camserv-install-models`): model weights now ship as a signed bundle with a canonical `models.manifest.json`. Installation verifies the manifest signature against pinned release-authority public keys (fail-closed), re-computes each artifact's SHA-256 and byte size, rejects path traversal and unmanifested payload files, then stages and commits atomically with rollback. Verified artifacts can be registered directly into `camserv.inference.models.ModelRegistry`. Covered by 11 unit/adversarial tests in `tests/test_model_installer.py`.

- **Hardware-rooted trust anchors — TPM 2.0 / PKCS#11 HSM** (`camserv.security.key_anchor`, console script `camserv-key-anchor`): release, OTA and model-signing public keys can now be resolved from a physical TPM 2.0 (Windows CNG *Microsoft Platform Crypto Provider*, via `ctypes` with no new dependency) or from a PKCS#11 HSM (optional `camserv[hsm]` extra), then pinned by SHA-256 `SubjectPublicKeyInfo` fingerprint. The resolver is fail-closed: `require_hardware=True` rejects software-file anchors, duplicate purposes and empty policies are refused, private-key files are rejected, missing TPM keys/PKCS#11 modules abort instead of silently downgrading, and fingerprint mismatches raise `KeyAnchorError`. `SignedModelInstaller.from_trust_anchors()` / `SignedUpdateManager.from_trust_anchors()` consume the anchors while enforcing Ed25519. Trust-anchor policy is configurable via `SecuritySettings.key_anchors`. Covered by 45 tests in `tests/test_key_anchor.py` using injected fake CNG/PKCS#11 providers, so CI validates the anchoring logic without physical hardware.

### Changed
- **Single version source of truth:** The canonical release version is declared once in `src/camserv/__init__.py` (`__version__`) and reflected dynamically by the FastAPI `/health` endpoint, the OpenAPI document, and the `camserv.api.routes` health probe. The previous drift — `0.9.0-rc1` in the Python package / `pyproject.toml` / Debian control / SBOM, `0.10.0-alpha2` in the Windows MSI builder, and `0.10.0-rcN` in the qualification docs — has been eliminated.
- **Version synchronized to `0.10.0-rc7`** across `pyproject.toml`, `deploy/debian/control`, `deploy/build_deb.py`, `deploy/build_deb.sh`, `deploy/debian/verify_native_debian.sh`, `deploy/windows/build_msi.py`, and the CycloneDX SBOM (`deploy/sbom/camserv-sbom.json`). `0.10.0-rc7` is the current pre-LTS release candidate; the final `0.10.0` / `v1.0.0-LTS` cut remains gated on the physical hardware qualification gates.
- **Documentation truth alignment:** README test badge, collected count, and verification transcript updated to the actual suite size (725 tests across 93 modules); this changelog restarted from the stale `0.2.0-rc1` baseline; the production-readiness scorecard test-count references corrected.

### Added (consolidated since 0.2.0-rc1)
- Enterprise federation and multi-node clustering: zero-trust mTLS, tenant isolation, failover orchestration, and distributed forensic replication (Phases 17–18).
- Intelligent Storage & Evidence Preservation Engine (ISEP): segmented recording, hybrid SSD/HDD tiering, retention and legal-hold governance, Ed25519 courtroom export, capacity forecasting, and crash recovery (Phase 24).
- Hardware adaptation and appliance engineering: universal accelerator abstraction (CUDA / DirectML / OpenVINO / Coral), adaptive resource intelligence, RK3588-class appliance targeting, and physical-qualification gates (Phase 25).

### Fixed
- `tests/test_phase24_isep_storage.py::test_safe_cleanup_lifecycle_and_hold_immunity` was wall-clock dependent (segment timestamps pinned to a past reference date, so the "recent" segment aged out and was purged). It now passes an explicit `now` timestamp to `execute_safe_cleanup`, making the retention-cleanup verification deterministic.

### Known Limitations
- On a general-purpose unprivileged host a small number of tests are environment-gated and may fail intermittently: disk-capacity forecasting (requires the ≥10% free-volume safety reserve), extended UI-freeze soak timing (Phase 25), privileged quarantine restoration and storage-lease timing (Phase 20), and multiprocessing ingestion-supervisor lifecycle. These do not indicate platform defects and pass in the qualified CI/lab environment.


## [0.2.0-rc1] - 2026-11-15
### Added
- **AI Appliance Architecture**: 4 Universal Hardware Adaptation Tiers with Graceful Degradation governor (`camserv.platform.appliance`).
- **Dedicated Linux Operating Environment**: Systemd service units, watchdog deadman timers, and restart loop circuit breaker (`camserv.deploy.supervisor`).
- **Central Fleet Management & Device Registry**: Ed25519 challenge-response enrollment, site isolation boundaries, and executive fleet dashboard (`camserv.central.registry`).
- **Secure Distributed Communication**: Signed message envelopes, replay protection (nonces + clock skew), sliding-window rate limiting, and WAN data minimization (`camserv.central.comm`).
- **Enterprise Security & Multi-Tenancy**: Server-side multi-tenant boundaries (`camserv.security.tenancy`), 6-role RBAC policy engine with dual-control quorum for raw visual access (`camserv.security.rbac`), and sanitized SHA-256 chained audit trails (`camserv.security.audit_trail`).
- **Tiered Storage & Evidence Governance**: RAM pre-roll (15s), operational NVMe pool, automated 48h retention purging, judicial hold locking, and court-admissible evidence export (`camserv.storage.tiered_storage`).
- **Signed OTA Updates**: Cryptographic Ed25519 release verification, Zip Slip containment, semver compatibility, and atomic snapshot rollback on health probe failure (`camserv.deploy.updater`).
- **Human-in-the-Loop Operator Governance**: 6-stage operational review pipeline preventing unreviewed automated physical actions (`camserv.web.operator_workflow`).
- **Observability & Reliability**: Prometheus `/metrics` collector, multi-subsystem liveness/readiness health probes, and continuous soak test memory profiler (`camserv.platform.observability`).
- **Commercial Product Packaging**: Community, Professional, and Enterprise edition gating with automated CycloneDX 1.5 JSON Software Bill of Materials (SBOM) generator (`scripts/generate_sbom.py`).
- **Comprehensive Vector & Social Branding**: Scalable vector SVG suite (emblem, horizontal logo, wordmark, monochrome) and official GitHub social preview card ($1280 \times 640$).

### Security Remediations
- **SEC-P3-01 (CRITICAL)**: Remediated Zip Slip path traversal in OTA package extractor; enforced directory containment and unmanifested file rejection.
- **SEC-P3-02 (CRITICAL)**: Enforced strict dual-control quorum on raw snapshot exports in `CentralizedPrivacyEnforcer`.
- **SEC-P3-03 (HIGH)**: Neutralized path traversal in storage chunk IDs, camera IDs, and incident vault filenames.
- **SEC-P3-04 (HIGH)**: Re-ordered distributed gateway validation so cryptographic signatures are verified before updating rate-limit counters, eliminating unauthenticated sender DoS attacks.
- **SEC-P3-05 (HIGH)**: Added server-side site authorization verification to device suspension and revocation endpoints.
- **SEC-P3-06 (MEDIUM)**: Added recursive sanitization to security audit logger for nested lists/tuples of dictionaries, preventing credential leakage.
- **SEC-P3-07 (MEDIUM)**: Enforced distinct user identities on dual-control quorum authorizations, preventing self-approval.
- **SEC-P3-08 (MEDIUM)**: Enforced active tenant status checks in multi-tenant boundary validation.
- **SEC-P3-09 (LOW)**: Clarified audit trail documentation to accurately describe sequential SHA-256 hash chaining.
- **SEC-P3-10 (LOW)**: Added security warning logging when default master secret is utilized in non-production profiles.

### Verified Test Suite
- Automated test suite elevated from 180 to **245 passing tests (100% pass rate in 10.8s)** across 47 test modules.

## [0.1.0] - 2026-11-13
### Added
- Initial modular pipeline architecture with async queues and bounded backpressure (`drop_oldest`).
- Object detection supporting ONNX Runtime (GPU/CPU) and Ultralytics with prediction flagging.
- Anonymous ByteTrack and BoT-SORT multi-object tracking with Kalman filtering and MOTA/MOTP metrics.
- Rule-based event detection (zone intrusion, fall detection, loitering, tampering, crowd density).
- Privacy masking filter with polygon exclusion and dynamic face/body blur.
- Redis caching layer and Milvus scene vector store (zero biometric data).
- AES-256-GCM tamper-evident evidence store with SHA-256 hash chaining.
- RS256 JWT authentication, RBAC, and append-only audit logger.
- FastAPI REST API and WebSocket streaming endpoints.
- Initial test suite comprising 95 automated tests.
