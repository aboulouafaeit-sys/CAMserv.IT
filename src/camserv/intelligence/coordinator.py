"""
camserv.intelligence.coordinator
================================

Central Coordinator for the CAMserv Intelligence Platform (Phase 27).

Orchestrates all 12 intelligence engines into a modular, failure-isolated,
hardware-adaptive subsystem.

Mandatory Guarantee:
Recording and ingestion are NEVER degraded or interrupted by AI processing.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from camserv.intelligence.anpr import LicensePlateEngine
from camserv.intelligence.classification import ObjectClassificationEngine
from camserv.intelligence.contracts import (
    BoundingBox,
    CameraIntelligenceConfig,
    CameraProfilePreset,
    DetectionPrediction,
    EngineHealthStatus,
    HardwareOperatingTier,
    IntelligencePriority,
    PlateRecognitionResult,
    TrackRecord,
    TrafficFlowMeasurement,
)
from camserv.intelligence.detection import ObjectDetectionEngine
from camserv.intelligence.events import EventDetectionEngine
from camserv.intelligence.evidence import EvidenceProvenanceEngine
from camserv.intelligence.health import IntelligenceHealthMonitor
from camserv.intelligence.registry import ModelCapabilityRegistry
from camserv.intelligence.rules import ConfigurableRulesEngine
from camserv.intelligence.scene import SceneReasoningRecord, SceneUnderstandingEngine
from camserv.intelligence.scheduler import AIResourceScheduler
from camserv.intelligence.tracking import ObjectTrackingEngine
from camserv.intelligence.traffic import TrafficAnalyticsEngine


class CAMservIntelligenceEngine:
    """
    Unified coordinator managing the 12 vision intelligence engines
    with hardware adaptation and total failure isolation.
    """

    def __init__(
        self,
        tier: HardwareOperatingTier = HardwareOperatingTier.TIER_A_CPU_LOW,
        confidence_threshold: float = 0.35,
        anpr_authorized: bool = False,
        anpr_justification: str = "",
    ) -> None:
        self._lock = threading.RLock()
        self.tier = tier

        # 1. Model Registry
        self.model_registry = ModelCapabilityRegistry()

        # 2. Resource Scheduler
        self.scheduler = AIResourceScheduler(initial_tier=tier)

        # 3. Health Monitor
        self.health_monitor = IntelligenceHealthMonitor()

        # 4. Detection & Classification
        optimal_model = self.model_registry.select_optimal_model("object_detection", tier)
        self.detector = ObjectDetectionEngine(
            confidence_threshold=confidence_threshold,
            model_record=optimal_model,
        )
        self.classifier = ObjectClassificationEngine()

        # 5. ANPR Engine (Optional, disabled by default)
        self.anpr_engine = LicensePlateEngine(
            authorized=anpr_authorized,
            authorization_justification=anpr_justification,
        )

        # 6. Event & Rules Engines
        self.event_engine = EventDetectionEngine()
        self.rules_engine = ConfigurableRulesEngine(event_engine=self.event_engine)

        # 7. Evidence Provenance Engine
        self.evidence_engine = EvidenceProvenanceEngine()

        # Per-Camera Engines (Lazy initialized)
        self._trackers: dict[str, ObjectTrackingEngine] = {}
        self._traffic_engines: dict[str, TrafficAnalyticsEngine] = {}
        self._scene_engines: dict[str, SceneUnderstandingEngine] = {}

        # Update initial health statuses
        self._update_all_health_states()

    def _update_all_health_states(self) -> None:
        """Register current health state of each engine with the health monitor."""
        self.health_monitor.record_engine_status("detection", self.detector.health_status)
        self.health_monitor.record_engine_status("classification", self.classifier.health_status)
        self.health_monitor.record_engine_status("anpr", self.anpr_engine.health_status)
        self.health_monitor.record_engine_status("events", self.event_engine.health_status)
        self.health_monitor.record_engine_status("rules", self.rules_engine.health_status)
        self.health_monitor.record_engine_status("evidence", self.evidence_engine.health_status)

    def get_tracker(self, camera_id: str) -> ObjectTrackingEngine:
        with self._lock:
            if camera_id not in self._trackers:
                self._trackers[camera_id] = ObjectTrackingEngine(camera_id=camera_id)
            return self._trackers[camera_id]

    def get_traffic_engine(self, camera_id: str) -> TrafficAnalyticsEngine:
        with self._lock:
            if camera_id not in self._traffic_engines:
                cfg = self.rules_engine.get_camera_config(camera_id)
                self._traffic_engines[camera_id] = TrafficAnalyticsEngine(
                    camera_id=camera_id,
                    calibration=cfg.calibration,
                )
            return self._traffic_engines[camera_id]

    def get_scene_engine(self, camera_id: str) -> SceneUnderstandingEngine:
        with self._lock:
            if camera_id not in self._scene_engines:
                self._scene_engines[camera_id] = SceneUnderstandingEngine(camera_id=camera_id)
            return self._scene_engines[camera_id]

    def configure_camera(
        self,
        camera_id: str,
        profile: CameraProfilePreset = CameraProfilePreset.GENERAL_SURVEILLANCE,
    ) -> CameraIntelligenceConfig:
        """Apply a deployment preset and prepare per-camera engines."""
        with self._lock:
            cfg = self.rules_engine.apply_profile(camera_id, profile)
            # Reinitialize camera-specific engines
            self._traffic_engines[camera_id] = TrafficAnalyticsEngine(
                camera_id=camera_id,
                calibration=cfg.calibration,
            )
            return cfg

    def set_hardware_tier(self, tier: HardwareOperatingTier) -> None:
        """Update hardware operating tier across scheduler and model selection."""
        with self._lock:
            self.tier = tier
            self.scheduler.set_hardware_tier(tier)
            optimal_model = self.model_registry.select_optimal_model("object_detection", tier)
            if optimal_model:
                self.detector = ObjectDetectionEngine(model_record=optimal_model)
            self._update_all_health_states()

    def analyze_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        frame_id: int,
        source_segment_id: str = "seg_unknown",
        timestamp_utc: float | None = None,
    ) -> dict[str, Any]:
        """
        Execute full-frame intelligence analysis through isolated workers.
        Guarantees that an exception or timeout will NEVER propagate to recording.
        """
        start_time = time.monotonic()
        ts = timestamp_utc or time.time()

        def _worker_task() -> dict[str, Any]:
            # 1. Detection
            raw_detections = self.detector.detect(
                frame=frame,
                camera_id=camera_id,
                frame_id=frame_id,
                timestamp_utc=ts,
            )

            # 2. Classification refinement
            refined_detections = [
                self.classifier.refine_detection(det, full_frame=frame)
                for det in raw_detections
            ]

            # 3. Tracking
            tracker = self.get_tracker(camera_id)
            tracks = tracker.update(refined_detections, frame_id=frame_id, timestamp_utc=ts)

            # 4. Traffic Flow Analysis
            traffic_engine = self.get_traffic_engine(camera_id)
            traffic_measurement = traffic_engine.process_tracks(tracks, timestamp_utc=ts)

            # 5. Scene Understanding
            scene_engine = self.get_scene_engine(camera_id)
            scene_record = scene_engine.evaluate_scene(
                tracks=tracks,
                detections=refined_detections,
                frame_id=frame_id,
                timestamp_utc=ts,
            )

            # 6. Rules Evaluation & Event Emission
            traffic_events = self.rules_engine.evaluate_traffic_rules(
                traffic_measurement=traffic_measurement,
                evidence_hash="sha256_mock",
                segment_id=source_segment_id,
                frame_id=frame_id,
            )
            scene_events = self.rules_engine.evaluate_scene_rules(
                scene_record=scene_record,
                evidence_hash="sha256_mock",
                segment_id=source_segment_id,
                frame_id=frame_id,
            )

            # 7. Evidence Association for High Severity Events
            all_events = traffic_events + scene_events
            for evt in all_events:
                self.evidence_engine.create_evidence_link(
                    event=evt,
                    raw_frame=frame,
                    crop_bbox=None,
                )

            return {
                "status": "SUCCESS",
                "camera_id": camera_id,
                "frame_id": frame_id,
                "detections": refined_detections,
                "tracks": tracks,
                "traffic": traffic_measurement,
                "scene": scene_record,
                "events": all_events,
            }

        fallback_dict = {
            "status": "SHED_OR_FAILED",
            "camera_id": camera_id,
            "frame_id": frame_id,
            "detections": [],
            "tracks": [],
            "traffic": None,
            "scene": None,
            "events": [],
            "error": "EXECUTION_FAILED",
        }

        # Execute through failure-isolated scheduler
        result, success, error_msg = self.scheduler.execute_isolated(
            camera_id=camera_id,
            task_callable=_worker_task,
            priority=IntelligencePriority.AI_ANALYTICS,
            fallback_value=fallback_dict,
        )

        if not success and isinstance(result, dict):
            result["error"] = error_msg

        latency_ms = (time.monotonic() - start_time) * 1000.0
        if success:
            self.health_monitor.record_latency(latency_ms)
        else:
            if "RESOURCE_ADMISSION_REJECTED" in error_msg:
                self.health_monitor.record_drop()
            else:
                self.health_monitor.record_error()

        return result if result is not None else {}

    def analyze_plate(
        self,
        camera_id: str,
        frame: np.ndarray,
        vehicle_bbox: BoundingBox,
        frame_id: int,
        source_segment_id: str = "seg_unknown",
    ) -> PlateRecognitionResult:
        """
        Execute isolated license plate recognition on a vehicle region.
        """
        def _anpr_task() -> PlateRecognitionResult:
            return self.anpr_engine.process_frame(
                full_frame=frame,
                vehicle_bbox=vehicle_bbox,
                camera_id=camera_id,
                frame_id=frame_id,
                source_segment_id=source_segment_id,
            )

        res, success, error_msg = self.scheduler.execute_isolated(
            camera_id=camera_id,
            task_callable=_anpr_task,
            priority=IntelligencePriority.EXPENSIVE_ANALYSIS,
        )

        if success and isinstance(res, PlateRecognitionResult):
            return res

        return self.anpr_engine._create_empty_result(camera_id, source_segment_id, vehicle_bbox)

    def get_health_summary(self) -> dict[str, Any]:
        """Return the consolidated health status across all engines."""
        self._update_all_health_states()
        summary = self.health_monitor.get_summary()
        summary["current_tier"] = self.tier.value
        summary["scheduler"] = {
            "total_submitted": self.scheduler.metrics.total_submitted,
            "total_completed": self.scheduler.metrics.total_completed,
            "total_shed": self.scheduler.metrics.total_shed,
            "total_timeouts": self.scheduler.metrics.total_timeouts,
            "total_worker_errors": self.scheduler.metrics.total_worker_errors,
            "current_state": self.scheduler.metrics.current_state,
        }
        return summary

    def shutdown(self) -> None:
        """Safely terminate all worker threads and background executors."""
        self.scheduler.shutdown()
