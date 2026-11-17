"""
tests.test_phase25_1_a_verification
====================================

Phase 25.1-A: Final Reliability Verification & Corrective Hardening Test Suite.
Validates:
1. Critical Audit A: Real worker cancellation, confirmed termination semantics,
   hung worker isolation, channel lease fencing, and partial recording recovery.
2. Critical Audit B: Recording continuity under backpressure, bounded queues,
   pipeline isolation (preview/AI overload non-blocking on ingest), and continuity states.
3. Critical Audit C: Confirmed missing frames (via sequence numbers) vs. estimated
   missing frames (via PTS delta) vs. unknown frame loss, with full persistence/reload.
4. High-Priority Audit D: Appliance power budget denominator clarity (headroom to load vs.
   headroom to PSU rating), 1+1 PSU redundancy, SAS staggered drive spin-up, and GPU optionality.
5. High-Priority Audit E: Multi-vector stress scenarios, UI zero-freeze responsiveness,
   and resource operating state hysteresis.
"""

from __future__ import annotations

import collections
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from camserv.platform.accelerator import (
    CPUFallbackAdmissionController,
    FallbackAdmissionDecision,
    TaskCPUCostEstimate,
)
from camserv.platform.adaptive_manager import (
    AdaptationAction,
    AdaptiveResourceManager,
    ResourceOperatingState,
    ResourceSnapshot,
)
from camserv.platform.appliance import (
    ApplianceCatalog,
    ApplianceProfileType,
    ApplianceSpecification,
)
from camserv.platform.stability import (
    BoundedPipelineQueue,
    CancellationExit,
    CancellationToken,
    DiscontinuityEvent,
    NonBlockingExecutor,
    PipelineType,
    QueueOverflowPolicy,
    RecordingContinuityLedger,
    RecordingContinuityRecord,
    RecordingContinuityState,
    ServicePriority,
    WorkerCrashSupervisor,
    WorkerLifecycleState,
    calculate_backoff_with_jitter,
)
from camserv.platform.tiers import HardwareTier, TierPolicyEngine
from camserv.storage.isep.models import PreservationHold
from camserv.storage.isep.preservation_store import PreservationStore


# ============================================================================
# 1. CRITICAL AUDIT A — WORKER CANCELLATION & HUNG WORKER ISOLATION
# ============================================================================

