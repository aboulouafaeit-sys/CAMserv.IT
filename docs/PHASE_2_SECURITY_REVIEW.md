# CAMserv — Phase 2 Security Review & Threat Model
**Phase:** 2 — Local AI & Edge Intelligence  
**Standard:** Zero-Trust Edge, Cryptographic Integrity, GDPR Conformity  

---

## 1. Threat Model & Mitigations

| Threat Vector | Potential Impact | Architectural Mitigation | Verification Evidence |
| :--- | :--- | :--- | :--- |
| **Model Weight Tampering** | Execution of malicious, backdoored, or corrupted ONNX weights. | Mandatory SHA-256 hash comparison in `ModelRegistry` before session binding. | `test_model_registry_integrity_rejection` (Raises `ModelIntegrityError`). |
| **Privacy Leak on Model Failure** | Detector crash reveals unmasked faces/plates to public view. | `FailClosedPrivacyPipeline` intercepts exceptions and enforces full-frame blackout. | `test_privacy_pipeline_fail_closed_mode` (Full blackout + alert counter). |
| **Evidence Contamination** | Blurring or enhancing video overwrites original courtroom evidence. | Strict non-destructive separation; pristine frame preserved with immutable SHA-256 digest. | `test_privacy_pipeline_normal_masking...` and `test_enhancement_pipeline...` |
| **Biometric Profiling / Tracking** | Illegal surveillance tracking across municipal boundaries (GDPR Art. 9). | Track IDs are ephemeral stream-scoped integers. Cross-camera matching is structurally forbidden. | `test_multi_camera_isolation_and_cross_camera_prohibition` (`CrossCameraMatchingForbiddenError`). |
| **Cascading Worker Exhaustion** | Camera stall or decoding hang crashes inference server. | Worker process isolation via shared memory (`CameraWorkerSupervisor`) with sub-150ms restart. | `test_supervisor_respawns_dead_worker` (Verified in Phase 1 baseline). |
| **Key Extraction / Memory Dump** | Unauthorized access to encryption master keys. | HKDF key derivation from OS entropy; keys written to disk with `0600` permissions. | `test_key_manager_file_permissions` (Verified in Phase 1 baseline). |

---

## 2. Cryptographic Architecture Summary

1. **Vault Encryption:** Chunks encrypted with **AES-256-GCM**, generating a 128-bit authentication tag per block.
2. **Chain of Custody:** Metadata chained with **SHA-256 Merkle roots**, providing mathematical proof of chronological ordering.
3. **Evidence Derivative Manifests:** `PrivacyEvidenceManifest` and `EnhancementManifest` record both `original_sha256` and `derivative_sha256`, enabling independent forensic auditors to verify authenticity.
