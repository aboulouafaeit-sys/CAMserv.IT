# Changelog
All notable changes to the CAMserv platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
