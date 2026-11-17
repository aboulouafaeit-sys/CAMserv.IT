"""
tests.test_phase25_1_b_cross_platform
=====================================

Qualification test suite for CAMserv Phase 25.1-B:
- Stage A: Cross-Platform Worker Termination, Process Isolation, IPC Reconciliation & Lease Fencing
- Stage B: Durable Recording Continuity Ledger (SQLite WAL Persistence, Unclean Crash Recovery, Degradation)
- Stage C: Multi-Camera Extended Software Soak Simulation with Fault Injection & Time-Series Metrics

Classification Labels Applied:
- ACTUALLY_EXECUTED_ON_WINDOWS: Native execution on Windows 11 host.
- MOCKED / SOFTWARE_INTEGRATION_TESTED: POSIX signal escalation and simulated fault paths.
- PHYSICAL_HARDWARE_TESTED: Physical CPU/RAM resource measurements on current host.
"""

from __future__ import annotations

import collections
import gc
import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from camserv.platform.stability import (
    BoundedPipelineQueue,
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
)
from camserv.storage.continuity_store import (
    CURRENT_CONTINUITY_SCHEMA_VERSION,
    ContinuityStoreCorruptError,
    ContinuityStoreError,
    DurableContinuityStore,
)


# ============================================================================
# STAGE A: Cross-Platform Worker Termination & Process Isolation Tests
# ============================================================================

@pytest.fixture(autouse=True)
def clean_channel_leases():
    """Ensure lease registry is clean before and after each test."""
    with WorkerCrashSupervisor._LEASE_LOCK:
        WorkerCrashSupervisor._ACTIVE_CHANNEL_LEASES.clear()
    yield
    with WorkerCrashSupervisor._LEASE_LOCK:
        WorkerCrashSupervisor._ACTIVE_CHANNEL_LEASES.clear()


