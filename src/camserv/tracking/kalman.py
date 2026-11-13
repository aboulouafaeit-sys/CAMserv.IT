"""Kalman filter for bounding-box tracking.

Implements a constant-velocity Kalman filter operating on the bounding-box
state vector ``[x, y, s, r, dx, dy, ds]`` where *(x, y)* is the centre,
*s* is the scale (area), *r* is the aspect ratio, and the *d** terms are
the corresponding velocities.

This module is self-contained and does **not** depend on filterpy so that
the tracker package has fewer mandatory dependencies.
"""

from __future__ import annotations

import numpy as np
import structlog

__all__ = ["KalmanBoxTracker"]

logger = structlog.get_logger(__name__)

# Dimensionality constants
_DIM_Z = 4  # measurement: [x, y, s, r]
_DIM_X = 7  # state: [x, y, s, r, dx, dy, ds]


def _bbox_to_z(bbox: np.ndarray) -> np.ndarray:
    """Convert ``[x1, y1, x2, y2]`` to measurement ``[cx, cy, s, r]``.

    Parameters
    ----------
    bbox:
        Bounding box in ``[x1, y1, x2, y2]`` format.

    Returns
    -------
    np.ndarray
        Measurement vector ``[cx, cy, s, r]``.
    """
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    cx = bbox[0] + w / 2.0
    cy = bbox[1] + h / 2.0
    s = w * h  # scale = area
    r = w / max(h, 1e-6)  # aspect ratio
    return np.array([cx, cy, s, r], dtype=np.float64)


def _z_to_bbox(z: np.ndarray) -> np.ndarray:
    """Convert measurement ``[cx, cy, s, r]`` back to ``[x1, y1, x2, y2]``.

    Parameters
    ----------
    z:
        Measurement vector ``[cx, cy, s, r]``.

    Returns
    -------
    np.ndarray
        Bounding box in ``[x1, y1, x2, y2]`` format.
    """
    w = np.sqrt(max(z[2] * z[3], 1e-6))
    h = max(z[2] / max(w, 1e-6), 1e-6)
    return np.array(
        [z[0] - w / 2.0, z[1] - h / 2.0, z[0] + w / 2.0, z[1] + h / 2.0],
        dtype=np.float64,
    )


