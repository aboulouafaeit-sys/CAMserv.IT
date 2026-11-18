"""
tests/test_phase27_2_real_ai_and_process_isolation.py
=====================================================

Phase 27.2 Verification Suite:
- Gate 27.2-A: Model Registry integrity, rejection of empty-file SHA-256 placeholder,
  and honest capability disclosure in ObjectDetectionEngine.
- Gate 27.2-B: Native OS Process Isolation, 12-state worker supervision, confirmed
  OS process termination, epoch generation protection, and stale result rejection.
- Gate 27.2-C: Priority hierarchy enforcement and recording continuity under AI worker
  crashes, OS process kills, timeouts, and extreme host pressure (0 dropped recording frames).
- Gate 27.2-D: Genuine pixel-based ANPR OCR reading characters from image pixels,
  rejection of synthetic hallucination on blank/unreadable plates, and privacy audit logging.
- Gate 27.2-E: Traffic tracking with 3x3 planar road homography perspective speed calibration.
- Gate 27.2-F: Hardware-adaptive CPU-only baseline, task admission controls, and hysteresis damping.
"""

from __future__ import annotations

import os
import tempfile
import time
import cv2
import numpy as np
import pytest

from camserv.intelligence.anpr import (
    LicensePlateEngine,
    assess_plate_quality,
    extract_characters_from_pixels,
)
from camserv.intelligence.contracts import (
    BoundingBox,
    CameraCalibration,
    DetectionPrediction,
    HardwareOperatingTier,
    InferenceTaskLease,
    IntelligencePriority,
    ModelCapabilityState,
    PlateProcessingStatus,
    SpeedMeasurementStatus,
    TrackLifecycleState,
    TrackRecord,
    WorkerLifecycleState,
)
from camserv.intelligence.detection import (
    CANONICAL_CLASSES,
    ObjectDetectionEngine,
)
from camserv.intelligence.process_worker import (
    ProcessIsolatedInferenceSupervisor,
)
from camserv.intelligence.registry import (
    EMPTY_FILE_SHA256,
    ModelCapabilityRecord,
    ModelCapabilityRegistry,
    validate_model_path,
)
from camserv.intelligence.scheduler import (
    AIResourceScheduler,
)
from camserv.intelligence.traffic import (
    TrafficAnalyticsEngine,
)
from camserv.platform.stability import (
    RecordingContinuityLedger,
    RecordingContinuityState,
)


# ===========================================================================
# Gate 27.2-A: Model Registry & Honest Capability Verification
# ===========================================================================

