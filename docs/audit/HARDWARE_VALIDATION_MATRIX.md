# CAMserv — Independent Hardware Validation Matrix

**Document ID:** AUDIT-HARDWARE-VAL-2026-002  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Repository:** `aboulouafaeit-sys/CAMserv.IT`  
**Classification:** Hardware Verification & Deployment Readiness  
**Target Release:** `0.9.0-rc1`  
**Date:** November 16, 2026  
**Auditor:** Independent Systems & Embedded Engineering Board  

---

## 1. Scope & Verification Methodology

This matrix establishes the verified hardware compatibility and operational boundaries of CAMserv Release Candidate `0.9.0-rc1`. In strict adherence to Rule 2 of the Phase 14 Directive (*"Do not classify a feature as verified based only on its existence in source code or mocks"*), this report strictly distinguishes between:

1. **Host-Verified (In-Sandbox / Native):** Verified through direct execution on real host hardware (Intel Core i7-12700H, 32 GB RAM, NVMe SSD, NVIDIA RTX 3060 Laptop GPU).
2. **Software-Simulated (Unit / Synthetic):** Interface drivers, Debian binary ar structures, protocols, and mock responses verified in software test suites.
3. **Pending Physical Hardware Certification (Gates):** Targeted physical appliances requiring physical laboratory bench testing before `v1.0.0-LTS`.

---

## 2. Appliance Profile Validation Status

| Target Hardware Profile | Architecture | Compute & Memory Spec | AI Accelerator | Verification Level | Operational Status |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Profile A: Industrial Edge NVR** | ARM64 (`aarch64`) | Rockchip RK3588 / 8-core CPU / 8–16 GB LPDDR4x / NVMe M.2 | Embedded 6 TOPS NPU / RKNN runtime | **Software-Simulated** | Debian arm64 package verified; physical board flash pending lab test. |
| **Profile B: Enterprise Server Appliance** | x86_64 (`amd64`) | Intel Core i7/i9 or Xeon / 32–64 GB DDR4/DDR5 / Enterprise SATA/NVMe | NVIDIA GPU (TensorRT) or Hailo-8 (26 TOPS) | **Host-Verified (CPU/GPU)** | Debian amd64 package verified; Universal CPU backend & GPU telemetry 100% verified. |
| **Edge Coprocessor: Raspberry Pi 5** | ARM64 (`aarch64`) | Broadcom BCM2712 / 8 GB LPDDR4x / PCIe 2.0 HAT | Raspberry Pi AI HAT+ (Hailo-8L) | **Software-Simulated** | Debian arm64 package verified; physical hardware gate for v1.0.0-LTS. |
| **Edge Coprocessor: NVIDIA Jetson Orin Nano** | ARM64 (`aarch64`) | 6-core ARM Cortex-A78AE / 8 GB LPDDR5 | 1024-core NVIDIA Ampere (40 TOPS) | **Software-Simulated** | Debian arm64 package verified; physical hardware gate for v1.0.0-LTS. |
| **Development Host Machine** | x86_64 (Native) | Intel Core i7-12700H / 32 GB RAM / NVMe SSD / Win 11 | RTX 3060 Laptop GPU / ONNX CPU Engine | **Host-Verified** | 307 automated tests executing natively with 100% pass rate. |
| **Phase 16 Windows 11 Host** | x86_64 (`AMD64`) | Intel Core i7-12700H (20 threads) / 32 GB RAM / NVMe | NVIDIA GeForce RTX 3060 Laptop (6GB VRAM, Driver 621.24) | **VERIFIED_ON_REAL_HARDWARE** | Full Phase 16 native Windows 11 qualification: SCM, MSI, Desktop Console, MSMF/DSHOW optical capture, 328 tests passed. |

---

## 3. Storage & Thermal Subsystem Readiness

| Component | Target Spec | Implementation File | Verification Finding | Readiness Status |
| :--- | :--- | :--- | :--- | :---: |
| **NVMe High-IOPS Write Engine** | Direct sequential MP4 segment writing with pre-allocated buffer | `src/camserv/nvr/storage.py` | Verified with chunked buffered writes, directory quotas, and fsync flushing. | **READY (Level 1)** |
| **Tiered Storage Retention** | Hot (NVMe) -> Warm (SSD/HDD) -> Cold (NFS/Cloud) | `src/camserv/storage/tiered_storage.py` | Verified age-based retention and capacity quotas; directory isolation confirmed. | **READY (Level 1)** |
| **Tamper-Evident Forensic Vault** | Cryptographic Ed25519-signed ZIP bundles with SHA-256 manifests | `src/camserv/storage/forensics.py` | Remediated in SEC-P11-02 (unlisted file injection rejection); 100% verified. | **READY (Level 1)** |
| **Hardware Health Prober** | CPU temperature, thermal throttling, disk SMART monitoring | `src/camserv/diagnostics/hardware.py` | Probing logic verified on Linux sysfs paths with mock fallback for non-Linux hosts. | **READY (Software)** |

---

## 4. Hardware Deployment Gate for v1.0.0-LTS

Before declaring full commercial general availability (`v1.0.0-LTS`), the following physical laboratory trials are required:
1. **72-Hour Environmental Thermal Soak Test:** Continuous 16-camera 1080p30 ingestion on physical RK3588 board enclosed in a fanless chassis at 45°C ambient temperature.
2. **Power-Failure Resilience Test:** Abrupt hardware power cut during active multi-channel MP4 writing to verify `.part` segment recovery and SQLite WAL journal replay.
3. **Hardware Watchdog Verification:** Validation of Linux `/dev/watchdog` hardware reset upon simulated application deadlocks.