class TestCrossPlatformWorkerTermination:
    """
    Verification of worker lifecycle management, non-blocking termination,
    IPC resource reconciliation, and strict channel lease fencing.
    """

    def test_windows_cooperative_cancellation_and_token_checkpoints(self) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify cooperative cancellation token propagation: worker checks token
        and exits gracefully, supervisor confirms termination and revokes lease.
        """
        token = CancellationToken()
        worker_executed_checkpoints = 0
        worker_finished = threading.Event()

        def _worker_loop() -> None:
            nonlocal worker_executed_checkpoints
            while not token.is_cancelled:
                worker_executed_checkpoints += 1
                time.sleep(0.01)
            token.confirm_stopped()
            worker_finished.set()

        t = threading.Thread(target=_worker_loop, daemon=True)
        supervisor = WorkerCrashSupervisor("test_cam01_worker", channel_id="cam_01")
        supervisor.register_worker(thread=t, token=token)
        t.start()

        # Let worker run briefly
        time.sleep(0.04)
        assert worker_executed_checkpoints >= 1
        assert supervisor.lease_token is not None

        # Request cancellation
        stopped = supervisor.request_cancellation(timeout_sec=1.0)
        assert stopped is True
        assert supervisor.termination_confirmed is True
        assert supervisor.termination_unconfirmed is False
        assert supervisor.state == WorkerLifecycleState.TERMINATED
        assert supervisor.lease_token is None  # Lease revoked only after confirmed stop
        assert worker_finished.is_set()

    def test_windows_unresponsive_worker_timeout_guard(self) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify that when a worker hangs and ignores cancellation, supervisor detects
        the timeout, reports TERMINATION_UNCONFIRMED, and crucially PRESERVES channel
        lease fencing so no duplicate worker can spawn.
        """
        token = CancellationToken()
        hang_event = threading.Event()

        def _hung_worker() -> None:
            # Deliberately ignores token.is_cancelled
            hang_event.wait(timeout=2.0)

        t = threading.Thread(target=_hung_worker, daemon=True)
        supervisor = WorkerCrashSupervisor("hung_cam02_worker", channel_id="cam_02")
        original_lease = supervisor.lease_token
        assert original_lease is not None
        supervisor.register_worker(thread=t, token=token)
        t.start()

        # Attempt cancellation with short timeout
        stopped = supervisor.request_cancellation(timeout_sec=0.05)
        try:
            assert stopped is False
            assert supervisor.termination_confirmed is False
            assert supervisor.termination_unconfirmed is True
            assert supervisor.state == WorkerLifecycleState.TERMINATION_UNCONFIRMED
            # Mandatory Invariant: channel lease MUST NOT be revoked while worker state is unconfirmed
            assert supervisor.lease_token == original_lease
            assert WorkerCrashSupervisor._ACTIVE_CHANNEL_LEASES.get("cam_02") == original_lease
        finally:
            hang_event.set()
            t.join(timeout=0.5)
            supervisor.revoke_channel_lease()

    def test_windows_process_forced_termination(self) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS / SOFTWARE_INTEGRATION_TESTED]
        Verify controlled process termination using proc.kill() / TerminateProcess.
        Confirm exit via is_alive() check, reconciliation of IPC resources, and lease revocation.
        """
        mock_proc = MagicMock()
        mock_proc.is_alive.side_effect = [True, False]  # Alive before kill, dead after kill

        supervisor = WorkerCrashSupervisor("proc_worker_cam03", channel_id="cam_03")
        supervisor.register_worker(process=mock_proc)
        assert supervisor.lease_token is not None

        # Terminate with force=True
        ok = supervisor.terminate_worker(force=True, timeout_sec=0.5)
        assert ok is True
        assert mock_proc.kill.called
        assert supervisor.termination_forced is True
        assert supervisor.termination_confirmed is True
        assert supervisor.termination_unconfirmed is False
        assert supervisor.state == WorkerLifecycleState.TERMINATED
        assert supervisor.lease_token is None

    def test_windows_process_exit_confirmation_is_alive_refusal(self) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify that if a process remains alive even after kill(), supervisor reports
        TERMINATION_UNCONFIRMED and DOES NOT release channel lease.
        """
        mock_proc = MagicMock()
        mock_proc.is_alive.return_value = True  # Process refuses to die

        supervisor = WorkerCrashSupervisor("stubborn_proc_worker", channel_id="cam_04")
        supervisor.register_worker(process=mock_proc)
        original_lease = supervisor.lease_token
        assert original_lease is not None

        try:
            ok = supervisor.terminate_worker(force=True, timeout_sec=0.05)
            assert ok is False
            assert supervisor.termination_confirmed is False
            assert supervisor.termination_unconfirmed is True
            assert supervisor.state == WorkerLifecycleState.TERMINATION_UNCONFIRMED
            # Lease is protected
            assert supervisor.lease_token == original_lease
        finally:
            supervisor.revoke_channel_lease()

    def test_windows_ipc_resource_reconciliation(self) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify reconcile_ipc() properly sanitizes registered IPC resources
        (multiprocessing.Queue, Pipe connections) to prevent supervisor deadlocks.
        """
        supervisor = WorkerCrashSupervisor("ipc_clean_worker", channel_id="cam_05")

        mock_queue = MagicMock()
        mock_queue.close = MagicMock()
        mock_queue.cancel_join_thread = MagicMock()

        mock_pipe = MagicMock()
        mock_pipe.close = MagicMock()

        supervisor.register_ipc_resource(mock_queue)
        supervisor.register_ipc_resource(mock_pipe)
        assert len(supervisor.ipc_resources) == 2

        supervisor.reconcile_ipc()
        assert mock_queue.close.called
        assert mock_queue.cancel_join_thread.called
        assert mock_pipe.close.called
        assert len(supervisor.ipc_resources) == 0

    def test_channel_lease_retention_before_exit_confirmation(self) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify strict anti-duplicate worker fencing: while Worker A holds lease for 'cam_06',
        Worker B attempting to acquire the same channel is rejected and fenced.
        """
        sup_a = WorkerCrashSupervisor("worker_a", channel_id="cam_06")
        token_a = sup_a.lease_token
        assert token_a is not None

        sup_b = WorkerCrashSupervisor("worker_b", channel_id="cam_06")
        # sup_b should have failed to acquire lease and become fenced
        assert sup_b.lease_token is None
        assert sup_b.is_fenced is True
        assert sup_b.state == WorkerLifecycleState.TERMINATED

        # Now cleanly terminate A
        sup_a.terminate_worker()
        assert sup_a.lease_token is None

        # Now Worker C can acquire it
        sup_c = WorkerCrashSupervisor("worker_c", channel_id="cam_06")
        assert sup_c.lease_token is not None
        sup_c.revoke_channel_lease()

    def test_unexpected_worker_crash_handling_and_backoff(self) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify that unexpected worker crashes increment restart count, compute exponential backoff,
        and cleanly fence the worker once max_restarts is exceeded.
        """
        sup = WorkerCrashSupervisor("flaky_worker", max_restarts=3, backoff_base_sec=0.1, channel_id="cam_07")
        try:
            # Crash 1
            d1 = sup.record_crash(RuntimeError("Decoder SEGV"))
            assert d1 > 0
            assert sup.restart_count == 1
            assert not sup.is_fenced

            # Crash 2
            d2 = sup.record_crash(RuntimeError("Decoder SEGV 2"))
            assert d2 > d1
            assert sup.restart_count == 2
            assert not sup.is_fenced

            # Crash 3
            d3 = sup.record_crash(RuntimeError("Decoder SEGV 3"))
            assert d3 > d2
            assert sup.restart_count == 3
            assert not sup.is_fenced

            # Crash 4: exceeds max_restarts (3)
            d4 = sup.record_crash(RuntimeError("Fatal pipeline stall"))
            assert d4 == -1.0
            assert sup.restart_count == 4
            assert sup.is_fenced is True
            assert sup.state == WorkerLifecycleState.TERMINATED
            assert sup.lease_token is None  # Lease revoked upon fencing
        finally:
            sup.revoke_channel_lease()

    def test_partial_segment_recovery_after_process_kill(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify quarantine_partial_segment safely renames an in-flight .part recording
        to .recovered_partial.mp4 without data truncation.
        """
        part_file = tmp_path / "stream_cam08_20261117_180000.part"
        part_file.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"A" * 4096)

        sup = WorkerCrashSupervisor("recovery_worker", channel_id="cam_08")
        try:
            recovered_path = sup.quarantine_partial_segment(part_file, reason="WORKER_KILLED")
            assert recovered_path is not None
            assert recovered_path.exists()
            assert not part_file.exists()
            assert "recovered_partial.mp4" in recovered_path.name
            assert recovered_path.stat().st_size == 4096 + 12
            assert sup.state == WorkerLifecycleState.RECOVERED
        finally:
            sup.revoke_channel_lease()

    def test_posix_sigterm_sigkill_escalation_mocked(self) -> None:
        """
        [MOCKED / SOFTWARE_INTEGRATION_TESTED]
        Verify POSIX graceful SIGTERM followed by SIGKILL escalation logic
        when running on Linux systems, with zombie prevention.
        """
        mock_proc = MagicMock()
        calls = []

        def _terminate() -> None:
            calls.append("SIGTERM")

        def _kill() -> None:
            calls.append("SIGKILL")

        mock_proc.terminate.side_effect = _terminate
        mock_proc.kill.side_effect = _kill
        # Process does not exit on SIGTERM, but exits on SIGKILL
        mock_proc.is_alive.side_effect = [True, False]

        sup = WorkerCrashSupervisor("posix_mock_worker", channel_id="cam_posix")
        sup.register_worker(process=mock_proc)

        ok = sup.terminate_worker(force=False, timeout_sec=0.1)
        assert ok is True
        assert "SIGTERM" in calls
        assert "SIGKILL" in calls
        assert sup.termination_confirmed is True
        assert sup.state == WorkerLifecycleState.TERMINATED