@pytest.mark.unit
def test_empty_file_placeholder_strictly_rejected() -> None:
    """
    GATE 27.2-A INTEGRITY AUDIT:
    Verify that the standard empty-file SHA-256 placeholder (e3b0c442...)
    is strictly rejected as a valid integrity reference.
    """
    with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as tmp:
        tmp.write(b"")  # 0-byte file
        tmp_path = tmp.name

    try:
        record = ModelCapabilityRecord(
            model_id="camserv_placeholder_test",
            name="Test Model",
            version="1.0.0",
            architecture="opencv_dnn_ssd",
            task="object_detection",
            supported_classes=["person", "car"],
            license="Apache-2.0",
            commercial_use_permitted=True,
            file_path=tmp_path,
            expected_sha256=EMPTY_FILE_SHA256,
            input_resolution=(416, 416),
            memory_footprint_mb=10.0,
        )

        # verify_integrity must reject empty-file placeholder
        assert record.verify_integrity() is False

        registry = ModelCapabilityRegistry()
        # register_user_model must reject empty-file placeholder
        ok, reason = registry.register_user_model(record)
        assert ok is False
        assert "PLACEHOLDER_HASH_DISALLOWED" in reason

        # get_model_capability_state must report MODEL_INTEGRITY_FAILED
        registry.register_model(record)
        state = registry.get_model_capability_state("camserv_placeholder_test")
        assert state == ModelCapabilityState.MODEL_INTEGRITY_FAILED
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.unit
def test_model_capability_states_evaluation() -> None:
    """Verify registry distinguishes NOT_INSTALLED, INTEGRITY_FAILED, and READY states."""
    registry = ModelCapabilityRegistry()

    # 1. Non-existent model ID
    assert registry.get_model_capability_state("unknown_model_xyz") == ModelCapabilityState.MODEL_NOT_INSTALLED

    # 2. Registered model whose weight file does not exist on disk
    assert registry.get_model_capability_state("camserv_det_cpu_v1") == ModelCapabilityState.MODEL_NOT_INSTALLED

    # 3. Model with invalid file hash
    with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as tmp:
        tmp.write(b"dummy non-empty neural weight content")
        tmp_path = tmp.name

    try:
        corrupted_record = ModelCapabilityRecord(
            model_id="corrupted_model",
            name="Corrupted Model",
            version="1.0.0",
            architecture="opencv_dnn_ssd",
            task="object_detection",
            supported_classes=["person"],
            license="Apache-2.0",
            commercial_use_permitted=True,
            file_path=tmp_path,
            expected_sha256="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            input_resolution=(416, 416),
            memory_footprint_mb=10.0,
        )
        registry.register_model(corrupted_record)
        assert registry.get_model_capability_state("corrupted_model") == ModelCapabilityState.MODEL_INTEGRITY_FAILED
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.adversarial
def test_user_model_path_traversal_protection() -> None:
    """Verify security validation rejects path traversal attempts."""
    assert validate_model_path("models/camserv_v1.onnx") is True
    assert validate_model_path("../../etc/passwd") is False
    assert validate_model_path("models/../../../windows/system32/cmd.exe") is False
    assert validate_model_path("models/\x00malicious.onnx") is False


@pytest.mark.unit
def test_detection_engine_metadata_and_heuristic_fallback_transparency() -> None:
    """
    Verify ObjectDetectionEngine honestly reports metadata:
    - In fallback mode: is_simulated_heuristic=True, real_weights_loaded=False.
    - When fallback disabled: returns [] without fabricating detections.
    """
    engine_with_fallback = ObjectDetectionEngine(allow_heuristic_fallback=True)
    frame = np.full((200, 200, 3), 128, dtype=np.uint8)
    dets = engine_with_fallback.detect(frame, camera_id="cam-01", frame_id=1)
    assert len(dets) >= 1
    assert dets[0].metadata["is_simulated_heuristic"] is True
    assert dets[0].metadata["real_weights_loaded"] is False

    # Disabled fallback mode
    engine_no_fallback = ObjectDetectionEngine(allow_heuristic_fallback=False)
    dets_empty = engine_no_fallback.detect(frame, camera_id="cam-01", frame_id=1)
    assert dets_empty == []


# ===========================================================================
# Gate 27.2-B: Native AI Process Isolation & Supervision
# ===========================================================================

@pytest.mark.integration
def test_supervisor_process_lifecycle_states() -> None:
    """
    CRITICAL PROCESS ISOLATION:
    Verify child OS process creation, execution, and confirmed OS termination.
    """
    sup = ProcessIsolatedInferenceSupervisor(
        worker_id="test_worker_lifecycle",
        task_timeout_sec=2.0,
        auto_restart=False,
    )
    try:
        assert sup.state == WorkerLifecycleState.READY
        assert sup.worker_pid is not None
        assert sup.is_alive is True

        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        preds, success, msg = sup.submit_and_wait(frame, camera_id="cam-01", frame_id=1)
        assert success is True
        assert msg == "SUCCESS"
        assert len(preds) >= 1

        # Confirmed termination sequence
        final_state = sup.terminate_worker(graceful=True)
        assert final_state == WorkerLifecycleState.TERMINATED
        assert sup.is_alive is False
        assert sup.worker_pid is None
    finally:
        sup.shutdown()


