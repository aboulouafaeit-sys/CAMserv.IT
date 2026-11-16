# Phase 15: Cross-Platform Credential Storage & Encryption Security

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Security Standards:** OWASP ASVS v4.0.3 & NIST SP 800-132  
**Scope:** Camera Secrets, Master Keys, DPAPI & AES-256-GCM Envelope Encryption  

---

## 1. Threat Model & Secret Protection Objectives

CAMserv stores sensitive secrets including:
1. IP camera RTSP/ONVIF credentials (passwords, tokens).
2. Master encryption keys governing the Digital Forensic Evidence Vault.
3. Central fleet mTLS client certificates and API tokens.

**Threat:** If an adversary obtains an unprivileged local shell or extracts a configuration backup, plaintext secrets must not be readable.

---

## 2. Platform Credential Implementations

```text
                                [CameraCredentialVault]
                                           │
                        ┌──────────────────┴──────────────────┐
                        ▼                                     ▼
             [Linux: AES-256-GCM]                   [Windows: Win32 DPAPI]
       (HKDF Master Key Envelope)             (Machine-Bound CryptProtectData)
                        │                                     │
           POSIX Mode 0600 on Disk              NTFS ACLs + Cryptographic Seal
```

### 2.1 Microsoft Windows: DPAPI Vault (`WindowsDPAPIVault`)
- Uses Win32 `CryptProtectData` and `CryptUnprotectData` via `crypt32.dll`.
- **Binding Scope:** `_CRYPTPROTECT_LOCAL_MACHINE = 0x4`.
  - Secrets are cryptographically bound to the local computer's TPM/LSA security state.
  - Another machine or an offline disk extraction cannot decrypt the payload.
- **Zero-Dependency Architecture:** Implemented in pure Python via standard library `ctypes`. No external pywin32 dependency is required.

### 2.2 Linux: AES-256-GCM Envelope Vault (`StandardSoftwareCredentialVault`)
- Derives 256-bit purpose-bound encryption keys using HKDF-SHA256 from the master secret (`CAMSERV_MASTER_KEY`).
- Encrypts credential records with 96-bit random nonces and authenticated tag validation.
- Files stored with restrictive POSIX permissions (`0600`).

---

## 3. Cryptographic Verification & Tamper Tests

`tests/test_platform_cross_platform.py::test_credential_vault_protection_roundtrip` verified:
- **Roundtrip Encryption/Decryption:** 100% data recovery on authentic payloads.
- **Tamper Detection:** Inverting a single bit in the ciphertext causes immediate cryptographic authentication failure, preventing ciphertext manipulation attacks.
