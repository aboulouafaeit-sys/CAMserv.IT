# CAMserv Digital Forensics Architecture & Chain of Custody
**Document ID:** FOR-ARCH-2026-001  
**Author:** Principal Forensic Systems Architect & Chief Cryptographer  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Compliance Standards:** ISO/IEC 27037 (Digital Evidence Handling), NIST SP 800-86, Federal Rules of Evidence Rule 902(14)

---

## 1. Forensic Integrity Principles

Digital video surveillance used in criminal proceedings, workplace investigations, or insurance arbitration must withstand rigorous adversarial scrutiny in court.

CAMserv enforces three non-negotiable forensic pillars:
1. **Pristine Raw Preservation:** The original raw bitstream received from the camera is preserved in its exact uncompressed or native H.264/H.265 compressed state. Software ISP enhancements (LAB CLAHE) and visual HUD overlays (contours, 3D rings, bounding cards) are recorded as **separate derived data layers** and NEVER burnt into the evidentiary master file.
2. **Cryptographic Sealing:** Video chunks and metadata are sealed using AES-256-GCM envelope encryption, chained in a continuous SHA-256 Merkle tree, and signed with asymmetric Ed25519 digital signatures.
3. **Immutable Chain of Custody:** Every access, export, redaction, or viewing event generates a tamper-evident audit record anchored in the cryptographic log.

---

## 2. Multi-Layer Evidentiary Separation

```
+-------------------------------------------------------------------------------+
|                       SEALED FORENSIC PACKAGE (.vault)                        |
|                                                                               |
|  +---------------------------+  +----------------------+  +----------------+  |
|  | Layer 1: Raw Bitstream    |  | Layer 2: ISP Vectors |  | Layer 3: HUD   |  |
|  | Native H.264 / H.265 GOPs |  | CLAHE Parameters &   |  | Segmentation   |  |
|  | (100% Unaltered Evidence) |  | Calibration Offsets  |  | Polygons & DTOs|  |
|  +-------------+-------------+  +----------+-----------+  +-------+--------+  |
|                |                           |                      |           |
|                +---------------------------+----------------------+           |
|                                            v                                  |
|                             +-----------------------------+                   |
|                             | SHA-256 Merkle Tree Root    |                   |
|                             +--------------+--------------+                   |
|                                            v                                  |
|                             +-----------------------------+                   |
|                             | Ed25519 Asymmetric Signature|                   |
|                             +-----------------------------+                   |
+-------------------------------------------------------------------------------+
```

### Evidentiary Layer Definitions
* **Layer 1 (Raw Evidence):** The unaltered camera bitstream as captured over RTSP. Admissible under Federal Rules of Evidence Rule 902.
* **Layer 2 (ISP Enhancement Metadata):** Mathematical transformation matrices, luminance lookup tables, and CLAHE clip parameters allowing forensic examiners to reproduce or revert contrast boosting deterministically.
* **Layer 3 (Analytical Annotations):** JSON metadata containing YOLOv8 segmentation coordinates, 17-keypoint skeletal angles, calibrated threat probabilities, and operator notes.

---

## 3. Cryptographic Sealing & Verification Workflow

### 3.1 Sealing Specification
1. **Chunk Encryption:** Every 5-second video segment is encrypted with AES-256-GCM using an ephemeral 256-bit DEK:
   $$\mathbf{C}_i, \mathbf{T}_i = \text{AES-GCM}_{\text{DEK}_i}(\mathbf{P}_i, \mathbf{IV}_i, \mathbf{AAD}_i)$$
   Where $\mathbf{AAD}_i$ (Additional Authenticated Data) binds the camera UUID, monotonic sequence number, and timestamp to the ciphertext $\mathbf{C}_i$ and authentication tag $\mathbf{T}_i$.
2. **Merkle Tree Construction:**
   Leaf nodes $h_i = \text{SHA-256}(\mathbf{C}_i \parallel \mathbf{T}_i)$.
   Parent nodes $h_{parent} = \text{SHA-256}(h_{left} \parallel h_{right})$.
   The resulting Merkle Root $R_{incident}$ uniquely represents the entire chronological sequence.
3. **Asymmetric Digital Signature:**
   The platform's private Ed25519 key (stored in hardware TPM or root-protected enclave) signs the manifest:
   $$\mathbf{\Sigma} = \text{Ed25519}_{\text{PrivKey}}(R_{incident} \parallel \text{Metadata})$$

### 3.2 Standalone Verification Tooling
Any third-party auditor, court official, or external defense counsel can verify evidence offline without installing CAMserv:
```bash
camserv-verify --package INCIDENT-2026-11-14-001.vault --public-key camserv_ed25519.pub
```
Verification checks:
1. Validates Ed25519 signature against published public key.
2. Reconstructs SHA-256 Merkle root from decrypted chunks; detects bit-level tampering or deleted frames.
3. Confirms AES-256-GCM authentication tags match.
