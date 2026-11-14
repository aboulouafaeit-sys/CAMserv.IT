# CAMserv — Technical Privacy Safeguards & Evidence Preservation Design
**Design Alignment:** Technical Architectural Safeguards Aligning with GDPR (EU 2016/679) and Applicable EU AI Act Requirements  
**Security Level:** High Assurance / Cryptographic Separation  
**Operational Mode:** Fail-Closed Default  
**Legal Notice:** This document specifies software-level architectural controls. It does not constitute formal legal certification or replace mandatory organizational compliance requirements.

---

## 1. Regulatory Context & Core Privacy Principles

Video surveillance systems in enterprise and municipal environments operate within strict regulatory data protection frameworks, including **GDPR Articles 5, 9, 25 (Data Protection by Design), and 32 (Security of Processing)**, as well as guidelines issued by the Italian Data Protection Authority (*Garante per la protezione dei dati personali*) and the European Data Protection Board (EDPB).

CAMserv embeds architectural safeguards directly into the video processing pipeline:

1. **Principle of Data Minimization (GDPR Art. 5.1.c):**  
   Video frames intended for real-time monitoring, multi-view operational displays, or analytical export undergo non-biometric obscuration of face and license plate regions by default.
2. **Prohibition of Biometric Data Processing (GDPR Art. 9):**  
   CAMserv explicitly excludes facial recognition algorithms, biometric template extractors, identity databases, and demographic profiling neural networks. Object tracking is restricted to transient, camera-scoped integer identifiers (`track_id`) that expire upon stream departure.
3. **Integrity and Confidentiality (GDPR Art. 5.1.f):**  
   The raw, unmodified original frame is preserved in an encrypted, tamper-evident vault. Privacy-masked frames are derivatives cryptographically bound to the pristine original.

---

## 2. Fail-Closed Privacy Pipeline Architecture

Conventional surveillance software fails "open" when computer vision models encounter errors or resource limits, allowing unmasked frames to stream directly to operator consoles.

CAMserv mandates a **Fail-Closed Architecture**:

```
+---------------------------------------------------------------------------------+
|                                RAW VIDEO FRAME                                  |
|                 (Computed Original SHA-256 Digest in Memory)                    |
+---------------------------------------+-----------------------------------------+
                                        |
                 +----------------------+----------------------+
                 |                                             |
                 v                                             v
     [Privacy Detection Model]                    [Pristine Raw Preservation]
   (Face & Plate Polygon Bounding)                (Tamper-Evident Local Vault)
                 |                                             |
        +--------+--------+                                    |
        |                 |                                    |
     [Success]         [Failure / Error]                       |
        |                 |                                    |
        v                 v                                    |
 [Apply Masking]   [Trigger FAIL_CLOSED]                       |
(Gaussian/Mosaic) (100% Solid Blackout + Alert)                |
        |                 |                                    |
        +--------+--------+                                    |
                 |                                             |
                 v                                             v
    [Derivative Masked Frame]                     [Compute Original SHA-256]
   (Computed Derivative SHA-256)                               |
                 |                                             |
                 +----------------------+----------------------+
                                        |
                                        v
                       +---------------------------------+
                       |     PrivacyEvidenceManifest     |
                       | - original_sha256               |
                       | - derivative_sha256             |
                       | - masking_method                |
                       | - fail_closed_active            |
                       | - timestamp_utc                 |
                       +---------------------------------+
```

### Invariant Guarantees:
1. **Zero Raw Egress under Error:**  
   If the detector throws an exception, crashes, or drops below confidence, the pipeline enters `PrivacyState.FAIL_CLOSED`. The frame emitted to the streaming server is 100% blacked out with an orange warning banner.
2. **Immutability of Original Evidence:**  
   The pristine raw frame is never altered in memory or overwritten by the derivative.
3. **Cryptographic Linkage:**  
   The `PrivacyEvidenceManifest` binds `original_sha256` and `derivative_sha256` into a verifiable cryptographic manifest. Altering either the raw recording or the masked output breaks validation.

---

## 3. Role-Based Access Separation

