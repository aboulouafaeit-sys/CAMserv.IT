# Phase 15: Cross-Platform Dependency & Runtime Compatibility Matrix

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Target Environments:** Debian 13 (Trixie), Debian 12 (Bookworm), Windows 11 x64, Windows 10 x64  
**Audit Standard:** Supply Chain Integrity & Platform Portability  

---

## 1. Runtime Platform Matrix

| Component / Layer | Debian 12 (Bookworm) | Debian 13 (Trixie) | Windows 11 (22H2+) | Windows 10 (22H2) |
|---|---|---|---|---|
| **Python Runtime** | Python 3.11.2 | Python 3.12+ | Python 3.11 – 3.14 (Verified 3.14.8) | Python 3.11 – 3.12 (Supported) |
| **Media Subsystem** | FFmpeg 5.1+, V4L2 | FFmpeg 6.1+, V4L2 | Media Foundation, FFmpeg 6.0+, DirectShow | Media Foundation, FFmpeg 5.0+ |
| **Relational Metadata** | SQLite 3.40+ (WAL) | SQLite 3.45+ (WAL) | SQLite 3.45+ (WAL) | SQLite 3.40+ (WAL) |
| **Service Supervisor** | systemd (>= 252) | systemd (>= 255) | Windows Service Control Manager (`sc.exe`) | Windows Service Control Manager (`sc.exe`) |
| **Secret Encryption** | Linux DAC (0600) / TPM | Linux DAC (0600) / TPM | Windows DPAPI (`crypt32.dll`) | Windows DPAPI (`crypt32.dll`) |
| **Filesystem Security** | POSIX Octal (0750) | POSIX Octal (0750) | NTFS Access Control Lists (`icacls.exe`) | NTFS Access Control Lists (`icacls.exe`) |
| **AI / GPU Acceleration** | TensorRT, OpenVINO, CPU | TensorRT, OpenVINO, CPU | DirectML (DX12), CUDA, CPU | DirectML (DX12), CUDA, CPU |

---

## 2. Python Package Compatibility Analysis

| Python Package | Debian Status | Windows Status | Compatibility Notes |
|---|---|---|---|
| `cryptography` | Fully Supported | Fully Supported | Pure CFFI wheel; Ed25519 & AES-GCM identical across OS. |
| `pydantic` / `pydantic-settings` | Fully Supported | Fully Supported | 100% OS-agnostic configuration validation. |
| `fastapi` / `uvicorn` / `starlette` | Fully Supported | Fully Supported | Async ASGI web server runs natively on Windows & Linux. |
| `opencv-python-headless` | Fully Supported | Fully Supported | Direct capture via MSMF on Windows; V4L2 on Linux. |
| `numpy` / `scipy` | Fully Supported | Fully Supported | Cross-platform tensor manipulation. |
| `structlog` | Fully Supported | Fully Supported | Structured JSON audit logging to file / console. |
| `httpx` | Fully Supported | Fully Supported | Asynchronous HTTP/mTLS client. |
| `sqlite3` | Built-in | Built-in | Native standard library module. |
| `ctypes` (Win32 APIs) | N/A (Linux) | Built-in | Used for zero-dependency DPAPI & Windows Service integration. |

---

## 3. Windows 10 Support Policy Assessment

- **Lifecycle Reality:** Microsoft standard support for Windows 10 officially concluded in October 2025.
- **Enterprise Positioning:** Windows 11 Enterprise (64-bit AMD64) is designated as the primary commercial Windows tier.
- **Degraded Fallback:** Windows 10 installations are supported under a secondary compatibility mode. If modern DirectML or virtualization features are unavailable on legacy Windows 10 builds, CAMserv degrades gracefully to CPU inference and DirectShow capture without crashing.
