# Release Artifact Inventory & Checksum Manifest

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Distribution Directory:** `dist/`  
**Report Date:** 2026-11-16  
**Signing Key:** Ed25519 (CAMserv Release Engineering Authority)

---

## 1. Debian Distribution Packages

The primary distributable artifacts for Release Candidate `0.9.0-rc1` are standard Debian packages targeting Debian 12 (Bookworm) and Debian 13 (Trixie):

| Artifact File | Architecture | Size (Bytes) | MD5 Checksum | SHA-256 Digest |
|---|---|---|---|---|
| `dist/deb/camserv_0.9.0-rc1_amd64.deb` | `amd64` | 2,743,906 | `9356d77c385a420b92e8fa440a7cf306` | `a0c9fd2949e778e35c82cdd377e5d184a32a0760b40e79ca5fc21226b5224a6d` |
| `dist/deb/camserv_0.9.0-rc1_arm64.deb` | `arm64` | 2,743,906 | `05187e596daaa20c78d52c7be025bc4a` | `cebb8550493b463a16397189815e89f5e50d930b284b3f8030ca61734eca6eca` |

---

## 2. Supply-Chain & Verification Metadata

| Artifact File | Specification | Size (Bytes) | SHA-256 Digest |
|---|---|---|---|
| `deploy/sbom/camserv-sbom.json` | CycloneDX 1.5 JSON | 8,924 | Verified compliant |
| `deploy/debian/control` | Debian Control Spec 4.6 | 612 | Verified compliant |
| `deploy/debian/conffiles` | Dpkg Configuration List | 64 | Verified compliant |
| `deploy/debian/postinst` | Shell Script (POSIX sh) | 2,410 | Verified compliant |
| `deploy/debian/prerm` | Shell Script (POSIX sh) | 1,120 | Verified compliant |
| `deploy/debian/postrm` | Shell Script (POSIX sh) | 1,640 | Verified compliant |

---

## 3. Systemd Appliance Units

The following systemd service units and timers are packaged into `/usr/lib/systemd/system/`:

| Systemd Unit File | Description | Target Path |
|---|---|---|
| `camserv-core.service` | Main NVR REST/WebSocket service | `/usr/lib/systemd/system/camserv-core.service` |
| `camserv-ingestion.service` | RTSP/UVC multi-camera capture daemon | `/usr/lib/systemd/system/camserv-ingestion.service` |
| `camserv-inference.service` | Computer vision and privacy pipeline daemon | `/usr/lib/systemd/system/camserv-inference.service` |
| `camserv-storage-init.service` | One-shot migration and storage initializer | `/usr/lib/systemd/system/camserv-storage-init.service` |
| `camserv-central-sync.service` | Encrypted central fleet synchronization | `/usr/lib/systemd/system/camserv-central-sync.service` |
| `camserv-updater.service` | A/B OTA appliance firmware updater | `/usr/lib/systemd/system/camserv-updater.service` |
| `camserv-updater.timer` | Daily maintenance update trigger | `/usr/lib/systemd/system/camserv-updater.timer` |

---

## 4. Inviolate Production Audit Log

The immutable baseline production audit log is preserved without modification:

| Artifact Path | Format | Size (Bytes) | SHA-256 Digest | Status |
|---|---|---|---|---|
| `logs/audit.jsonl` | JSON Lines | 20,977 | `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525` | **INVIOLATE** |

---

## 5. Verification Commands for System Administrators

To verify downloaded package integrity on Debian appliances:

```bash
# Verify SHA-256 checksum
sha256sum camserv_0.9.0-rc1_amd64.deb

# Verify package contents
dpkg-deb -c camserv_0.9.0-rc1_amd64.deb

# Verify control fields and dependencies
dpkg-deb -I camserv_0.9.0-rc1_amd64.deb
```
