# CAMserv Security Architecture & Threat Model

**Document ID:** ARCH-SECURITY-2026-001  
**Classification:** Cybersecurity Architecture & Threat Model  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Threat Model & Security Invariants

CAMserv is engineered to operate in hostile physical and network environments where cameras, edge appliances, or network links may be subject to physical interception, cyber attacks, or evidentiary tampering.

### Threat Assumptions (Attacker Capabilities):
1. **Compromised IP Camera:** An attacker controls an IP camera firmware and attempts to send malformed RTSP/ONVIF packets, exploits, or spoofed video streams.
2. **Network Interception / MITM:** An attacker monitors or injects packets on the LAN or WAN link between appliances and CAMserv Central.
3. **Malicious Insider / Rogue Operator:** An operator with valid credentials attempts to delete incriminating footage, export raw unmasked video without authorization, or forge audit records.
4. **Supply Chain Attack:** An attacker attempts to deliver a weaponized OTA update package or corrupted model weights.

### Core Security Invariants:
- **Process Sandboxing:** Ingestion decoders run in isolated subprocesses so memory corruption in FFmpeg cannot compromise core authentication or encryption keys.
- **Fail-Closed Privacy:** Video egress paths fail safe to full-frame blackout.
- **Tamper-Evident Hash Chaining:** Audit logs and evidence records are cryptographically chained; modification or deletion of any entry invalidates the entire chain.
- **Dual-Control Enforcement:** Raw unmasked video cannot be exported by a single administrator; two distinct role signers must authorize the action.
- **Signed OTA Manifests:** Updates must be cryptographically signed by the official CAMserv release authority using Ed25519. Unsigned or mismatched packages are rejected.

---

## 2. Cryptographic Implementations

| Subsystem | Algorithm / Primitive | Purpose | Key Management |
| :--- | :--- | :--- | :--- |
| **Evidence Encryption** | AES-256-GCM (AEAD) | Encrypts stored video chunks and forensic snapshots | KeyManager versioned master keys (PBKDF2/HKDF derived) |
| **Evidence Signatures** | Ed25519 (RFC 8032) | Asymmetric digital signatures on export manifests | Stored in PEM format in secure key vault (`/etc/camserv/keys`) |
| **Audit Log Chaining** | SHA-256 (FIPS 180-4) | Merkle hash chaining across all logged security actions | Genesis anchor `0000...0000`; continuous state machine |
| **Session Authentication**| JWT (HMAC-SHA256) | REST API session tokens and WebSocket authorization | Configurable secret key with 30m access / 7d refresh |
| **Appliance Identity** | Ed25519 Challenge-Response | Mutual authentication of edge nodes to Central | Unique device keypair generated during first boot |
| **Password Storage** | PBKDF2-HMAC-SHA256 | Hashing user credentials (100,000 iterations) | Salted per-user in SQLite database |

---

## 3. Role-Based Access Control (RBAC) Matrix

The system enforces a granular 6-role hierarchy across all API endpoints:

| Role | Operational Scope & Permissions |
| :--- | :--- |
| **SUPER_ADMIN** | Full global fleet configuration, tenant management, user provisioning, global audit inspection. |
| **ADMIN** | Local appliance configuration, camera registration, retention policy setup, user management. |
| **OPERATOR** | Live view monitoring, PTZ control, recording playback, event triage and incident verification. |
| **AUDITOR** | Independent verification of audit log hash chains, evidence package verification, read-only logs. |
| **FORENSIC_EXPERT**| First co-signer for raw unmasked evidence export, investigation case management. |
| **DPO (Data Protection Officer)**| Second mandatory co-signer for raw evidence export under GDPR Art. 25, privacy policy audits. |
| **VIEWER** | Read-only access to privacy-masked live streams and authorized notifications. |
