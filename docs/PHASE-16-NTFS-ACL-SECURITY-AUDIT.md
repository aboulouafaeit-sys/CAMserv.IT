# Phase 16: NTFS Access Control List (ACL) Security Audit

**Target Release:** 0.10.0-alpha2  
**Module:** `src/camserv/platform/windows/filesystem.py` (`WindowsFilesystem`)  
**Evaluated Subject:** Directory Permissions, `icacls.exe`, LPE Prevention  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Executive Summary

Filesystem access controls on Windows NVR deployments are critical to prevent unauthorized local users from tampering with evidence files, viewing private video recordings, or performing local privilege escalation (LPE) via file overwrites.

---

## 2. NTFS Security Policy & Directory Hierarchy

CAMserv strictly segments its directory hierarchy across standard Windows filesystem roots:

| Directory | Default Path | Required Permissions | Purpose |
| :--- | :--- | :--- | :--- |
| **Binaries** | `%ProgramFiles%\CAMserv\bin` | `Administrators:(F)`, `SYSTEM:(F)`, `Users:(RX)` | Service binaries and executables |
| **Configuration** | `%ProgramData%\CAMserv\config` | `Administrators:(F)`, `SYSTEM:(F)`, `ActiveUser:(F)` | Configuration settings |
| **Recordings** | `%ProgramData%\CAMserv\recordings` | `Administrators:(F)`, `SYSTEM:(F)`, `ActiveUser:(F)` | Video evidence segments |
| **Forensic Vault** | `%ProgramData%\CAMserv\vault` | `Administrators:(F)`, `SYSTEM:(F)`, `ActiveUser:(F)` | Master keys & signatures |
| **Audit Logs** | `%ProgramData%\CAMserv\logs` | `Administrators:(F)`, `SYSTEM:(F)`, `ActiveUser:(F)` | Tamper-proof audit trails |

---

## 3. Enforcement Mechanism via `icacls.exe`

`WindowsFilesystem.secure_directory(path, is_sensitive=True)` applies restrictive Access Control Lists:
1. **Inheritance Stripping:** Removes inherited permissions to eliminate unintended access inherited from `%ProgramData%`.
2. **Explicit Grants:**
   - `icacls <dir> /inheritance:r` (Strip inherited ACEs)
   - `icacls <dir> /grant:r "SYSTEM:(OI)(CI)F"` (LocalSystem full control)
   - `icacls <dir> /grant:r "Administrators:(OI)(CI)F"` (Administrators full control)
   - `icacls <dir> /grant:r "%USERNAME%:(OI)(CI)F"` (Active service/user account full control)
3. **Transient Files Handling:**
   To avoid file locking or `[WinError 5] Access is denied` during atomic writes (`os.replace`), permissions are applied exclusively to permanent directories rather than ephemeral temporary files.

---

## 4. Audit Finding & Verification Evidence

- **Result:** **PASS** (Zero permissive world-writable permissions on sensitive directories).
- **Unit Test:** `test_windows_filesystem_ntfs_acls` — PASSED.
