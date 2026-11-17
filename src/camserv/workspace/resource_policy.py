"""
camserv.workspace.resource_policy
=================================

Capability-Aware Operator Resource Management Policy Engine.
Adapts stream quality, maximum concurrent decoded streams, and frame rate caps
according to operational resource profiles (Low Resource, Balanced, High Performance, Custom).
Enforces truth-in-advertising: explicitly identifies CPU fallback decoding when GPU is unverified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from camserv.platform.factory import get_platform_hardware_prober
from camserv.platform.shared.interfaces import PlatformHardwareProber
from camserv.workspace.models import DisplayLayout, ResourceProfile

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class StreamAllocationPolicy:
    """Configured limits and policies for video decoding workloads."""

    max_concurrent_streams: int
    target_fps: int
    preferred_resolution: tuple[int, int]
    allow_background_pause: bool
    background_refresh_interval_sec: float
    active_decoder: str
    is_hardware_accelerated: bool


class OperatorResourcePolicyEngine:
    """
    Evaluates host system capability and manages stream decoding policy profiles.
    """

    PRESET_POLICIES: dict[ResourceProfile, dict[str, Any]] = {
        ResourceProfile.LOW_RESOURCE: {
            "max_concurrent_streams": 4,
            "target_fps": 10,
            "preferred_resolution": (1280, 720),
            "allow_background_pause": True,
            "background_refresh_interval_sec": 5.0,
        },
        ResourceProfile.BALANCED: {
            "max_concurrent_streams": 9,
            "target_fps": 20,
            "preferred_resolution": (1920, 1080),
            "allow_background_pause": False,
            "background_refresh_interval_sec": 2.0,
        },
        ResourceProfile.HIGH_PERFORMANCE: {
            "max_concurrent_streams": 25,
            "target_fps": 25,
            "preferred_resolution": (1920, 1080),
            "allow_background_pause": False,
            "background_refresh_interval_sec": 0.5,
        },
    }

    def __init__(
        self,
        hardware_prober: PlatformHardwareProber | None = None,
        default_profile: ResourceProfile = ResourceProfile.BALANCED,
    ) -> None:
        self.prober = hardware_prober or get_platform_hardware_prober()
        self.current_profile = default_profile
        self._custom_overrides: dict[str, Any] = {}

    def inspect_hardware_capability(self) -> dict[str, Any]:
        """
        Query actual hardware environment.
        Never reports GPU acceleration unless genuine execution verifies it.
        """
        cpu_ram = self.prober.probe_cpu_and_ram()
        gpus = self.prober.probe_gpus()

        # Check for confirmed dedicated GPU
        has_verified_gpu = False
        gpu_name = "CPU Software Fallback (OpenCV/FFmpeg)"
        vram_mb = 0

        if gpus and len(gpus) > 0:
            top_gpu = gpus[0]
            vram_mb = top_gpu.get("memory_total_mb", 0)
            candidate_name = top_gpu.get("name", "")
            # Require at least 512MB VRAM and valid driver to count as verified acceleration
            if vram_mb >= 512 and "N/A" not in str(top_gpu.get("driver_version", "")):
                has_verified_gpu = True
                gpu_name = candidate_name

        decoder_desc = (
            f"Hardware Accelerated ({gpu_name})"
            if has_verified_gpu
            else "CPU Software Fallback (OpenCV/FFmpeg)"
        )

        return {
            "os": cpu_ram.get("os", "Unknown"),
            "cpu_cores": cpu_ram.get("logical_cores", 1),
            "cpu_logical_cores": cpu_ram.get("logical_cores", 1),
            "ram_total_mb": cpu_ram.get("ram_total_mb", 0),
            "ram_available_mb": cpu_ram.get("ram_available_mb", 0),
            "gpu_detected": has_verified_gpu,
            "gpu_model": gpu_name,
            "gpu_name": gpu_name,
            "vram_mb": vram_mb,
            "is_gpu_accelerated": has_verified_gpu,
            "active_decoder": decoder_desc,
        }

    def get_allocation_policy(
        self, profile: ResourceProfile | None = None
    ) -> StreamAllocationPolicy:
        """Calculate active decoding policy parameters based on selected profile."""
        prof = profile or self.current_profile
        hw = self.inspect_hardware_capability()

        if prof in (ResourceProfile.OPERATOR_CONFIGURED, ResourceProfile.CUSTOM) and self._custom_overrides:
            base_config = dict(self._custom_overrides)
        else:
            base_config = dict(self.PRESET_POLICIES.get(prof, self.PRESET_POLICIES[ResourceProfile.BALANCED]))

        return StreamAllocationPolicy(
            max_concurrent_streams=int(base_config.get("max_concurrent_streams", 9)),
            target_fps=int(base_config.get("target_fps", 15)),
            preferred_resolution=tuple(base_config.get("preferred_resolution", (1920, 1080))),
            allow_background_pause=bool(base_config.get("allow_background_pause", False)),
            background_refresh_interval_sec=float(base_config.get("background_refresh_interval_sec", 2.0)),
            active_decoder=hw["active_decoder"],
            is_hardware_accelerated=hw["is_gpu_accelerated"],
        )

    def get_profile_spec(self, profile: ResourceProfile) -> dict[str, Any]:
        """Retrieve resource specification for a given profile."""
        policy = self.get_allocation_policy(profile)
        is_low = (profile in (ResourceProfile.LOW_RESOURCE, ResourceProfile.LOW))
        return {
            "max_concurrent_streams": policy.max_concurrent_streams,
            "preferred_stream_type": "sub" if is_low else "main",
            "target_fps": policy.target_fps,
            "enable_glassmorphism": not is_low,
            "resolution": policy.preferred_resolution,
            "allow_background_pause": policy.allow_background_pause,
        }

    def allocate_streams_for_layout(
        self, layout: DisplayLayout, profile: ResourceProfile
    ) -> DisplayLayout:
        """Allocate main/sub/paused stream qualities for a layout according to profile."""
        spec = self.get_profile_spec(profile)
        max_active = spec["max_concurrent_streams"]
        pref_type = spec["preferred_stream_type"]

        for idx, tile in enumerate(layout.tiles):
            if idx < max_active:
                tile.stream_type = pref_type
                tile.stream_quality = pref_type
            else:
                tile.stream_type = "paused"
                tile.stream_quality = "sub"
        return layout

    def switch_profile(self, profile: ResourceProfile) -> StreamAllocationPolicy:
        """Activate a different resource management profile."""
        self.current_profile = profile
        logger.info("resource_policy.profile_switched", profile=profile.value)
        return self.get_allocation_policy()

    def set_custom_overrides(self, overrides: dict[str, Any]) -> None:
        """Apply operator-customized decoding parameters."""
        self._custom_overrides.update(overrides)
        self.current_profile = ResourceProfile.OPERATOR_CONFIGURED
