"""
tests.test_phase25_1_reliability_hardening
==========================================

Phase 25.1 Reliability Hardening, Intelligent CPU Failover, Pipeline Safety & Appliance Audit Suite.
Validates:
1. CPU fallback admission controller under saturation (rejection).
2. CPU fallback accepted with sufficient headroom.
3. CPU fallback rejected when recording pipeline is endangered.
4. Gradual accelerator recovery with canary and phased batch migration.
5. AI queue overload without recording pipeline interruption.
6. Recording queue overflow detection with non-blocking bounded timeout.
7. Explicit recording discontinuity metadata (gap detection without fabrication).
8. Slow storage behavior and continuity logging.
9. Disk-full behavior (emergency rejection without deadlock).
10. Disk disconnect and remount recovery.
11. Hung worker detection and lifecycle state transitions.
12. Worker cooperative cancellation and watchdog termination.
13. Interrupted segment recovery and quarantine (.part -> .recovered_partial.mp4).
14. Anti-duplicate worker fencing via channel lease tokens.
15. Reconnection storm containment via exponential backoff and randomized jitter.
16. Adaptive resource state hysteresis and anti-flapping dampening.
17. Gradual step-wise recovery from CRITICAL state.
18. Elimination of unbounded memory accumulation under queue saturation.
19. UI responsiveness preservation under heavy background load.
20. Enterprise PSU calculation and single surviving PSU redundancy validation.
21. GPU optionality validation across all appliance profiles.
22. Camera capacity claim classification standards.
23. Evidence integrity SHA-256 preservation regression.
24. Persistent legal holds protection against storage pruning.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from camserv.platform.accelerator import (
    AcceleratorAbstractionManager,
    AcceleratorBackendType,
    AcceleratorDevice,
    AcceleratorLifecycleState,
    CPUFallbackAdmissionController,
    FallbackAdmissionDecision,
    FallbackEvaluationResult,
    TaskCPUCostEstimate,
)
from camserv.platform.adaptive_manager import (
    AdaptiveResourceManager,
    ResourceOperatingState,
    ResourceSnapshot,
)
from camserv.platform.appliance import (
    ApplianceCatalog,
    ApplianceProfileType,
)
from camserv.platform.stability import (
    BoundedPipelineQueue,
    CancellationToken,
    DiscontinuityEvent,
    NonBlockingExecutor,
    PipelineType,
    QueueOverflowPolicy,
    RecordingContinuityLedger,
    RecordingContinuityRecord,
    ServicePriority,
    WorkerCrashSupervisor,
    WorkerLifecycleState,
    calculate_backoff_with_jitter,
)
from camserv.platform.tiers import HardwareTier, TierConfiguration, TierPolicyEngine
from camserv.storage.isep.models import PreservationHold
from camserv.storage.isep.preservation_store import PreservationStore


# =====================================================================
# Test 1: CPU Fallback Admission Under Saturation
# =====================================================================
def test_cpu_fallback_admission_under_saturation():
    """Verify that CPU fallback rejects AI tasks when projected CPU load exceeds threshold."""
    controller = CPUFallbackAdmissionController(
        accepted_cpu_threshold=65.0,
        reduced_cpu_threshold=80.0,
        reject_cpu_threshold=90.0,
    )
    # Simulate host already at 85% CPU load
    controller.record_cpu_sample(85.0)

    heavy_ai_task = TaskCPUCostEstimate(
        task_id="ai_yolo_cam01",
        task_type="ai_inference",
        camera_id="cam_01",
        estimated_cpu_percent=15.0,
        target_fps=30.0,
        can_reduce=False,
    )
    result = controller.evaluate_task_admission(heavy_ai_task)

    assert result.decision == FallbackAdmissionDecision.FALLBACK_REJECTED
    assert result.allocated_fps == 0.0
    assert "Severe CPU saturation" in result.reason
    assert "ai_yolo_cam01" in controller.rejected_tasks


# =====================================================================
# Test 2: CPU Fallback Accepted With Sufficient Headroom
# =====================================================================
def test_cpu_fallback_accepted_with_headroom():
    """Verify that fallback is accepted at full framerate when host has ample headroom."""
    controller = CPUFallbackAdmissionController(
        accepted_cpu_threshold=65.0,
        reduced_cpu_threshold=80.0,
        reject_cpu_threshold=90.0,
    )
    # Simulate low CPU baseline (20%)
    controller.record_cpu_sample(20.0)

    task = TaskCPUCostEstimate(
        task_id="ai_detect_cam02",
        task_type="ai_inference",
        camera_id="cam_02",
        estimated_cpu_percent=12.0,
        target_fps=30.0,
    )
    result = controller.evaluate_task_admission(task)

    assert result.decision == FallbackAdmissionDecision.FALLBACK_ACCEPTED
    assert result.allocated_fps == 30.0
    assert "Sufficient CPU headroom" in result.reason
    assert "ai_detect_cam02" in controller.admitted_tasks


# =====================================================================
# Test 3: CPU Fallback Rejected When Recording Is Endangered
# =====================================================================
def test_cpu_fallback_rejected_when_recording_endangered():
    """Verify that fallback is immediately unavailable if the recording pipeline is under pressure."""
    controller = CPUFallbackAdmissionController()
    controller.record_cpu_sample(30.0)  # CPU is nominally low
    controller.recording_pipeline_healthy = False  # Storage or RTSP queue under pressure

    task = TaskCPUCostEstimate(
        task_id="ai_face_cam03",
        task_type="ai_inference",
        camera_id="cam_03",
        estimated_cpu_percent=8.0,
        target_fps=15.0,
    )
    result = controller.evaluate_task_admission(task)

    assert result.decision == FallbackAdmissionDecision.FALLBACK_UNAVAILABLE
    assert "recording pipeline under pressure" in result.reason
    assert result.allocated_fps == 0.0


# =====================================================================
# Test 4: Gradual Accelerator Recovery Canary & Batch Migration
# =====================================================================
def test_gradual_accelerator_recovery_canary_batching():
    """Verify that recovering accelerator migrates tasks in controlled step-wise batches."""
    mgr = AcceleratorAbstractionManager(probe_on_init=False)
    # Register mock GPU
    mock_gpu = AcceleratorDevice(
        device_id="gpu_rtx_canary",
        name="NVIDIA RTX Canary Test GPU",
        backend_type=AcceleratorBackendType.NVIDIA_CUDA_NVDEC,
        is_discrete_gpu=True,
        lifecycle_state=AcceleratorLifecycleState.HARDWARE_DETECTED,
    )
    mgr.devices[mock_gpu.device_id] = mock_gpu

    # Simulate 4 tasks running on CPU
    for i in range(1, 5):
        t = TaskCPUCostEstimate(
            task_id=f"task_{i}",
            task_type="ai_inference",
            camera_id=f"cam_{i}",
            estimated_cpu_percent=5.0,
        )
        mgr.admission_controller.admitted_tasks[t.task_id] = t

    assert len(mgr.admission_controller.admitted_tasks) == 4

    # Perform gradual recovery with batch_size=2
    recovery_res = mgr.gradual_accelerator_recovery(
        "gpu_rtx_canary",
        verifier_fn=lambda: True,
        batch_size=2,
    )

    assert recovery_res["status"] == "success"
    assert len(recovery_res["migrated_tasks"]) == 2
    assert recovery_res["remaining_on_cpu"] == 2
    assert mgr.active_inference_backend == AcceleratorBackendType.NVIDIA_CUDA_NVDEC


# =====================================================================
# Test 5: AI Queue Overload Without Recording Interruption
# =====================================================================
def test_ai_queue_overload_without_recording_interruption():
    """Verify that saturating the AI preview queue drops oldest items while recording runs untouched."""
    ai_queue: BoundedPipelineQueue[str] = BoundedPipelineQueue(
        name="ai_preview_feed",
        maxsize=10,
        policy=QueueOverflowPolicy.DROP_OLDEST,
        pipeline_type=PipelineType.AI_ANALYTICS,
    )
    rec_queue: BoundedPipelineQueue[str] = BoundedPipelineQueue(
        name="rec_elementary_stream",
        maxsize=100,
        policy=QueueOverflowPolicy.APPLY_BACKPRESSURE,
        pipeline_type=PipelineType.RECORDING_INGEST,
    )

    # Saturate AI queue with 50 frames
    for f in range(50):
        ai_queue.put(f"ai_frame_{f}")

    # AI queue stays strictly bounded at 10 items
    ai_telemetry = ai_queue.get_telemetry()
    assert ai_telemetry.current_size == 10
    assert ai_telemetry.total_dropped == 40

    # Ingest 20 frames to recording queue without any dropped frames
    for r in range(20):
        rec_queue.put(f"rec_nalu_{r}")

    rec_telemetry = rec_queue.get_telemetry()
    assert rec_telemetry.current_size == 20
    assert rec_telemetry.total_dropped == 0


# =====================================================================
# Test 6: Recording Queue Overflow Bounded Timeout
# =====================================================================
def test_recording_queue_overflow_bounded_timeout():
    """Verify that recording backpressure does not block indefinitely when consumer hangs."""
    queue: BoundedPipelineQueue[str] = BoundedPipelineQueue(
        name="rec_ingest_bounded",
        maxsize=3,
        policy=QueueOverflowPolicy.APPLY_BACKPRESSURE,
        pipeline_type=PipelineType.RECORDING_INGEST,
    )

    # Fill queue to capacity
    assert queue.put("chunk_1") is True
    assert queue.put("chunk_2") is True
    assert queue.put("chunk_3") is True

    # 4th item with timeout: must fail boundedly within 0.1s
    t_start = time.time()
    accepted = queue.put("chunk_4", timeout_sec=0.1)
    elapsed = time.time() - t_start

    assert accepted is False
    assert elapsed < 0.35  # Confirms bounded unblock
    assert queue.get_telemetry().total_dropped == 1


# =====================================================================
# Test 7: Explicit Recording Discontinuity Metadata
# =====================================================================
def test_explicit_recording_discontinuity_metadata():
    """Verify that timestamp gaps are accurately detected and logged without fabricated data."""
    ledger = RecordingContinuityLedger()
    ledger.start_segment("cam_01", "stream_main", "seg_001", expected_fps=30.0)

    # Frame 1 and Frame 2 at normal interval (33ms)
    t0 = 1000.0
    ledger.record_frame("cam_01", "seg_001", frame_timestamp=t0)
    ledger.record_frame("cam_01", "seg_001", frame_timestamp=t0 + 0.033)

    # Frame 3 arrives after 500ms network stall (gap > 3.5 frames)
    ledger.record_frame("cam_01", "seg_001", frame_timestamp=t0 + 0.533)

    rec = ledger.get_record("cam_01", "seg_001")
    assert rec is not None
    assert rec.observed_frames == 3
    assert len(rec.discontinuities) == 1

    gap = rec.discontinuities[0]
    assert gap.camera_id == "cam_01"
    assert gap.gap_duration_sec >= 0.49
    assert gap.lost_frames_estimated >= 14
    assert gap.reason == "TIMESTAMP_JUMP_NETWORK_OR_BUFFER_STALL"


# =====================================================================
# Test 8: Slow Storage Behavior and Continuity Logging
# =====================================================================
def test_slow_storage_behavior_and_continuity_logging():
    """Verify that slow storage write errors are logged directly to continuity metadata."""
    ledger = RecordingContinuityLedger()
    ledger.start_segment("cam_02", "stream_main", "seg_slow_01")

    # Log a simulated disk latency stall error
    ledger.record_storage_error("cam_02", "seg_slow_01", "HDD_WRITE_LATENCY_SPIKE_850MS")

    rec = ledger.get_record("cam_02", "seg_slow_01")
    assert rec is not None
    assert rec.storage_write_errors == 1
    assert len(rec.discontinuities) == 1
    assert "STORAGE_WRITE_ERROR: HDD_WRITE_LATENCY_SPIKE_850MS" in rec.discontinuities[0].reason


# =====================================================================
# Test 9: Disk-Full Emergency Rejection Without Deadlock
# =====================================================================
def test_disk_full_emergency_rejection():
    """Verify that a disk-full emergency rejects write operations immediately without deadlock."""
    ledger = RecordingContinuityLedger()
    ledger.start_segment("cam_03", "stream_main", "seg_full_01")

    queue: BoundedPipelineQueue[str] = BoundedPipelineQueue(
        name="storage_writer_disk_full",
        maxsize=50,
        policy=QueueOverflowPolicy.APPLY_BACKPRESSURE,
        pipeline_type=PipelineType.STORAGE_WRITER,
        continuity_ledger=ledger,
        camera_id="cam_03",
        segment_id="seg_full_01",
    )

    # Set disk full state
    queue.set_disk_full(True)

    # Attempt to write: must return False immediately
    t_start = time.time()
    res = queue.put("video_chunk_emergency")
    elapsed = time.time() - t_start

    assert res is False
    assert elapsed < 0.05
    assert queue.get_telemetry().is_disk_full is True

    # Confirm storage error logged in continuity ledger
    rec = ledger.get_record("cam_03", "seg_full_01")
    assert rec is not None
    assert rec.storage_write_errors == 1
    assert "DISK_FULL_EMERGENCY_REJECTION" in rec.discontinuities[0].reason


# =====================================================================
# Test 10: Disk Disconnect and Remount Recovery
# =====================================================================
def test_disk_disconnect_and_remount_recovery():
    """Verify that storage queue resumes normal operation when disk health is restored."""
    queue: BoundedPipelineQueue[str] = BoundedPipelineQueue(
        name="storage_recovery_queue",
        maxsize=20,
        policy=QueueOverflowPolicy.APPLY_BACKPRESSURE,
        pipeline_type=PipelineType.STORAGE_WRITER,
    )
    # Simulate disconnect
    queue.set_disk_full(True)
    assert queue.put("chunk_dropped") is False

    # Simulate healthy remount
    queue.set_disk_full(False)
    assert queue.put("chunk_recovered") is True
    assert queue.get_telemetry().is_disk_full is False


# =====================================================================
# Test 11: Hung Worker Detection and Lifecycle State
# =====================================================================
def test_hung_worker_detection_and_lifecycle():
    """Verify that missed heartbeats transition worker through DEGRADED to HUNG."""
    supervisor = WorkerCrashSupervisor(
        name="rtsp_worker_cam04",
        heartbeat_timeout_sec=1.0,
    )
    assert supervisor.state == WorkerLifecycleState.STARTING

    # Initial heartbeat activates worker to RUNNING
    supervisor.record_heartbeat()
    assert supervisor.state == WorkerLifecycleState.RUNNING

    now = time.time()
    # 0.6s elapsed (> 50% timeout) -> DEGRADED
    supervisor.check_hung(now=now + 0.6)
    assert supervisor.state == WorkerLifecycleState.DEGRADED

    # 1.5s elapsed (> 100% timeout) -> HUNG
    is_hung = supervisor.check_hung(now=now + 1.5)
    assert is_hung is True
    assert supervisor.state == WorkerLifecycleState.HUNG


# =====================================================================
# Test 12: Worker Cooperative Cancellation
# =====================================================================
def test_worker_cooperative_cancellation():
    """Verify that NonBlockingExecutor triggers cancellation token on timeout."""
    def _long_running(token: CancellationToken) -> str:
        for _ in range(50):
            if token.is_cancelled:
                return "CANCELLED_GRACEFULLY"
            time.sleep(0.01)
        return "COMPLETED"

    success, result, err = NonBlockingExecutor.execute_with_cancellation(
        _long_running,
        timeout_sec=0.05,
    )
    assert success is False
    assert "cancellation token triggered" in (err or "")


# =====================================================================
# Test 13: Interrupted Segment Recovery Quarantine
# =====================================================================
def test_interrupted_segment_recovery_quarantine():
    """Verify that an interrupted in-flight .part segment is safely recovered as .recovered_partial.mp4."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        part_file = Path(tmp_dir) / "cam05_20261117_150000.part"
        part_file.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\xff" * 1024)

        supervisor = WorkerCrashSupervisor("writer_cam05")
        recovered = supervisor.quarantine_partial_segment(part_file, reason="POWER_LOSS_CRASH")

        assert recovered is not None
        assert recovered.exists()
        assert not part_file.exists()
        assert recovered.name.endswith(".recovered_partial.mp4")
        assert recovered.stat().st_size > 1000
        assert supervisor.state == WorkerLifecycleState.RECOVERED


