# Phase 16: Windows Service Security & Session 0 Isolation Audit

**Target Release:** 0.10.0-alpha2  
**Host Environment:** Microsoft Windows 11 Pro 64-bit  
**Evaluated Subject:** Service Security Architecture, Account Privileges, Session 0 Isolation  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Threat Model & Security Posture

Windows Services operate with elevated privileges and must withstand hostile attacks, local privilege escalation (LPE), and service impersonation attempts.

### Threat Matrix

| Threat ID | Threat Description | Mitigation Strategy in CAMserv | Validation Status |
| :--- | :--- | :--- | :--- |
| **THREAT-W01** | Unquoted Service Path Vulnerability | Binary path passed to `sc.exe create` is explicitly wrapped in escaped quotes: `f'"{exec_path}"{arg_str}'`. | **VERIFIED** |
| **THREAT-W02** | Session 0 Shatter Attack / GUI Injection | Decoupled architecture: SCM service contains zero GUI code. Interactive console operates purely over loopback REST/WebSocket. | **VERIFIED** |
| **THREAT-W03** | Service Binary Hijacking (DLL Search Order) | Executable directory resides in `%ProgramFiles%\CAMserv\bin` with write permissions restricted exclusively to `SYSTEM` and `Administrators`. | **VERIFIED** |
| **THREAT-W04** | Service Denial of Service via SCM Flooding | SCM controls handled through dedicated handler callback with atomic state checks and timeout hints. | **VERIFIED** |
| **THREAT-W05** | Credential Exposure in Service Parameters | Passwords and API tokens are never passed via CLI arguments; all secrets are protected via Windows DPAPI local machine storage. | **VERIFIED** |

---

## 2. Service Account Strategy

CAMserv supports two operational account modes:

1. **`LocalSystem` (Default MSI Installation):**
   - Enables full hardware access for GPU inference (DirectML / CUDA) and raw camera device interfaces.
   - Restricts network access outside host perimeter except explicit camera ingress ports.
2. **`NT SERVICE\CAMserv` (Virtual Service Account):**
   - Least-privilege managed virtual service account.
   - Isolation from host user accounts with isolated SID (`S-1-5-80-...`).
   - NTFS ACLs specifically grant full access to `%ProgramData%\CAMserv` to this SID.

---

## 3. Session 0 Isolation Verification

In Windows Vista and later (including Windows 11), Session 0 is completely isolated from all interactive user sessions.
- **Verification Result:** Zero message loops (`GetMessage`, `DispatchMessage`) exist in the service worker threads.
- All desktop operator interactions occur within the user's interactive Session (Session 1+) via `DesktopOperatorConsole`.
- Inter-process communication occurs over HTTP loopback `127.0.0.1:8080`, bound exclusively to localhost unless explicitly overridden by configuration.
