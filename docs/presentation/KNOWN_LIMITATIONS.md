# CAMserv — Known Limitations & Engineering Disclosures

**Document ID:** DISCLOSURE-LIMITATIONS-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Repository:** `aboulouafaeit-sys/CAMserv.IT`  
**Date:** November 15, 2026  

---

## 1. Purpose of This Disclosure

In contrast to conventional commercial marketing that obscures operational boundaries, CAMserv maintains strict engineering transparency. This document provides an exhaustive, honest register of current technical limitations, deployment prerequisites, and unvalidated hardware conditions.

---

## 2. Technical & Hardware Disclosures

### 2.1 Developer Workstation vs. Bare-Metal Appliance Environment
* **Current State:** The primary continuous integration and developer test harness executes in modern 64-bit Python environments (Windows 11 Enterprise and Linux containers).
* **Limitation:** While all Linux systemd service unit templates (`deploy/systemd/`) and partition tables (`deploy/appliance-os/partitioning.yaml`) are fully drafted, the raw disk image (`camserv-appliance-os.raw.zst`) has not yet been flashed to physical bare-metal hardware. Physical booting on specific motherboards may require motherboard-specific EFI firmware configurations or device trees.

### 2.2 Camera Testing: Simulated vs. Physical ONVIF Hardware
* **Current State:** Automated test suites validate RTSP ingestion, frame decoding, and ONVIF WS-Discovery using deterministic mock servers and synthetic video generators.
* **Limitation:** Real-world physical IP cameras frequently exhibit vendor-specific firmware bugs, non-standard RTSP keepalive timeouts, packet loss under poor wireless links, and proprietary PTZ dialects. Field calibration remains mandatory for each physical deployment site.

### 2.3 Soak Testing & Long-Duration Burn-In
* **Current State:** The synthetic soak test harness (`scripts/soak_test_harness.py`) validates memory stability across 1,000 continuous ingestion and inference cycles with near-zero RSS drift ($0.001\%$).
* **Limitation:** A software test harness does not replace a continuous physical 72-hour burn-in test inside an environmental thermal chamber ($45^\circ\text{C}$). Physical hardware endurance and fan cooling behavior under prolonged load must be validated by the hardware manufacturer.

### 2.4 Cryptographic Audit Trail Truncation Boundary
* **Current State:** The audit trail (`camserv.security.audit_trail.SecurityAuditLogger`) uses a sequential SHA-256 hash chain ($H_n = \text{SHA256}(R_n \parallel H_{n-1})$). Any modification, deletion, or reordering of intermediate records is immediately detected.
* **Limitation:** An attacker with complete administrative access to the underlying storage database could theoretically truncate the last $N$ records without breaking the hash chain of earlier entries, unless the latest chain head hash is periodically committed to an external witness ledger or Central master controller.

### 2.5 Third-Party Model Weight Licensing & Commercial Distribution
* **Current State:** The automated Software Bill of Materials (SBOM) generator (`scripts/generate_sbom.py`) catalogs all runtime dependencies and pre-trained ONNX models under permissive licenses (MIT, Apache-2.0, BSD-3-Clause).
* **Limitation:** Commercial OEMs bundling proprietary software with CAMserv must obtain independent corporate legal counsel review regarding patent indemnification, dataset training copyright risks, and jurisdiction-specific AI liability frameworks.
