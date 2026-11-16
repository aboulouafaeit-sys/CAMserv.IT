# Phase 15: Portability Audit & Operating-System Assumption Analysis

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Scope:** Exhaustive Audit of Linux-Specific and Windows-Specific Assumptions in Source Code  
**Audit Standard:** Posix / Win32 API Neutrality & CWE-676 Portability Review  

---

## 1. Audit Methodology & Scope

An automated and manual inspection of all Python modules in `src/camserv/` was conducted to identify:
1. Implicit assumptions about POSIX/Linux file paths, permissions, and signals.
2. Direct invocation of Linux-only binaries (`systemctl`, `journalctl`, `udevadm`).
3. Absence of native Windows counterparts for service management, hardware acceleration, camera enumeration, and credential protection.

---

## 2. Identified Linux-Specific Assumptions & Remediation Plan

| Module / File | Identified Linux Assumption | Severity | Platform Risk | Remediation Strategy |
|---|---|---|---|---|
| `camserv.storage.init_service` | Hardcoded `/var/lib/camserv`, `/var/log`, `/etc/camserv` | **HIGH** | Directory creation fails or writes to non-standard paths on Windows. | Abstract via `PlatformFilesystem.get_standard_paths()`. Resolves to `%ProgramData%\CAMserv` on Windows. |
| `camserv.storage.init_service` | `os.chmod(d, 0o700)` and `os.chmod(d, 0o750)` | **MEDIUM** | Has no effect on NTFS; leaves permissions open on Windows. | Implement `WindowsFilesystem.secure_directory()` applying NTFS ACLs via `icacls`. |
| `camserv.security.keys` | `os.chmod(path, stat.S_IRUSR \| stat.S_IWUSR)` | **HIGH** | Master encryption keys readable by standard Windows local users. | Protect master encryption keys using Windows `DPAPI` (`CryptProtectData`) on Windows. |
| `camserv.deploy.supervisor` | Relies on systemd unit names and `systemctl` restart semantics | **MEDIUM** | Inability to supervise background daemons on Windows. | Provide `WindowsServiceManager` interacting with Windows Service Control Manager (`sc.exe`). |
| `camserv.acquisition.camera` | Optical camera index `0` bound to V4L2 backend | **MEDIUM** | Inefficient capture or device negotiation on Windows webcams. | Bind Windows local cameras to Microsoft Media Foundation (`CAP_MSMF`) or DirectShow (`CAP_DSHOW`). |
| `camserv.platform.hardware` | Reads `/sys/class/thermal` and `/proc/cpuinfo` | **LOW** | Thermal probing fails on non-Linux hosts. | Route thermal and CPU queries through `WindowsHardwareProber` using WMI / CimInstance and `nvidia-smi`. |
| `camserv.pipeline.engine` | Uses POSIX signal handling (`SIGTERM`, `SIGHUP`) | **LOW** | `SIGHUP` not supported on Windows. | Guard `signal.SIGHUP` with `hasattr(signal, "SIGHUP")` and support `win32` console control handlers. |

---

## 3. Identified Windows-Specific Considerations

1. **Path Separator Neutrality:**
   - All modules must strictly use `pathlib.Path` or `os.path.join()`. Forward slashes (`/`) and backward slashes (`\`) are normalized cleanly by `Path`.
2. **Case Sensitivity:**
   - Linux filesystems (ext4) are case-sensitive; Windows NTFS is case-preserving but case-insensitive by default. Canonical identifier lowercasing (`cam_id.lower()`) must be maintained across all modules.
3. **File Locking in SQLite:**
   - Windows strictly locks open SQLite files. Code must ensure database connections and file descriptors are cleanly closed before file moves or unlinking (`os.replace` semantics).

---

## 4. Portability Audit Verdict

CAMserv's core business logic is highly modular and cleanly structured in pure Python, enabling straightforward cross-platform abstraction without requiring architectural rewrites. Routing all operating-system-dependent operations through `src/camserv/platform/` completely eliminates all identified portability risks.
