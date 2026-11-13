"""CAMserv tracking package — multi-object tracking with anonymous IDs.

Provides ByteTrack and BoT-SORT trackers for real-time multi-object tracking.
All track IDs are anonymous incrementing integers — no identity inference
is performed or permitted.

Typical usage::

    from camserv.tracking.bytetrack import ByteTracker
    from camserv.tracking.botsort import BoTSORTracker
    from camserv.tracking.metrics import TrackingMetrics
"""

from camserv.tracking.bytetrack import ByteTracker
from camserv.tracking.botsort import BoTSORTracker
from camserv.tracking.kalman import KalmanBoxTracker
from camserv.tracking.metrics import TrackingMetrics

__all__ = [
    "ByteTracker",
    "BoTSORTracker",
    "KalmanBoxTracker",
    "TrackingMetrics",
]
