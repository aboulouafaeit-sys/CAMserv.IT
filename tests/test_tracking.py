"""Tracking subsystem tests for CAMserv.

Verifies:
- ByteTrack assigns unique anonymous incrementing integer IDs
- ByteTrack maintains track persistence across temporary occlusion
- ByteTrack handles empty detection inputs gracefully
- ByteTrack purges stale lost tracks exceeding max_age
- ByteTrack detects and tallies ID switches
- BoT-SORT integrates appearance embeddings when available
- BoT-SORT falls back gracefully to motion/IoU when Re-ID is absent
- KalmanBoxTracker predict/update cycle stability
- Tracking IDs are strictly anonymous and contain no PII
- Track fragmentation telemetry
- Tracking performance in crowded scenes (20+ objects)
- Multi-Object Tracking Accuracy (MOTA) and Precision (MOTP) calculations
"""

from __future__ import annotations

import numpy as np
import pytest

from camserv.pipeline.interfaces import (
    BoundingBox,
    Detection,
    Frame,
    Track,
    TrackState,
)
from camserv.tracking.botsort import BoTSORTracker, GMCMethod
from camserv.tracking.bytetrack import ByteTracker, STrack
from camserv.tracking.kalman import KalmanBoxTracker
from camserv.tracking.metrics import TrackingMetrics


@pytest.mark.unit
def test_bytetrack_assigns_unique_ids() -> None:
    """Verify that ByteTracker assigns unique incrementing integer IDs to distinct objects."""
    tracker = ByteTracker(track_thresh=0.5, min_hits=1)

    bboxes = np.array([
        [10.0, 10.0, 50.0, 50.0],
        [100.0, 100.0, 160.0, 160.0],
        [300.0, 300.0, 380.0, 380.0],
    ])
    confs = np.array([0.9, 0.85, 0.95])

    tracks = tracker.update(bboxes, confs)

    assert len(tracks) == 3
    track_ids = [t.track_id for t in tracks]
    assert len(set(track_ids)) == 3
    # All IDs must be integers
    for tid in track_ids:
        assert isinstance(tid, int)


@pytest.mark.unit
def test_bytetrack_maintains_tracks_through_occlusion() -> None:
    """Verify track identity is preserved when an object is temporarily occluded for several frames."""
    tracker = ByteTracker(track_thresh=0.5, max_age=5, min_hits=1)

    box = np.array([[100.0, 100.0, 150.0, 150.0]])
    conf = np.array([0.9])

    # Frame 1: Detection present
    tracks1 = tracker.update(box, conf)
    assert len(tracks1) == 1
    orig_id = tracks1[0].track_id

    # Frame 2 & 3: Occlusion (empty detections)
    empty_boxes = np.empty((0, 4))
    empty_confs = np.empty((0,))
    tracker.update(empty_boxes, empty_confs)
    tracker.update(empty_boxes, empty_confs)

    # Frame 4: Object reappears at nearby position
    reappeared_box = np.array([[104.0, 103.0, 154.0, 153.0]])
    tracks4 = tracker.update(reappeared_box, conf)

    assert len(tracks4) == 1
    assert tracks4[0].track_id == orig_id


@pytest.mark.unit
def test_bytetrack_handles_empty_detections() -> None:
    """Verify tracker updates properly when zero detections are received."""
    tracker = ByteTracker()
    empty_boxes = np.empty((0, 4))
    empty_confs = np.empty((0,))

    tracks = tracker.update(empty_boxes, empty_confs)
    assert isinstance(tracks, list)
    assert len(tracks) == 0


