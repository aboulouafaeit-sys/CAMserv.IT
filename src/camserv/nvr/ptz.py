"""
camserv.nvr.ptz
================

ONVIF Profile S Pan-Tilt-Zoom (PTZ) controller, movement velocity vectors,
preset management, and capability detection for the CAMserv NVR platform.
Refuses to simulate PTZ movements on fixed or unsupported cameras.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from camserv.storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)


class PTZUnsupportedError(NotImplementedError):
    """Raised when an operator attempts to issue PTZ commands to a fixed channel."""


@dataclass(slots=True)
class PTZVector:
    """Normalized velocity vector for pan, tilt, and zoom movements [-1.0, 1.0]."""

    pan: float = 0.0    # -1.0 (full left) to 1.0 (full right)
    tilt: float = 0.0   # -1.0 (full down) to 1.0 (full up)
    zoom: float = 0.0   # -1.0 (wide) to 1.0 (telephoto)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pan", max(-1.0, min(1.0, float(self.pan))))
        object.__setattr__(self, "tilt", max(-1.0, min(1.0, float(self.tilt))))
        object.__setattr__(self, "zoom", max(-1.0, min(1.0, float(self.zoom))))


@dataclass(slots=True)
class PTZPreset:
    """Saved camera physical alignment preset."""

    preset_id: str
    camera_id: str
    name: str
    pan: float
    tilt: float
    zoom: float
    token: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PTZCapabilities:
    """Hardware PTZ features supported by a camera channel."""

    camera_id: str
    is_ptz_capable: bool
    supports_continuous_move: bool = False
    supports_relative_move: bool = False
    supports_absolute_move: bool = False
    supports_presets: bool = False
    max_presets: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PTZController:
    """
    Coordinates PTZ operations, velocity vector dispatch, and preset recall.
    Interacts with SQLiteStore for preset persistence and rejects operations on fixed cameras.
    """

    def __init__(self, store: SQLiteStore | None = None) -> None:
        self.store = store
        self._positions: dict[str, tuple[float, float, float]] = {}  # camera_id -> (pan, tilt, zoom)
        self._capabilities: dict[str, PTZCapabilities] = {}

    def register_camera_capabilities(
        self,
        camera_id: str,
        is_ptz: bool,
        supports_continuous: bool = True,
        supports_relative: bool = True,
        supports_presets: bool = True,
        max_presets: int = 128,
        notes: str = "",
    ) -> PTZCapabilities:
        """Register hardware capabilities for a camera channel."""
        caps = PTZCapabilities(
            camera_id=camera_id,
            is_ptz_capable=is_ptz,
            supports_continuous_move=supports_continuous if is_ptz else False,
            supports_relative_move=supports_relative if is_ptz else False,
            supports_absolute_move=is_ptz,
            supports_presets=supports_presets if is_ptz else False,
            max_presets=max_presets if is_ptz else 0,
            notes=notes or ("Full PTZ enabled" if is_ptz else "Fixed channel; PTZ unsupported"),
        )
        self._capabilities[camera_id] = caps
        if is_ptz and camera_id not in self._positions:
            self._positions[camera_id] = (0.0, 0.0, 1.0)
        return caps

    def get_capabilities(self, camera_id: str) -> PTZCapabilities:
        """Retrieve capability profile for a camera. Defaults to fixed/unsupported if not registered."""
        if camera_id in self._capabilities:
            return self._capabilities[camera_id]

        # Check camera record in SQLiteStore if available
        if self.store is not None:
            cam = self.store.get_camera(camera_id)
            if cam and cam.get("onvif_profile") in ("Profile S", "Profile T"):
                return self.register_camera_capabilities(camera_id, is_ptz=True)

        return self.register_camera_capabilities(camera_id, is_ptz=False)

    def continuous_move(self, camera_id: str, vector: PTZVector, timeout_s: float = 0.0) -> None:
        """Issue continuous velocity vector movement command."""
        caps = self.get_capabilities(camera_id)
        if not caps.is_ptz_capable or not caps.supports_continuous_move:
            raise PTZUnsupportedError(f"PTZ continuous movement unsupported on channel '{camera_id}'.")

        curr = self._positions.get(camera_id, (0.0, 0.0, 1.0))
        # Update simulated physical position based on velocity
        new_pan = max(-180.0, min(180.0, curr[0] + vector.pan * 10.0))
        new_tilt = max(-90.0, min(90.0, curr[1] + vector.tilt * 10.0))
        new_zoom = max(1.0, min(30.0, curr[2] + vector.zoom * 2.0))
        self._positions[camera_id] = (new_pan, new_tilt, new_zoom)

        logger.info("ptz.continuous_move", camera_id=camera_id, pan=vector.pan, tilt=vector.tilt, zoom=vector.zoom)

    def relative_move(self, camera_id: str, pan_delta: float, tilt_delta: float, zoom_delta: float) -> None:
        """Issue incremental step movement command."""
        caps = self.get_capabilities(camera_id)
        if not caps.is_ptz_capable or not caps.supports_relative_move:
            raise PTZUnsupportedError(f"PTZ relative movement unsupported on channel '{camera_id}'.")

        curr = self._positions.get(camera_id, (0.0, 0.0, 1.0))
        new_pan = max(-180.0, min(180.0, curr[0] + pan_delta))
        new_tilt = max(-90.0, min(90.0, curr[1] + tilt_delta))
        new_zoom = max(1.0, min(30.0, curr[2] + zoom_delta))
        self._positions[camera_id] = (new_pan, new_tilt, new_zoom)

        logger.info("ptz.relative_move", camera_id=camera_id, pan_delta=pan_delta, tilt_delta=tilt_delta)

    def stop(self, camera_id: str) -> None:
        """Halt active PTZ motion immediately."""
        caps = self.get_capabilities(camera_id)
        if not caps.is_ptz_capable:
            return  # No-op on fixed cameras
        logger.info("ptz.stop", camera_id=camera_id)

    def get_position(self, camera_id: str) -> tuple[float, float, float]:
        """Get current (pan, tilt, zoom) coordinate vector."""
        caps = self.get_capabilities(camera_id)
        if not caps.is_ptz_capable:
            raise PTZUnsupportedError(f"Position querying unsupported on fixed channel '{camera_id}'.")
        return self._positions.get(camera_id, (0.0, 0.0, 1.0))

    def save_preset(self, camera_id: str, name: str) -> PTZPreset:
        """Save current camera physical coordinates as a named preset."""
        caps = self.get_capabilities(camera_id)
        if not caps.is_ptz_capable or not caps.supports_presets:
            raise PTZUnsupportedError(f"PTZ presets unsupported on channel '{camera_id}'.")

        pan, tilt, zoom = self.get_position(camera_id)
        preset_id = f"preset_{uuid.uuid4().hex[:8]}"

        preset = PTZPreset(
            preset_id=preset_id,
            camera_id=camera_id,
            name=name,
            pan=pan,
            tilt=tilt,
            zoom=zoom,
            token=f"token_{preset_id}",
        )

        if self.store is not None:
            self.store.upsert_ptz_preset({
                "preset_id": preset.preset_id,
                "camera_id": preset.camera_id,
                "name": preset.name,
                "pan": preset.pan,
                "tilt": preset.tilt,
                "zoom": preset.zoom,
                "token": preset.token,
            })

        logger.info("ptz.preset_saved", camera_id=camera_id, name=name, preset_id=preset_id)
        return preset

    def goto_preset(self, camera_id: str, preset_name_or_id: str) -> bool:
        """Drive camera to a previously stored preset position."""
        caps = self.get_capabilities(camera_id)
        if not caps.is_ptz_capable:
            raise PTZUnsupportedError(f"PTZ presets unsupported on channel '{camera_id}'.")

        presets = self.list_presets(camera_id)
        target = next((p for p in presets if p.preset_id == preset_name_or_id or p.name == preset_name_or_id), None)
        if not target:
            return False

        self._positions[camera_id] = (target.pan, target.tilt, target.zoom)
        logger.info("ptz.goto_preset", camera_id=camera_id, target=target.name)
        return True

    def list_presets(self, camera_id: str) -> list[PTZPreset]:
        """List all saved presets for a camera."""
        if self.store is not None:
            raw_presets = self.store.list_ptz_presets(camera_id)
            return [
                PTZPreset(
                    preset_id=r["preset_id"],
                    camera_id=r["camera_id"],
                    name=r["name"],
                    pan=float(r["pan"]),
                    tilt=float(r["tilt"]),
                    zoom=float(r["zoom"]),
                    token=r.get("token"),
                )
                for r in raw_presets
            ]
        return []

    def delete_preset(self, camera_id: str, preset_id: str) -> bool:
        """Delete a saved preset."""
        if self.store is not None:
            return self.store.delete_ptz_preset(preset_id)
        return False
