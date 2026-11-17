# CAMserv — Phase 26.2: NIST SP 800-63B Alignment & Identity Assurance Review

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Subsystems:** `camserv.security.identity.password`, `mfa`, `authorization`, `models`  
**Audit Role:** Principal Cryptographer & Regulatory Compliance Auditor  
**Status:** FULLY REVIEWED — TRUTHFUL BOUNDARY DELINEATION ESTABLISHED  

---

## 1. Executive Summary: Terminology & Standards Transparency

In commercial security marketing, claims of "NIST SP 800-63B compliance" or "AAL2/AAL3 certification" are frequently made without independent assessment evidence or without honoring the strict cryptographic definitions established by the National Institute of Standards and Technology (NIST).

In Phase 26.2, CAMserv establishes a **strict policy of architectural honesty**:
- Internal labels (such as `AuthAssuranceLevel.AAL1`, `AAL2`, `AAL3`) reflect **internal application authorization tiers**, NOT formal federal certifications.
- CAMserv explicitly distinguishes **two-factor authentication (2FA)** from **phishing-resistant authentication**.
- CAMserv makes **NO formal claim of NIST certification or federal AAL compliance**.

---

## 2. NIST SP 800-63B Revision 4 Alignment Matrix

The following table delineates the exact alignment between NIST SP 800-63B criteria and the actual implementations in CAMserv:

| Capability / Attribute | NIST SP 800-63B Rev 4 Requirement | CAMserv Phase 26.2 Implementation | Actual Alignment Status |
| :--- | :--- | :--- | :--- |
| **Password Hashing** | Memory-hard KDF (Argon2id, PBKDF2, scrypt) | RFC 9106 Argon2id ($m=65536, t=2, p=4$) + dual-verification | **ALIGNED** (State-of-the-art software implementation) |
| **Password Policy** | Min 8 chars, 64 max, no arbitrary composition rules | Min 12 chars, 128 max, common dictionary check, passphrase exemption | **ALIGNED** (Follows NIST passphrase guidelines) |
| **Multi-Factor Auth (2FA)** | Two distinct factors (Knowledge + Possession) | Password + RFC 6238 TOTP / Single-use recovery codes | **ALIGNED** (Standard two-factor possession) |
| **Replay Resistance** | One-time code invalidation | TOTP time-step cache rejects replayed codes in valid window | **ALIGNED** (Replay protection implemented) |
| **Phishing Resistance** | Verifier-impersonation resistance (origin binding) | TOTP codes can be intercepted by reverse proxies (Evilginx) | **NOT PHISHING-RESISTANT** (Standard TOTP limitation) |
| **Hardware Passkeys / FIDO2** | Hardware cryptographic tokens (ES256/RS256) | `PasskeyManager` implements option generation hooks only | **PROVISIONAL ONLY** (Hooks exist; verification omitted) |
| **Formal Certification** | Accredited laboratory audit & CMVP validation | No external federal laboratory audit conducted | **NO COMPLIANCE CLAIMED** (Internal tiering only) |

---

## 3. Cryptographic Authenticator Truthfulness

### 3.1 Why TOTP Is Not Phishing-Resistant
RFC 6238 Time-Based One-Time Passwords (TOTP) provide strong possession verification against offline credential theft. However:
- A malicious actor using an automated reverse proxy (e.g. Evilginx) can present a legitimate-looking login page to an operator.
- When the operator enters their username, password, and 6-digit TOTP code, the reverse proxy immediately forwards these credentials to the real CAMserv appliance.
- The appliance issues a valid session token, which the reverse proxy captures.
- **Therefore, TOTP does not bind the authentication exchange to the TLS origin**, and must never be advertised as "phishing-resistant."

### 3.2 WebAuthn / Passkey Implementation Reality
In Phase 26.1 and 26.2:
- `PasskeyManager` generates standard WebAuthn challenge dictionaries (`create_registration_options` and `create_assertion_options`).
- However, CAMserv does NOT yet include a full Relying Party (RP) cryptographic verification engine (CBOR/COSE decoding, attestation certificate path validation, client data JSON origin verification).
- Calling verification entry points explicitly raises `NotImplementedError`, preventing deceptive claims of passkey authentication.

---

## 4. Internal Authorization Tier Mapping

Within CAMserv's codebase, `AuthAssuranceLevel` serves as a strict internal privilege gate:

```python
class AuthAssuranceLevel(str, enum.Enum):
    AAL1 = "aal1"  # Single-factor authenticated session (Password only)
    AAL2 = "aal2"  # Multi-factor authenticated session (Password + TOTP / Recovery Code)
    AAL3 = "aal3"  # Reserved for future hardware cryptographic passkeys
```

- High-impact surveillance operations (`AAL2_MANDATORY_PERMISSIONS`: `evidence:export`, `system:firmware_update`, `emergency:lift`, `account:role_change`) strictly reject `AAL1` sessions.
- Users must complete a step-up challenge to elevate their session to `AAL2` before these actions are permitted.

---

## 5. Roadmap to True NIST AAL3 Phishing Resistance

To achieve genuine phishing-resistant AAL3 compliance in future major releases:
1. Integrate an accredited Python WebAuthn Relying Party library (such as `py_webauthn` or Yubico `fido2`).
2. Implement strict origin validation, RP ID matching, and cryptographic signature counter verification.
3. Bind root master encryption keys to physical appliance TPM 2.0 endorsement credentials.