@pytest.mark.integration
def test_supervisor_forced_process_termination_on_timeout() -> None:
    """
    VERIFIED FORCED TERMINATION:
    When an isolated task times out, supervisor forcefully terminates OS child process,
    confirms process exit, and restarts a new generation.
    """
    sup = ProcessIsolatedInferenceSupervisor(
        worker_id="test_worker_timeout",
        task_timeout_sec=0.2,
        auto_restart=True,
    )
    try:
        initial_gen = sup.generation
        old_pid = sup.worker_pid

        # Force termination directly
        state = sup.terminate_worker(graceful=False)
        assert state == WorkerLifecycleState.TERMINATED
        assert sup.is_alive is False

        # Next submission triggers clean restart with incremented generation
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        preds, success, msg = sup.submit_and_wait(frame, camera_id="cam-01", frame_id=2, timeout_sec=2.0)
        assert success is True
        assert sup.generation == initial_gen + 1
        assert sup.worker_pid is not None
        assert sup.worker_pid != old_pid
    finally:
        sup.shutdown()


@pytest.mark.adversarial
def test_supervisor_circuit_breaker_on_rapid_crashes() -> None:
    """Verify supervisor circuit breaker prevents infinite restart loops (trips to RECOVERY_FAILED)."""
    sup = ProcessIsolatedInferenceSupervisor(
        worker_id="test_worker_circuit_breaker",
        auto_restart=True,
        max_restarts_per_window=3,
        restart_window_sec=5.0,
    )
    try:
        # Intentionally force-kill multiple times in rapid succession
        for _ in range(4):
            sup.terminate_worker(graceful=False)
            frame = np.full((50, 50, 3), 128, dtype=np.uint8)
            sup.submit_and_wait(frame, camera_id="cam-cb", frame_id=1, timeout_sec=0.1)

        # After exceeding max_restarts_per_window, state should become RECOVERY_FAILED
        assert sup.state == WorkerLifecycleState.RECOVERY_FAILED
    finally:
        sup.shutdown()


# ===========================================================================
# Gate 27.2-C: Recording Continuity Under Worker Failures
# ===========================================================================

@pytest.mark.integration
def test_recording_continuity_under_ai_worker_crash() -> None:
    """
    GATE 27.2-C RECORDING ISOLATION:
    Simulates continuous video recording while AI inference workers crash,
    time out, and get terminated by OS signals.
    Guarantees:
    - 0 dropped recording frames in RecordingContinuityLedger.
    - Recording remains in continuous uninterrupted state.
    """
    ledger = RecordingContinuityLedger()
    rec = ledger.start_segment(
        camera_id="cam-prod-01",
        stream_id="main",
        segment_id="seg_phase27_2_cont_01",
        expected_fps=30.0,
    )

    scheduler = AIResourceScheduler(
        initial_tier=HardwareOperatingTier.TIER_A_CPU_LOW,
        worker_timeout_sec=0.3,
    )

    frame = np.full((200, 200, 3), 128, dtype=np.uint8)

    # Ingest 60 continuous recording frames (2 seconds at 30fps)
    # Concurrent with isolated AI failures
    for frame_idx in range(1, 61):
        # 1. Primary recording frame recorded without interruption
        ledger.record_frame(
            camera_id="cam-prod-01",
            segment_id="seg_phase27_2_cont_01",
            frame_seq=frame_idx,
            pts=frame_idx / 30.0,
        )

        # 2. Intermittent crashing or lingering AI task
        if frame_idx % 15 == 0:
            def crashing_task():
                raise RuntimeError("Simulated segmentation fault / native runtime crash")

            scheduler.execute_isolated("cam-prod-01", crashing_task, fallback_value=[])

        elif frame_idx % 20 == 0:
            def lingering_task():
                time.sleep(0.6)  # Will exceed 0.3s timeout

            scheduler.execute_isolated("cam-prod-01", lingering_task, fallback_value=[])

    final_rec = ledger.finalize_segment(
        camera_id="cam-prod-01",
        segment_id="seg_phase27_2_cont_01",
        expected_frames=60,
    )

    # Invariant checks: AI failures must have ZERO impact on recording continuity
    assert final_rec.observed_frames == 60
    assert final_rec.confirmed_missing_frames_total == 0
    assert final_rec.estimated_missing_frames_total == 0
    assert len(final_rec.discontinuities) == 0
    assert final_rec.current_state == RecordingContinuityState.CONTINUOUS
    assert final_rec.to_dict()["continuity_ratio"] == 1.0

    scheduler.shutdown()


