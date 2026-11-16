# Phase 14: Debian Native Deployment & Environment Validation

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Target Distributions:** Debian 13 (Trixie), Debian 12 (Bookworm)  
**Target Architectures:** `amd64` (Primary) & `arm64` (Secondary)  
**Environment Evaluation Status:** Host Windows 11 Enterprise (WSL/Docker Absent)  
**Classification:** `SIMULATED` / `BLOCKED_BY_ENVIRONMENT` (Native Debian Gate Recorded)

---

## 1. Environment Availability & Native Testing Assessment

Section 4 of the Phase 14 directive mandates testing against real Debian environments:
- Debian 13 Trixie amd64
- Debian 12 Bookworm amd64
- Debian 13 / 12 arm64 (Real hardware or virtual machine)

### Host Hardware & Subsystem Audit
An audit of the workstation executed the following checks:
- Command `wsl -l -v`: Exited with code 1: *"The Windows Subsystem for Linux is not installed."*
- Command `docker --version`: Command not found.
- Command `podman --version`: Command not found.
- Command `qemu-system-x86_64 --version`: Command not found.

### Engineering Rule 9 Compliance
> *"If genuine Debian environments are unavailable, prepare reproducible test scripts and mark the corresponding qualification gates BLOCKED. Do not fabricate results."*

In strict adherence to this mandate, native execution on a live Linux kernel is classified as **`BLOCKED_BY_ENVIRONMENT`**. We do not fabricate native terminal logs from a non-existent Linux kernel. Instead:
1. All package structures, maintainer scripts, file hierarchies, and permission masks were verified via Python-based GNU ar/tar archive inspection and sandbox test harnesses (`VERIFIED_IN_SOFTWARE`).
2. An automated, fully reproducible Debian validation script (`deploy/debian/verify_native_debian.sh`) has been prepared and documented below for execution on genuine Debian 12/13 test instances.

---

## 2. Native Debian Test Script Manifest

The following test script is bundled at `deploy/debian/verify_native_debian.sh` for execution in a clean Debian 12/13 environment:

```bash
#!/usr/bin/env bash
# CAMserv Native Debian Qualification Script
# Target: Debian 12 (Bookworm) / Debian 13 (Trixie)
set -euo pipefail

echo "=========================================================="
echo "CAMserv 0.9.0-rc1 Native Debian Installation Verification"
echo "=========================================================="

ARCH=$(dpkg --print-architecture)
PKG_NAME="camserv_0.9.0-rc1_${ARCH}.deb"

echo "[1/8] Checking package existence..."
if [ ! -f "${PKG_NAME}" ]; then
    echo "ERROR: Package ${PKG_NAME} not found in current directory."
    exit 1
fi

echo "[2/8] Validating package metadata with dpkg-deb..."
dpkg-deb --info "${PKG_NAME}"
dpkg-deb --contents "${PKG_NAME}"

echo "[3/8] Checking package dependencies..."
apt-get update
apt-get install -y python3 python3-pip ffmpeg libglib2.0-0 sqlite3 systemd

echo "[4/8] Installing CAMserv debian package..."
dpkg -i "${PKG_NAME}" || apt-get install -f -y

echo "[5/8] Verifying system user, permissions and directories..."
id camserv
groups camserv | grep -E "video|render"
ls -ld /etc/camserv /var/lib/camserv /var/log/camserv
ls -la /etc/camserv/camserv.env

echo "[6/8] Testing systemd service lifecycle..."
systemctl daemon-reload
systemctl start camserv-storage-init.service
systemctl start camserv-core.service
systemctl status camserv-core.service --no-pager

echo "[7/8] Querying local REST health endpoint..."
sleep 3
curl -f http://127.0.0.1:8000/health || curl -f http://127.0.0.1:8080/health

echo "[8/8] Testing package purge and evidence vault preservation..."
touch /var/lib/camserv/vault/test_evidence.zip
apt-get purge -y camserv
if [ -f /var/lib/camserv/vault/test_evidence.zip ]; then
    echo "SUCCESS: Evidence Vault preserved across purge!"
    rm -rf /var/lib/camserv/vault/test_evidence.zip
else
    echo "FAILURE: Evidence Vault was deleted during purge!"
    exit 2
fi

echo "=========================================================="
echo "CAMserv 0.9.0-rc1 Native Debian Verification: SUCCESSFUL"
echo "=========================================================="
```

---

## 3. Qualification Gate Status

- **Debian Package Mechanics:** `VERIFIED_IN_SOFTWARE` (Passed 100%)
- **Debian 12 Bookworm Native Kernel Execution:** `BLOCKED_BY_ENVIRONMENT` (Gate recorded for lab execution)
- **Debian 13 Trixie Native Kernel Execution:** `BLOCKED_BY_ENVIRONMENT` (Gate recorded for lab execution)
- **ARM64 Physical Appliance Execution:** `NOT_TESTED` (Physical Hardware Gate recorded for v1.0.0-LTS)
