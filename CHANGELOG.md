# Changelog
All notable changes to the CAMserv platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - Phase B/C/D Master Engineering Evolution
### Added
- **Governance Infrastructure**: Architecture Decision Records (`docs/adr/`), Task Registry, Dependency Map, Risk Register, and Release Checklist.
- **Unified CLI Engine** (`src/camserv/main.py`): Command-line subcommands for `serve`, `verify-evidence`, `detect-hw`, and `nvr-scan`.
- **NVR & ONVIF Integration** (`src/camserv/acquisition/onvif.py`): WS-Discovery, Profile S/T stream negotiation, and simulated NVR compatibility test framework.
- **Temporal Event Reasoning** (`src/camserv/events/temporal.py`): Multi-frame temporal state graphs with observation tracing, model version metadata, and explainable decision trees.
- **Forensic Verification & Digital Signatures** (`src/camserv/storage/forensics.py`): Ed25519 digital signatures, RFC 3161 compliant timestamping tokens, and standalone evidence inspection CLI.
- **SQLite Metadata Persistence** (`src/camserv/storage/sqlite_store.py`): Transactional persistence for cameras, users, and audit records with automatic migration.
- **Hardware Detection Module** (`src/camserv/platform/hardware.py`): Dynamic host probing for CPU cores, RAM, GPU architecture, VRAM, and CUDA compute capability.
- **CAMserv Design System & Brand Identity** (`src/camserv/web/` & `docs/brand/`):
  - Original vector SVG master logo, symbol mark, application icons, and favicon.
  - Comprehensive brand guidelines and typography/color design tokens.
  - Interactive CAMserv Enterprise Web Console covering all 12 operational screens.

### Fixed
- Missing `camserv.main:main` entrypoint reported during baseline audit.
- Transient in-memory camera configuration now backed by durable SQLite storage.
- Evidence packages now feature asymmetric digital signatures in addition to symmetric hash chains.

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
