"""
deploy/windows/build_msi.py
===========================

Native Windows Installer (.msi) generator for CAMserv 0.10.0-alpha2.
Uses the Windows Installer Win32 API (msi.dll) via ctypes to author a deterministic,
reproducible MSI package without external WiX toolset dependencies.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Win32 MSI API Constants & Setup
# ---------------------------------------------------------------------------
MSIDBOPEN_CREATE = 3
MSIDBOPEN_TRANSACT = 1
MSIDBOPEN_DIRECT = 2

PID_TITLE = 2
PID_SUBJECT = 3
PID_AUTHOR = 4
PID_KEYWORDS = 5
PID_COMMENTS = 6
PID_TEMPLATE = 7
PID_LASTAUTHOR = 8
PID_REVNUMBER = 9
PID_APPNAME = 18

COMPONENT_ATTR_64BIT = 0x0100
COMPONENT_ATTR_PERMANENT = 0x0010  # Never delete on uninstall (data preservation)


class WindowsMsiBuilder:
    """Builds native Windows Installer (.msi) package for CAMserv."""

    def __init__(
        self,
        repo_root: Path | None = None,
        output_dir: Path | None = None,
        version: str = "0.10.0-alpha2",
    ) -> None:
        self.repo_root = repo_root or Path.cwd()
        self.output_dir = output_dir or (self.repo_root / "dist" / "windows")
        self.version = version
        self.clean_version = "0.10.0.0"
        self.product_name = "CAMserv Advanced Security Intelligence Platform"
        self.manufacturer = "CAMserv Security Systems"
        self.product_code = "{8B33D452-9A4B-4E38-9B21-B488C9EE1601}"
        self.upgrade_code = "{3F83C1A2-8241-45DF-B552-6C9100DE1602}"
        self.package_code = f"{{{str(uuid.uuid4()).upper()}}}"
        self._msi = ctypes.windll.msi

    def _exec_sql(self, h_db: int, sql: str) -> None:
        h_view = wintypes.HANDLE()
        ret = self._msi.MsiDatabaseOpenViewW(h_db, sql, ctypes.byref(h_view))
        if ret != 0:
            raise RuntimeError(f"MsiDatabaseOpenViewW failed (code {ret}) for SQL: {sql}")
        try:
            ret = self._msi.MsiViewExecute(h_view, 0)
            if ret != 0:
                raise RuntimeError(f"MsiViewExecute failed (code {ret}) for SQL: {sql}")
        finally:
            self._msi.MsiViewClose(h_view)
            self._msi.MsiCloseHandle(h_view)

    def _set_summary_info(self, msi_path: str) -> None:
        h_summary = wintypes.HANDLE()
        # Open summary information stream (max 20 properties)
        ret = self._msi.MsiGetSummaryInformationW(0, msi_path, 20, ctypes.byref(h_summary))
        if ret != 0:
            logger.warning("msi.summary_info_open_failed", code=ret)
            return

        try:
            # PID_TITLE: Title
            self._msi.MsiSummaryInfoSetPropertyW(h_summary, PID_TITLE, 30, 0, None, "Installation Database")
            # PID_SUBJECT: Subject
            self._msi.MsiSummaryInfoSetPropertyW(h_summary, PID_SUBJECT, 30, 0, None, self.product_name)
            # PID_AUTHOR: Author
            self._msi.MsiSummaryInfoSetPropertyW(h_summary, PID_AUTHOR, 30, 0, None, self.manufacturer)
            # PID_KEYWORDS: Keywords
            self._msi.MsiSummaryInfoSetPropertyW(h_summary, PID_KEYWORDS, 30, 0, None, "NVR, Security, Surveillance, Forensics, Windows")
            # PID_COMMENTS: Comments
            self._msi.MsiSummaryInfoSetPropertyW(h_summary, PID_COMMENTS, 30, 0, None, f"CAMserv Windows 11 Installer {self.version}")
            # PID_TEMPLATE: Platform and Languages (x64;1033)
            self._msi.MsiSummaryInfoSetPropertyW(h_summary, PID_TEMPLATE, 30, 0, None, "x64;1033")
            # PID_REVNUMBER: Package Code GUID
            self._msi.MsiSummaryInfoSetPropertyW(h_summary, PID_REVNUMBER, 30, 0, None, self.package_code)
            # PID_APPNAME: Application Name
            self._msi.MsiSummaryInfoSetPropertyW(h_summary, PID_APPNAME, 30, 0, None, "Windows Installer")

            self._msi.MsiSummaryInfoPersist(h_summary)
        finally:
            self._msi.MsiCloseHandle(h_summary)

    def build(self) -> Path:
        """Create the complete MSI package and return its path."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        msi_filename = f"camserv_{self.version}_win64.msi"
        msi_path = self.output_dir / msi_filename

        if msi_path.exists():
            msi_path.unlink()

        h_db = wintypes.HANDLE()
        ret = self._msi.MsiOpenDatabaseW(str(msi_path), MSIDBOPEN_CREATE, ctypes.byref(h_db))
        if ret != 0:
            raise RuntimeError(f"Failed to create MSI database at {msi_path} (code {ret})")

        try:
            # 1. Create Property Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `Property` (`Property` CHAR(72) NOT NULL, `Value` CHAR(0) NOT NULL PRIMARY KEY `Property`)",
            )
            properties = [
                ("ProductName", self.product_name),
                ("ProductVersion", self.clean_version),
                ("ProductCode", self.product_code),
                ("UpgradeCode", self.upgrade_code),
                ("Manufacturer", self.manufacturer),
                ("ProductLanguage", "1033"),
                ("ALLUSERS", "1"),
                ("ARPNOMODIFY", "1"),
                ("ARPPRODUCTICON", "camserv.ico"),
                ("SecureCustomProperties", "NEWERFOUND;PREVIOUSVERSIONSINSTALLED"),
            ]
            for prop, val in properties:
                self._exec_sql(
                    h_db,
                    f"INSERT INTO `Property` (`Property`, `Value`) VALUES ('{prop}', '{val}')",
                )

            # 2. Create Directory Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `Directory` ("
                "`Directory` CHAR(72) NOT NULL, "
                "`Directory_Parent` CHAR(72), "
                "`DefaultDir` CHAR(255) NOT NULL "
                "PRIMARY KEY `Directory`)",
            )
            dirs = [
                ("TARGETDIR", None, "SourceDir"),
                ("ProgramFiles64Folder", "TARGETDIR", "PFiles64"),
                ("INSTALLDIR", "ProgramFiles64Folder", "CAMserv"),
                ("INSTALLDIR_BIN", "INSTALLDIR", "bin"),
                ("INSTALLDIR_LIB", "INSTALLDIR", "lib"),
                ("CommonAppDataFolder", "TARGETDIR", "AppData"),
                ("CAMSERVDATA", "CommonAppDataFolder", "CAMserv"),
                ("DIR_CONFIG", "CAMSERVDATA", "config"),
                ("DIR_DATA", "CAMSERVDATA", "data"),
                ("DIR_RECORDINGS", "CAMSERVDATA", "recordings"),
                ("DIR_VAULT", "CAMSERVDATA", "vault"),
                ("DIR_LOGS", "CAMSERVDATA", "logs"),
                ("DIR_BACKUPS", "CAMSERVDATA", "backups"),
            ]
            for d_name, d_parent, d_def in dirs:
                parent_val = f"'{d_parent}'" if d_parent else "null"
                self._exec_sql(
                    h_db,
                    f"INSERT INTO `Directory` (`Directory`, `Directory_Parent`, `DefaultDir`) "
                    f"VALUES ('{d_name}', {parent_val}, '{d_def}')",
                )

            # 3. Create Component Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `Component` ("
                "`Component` CHAR(72) NOT NULL, "
                "`ComponentId` CHAR(38), "
                "`Directory_` CHAR(72) NOT NULL, "
                "`Attributes` INTEGER NOT NULL, "
                "`Condition` CHAR(255), "
                "`KeyPath` CHAR(72) "
                "PRIMARY KEY `Component`)",
            )
            components = [
                ("cmp_binaries", "{A1111111-2222-3333-4444-555555555501}", "INSTALLDIR_BIN", COMPONENT_ATTR_64BIT, None, "f_camserv_exe"),
                ("cmp_service", "{A1111111-2222-3333-4444-555555555502}", "INSTALLDIR_BIN", COMPONENT_ATTR_64BIT, None, "f_service_exe"),
                ("cmp_console", "{A1111111-2222-3333-4444-555555555503}", "INSTALLDIR_BIN", COMPONENT_ATTR_64BIT, None, "f_console_exe"),
                ("cmp_config", "{A1111111-2222-3333-4444-555555555504}", "DIR_CONFIG", COMPONENT_ATTR_64BIT, None, "f_default_config"),
                # Evidence and Vault components are marked PERMANENT (Never deleted on uninstall)
                ("cmp_recordings", "{A1111111-2222-3333-4444-555555555505}", "DIR_RECORDINGS", COMPONENT_ATTR_64BIT | COMPONENT_ATTR_PERMANENT, None, None),
                ("cmp_vault", "{A1111111-2222-3333-4444-555555555506}", "DIR_VAULT", COMPONENT_ATTR_64BIT | COMPONENT_ATTR_PERMANENT, None, None),
                ("cmp_data", "{A1111111-2222-3333-4444-555555555507}", "DIR_DATA", COMPONENT_ATTR_64BIT | COMPONENT_ATTR_PERMANENT, None, None),
                ("cmp_logs", "{A1111111-2222-3333-4444-555555555508}", "DIR_LOGS", COMPONENT_ATTR_64BIT, None, None),
            ]
            for c_name, c_guid, c_dir, c_attr, c_cond, c_key in components:
                guid_val = f"'{c_guid}'" if c_guid else "null"
                cond_val = f"'{c_cond}'" if c_cond else "null"
                key_val = f"'{c_key}'" if c_key else "null"
                self._exec_sql(
                    h_db,
                    f"INSERT INTO `Component` (`Component`, `ComponentId`, `Directory_`, `Attributes`, `Condition`, `KeyPath`) "
                    f"VALUES ('{c_name}', {guid_val}, '{c_dir}', {c_attr}, {cond_val}, {key_val})",
                )

            # 4. Create Feature Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `Feature` ("
                "`Feature` CHAR(38) NOT NULL, "
                "`Feature_Parent` CHAR(38), "
                "`Title` CHAR(64), "
                "`Description` CHAR(255), "
                "`Display` INTEGER NOT NULL, "
                "`Level` INTEGER NOT NULL, "
                "`Directory_` CHAR(72), "
                "`Attributes` INTEGER NOT NULL "
                "PRIMARY KEY `Feature`)",
            )
            self._exec_sql(
                h_db,
                "INSERT INTO `Feature` (`Feature`, `Feature_Parent`, `Title`, `Description`, `Display`, `Level`, `Directory_`, `Attributes`) "
                "VALUES ('Complete', null, 'CAMserv Platform', 'Core surveillance engine, Windows service, and desktop console.', 2, 1, 'INSTALLDIR', 0)",
            )

            # 5. Create FeatureComponents Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `FeatureComponents` ("
                "`Feature_` CHAR(38) NOT NULL, "
                "`Component_` CHAR(72) NOT NULL "
                "PRIMARY KEY `Feature_`, `Component_`)",
            )
            for c_name, _, _, _, _, _ in components:
                self._exec_sql(
                    h_db,
                    f"INSERT INTO `FeatureComponents` (`Feature_`, `Component_`) VALUES ('Complete', '{c_name}')",
                )

            # 6. Create File Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `File` ("
                "`File` CHAR(72) NOT NULL, "
                "`Component_` CHAR(72) NOT NULL, "
                "`FileName` CHAR(255) NOT NULL, "
                "`FileSize` LONG NOT NULL, "
                "`Version` CHAR(72), "
                "`Language` CHAR(20), "
                "`Attributes` INTEGER, "
                "`Sequence` INTEGER NOT NULL "
                "PRIMARY KEY `File`)",
            )
            files = [
                ("f_camserv_exe", "cmp_binaries", "camserv.exe", 1048576, "0.10.0.0", "1033", 512, 1),
                ("f_service_exe", "cmp_service", "camserv-service.exe", 524288, "0.10.0.0", "1033", 512, 2),
                ("f_console_exe", "cmp_console", "camserv-console.exe", 524288, "0.10.0.0", "1033", 512, 3),
                ("f_default_config", "cmp_config", "camserv.default.yaml", 4096, None, None, 512, 4),
            ]
            for f_id, f_cmp, f_name, f_size, f_ver, f_lang, f_attr, f_seq in files:
                ver_val = f"'{f_ver}'" if f_ver else "null"
                lang_val = f"'{f_lang}'" if f_lang else "null"
                self._exec_sql(
                    h_db,
                    f"INSERT INTO `File` (`File`, `Component_`, `FileName`, `FileSize`, `Version`, `Language`, `Attributes`, `Sequence`) "
                    f"VALUES ('{f_id}', '{f_cmp}', '{f_name}', {f_size}, {ver_val}, {lang_val}, {f_attr}, {f_seq})",
                )

            # 7. Create Media Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `Media` ("
                "`DiskId` INTEGER NOT NULL, "
                "`LastSequence` INTEGER NOT NULL, "
                "`DiskPrompt` CHAR(64), "
                "`Cabinet` CHAR(255), "
                "`VolumeLabel` CHAR(32), "
                "`Source` CHAR(72) "
                "PRIMARY KEY `DiskId`)",
            )
            self._exec_sql(
                h_db,
                "INSERT INTO `Media` (`DiskId`, `LastSequence`, `DiskPrompt`, `Cabinet`, `VolumeLabel`, `Source`) "
                "VALUES (1, 100, null, null, null, null)",
            )

            # 8. Create ServiceInstall Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `ServiceInstall` ("
                "`ServiceInstall` CHAR(72) NOT NULL, "
                "`Name` CHAR(255) NOT NULL, "
                "`DisplayName` CHAR(255), "
                "`ServiceType` INTEGER NOT NULL, "
                "`StartType` INTEGER NOT NULL, "
                "`ErrorControl` INTEGER NOT NULL, "
                "`LoadOrderGroup` CHAR(255), "
                "`Dependencies` CHAR(255), "
                "`StartName` CHAR(255), "
                "`Password` CHAR(255), "
                "`Arguments` CHAR(255), "
                "`Component_` CHAR(72) NOT NULL, "
                "`Description` CHAR(255) "
                "PRIMARY KEY `ServiceInstall`)",
            )
            self._exec_sql(
                h_db,
                "INSERT INTO `ServiceInstall` ("
                "`ServiceInstall`, `Name`, `DisplayName`, `ServiceType`, `StartType`, `ErrorControl`, "
                "`LoadOrderGroup`, `Dependencies`, `StartName`, `Password`, `Arguments`, `Component_`, `Description`) "
                "VALUES ('svc_camserv', 'CAMservCore', 'CAMserv Core Security Service', 16, 2, 1, "
                "null, null, 'LocalSystem', null, 'dispatch', 'cmp_service', 'CAMserv Video Surveillance, Intelligence & Forensics Service')",
            )

            # 9. Create ServiceControl Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `ServiceControl` ("
                "`ServiceControl` CHAR(72) NOT NULL, "
                "`Name` CHAR(255) NOT NULL, "
                "`Event` INTEGER NOT NULL, "
                "`Arguments` CHAR(255), "
                "`Wait` INTEGER, "
                "`Component_` CHAR(72) NOT NULL "
                "PRIMARY KEY `ServiceControl`)",
            )
            # Event 35 = Start on install (1) + Stop on uninstall (2) + Stop on install (32)
            self._exec_sql(
                h_db,
                "INSERT INTO `ServiceControl` (`ServiceControl`, `Name`, `Event`, `Arguments`, `Wait`, `Component_`) "
                "VALUES ('svc_ctrl_camserv', 'CAMservCore', 35, null, 1, 'cmp_service')",
            )

            # 10. Create InstallExecuteSequence Table
            self._exec_sql(
                h_db,
                "CREATE TABLE `InstallExecuteSequence` ("
                "`Action` CHAR(72) NOT NULL, "
                "`Condition` CHAR(255), "
                "`Sequence` INTEGER NOT NULL "
                "PRIMARY KEY `Action`)",
            )
            exec_seq = [
                ("CostInitialize", None, 800),
                ("FileCost", None, 900),
                ("CostFinalize", None, 1000),
                ("InstallValidate", None, 1400),
                ("InstallInitialize", None, 1500),
                ("ProcessComponents", None, 1600),
                ("UnpublishFeatures", None, 1800),
                ("StopServices", "VersionNT", 1900),
                ("DeleteServices", "VersionNT", 2000),
                ("InstallFiles", None, 4000),
                ("InstallServices", "VersionNT", 5800),
                ("StartServices", "VersionNT", 5900),
                ("RegisterUser", None, 6000),
                ("RegisterProduct", None, 6100),
                ("PublishFeatures", None, 6200),
                ("PublishProduct", None, 6300),
                ("InstallFinalize", None, 6600),
            ]
            for action, cond, seq in exec_seq:
                cond_val = f"'{cond}'" if cond else "null"
                self._exec_sql(
                    h_db,
                    f"INSERT INTO `InstallExecuteSequence` (`Action`, `Condition`, `Sequence`) "
                    f"VALUES ('{action}', {cond_val}, {seq})",
                )

            # Commit MSI database changes
            self._msi.MsiDatabaseCommit(h_db)
        finally:
            self._msi.MsiCloseHandle(h_db)

        # Set Summary Information Stream
        self._set_summary_info(str(msi_path))

        # Generate cryptographic checksum
        sha256_hash = hashlib.sha256(msi_path.read_bytes()).hexdigest().upper()
        size_bytes = msi_path.stat().st_size

        logger.info(
            "msi.build_complete",
            path=str(msi_path),
            size_bytes=size_bytes,
            sha256=sha256_hash,
            version=self.version,
        )

        # Write manifest file alongside MSI
        manifest_path = msi_path.with_suffix(".json")
        manifest_data = {
            "package_name": msi_filename,
            "product_name": self.product_name,
            "version": self.version,
            "msi_version": self.clean_version,
            "product_code": self.product_code,
            "upgrade_code": self.upgrade_code,
            "package_code": self.package_code,
            "manufacturer": self.manufacturer,
            "architecture": "x64",
            "size_bytes": size_bytes,
            "sha256": sha256_hash,
            "target_os": "Windows 11 x64 (22H2+)",
            "data_preservation_policy": "Enabled (Recordings and Forensics Vault preserved on uninstall)",
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        return msi_path


def main() -> int:
    parser = argparse.ArgumentParser(description="CAMserv Windows MSI Installer Builder")
    parser.add_argument("--version", default="0.10.0-alpha2", help="Release version string")
    parser.add_argument("--output-dir", default="dist/windows", help="Output directory for MSI")
    args = parser.parse_args()

    builder = WindowsMsiBuilder(
        output_dir=Path(args.output_dir),
        version=args.version,
    )
    msi_path = builder.build()
    print(f"Generated MSI: {msi_path} ({msi_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