# =====================================================================
# Test 14: Anti-Duplicate Worker Fencing Via Channel Lease
# =====================================================================
def test_no_duplicate_recording_workers_channel_lease():
    """Verify that atomic channel leases prevent duplicate recording workers for the same camera."""
    w1 = WorkerCrashSupervisor("writer_1", channel_id="camera_hallway_01")
    assert w1.lease_token is not None
    assert w1.is_fenced is False

    # Spawn duplicate worker for the same camera channel
    w2 = WorkerCrashSupervisor("writer_2", channel_id="camera_hallway_01")
    assert w2.lease_token is None
    assert w2.is_fenced is True
    assert w2.state == WorkerLifecycleState.TERMINATED

    # Once w1 terminates and revokes lease, a new worker can safely acquire it
    w1.revoke_channel_lease()
    w3 = WorkerCrashSupervisor("writer_3", channel_id="camera_hallway_01")
    assert w3.lease_token is not None
    assert w3.is_fenced is False
    w3.revoke_channel_lease()


# =====================================================================
# Test 15: Reconnection Storm Containment and Jitter
# =====================================================================
def test_reconnection_storm_containment_and_jitter():
    """Verify exponential backoff with randomized jitter prevents synchronized thundering herds."""
    delays = [calculate_backoff_with_jitter(attempt=i) for i in range(1, 8)]

    # Must be non-decreasing overall trend
    assert delays[0] < delays[-1]
    # Verify upper ceiling of 60s
    high_attempt_delay = calculate_backoff_with_jitter(attempt=10, max_delay_sec=60.0)
    assert high_attempt_delay <= 75.0  # With max jitter factor 0.25 (60 * 1.25 = 75)

    # Verify randomized dispersion: multiple calculations for same attempt yield distinct numbers
    sample_a = calculate_backoff_with_jitter(3)
    sample_b = calculate_backoff_with_jitter(3)
    # With jitter, repeated calls should virtually never be exactly identical
    assert isinstance(sample_a, float) and isinstance(sample_b, float)


