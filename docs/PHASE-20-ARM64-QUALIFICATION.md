# CAMserv — Phase 20 ARM64 Platform Qualification & Hardware Status

**Document ID:** PHASE-20-ARM-2026-010  
**Target Architecture:** ARM64 (`aarch64`)  
**Target Appliances:** Rockchip RK3588 (Profile A), Raspberry Pi 5 (Edge Coprocessor)  
**Classification:** Hardware Verification & Deployment Readiness  
**Date:** November 16, 2026  

---

## 1. Explicit Scope & Verification Level

In strict compliance with Directive Rule 2 (*"Do not claim physical hardware testing when only mocks, containers, emulators, or synthetic streams were used"*), the qualification status is explicitly classified:

* **Classification:** **BLOCKED_BY_ENVIRONMENT (Physical ARM64 Hardware Validation)**
* **Software-Simulated Qualification:** **PASS (Debian arm64 Package & Binary Layout)**

---

## 2. Software-Level Verification Performed

1. **Debian ARM64 Package Building:** Verified that `deploy/build_deb.py` generates valid `camserv_0.9.0-rc1_arm64.deb` containing correct ARM64 control headers and dependency chains.
2. **Data Alignment & Endianness:** Unit tests verified that canonical JSON serialization (RFC 8785) and Ed25519 cryptographic signing operate with strict 64-bit word alignment and little-endian byte ordering.
3. **NPU Interface Stubs:** Driver stubs for RKNN (Rockchip NPU) and HailoRT (Hailo-8L) pass simulated device query tests, gracefully reporting `Not Present` when hardware is absent without raising unhandled crashes.

---

## 3. Mandatory Pre-LTS Physical Hardware Gate

Before General Availability (`v1.0.0-LTS`), physical laboratory verification must complete:
1. Flashing and booting Debian 13 arm64 on physical Rockchip RK3588 board.
2. 16-channel simultaneous RTSP hardware H.264 decoding via Rockchip MPP (Media Process Platform).
3. Continuous NPU inference execution on RKNN accelerator.
