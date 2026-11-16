# CAMserv — Phase 20 Debian Native Platform Qualification

**Document ID:** PHASE-20-DEB-2026-009  
**Target Platforms:** Debian 13 Trixie & Debian 12 Bookworm (amd64 / arm64)  
**Package Evaluated:** `dist/deb/camserv_0.9.0-rc1_amd64.deb` & `camserv_0.9.0-rc1_arm64.deb`  
**Date:** November 16, 2026  

---

## 1. Package Structure & Multi-Arch Verification

Debian `.deb` packages were analyzed for compliance with Debian packaging standards:

* **AR Archive Composition:** Validated 3-member composition (`debian-binary`, `control.tar.gz`, `data.tar.gz`).
* **Dependency Declarations:**
  * `Depends: python3 (>= 3.10), python3-pip, python3-venv, ffmpeg, libgl1, libglib2.0-0t64 | libglib2.0-0, sqlite3, libcap2-bin, systemd`
  * Time64-transition compatibility verified via `libglib2.0-0t64 | libglib2.0-0` (essential for Debian 13 Trixie).
* **Package File Count:** >50 data files correctly mapped to `/opt/camserv`, `/usr/bin/camserv`, and `/lib/systemd/system/`.

---

## 2. Systemd Security & Sandboxing Verification

The unit file `camserv-core.service` incorporates full defense-in-depth Linux kernel sandboxing:

* `ProtectSystem=strict`: The entire host filesystem (`/usr`, `/boot`, `/etc`) is mounted read-only for the service process.
* `ProtectHome=yes`: `/home`, `/root`, and `/run/user` are inaccessible.
* `NoNewPrivileges=yes`: Prevents privilege escalation via setuid/setgid binaries.
* `PrivateTmp=yes`: Isolated `/tmp` and `/var/tmp` namespaces.
* `ProtectKernelTunables=yes`: `/proc/sys`, `/sys` write access blocked.
* `ProtectControlGroups=yes`: cgroups hierarchy mounted read-only.
* `CapabilityBoundingSet=CAP_NET_BIND_SERVICE`: All root capabilities dropped except low port binding.
* `User=camserv / Group=camserv`: Dedicated unprivileged daemon account.

---

## 3. Directory DACL Permissions

* Configuration: `/etc/camserv/camserv.yaml` (0640 `root:camserv`)
* Evidence Vault: `/var/lib/camserv/vault` (0700 `camserv:camserv`)
* Recordings: `/var/lib/camserv/recordings` (0750 `camserv:camserv`)
* Logs: `/var/log/camserv` (0755 `camserv:camserv`)
