# CAMserv — Strategic Product Roadmap & Engineering Vision

**Document ID:** ROADMAP-STRATEGIC-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Repository:** `aboulouafaeit-sys/CAMserv.IT`  
**Date:** November 15, 2026  

---

## 1. Roadmap Principles

CAMserv development follows three core engineering tenets:
1. **Evidence-Driven Execution:** Capabilities are documented as planned until verified with reproducible tests and real code.
2. **Privacy as an Invariant:** Technological innovation must never compromise fundamental human rights or privacy safeguards.
3. **Hardware Agnosticism:** Features must never be coupled to a single proprietary GPU vendor or operating system.

---

## 2. Strategic Engineering Milestones

### Milestone 1: Bare-Metal Appliance Manufacturing & OS Build (Q1-Q2 2027)
* **Goal:** Deliver turnkey, flashable raw disk images for dedicated CAMserv AI Appliances.
* **Key Deliverables:**
  - Automated Linux debootstrap build pipeline generating compressed appliance disk images (`camserv-appliance-os.raw.zst`).
  - Validation of dual A/B partition slots on UEFI / GRUB hardware.
  - Native Rockchip RK3588 NPU (Profile A) and Intel Core Ultra NPU (Profile B) acceleration backends.
  - 72-hour continuous thermal chamber soak testing ($45^\circ\text{C}$).
  - Hardware TPM 2.0 endorsement key binding for device enrollment.

### Milestone 2: Enterprise Central Mesh & Scaled Clustering (Q3-Q4 2027)
* **Goal:** Expand multi-site central management for enterprise clusters exceeding 1,000 cameras.
* **Key Deliverables:**
  - Automated internal Public Key Infrastructure (mTLS PKI CA) with automated device certificate rotation.
  - Clustered Milvus vector database mesh for multi-site spatial metadata querying.
  - High-availability distributed storage replication across secondary S3/MinIO cold archives.
  - Integration connectors for enterprise SIEM systems (Splunk, Elastic, Microsoft Sentinel) via CEF/Syslog.

### Milestone 3: Embedded Edge Cameras & Formal Certifications (2028)
* **Goal:** Ultra-compact embedded camera integration and third-party security certifications.
* **Key Deliverables:**
  - Lightweight C++ / Rust inference runtime for low-power on-camera microcontrollers (1-3W).
  - Common Criteria (ISO/IEC 15408) EAL4+ security evaluation readiness.
  - FIPS 140-3 cryptographic boundary certification for evidence vault modules.
  - European Union Cyber Resilience Act (CRA) compliance documentation suite.

---

## 3. Explicit Non-Goals (What CAMserv Will NEVER Do)

To preserve our moral, architectural, and legal integrity, CAMserv explicitly rejects:
* **Facial Recognition & Biometric Profiling:** We will never implement biometric facial recognition, emotion analysis, or demographic surveillance databases.
* **Proprietary Cloud Lock-In:** We will never force users to route private video streams through proprietary cloud servers or require active internet connections for local surveillance.
* **Automated Physical Action Without Human Review:** We will never permit algorithmic AI models to trigger physical dispatches or door lockouts autonomously without human verification.
* **Proprietary Closed Formats:** We will never encrypt forensic evidence in undocumented proprietary wrappers that cannot be inspected using open, standards-compliant tools.
