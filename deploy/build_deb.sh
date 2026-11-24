#!/bin/bash
# ==============================================================================
# CAMserv Appliance Debian Package Builder
# Builds standalone .deb installer for Debian 13 (Trixie), Debian 12 (Bookworm) & Ubuntu 24.04 LTS
# Supports amd64 and arm64 multi-architecture builds.
# ==============================================================================

set -euo pipefail

PACKAGE_NAME="camserv"
VERSION="${1:-0.10.0-rc7}"
ARCH="${2:-amd64}"

echo "[*] Initializing CAMserv Debian package build for ${PACKAGE_NAME} v${VERSION} (${ARCH})..."

# Prefer python3 build_deb.py for cross-platform deterministic builds and audits
if command -v python3 >/dev/null 2>&1; then
    python3 deploy/build_deb.py --version "${VERSION}" --arch "${ARCH}"
elif command -v dpkg-deb >/dev/null 2>&1; then
    DIST_DIR="dist/deb/${PACKAGE_NAME}_${VERSION}_${ARCH}"
    rm -rf "${DIST_DIR}"
    mkdir -p "${DIST_DIR}/DEBIAN" "${DIST_DIR}/opt/camserv" "${DIST_DIR}/lib/systemd/system" "${DIST_DIR}/etc/camserv" "${DIST_DIR}/usr/bin"
    cp deploy/debian/control "${DIST_DIR}/DEBIAN/control"
    cp deploy/debian/postinst "${DIST_DIR}/DEBIAN/postinst"
    cp deploy/debian/prerm "${DIST_DIR}/DEBIAN/prerm"
    cp deploy/debian/postrm "${DIST_DIR}/DEBIAN/postrm"
    chmod 755 "${DIST_DIR}/DEBIAN/postinst" "${DIST_DIR}/DEBIAN/prerm" "${DIST_DIR}/DEBIAN/postrm"
    cp deploy/systemd/*.service "${DIST_DIR}/lib/systemd/system/"
    cp deploy/systemd/*.target "${DIST_DIR}/lib/systemd/system/"
    cp deploy/camserv.default.yaml "${DIST_DIR}/etc/camserv/camserv.yaml"
    cp -r src pyproject.toml README.md LICENSE "${DIST_DIR}/opt/camserv/"
    cat << 'EOF' > "${DIST_DIR}/usr/bin/camserv"
#!/bin/sh
exec /opt/camserv/venv/bin/python -m camserv.main "$@"
EOF
    chmod 755 "${DIST_DIR}/usr/bin/camserv"
    dpkg-deb --build "${DIST_DIR}" "dist/deb/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
    echo "[+] Successfully generated: dist/deb/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
else
    echo "[-] Error: Neither python3 nor dpkg-deb is available in this environment."
    exit 1
fi