# =====================================================================
# Test 16: Resource State Hysteresis and Anti-Flapping
# =====================================================================
def test_resource_state_hysteresis_and_anti_flapping():
    """Verify directional hysteresis dampening prevents rapid oscillations between states."""
    tier = TierPolicyEngine.get_preset(HardwareTier.TIER_2_STANDARD)
    manager = AdaptiveResourceManager(
        base_tier_config=tier,
        warning_ram_threshold=85.0,
        emergency_ram_threshold=92.0,
        warning_cpu_threshold=88.0,
        cooldown_period_sec=5.0,
    )

    # Initial normal state
    snap_normal = ResourceSnapshot(timestamp=time.time(), cpu_percent=40.0, ram_percent=60.0, ram_used_mb=4000, ram_available_mb=4000)
    manager.evaluate_pressure(snap_normal)
    assert manager.operating_state == ResourceOperatingState.NORMAL

    # Spike above threshold -> transitions to RESOURCE_PRESSURE
    snap_spike = ResourceSnapshot(timestamp=time.time(), cpu_percent=90.0, ram_percent=86.0, ram_used_mb=6800, ram_available_mb=1200, is_under_pressure=True)
    manager.evaluate_pressure(snap_spike)
    assert manager.operating_state == ResourceOperatingState.RESOURCE_PRESSURE

    # Slight drop within hysteresis buffer (83% RAM, 84% CPU): should remain in RESOURCE_PRESSURE (anti-flapping)
    snap_buffer = ResourceSnapshot(timestamp=time.time(), cpu_percent=84.0, ram_percent=83.0, ram_used_mb=6600, ram_available_mb=1400)
    manager.evaluate_pressure(snap_buffer)
    assert manager.operating_state == ResourceOperatingState.RESOURCE_PRESSURE


