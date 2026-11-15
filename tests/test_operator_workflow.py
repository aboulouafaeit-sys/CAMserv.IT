"""
tests.test_operator_workflow
============================

Unit tests for CAMserv 14-screen operator workflow and Human-in-the-Loop (HITL) governance:
verifying that no consequential physical action can ever be dispatched solely by unreviewed AI.
"""

import pytest

from camserv.web.operator_workflow import (
    IncidentWorkflowRecord,
    OperatorWorkflowEngine,
    WorkflowActionError,
    WorkflowStage,
)


def test_operator_workflow_complete_successful_lifecycle():
    """Verify the complete 6-stage human-in-the-loop governance sequence."""
    engine = OperatorWorkflowEngine()

    # Step 1: Detection hypothesis registered
    rec = engine.register_detection(
        incident_id="INC-2026-001",
        camera_id="cam_gate_north",
        event_type="RESTRICTED_ZONE_INTRUSION",
        confidence=0.92,
    )
    assert rec.stage == WorkflowStage.QUEUED_FOR_REVIEW

    # Step 2: Operator Alice opens evidence explorer
    engine.begin_inspection("INC-2026-001", operator_id="alice")
    assert rec.stage == WorkflowStage.UNDER_INSPECTION
    assert rec.assigned_operator == "alice"

    # Step 3: Alice confirms real threat based on ground contact telemetry
    engine.record_human_decision("INC-2026-001", operator_id="alice", confirmed=True, notes="Individual climbed over fence.")
    assert rec.stage == WorkflowStage.CONFIRMED_HUMAN_VERIFIED

    # Step 4: Alice authorizes physical response
    engine.authorize_consequential_dispatch(
        incident_id="INC-2026-001",
        operator_id="alice",
        action_name="LOCK_PERIMETER_GATE",
        justification="Confirmed intrusion in secure zone",
    )
    assert rec.stage == WorkflowStage.DISPATCH_AUTHORIZED
    assert "LOCK_PERIMETER_GATE" in (rec.authorized_action or "")

    # Step 5: Case sealed into audit trail
    engine.seal_in_audit_chain("INC-2026-001", audit_entry_hash="a1b2c3d4e5f67890" * 4)
    assert rec.stage == WorkflowStage.SEALED_IN_AUDIT
    assert rec.audit_chain_hash is not None


def test_unreviewed_ai_cannot_trigger_dispatch():
    """Verify that attempting to trigger dispatch without human confirmation is strictly blocked."""
    engine = OperatorWorkflowEngine()
    engine.register_detection("INC-UNVERIFIED", "cam_1", "PERIMETER_LOITERING", 0.98)

    # Attempting dispatch directly from QUEUED_FOR_REVIEW MUST fail!
    with pytest.raises(WorkflowActionError, match="CRITICAL GOVERNANCE VIOLATION"):
        engine.authorize_consequential_dispatch(
            incident_id="INC-UNVERIFIED",
            operator_id="system_auto",
            action_name="DISPATCH_ARMED_GUARDS",
            justification="High algorithmic confidence",
        )

    # Begin inspection, but still unconfirmed -> dispatch MUST fail!
    engine.begin_inspection("INC-UNVERIFIED", operator_id="bob")
    with pytest.raises(WorkflowActionError, match="CRITICAL GOVERNANCE VIOLATION"):
        engine.authorize_consequential_dispatch(
            incident_id="INC-UNVERIFIED",
            operator_id="bob",
            action_name="SOUND_ALARM",
            justification="Inspection in progress",
        )


def test_dismissed_false_positive_workflow():
    """Verify that false positives are dismissed cleanly and cannot trigger dispatch."""
    engine = OperatorWorkflowEngine()
    engine.register_detection("INC-FALSE-ALARM", "cam_2", "SCHEDULE_ANOMALY", 0.65)

    engine.begin_inspection("INC-FALSE-ALARM", operator_id="carol")
    engine.record_human_decision("INC-FALSE-ALARM", operator_id="carol", confirmed=False, notes="Authorized night shift cleaner.")
    assert engine.incidents["INC-FALSE-ALARM"].stage == WorkflowStage.DISMISSED_FALSE_POSITIVE

    # Dispatch on dismissed alert MUST fail!
    with pytest.raises(WorkflowActionError, match="CRITICAL GOVERNANCE VIOLATION"):
        engine.authorize_consequential_dispatch(
            incident_id="INC-FALSE-ALARM",
            operator_id="carol",
            action_name="DISPATCH_SECURITY",
            justification="Error",
        )

    # Dismissed alert can be sealed in audit trail
    engine.seal_in_audit_chain("INC-FALSE-ALARM", audit_entry_hash="00112233" * 8)
    assert engine.incidents["INC-FALSE-ALARM"].stage == WorkflowStage.SEALED_IN_AUDIT


def test_operator_mismatch_prevention():
    """Verify that an operator cannot sign off on an inspection claimed by another without handover."""
    engine = OperatorWorkflowEngine()
    engine.register_detection("INC-HANDOVER", "cam_3", "CAMERA_TAMPERING", 0.88)

    engine.begin_inspection("INC-HANDOVER", operator_id="operator_alice")

    with pytest.raises(WorkflowActionError, match="Operator mismatch"):
        engine.record_human_decision("INC-HANDOVER", operator_id="operator_bob", confirmed=True, notes="Tampered")