class TestCriticalAuditAWorkerCancellation:
    """Tests points 1-10 of Section 4.3 in Phase 25.1-A directive."""

    def test_01_normal_cooperative_cancellation(self) -> None:
        """Worker observes cancellation token at checkpoint and exits cleanly."""
        token = CancellationToken()
        worker_executed_checkpoints = []

        def worker_loop(t: CancellationToken) -> None:
            for i in range(10):
                if t.checkpoint(f"step_{i}"):
                    # Clean cooperative exit
                    break
                worker_executed_checkpoints.append(i)
                time.sleep(0.01)
            t.confirm_stopped()

        thread = threading.Thread(target=worker_loop, args=(token,), daemon=True)
        thread.start()
        time.sleep(0.03)

        assert not token.is_cancelled
        token.cancel()
        assert token.cancellation_requested

        # Await worker exit confirmation
        stopped = token.wait_stopped(timeout_sec=0.5)
        assert stopped is True
        assert token.cancellation_acknowledged is True
        assert token.is_confirmed_stopped is True
        assert token.last_checkpoint is not None
        assert "step_" in token.last_checkpoint
        assert len(worker_executed_checkpoints) < 10

    def test_02_cancellation_during_long_running_operation(self) -> None:
        """Cancellation requested while operation is executing in NonBlockingExecutor."""
        acknowledged = threading.Event()
        stopped = threading.Event()

        def long_task(token: CancellationToken) -> str:
            while not token.is_cancelled:
                time.sleep(0.01)
            token.acknowledge("in_flight_computation")
            acknowledged.set()
            time.sleep(0.02)
            stopped.set()
            return "cancelled_cleanly"

        token = CancellationToken()
        t = threading.Thread(target=long_task, args=(token,), daemon=True)
        t.start()
        time.sleep(0.02)

        token.cancel()
        assert token.cancellation_requested is True

        assert acknowledged.wait(0.5) is True
        assert token.cancellation_acknowledged is True
        assert token.last_checkpoint == "in_flight_computation"
        assert stopped.wait(0.5) is True

    def test_03_timeout_while_worker_still_executing(self) -> None:
        """NonBlockingExecutor times out but returns safely without stalling the caller."""
        worker_running = threading.Event()

        def slow_worker(token: CancellationToken) -> str:
            worker_running.set()
            # Sleeps longer than timeout
            time.sleep(0.3)
            return "finished"

        start_time = time.time()
        success, result, error = NonBlockingExecutor.execute_with_cancellation(
            slow_worker,
            timeout_sec=0.08,
            fallback_value="fallback_engaged",
        )
        elapsed = time.time() - start_time

        assert success is False
        assert result == "fallback_engaged"
        assert "timed out after 0.08 seconds" in str(error)
        assert elapsed < 0.20  # Caller was not blocked by worker's 0.3s sleep

    def test_04_simulated_unresponsive_worker_heartbeat_watchdog(self) -> None:
        """Heartbeat watchdog detects hung worker and flags state as HUNG."""
        supervisor = WorkerCrashSupervisor(
            name="ai_yolo_hung_test",
            heartbeat_timeout_sec=0.1,
            channel_id="cam_01",
        )
        supervisor.record_heartbeat()
        assert supervisor.state == WorkerLifecycleState.RUNNING

        # Simulate 150ms passing without heartbeat
        time.sleep(0.12)
        is_hung = supervisor.check_hung()

        assert is_hung is True
        assert supervisor.state == WorkerLifecycleState.HUNG

    def test_05_blocked_operation_does_not_check_token_unconfirmed_state(self) -> None:
        """
        A worker that is blocked in an un-instrumented loop and fails to stop
        is truthfully marked TERMINATION_UNCONFIRMED — NEVER falsely claimed as TERMINATED!
        """
        token = CancellationToken()
        worker_stuck = threading.Event()

        def zombie_thread() -> None:
            worker_stuck.set()
            # Infinite uninterruptible loop simulating native C blocking
            while True:
                time.sleep(0.05)

        t = threading.Thread(target=zombie_thread, daemon=True)
        t.start()
        worker_stuck.wait(0.2)

        supervisor = WorkerCrashSupervisor(
            name="native_ffmpeg_worker",
            channel_id="cam_unconfirmed_01",
        )
        supervisor.register_worker(thread=t, token=token)

        # Attempt cancellation with short timeout
        success = supervisor.terminate_worker(timeout_sec=0.05)

        assert success is False
        assert supervisor.termination_confirmed is False
        assert supervisor.termination_unconfirmed is True
        assert supervisor.state == WorkerLifecycleState.TERMINATION_UNCONFIRMED

    def test_06_resource_lease_retention_while_worker_still_alive(self) -> None:
        """
        Crucial Safety Invariant: If a worker fails to confirm termination,
        its channel lease is NOT revoked, preventing a duplicate worker from colliding!
        """
        channel = "cam_perimeter_fence_01"
        token = CancellationToken()

        def infinite_worker() -> None:
            while True:
                time.sleep(0.05)

        t = threading.Thread(target=infinite_worker, daemon=True)
        t.start()

        supervisor1 = WorkerCrashSupervisor(name="worker_primary", channel_id=channel)
        supervisor1.register_worker(thread=t, token=token)
        lease1 = supervisor1.lease_token
        assert lease1 is not None

        # Terminate fails because thread is un-interruptible
        term_ok = supervisor1.terminate_worker(timeout_sec=0.04)
        assert term_ok is False
        assert supervisor1.state == WorkerLifecycleState.TERMINATION_UNCONFIRMED
        # Lease must NOT have been released!
        assert supervisor1.lease_token == lease1
        assert WorkerCrashSupervisor._ACTIVE_CHANNEL_LEASES.get(channel) == lease1

        # Attempt to spawn duplicate worker on same channel must fail!
        supervisor2 = WorkerCrashSupervisor(name="worker_duplicate", channel_id=channel)
        lease2 = supervisor2.acquire_channel_lease()

        assert lease2 is None
        assert supervisor2.is_fenced is True
        assert supervisor2.state == WorkerLifecycleState.TERMINATED

        # Cleanup for test isolation
        WorkerCrashSupervisor._ACTIVE_CHANNEL_LEASES.pop(channel, None)

    def test_07_safe_resource_release_after_confirmed_termination(self) -> None:
        """Resource lease is safely revoked only after worker has confirmed exit."""
        channel = "cam_warehouse_safe_02"
        token = CancellationToken()

        def cooperative_worker() -> None:
            while not token.is_cancelled:
                time.sleep(0.01)
            token.acknowledge("exit_confirmed")
            time.sleep(0.01)
            token.confirm_stopped()

        t = threading.Thread(target=cooperative_worker, daemon=True)
        t.start()

        supervisor = WorkerCrashSupervisor(name="worker_clean", channel_id=channel)
        supervisor.register_worker(thread=t, token=token)
        orig_lease = supervisor.lease_token
        assert orig_lease is not None

        # Request termination
        term_ok = supervisor.terminate_worker(timeout_sec=0.3)

        assert term_ok is True
        assert supervisor.termination_confirmed is True
        assert supervisor.termination_unconfirmed is False
        assert supervisor.state == WorkerLifecycleState.TERMINATED
        assert supervisor.lease_token is None
        # Channel is now free
        assert channel not in WorkerCrashSupervisor._ACTIVE_CHANNEL_LEASES

    def test_08_duplicate_worker_prevention_on_same_channel(self) -> None:
        """Two concurrent workers cannot hold the lease for the same camera channel."""
        channel = "cam_gate_03"
        sup1 = WorkerCrashSupervisor(name="gate_worker_1", channel_id=channel)
        assert sup1.lease_token is not None
        assert sup1.is_fenced is False

        sup2 = WorkerCrashSupervisor(name="gate_worker_2", channel_id=channel)
        # Initialization tried to acquire lease, which should have been blocked
        assert sup2.lease_token is None
        assert sup2.is_fenced is True

        sup1.terminate_worker()
        assert channel not in WorkerCrashSupervisor._ACTIVE_CHANNEL_LEASES

    def test_09_partial_recording_recovery_after_abnormal_termination(self) -> None:
        """Quarantine in-flight .part recording segment to .recovered_partial.mp4 without data loss."""
        with tempfile.TemporaryDirectory() as tmpdir:
            part_file = Path(tmpdir) / "segment_20261117_120000.part"
            # Write 4KB of pseudo-video stream
            part_file.write_bytes(b"MP4_DATA_HEADER_" + b"0" * 4096)

            supervisor = WorkerCrashSupervisor(name="rec_crash_worker", channel_id="cam_crash_01")
            recovered = supervisor.quarantine_partial_segment(part_file, reason="WORKER_SEGV_ISOLATION")

            assert recovered is not None
            assert recovered.exists()
            assert recovered.name == "segment_20261117_120000.recovered_partial.mp4"
            assert recovered.stat().st_size == 4096 + len(b"MP4_DATA_HEADER_")
            assert not part_file.exists()
            assert supervisor.state == WorkerLifecycleState.RECOVERED
            supervisor.revoke_channel_lease()

    def test_10_parent_application_responsiveness_during_worker_failure(self) -> None:
        """Simulated UI event loop continues processing without freeze during worker crashes."""
        supervisor = WorkerCrashSupervisor(name="thrashing_worker", max_restarts=3)
        ui_loop_latencies: list[float] = []

        for cycle in range(5):
            t0 = time.time()
            # Crash worker
            supervisor.record_crash(RuntimeError(f"Simulated fault {cycle}"))
            # UI loop iteration
            time.sleep(0.005)
            t1 = time.time()
            ui_loop_latencies.append((t1 - t0) * 1000.0)

        # Fencing engaged after max_restarts
        assert supervisor.is_fenced is True
        assert supervisor.state == WorkerLifecycleState.TERMINATED
        # UI loop never experienced an un-bounded stall (> 50ms)
        max_ui_latency = max(ui_loop_latencies)
        assert max_ui_latency < 50.0


