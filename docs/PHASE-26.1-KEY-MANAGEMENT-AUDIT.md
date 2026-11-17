# CAMserv — Phase 26.1: Cryptographic Key Management Audit
## Key Hierarchy, Storage Isolation, Derivation Contexts & Offline Theft Resistance

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Phase:** 26.1 — Identity Security Verification & Adversarial Hardening  
**Audited Subsystems:** `camserv.security.identity.mfa`, `camserv.security.identity.secrets`, `camserv.security.encryption`, `camserv.security.keys`  
**Standards:** NIST SP 800-57 (Key Management), NIST SP 800-133 (Cryptographic Key Generation)  
**Status:** **AUDITED & QUALIFIED: STRONG KEY SEPARATION & THEFT RESISTANCE**  

---

## 1. Cryptographic Key Inventory

| Key Identifier | Purpose / Scope | Algorithm | Derivation / Generation Method | Storage Location | Protection Mechanism |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **`master_key`** | Root secret for appliance encryption | 256-bit AES | CSPRNG (`secrets.token_bytes(32)`) | `data/secrets/master.key` or `CAMSERV_MASTER_KEY` env var | File mode `0600` / OS environment variable |
| **`camera_vault_key`** | RTSP / ONVIF credential encryption at rest | AES-256-GCM | HKDF-SHA256 (`info="camserv-v1-camera-credentials"`, `salt="camserv-camera-credential-salt-v1"`) | `data/secrets/camera_vault.key` (or derived from master) | File mode `0600` / HKDF context separation |
| **`mfa_secret_key`** | TOTP seed encryption at rest | AES-256-GCM | CSPRNG 256-bit / HKDF | `data/secrets/identity_mfa.key` | File mode `0600` / GCM authenticated tag |
| **`signing_key`** | Evidence and manifest signing | Ed25519 | Ed25519 Private Key generation | `data/keys/signing_key_v1.pem` | Encrypted at rest via AES-GCM or `0600` PEM |
| **`bootstrap_token`** | One-time local admin setup token | 256-bit Hex | CSPRNG (`secrets.token_hex(32)`) | `data/.bootstrap_token` | Ephemeral (15m TTL), memory-shredded upon use |

---

## 2. Key Separation & Derivation Analysis

CAMserv enforces strict cryptographic key separation using RFC 5869 HKDF-SHA256:
$$\text{DerivedKey} = \text{HKDF-Extract-and-Expand}(\text{MasterKey}, \text{Salt}, \text{Info}, \text{Length}=32)$$

### Context Separation Guarantees:
1. `camserv-v1-camera-credentials` produces a key usable **only** for camera secrets. Even if a camera key were leaked via a compromised camera driver, it cannot decrypt TOTP seeds or judicial evidence archives.
2. `camserv-v1-identity-mfa` produces a distinct key used exclusively for MFA secret envelopes.
3. Cryptographic signing keys (Ed25519) and symmetric encryption keys (AES-256-GCM) are strictly segregated in `KeyManager`, preventing key re-use across incompatible cryptographic primitives.

---

## 3. Database Copy / Offline Theft Resistance

### Threat Scenario:
An adversary gains unauthorized access to a backup copy or cold disk image of `data/identity.db` (e.g. via stolen USB backup or unprivileged backup operator).

### Adversarial Verification Result:
- In `test_key_theft_offline_database_theft`:
  - TOTP seeds stored in `totp_credentials.encrypted_secret` are encrypted with AES-256-GCM.
  - Camera credentials stored in `CameraCredentialProtection` are encrypted with AES-256-GCM.
  - When `data/identity.db` was mounted on a secondary testbed without the corresponding `data/secrets/*.key` files:
    - Decryption attempts failed unconditionally with `cryptography.exceptions.InvalidTag`.
    - Zero plaintext credential recovery was possible.
- **Verdict:** **VERIFIED**. Stealing the SQLite database alone does not expose encrypted credentials.

---

## 4. Key Exposure & Failure Behavior

### 4.1 Log & Error Tracing Hygiene
- Inspected exception handling in `MFASecretProtector` and `CameraCredentialProtection`.
- Decryption failures raise generic or standard `InvalidTag` exceptions without logging the key, nonce, or ciphertext.
- Master key string values are never logged by `structlog`.

### 4.2 Failure Behavior (Fail Closed)
- If key files are missing, corrupted, or unreadable:
  - Encryption services raise `KeyManagementError` or `ValueError` immediately upon service initialization.
  - The service **fails closed**: no unencrypted secrets are written to storage, and no unauthenticated access is permitted.
  - Surveillance camera ingestion and recording continue using already-running pipeline buffers.

---

## 5. Identified Limitations & Future Recommendations

1. **Software Key Storage Boundary:** While file permissions are set to `0600`, key files currently reside on the local filesystem. A root/SYSTEM-level local administrator can read both the keys and the database.
2. **TPM 2.0 / Hardware Enclave Recommendation:** For enterprise appliance qualification in Phase 27/28, bind the master key directly to physical TPM 2.0 Non-Volatile (NV) RAM indices or Windows DPAPI machine keys to prevent offline memory-dump theft.
