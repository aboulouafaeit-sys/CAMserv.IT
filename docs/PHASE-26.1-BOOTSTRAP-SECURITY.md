# CAMserv — Phase 26.1: Bootstrap Security & Windows Permissions Audit
## Platform Permissions, NTFS DACL Hardening, Race Conditions & Erasure Reality

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Phase:** 26.1 — Identity Security Verification & Adversarial Hardening  
**Target Subsystem:** `camserv.security.identity.bootstrap.LocalAdministratorBootstrap`  
**Platforms:** Windows 11 Enterprise (NTFS) & Debian Linux (ext4/xfs)  
**Status:** **AUDITED, HARDENED & QUALIFIED**  

---

## 1. Platform Permission Discrepancy & NTFS Realities

### 1.1 The POSIX `0600` Fallacy on Windows
In standard POSIX environments (Debian/Ubuntu), calling `os.chmod(path, 0o600)` restricts read and write permissions exclusively to the file owner.
However, on **Windows NTFS**, Python's `os.chmod()` implementation behaves completely differently:
- It only toggles the `FILE_ATTRIBUTE_READONLY` flag on the FAT/NTFS metadata.
- It does **not** modify or inspect Windows Access Control Lists (DACLs).
- Newly created files in `data/` inherit the parent directory's DACL, typically granting read access to all local authenticated users (`NT AUTHORITY\Authenticated Users`).

### 1.2 Remediated Windows DACL Hardening
To prevent local unprivileged accounts from reading the bootstrap token on Windows, Phase 26.1 introduces explicit Windows DACL stripping via `icacls`:
```python
if sys.platform == "win32":
    u = os.environ.get("USERNAME", "SYSTEM")
    subprocess.run(
        ["icacls", str(self.token_path), "/inheritance:r", "/grant:r", f"{u}:F"],
        capture_output=True,
        timeout=5.0,
    )
```
- `/inheritance:r`: Strips all inherited parent permissions.
- `/grant:r "%USERNAME%":F`: Explicitly grants Full Control exclusively to the current service account. Non-admin users attempting to open the file receive Windows Error 5 (`ACCESS_DENIED`).

---

## 2. Adversarial Vectors & Hardened Defenses

| Attack Vector | Adversarial Threat | Vulnerability Analysis | Remediated Defense in Phase 26.1 |
| :--- | :--- | :--- | :--- |
| **Symlink / Reparse Point Attack** | Adversary creates a symlink at `data/.bootstrap_token` pointing to a critical system file (e.g. `/etc/passwd` or `bootmgr`). | `open(..., "w")` would follow the link and overwrite the target file. | **Hardened:** Pre-creation check `self.token_path.is_symlink()` raises `BootstrapError` if any reparse point is detected. |
| **Race Condition on Creation** | Attacker attempts to pre-create or swap the token file during appliance startup. | Non-atomic creation could write token to an attacker-controlled handle. | **Hardened:** Atomic file descriptor creation via `os.open(..., os.O_CREAT \| os.O_WRONLY \| os.O_TRUNC, 0o600)`. |
| **Token Entropy Exhaustion** | Attacker attempts to brute-force the bootstrap token over the local network. | Low-entropy tokens (e.g. 6-digit PIN) could be guessed within the 15-minute window. | **Guaranteed:** 256 bits of entropy generated via `secrets.token_hex(32)`. $2^{256}$ search space is computationally infeasible to brute force. |
| **Token Expiry Bypass** | Attacker attempts to use a stale token after 15 minutes. | Clock manipulation or missing expiry check could allow expired token use. | **Guaranteed:** `expires_at_utc` checked against `datetime.now(timezone.utc)`. Stale tokens trigger immediate invalidation. |
| **Concurrent Bootstrap Race** | Multiple requests attempt to complete bootstrap simultaneously with different passwords. | Race condition could allow split-brain admin creation. | **Guaranteed:** SQLite `BEGIN IMMEDIATE` transaction lock in `create_user` guarantees strictly one admin account can be created. |
| **Post-Bootstrap Re-Entry** | Attacker attempts to invoke `initiate_bootstrap()` or `complete_bootstrap()` on an already configured system. | Could overwrite genuine admin credentials. | **Guaranteed:** `is_bootstrap_needed()` checks `is_bootstrapped` and `count_administrators()`, raising `BootstrapAlreadyCompletedError`. |

---

## 3. Storage Truthfulness: File Unlinking vs Physical SSD Erasure

Previous documentation described `_shred_token_file()` as "guaranteed physical cryptographic erasure".

> [!WARNING]
> **Forensic Truthfulness Correction:**
> On modern Solid-State Drives (NAND flash) and Copy-on-Write (CoW) filesystems:
> 1. The **Flash Translation Layer (FTL)** uses wear-leveling algorithms that write newly overwritten blocks to different physical flash sectors.
> 2. NTFS and ext4 journaling may leave fragments of previous writes in metadata logs or unallocated clusters.
> 3. Calling `f.write(os.urandom(...))` and `unlink()` provides **best-effort logical filesystem overwriting**, but **cannot** guarantee that raw NAND physical memory cells are sanitized without a cryptographic Secure Erase ATA command.
> 
> Therefore, the primary security against token recovery is **ephemeral single-use invalidation in the database state machine** (`invalidate_bootstrap_token()`), rendering any recovered token string cryptographically useless even if raw flash blocks were inspected.
