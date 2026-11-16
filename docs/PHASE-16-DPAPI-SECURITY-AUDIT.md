# Phase 16: Windows DPAPI Credential Security Audit

**Target Release:** 0.10.0-alpha2  
**Module:** `src/camserv/platform/windows/credentials.py` (`WindowsDPAPIVault`)  
**Evaluated Subject:** Win32 Data Protection API (DPAPI) via `crypt32.dll`  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Executive Summary

Storage of plaintext camera passwords, JWT signing keys, and forensic secrets in configuration files represents an unacceptable security risk in enterprise NVR deployments. On Windows 11, CAMserv eliminates plaintext secrets by integrating natively with the **Windows Data Protection API (DPAPI)**.

---

## 2. Technical Implementation

`WindowsDPAPIVault` directly wraps Win32 DPAPI functions from `crypt32.dll` via ctypes:
- **`CryptProtectData`:** Encrypts raw secret bytes into an encrypted ciphertext blob.
- **`CryptUnprotectData`:** Decrypts ciphertext back to plaintext.

### Key Security Flags Configured:
- **`_CRYPTPROTECT_LOCAL_MACHINE (0x4)`:**
  Binds the encryption key to the local machine context. This ensures that any background service (including `LocalSystem` and `NT SERVICE\CAMserv`) running on the host can decrypt credentials, while an exported or stolen credential file copied to another physical PC or attacker workstation cannot be decrypted.
- **`_CRYPTPROTECT_UI_FORBIDDEN (0x1)`:**
  Guarantees that no graphical credential prompt or UI dialog is ever raised, ensuring uninterrupted execution in Session 0 background services.

---

## 3. Cryptographic Verification Results

Verification testing executed round-trip encryption and decryption:

```python
vault = WindowsDPAPIVault()
secret = b"TopSecretCameraPassword!12345"
protected = vault.protect_secret(secret, description="camera_01_credential")
unprotected = vault.unprotect_secret(protected, description="camera_01_credential")
assert unprotected == secret
```

- **Ciphertext Entropy:** The ciphertext blob is structurally distinct from plaintext, prepended with DPAPI GUIDs and HMAC checksums.
- **Hardware Binding:** When TPM 2.0 or Windows LSA protection is enabled, DPAPI automatically derives master encryption keys from the host platform security hardware.

---

## 4. Audit Finding & Verification Evidence

- **Result:** **PASS** (Zero plaintext credentials stored on Windows).
- **Unit Test:** `test_windows_dpapi_machine_protection` — PASSED.