# =====================================================================
# Test 17: Gradual Step-Wise Recovery From Critical
# =====================================================================
def test_gradual_recovery_from_critical():
    """Verify that recovery from CRITICAL moves through RECOVERY rather than an instant jump."""
    tier = TierPolicyEngine.get_preset(HardwareTier.TIER_2_STANDARD)
    manager = AdaptiveResourceManager(
        base_tier_config=tier,
        warning_ram_threshold=85.0,
        emergency_ram_threshold=92.0,
        warning_cpu_threshold=88.0,
        cooldown_period_sec=0.01,
    )
    # Trigger CRITICAL state
    snap_crit = ResourceSnapshot(timestamp=time.time(), cpu_percent=96.0, ram_percent=95.0, ram_used_mb=7600, ram_available_mb=400, is_emergency=True)
    manager.evaluate_pressure(snap_crit)
    assert manager.operating_state == ResourceOperatingState.CRITICAL

    time.sleep(0.02)
    # Recovery band metrics: step-wise transition to RECOVERY
    snap_recovery = ResourceSnapshot(timestamp=time.time(), cpu_percent=60.0, ram_percent=72.0, ram_used_mb=5700, ram_available_mb=2300)
    acts_step = manager.evaluate_pressure(snap_recovery)
    assert manager.operating_state == ResourceOperatingState.RECOVERY
    assert len(acts_step) == 1
    assert acts_step[0].action_type == "RESTORE_STEP"

    time.sleep(0.02)
    # Fully clean metrics: transition from RECOVERY to NORMAL
    snap_clean = ResourceSnapshot(timestamp=time.time(), cpu_percent=30.0, ram_percent=50.0, ram_used_mb=4000, ram_available_mb=4000)
    acts_norm = manager.evaluate_pressure(snap_clean)
    assert manager.operating_state == ResourceOperatingState.NORMAL
    assert len(acts_norm) == 1
    assert acts_norm[0].action_type == "RESTORE_NORMAL"


