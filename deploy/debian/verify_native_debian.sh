#!/usr/bin/env bash
# ==============================================================================
# CAMserv 0.9.0-rc1 Native Debian Installation & Qualification Script
# Target: Debian 12 (Bookworm) / Debian 13 (Trixie)
# Architectures: amd64 / arm64
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "CAMserv 0.9.0-rc1 Native Debian Qualification"
echo "=========================================================="

ARCH=$(dpkg --print-architecture)
PKG_NAME="camserv_0.9.0-rc1_${ARCH}.deb"

echo "[1/8] Verifying Debian package file..."
if [ ! -f "${PKG_NAME}" ]; then
    if [ -f "dist/deb/${PKG_NAME}" ]; then
        PKG_NAME="dist/deb/${PKG_NAME}"
    else
        echo "ERROR: Package ${PKG_NAME} not found."
        exit 1
    fi
fi
echo "Using package: ${PKG_NAME}"

echo "[2/8] Validating package metadata with dpkg-deb..."
dpkg-deb --info "${PKG_NAME}"
dpkg-deb --contents "${PKG_NAME}"

echo "[3/8] Installing runtime dependencies..."
apt-get update
apt-get install -y python3 python3-pip ffmpeg libglib2.0-0 sqlite3 systemd

echo "[4/8] Installing CAMserv package..."
dpkg -i "${PKG_NAME}" || apt-get install -f -y

echo "[5/8] Checking system user, groups and directory DAC permissions..."
id camserv
groups camserv | grep -E "video|render"
ls -ld /etc/camserv /var/lib/camserv /var/log/camserv
ls -la /etc/camserv/camserv.env

echo "[6/8] Starting systemd services..."
systemctl daemon-reload
systemctl start camserv-storage-init.service
systemctl start camserv-core.service
sleep 2
systemctl status camserv-core.service --no-pager

echo "[7/8] Testing REST API health endpoint..."
curl -f http://127.0.0.1:8080/health || curl -f http://127.0.0.1:8000/health

echo "[8/8] Testing package purge and evidence vault preservation..."
touch /var/lib/camserv/vault/qualification_canary.zip
apt-get purge -y camserv
if [ -f /var/lib/camserv/vault/qualification_canary.zip ]; then
    echo "SUCCESS: Evidence Vault preserved across package purge!"
    rm -f /var/lib/camserv/vault/qualification_canary.zip
else
    echo "CRITICAL DEFECT: Evidence Vault was deleted during purge!"
    exit 2
fi

echo "=========================================================="
echo "CAMserv 0.9.0-rc1 Native Debian Qualification: PASSED"
echo "=========================================================="
