"""
camserv.platform.tiers
======================

Adaptive Operating Tiers for CAMserv Universal Hardware Compatibility.
Provides tailored execution profiles spanning low-end CPU-only machines to
multi-stream enterprise servers, ensuring mathematical reliability and strict
privacy preservation across all hardware classes.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

import structlog

from camserv.platform.hardware import HardwareProfile

logger = structlog.get_logger(__name__)


class HardwareTier(enum.Enum):
    """Adaptive hardware operating classes."""

    TIER_1_LOW_END = "tier_1_low_end"        # Budget laptops, mini-PCs, Intel Celeron/i3, 4-8GB RAM, CPU-only
    TIER_2_STANDARD = "tier_2_standard"      # Standard desktops, Core i5/Ryzen 5, 8-16GB RAM, integrated/entry GPU
    TIER_3_WORKSTATION = "tier_3_workstation"# Workstations, RTX 3060/4060+, 16-64GB RAM, dedicated CUDA VRAM
    TIER_4_ENTERPRISE = "tier_4_enterprise"  # Servers, multi-GPU, A100/A5000/H100, 64GB+ RAM, rackmount NVR


@dataclass(slots=True)
class TierConfiguration:
    """Operational constraints, model sizing, and processing limits for an operating tier."""

    tier: HardwareTier
    display_name: str
    target_resolution: tuple[int, int]
    target_fps: int
    max_concurrent_streams: int
    model_family: str
    inference_backend: str
    batch_size: int
    enable_half_precision: bool
    enable_int8_quantization: bool
    enable_reid_features: bool
    enable_temporal_dense_graph: bool
    enable_privacy_masking: bool  # ALWAYS True: Privacy safeguards cannot be disabled!
    memory_ceiling_mb: int
    queue_capacity_frames: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a structured dictionary."""
        return {
            "tier": self.tier.value,
            "display_name": self.display_name,
            "target_resolution": f"{self.target_resolution[0]}x{self.target_resolution[1]}",
            "target_fps": self.target_fps,
            "max_concurrent_streams": self.max_concurrent_streams,
            "model_family": self.model_family,
            "inference_backend": self.inference_backend,
            "batch_size": self.batch_size,
            "enable_half_precision": self.enable_half_precision,
            "enable_int8_quantization": self.enable_int8_quantization,
            "enable_reid_features": self.enable_reid_features,
            "enable_temporal_dense_graph": self.enable_temporal_dense_graph,
            "enable_privacy_masking": self.enable_privacy_masking,
            "memory_ceiling_mb": self.memory_ceiling_mb,
            "queue_capacity_frames": self.queue_capacity_frames,
            "description": self.description,
        }


class TierPolicyEngine:
    """Evaluates host hardware metrics and assigns the optimal operating tier."""

    TIER_PRESETS: dict[HardwareTier, TierConfiguration] = {
        HardwareTier.TIER_1_LOW_END: TierConfiguration(
            tier=HardwareTier.TIER_1_LOW_END,
            display_name="Tier 1: Resource-Constrained / CPU-Only",
            target_resolution=(480, 480),
            target_fps=8,
            max_concurrent_streams=2,
            model_family="yolov8n-int8",
            inference_backend="onnx_cpu",
            batch_size=1,
            enable_half_precision=False,
            enable_int8_quantization=True,
            enable_reid_features=False,         # Pure IoU tracking to eliminate memory overhead
            enable_temporal_dense_graph=False,   # Linear sliding window kinematics
            enable_privacy_masking=True,         # Invariant: Privacy cannot fail
            memory_ceiling_mb=1024,
            queue_capacity_frames=8,
            description="Optimized for entry-level PCs and edge devices without discrete GPUs.",
        ),
        HardwareTier.TIER_2_STANDARD: TierConfiguration(
            tier=HardwareTier.TIER_2_STANDARD,
            display_name="Tier 2: Standard Desktop / Integrated Graphics",
            target_resolution=(640, 640),
            target_fps=15,
            max_concurrent_streams=4,
            model_family="yolov8s",
            inference_backend="onnx_cpu",
            batch_size=2,
            enable_half_precision=False,
            enable_int8_quantization=False,
            enable_reid_features=True,
            enable_temporal_dense_graph=True,
            enable_privacy_masking=True,
            memory_ceiling_mb=2560,
            queue_capacity_frames=16,
            description="Balanced profile for commercial office workstations and standard PCs.",
        ),
        HardwareTier.TIER_3_WORKSTATION: TierConfiguration(
            tier=HardwareTier.TIER_3_WORKSTATION,
            display_name="Tier 3: GPU Workstation / Dedicated CUDA",
            target_resolution=(640, 640),
            target_fps=25,
            max_concurrent_streams=8,
            model_family="yolov8s-fp16",
            inference_backend="onnx_gpu",
            batch_size=4,
            enable_half_precision=True,
            enable_int8_quantization=False,
            enable_reid_features=True,
            enable_temporal_dense_graph=True,
            enable_privacy_masking=True,
            memory_ceiling_mb=6144,
            queue_capacity_frames=32,
            description="Full-capability GPU acceleration for dedicated surveillance monitoring.",
        ),
        HardwareTier.TIER_4_ENTERPRISE: TierConfiguration(
            tier=HardwareTier.TIER_4_ENTERPRISE,
            display_name="Tier 4: Enterprise Server / High-Density NVR",
            target_resolution=(1280, 1280),
            target_fps=30,
            max_concurrent_streams=24,
            model_family="yolov8m-tensorrt",
            inference_backend="tensorrt",
            batch_size=8,
            enable_half_precision=True,
            enable_int8_quantization=False,
            enable_reid_features=True,
            enable_temporal_dense_graph=True,
            enable_privacy_masking=True,
            memory_ceiling_mb=16384,
            queue_capacity_frames=64,
            description="High-density multi-channel processing for enterprise clusters and servers.",
        ),
    }

    @classmethod
    def resolve_tier(cls, profile: HardwareProfile) -> TierConfiguration:
        """Map a hardware profile to the safest, most performant operating tier."""
        total_ram = profile.ram_total_mb
        cores = profile.cpu_cores_logical
        gpus = profile.gpus
        has_cuda = profile.has_cuda

        # Tier 4: Enterprise (High VRAM + 32GB+ RAM + Multi-core / TensorRT)
        if has_cuda and gpus and gpus[0].memory_total_mb >= 12000 and total_ram >= 32000 and cores >= 16:
            tier = HardwareTier.TIER_4_ENTERPRISE
        # Tier 3: Workstation (Dedicated GPU >= 4GB VRAM + 16GB+ RAM)
        elif has_cuda and gpus and gpus[0].memory_total_mb >= 4000 and total_ram >= 12000:
            tier = HardwareTier.TIER_3_WORKSTATION
        # Tier 2: Standard (8GB+ RAM, 4+ cores, or entry-level GPU)
        elif total_ram >= 7500 and cores >= 4:
            tier = HardwareTier.TIER_2_STANDARD
        # Tier 1: Low-End (<8GB RAM or <=2 cores or CPU-only constrained)
        else:
            tier = HardwareTier.TIER_1_LOW_END

        config = cls.TIER_PRESETS[tier]
        logger.info(
            "hardware.tier_resolved",
            tier=tier.value,
            resolution=f"{config.target_resolution[0]}x{config.target_resolution[1]}",
            fps=config.target_fps,
            backend=config.inference_backend,
        )
        return config

    @classmethod
    def get_preset(cls, tier: HardwareTier) -> TierConfiguration:
        """Obtain tier configuration by enum."""
        return cls.TIER_PRESETS[tier]