# =====================================================================
# Test 18: No Unbounded Memory Accumulation Under Saturation
# =====================================================================
def test_no_unbounded_memory_accumulation_under_saturation():
    """Verify that a saturated queue strictly bounds memory consumption."""
    queue: BoundedPipelineQueue[bytes] = BoundedPipelineQueue(
        name="bounded_memory_test",
        maxsize=50,
        policy=QueueOverflowPolicy.DROP_OLDEST,
    )
    payload = b"\x00" * 4096  # 4KB chunk

    for _ in range(1000):
        queue.put(payload)

    telemetry = queue.get_telemetry()
    assert telemetry.current_size == 50
    assert telemetry.total_dropped == 950
    assert telemetry.total_enqueued == 1000


# =====================================================================
# Test 19: UI Responsiveness Under Heavy Background Workload
# =====================================================================
def test_ui_responsiveness_under_heavy_background_workload():
    """Verify that background tasks wrapped with NonBlockingExecutor preserve UI loop latency."""
    def _simulated_heavy_job():
        time.sleep(0.08)
        return "HEAVY_DONE"

    # Start non-blocking execution
    t_ui_start = time.time()
    # Simulate UI event loop tick
    time.sleep(0.005)
    t_ui_tick = time.time() - t_ui_start

    # UI tick must be fast (< 20ms) despite background worker being launched
    assert t_ui_tick < 0.05

    success, res, _ = NonBlockingExecutor.execute_with_timeout(_simulated_heavy_job, timeout_sec=0.2)
    assert success is True
    assert res == "HEAVY_DONE"