@pytest.mark.unit
def test_bytetrack_removes_old_tracks() -> None:
    """Verify lost tracks are removed after exceeding max_age frames without observation."""
    tracker = ByteTracker(track_thresh=0.5, max_age=3, min_hits=1)

    box = np.array([[50.0, 50.0, 90.0, 90.0]])
    conf = np.array([0.9])

    tracks = tracker.update(box, conf)
    assert len(tracks) == 1

    empty_boxes = np.empty((0, 4))
    empty_confs = np.empty((0,))

    # Progress past max_age frames
    for _ in range(4):
        tracker.update(empty_boxes, empty_confs)

    # Reappear at original position; should be considered a new track, not the purged old one
    tracks_after = tracker.update(box, conf)
    assert len(tracks_after) == 1
    assert tracks_after[0].track_id != tracks[0].track_id


@pytest.mark.unit
def test_bytetrack_id_switch_counting() -> None:
    """Verify ID switch counter increments when ground-truth identity swaps or tracks switch."""
    metrics = TrackingMetrics()

    # Frame 1: GT 1 matches Pred 10, GT 2 matches Pred 20
    gt_ids = [1, 2]
    gt_boxes = np.array([[10, 10, 50, 50], [100, 100, 150, 150]], dtype=float)
    pred_ids = [10, 20]
    pred_boxes = np.array([[10, 10, 50, 50], [100, 100, 150, 150]], dtype=float)
    metrics.update(gt_ids, gt_boxes, pred_ids, pred_boxes)
    assert metrics.id_switch_count == 0

    # Frame 2: Prediction swapped (GT 1 now matches Pred 20, GT 2 matches Pred 10)
    swapped_pred_ids = [20, 10]
    metrics.update(gt_ids, gt_boxes, swapped_pred_ids, pred_boxes)
    assert metrics.id_switch_count >= 1


@pytest.mark.unit
def test_botsort_with_appearance_features() -> None:
    """Verify BoTSORTracker associates tracks using appearance feature embeddings."""
    tracker = BoTSORTracker(
        track_thresh=0.4,
        appearance_thresh=0.3,
        appearance_weight=0.7,
        gmc_method=GMCMethod.NONE,
        min_hits=1,
    )

    bboxes = np.array([[100.0, 100.0, 160.0, 160.0]])
    confs = np.array([0.9])
    feat1 = np.ones((1, 128), dtype=np.float32)

    # Step 1: Initialise track with appearance feature
    t1 = tracker.update(bboxes, confs, features=feat1)
    assert len(t1) == 1
    track_id = t1[0].track_id

    # Step 2: Next frame with matching feature
    feat2 = np.ones((1, 128), dtype=np.float32)
    t2 = tracker.update(bboxes + 2.0, confs, features=feat2)
    assert len(t2) == 1
    assert t2[0].track_id == track_id


@pytest.mark.unit
def test_botsort_fallback_without_reid() -> None:
    """Verify BoTSORTracker functions seamlessly without appearance features (features=None)."""
    tracker = BoTSORTracker(
        track_thresh=0.4,
        gmc_method=GMCMethod.NONE,
        min_hits=1,
    )

    bboxes = np.array([[200.0, 200.0, 260.0, 260.0]])
    confs = np.array([0.88])

    tracks = tracker.update(bboxes, confs, features=None)
    assert len(tracks) == 1
    assert tracks[0].track_id > 0


@pytest.mark.unit
def test_kalman_predict_update_cycle() -> None:
    """Verify KalmanBoxTracker state prediction and measurement update cycles."""
    initial_bbox = np.array([50.0, 50.0, 100.0, 120.0])
    tracker = KalmanBoxTracker(bbox=initial_bbox)

    # Predict advances state
    pred_bbox = tracker.predict()
    assert len(pred_bbox) == 4
    assert tracker.age == 1
    assert tracker.time_since_update == 1

    # Update incorporates new measurement
    meas_bbox = np.array([52.0, 51.0, 102.0, 121.0])
    tracker.update(meas_bbox)
    assert tracker.hits == 1
    assert tracker.time_since_update == 0

    est_bbox = tracker.get_bbox()
    assert len(est_bbox) == 4
    # Estimated box should be close to measurement
    assert est_bbox[0] == pytest.approx(52.0, abs=5.0)


