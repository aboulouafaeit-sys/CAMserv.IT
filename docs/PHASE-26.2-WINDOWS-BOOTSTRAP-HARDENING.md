# CAMserv — Phase 26.2: Windows Bootstrap Security & DACL Hardening

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Subsystem:** `camserv.security.identity.bootstrap`  
**Audit Role:** Principal Windows Systems Engineer & OS Security Specialist  
**Status:** FULLY VERIFIED & HARDENED — ATOMIC PRE-DACL CREATION ENFORCED  

---

## 1. Vulnerability Analysis & Attack Vectors

The initial administrator bootstrap token (`data/.bootstrap_token`) is a high-value target: anyone possessing this one-time 256-bit token can register the primary local administrator account and assume total control of the CAMserv surveillance appliance.

Independent adversarial review identified three distinct attack vectors in previous bootstrap generation logic:

1. **TOCTOU Race & Symlink / Junction Substitution:**
   Using `os.open(O_CREAT | O_WRONLY | O_TRUNC)` allows an attacker to pre-create the target file as a symlink or NTFS directory junction, causing the application to follow the link and overwrite arbitrary system files.
2. **Pre-DACL Token Exposure Window:**
   Writing token bytes into the file descriptor *before* applying Windows NTFS access controls leaves the token sitting on disk for milliseconds under default inherited NTFS permissions, readable by unprivileged local users (`BUILTIN\Users`).
3. **Inadequate POSIX Attribute Mapping on Windows:**
   On Windows NTFS, Python's `os.chmod(path, 0o600)` only sets the DOS read-only attribute bit; it does NOT modify NTFS Discretionary Access Control Lists (DACLs).

---

## 2. Phase 26.2 Atomic Hardening Architecture

In Phase 26.2, `LocalAdministratorBootstrap.initiate_bootstrap` was re-engineered into a strict, three-stage hardened pipeline:

```
+-----------------------------------------------------------------------------------------+
|                        PHASE 26.2 BOOTSTRAP GENERATION PIPELINE                         |
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|  [STAGE 1: Pre-Creation Validation & Exclusive Atomicity]                               |
|   * Verify path is not a symlink or reparse point (os.path.islink)                      |
|   * Unlink pre-existing target file to defeat pre-creation substitution                 |
|   * Create 0-byte file with os.O_CREAT | os.O_EXCL | os.O_WRONLY                        |
|   * Close handle immediately (file is completely empty)                                 |
|                                                                                         |
|  [STAGE 2: Pre-DACL Hardening & Verification (NO SECRET ON DISK)]                       |
|   * Windows: Execute icacls /inheritance:r /grant:r "%USERNAME%":F /grant:r "SYSTEM":F   |
|   * Windows: Query icacls output to verify BUILTIN\Users has ZERO permissions           |
|   * POSIX: Apply os.chmod(0o600)                                                        |
|   * If verification fails: delete empty file immediately and abort                      |
|                                                                                         |
|  [STAGE 3: Protected Content Inscription & Sync]                                       |
|   * Open pre-hardened file exclusively for writing                                      |
|   * Inscribe 256-bit cryptographic token                                                |
|   * Flush stream buffer and invoke os.fsync() to force physical write                   |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
```

---

## 3. Windows NTFS DACL Verification

When running on Windows platforms, the resulting security descriptor is inspected:

```cmd
icacls data\.bootstrap_token
```

**Expected DACL Output:**
```
data\.bootstrap_token NT AUTHORITY\SYSTEM:(F)
                      WORKSTATION\MPront:(F)
```

**Verification Rule:**
If the DACL string contains `BUILTIN\Users`, `Everyone`, or `NT AUTHORITY\Authenticated Users`, `LocalAdministratorBootstrap` immediately unlinks the file and raises `BootstrapError("Windows DACL hardening verification failed: unprivileged accounts retain access")`.

---

## 4. Solid-State Storage & Flash Wear-Leveling Reality

> [!WARNING]
> **Physical Flash Erasure Limits:**
> When the bootstrap process completes or expires, CAMserv executes `_shred_token_file()`, performing a multi-pass overwrite (cryptographic pseudo-random bytes, followed by zeroes, followed by `os.fsync()`) before calling `unlink()`.
> 
> However, on modern solid-state storage (SSDs, eMMC, NVMe), the Flash Translation Layer (FTL) uses wear-leveling algorithms that write new data to alternate physical flash blocks. Therefore, software overwrites logical sectors but cannot guarantee that underlying physical NAND cells are instantaneously bleached.
> 
> True physical protection requires full-disk encryption (BitLocker on Windows, LUKS on Linux) or NVMe Secure Erase commands at decommissioning. CAMserv documents this physical boundary with complete transparency.
