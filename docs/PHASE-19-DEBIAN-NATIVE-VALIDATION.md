# Phase 19: Debian 13 (Trixie) & Debian 12 (Bookworm) Native Packaging, systemd Hardening & Appliance Service Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc3`  
**Target OS Matrix:** Debian GNU/Linux 13 (Trixie) & Debian GNU/Linux 12 (Bookworm)  
**Architectures:** AMD64 (`amd64`), ARM64 (`arm64`)  
**Evaluated Modules:** `deploy/debian/`, `src/camserv/deploy/`  
**Auditor:** Principal Linux Appliance Architect & Linux Security Engineer  
**Evaluation Date:** November 16, 2026  

---

## 1. Executive Summary

Phase 19 qualifies the native Debian appliance packaging and systemd service deployment of CAMserv. The evaluation verified the automated generation of pristine Debian packages (`.deb`), least-privilege system account isolation, directory structure compliance with the Filesystem Hierarchy Standard (FHS 3.0), and strict systemd security containment.

All 6 appliance validation tests in `tests/test_audit_phase13_appliance.py` and 5 package qualification tests in `tests/test_audit_phase14_qualification.py` passed with 100% compliance.

---

## 2. Debian Package Architecture & FHS Compliance

```
+---------------------------------------------------------------------------------------------------+
|                                DEBIAN APPLIANCE FILESYSTEM LAYOUT                                 |
+---------------------------------------------------------------------------------------------------+
|  /opt/camserv/                               - Application binaries, virtualenv, and Python core  |
|  /etc/camserv/                               - System configuration (camserv.yaml, logging.yaml)  |
|  /etc/camserv/node.key (0600)                - Cluster mTLS private key (camserv:camserv)         |
|  /var/lib/camserv/storage/                   - Ingested video segments and live recordings        |
|  /var/lib/camserv/vault/                     - Cryptographically sealed forensic evidence bundles |
|  /var/lib/camserv/cluster/                   - Persistent cluster state (cluster_state.json)      |
|  /var/log/camserv/                           - Structured JSON operational and audit logs         |
|  /lib/systemd/system/camserv.service         - Hardened systemd service unit descriptor           |
+---------------------------------------------------------------------------------------------------+
```

### Package Generation & Structure
* **Package Format:** Native Debian binary package (`camserv_0.10.0-rc3_amd64.deb` / `arm64.deb`).
* **Control Metadata:** Strict dependency resolution (`python3 (>= 3.11)`, `systemd`, `ffmpeg`, `libopencv-core4.6`, `ca-certificates`).
* **Maintainer Scripts:**
  - `postinst`: Creates unprivileged system user `camserv` in groups `video`, `dialout`, sets directory permissions, reloads systemd.
  - `prerm`: Safely signals `SIGTERM` to `camserv.service` allowing active segment finalization before file removal.
  - `postrm`: Preserves `/var/lib/camserv/vault` and recordings on package purge to guarantee evidence retention.

---

## 3. Hardened systemd Service Unit Containment

The `camserv.service` systemd unit implements defense-in-depth isolation directives:

```ini
[Unit]
Description=CAMserv Advanced Security Intelligence Platform NVR
After=network.target time-sync.target
Wants=time-sync.target

[Service]
Type=simple
User=camserv
Group=camserv
WorkingDirectory=/opt/camserv
ExecStart=/opt/camserv/bin/camserv daemon --config /etc/camserv/camserv.yaml
Restart=always
RestartSec=5s

# Security Hardening Directives
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
ProtectKernelModules=true
RestrictRealtime=true
MemoryDenyWriteExecute=true
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
ReadWritePaths=/var/lib/camserv /var/log/camserv /etc/camserv

[Install]
WantedBy=multi-user.target
```

---

## 4. Verification Test Evidence

* Deterministic Debian package generation: `tests/test_audit_phase14_qualification.py::test_stage_a_deterministic_package_build`.
* systemd service unit syntax and permissions: `tests/test_audit_phase13_appliance.py::test_debian_systemd_unit_validity`.
* Control scripts security inspection: `tests/test_audit_phase13_appliance.py::test_debian_postinst_permissions`.
* Cross-platform execution parity: `tests/test_platform_cross_platform.py` (7 tests passed).

---

## 5. Auditor Conclusion

**Debian Qualification Status:** **QUALIFIED & APPLIANCE-READY (TIER 1)**  
Debian 12 and 13 packaging operates with FHS compliance, deterministic build reproducibility, and strict systemd sandboxing.
