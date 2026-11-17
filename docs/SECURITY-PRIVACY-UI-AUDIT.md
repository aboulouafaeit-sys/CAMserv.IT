# CAMserv — Security, Privacy & Invariant UI Audit

**Document ID:** AUDIT-SEC-UI-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Visual Direction:** Cinematic Dark / Multi-Layer Glassmorphism  
**Date:** November 17, 2026  
**Auditor:** Independent Digital Forensics & Privacy Compliance Board  

---

## 1. Scope & Invariant Principles

The visual overhaul of CAMserv must strictly preserve all foundational security controls, mathematical quorum guarantees, privacy enforcement pipelines, and forensic witness invariants. The frontend interface serves as an authoritative window into backend security state; it must never introduce security bypasses, mislead operators, or violate GDPR/AI-Act ethical standards.

---

## 2. Security & Privacy Invariant Verification

### 2.1 Fail-Closed Privacy Redaction (GDPR Article 25)
* **Backend Invariant:** Video delivery pipelines enforce fail-closed spatial blurring. If the detection pipeline is unconfigured or encounters an internal fault, video output is completely blacked out.
* **UI Enforcement:**
  - The Live Monitoring screen and Camera Management interfaces do **not** permit operators to bypass or disable spatial privacy masking.
  - Clicking any privacy toggle displays a clinical modal notice:  
    `"Privacy Masking is enforced by kernel/pipeline policy. Raw unredacted footage is cryptographically sealed and accessible only via Dual-Control Judicial Quorum authorization."`
  - Unmasked raw video streams are never transmitted to unauthorized operator browser sessions.

### 2.2 Strict Non-Biometric Invariant (EU AI Act Compliance)
* **Prohibition:** Biometric face recognition, 1:N facial search, emotion classification, gender/age profiling, and biometric cross-camera Re-ID are strictly prohibited.
* **UI Verification:**
  - The UI contains zero facial recognition match scores, biometric identity candidate lists, or face recognition databases.
  - Detections are restricted to anonymous object classifications (`person`, `vehicle`, `bicycle`, `backpack`).
  - Spatial tracking displays anonymous trajectory ribbons and ground contact point uncertainty ellipses without persistent person identity.

### 2.3 Epistemic Uncertainty & Non-Accusatory Presentation
* **Probabilistic Cues:** Deep learning outputs are presented with explicit epistemic uncertainty tags (`is_prediction: true`, `confidence: float`).
* **Ethical Language:** Behavioral detections are classified as `"Reviewable Event Candidates"`, never as `"Suspect"`, `"Criminal"`, or `"Guilty"`.
* **Threat Scores:** Threat priority values reflect operational urgency (e.g. perimeter sensor trip), not a probability of human criminal intent.

### 2.4 Quorum & Storage Fencing Transparency
* **Consensus Telemetry:** The UI displays genuine cluster metrics (Term number, active node count $N$, required quorum $Q = \lfloor \max(N, \text{expected}) / 2 \rfloor + 1$).
* **Fenced Writer Indication:** If a node's `StorageLease` expires or is revoked, the UI immediately marks all associated camera viewports as `[FENCED WRITER - RECORDING HALTED]`.
* **Quarantine Segregation:** Incomplete segments isolated under `SEC-P20-02` are routed to the Quarantined Segments Queue and excluded from the courtroom evidence timeline until authorized by a forensic officer.

### 2.5 Audit Log Invariant (Rule 1)
* **Audit File:** `logs/audit.jsonl`
* **Byte Count:** Exactly **20,977 bytes**
* **SHA-256 Digest:** `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525`
* **Status:** Verified intact before, during, and after all Phase 22 visual implementations.