@pytest.mark.unit
def test_tracking_ids_are_anonymous() -> None:
    """Verify tracking outputs only contain anonymous integer IDs without any PII fields."""
    tracker = ByteTracker(track_thresh=0.5, min_hits=1)
    bboxes = np.array([[10.0, 20.0, 80.0, 120.0]])
    confs = np.array([0.9])

    tracks = tracker.update(bboxes, confs, class_names=["person"])
    assert len(tracks) == 1
    track = tracks[0]

    # Verify ID is an integer
    assert isinstance(track.track_id, int)
    # Check that no PII attributes exist
    forbidden_attrs = ["name", "face_id", "ssn", "biometric", "identity", "user_id"]
    for attr in forbidden_attrs:
        assert not hasattr(track, attr)
    # Verify is_prediction is True
    assert track.is_prediction is True


@pytest.mark.unit
def test_track_fragmentation_metrics() -> None:
    """Verify tracking metrics correctly tally track fragmentations when a track drops and resumes."""
    metrics = TrackingMetrics()

    # Frame 1: GT 1 detected as Track 100
    metrics.update([1], np.array([[10, 10, 50, 50]]), [100], np.array([[10, 10, 50, 50]]))
    # Frame 2: Missing (miss)
    metrics.update([1], np.array([[10, 10, 50, 50]]), [], np.empty((0, 4)))
    # Frame 3: Resumes with same Track 100
    metrics.update([1], np.array([[10, 10, 50, 50]]), [100], np.array([[10, 10, 50, 50]]))

    assert metrics.fragmentation_count >= 1


@pytest.mark.unit
def test_crowded_scene_tracking() -> None:
    """Verify tracking scalability and performance with 20+ concurrent objects in a crowded frame."""
    tracker = ByteTracker(track_thresh=0.3, min_hits=1)

    np.random.seed(123)
    # Generate 25 distinct object bboxes
    n_objects = 25
    x1 = np.random.uniform(0, 500, size=n_objects)
    y1 = np.random.uniform(0, 400, size=n_objects)
    bboxes = np.column_stack([x1, y1, x1 + 40, y1 + 60])
    confs = np.random.uniform(0.7, 0.99, size=n_objects)

    # Frame 1: Initialise all 25 tracks
    tracks1 = tracker.update(bboxes, confs)
    assert len(tracks1) == n_objects
    assert len({t.track_id for t in tracks1}) == n_objects

    # Frame 2: Slight motion
    moved_bboxes = bboxes + np.random.uniform(-2, 2, size=bboxes.shape)
    tracks2 = tracker.update(moved_bboxes, confs)
    assert len(tracks2) == n_objects


@pytest.mark.unit
def test_mota_motp_computation() -> None:
    """Verify MOTA and MOTP evaluation metrics compute correctly for perfect and imperfect tracking."""
    metrics = TrackingMetrics()

    # Frame 1: Perfect match (IoU = 1.0)
    gt_ids = [1, 2]
    boxes = np.array([[10.0, 10.0, 50.0, 50.0], [100.0, 100.0, 150.0, 150.0]])
    metrics.update(gt_ids, boxes, gt_ids, boxes)

    assert metrics.mota == pytest.approx(1.0)
    assert metrics.motp == pytest.approx(1.0)

    # Frame 2: One miss and one false positive
    metrics.update(
        gt_ids=[1, 2],
        gt_boxes=boxes,
        pred_ids=[1, 99],  # GT 2 missed, Pred 99 is false positive
        pred_boxes=np.array([[10.0, 10.0, 50.0, 50.0], [200.0, 200.0, 250.0, 250.0]]),
    )

    # Total GT = 4, misses = 1, false_positives = 1 -> MOTA = 1 - (1+1)/4 = 0.5
    assert metrics.mota == pytest.approx(0.5)
    assert 0.0 < metrics.motp <= 1.0
