# Phase 15: Windows Service Architecture & Process Lifecycle

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Scope:** Background Service Architecture on Microsoft Windows  
**Host Subsystem:** Windows Service Control Manager (SCM) & Win32 Services API  

---

## 1. Architectural Design

On Debian Linux appliances, background daemons are supervised by `systemd`. On Microsoft Windows, enterprise deployments require native integration with the **Windows Service Control Manager (SCM)** so that CAMserv starts automatically upon host boot prior to user logon and executes in Session 0:

```text
[Windows Boot / OS Init]
          │
          ▼
[Windows Service Control Manager (services.exe)]
          │
          ├── Reads: HKLM\SYSTEM\CurrentControlSet\Services\CAMserv
          ├── Invokes: python.exe -m camserv.platform.windows.service run-service
          │
          ▼
[CAMserv Windows Service Host (Session 0)]
    ├── Security Context: "NT SERVICE\CAMserv" or "LocalSystem"
    ├── Service Status Handler (SERVICE_STATUS: RUNNING / STOPPED)
    ├── SCM Control Handler:
    │     ├── SERVICE_CONTROL_STOP       ──> Triggers Graceful Pipeline Flush
    │     ├── SERVICE_CONTROL_SHUTDOWN   ──> Emergency Database Checkpoint
    │     └── SERVICE_CONTROL_POWEREVENT ──> Pause / Resume Buffer Rings
    │
    ▼
[CAMserv Core Engine Pipeline (Asyncio Event Loop)]
```

---

## 2. Windows Service Lifecycle States

The service manager reports four fundamental lifecycle states to SCM:

1. **`SERVICE_START_PENDING`:**
   - Pre-flight storage initialization via `PlatformFilesystem.initialize_filesystem()`.
   - SQLite WAL database verification and schema migration check.
   - Master encryption key retrieval via Windows DPAPI.
2. **`SERVICE_RUNNING`:**
   - ASGI REST and WebSocket server (`uvicorn`) active on port 8080.
   - Camera ingestion supervisors active on configured channels.
   - Fail-closed privacy inference pipeline active.
3. **`SERVICE_STOP_PENDING`:**
   - Ingestion supervisor halts incoming frame pulls.
   - In-flight MP4 recording chunks finalized and timeline indexed.
   - SQLite WAL checkpoint flushed to disk.
4. **`SERVICE_STOPPED`:**
   - Shared memory segments unlinked.
   - Service process exits with code 0.

---

## 3. Deployment & SCM Commands

Administrators can install, inspect, and control CAMserv on Windows via `sc.exe`:

```cmd
:: 1. Register the Service
sc.exe create CAMserv binPath= "\"C:\Program Files\CAMserv\python\python.exe\" -m camserv.main serve" DisplayName= "CAMserv Security Intelligence Platform" start= auto

:: 2. Configure Service Failure Actions (Automated Restart on Crash)
sc.exe failure CAMserv reset= 86400 actions= restart/5000/restart/10000/none/0

:: 3. Start the Service
sc.exe start CAMserv

:: 4. Query Real-Time Status
sc.exe query CAMserv
```
