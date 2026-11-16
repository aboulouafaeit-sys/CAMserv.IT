# CAMserv — Phase 20 Windows MSI Installer Qualification

**Document ID:** PHASE-20-MSI-2026-008  
**Target Release:** `0.10.0`  
**Package Evaluated:** `dist/windows/camserv_0.10.0-alpha2_win64.msi`  
**Package Size:** 24,576 bytes  
**SHA-256 Digest:** `A45AA0B50ED4FA403FD214CD0CF6656B0717037B23073F12CDF7A28A3CEE1B92`  
**Date:** November 16, 2026  

---

## 1. Technical Audit of MSI Database Structure

The MSI package was audited using native Windows Installer Win32 APIs (`ctypes.windll.msi`).

### Database Properties:
* **Product Name:** `CAMserv Advanced Security Intelligence Platform`
* **Product Version:** `0.10.0.0`
* **Product Code:** `{8B33D452-9A4B-4E38-9B21-B488C9EE1601}`
* **Upgrade Code:** `{3F83C1A2-8241-45DF-B552-6C9100DE1602}`
* **Architecture:** x64 (`COMPONENT_ATTR_64BIT = 0x0100`)
* **ALLUSERS:** `1` (Per-machine installation in `Program Files\CAMserv`)

---

## 2. Evidence & Data Preservation Verification

In accordance with forensic requirements, uninstalling or upgrading CAMserv must never destroy evidence or audit trails.

Querying the MSI `Component` table revealed the following attributes:
* `cmp_recordings`: Attribute `272` (`0x0100 | 0x0010 = msidbComponentAttributes64bit | msidbComponentAttributesPermanent`)
* `cmp_vault`: Attribute `272` (Permanent)
* `cmp_data`: Attribute `272` (Permanent)

**Verification:** The `msidbComponentAttributesPermanent` flag (16) instructs the Windows Installer engine to **never unlink or delete** the directory contents upon package uninstallation or upgrade. Forensic integrity is preserved.

---

## 3. Package Size & Payload Clarification

The package size is 24 KB because the MSI contains the relational database definition tables (`Property`, `Directory`, `Component`, `Feature`, `File`, `Media`, `ServiceInstall`, `ServiceControl`, `InstallExecuteSequence`), but does not embed a compressed `.cab` stream (`Cabinet` column in `Media` table is `null`).

* **Operational Status:** Valid schema-defining installer database.
* **Production Packaging Requirement:** Production deployment requires bundling binary executables into an embedded `#Data1.cab` using `makecab.exe` during CI/CD build pipelines.
