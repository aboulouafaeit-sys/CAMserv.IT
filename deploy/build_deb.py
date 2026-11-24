#!/usr/bin/env python3
"""
deploy/build_deb.py
===================

Pure Python Debian (.deb) Package Builder & Inspector for CAMserv.
Builds 100% standards-compliant Debian packages (Debian 13 Trixie, Debian 12 Bookworm, Ubuntu 24.04 LTS)
without requiring native dpkg-deb or GNU ar binaries.
Supports amd64 (x86_64) and arm64 (aarch64) multi-architecture builds.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import platform
import shutil
import stat
import struct
import sys
import tarfile
from pathlib import Path
from typing import Any, BinaryIO

PACKAGE_NAME = "camserv"
DEFAULT_VERSION = "0.10.0-rc7"


def create_ar_header(filename: str, size: int, mode: int = 0o100644, mtime: int = 0) -> bytes:
    """Format a standard BSD/GNU ar member header (60 bytes)."""
    # ar header format:
    # 0..15:  file name (padded with space or slash)
    # 16..27: modification time (decimal)
    # 28..33: owner ID (decimal)
    # 34..39: group ID (decimal)
    # 40..47: file mode (octal)
    # 48..57: file size (decimal)
    # 58..59: magic bytes (\x60\x0a)
    name_field = f"{filename}/".ljust(16)[:16].encode("ascii")
    mtime_field = str(mtime).ljust(12)[:12].encode("ascii")
    uid_field = "0".ljust(6)[:6].encode("ascii")
    gid_field = "0".ljust(6)[:6].encode("ascii")
    mode_field = f"{mode:o}".ljust(8)[:8].encode("ascii")
    size_field = str(size).ljust(10)[:10].encode("ascii")
    magic = b"\x60\n"

    header = name_field + mtime_field + uid_field + gid_field + mode_field + size_field + magic
    assert len(header) == 60, f"Header size must be 60 bytes, got {len(header)}"
    return header


def build_tar_gz(source_dir: Path, base_in_tar: str = ".") -> bytes:
    """Pack a directory into a reproducible gzip-compressed tar archive."""
    buf = io.BytesIO()
    # Fixed mtime for deterministic builds
    fixed_mtime = 1794840000  # Nov 2026

    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=fixed_mtime) as gz_out:
        with tarfile.open(fileobj=gz_out, mode="w", format=tarfile.PAX_FORMAT) as tar:
            # Walk directory sorted
            for root, dirs, files in os.walk(source_dir):
                dirs.sort()
                files.sort()
                rel_root = Path(root).relative_to(source_dir)
                for d in dirs:
                    d_path = Path(root) / d
                    tar_path = (Path(base_in_tar) / rel_root / d).as_posix()
                    ti = tar.gettarinfo(d_path, arcname=tar_path)
                    ti.uid = 0
                    ti.gid = 0
                    ti.uname = "root"
                    ti.gname = "root"
                    ti.mtime = fixed_mtime
                    ti.mode = 0o755
                    tar.addfile(ti)

                for f in files:
                    f_path = Path(root) / f
                    tar_path = (Path(base_in_tar) / rel_root / f).as_posix()
                    ti = tar.gettarinfo(f_path, arcname=tar_path)
                    ti.uid = 0
                    ti.gid = 0
                    ti.uname = "root"
                    ti.gname = "root"
                    ti.mtime = fixed_mtime
                    # Executable permissions for scripts and binaries
                    if "bin/" in tar_path or "DEBIAN/post" in tar_path or "DEBIAN/pre" in tar_path:
                        ti.mode = 0o755
                    else:
                        ti.mode = 0o644
                    with open(f_path, "rb") as f_in:
                        tar.addfile(ti, f_in)

    return buf.getvalue()


class DebianPackageBuilder:
    """Constructs, audits, and validates a Debian package."""

    def __init__(
        self,
        repo_root: Path,
        version: str = DEFAULT_VERSION,
        arch: str = "amd64",
        output_dir: Path | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.version = version
        self.arch = arch
        self.output_dir = output_dir or (repo_root / "dist" / "deb")
        self.staging_dir = self.output_dir / f"{PACKAGE_NAME}_{version}_{arch}"

    def stage_files(self) -> None:
        """Stage application files, systemd services, configs, and Debian maintainer scripts."""
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)

        debian_dir = self.staging_dir / "DEBIAN"
        opt_dir = self.staging_dir / "opt" / "camserv"
        systemd_dir = self.staging_dir / "lib" / "systemd" / "system"
        bin_dir = self.staging_dir / "usr" / "bin"
        etc_dir = self.staging_dir / "etc" / "camserv"

        for p in [debian_dir, opt_dir, systemd_dir, bin_dir, etc_dir]:
            p.mkdir(parents=True, exist_ok=True)

        # 1. Maintainer scripts and control
        control_src = (self.repo_root / "deploy" / "debian" / "control").read_text(encoding="utf-8")
        # Ensure target architecture is updated
        lines = []
        for line in control_src.splitlines():
            if line.startswith("Architecture:"):
                lines.append(f"Architecture: {self.arch}")
            elif line.startswith("Version:"):
                lines.append(f"Version: {self.version}")
            else:
                lines.append(line)
        (debian_dir / "control").write_text("\n".join(lines) + "\n", encoding="utf-8")

        for script in ["postinst", "prerm", "postrm"]:
            src_script = self.repo_root / "deploy" / "debian" / script
            dst_script = debian_dir / script
            if src_script.exists():
                shutil.copy2(src_script, dst_script)
                os.chmod(dst_script, 0o755)

        # Conffiles
        (debian_dir / "conffiles").write_text("/etc/camserv/camserv.yaml\n", encoding="utf-8")

        # 2. Systemd service definitions
        sysd_src = self.repo_root / "deploy" / "systemd"
        for unit in sysd_src.glob("*"):
            if unit.is_file() and (unit.name.endswith(".service") or unit.name.endswith(".target")):
                shutil.copy2(unit, systemd_dir / unit.name)

        # 3. Default configuration
        cfg_src = self.repo_root / "deploy" / "camserv.default.yaml"
        if cfg_src.exists():
            shutil.copy2(cfg_src, etc_dir / "camserv.yaml")

        # 4. CLI wrapper in /usr/bin/camserv
        cli_launcher = (
            "#!/bin/sh\n"
            "# CAMserv CLI Launcher\n"
            "exec /opt/camserv/venv/bin/python -m camserv.main \"$@\"\n"
        )
        cli_file = bin_dir / "camserv"
        cli_file.write_text(cli_launcher, encoding="utf-8")
        os.chmod(cli_file, 0o755)

        # 5. Application source code and assets (clean copy)
        def _ignore_filter(directory: str, contents: list[str]) -> set[str]:
            ignored = set()
            for c in contents:
                if c in ["__pycache__", ".pytest_cache", ".git", ".mypy_cache"]:
                    ignored.add(c)
                elif c.endswith((".pyc", ".pyo", ".pyd", ".db", ".sqlite", ".pem", ".key")):
                    ignored.add(c)
            return ignored

        shutil.copytree(self.repo_root / "src", opt_dir / "src", ignore=_ignore_filter)
        for doc in ["pyproject.toml", "README.md", "LICENSE"]:
            doc_path = self.repo_root / doc
            if doc_path.exists():
                shutil.copy2(doc_path, opt_dir / doc)

        # 6. Generate md5sums for all data files
        md5_lines = []
        for root, _, files in os.walk(self.staging_dir):
            if "DEBIAN" in Path(root).parts:
                continue
            for f in sorted(files):
                full_path = Path(root) / f
                rel_path = full_path.relative_to(self.staging_dir).as_posix()
                with open(full_path, "rb") as fp:
                    digest = hashlib.md5(fp.read()).hexdigest()
                md5_lines.append(f"{digest}  {rel_path}")

        (debian_dir / "md5sums").write_text("\n".join(md5_lines) + "\n", encoding="utf-8")

    def audit_staging_safety(self) -> list[str]:
        """Perform security audit on staged files to ensure no secrets or test DBs are bundled."""
        violations = []
        prohibited_extensions = [".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pfx", ".p12", ".env"]
        prohibited_names = ["camserv.db", "audit.jsonl", "id_rsa", "id_ed25519", "test_secrets.yaml"]

        for root, _, files in os.walk(self.staging_dir):
            for f in files:
                f_path = Path(root) / f
                rel = f_path.relative_to(self.staging_dir).as_posix()

                # Check extensions
                for ext in prohibited_extensions:
                    if f.endswith(ext):
                        violations.append(f"Forbidden extension '{ext}': {rel}")

                # Check sensitive filenames
                if f in prohibited_names:
                    violations.append(f"Forbidden filename '{f}': {rel}")

                # Check secret tokens in non-binary files
                if f.endswith((".py", ".yaml", ".json", ".sh")) and f_path.stat().st_size < 100_000:
                    try:
                        content = f_path.read_text(encoding="utf-8", errors="ignore")
                        if "BEGIN RSA PRIVATE KEY" in content or "BEGIN OPENSSH PRIVATE KEY" in content:
                            violations.append(f"Private cryptographic key found in {rel}")
                    except Exception:
                        pass

        return violations

    def build_deb(self) -> Path:
        """Assemble the Debian package archive (.deb)."""
        self.stage_files()
        violations = self.audit_staging_safety()
        if violations:
            raise RuntimeError(f"Package staging security audit failed with {len(violations)} violations:\n" + "\n".join(violations))

        deb_filename = f"{PACKAGE_NAME}_{self.version}_{self.arch}.deb"
        deb_path = self.output_dir / deb_filename
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Member: debian-binary
        debian_binary = b"2.0\n"

        # 2. Member: control.tar.gz (DEBIAN directory contents)
        debian_dir = self.staging_dir / "DEBIAN"
        control_tar_gz = build_tar_gz(debian_dir, base_in_tar=".")

        # 3. Member: data.tar.gz (All files outside DEBIAN)
        # Create a temporary staging area for data files
        data_staging = self.output_dir / "data_staging"
        if data_staging.exists():
            shutil.rmtree(data_staging)
        data_staging.mkdir(parents=True)

        for item in self.staging_dir.iterdir():
            if item.name == "DEBIAN":
                continue
            if item.is_dir():
                shutil.copytree(item, data_staging / item.name)
            else:
                shutil.copy2(item, data_staging / item.name)

        data_tar_gz = build_tar_gz(data_staging, base_in_tar=".")
        shutil.rmtree(data_staging)

        # 4. Assemble the ar archive
        with open(deb_path, "wb") as deb:
            # ar signature
            deb.write(b"!<arch>\n")

            # debian-binary
            h1 = create_ar_header("debian-binary", len(debian_binary))
            deb.write(h1)
            deb.write(debian_binary)
            if len(debian_binary) % 2 != 0:
                deb.write(b"\n")

            # control.tar.gz
            h2 = create_ar_header("control.tar.gz", len(control_tar_gz))
            deb.write(h2)
            deb.write(control_tar_gz)
            if len(control_tar_gz) % 2 != 0:
                deb.write(b"\n")

            # data.tar.gz
            h3 = create_ar_header("data.tar.gz", len(data_tar_gz))
            deb.write(h3)
            deb.write(data_tar_gz)
            if len(data_tar_gz) % 2 != 0:
                deb.write(b"\n")

        return deb_path

    @staticmethod
    def inspect_deb(deb_path: Path) -> dict[str, Any]:
        """Inspect and parse an existing .deb package archive."""
        if not deb_path.exists():
            raise FileNotFoundError(f"Debian package not found: {deb_path}")

        sha256 = hashlib.sha256(deb_path.read_bytes()).hexdigest()
        file_size = deb_path.stat().st_size

        members: dict[str, bytes] = {}
        with open(deb_path, "rb") as f:
            magic = f.read(8)
            if magic != b"!<arch>\n":
                raise ValueError("Not a valid ar / debian archive (invalid magic header)")

            while True:
                header_bytes = f.read(60)
                if not header_bytes:
                    break
                if len(header_bytes) < 60:
                    break
                name = header_bytes[0:16].decode("ascii").strip().rstrip("/")
                size = int(header_bytes[48:58].decode("ascii").strip())
                data = f.read(size)
                members[name] = data
                if size % 2 != 0:
                    f.read(1)  # Padding byte

        control_files: list[str] = []
        control_text = ""
        if "control.tar.gz" in members:
            with gzip.GzipFile(fileobj=io.BytesIO(members["control.tar.gz"])) as gz:
                with tarfile.open(fileobj=gz, mode="r") as tar:
                    control_files = tar.getnames()
                    for m in tar.getmembers():
                        if m.name.endswith("control") and m.isfile():
                            ctl = tar.extractfile(m)
                            if ctl:
                                control_text = ctl.read().decode("utf-8")
                                break

        data_files: list[str] = []
        if "data.tar.gz" in members:
            with gzip.GzipFile(fileobj=io.BytesIO(members["data.tar.gz"])) as gz:
                with tarfile.open(fileobj=gz, mode="r") as tar:
                    data_files = tar.getnames()

        return {
            "path": str(deb_path),
            "size_bytes": file_size,
            "sha256": sha256,
            "ar_members": list(members.keys()),
            "control_files": control_files,
            "control_text": control_text,
            "data_file_count": len(data_files),
            "data_files": data_files,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="CAMserv Debian Package Builder & Inspector")
    parser.add_argument("--version", default=DEFAULT_VERSION, help="Target package version")
    parser.add_argument("--arch", default="amd64", choices=["amd64", "arm64"], help="Target CPU architecture")
    parser.add_argument("--inspect", type=str, default=None, help="Inspect an existing .deb file")

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent

    if args.inspect:
        deb_file = Path(args.inspect)
        report = DebianPackageBuilder.inspect_deb(deb_file)
        print(f"\n[CAMserv Debian Package Inspection: {deb_file.name}]")
        print("=" * 70)
        print(f"Size:        {report['size_bytes']} bytes ({report['size_bytes'] / 1024:.1f} KB)")
        print(f"SHA-256:     {report['sha256']}")
        print(f"AR Members:  {', '.join(report['ar_members'])}")
        print(f"Data Files:  {report['data_file_count']} installed items")
        print("-" * 70)
        print("Package Control Manifest:")
        print(report["control_text"])
        print("-" * 70)
        print("Installed Systemd Units:")
        for df in report["data_files"]:
            if "systemd" in df:
                print(f"  - {df}")
        print("=" * 70 + "\n")
        return

    print(f"\n[*] Building CAMserv Debian package ({args.version}, {args.arch})...")
    builder = DebianPackageBuilder(repo_root=repo_root, version=args.version, arch=args.arch)
    deb_path = builder.build_deb()
    report = DebianPackageBuilder.inspect_deb(deb_path)

    print(f"[+] Successfully built: {deb_path}")
    print(f"    Size:        {report['size_bytes']} bytes ({report['size_bytes'] / 1024:.1f} KB)")
    print(f"    SHA-256:     {report['sha256']}")
    print(f"    Data Files:  {report['data_file_count']} files bundled")
    print(f"    AR Members:  {', '.join(report['ar_members'])}\n")


if __name__ == "__main__":
    main()
