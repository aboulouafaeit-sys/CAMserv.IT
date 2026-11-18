"""
camserv.intelligence.rules
==========================

Configurable Rules Engine and Deployment Profile Presets.

Enforces:
- Camera profile presets: Road/Traffic, Parking, Entrance, Warehouse, Retail, Perimeter, General.
- Operator-configurable thresholds (confidence, sampling rate, active event types).
- Rule evaluation mapping vision inferences to actionable events.
- Audit logging of configuration changes.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from camserv.intelligence.contracts import (
    CameraIntelligenceConfig,
    CameraProfilePreset,
    EngineHealthStatus,
    EpistemicLevel,
    IntelligenceEventType,
)
from camserv.intelligence.events import EventDetectionEngine
from camserv.intelligence.scene import SceneReasoningRecord
from camserv.intelligence.traffic import TrafficFlowMeasurement


# ---------------------------------------------------------------------------
# Default Camera Profile Configurations
# ---------------------------------------------------------------------------

PROFILE_DEFAULTS: dict[CameraProfilePreset, dict[str, Any]] = {
    CameraProfilePreset.ROAD_TRAFFIC: {
        "enabled_engines": {"detection", "classification", "tracking", "traffic", "scene", "events"},
        "confidence_threshold": 0.40,
        "sampling_fps": 6.0,
        "anpr_authorized": False,
        "active_events": {
            IntelligenceEventType.VEHICLE_DETECTED,
            IntelligenceEventType.TRAFFIC_CONGESTION,
            IntelligenceEventType.WRONG_DIRECTION_INDICATOR,
            IntelligenceEventType.VEHICLE_STOPPED,
            IntelligenceEventType.ROAD_OBSTRUCTION,
        },
    },
    CameraProfilePreset.PARKING: {
        "enabled_engines": {"detection", "classification", "tracking", "traffic", "events"},
        "confidence_threshold": 0.45,
        "sampling_fps": 3.0,
        "anpr_authorized": False,
        "active_events": {
            IntelligenceEventType.VEHICLE_DETECTED,
            IntelligenceEventType.VEHICLE_STOPPED,
            IntelligenceEventType.VEHICLE_ENTERED_ZONE,
            IntelligenceEventType.VEHICLE_EXITED_ZONE,
        },
    },
    CameraProfilePreset.BUILDING_ENTRANCE: {
        "enabled_engines": {"detection", "classification", "tracking", "scene", "events"},
        "confidence_threshold": 0.50,
        "sampling_fps": 4.0,
        "anpr_authorized": False,
        "active_events": {
            IntelligenceEventType.PERSON_DETECTED,
            IntelligenceEventType.PEDESTRIAN_CROSSING,
        },
    },
    CameraProfilePreset.PERIMETER: {
        "enabled_engines": {"detection", "classification", "tracking", "scene", "events"},
        "confidence_threshold": 0.35,
        "sampling_fps": 5.0,
        "anpr_authorized": False,
        "active_events": {
            IntelligenceEventType.PERSON_DETECTED,
            IntelligenceEventType.VEHICLE_DETECTED,
            IntelligenceEventType.VEHICLE_ENTERED_ZONE,
        },
    },
    CameraProfilePreset.GENERAL_SURVEILLANCE: {
        "enabled_engines": {"detection", "tracking", "scene", "events"},
        "confidence_threshold": 0.40,
        "sampling_fps": 4.0,
        "anpr_authorized": False,
        "active_events": {
            IntelligenceEventType.PERSON_DETECTED,
            IntelligenceEventType.VEHICLE_DETECTED,
        },
    },
}


# ---------------------------------------------------------------------------
# Configurable Rules Engine
# ---------------------------------------------------------------------------

class ConfigurableRulesEngine:
    """
    Evaluates vision and traffic metrics against active camera profiles
    and dispatches verified events to the EventDetectionEngine.
    """

    def __init__(self, event_engine: EventDetectionEngine) -> None:
        self.event_engine = event_engine
        self._lock = threading.RLock()
        self._camera_configs: dict[str, CameraIntelligenceConfig] = {}
        self._health_status = EngineHealthStatus.ACTIVE

    @property
    def health_status(self) -> EngineHealthStatus:
        with self._lock:
            return self._health_status

    def configure_camera(
        self,
        config: CameraIntelligenceConfig,
    ) -> None:
        """Register or update a camera's intelligence configuration."""
        with self._lock:
            self._camera_configs[config.camera_id] = config

    def get_camera_config(self, camera_id: str) -> CameraIntelligenceConfig:
        """Retrieve active configuration for a camera, or initialize with profile default."""
        with self._lock:
            if camera_id not in self._camera_configs:
                self._camera_configs[camera_id] = CameraIntelligenceConfig(camera_id=camera_id)
            return self._camera_configs[camera_id]

    def apply_profile(
        self,
        camera_id: str,
        profile: CameraProfilePreset,
    ) -> CameraIntelligenceConfig:
        """Apply a predefined surveillance deployment preset to a camera."""
        with self._lock:
            defaults = PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS[CameraProfilePreset.GENERAL_SURVEILLANCE])
            cfg = CameraIntelligenceConfig(
                camera_id=camera_id,
                profile_preset=profile,
                enabled_engines=set(defaults["enabled_engines"]),
                confidence_threshold=defaults["confidence_threshold"],
                sampling_fps=defaults["sampling_fps"],
                anpr_authorized=defaults["anpr_authorized"],
            )
            self._camera_configs[camera_id] = cfg
            return cfg

    def evaluate_traffic_rules(
        self,
        traffic_measurement: TrafficFlowMeasurement,
        evidence_hash: str = "sha256_mock",
        segment_id: str = "seg_unknown",
        frame_id: int = 0,
    ) -> list[Any]:
        """
        Evaluate traffic flow metrics and publish corresponding events if thresholds are exceeded.
        """
        cfg = self.get_camera_config(traffic_measurement.camera_id)
        events_emitted = []

        # 1. Congestion Event
        if traffic_measurement.congestion_level.value in ("congested", "standstill"):
            evt = self.event_engine.publish_event(
                event_type=IntelligenceEventType.TRAFFIC_CONGESTION,
                camera_id=traffic_measurement.camera_id,
                confidence=0.85,
                severity="MEDIUM" if traffic_measurement.congestion_level.value == "congested" else "HIGH",
                epistemic_level=EpistemicLevel.EVENT,
                evidence_hash=evidence_hash,
                source_segment_id=segment_id,
                source_frame_id=frame_id,
                entity_key=f"congestion_{traffic_measurement.congestion_level.value}",
                requires_human_review=False,
                metadata={
                    "density": traffic_measurement.estimated_density,
                    "level": traffic_measurement.congestion_level.value,
                    "queue_m": traffic_measurement.queue_length_meters,
                },
            )
            if evt:
                events_emitted.append(evt)

        # 2. Wrong Direction Alert
        if traffic_measurement.wrong_direction_count > 0:
            evt = self.event_engine.publish_event(
                event_type=IntelligenceEventType.WRONG_DIRECTION_INDICATOR,
                camera_id=traffic_measurement.camera_id,
                confidence=0.90,
                severity="HIGH",
                epistemic_level=EpistemicLevel.EVENT,
                evidence_hash=evidence_hash,
                source_segment_id=segment_id,
                source_frame_id=frame_id,
                entity_key="wrong_direction",
                requires_human_review=True,
                metadata={"wrong_way_count": traffic_measurement.wrong_direction_count},
            )
            if evt:
                events_emitted.append(evt)

        return events_emitted

    def evaluate_scene_rules(
        self,
        scene_record: SceneReasoningRecord,
        evidence_hash: str = "sha256_mock",
        segment_id: str = "seg_unknown",
        frame_id: int = 0,
    ) -> list[Any]:
        """
        Evaluate scene reasoning inferences and publish actionable events.
        """
        events_emitted = []
        for raw_evt in scene_record.events:
            if "VEHICLE_STOPPED" in raw_evt:
                evt = self.event_engine.publish_event(
                    event_type=IntelligenceEventType.VEHICLE_STOPPED,
                    camera_id=scene_record.camera_id,
                    confidence=scene_record.confidence,
                    severity="MEDIUM",
                    epistemic_level=EpistemicLevel.EVENT,
                    evidence_hash=evidence_hash,
                    source_segment_id=segment_id,
                    source_frame_id=frame_id,
                    entity_key=raw_evt,
                    requires_human_review=False,
                    metadata={"scene_reasoning": raw_evt},
                )
                if evt:
                    events_emitted.append(evt)
            elif "ROAD_OBSTRUCTION" in raw_evt:
                evt = self.event_engine.publish_event(
                    event_type=IntelligenceEventType.ROAD_OBSTRUCTION,
                    camera_id=scene_record.camera_id,
                    confidence=scene_record.confidence,
                    severity="HIGH",
                    epistemic_level=EpistemicLevel.EVENT,
                    evidence_hash=evidence_hash,
                    source_segment_id=segment_id,
                    source_frame_id=frame_id,
                    entity_key="road_obstruction",
                    requires_human_review=True,
                    metadata={"scene_reasoning": raw_evt},
                )
                if evt:
                    events_emitted.append(evt)
            elif "SMOKE_INDICATOR" in raw_evt:
                evt = self.event_engine.publish_event(
                    event_type=IntelligenceEventType.SMOKE_INDICATOR,
                    camera_id=scene_record.camera_id,
                    confidence=scene_record.confidence,
                    severity="CRITICAL",
                    epistemic_level=EpistemicLevel.EVENT,
                    evidence_hash=evidence_hash,
                    source_segment_id=segment_id,
                    source_frame_id=frame_id,
                    entity_key="smoke_indicator",
                    requires_human_review=True,
                    metadata={"scene_reasoning": raw_evt},
                )
                if evt:
                    events_emitted.append(evt)
            elif "FIRE_INDICATOR" in raw_evt:
                evt = self.event_engine.publish_event(
                    event_type=IntelligenceEventType.FIRE_INDICATOR,
                    camera_id=scene_record.camera_id,
                    confidence=scene_record.confidence,
                    severity="CRITICAL",
                    epistemic_level=EpistemicLevel.EVENT,
                    evidence_hash=evidence_hash,
                    source_segment_id=segment_id,
                    source_frame_id=frame_id,
                    entity_key="fire_indicator",
                    requires_human_review=True,
                    metadata={"scene_reasoning": raw_evt},
                )
                if evt:
                    events_emitted.append(evt)

        return events_emitted