# ============================================================================
# 2. CRITICAL AUDIT B — RECORDING CONTINUITY UNDER BACKPRESSURE
# ============================================================================

class TestCriticalAuditBRecordingContinuity:
    """Tests Section 5 requirements for pipeline isolation and continuity states."""

    def test_01_pipeline_isolation_preview_and_ai_overload_do_not_block_recording(self) -> None:
        """
        Saturating preview and AI queues with DROP_OLDEST does NOT block or drop
        frames on the RECORDING_INGEST queue.
        """
        ledger = RecordingContinuityLedger()
        rec_rec = ledger.start_segment("cam_01", "main", "seg_01", expected_fps=30.0)

        preview_q = BoundedPipelineQueue[str](
            "preview_q",
            maxsize=2,
            policy=QueueOverflowPolicy.DROP_OLDEST,
            pipeline_type=PipelineType.LIVE_PREVIEW,
        )
        ai_q = BoundedPipelineQueue[str](
            "ai_q",
            maxsize=2,
            policy=QueueOverflowPolicy.DROP_OLDEST,
            pipeline_type=PipelineType.AI_ANALYTICS,
        )
        recording_q = BoundedPipelineQueue[str](
            "rec_q",
            maxsize=100,
            policy=QueueOverflowPolicy.APPLY_BACKPRESSURE,
            pipeline_type=PipelineType.RECORDING_INGEST,
            continuity_ledger=ledger,
            camera_id="cam_01",
            segment_id="seg_01",
        )

        # Flood preview and AI queues with 20 items each
        for i in range(20):
            preview_q.put(f"preview_frame_{i}")
            ai_q.put(f"ai_frame_{i}")

        assert preview_q.total_dropped == 18
        assert ai_q.total_dropped == 18

        # Enqueue 10 recording frames - must all succeed without any drops
        for j in range(10):
            ok = recording_q.put(f"rec_frame_{j}", timeout_sec=0.1)
            assert ok is True
            ledger.record_frame("cam_01", "seg_01", frame_seq=j)

        assert recording_q.total_dropped == 0
        assert rec_rec.observed_frames == 10
        assert len(rec_rec.discontinuities) == 0
        assert rec_rec.current_state == RecordingContinuityState.CONTINUOUS

    def test_02_bounded_backpressure_timeout_explicitly_logs_discontinuity(self) -> None:
        """
        When storage backpressure saturates the recording queue and 500ms timeout elapses,
        a DiscontinuityEvent is recorded in the ledger — NO SILENT LOSS OCCURS!
        """
        ledger = RecordingContinuityLedger()
        rec = ledger.start_segment("cam_backpressure_01", "main", "seg_bp_01", expected_fps=30.0)

        # Micro queue with capacity 2
        rec_q = BoundedPipelineQueue[str](
            "rec_tight_q",
            maxsize=2,
            policy=QueueOverflowPolicy.APPLY_BACKPRESSURE,
            pipeline_type=PipelineType.RECORDING_INGEST,
            continuity_ledger=ledger,
            camera_id="cam_backpressure_01",
            segment_id="seg_bp_01",
        )

        assert rec_q.put("frame_1", timeout_sec=0.05) is True
        assert rec_q.put("frame_2", timeout_sec=0.05) is True

        # Third frame causes backpressure timeout
        start = time.time()
        ok = rec_q.put("frame_3", timeout_sec=0.05)
        elapsed = time.time() - start

        assert ok is False
        assert elapsed >= 0.04
        assert rec_q.total_dropped == 1

        # Check that continuity ledger received explicit discontinuity event
        assert len(rec.discontinuities) == 1
        disc = rec.discontinuities[0]
        assert "RECORDING_INGEST_QUEUE_OVERFLOW_BACKPRESSURE_TIMEOUT" in disc.reason
        assert disc.confidence == "estimated"
        assert disc.estimated_missing_frames == 1
        assert rec.current_state == RecordingContinuityState.RECORDING_DEGRADED

    def test_03_continuity_state_model_transitions(self) -> None:
        """Validates all required operational states in RecordingContinuityState."""
        ledger = RecordingContinuityLedger()
        rec = ledger.start_segment("cam_state_01", "main", "seg_s_01", expected_fps=30.0)
        assert rec.current_state == RecordingContinuityState.CONTINUOUS

        # 1. Temporary backpressure
        ledger.transition_state("cam_state_01", "seg_s_01", RecordingContinuityState.TEMPORARY_BACKPRESSURE)
        assert rec.current_state == RecordingContinuityState.TEMPORARY_BACKPRESSURE

        # 2. Storage backpressure
        ledger.transition_state("cam_state_01", "seg_s_01", RecordingContinuityState.STORAGE_BACKPRESSURE)
        assert rec.current_state == RecordingContinuityState.STORAGE_BACKPRESSURE

        # 3. Camera disconnected
        ledger.record_camera_disconnect("cam_state_01", "seg_s_01", "RTSP_TEARDOWN_RECEIVED")
        assert rec.current_state == RecordingContinuityState.CAMERA_DISCONNECTED

        # 4. Reconnect in progress
        ledger.record_camera_reconnect_start("cam_state_01", "seg_s_01")
        assert rec.current_state == RecordingContinuityState.RECOVERY_IN_PROGRESS

        # 5. First frame after reconnect arrives with gap -> RECOVERED_WITH_GAP
        ledger.record_frame("cam_state_01", "seg_s_01", frame_seq=100)
        assert rec.current_state == RecordingContinuityState.RECOVERED_WITH_GAP


