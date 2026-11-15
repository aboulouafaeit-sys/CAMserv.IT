# CAMserv Master Release Roadmap

**Document ID:** ROADMAP-REL-2026-001  
**Classification:** Strategic Release Planning  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Release Versioning Strategy

CAMserv follows **Semantic Versioning (SemVer 2.0.0)** (`MAJOR.MINOR.PATCH`):
- `v0.1.0`: Initial baseline prototype (Phase 1).
- `v0.2.0-rc1`: Security-hardened core engine with 10 post-Phase 3 remediations, full brand assets, and international documentation.
- `v0.5.0`: Core NVR subsystem with continuous recording, timeline playback, and WebRTC streaming (Phase 5).
- `v0.7.0`: Advanced zone analytics, tripwires, tampering detection, and hardware accelerator adapters (Phase 6).
- `v0.9.0-rc1`: Complete feature-complete integrated ecosystem with appliance OS images and CycloneDX SBOM (Phase 12).
- `v1.0.0-LTS`: First enterprise Long-Term Support production release following a successful 72-hour environmental soak test and physical hardware validation.

---

## 2. Release Milestones & Acceptance Criteria

| Release | Target Scope | Mandatory Acceptance Gate |
| :--- | :--- | :--- |
| **v0.2.0-rc1** | Presentation overhaul, CI workflow, and security audit remediations. | 245/245 tests passing; zero broken doc links; audit chain intact. |
| **v0.5.0** | Core NVR engine, SQLite recording index, continuous recording, timeline, WebRTC/HLS. | 24/7 continuous recording verified across synthetic feeds; crash recovery tested. |
| **v0.7.0** | Tripwires, polygon zones, tampering alarms, and hardware adapters. | Accurate line crossing and occlusion detection with zero false-positive runaway. |
| **v0.9.0-rc1** | Unified enterprise ecosystem, central fleet sync, and appliance Debian packages. | Independent security audit clean (0 Critical/High); Debian `.deb` builds cleanly. |
| **v1.0.0-LTS** | Physical hardware certification across Profile A/B boards and multi-camera lab matrix. | Completed 72-hour continuous thermal soak test without memory leaks or crash. |
