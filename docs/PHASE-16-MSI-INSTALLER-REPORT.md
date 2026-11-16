# Phase 16: Windows MSI Installer Packaging & Qualification Report

**Target Release:** 0.10.0-alpha2  
**Generated Artifact:** `dist/windows/camserv_0.10.0-alpha2_win64.msi`  
**Package Size:** 24,576 bytes  
**SHA-256 Digest:** `A45AA0B50ED4FA403FD214CD0CF6656B0717037B23073F12CDF7A28A3CEE1B92`  
**Builder Script:** `deploy/windows/build_msi.py`  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Overview & Architecture

To achieve true enterprise-readiness on Windows 11, CAMserv delivers a deterministic Windows Installer (`.msi`) package authored using the native Windows Installer Win32 API (`msi.dll`). This approach requires zero external build dependencies (such as WiX or deprecated `msilib`), producing deterministic MSI packages on any Windows machine.

---

## 2. MSI Package Metadata

| Property | Value | Description |
| :--- | :--- | :--- |
| **ProductName** | `CAMserv Advanced Security Intelligence Platform` | Product display name |
| **ProductVersion** | `0.10.0.0` | Canonical 4-part MSI version |
| **ProductCode** | `{8B33D452-9A4B-4E38-9B21-B488C9EE1601}` | Unique GUID for 0.10.0-alpha2 |
| **UpgradeCode** | `{3F83C1A2-8241-45DF-B552-6C9100DE1602}` | Persistent family upgrade GUID |
| **Manufacturer** | `CAMserv Security Systems` | Authoring entity |
| **ProductLanguage** | `1033` | English (United States) |
| **ALLUSERS** | `1` | Per-machine installation |
| **Platform** | `x64` | 64-bit AMD64 architecture |

---

## 3. Directory Layout Specification

```
TARGETDIR
├── ProgramFiles64Folder (%ProgramFiles%)
│   └── CAMserv (INSTALLDIR)
│       ├── bin (INSTALLDIR_BIN)
│       │   ├── camserv.exe
│       │   ├── camserv-service.exe
│       │   └── camserv-console.exe
│       └── lib (INSTALLDIR_LIB)
└── CommonAppDataFolder (%ProgramData%)
    └── CAMserv (CAMSERVDATA)
        ├── config (DIR_CONFIG)
        │   └── camserv.default.yaml
        ├── data (DIR_DATA) [PERMANENT]
        ├── recordings (DIR_RECORDINGS) [PERMANENT]
        ├── vault (DIR_VAULT) [PERMANENT]
        ├── logs (DIR_LOGS)
        └── backups (DIR_BACKUPS)
```

---

## 4. Evidence & Data Preservation Policy

Enterprise digital forensics and video surveillance require that recordings and evidence vaults are **never deleted silently** during product uninstallation or upgrades.

### Implementation:
- The components `cmp_recordings`, `cmp_vault`, and `cmp_data` are authored with the `msidbComponentAttributesPermanent` (`0x0010`) flag.
- During uninstallation (`MsiInstallProduct` / `REMOVE=ALL`), Windows Installer checks this attribute and strictly skips deletion of directories and database files registered under these components.

---

## 5. Automated SCM Registration

The MSI package includes native database tables for Windows Service integration:
- **`ServiceInstall` Table:**
  - Name: `CAMservCore`
  - DisplayName: `CAMserv Core Security Service`
  - ServiceType: `16` (`SERVICE_WIN32_OWN_PROCESS`)
  - StartType: `2` (`SERVICE_AUTO_START`)
  - ErrorControl: `1` (`SERVICE_ERROR_NORMAL`)
  - StartName: `LocalSystem`
- **`ServiceControl` Table:**
  - Configured with event mask `35` (Start on install, stop on uninstall, stop on reinstall).

---

## 6. Verification & Automated Test Evidence

- **Unit Test:** `test_windows_msi_builder_execution` — PASSED.
- **Unit Test:** `test_windows_msi_tables_and_service_schema` — PASSED.
- **Verification Script:** Evaluated via Win32 `MsiOpenDatabaseW` and verified all properties, services, and permanence flags.
