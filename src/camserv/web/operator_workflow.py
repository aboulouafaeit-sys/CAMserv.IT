"""
camserv.web.operator_workflow
=============================

Professional security operator workflow engine and Human-in-the-Loop (HITL)
governance for the 14-screen CAMserv Operations Console.
Guarantees that no consequential physical action can ever be dispatched
solely by unreviewed algorithmic inference.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class WorkflowStage(str, enum.Enum):
    """Sequential operational triage phases."""

    DETECTED = "detected"                      # Step 1: Algorithmic detection flagged (hypothesis)
    QUEUED_FOR_REVIEW = "queued_for_review"    # Step 2: Event queued on operator console
    UNDER_INSPECTION = "under_inspection"      # Step 3: Operator actively inspecting evidence & telemetry
    DISMISSED_FALSE_POSITIVE = "dismissed_false_positive" # Operator rejected alert (calibrates models)
    CONFIRMED_HUMAN_VERIFIED = "confirmed_human_verified" # Step 4: Human confirmed real threat
    DISPATCH_AUTHORIZED = "dispatch_authorized"# Step 5: Operator authorized consequential physical response
    SEALED_IN_AUDIT = "sealed_in_audit"        # Step 6: Case closed and sealed in cryptographic audit trail


class WorkflowActionError(PermissionError):
    """Raised when an action violates human-in-the-loop governance invariants."""


@dataclass(slots=True)
class IncidentWorkflowRecord:
    """Stateful record tracking the progression of a security incident through operator review."""

    incident_id: str
    camera_id: str
    event_type: str
    algorithmic_confidence: float
    stage: WorkflowStage = WorkflowStage.DETECTED
    assigned_operator: str | None = None
    review_notes: str = ""
    inspection_started_at: float | None = None
    confirmed_at: float | None = None
    authorized_action: str | None = None
    audit_chain_hash: str | None = None
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize workflow record."""
        return {
            "incident_id": self.incident_id,
            "camera_id": self.camera_id,
            "event_type": self.event_type,
            "algorithmic_confidence": round(self.algorithmic_confidence, 3),
            "stage": self.stage.value,
            "assigned_operator": self.assigned_operator,
            "review_notes": self.review_notes,
            "inspection_started_at": self.inspection_started_at,
            "confirmed_at": self.confirmed_at,
            "authorized_action": self.authorized_action,
            "audit_chain_hash": self.audit_chain_hash,
            "created_at": self.created_at,
        }