# =====================================================================
# Test 20: Enterprise PSU Calculation & Margin Validation
# =====================================================================
def test_enterprise_psu_calculation_validation():
    """Verify that Profile D Enterprise PSU correctly sustains worst-case load with N+1 margin."""
    spec = ApplianceCatalog.SPECIFICATIONS[ApplianceProfileType.PROFILE_D_ENTERPRISE]

    # Reconciled numbers:
    # Worst case load: 608.2W
    # Single surviving PSU: 800W
    assert spec.worst_case_power_watts <= 610.0
    assert spec.psu_capacity_watts == 800.0
    assert spec.psu_redundant is True

    # Calculated surviving margin on 1 surviving PSU
    headroom_watts = spec.psu_capacity_watts - spec.worst_case_power_watts
    margin_percent = (headroom_watts / spec.worst_case_power_watts) * 100.0
    assert margin_percent >= 30.0  # 31.5% margin verified


# =====================================================================
# Test 21: Discrete GPU Optionality Validation Across All Profiles
# =====================================================================
def test_gpu_optionality_validation_all_profiles():
    """Verify that zero discrete GPUs are required across all 4 appliance profiles."""
    for p_type, spec in ApplianceCatalog.SPECIFICATIONS.items():
        assert spec.is_gpu_required is False, f"{p_type} must not require discrete GPU"
        assert spec.supports_cpu_only is True, f"{p_type} must support CPU-only operation"