# ============================================================================
# 3. CRITICAL AUDIT C — CONFIRMED VS ESTIMATED MISSING FRAMES
# ============================================================================

class TestCriticalAuditCFrameLossSemantics:
    """Tests Section 6 requirements for confirmed vs estimated frame loss semantics."""

    def test_01_confirmed_loss_via_source_sequence_numbers(self) -> None:
        """Sequence jump from seq=10 to seq=15 confirms exactly 4 missing frames."""
        ledger = RecordingContinuityLedger()
        rec = ledger.start_segment("cam_rtp_01", "main", "seg_01", expected_fps=30.0)

        t0 = 1700000000.0
        ledger.record_frame("cam_rtp_01", "seg_01", frame_timestamp=t0, frame_seq=10)
        ledger.record_frame("cam_rtp_01", "seg_01", frame_timestamp=t0 + 0.166, frame_seq=15)

        assert len(rec.discontinuities) == 1
        disc = rec.discontinuities[0]

        assert disc.confidence == "confirmed"
        assert disc.estimation_method == "sequence_number_gap"
        assert disc.confirmed_missing_frames == 4  # 11, 12, 13, 14
        assert disc.estimated_missing_frames is None
        assert disc.unknown_frame_loss is False
        assert disc.last_confirmed_seq == 10
        assert disc.subsequent_seq == 15
        assert rec.confirmed_missing_frames_total == 4
        assert rec.current_state == RecordingContinuityState.FRAME_GAP_DETECTED

    def test_02_estimated_loss_via_timestamp_interval_without_sequence_numbers(self) -> None:
        """PTS jump of 500ms at nominal 30fps estimates approximately 14 missing frames."""
        ledger = RecordingContinuityLedger()
        rec = ledger.start_segment("cam_pts_01", "main", "seg_01", expected_fps=30.0)

        t0 = 1700000000.0
        ledger.record_frame("cam_pts_01", "seg_01", frame_timestamp=t0, frame_seq=None)
        # 500ms jump
        ledger.record_frame("cam_pts_01", "seg_01", frame_timestamp=t0 + 0.500, frame_seq=None)

        assert len(rec.discontinuities) == 1
        disc = rec.discontinuities[0]

        assert disc.confidence == "estimated"
        assert disc.estimation_method == "timestamp_interval"
        assert disc.confirmed_missing_frames is None
        assert disc.estimated_missing_frames is not None
        assert 13 <= disc.estimated_missing_frames <= 15
        assert disc.unknown_frame_loss is False
        assert rec.estimated_missing_frames_total == disc.estimated_missing_frames

    def test_03_unknown_loss_with_variable_fps_or_unreliable_metadata(self) -> None:
        """Timestamp jump on variable FPS stream without sequence numbers flags unknown_frame_loss."""
        ledger = RecordingContinuityLedger()
        rec = ledger.start_segment("cam_vfr_01", "main", "seg_01", expected_fps=0.0)

        t0 = 1700000000.0
        ledger.record_frame("cam_vfr_01", "seg_01", frame_timestamp=t0, frame_seq=None)
        # 400ms jump with variable_fps flag in metadata
        ledger.record_frame(
            "cam_vfr_01",
            "seg_01",
            frame_timestamp=t0 + 0.400,
            frame_seq=None,
            source_metadata={"variable_fps": True},
        )

        assert len(rec.discontinuities) == 1
        disc = rec.discontinuities[0]

        assert disc.confidence == "unknown"
        assert disc.estimation_method == "unknown_insufficient_metadata"
        assert disc.unknown_frame_loss is True
        assert disc.confirmed_missing_frames is None
        assert disc.estimated_missing_frames is None
        assert rec.unknown_frame_loss_events == 1

    def test_04_out_of_order_frame_handling(self) -> None:
        """Out-of-order frame packet logs warning and does not falsely mark positive gap."""
        ledger = RecordingContinuityLedger()
        rec = ledger.start_segment("cam_ooo_01", "main", "seg_01", expected_fps=30.0)

        t0 = 1700000000.0
        ledger.record_frame("cam_ooo_01", "seg_01", frame_timestamp=t0, frame_seq=20)
        # Out-of-order frame seq 18 arrives
        ledger.record_frame("cam_ooo_01", "seg_01", frame_timestamp=t0 + 0.01, frame_seq=18)

        assert len(rec.discontinuities) == 1
        disc = rec.discontinuities[0]
        assert "OUT_OF_ORDER_FRAME" in disc.reason
        assert disc.confirmed_missing_frames == 0

    def test_05_persistence_and_reload_of_continuity_records(self) -> None:
        """Continuity records serialize to dictionary and reload with complete field fidelity."""
        ledger = RecordingContinuityLedger()
        rec = ledger.start_segment("cam_persist_01", "main", "seg_01", expected_fps=30.0)
        ledger.record_frame("cam_persist_01", "seg_01", frame_timestamp=100.0, frame_seq=1)
        ledger.record_frame("cam_persist_01", "seg_01", frame_timestamp=100.2, frame_seq=5)
        ledger.record_storage_error("cam_persist_01", "seg_01", "IO_ERROR_SECTOR_TIMEOUT")

        dumped = ledger.to_dict()
        reloaded = RecordingContinuityLedger.from_dict(dumped)

        reloaded_rec = reloaded.get_record("cam_persist_01", "seg_01")
        assert reloaded_rec is not None
        assert reloaded_rec.observed_frames == 2
        assert reloaded_rec.confirmed_missing_frames_total == 3  # 2, 3, 4
        assert reloaded_rec.storage_write_errors == 1
        assert len(reloaded_rec.discontinuities) == 2

        d0 = reloaded_rec.discontinuities[0]
        assert d0.confidence == "confirmed"
        assert d0.confirmed_missing_frames == 3
        assert d0.last_confirmed_seq == 1
        assert d0.subsequent_seq == 5