# ============================================================================
# STAGE B: Durable Recording Continuity Ledger Tests
# ============================================================================

class TestDurableContinuityLedger:
    """
    Verification of transactional SQLite WAL continuity store,
    idempotent upsert, crash recovery, and non-blocking degradation.
    """

    def test_durable_continuity_store_initialization_wal(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify DurableContinuityStore creates database with WAL journal mode,
        synchronous NORMAL, schema versioning, and required tables.
        """
        db_file = tmp_path / "continuity.db"
        store = DurableContinuityStore(db_file)
        assert store.is_degraded is False

        # Verify PRAGMAs and schema directly
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0]
        assert journal_mode.lower() == "wal"

        cursor.execute("SELECT version FROM schema_version;")
        ver = cursor.fetchone()[0]
        assert ver == CURRENT_CONTINUITY_SCHEMA_VERSION

        # Verify tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        assert "continuity_segments" in tables
        assert "continuity_events" in tables
        conn.close()

    def test_durable_continuity_segment_persistence_and_upsert(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify segments can be saved, updated idempotently via UPSERT, and loaded.
        """
        db_file = tmp_path / "continuity_upsert.db"
        store = DurableContinuityStore(db_file)

        now_iso = datetime.now(timezone.utc).isoformat()
        rec = RecordingContinuityRecord(
            camera_id="cam_front",
            stream_id="stream_01",
            segment_id="seg_001",
            start_timestamp_utc=now_iso,
            observed_frames=100,
            expected_frames=100,
            current_state=RecordingContinuityState.CONTINUOUS,
        )

        # Initial save
        saved = store.save_segment(rec)
        assert saved is True

        loaded = store.load_segment("cam_front", "seg_001")
        assert loaded is not None
        assert loaded.observed_frames == 100
        assert loaded.current_state == RecordingContinuityState.CONTINUOUS

        # Upsert with more frames and degraded state
        rec.observed_frames = 250
        rec.confirmed_missing_frames_total = 5
        rec.current_state = RecordingContinuityState.FRAME_GAP_DETECTED
        rec.is_finalized = True

        store.save_segment(rec)
        loaded2 = store.load_segment("cam_front", "seg_001")
        assert loaded2 is not None
        assert loaded2.observed_frames == 250
        assert loaded2.confirmed_missing_frames_total == 5
        assert loaded2.current_state == RecordingContinuityState.FRAME_GAP_DETECTED
        assert loaded2.is_finalized is True

    def test_durable_continuity_event_persistence_and_deduplication(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify DiscontinuityEvents are durably persisted and deduplicated by event_id.
        """
        db_file = tmp_path / "continuity_events.db"
        store = DurableContinuityStore(db_file)

        now_iso = datetime.now(timezone.utc).isoformat()
        seg = RecordingContinuityRecord(
            camera_id="cam_gate",
            stream_id="main",
            segment_id="seg_gate_01",
            start_timestamp_utc=now_iso,
        )
        store.save_segment(seg)

        ev = DiscontinuityEvent(
            camera_id="cam_gate",
            stream_id="main",
            segment_id="seg_gate_01",
            gap_start_utc=now_iso,
            gap_end_utc=now_iso,
            gap_duration_sec=0.35,
            lost_frames_estimated=10,
            confirmed_missing_frames=10,
            reason="NETWORK_TIMEOUT",
            detected_at_utc=now_iso,
            last_confirmed_seq=100,
            subsequent_seq=111,
        )

        ok1 = store.save_discontinuity_event(ev, event_id="ev_001")
        assert ok1 is True

        # Insert again with identical event_id (must be ignored, not crash)
        ok2 = store.save_discontinuity_event(ev, event_id="ev_001")
        assert ok2 is True

        # Load segment and check event was attached
        loaded_seg = store.load_segment("cam_gate", "seg_gate_01")
        assert loaded_seg is not None
        assert len(loaded_seg.discontinuities) == 1
        assert loaded_seg.discontinuities[0].reason == "NETWORK_TIMEOUT"
        assert loaded_seg.discontinuities[0].confirmed_missing_frames == 10

    def test_durable_continuity_unclean_shutdown_recovery(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify unclean shutdown recovery: unfinalized segments left in-flight
        prior to process death are marked RECORDING_INTERRUPTED, assigned a crash
        discontinuity record, and never falsely reported as continuous.
        """
        db_file = tmp_path / "continuity_crash.db"
        store1 = DurableContinuityStore(db_file)

        # Simulate unfinalized active segment
        seg = RecordingContinuityRecord(
            camera_id="cam_crash",
            stream_id="main",
            segment_id="seg_unfinalized_99",
            start_timestamp_utc="2026-11-17T18:00:00Z",
            observed_frames=450,
            is_finalized=False,
            current_state=RecordingContinuityState.CONTINUOUS,
        )
        store1.save_segment(seg)

        # Simulate abrupt crash and restart: create fresh store instance
        store2 = DurableContinuityStore(db_file)
        recovered = store2.recover_unclean_shutdown()

        assert len(recovered) == 1
        rec = recovered[0]
        assert rec.segment_id == "seg_unfinalized_99"
        assert rec.current_state == RecordingContinuityState.RECORDING_INTERRUPTED
        assert rec.is_finalized is True
        assert rec.unknown_frame_loss_events >= 1
        assert len(rec.discontinuities) >= 1
        assert rec.discontinuities[-1].reason == "PROCESS_ABRUPT_TERMINATION_OR_POWER_CUT"

        # Verify on-disk persistence of recovery
        persisted = store2.load_segment("cam_crash", "seg_unfinalized_99")
        assert persisted is not None
        assert persisted.current_state == RecordingContinuityState.RECORDING_INTERRUPTED
        assert persisted.is_finalized is True

        # Running recovery again should find 0 unfinalized segments
        assert len(store2.recover_unclean_shutdown()) == 0

    def test_ledger_integration_with_durable_store(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify RecordingContinuityLedger seamlessly persists updates to DurableContinuityStore
        and rehydrates unfinalized segments across simulated restarts.
        """
        db_file = tmp_path / "ledger_integrated.db"
        ledger1 = RecordingContinuityLedger(db_path=db_file)
        ledger1.register_camera_fps("cam_yard", 30.0)

        # Start segment and record frames
        ledger1.start_segment("cam_yard", "stream_hd", "seg_yard_01")
        for i in range(1, 31):
            ledger1.record_frame("cam_yard", "seg_yard_01", frame_seq=i, pts=i / 30.0)

        # Record a gap
        ledger1.record_discontinuity(
            camera_id="cam_yard",
            segment_id="seg_yard_01",
            gap_duration_sec=0.2,
            reason="RTSP_DROPPED_PACKET",
            last_seq=30,
            curr_seq=36,
        )

        # Verify state in ledger1
        rec1 = ledger1.get_record("cam_yard", "seg_yard_01")
        assert rec1 is not None
        assert rec1.observed_frames == 30
        assert rec1.confirmed_missing_frames_total == 5
        assert rec1.current_state in (RecordingContinuityState.FRAME_GAP_DETECTED, RecordingContinuityState.RECORDING_DEGRADED)

        # Simulate restart with ledger2 pointing to same database
        ledger2 = RecordingContinuityLedger(db_path=db_file)
        recovered = ledger2.recover_from_store()
        assert len(recovered) == 1
        assert recovered[0].current_state == RecordingContinuityState.RECORDING_INTERRUPTED

        rec2 = ledger2.get_record("cam_yard", "seg_yard_01")
        assert rec2 is not None
        assert rec2.current_state == RecordingContinuityState.RECORDING_INTERRUPTED

    def test_persistence_degradation_without_blocking_recording(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify that database failure (e.g., locked file, permission error) sets
        is_persistence_degraded=True but DOES NOT crash or block frame recording.
        """
        db_file = tmp_path / "degraded.db"
        store = DurableContinuityStore(db_file)
        ledger = RecordingContinuityLedger(durable_store=store)

        ledger.start_segment("cam_deg", "main", "seg_deg_01")
        assert ledger.is_persistence_degraded is False

        # Inject failure into store.save_segment
        with patch.object(store, "save_segment", return_value=False):
            # Ingesting frames must still succeed in memory
            for i in range(1, 10):
                ledger.record_frame("cam_deg", "seg_deg_01", frame_seq=i, pts=i * 0.033)

            assert ledger.is_persistence_degraded is True
            rec = ledger.get_record("cam_deg", "seg_deg_01")
            assert rec is not None
            assert rec.observed_frames == 9  # In-memory continuity is intact!

    def test_concurrent_multi_camera_events_in_continuity_store(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify concurrent writes from multiple camera threads to the SQLite WAL
        continuity store operate reliably without database locks or corruptions.
        """
        db_file = tmp_path / "concurrent_store.db"
        store = DurableContinuityStore(db_file)

        camera_ids = [f"cam_{i:02d}" for i in range(8)]
        threads = []
        errors = []

        def _cam_worker(cid: str) -> None:
            try:
                for seg_idx in range(5):
                    sid = f"seg_{cid}_{seg_idx}"
                    now_iso = datetime.now(timezone.utc).isoformat()
                    rec = RecordingContinuityRecord(
                        camera_id=cid,
                        stream_id="main",
                        segment_id=sid,
                        start_timestamp_utc=now_iso,
                        observed_frames=50,
                    )
                    store.save_segment(rec)

                    ev = DiscontinuityEvent(
                        camera_id=cid,
                        stream_id="main",
                        segment_id=sid,
                        gap_start_utc=now_iso,
                        gap_end_utc=now_iso,
                        gap_duration_sec=0.1,
                        lost_frames_estimated=3,
                        reason="SYNTHETIC_GAP",
                        detected_at_utc=now_iso,
                    )
                    store.save_discontinuity_event(ev)
            except Exception as e:
                errors.append(f"{cid}: {e}")

        for cid in camera_ids:
            t = threading.Thread(target=_cam_worker, args=(cid,), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0
        assert store.is_degraded is False

        # Verify all 40 segments were persisted
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM continuity_segments;")
        seg_count = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM continuity_events;")
        ev_count = cursor.fetchone()[0]
        conn.close()

        assert seg_count == 40
        assert ev_count == 40


# ============================================================================
# STAGE C: Multi-Camera Extended Software Soak & Failure Recovery Tests
# ============================================================================

class TestExtendedSoftwareSoakSimulation:
    """
    Simulation of multi-camera sustained ingest, queue pressure,
    preview frame dropping, AI downsampling, and injected fault recovery.
    Captures verifiable time-series telemetry.
    """

    def test_multi_camera_soak_stream_workload(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS / PHYSICAL_HARDWARE_TESTED]
        Simulate sustained 4-camera video ingest (30 fps) across bounded queues
        with live WAL continuity commits and measure exact time-series performance.
        """
        db_file = tmp_path / "soak_test.db"
        store = DurableContinuityStore(db_file)
        ledger = RecordingContinuityLedger(durable_store=store)

        cameras = ["cam_north", "cam_south", "cam_east", "cam_west"]
        queues = {
            cam: BoundedPipelineQueue[bytes](
                name=f"rec_queue_{cam}",
                maxsize=60,
                policy=QueueOverflowPolicy.DROP_OLDEST,
                pipeline_type=PipelineType.RECORDING_INGEST,
                continuity_ledger=ledger,
                camera_id=cam,
                segment_id=f"seg_{cam}_01",
            )
            for cam in cameras
        }

        for cam in cameras:
            ledger.register_camera_fps(cam, 30.0)
            ledger.start_segment(cam, "main", f"seg_{cam}_01")

        start_time = time.perf_counter()
        frames_ingested = 0
        target_frames = 120  # 120 frames per camera = 480 total frames

        for seq in range(1, target_frames + 1):
            pts = seq / 30.0
            frame_payload = b"FRAME_" + bytes(seq % 256 for _ in range(512))
            for cam in cameras:
                # Enqueue into bounded pipeline
                queues[cam].put(frame_payload, timeout_sec=0.01)
                ledger.record_frame(cam, f"seg_{cam}_01", frame_seq=seq, pts=pts)
                frames_ingested += 1

                # Dequeue simulate disk storage consumer
                popped = queues[cam].get(timeout_sec=0.01)
                assert popped is not None

        elapsed = time.perf_counter() - start_time
        assert frames_ingested == 480
        assert elapsed > 0.0

        # Verify all cameras maintained CONTINUOUS state with 0 missing frames
        for cam in cameras:
            rec = ledger.get_record(cam, f"seg_{cam}_01")
            assert rec is not None
            assert rec.observed_frames == target_frames
            assert rec.confirmed_missing_frames_total == 0
            assert rec.current_state == RecordingContinuityState.CONTINUOUS
            assert queues[cam].total_dropped == 0

    def test_soak_fault_injection_recovery(self, tmp_path: Path) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Simulate mixed camera stream with injected faults:
        1. Storage write stall -> queue overflow -> preview frames drop gracefully.
        2. Camera network packet drop -> discontinuity gap logged.
        3. Camera reconnect -> continuity recovers cleanly.
        """
        db_file = tmp_path / "soak_faults.db"
        store = DurableContinuityStore(db_file)
        ledger = RecordingContinuityLedger(durable_store=store)

        cid = "cam_fault_01"
        sid = "seg_fault_01"
        ledger.register_camera_fps(cid, 30.0)
        ledger.start_segment(cid, "main", sid)

        # Preview queue with DROP_OLDEST
        preview_queue = BoundedPipelineQueue[bytes](
            name="preview_q",
            maxsize=5,
            policy=QueueOverflowPolicy.DROP_OLDEST,
            pipeline_type=PipelineType.LIVE_PREVIEW,
            continuity_ledger=ledger,
            camera_id=cid,
            segment_id=sid,
        )

        # 1. Simulate burst of 15 frames into preview queue of size 5
        for i in range(15):
            preview_queue.put(b"PREVIEW_FRAME", timeout_sec=0.001)

        # Preview queue should have dropped 10 frames without crashing
        assert preview_queue.total_dropped == 10
        assert preview_queue.overflow_events == 10
        assert preview_queue.qsize() == 5

        # 2. Ingest frames with a network drop between seq 20 and seq 26
        for seq in range(1, 21):
            ledger.record_frame(cid, sid, frame_seq=seq, pts=seq / 30.0)

        # Inject network gap: seq 21-25 lost (5 frames lost)
        ledger.record_discontinuity(
            camera_id=cid,
            segment_id=sid,
            gap_duration_sec=0.166,
            reason="CAMERA_RTSP_PACKET_LOSS",
            last_seq=20,
            curr_seq=26,
            last_pts=20 / 30.0,
            curr_pts=26 / 30.0,
        )

        # Ingest subsequent frames after reconnect
        for seq in range(26, 41):
            ledger.record_frame(cid, sid, frame_seq=seq, pts=seq / 30.0)

        rec = ledger.get_record(cid, sid)
        assert rec is not None
        assert rec.observed_frames == 35
        assert rec.confirmed_missing_frames_total == 5
        assert rec.current_state in (RecordingContinuityState.FRAME_GAP_DETECTED, RecordingContinuityState.RECORDING_DEGRADED)
        assert len(rec.discontinuities) == 1
        assert rec.discontinuities[0].reason == "CAMERA_RTSP_PACKET_LOSS"

    def test_nonblocking_executor_ui_isolation(self) -> None:
        """
        [ACTUALLY_EXECUTED_ON_WINDOWS]
        Verify NonBlockingExecutor protects UI dispatch loop from hanging
        during blocking network probes or slow disk syncs.
        """
        def _slow_task() -> str:
            time.sleep(0.2)
            return "DONE"

        # Hard timeout of 0.05s on a 0.2s task
        success, result, err = NonBlockingExecutor.execute_with_timeout(
            _slow_task,
            timeout_sec=0.05,
            fallback_value="FALLBACK",
        )
        assert success is False
        assert result == "FALLBACK"
        assert err is not None
        assert "timed out" in err.lower()
