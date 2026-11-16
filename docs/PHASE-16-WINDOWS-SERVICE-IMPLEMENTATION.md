# Phase 16: Windows Service Implementation & SCM Integration Report

**Target Release:** 0.10.0-alpha2  
**Host Environment:** Microsoft Windows 11 Pro 64-bit (Build 26300)  
**Primary Module:** `src/camserv/platform/windows/service.py`  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Architectural Overview

Windows Services run in **Session 0**, an isolated, non-interactive Windows session designed to isolate background system daemons from interactive user desktop sessions. CAMserv implements a native Windows Service architecture adhering strictly to Win32 Service Control Manager (SCM) specifications via `advapi32.dll`.

### Architecture Diagram

```
+-------------------------------------------------------------+
|               Windows Service Control Manager (SCM)          |
+-------------------------------------------------------------+
                               |
             Control Codes / SCM Dispatcher
                               v
+-------------------------------------------------------------+
|                 WindowsServiceRunner (Session 0)            |
|  - StartServiceCtrlDispatcherW                              |
|  - RegisterServiceCtrlHandlerW                              |
|  - SetServiceStatus (SERVICE_RUNNING / SERVICE_STOP_PENDING)|
+-------------------------------------------------------------+
                               |
                        Worker Thread
                               v
+-------------------------------------------------------------+
|                  CAMserv Core Engine & API                  |
|  - FastAPI Application (Uvicorn ASGI server)                |
|  - Ingestion Pipelines (Media Foundation / RTSP / ONVIF)    |
|  - AI Inference Engine (CUDA / DirectML / CPU Fallback)     |
|  - Forensic Audit Logger & Recording Engine                 |
+-------------------------------------------------------------+
```

---

## 2. Technical Implementation Details

### 2.1 Win32 SCM Integration via `advapi32.dll`

The service runner utilizes pure Win32 ctypes integration without requiring third-party compilation:
- **`SERVICE_TABLE_ENTRYW`:** Formats service entry structures for `StartServiceCtrlDispatcherW`.
- **`RegisterServiceCtrlHandlerW`:** Registers the service control callback handler.
- **`SetServiceStatus`:** Propagates state transitions (`SERVICE_START_PENDING`, `SERVICE_RUNNING`, `SERVICE_STOP_PENDING`, `SERVICE_STOPPED`).

### 2.2 SCM Control Code Handlers

| SCM Control Code | Value | Action Taken |
| :--- | :--- | :--- |
| `SERVICE_CONTROL_STOP` | `0x00000001` | Sets `SERVICE_STOP_PENDING` (wait hint: 10,000ms), sets `_stop_event`, shuts down Uvicorn cleanly. |
| `SERVICE_CONTROL_SHUTDOWN` | `0x00000005` | Initiates rapid shutdown sequence before host poweroff. |
| `SERVICE_CONTROL_INTERROGATE` | `0x00000004` | Refreshes and returns current service status to SCM. |

### 2.3 Interactive Fallback Mechanism

When `WindowsServiceRunner` is executed from an interactive shell or test fixture, `StartServiceCtrlDispatcherW` immediately returns `ERROR_FAILED_SERVICE_CONTROLLER_CONNECT` (Win32 Error 1063). The runner traps this error and seamlessly falls back to interactive console execution mode (`run_console()`), enabling testability and local debugging without administrative service registration.

### 2.4 Service Management CLI

CAMserv provides a unified service CLI accessible via:
```powershell
python -m camserv.platform.windows.service [install|uninstall|start|stop|restart|status|run|dispatch]
```

- **`install`:** Invokes `sc.exe create CAMservCore` with auto-start configuration and restart recovery actions (`sc.exe failure CAMservCore reset= 86400 actions= restart/60000/restart/60000/none/0`).
- **`uninstall`:** Safely issues `sc.exe stop CAMservCore` followed by `sc.exe delete CAMservCore`.
- **`status`:** Queries SCM status and outputs structured state.

---

## 3. Verification & Test Evidence

- **Unit Test:** `test_windows_service_manager_query` — PASSED.
- **Unit Test:** `test_windows_service_runner_interactive_fallback` — PASSED.
- **CLI Verification:** Successfully queried unregistered state:
  ```
  Service: CAMservCore | State: not_installed | Installed: False
  ```