| Access Role | View Permission | Data Access Path | Cryptographic Key Requirement |
| :--- | :--- | :--- | :--- |
| **Operator / Guard** | Live Monitoring & Alarms | Privacy-Masked Stream Only | Stream Access Token |
| **System Admin** | Telemetry & Health Metrics | Aggregated Counters & Logs | Admin JWT |
| **Forensic Investigator** | Incident Video Review | Derivative Video + Manifest | Investigator Role Key |
| **Legal / Compliance Officer** | Unmasked Raw Evidence Export | Pristine Raw Vault Chunks | Dual-Control Quorum Key (Vault AES-256-GCM) |

---

## 4. Mandatory Organizational Prerequisites for Production Deployment

> [!IMPORTANT]
> Technical safeguards implemented in software (such as automated masking, fail-closed blackouts, and cryptographic manifests) do not independently confer legal compliance or replace statutory responsibilities. Prior to commissioning CAMserv in any real-world production environment, the operating organization must formally satisfy all applicable legal, administrative, and organizational requirements.

### 4.1 Data Protection Impact Assessment (DPIA) — GDPR Article 35
Because systematic video surveillance of publicly accessible or workplace areas constitutes high-risk processing under EDPB Guidelines 3/2019 and national supervisory decisions (e.g., *Provvedimento in materia di videosorveglianza* by the Italian *Garante*), a comprehensive DPIA must be conducted prior to system activation. The DPIA must:
- Document the legitimate necessity and proportionality of deploying video intelligence.
- Evaluate risks to the rights and freedoms of recorded data subjects.
- Assess risks of algorithmic false positives in behavioral event triggers.
- Formally document mitigating technical controls (including CAMserv's fail-closed masking and transient ID expiration).

### 4.2 Records of Processing Activities (RoPA) — GDPR Article 30
The deploying controller must register the CAMserv processing operations in its official RoPA, specifying:
- Purpose of processing (e.g., perimeter security, access control, asset protection).
- Categories of data subjects (employees, visitors, public).
- Categories of personal data (transient visual appearances; raw encrypted streams in forensic vault).
- Categories of recipients (authorized internal security personnel; law enforcement upon lawful warrant).
- Third-country transfers: Prohibited under CAMserv's 100% Ultra-Local Zero-API architecture.
- Retention time limits and deletion schedules.

### 4.3 Retention Limits & Storage Limitation — GDPR Article 5(1)(e)
- Standard continuous surveillance recordings must adhere to national retention thresholds (typically 24 to 72 hours under Italian and EU norms).
- Automated retention purging must be enforced, except where an identified security incident requires evidentiary preservation under judicial hold.
- Evidentiary records stored in the Smart Adaptive Vault must be indexed with strict expiration dates and cryptographic seal verification.

### 4.4 Public Information & Statutory Signage — GDPR Articles 13 & 14
- Prominent first-layer warning notices (standard video surveillance signage) must be posted at all entrances and boundary lines before individuals enter camera capture fields.
- The sign must clearly identify:
  1. Identity and contact details of the Data Controller.
  2. Contact details of the Data Protection Officer (DPO).
  3. Purpose of surveillance and legal basis (GDPR Art. 6(1)(f) legitimate interest or Art. 6(1)(e) public interest).
  4. Retention period.
  5. Second-layer full privacy disclosure location (QR code / URL).
  6. Rights of data subjects (access, restriction, objection, complaint to supervisory authority).

### 4.5 Human-in-the-Loop Oversight & EU AI Act Alignment
Under the EU AI Act (Regulation (EU) 2024/1689), computer vision systems used in safety-critical, law enforcement, or sensitive public domains require meaningful human oversight (Article 14):
- Algorithmic outputs (`severity >= HIGH`) are classified as probabilistic hypotheses (`is_prediction = True`).
- Automated physical interventions (such as automated locking, alert escalation to authorities, or disciplinary actions) are strictly prohibited without human verification by a trained operator.
- Operators must possess authority to override, pause, or discard algorithmic alerts without consequence.
- Biometric categorization and emotion recognition are categorically disabled in CAMserv's neural inference architecture.

