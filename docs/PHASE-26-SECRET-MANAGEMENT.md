# CAMserv — Phase 26: Secret Management & Camera Credential Protection
## Cryptographic Key Separation, AES-256-GCM At Rest & Zero-Leakage Redaction

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Phase:** 26 — Identity & Access Security Foundation  
**Cryptographic Standards:** AES-256-GCM (NIST SP 800-38D), HKDF-SHA256 (RFC 5869)  
**Author:** Lead Cryptographic Systems Engineer  
**Status:** COMPLETE & VERIFIED  

---

## 1. Secrets Management Scope & Threat Exposure

Surveillance systems handle highly sensitive secrets whose compromise would grant attackers unauthorized control over physical building security:
1. **Camera Authentication Credentials:** RTSP passwords, ONVIF administrative credentials, PTZ control tokens.
2. **Multi-Factor Secrets:** TOTP base32 seed secrets.
3. **Appliance Bootstrap Tokens:** One-time initial administrative setup credentials.
4. **Forensic Evidence Signing Keys:** Asymmetric keys used for sealing court evidence.

Prior to Phase 26, RTSP stream URLs containing cleartext passwords (e.g. `rtsp://admin:P@ssword@192.168.1.100/ch0`) could be inadvertently serialized into REST API responses, diagnostic logs, or JSON status dumps.

---

## 2. Cryptographic Key Hierarchy & Separation

CAMserv enforces strict cryptographic key separation so that compromise of one operational key never exposes keys used for other subsystems.

```mermaid
flowchart TD
    Master["Master Secret / Entropy\n(256-bit Key / data/secrets/master.key)"]
    
    subgraph HKDF["RFC 5869 HKDF-SHA256 Key Derivation"]
        HKDF1["HKDF('camserv-v1-camera-credentials')"]
        HKDF2["HKDF('camserv-v1-identity-mfa')"]
        HKDF3["HKDF('camserv-v1-evidence')"]
    end

    CameraKey["Camera Credential Key\n(AES-256-GCM)"]
    MFAKey["TOTP Secret Key\n(AES-256-GCM)"]
    EvidenceKey["Evidence Vault Key\n(AES-256-GCM)"]

    Master --> HKDF1
    Master --> HKDF2
    Master --> HKDF3

    HKDF1 --> CameraKey
    HKDF2 --> MFAKey
    HKDF3 --> EvidenceKey

    CameraKey --> Vault["Camera Credential Vault\n(Encrypted RTSP/ONVIF URLs)"]
    MFAKey --> TOTPStore["Durable TOTP Store\n(Encrypted Seeds)"]
    EvidenceKey --> JudicialVault["Forensic Evidence Archive\n(Sealed Court Packages)"]
```

---

## 3. Camera Credential Protection Vault (`CameraCredentialProtection`)

### 3.1 Authenticated Encryption at Rest
Device credentials and raw stream URLs are encrypted using **AES-256-GCM**:
- Nonce: 96-bit cryptographically random nonce generated per encryption operation (`secrets.token_bytes(12)`).
- Integrity Tag: 128-bit GCM authentication tag verifying ciphertext authenticity.
- Serialized Envelope: Stored as a compact JSON base64 container `{"n": "<nonce_b64>", "c": "<ciphertext_b64>"}`.
- Re-use Prevention: Nonce reuse is strictly prohibited.

### 3.2 Robust URL Password Scrubbing (`redact_url`)
A common vulnerability in surveillance software is naive regex replacement that fails when camera passwords contain characters such as `@`, `:`, or slashes. CAMserv implements a robust parser:
1. Decomposes the URL authority via `urllib.parse.urlsplit`.
2. Splits user authentication using right-split on `@` (`netloc.rsplit("@", 1)`), accurately separating user credentials from the target host even if the password contains multiple `@` characters.
3. Replaces the password with `***REDACTED***` while preserving username, host, port, path, and query parameters:
   $$\text{rtsp://admin:P@ss:w0rd!123@192.168.1.100:554/ch0} \longrightarrow \text{rtsp://admin:***REDACTED***@192.168.1.100:554/ch0}$$

### 3.3 Deep Recursive Object Redaction
Before any data payload is returned to a client or logged:
- `redact_sensitive_data()` recursively traverses dictionaries, lists, and strings.
- Keys matching sensitive patterns (`password`, `secret`, `token`, `api_key`, `credential`, `private_key`) are immediately masked with `***REDACTED***`.
- Keys representing URLs (`url`, `rtsp_url`, `stream_url`) are automatically passed through `redact_url()`.

---

## 4. Local Filesystem Key Security
- **File Mode Permissions:** All generated key files (`data/secrets/camera_vault.key`, `data/secrets/identity_mfa.key`, `data/.bootstrap_token`) are created with restrictive permissions `0600` (readable and writable only by the CAMserv service account).
- **In-Memory Hygiene:** Sensitive strings are scrubbed or overwritten where possible, and plaintext passwords are never cached in long-lived state objects.