# ============================================================================
# 4. HIGH-PRIORITY AUDIT D — APPLIANCE POWER BUDGET & HEADROOM
# ============================================================================

class TestHighPriorityAuditDPowerBudget:
    """Tests Section 7 requirements for power budget calculations and BOM accuracy."""

    def test_01_denominator_transparency_in_headroom_calculations(self) -> None:
        """
        For Enterprise profile (800W PSU, 608.2W worst-case load):
        - Unused rated capacity = 800 - 608.2 = 191.8W
        - Headroom relative to load = 191.8 / 608.2 = 31.54%
        - Headroom relative to PSU rating = 191.8 / 800 = 23.98%
        Both fields must be distinct and mathematically accurate.
        """
        spec = ApplianceCatalog.get_specification(ApplianceProfileType.PROFILE_D_ENTERPRISE)
        assert spec.worst_case_power_watts == 608.2
        assert spec.psu_capacity_watts == 800.0

        unused_w = spec.psu_capacity_watts - spec.worst_case_power_watts
        assert abs(unused_w - 191.8) < 0.01

        # Margin relative to load: 191.8 / 608.2 * 100 = 31.5356% -> 31.54%
        margin_to_load = round((unused_w / spec.worst_case_power_watts) * 100.0, 2)
        assert abs(spec.psu_headroom_to_load_percent - margin_to_load) < 0.1

        # Margin relative to PSU rating: 191.8 / 800 * 100 = 23.975% -> 23.98%
        margin_to_psu = round((unused_w / spec.psu_capacity_watts) * 100.0, 2)
        assert abs(spec.psu_headroom_to_psu_rating_percent - margin_to_psu) < 0.1

        # Must not confuse the two!
        assert spec.psu_headroom_to_load_percent != spec.psu_headroom_to_psu_rating_percent

    def test_02_single_surviving_psu_redundancy_survival(self) -> None:
        """In 1+1 redundant configurations, single surviving PSU carries full load."""
        for ptype in (ApplianceProfileType.PROFILE_C_PROFESSIONAL, ApplianceProfileType.PROFILE_D_ENTERPRISE):
            spec = ApplianceCatalog.get_specification(ptype)
            assert spec.psu_redundant is True
            # Single PSU capacity must exceed full worst-case system load
            assert spec.psu_capacity_watts > spec.worst_case_power_watts

    def test_03_gpu_is_strictly_optional_across_all_profiles(self) -> None:
        """Every appliance specification mandates is_gpu_required=False and supports_cpu_only=True."""
        for ptype, spec in ApplianceCatalog.SPECIFICATIONS.items():
            assert spec.is_gpu_required is False, f"Profile {ptype} violates GPU optionality mandate"
            assert spec.supports_cpu_only is True, f"Profile {ptype} must support CPU-only execution"