class KalmanBoxTracker:
    """Kalman filter tracker for a single bounding box.

    The state vector is::

        x = [cx, cy, s, r, dx, dy, ds]^T

    where *r* (aspect ratio) is assumed constant between updates.

    Parameters
    ----------
    bbox:
        Initial bounding box ``[x1, y1, x2, y2]``.
    process_noise_scale:
        Multiplier for process noise covariance diagonal.
    measurement_noise_scale:
        Multiplier for measurement noise covariance diagonal.
    """

    def __init__(
        self,
        bbox: np.ndarray,
        process_noise_scale: float = 1.0,
        measurement_noise_scale: float = 1.0,
    ) -> None:
        # State transition matrix (constant-velocity model)
        self.F = np.eye(_DIM_X, dtype=np.float64)
        self.F[0, 4] = 1.0  # cx += dx
        self.F[1, 5] = 1.0  # cy += dy
        self.F[2, 6] = 1.0  # s  += ds

        # Measurement matrix (we observe [cx, cy, s, r])
        self.H = np.zeros((_DIM_Z, _DIM_X), dtype=np.float64)
        self.H[:_DIM_Z, :_DIM_Z] = np.eye(_DIM_Z)

        # Process noise covariance
        self.Q = np.eye(_DIM_X, dtype=np.float64) * process_noise_scale
        # Give higher noise to velocities
        self.Q[4, 4] *= 0.01
        self.Q[5, 5] *= 0.01
        self.Q[6, 6] *= 0.0001

        # Measurement noise covariance
        self.R = np.eye(_DIM_Z, dtype=np.float64) * measurement_noise_scale
        self.R[2, 2] *= 10.0  # scale measurement is noisier
        self.R[3, 3] *= 10.0  # aspect ratio measurement is noisier

        # Initial state
        z = _bbox_to_z(bbox)
        self.x = np.zeros((_DIM_X, 1), dtype=np.float64)
        self.x[:_DIM_Z, 0] = z

        # State covariance — high initial uncertainty for velocities
        self.P = np.eye(_DIM_X, dtype=np.float64)
        self.P[4:, 4:] *= 1000.0  # velocity uncertainty
        self.P *= 10.0

        self.time_since_update: int = 0
        self.hits: int = 0
        self.hit_streak: int = 0
        self.age: int = 0

    # ------------------------------------------------------------------
    # Core Kalman operations
    # ------------------------------------------------------------------

    def predict(self) -> np.ndarray:
        """Advance state by one time-step and return predicted bbox.

        Returns
        -------
        np.ndarray
            Predicted bounding box ``[x1, y1, x2, y2]``.
        """
        # Enforce non-negative area
        if self.x[6, 0] + self.x[2, 0] <= 0:
            self.x[6, 0] *= 0.0

        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q

        self.age += 1
        self.time_since_update += 1
        self.hit_streak = 0 if self.time_since_update > 0 else self.hit_streak

        return self.get_bbox()

    def update(self, bbox: np.ndarray) -> None:
        """Update state with an observed bounding box.

        Parameters
        ----------
        bbox:
            Observed bounding box ``[x1, y1, x2, y2]``.
        """
        z = _bbox_to_z(bbox).reshape((_DIM_Z, 1))

        # Innovation
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R

        # Kalman gain
        try:
            K = self.P @ self.H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            logger.warning("kalman_singular_innovation_covariance")
            return

        self.x = self.x + K @ y
        I_KH = np.eye(_DIM_X) - K @ self.H
        # Joseph form for numerical stability
        self.P = I_KH @ self.P @ I_KH.T + K @ self.R @ K.T

        self.time_since_update = 0
        self.hits += 1
        self.hit_streak += 1

    # ------------------------------------------------------------------
    # Bounding-box helpers
    # ------------------------------------------------------------------

    def get_bbox(self) -> np.ndarray:
        """Return current state as ``[x1, y1, x2, y2]``.

        Returns
        -------
        np.ndarray
            Bounding box derived from current state estimate.
        """
        return _z_to_bbox(self.x[:_DIM_Z, 0])

    def get_state(self) -> np.ndarray:
        """Return the full state vector (7,).

        Returns
        -------
        np.ndarray
            Copy of internal state ``[cx, cy, s, r, dx, dy, ds]``.
        """
        return self.x[:, 0].copy()

    # ------------------------------------------------------------------
    # Gating
    # ------------------------------------------------------------------

    def mahalanobis_distance(self, bbox: np.ndarray) -> float:
        """Compute Mahalanobis distance between predicted state and a bbox.

        Useful for gating unlikely associations before running the full
        assignment solver.

        Parameters
        ----------
        bbox:
            Candidate bounding box ``[x1, y1, x2, y2]``.

        Returns
        -------
        float
            Squared Mahalanobis distance.  Lower is better.
        """
        z = _bbox_to_z(bbox).reshape((_DIM_Z, 1))
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R

        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            logger.warning("kalman_singular_covariance_mahalanobis")
            return float("inf")

        d: float = float(np.squeeze(y.T @ S_inv @ y))
        return d

    def gating_distance(
        self,
        bbox: np.ndarray,
        threshold: float = 9.4877,  # chi-squared 95 % for 4 DOF
    ) -> tuple[float, bool]:
        """Compute Mahalanobis distance and whether it passes the gate.

        Parameters
        ----------
        bbox:
            Candidate bounding box ``[x1, y1, x2, y2]``.
        threshold:
            Gating threshold (chi-squared value). Default is 95 % for 4 DOF.

        Returns
        -------
        tuple[float, bool]
            ``(distance, passes_gate)``
        """
        d = self.mahalanobis_distance(bbox)
        return d, d < threshold
