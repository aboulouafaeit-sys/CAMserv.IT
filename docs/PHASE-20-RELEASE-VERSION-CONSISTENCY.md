# CAMserv — Phase 20 Release Version Consistency Matrix

**Document ID:** PHASE-20-VER-2026-017  
**Target Release:** `0.10.0` (Pre-LTS Qualification)  
**Date:** November 16, 2026  

---

## 1. Release Chain Version Consistency Matrix

An exhaustive audit of version identifiers across all files and artifacts was conducted to resolve historical version drift:

| Target Component / Artifact | File Path | Recorded Version | Target Alignment | Status & Justification |
| :--- | :--- | :---: | :---: | :--- |
| **Python Core Module** | `src/camserv/__init__.py` | `0.9.0-rc1` | `0.10.0` | Pinned in Phase 11 regression test suite (`test_version_manifest_alignment`). Transitioning to `0.10.0` at release cut. |
| **Python Package Config** | `pyproject.toml` | `0.9.0-rc1` | `0.10.0` | Pinned in Phase 11 regression test suite. |
| **CycloneDX SBOM** | `deploy/sbom/camserv-sbom.json` | `0.9.0-rc1` | `0.10.0` | Pinned in Phase 11 regression test suite. |
| **API Health Endpoint** | `src/camserv/api/app.py` | Dynamically reports `__version__` | `0.10.0` | **VERIFIED CONSISTENT:** Dynamically derives version from `camserv.__version__`. |
| **OpenAPI Specification** | `src/camserv/api/routes.py` | Dynamically reports `__version__` | `0.10.0` | **VERIFIED CONSISTENT.** |
| **Windows MSI Installer** | `dist/windows/camserv_0.10.0-alpha2_win64.msi` | `0.10.0.0` (MSI) / `0.10.0-alpha2` | `0.10.0` | Built in Phase 16 preview. ProductVersion is `0.10.0.0`. |
| **Windows MSI Manifest** | `dist/windows/camserv_0.10.0-alpha2_win64.json` | `0.10.0-alpha2` | `0.10.0` | Accompanies MSI artifact. |
| **Debian Packaging Control** | `deploy/debian/control` | `0.9.0-rc1` | `0.10.0` | Built in Phase 13/14 appliance qualification. |
| **Debian AMD64 Package** | `dist/deb/camserv_0.9.0-rc1_amd64.deb` | `0.9.0-rc1` | `0.10.0` | Original binary artifact preserved with verified SHA-256 digest. |
| **Debian ARM64 Package** | `dist/deb/camserv_0.9.0-rc1_arm64.deb` | `0.9.0-rc1` | `0.10.0` | Original binary artifact preserved with verified SHA-256 digest. |
| **Systemd Units** | `deploy/systemd/camserv-core.service` | Unversioned unit | N/A | Fully decoupled from release string. |

---

## 2. Preserved Artifact SHA-256 Hashes

In compliance with Directive Rule 2, existing release artifacts were audited and their cryptographic hashes preserved prior to any rebuild:

* `dist/deb/camserv_0.9.0-rc1_amd64.deb`: `A0C9FD2949E778E35C82CDD377E5D184A32A0760B40E79CA5FC21226B5224A6D`
* `dist/deb/camserv_0.9.0-rc1_arm64.deb`: `CEBB8550493B463A16397189815E89F5E50D930B284B3F8030CA61734ECA6ECA`
* `dist/windows/camserv_0.10.0-alpha2_win64.msi`: `A45AA0B50ED4FA403FD214CD0CF6656B0717037B23073F12CDF7A28A3CEE1B92`
* `dist/windows/camserv_0.10.0-alpha2_win64.json`: `7F68CEA3E394CF613F530692AA5B4B110C9AB92369D12C7D1DEB971B04E4FD61`

---

## 3. Version Alignment Action Plan for Final LTS Release

1. Update `__version__ = "0.10.0"` in `src/camserv/__init__.py`.
2. Update `version = "0.10.0"` in `pyproject.toml` and `deploy/debian/control`.
3. Re-generate `deploy/sbom/camserv-sbom.json` with target version `0.10.0`.
4. Update Phase 11 assertion test in `tests/test_audit_phase11_regressions.py` to assert `"0.10.0"`.
5. Build official final release artifacts: `camserv_0.10.0_amd64.deb`, `camserv_0.10.0_arm64.deb`, `camserv_0.10.0_win64.msi`.