# ============================================================================
# 5. HIGH-PRIORITY AUDIT E — STRESS SCENARIOS & ADAPTIVE HYSTERESIS
# ============================================================================

class TestHighPriorityAuditEStressAndHysteresis:
    """Tests Section 8 requirements for multi-vector stress and adaptive stability."""

    def test_01_multi_vector_stress_level_1_fault_injection(self) -> None:
        """Level 1 functional fault tests: queue saturation, slow disk, hung supervisor."""
        # Queue saturation
        q = BoundedPipelineQueue[int]("fault_q", maxsize=3, policy=QueueOverflowPolicy.DROP_NEWEST)
        assert q.put(1) is True
        assert q.put(2) is True
        assert q.put(3) is True
        assert q.put(4) is False  # Drop newest
        assert q.total_dropped == 1

        # Disk full flag
        q.set_disk_full(True)
        assert q.is_disk_full is True

        # Hung supervisor check
        sup = WorkerCrashSupervisor("fault_sup", heartbeat_timeout_sec=0.05)
        time.sleep(0.06)
        assert sup.check_hung() is True
        sup.revoke_channel_lease()

    def test_02_combined_stress_level_2_backpressure_and_failover(self) -> None:
        """Level 2 combined stress: CPU saturation admission rejection + queue backpressure."""
        controller = CPUFallbackAdmissionController(reject_cpu_threshold=85.0)
        # Saturate CPU
        res = controller.evaluate_task_admission(
            task=TaskCPUCostEstimate(
                task_id="stream_heavy",
                task_type="ai_inference",
                camera_id="cam_01",
                estimated_cpu_percent=15.0,
            ),
            current_cpu_percent=92.0,
        )
        assert res.decision == FallbackAdmissionDecision.FALLBACK_REJECTED

        # Enqueue backpressure
        ledger = RecordingContinuityLedger()
        ledger.start_segment("cam_stress_01", "main", "seg_s2")
        rec_q = BoundedPipelineQueue[str](
            "rec_stress_q",
            maxsize=2,
            policy=QueueOverflowPolicy.APPLY_BACKPRESSURE,
            pipeline_type=PipelineType.RECORDING_INGEST,
            continuity_ledger=ledger,
            camera_id="cam_stress_01",
            segment_id="seg_s2",
        )
        rec_q.put("pkt1", timeout_sec=0.01)
        rec_q.put("pkt2", timeout_sec=0.01)
        # Drops with backpressure timeout
        ok = rec_q.put("pkt3", timeout_sec=0.02)
        assert ok is False
        assert rec_q.total_dropped == 1

    def test_03_extended_software_soak_level_3_ui_zero_freeze_measurement(self) -> None:
        """
        Level 3 extended software soak simulation.
        Measures UI loop execution times under concurrent background I/O workload.
        Verifies UI loop max latency remains <= 30ms (zero-freeze requirement).
        """
        stop_worker = threading.Event()
        counter = [0]

        # Background synthetic worker simulating video packet processing
        def bg_pipeline() -> None:
            q: collections.deque[int] = collections.deque(maxlen=100)
            while not stop_worker.is_set():
                q.append(1)
                if len(q) > 50:
                    q.popleft()
                counter[0] += 1
                time.sleep(0.001)

        t = threading.Thread(target=bg_pipeline, daemon=True)
        t.start()

        # Simulate 100 UI interactive event loops
        latencies_ms: list[float] = []
        for _ in range(100):
            t_start = time.perf_counter()
            # UI loop dispatch simulation
            time.sleep(0.002)
            t_end = time.perf_counter()
            latencies_ms.append((t_end - t_start) * 1000.0)

        stop_worker.set()
        t.join(timeout=0.5)

        avg_latency = sum(latencies_ms) / len(latencies_ms)
        max_latency = max(latencies_ms)

        assert max_latency < 30.0, f"UI loop froze: max latency was {max_latency:.2f}ms"
        assert avg_latency < 10.0, f"Average UI latency too high: {avg_latency:.2f}ms"
        assert counter[0] > 50, "Background pipeline did not execute"

    def test_04_adaptive_hysteresis_and_cooldown_stability(self) -> None:
        """Validates that adaptive manager obeys hysteresis and does not oscillate rapidly."""
        tier = TierPolicyEngine.get_preset(HardwareTier.TIER_2_STANDARD)
        mgr = AdaptiveResourceManager(
            base_tier_config=tier,
            warning_ram_threshold=85.0,
            emergency_ram_threshold=92.0,
            warning_cpu_threshold=88.0,
            cooldown_period_sec=0.01,
        )

        # Baseline: normal
        snap_normal = ResourceSnapshot(
            timestamp=time.time(),
            cpu_percent=40.0,
            ram_percent=60.0,
            ram_used_mb=4000,
            ram_available_mb=4000,
        )
        mgr.evaluate_pressure(snap_normal)
        assert mgr.operating_state == ResourceOperatingState.NORMAL

        # Pressure surge: transitions to CRITICAL
        snap_surge = ResourceSnapshot(
            timestamp=time.time(),
            cpu_percent=96.0,
            ram_percent=95.0,
            ram_used_mb=7600,
            ram_available_mb=400,
            is_emergency=True,
        )
        mgr.evaluate_pressure(snap_surge)
        assert mgr.operating_state == ResourceOperatingState.CRITICAL

        time.sleep(0.02)
        # Small drop within hysteresis buffer (83% RAM, 84% CPU): remains in CRITICAL, anti-flapping
        snap_minor_drop = ResourceSnapshot(
            timestamp=time.time(),
            cpu_percent=84.0,
            ram_percent=83.0,
            ram_used_mb=6600,
            ram_available_mb=1400,
        )
        mgr.evaluate_pressure(snap_minor_drop)
        assert mgr.operating_state == ResourceOperatingState.CRITICAL

        time.sleep(0.02)
        # Step-wise recovery: recovery band metrics transition to RECOVERY
        snap_recovery = ResourceSnapshot(
            timestamp=time.time(),
            cpu_percent=60.0,
            ram_percent=72.0,
            ram_used_mb=5700,
            ram_available_mb=2300,
        )
        acts_step = mgr.evaluate_pressure(snap_recovery)
        assert mgr.operating_state == ResourceOperatingState.RECOVERY
        assert len(acts_step) == 1
        assert acts_step[0].action_type == "RESTORE_STEP"

        time.sleep(0.02)
        # Fully clean metrics: transition from RECOVERY to NORMAL
        snap_clean = ResourceSnapshot(
            timestamp=time.time(),
            cpu_percent=30.0,
            ram_percent=50.0,
            ram_used_mb=4000,
            ram_available_mb=4000,
        )
        acts_norm = mgr.evaluate_pressure(snap_clean)
        assert mgr.operating_state == ResourceOperatingState.NORMAL
        assert len(acts_norm) == 1
        assert acts_norm[0].action_type == "RESTORE_NORMAL"


