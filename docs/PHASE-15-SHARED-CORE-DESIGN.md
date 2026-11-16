# Phase 15: Shared Core Engine Design & Boundary Specifications

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Author:** Principal Cross-Platform Software Architect  
**Scope:** Core Domain Isolation, Platform Boundary Invariants & Universal Business Logic  

---

## 1. Shared Core Philosophy

The primary objective of Phase 15 is to ensure that CAMserv remains **one cohesive product** across Debian Linux and Microsoft Windows. To achieve this, the Core Engine is strictly insulated from operating-system-specific assumptions, ensuring that:
- Core business logic is **never duplicated** between platforms.
- NVR recording, indexing, and retention policies execute identically regardless of host OS.
- Fail-closed privacy, digital forensics, and cryptographic evidence signing maintain identical byte-for-byte formats and legal admissibility standards.
- REST and WebSocket API contracts present identical schemas across deployments.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Shared Core Domain Models                       │
│  - CameraStream & FrameSource (camserv.acquisition.camera)             │
│  - NVR Recording Engine & Timeline Indexer (camserv.nvr)               │
│  - Fail-Closed Privacy & GDPR Anonymization (camserv.inference.privacy)│
│  - Behavioral Threat Engine & Event Bus (camserv.events)               │
│  - SQLite WAL Store & Schema Migrations (camserv.storage)              │
│  - Ed25519 Forensic Signer & Evidence Packager (camserv.storage)       │
│  - RBAC Security & JWT Authentication (camserv.security)               │
│  - Pydantic Configuration Models (camserv.config)                      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                         Platform Abstraction API
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌───────────────────────┐                       ┌───────────────────────┐
│     Linux Adapter     │                       │    Windows Adapter    │
│  (camserv.platform)   │                       │  (camserv.platform)   │
└───────────────────────┘                       └───────────────────────┘
```

---

## 2. Shared Core Boundary Enforcements

To prevent architectural drift, the following invariants are enforced:

### 2.1 File System Paths
- **Rule:** Core application modules (`camserv.nvr`, `camserv.storage`, `camserv.api`, `camserv.inference`) must **never** hardcode `/var/lib/...`, `/etc/...`, or `C:\...` paths.
- **Contract:** All path queries are routed through `camserv.platform.shared.paths.PathResolver.resolve_paths()`, which dynamically returns appropriate directories based on execution mode (system service vs local workspace).

### 2.2 Permissions and Security
- **Rule:** Core modules must not execute direct `os.chmod()` or manipulate raw security descriptors.
- **Contract:** Permissions are applied via `PlatformFilesystem.secure_directory()` and `secure_file()`, dispatching to POSIX DAC on Linux (`0750` / `0600`) and NTFS ACLs on Windows (`icacls`).

### 2.3 Secret Management
- **Rule:** Plaintext master encryption keys must never be written to configuration files or logs.
- **Contract:** Secrets are protected via `PlatformCredentialVault.protect_secret()`, using native Windows DPAPI (`crypt32.dll`) on Windows and AES-256-GCM envelope encryption on Linux.

### 2.4 Service Management
- **Rule:** Background daemons must not assume `systemctl` or Windows `sc.exe` availability.
- **Contract:** Service lifecycle calls are mediated by `PlatformServiceManager`.
