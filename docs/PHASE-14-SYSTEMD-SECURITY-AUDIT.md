# Phase 14: Systemd Service Architecture & Linux Security Audit

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Scope:** Systemd Sandboxing, Least Privilege, IPC Boundaries & Fault Injection  
**Classification:** `VERIFIED_IN_SOFTWARE` (Contract Test Suite & Static Validator)

---

## 1. Systemd Unit Sandboxing Profile

The 7 systemd service and timer units were audited against modern Linux security standards:

```ini
[Unit]
Description=CAMserv Core NVR Daemon
After=network.target camserv-storage-init.service
Wants=camserv-storage-init.service

[Service]
Type=simple
User=camserv
Group=camserv
ExecStart=/usr/bin/camserv-cli serve --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5s
WatchdogSec=15s

# Hardening Sandboxes
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
NoNewPrivileges=true
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=
ReadWritePaths=/var/lib/camserv /var/log/camserv /run/camserv
```

### Directive Evaluation Table

| Sandboxing Directive | Configured Value | Security Benefit | Enforced in Units |
|---|---|---|---|
| `User` / `Group` | `camserv:camserv` | Eliminates root daemon vulnerabilities | All user-facing daemons |
| `ProtectSystem` | `strict` | Entire OS filesystem mounted read-only | `core`, `ingestion`, `inference`, `sync` |
| `ProtectHome` | `true` | Hides `/home`, `/root`, `/run/user` | `core`, `ingestion`, `inference`, `sync` |
| `PrivateTmp` | `true` | Isolated tmpfs preventing symlink attacks | `core`, `ingestion`, `inference`, `sync` |
| `NoNewPrivileges` | `true` | Prevents privilege escalation via SUID | All units |
| `CapabilityBoundingSet` | `CAP_NET_BIND_SERVICE` | Restricts raw kernel caps; drops raw sockets | `core`, `sync` |
| `DeviceAllow` | `/dev/video* rwm`, `/dev/dri/* rwm` | Restricts access solely to optical/GPU nodes | `ingestion`, `inference` |
| `SupplementaryGroups` | `video render` | Access to camera hardware decoders | `ingestion`, `inference` |
| `WatchdogSec` | `15s` / `30s` | Automated recovery from thread deadlock | `core`, `ingestion`, `inference` |

---

## 2. Fault Injection & Edge Case Testing

Systemd service recovery behavior was tested against 6 simulated hardware/environmental failure conditions:

1. **Missing Optical Device (`/dev/video0` absent):**
   - Ingestion daemon enters controlled retry mode with exponential backoff; does not crash whole service or corrupt databases.
2. **Missing GPU Device (`/dev/dri/renderD128` absent):**
   - Inference service automatically falls back to CPU execution with a warning log entry.
3. **Database Unavailability / Lock Contention:**
   - Database operations timeout cleanly; connection pool retries with jitter without crashing the API worker.
4. **Sudden Power Loss / Crash (`SIGKILL` simulation):**
   - SQLite WAL recovers pending changes upon restart.
5. **Storage Full Condition (ENOSPC):**
   - Storage manager detects disk threshold (>95%), halts continuous recording on low-priority streams, logs alert, and protects high-priority evidence chunks.
6. **Watchdog Timeout:**
   - Deadlocked daemon terminated by systemd after threshold expires; cleanly restarted within 5 seconds.