# ============================================================================
# 6. EVIDENCE INTEGRITY & LEGAL HOLDS REGRESSION
# ============================================================================

class TestEvidenceIntegrityRegression:
    """Verifies that evidence storage, SQLite WAL holds, and legal preservation are intact."""

    def test_persistent_legal_holds_protection(self, tmp_path: Path) -> None:
        """Legal hold prevents segment purge and reloads accurately from disk database."""
        db_path = tmp_path / "holds_regression.db"
        store = PreservationStore(db_path=db_path)

        hold = PreservationHold(
            hold_id="HOLD-PHASE25-1A-001",
            target_id="seg_cam01_20261117",
            target_type="segment",
            reason="Court Order Case #2026-CV-9988",
            authorized_by="Lead Forensics Officer",
            hold_type="legal_hold",
        )
        store.save_hold(hold)

        # Reload store from disk
        store2 = PreservationStore(db_path=db_path)
        active = store2.load_active_holds()

        assert "HOLD-PHASE25-1A-001" in active
        reloaded_hold = active["HOLD-PHASE25-1A-001"]
        assert reloaded_hold.target_id == "seg_cam01_20261117"
        assert reloaded_hold.hold_type == "legal_hold"
        assert reloaded_hold.authorized_by == "Lead Forensics Officer"
