# CAMserv 0.9.0-rc1 Release Notes

**Release Date:** 2026-11-16  
**Version:** `0.9.0-rc1` (Release Candidate 1)  
**Target Operating Systems:** Debian 13 (Trixie), Debian 12 (Bookworm)  
**Target Architectures:** `amd64` (x86_64), `arm64` (aarch64)  
**Distribution Channel:** Debian Binary Packages (`.deb`)

---

## 1. Welcome to CAMserv 0.9.0-rc1

CAMserv is a privacy-first, enterprise-grade Network Video Recorder (NVR), Security Intelligence Platform, and Digital Forensics Appliance designed for modern edge deployments. Version `0.9.0-rc1` marks the first official Release Candidate of CAMserv, introducing native Debian appliance packaging, systemd service sandboxing, deterministic build pipelines, and hardened lifecycle management.

---

## 2. Key Highlights & New Capabilities

### 2.1 Native Debian Appliance Packaging
- **Standard `.deb` Packages:** Ready-to-install packages for Debian 12 (Bookworm) and Debian 13 (Trixie) across both `amd64` and `arm64` architectures.
- **Deterministic Builds:** Bit-for-bit reproducible packaging using standardized timestamps, sorted tarball members, and root ownership.
- **Dpkg Conffiles Preservation:** Preserves administrator configurations (`/etc/camserv/camserv.conf`, `/etc/camserv/camserv.env`) across package upgrades.
- **GDPR & Judicial Vault Retention:** Administrative package purge (`apt purge`) safely preserves video recordings and signed forensic evidence in `/var/lib/camserv/vault/` to prevent accidental destruction of court-ordered or legally retained surveillance data.

### 2.2 Hardened Systemd Sandboxing
- Modular multi-daemon architecture:
  - `camserv-core.service`: REST/WebSocket API and central event coordinator.
  - `camserv-ingestion.service`: RTSP/UVC/ONVIF multi-stream capture daemon.
  - `camserv-inference.service`: Computer vision and edge AI privacy daemon.
  - `camserv-storage-init.service`: Pre-flight database migration and storage initialization.
  - `camserv-central-sync.service`: Fleet synchronization daemon with mTLS encryption.
  - `camserv-updater.service` & `timer`: Automated A/B firmware updater.
- **Sandboxing Contracts:** Daemons run as unprivileged user `camserv:camserv` with `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true`, `WatchdogSec=15s`, and granular device cgroups (`/dev/video*`, `/dev/dri/*`).

### 2.3 End-to-End Fail-Closed Privacy Pipeline
- Automated real-time facial and license plate anonymization via Gaussian blur and pixelation filters.
- **Fail-Closed Protection:** If the privacy inference engine encounters a GPU fault or software exception, the video pipeline immediately halts frame transmission and renders an emergency masked blackout frame with a `PRIVACY_FAIL_CLOSED` security alert, preventing unmasked video leaks.

### 2.4 Legally Defensible Digital Forensics
- Export video clips as cryptographically signed digital forensic packages (`.zip`).
- Every package bundles raw video, detailed metadata manifests (camera details, GPS, operator identity), and an **Ed25519 digital signature** over the SHA-256 digest of the export archive, ensuring tamper detection and chain-of-custody compliance under ISO/IEC 27037.

### 2.5 Hardened Credential Scrubbing
- Advanced regex scrubbing sanitizes embedded passwords from camera RTSP and HTTP URLs in logs, telemetry, and REST responses.
- Handles complex credentials with special characters (`:`, `@`, `/`, `#`, `?`, `&`, `~`, `+`, `=`, `%`) and URL-encoded strings.

---

## 3. Package Verification & Downloads

| Package Name | Architecture | File Size | SHA-256 Digest |
|---|---|---|---|
| `camserv_0.9.0-rc1_amd64.deb` | `amd64` | 2,743,906 bytes | `a0c9fd2949e778e35c82cdd377e5d184a32a0760b40e79ca5fc21226b5224a6d` |
| `camserv_0.9.0-rc1_arm64.deb` | `arm64` | 2,743,906 bytes | `cebb8550493b463a16397189815e89f5e50d930b284b3f8030ca61734eca6eca` |

---

## 4. Quick Installation Guide (Debian 12 / 13)

### Step 1: Install Dependencies
```bash
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg libglib2.0-0 sqlite3 systemd
```

### Step 2: Install CAMserv Package
```bash
sudo dpkg -i camserv_0.9.0-rc1_amd64.deb
# If missing dependencies:
sudo apt install -f -y
```

### Step 3: Configure Appliance
Edit the primary configuration file:
```bash
sudo nano /etc/camserv/camserv.conf
```

### Step 4: Verify Service Status
```bash
sudo systemctl status camserv-core
sudo systemctl status camserv-ingestion
```

### Step 5: Access Web Console
Open a browser and navigate to:
```text
http://<appliance-ip>:8080/
```

---

## 5. Known Limitations & Hardware Gates (Targeted for v1.0.0-LTS)

- **Bare-metal Appliance ISO:** Full bootable Debian 13 installation ISO will be released with `v1.0.0-LTS`.
- **Physical Hardware Laboratory Qualification:** Physical on-bench validation on Raspberry Pi 5 single-board computers and NVIDIA Jetson Orin Nano systems (along with a 72-hour thermal chamber stress test) will be completed prior to the final LTS milestone.

---

## 6. Full Qualification Documentation

For complete technical audit reports and qualification evidence:
- Master Qualification Audit: `docs/audit/PHASE-14-RELEASE-QUALIFICATION.md`
- Debian Installation Report: `docs/audit/DEBIAN-REAL-INSTALLATION-RESULTS.md`
- Systemd Runtime Report: `docs/audit/SYSTEMD-RUNTIME-VALIDATION.md`
- Camera Pipeline Report: `docs/audit/REAL-CAMERA-DEPLOYMENT-RESULTS.md`
- Linux Security Report: `docs/audit/LINUX-SECURITY-AUDIT.md`
- Upgrade & Lifecycle Report: `docs/audit/UPGRADE-ROLLBACK-RECOVERY-RESULTS.md`
- Performance & Throughput: `docs/audit/PERFORMANCE-ON-DEBIAN.md`
- Supply Chain & SBOM: `docs/audit/RELEASE-SUPPLY-CHAIN-REVIEW.md`
- Artifact Inventory: `docs/audit/RELEASE-ARTIFACT-INVENTORY.md`
- Test Execution Report: `docs/audit/PHASE-14-TEST-EXECUTION-REPORT.md`
- Release Blockers & Gating: `docs/audit/PHASE-14-RELEASE-BLOCKERS.md`
