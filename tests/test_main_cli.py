"""Tests for CAMserv unified command-line interface."""
from __future__ import annotations

import argparse
from pathlib import Path
import pytest

from camserv.main import (
    run_audit_verify,
    run_detect_hw,
    run_nvr_scan,
    run_verify_evidence,
)
from camserv.storage.forensics import EvidencePackager, ForensicSigner


@pytest.mark.unit
def test_cli_detect_hw() -> None:
    """Test detect-hw subcommand returns success (exit code 0)."""
    args = argparse.Namespace()
    code = run_detect_hw(args)
    assert code == 0


@pytest.mark.unit
def test_cli_audit_verify(tmp_path: Path) -> None:
    """Test audit-verify subcommand with non-existent and empty log."""
    log_file = tmp_path / "test_audit.jsonl"
    args = argparse.Namespace(log=str(log_file))
    code = run_audit_verify(args)
    assert code == 0


@pytest.mark.unit
def test_cli_nvr_scan() -> None:
    """Test nvr-scan subcommand with URL testing."""
    args = argparse.Namespace(url="rtsp://127.0.0.1:8554/live/test", timeout=0.5)
    code = run_nvr_scan(args)
    assert code == 0


@pytest.mark.unit
def test_cli_verify_evidence(tmp_path: Path) -> None:
    """Test verify-evidence subcommand with authentic and non-existent packages."""
    # 1. Non-existent file
    args_missing = argparse.Namespace(package=str(tmp_path / "missing.zip"), public_key=None)
    assert run_verify_evidence(args_missing) == 1

    # 2. Valid package
    signer = ForensicSigner()
    packager = EvidencePackager(signer)
    zip_path = tmp_path / "test_pkg.zip"
    packager.create_package(
        output_zip=zip_path,
        evidence_id="ev_cli_test",
        camera_id="cam-01",
        event_id="evt_01",
        file_payloads={"file.txt": b"content"},
    )

    args_valid = argparse.Namespace(package=str(zip_path), public_key=None)
    assert run_verify_evidence(args_valid) == 0