class OperatorWorkflowEngine:
    """
    Enforces the mandatory 6-step human-in-the-loop security governance pipeline:
    Camera alert -> Event review -> Evidence inspection -> Human decision -> Authorized action -> Audit record.
    """

    def __init__(self) -> None:
        self.incidents: dict[str, IncidentWorkflowRecord] = {}

    def register_detection(
        self,
        incident_id: str,
        camera_id: str,
        event_type: str,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> IncidentWorkflowRecord:
        """Register a probabilistic algorithmic threat detection hypothesis."""
        record = IncidentWorkflowRecord(
            incident_id=incident_id,
            camera_id=camera_id,
            event_type=event_type,
            algorithmic_confidence=confidence,
            stage=WorkflowStage.QUEUED_FOR_REVIEW,
            metadata=metadata or {},
        )
        self.incidents[incident_id] = record
        logger.info("workflow.incident_queued", incident_id=incident_id, camera=camera_id)
        return record

    def begin_inspection(self, incident_id: str, operator_id: str) -> IncidentWorkflowRecord:
        """Mark that an authorized operator has opened the telemetry and evidence explorer."""
        if incident_id not in self.incidents:
            raise ValueError(f"Incident '{incident_id}' not found.")

        rec = self.incidents[incident_id]
        if rec.stage not in (WorkflowStage.QUEUED_FOR_REVIEW, WorkflowStage.UNDER_INSPECTION):
            raise WorkflowActionError(f"Cannot begin inspection: Incident is in '{rec.stage.value}' stage.")

        rec.assigned_operator = operator_id
        rec.stage = WorkflowStage.UNDER_INSPECTION
        rec.inspection_started_at = time.time()
        logger.info("workflow.inspection_started", incident_id=incident_id, operator=operator_id)
        return rec

    def record_human_decision(
        self,
        incident_id: str,
        operator_id: str,
        confirmed: bool,
        notes: str,
    ) -> IncidentWorkflowRecord:
        """
        Record the operator's human decision after inspecting evidence.
        If confirmed: Transitions to CONFIRMED_HUMAN_VERIFIED.
        If dismissed: Transitions to DISMISSED_FALSE_POSITIVE.
        """
        if incident_id not in self.incidents:
            raise ValueError(f"Incident '{incident_id}' not found.")

        rec = self.incidents[incident_id]
        if rec.stage != WorkflowStage.UNDER_INSPECTION:
            raise WorkflowActionError("Cannot record decision: Operator must inspect evidence first.")

        if rec.assigned_operator and rec.assigned_operator != operator_id:
            raise WorkflowActionError(
                f"Operator mismatch: Incident was claimed by '{rec.assigned_operator}', not '{operator_id}'."
            )

        rec.review_notes = notes
        if confirmed:
            rec.stage = WorkflowStage.CONFIRMED_HUMAN_VERIFIED
            rec.confirmed_at = time.time()
            logger.info("workflow.incident_confirmed", incident_id=incident_id, operator=operator_id)
        else:
            rec.stage = WorkflowStage.DISMISSED_FALSE_POSITIVE
            logger.info("workflow.incident_dismissed", incident_id=incident_id, operator=operator_id)

        return rec

    def authorize_consequential_dispatch(
        self,
        incident_id: str,
        operator_id: str,
        action_name: str,
        justification: str,
    ) -> IncidentWorkflowRecord:
        """
        Authorize physical response (lock door, trigger strobe, dispatch security guards).
        MANDATORY INVARIANT: Cannot authorize action on unconfirmed or dismissed events!
        """
        if incident_id not in self.incidents:
            raise ValueError(f"Incident '{incident_id}' not found.")

        rec = self.incidents[incident_id]

        # Invariant: Must be human-confirmed
        if rec.stage != WorkflowStage.CONFIRMED_HUMAN_VERIFIED:
            logger.critical(
                "workflow.illegal_dispatch_attempt_blocked",
                incident_id=incident_id,
                stage=rec.stage.value,
                operator=operator_id,
            )
            raise WorkflowActionError(
                "CRITICAL GOVERNANCE VIOLATION: Consequential action cannot be triggered "
                f"while incident is in '{rec.stage.value}' stage. "
                "Human operator verification is strictly mandatory."
            )

        rec.stage = WorkflowStage.DISPATCH_AUTHORIZED
        rec.authorized_action = f"{action_name}: {justification}"
        logger.info("workflow.dispatch_authorized", incident_id=incident_id, action=action_name, operator=operator_id)
        return rec

    def seal_in_audit_chain(self, incident_id: str, audit_entry_hash: str) -> IncidentWorkflowRecord:
        """Close the incident file and bind it to the cryptographic audit trail."""
        if incident_id not in self.incidents:
            raise ValueError(f"Incident '{incident_id}' not found.")

        rec = self.incidents[incident_id]
        if rec.stage not in (WorkflowStage.DISPATCH_AUTHORIZED, WorkflowStage.DISMISSED_FALSE_POSITIVE):
            raise WorkflowActionError("Cannot seal incident before decision or action authorization.")

        rec.stage = WorkflowStage.SEALED_IN_AUDIT
        rec.audit_chain_hash = audit_entry_hash
        logger.info("workflow.incident_sealed", incident_id=incident_id, hash=audit_entry_hash[:16])
        return rec