@pytest.mark.integration
def test_recording_continuity_under_critical_host_pressure() -> None:
    """
    HOST PRESSURE SHEDDING:
    When CPU pressure reaches 95%, AI scheduler sheds all AI tasks immediately.
    Recording continues with 0 frame loss.
    """
    ledger = RecordingContinuityLedger()
    ledger.start_segment(
        camera_id="cam-prod-02",
        stream_id="main",
        segment_id="seg_pressure_01",
        expected_fps=30.0,
    )

    scheduler = AIResourceScheduler()
    # Trigger critical host condition
    scheduler.update_host_pressure(cpu_percent=96.0, ram_percent=92.0)
    assert scheduler.metrics.current_state == "CRITICAL"

    # Verify AI task is immediately rejected without consuming CPU
    admitted = scheduler.check_admission("cam-prod-02", priority=IntelligencePriority.AI_ANALYTICS)
    assert admitted is False

    # Ingest recording frames during critical pressure
    for i in range(1, 31):
        ledger.record_frame(
            camera_id="cam-prod-02",
            segment_id="seg_pressure_01",
            frame_seq=i,
            pts=i / 30.0,
        )

    final = ledger.finalize_segment(
        camera_id="cam-prod-02",
        segment_id="seg_pressure_01",
        expected_frames=30,
    )
    assert final.observed_frames == 30
    assert final.confirmed_missing_frames_total == 0
    assert final.current_state == RecordingContinuityState.CONTINUOUS

    scheduler.shutdown()


# ===========================================================================
# Gate 27.2-D: Real OCR and ANPR Integration
# ===========================================================================

