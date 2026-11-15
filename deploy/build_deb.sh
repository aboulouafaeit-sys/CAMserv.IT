#!/bin/bash
# ==============================================================================
# CAMserv Appliance Debian Package Builder
# Builds standalone .deb installer for Debian 12 (Bookworm) & Ubuntu 24.04 LTS
# ==============================================================================

set -euo pipefail

PACKAGE_NAME="camserv"
VERSION="0.9.0-rc1"
ARCH="amd64"
DIST_DIR="dist/deb/${PACKAGE_NAME}_${VERSION}_${ARCH}"

echo "[*] Initializing CAMserv Debian package build structure..."
rm -rf dist/deb
mkdir -p "${DIST_DIR}/DEBIAN"
mkdir -p "${DIST_DIR}/opt/camserv"
mkdir -p "${DIST_DIR}/lib/systemd/system"
mkdir -p "${DIST_DIR}/etc/camserv"
mkdir -p "${DIST_DIR}/usr/bin"

# 1. Copy package metadata and maintainer scripts
cp deploy/debian/control "${DIST_DIR}/DEBIAN/control"
cp deploy/debian/postinst "${DIST_DIR}/DEBIAN/postinst"
cp deploy/debian/prerm "${DIST_DIR}/DEBIAN/prerm"
cp deploy/debian/postrm "${DIST_DIR}/DEBIAN/postrm"
chmod 755 "${DIST_DIR}/DEBIAN/postinst" "${DIST_DIR}/DEBIAN/prerm" "${DIST_DIR}/DEBIAN/postrm"

# 2. Copy systemd services
cp deploy/systemd/*.service "${DIST_DIR}/lib/systemd/system/"
cp deploy/systemd/*.target "${DIST_DIR}/lib/systemd/system/"

# 3. Copy source files
cp -r src "${DIST_DIR}/opt/camserv/"
cp pyproject.toml "${DIST_DIR}/opt/camserv/"
cp README.md "${DIST_DIR}/opt/camserv/"
cp LICENSE "${DIST_DIR}/opt/camserv/"

# 4. Create symlink for CLI launcher
cat << 'EOF' > "${DIST_DIR}/usr/bin/camserv"
#!/bin/sh
exec /opt/camserv/venv/bin/python -m camserv.main "$@"
EOF
chmod 755 "${DIST_DIR}/usr/bin/camserv"

# 5. Build Debian package using dpkg-deb if present
if command -v dpkg-deb >/dev/null 2>&1; then
    echo "[*] Running dpkg-deb --build..."
    dpkg-deb --build "${DIST_DIR}" "dist/deb/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
    echo "[+] Successfully generated: dist/deb/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
else
    echo "[!] dpkg-deb not found in current environment. Package directory staged at: ${DIST_DIR}"
fi