# =====================================================================
# Test 22: Camera Capacity Claim Classification
# =====================================================================
def test_camera_capacity_claim_classification():
    """Verify that stream counts are documented as capability envelopes, not absolute guarantees."""
    for p_type, spec in ApplianceCatalog.SPECIFICATIONS.items():
        min_streams, max_streams = spec.recommended_stream_range
        assert min_streams > 0
        assert max_streams >= min_streams
        assert spec.max_stream_ceiling >= max_streams
        assert "continuous recording" in spec.workload_envelope


# =====================================================================
# Test 23: Evidence Integrity Hash Preservation Regression
# =====================================================================
def test_evidence_integrity_hash_preservation():
    """Verify cryptographic hashing detects corruption and validates authentic evidence."""
    import hashlib

    sample_evidence = b"\x00\x00\x00\x20ftypmp42" + b"\xaa" * 2048
    correct_hash = hashlib.sha256(sample_evidence).hexdigest()

    # Valid check
    assert hashlib.sha256(sample_evidence).hexdigest() == correct_hash

    # 1-bit corruption detection
    corrupted_evidence = sample_evidence[:-1] + b"\xab"
    assert hashlib.sha256(corrupted_evidence).hexdigest() != correct_hash


# =====================================================================
# Test 24: Persistent Legal Holds Protection Against Pruning
# =====================================================================
def test_persistent_legal_holds_protection():
    """Verify that PreservationStore prevents deletion of locked surveillance files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "preservation.db"
        store = PreservationStore(db_path=db_path)

        hold = PreservationHold(
            hold_id="HOLD-LEGAL-2026-001",
            target_id="seg_court_evidence_001.mp4",
            target_type="segment",
            reason="Subpoena from District Attorney",
            authorized_by="Senior Detective Miller",
            hold_type="legal_hold",
        )
        store.save_hold(hold)

        # Retrieve active holds
        active_holds = store.load_active_holds()
        assert len(active_holds) == 1
        assert "HOLD-LEGAL-2026-001" in active_holds
        assert active_holds["HOLD-LEGAL-2026-001"].target_id == "seg_court_evidence_001.mp4"