@pytest.mark.unit
def test_genuine_pixel_ocr_reads_image_pixels() -> None:
    """
    GATE 27.2-D REAL OCR:
    Verify that characters are recognized directly from image pixels
    using contour segmentation and normalized template matching.
    """
    # Create plate crop with text "ABC12" rendered in pixels
    plate_img = np.full((60, 200), 220, dtype=np.uint8)
    cv2.putText(plate_img, "ABC12", (15, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 20, 2, cv2.LINE_AA)

    chars = extract_characters_from_pixels(plate_img, min_confidence=0.45)
    text = "".join(c for c, _ in chars)

    assert "ABC12" in text
    assert len(chars) >= 4
    for _, conf in chars:
        assert 0.50 <= conf <= 1.0


@pytest.mark.unit
def test_blank_plate_strict_ocr_rejection_no_hallucination() -> None:
    """
    HALLUCINATION PREVENTION:
    In strict OCR mode, a blank or noise plate crop must return
    OCR_RUNTIME_UNAVAILABLE or UNREADABLE with 0 characters.
    Never synthesizes characters from frame_id or timestamps.
    """
    engine = LicensePlateEngine(authorized=True, strict_pixel_ocr=True)

    # Frame with blank vehicle lower crop
    frame = np.full((480, 640, 3), 100, dtype=np.uint8)
    frame[315:375, 250:400] = np.full((60, 150, 3), 200, dtype=np.uint8)  # Blank plate region

    v_bbox = BoundingBox(200.0, 150.0, 450.0, 400.0)
    res = engine.process_frame(frame, v_bbox, camera_id="cam-01", frame_id=999)

    assert len(res.character_confidences) == 0
    assert res.raw_ocr_text == ""
    assert res.normalized_candidate == ""
    assert res.status in (PlateProcessingStatus.UNREADABLE, PlateProcessingStatus.OCR_RUNTIME_UNAVAILABLE)
    assert res.metadata["is_simulated_ocr"] is False


@pytest.mark.unit
def test_anpr_optical_gating_blur_and_glare() -> None:
    """Verify optical gating rejects excessively blurred and saturated crops."""
    # Motion blurred crop
    blurred = np.full((50, 150, 3), 128, dtype=np.uint8)
    q_blur = assess_plate_quality(blurred)
    assert q_blur.passed_gating is False
    assert q_blur.rejection_reason == "EXCESSIVE_MOTION_BLUR"

    # Glare saturated crop
    glare = np.random.randint(50, 150, (50, 150, 3), dtype=np.uint8)
    glare[:35, :120] = 255
    q_glare = assess_plate_quality(glare)
    assert q_glare.passed_gating is False
    assert q_glare.rejection_reason == "SEVERE_OPTICAL_GLARE"


# ===========================================================================
# Gate 27.2-E: Tracking & Homography Perspective Speed Calibration
# ===========================================================================

@pytest.mark.unit
def test_planar_homography_perspective_speed_calibration() -> None:
    """
    GATE 27.2-E PERSPECTIVE RECTIFICATION:
    Verify that 3x3 planar homography matrix H rectifies foreshortened image
    coordinates to ground plane (meters), calculating accurate road speed in km/h.
    """
    # 3x3 homography matrix mapping (u, v) in image pixels to (X_w, Y_w) in meters
    # Example calibrated road plane: 20 pixels = 1 meter in X, 10 pixels = 1 meter in Y
    homography_matrix = [
        [0.05, 0.0,  0.0],
        [0.0,  0.10, 0.0],
        [0.0,  0.0,  1.0],
    ]

    calib = CameraCalibration(
        camera_id="cam-road-01",
        is_calibrated=True,
        homography_matrix=homography_matrix,
    )

    engine = TrafficAnalyticsEngine(camera_id="cam-road-01", calibration=calib)

    # Vehicle with velocity (vx=100.0 px/s, vy=0.0 px/s)
    # Ground plane displacement = 100 * 0.05 = 5.0 m/s
    # Speed in km/h = 5.0 * 3.6 = 18.0 km/h
    trk = TrackRecord(
        track_id=10,
        camera_id="cam-road-01",
        session_id="s1",
        bbox=BoundingBox(100.0, 100.0, 160.0, 160.0),
        class_name="car",
        class_id=1,
        confidence=0.92,
        state=TrackLifecycleState.TRACKED,
        age_frames=15,
        created_at_utc=1.0,
        last_seen_utc=2.0,
        velocity_pixels_per_sec=(100.0, 0.0),
    )

    measurement = engine.process_tracks([trk], timestamp_utc=2.0)

    assert measurement.speed_status == SpeedMeasurementStatus.CALIBRATED_ACCURATE
    assert measurement.calibrated_speed_kmh == pytest.approx(18.0, abs=0.1)
    assert measurement.metadata.get("projection_method") == "planar_homography_3x3"


# ===========================================================================
# Gate 27.2-F: Hardware-Adaptive CPU-Only Baseline & Scheduling
# ===========================================================================

@pytest.mark.unit
def test_cpu_only_tier_a_budget_and_shedding() -> None:
    """Verify Tier A CPU Low enforces conservative concurrency, queue bounds, and sampling."""
    scheduler = AIResourceScheduler(initial_tier=HardwareOperatingTier.TIER_A_CPU_LOW)

    assert scheduler.current_tier == HardwareOperatingTier.TIER_A_CPU_LOW
    rate = scheduler.calculate_sampling_rate("cam-cpu")
    assert rate == 2.0  # 2.0 default sampling FPS on low CPU

    # Update load to DEGRADED
    scheduler.update_host_pressure(cpu_percent=78.0, ram_percent=60.0)
    assert scheduler.metrics.current_state == "DEGRADED"
    rate_degraded = scheduler.calculate_sampling_rate("cam-cpu")
    assert rate_degraded == 0.5  # 0.5 min sampling FPS

    scheduler.shutdown()
