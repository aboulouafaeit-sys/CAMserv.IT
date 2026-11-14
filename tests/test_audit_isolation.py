"""Regression test verifying test audit log isolation (Phase 1A Condition C1)."""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from camserv.api.app import create_app
from camserv.security.audit import AuditAction, AuditLogger


@pytest.mark.unit
def test_audit_log_isolated_from_production() -> None:
    """Verify that CAMSERV_SECURITY__AUDIT_LOG_PATH points to a temporary location during tests."""
    active_path = os.environ.get("CAMSERV_SECURITY__AUDIT_LOG_PATH")
    assert active_path is not None, "CAMSERV_SECURITY__AUDIT_LOG_PATH must be set during test sessions"
    
    # Must NOT point to the production logs/audit.jsonl file
    prod_path = Path("logs/audit.jsonl").resolve()
    test_path = Path(active_path).resolve()
    assert test_path != prod_path, f"Test audit path {test_path} must not be production path {prod_path}"


@pytest.mark.unit
def test_create_app_respects_custom_audit_path(tmp_path: Path) -> None:
    """Verify create_app respects the isolated audit path without touching logs/audit.jsonl."""
    custom_log = tmp_path / "custom_audit.jsonl"
    os.environ["CAMSERV_SECURITY__AUDIT_LOG_PATH"] = str(custom_log)
    try:
        app = create_app()
        audit: AuditLogger = app.state.audit_logger
        audit.log(
            actor="test_runner",
            action=AuditAction.CONFIG_CHANGE,
            resource="test_resource",
            result="SUCCESS",
        )
        assert custom_log.exists()
        assert custom_log.stat().st_size > 0
    finally:
        pass
