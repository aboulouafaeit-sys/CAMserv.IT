# CAMserv — Privacy Architecture & Evidence Preservation Design
**Standard:** GDPR (EU 2016/679) & Italian Garante Privacy Conformity  
**Security Level:** High Assurance / Cryptographic Separation  
**Operational Mode:** Fail-Closed Default  

---

## 1. Regulatory Context & Core Privacy Principles

Video surveillance systems in enterprise and municipal environments must comply with strict data protection frameworks, including **GDPR Articles 5, 9, 25 (Privacy by Design), and 32 (Security of Processing)**, as well as the Italian Data Protection Authority (*Garante per la protezione dei dati personali*) guidelines on video surveillance.

CAMserv enforces these requirements architecturally rather than through optional policy toggles:

1. **Principle of Data Minimization (GDPR Art. 5.1.c):**  
   Video frames intended for real-time monitoring, live multi-view displays, or analytical export must have face and license plate regions obscured by default.
2. **Prohibition of Biometric Data Processing (GDPR Art. 9):**  
   CAMserv completely excludes facial recognition models, biometric embeddings, and identity databases. Objects are tracked exclusively using transient anonymous integers (`track_id`) scoped strictly to individual camera streams.
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
