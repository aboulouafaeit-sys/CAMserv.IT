"""
camserv.platform.hardware
=========================

Hardware detection, accelerator capability probing, and runtime target profiling
for the CAMserv platform. Automatically discovers host CPU, RAM, NVIDIA GPU
compute capabilities, and determines optimal execution providers.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class GPUCapability:
    """Detected GPU hardware specifications."""

    index: int
    name: str
    memory_total_mb: int
    memory_free_mb: int
    compute_capability: tuple[int, int]
    cuda_driver_version: str | None = None
    is_supported: bool = True
    recommended_fp16: bool = True


@dataclass(slots=True)
class HardwareProfile:
    """Full host hardware profile and execution capability assessment."""

    os_name: str
    os_release: str
    os_version: str
    cpu_architecture: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    ram_total_mb: int
    ram_available_mb: int
    gpus: list[GPUCapability] = field(default_factory=list)
    has_cuda: bool = False
    has_tensorrt: bool = False
    recommended_backend: str = "onnx_cpu"
    max_recommended_concurrent_streams: int = 2
    limitations: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Return a structured dictionary summary of host hardware."""
        return {
            "os": f"{self.os_name} {self.os_release} ({self.cpu_architecture})",
            "cpu_cores": f"{self.cpu_cores_physical} physical / {self.cpu_cores_logical} logical",
            "ram_mb": f"{self.ram_available_mb} available / {self.ram_total_mb} total",
            "gpu_count": len(self.gpus),
            "primary_gpu": self.gpus[0].name if self.gpus else "None (CPU only)",
            "primary_vram_mb": self.gpus[0].memory_total_mb if self.gpus else 0,
            "recommended_backend": self.recommended_backend,
            "recommended_max_streams": self.max_recommended_concurrent_streams,
            "limitations": self.limitations,
        }


class HardwareDetector:
    """Probes host hardware and recommends execution configurations."""

    @classmethod
    def probe_host(cls) -> HardwareProfile:
        """Inspect the current machine environment and build a HardwareProfile."""
        os_name = platform.system()
        os_release = platform.release()
        os_version = platform.version()
        cpu_arch = platform.machine()

        # CPU Cores
        logical_cores = os.cpu_count() or 1
        physical_cores = max(1, logical_cores // 2)

        # RAM detection
        ram_total_mb, ram_avail_mb = cls._get_ram_info()

        # GPU detection
        gpus, has_cuda = cls._probe_nvidia_gpus()

        # Backend recommendation
        recommended_backend = "onnx_cpu"
        recommended_streams = max(1, min(4, physical_cores))
        has_tensorrt = False
        limitations: list[str] = []

        if has_cuda and gpus:
            primary = gpus[0]
            major, minor = primary.compute_capability
            # Compute 7.0+ (Volta, Turing, Ampere, Ada, Hopper, Blackwell)
            if major >= 7:
                recommended_backend = "onnx_gpu"
                if primary.memory_total_mb >= 4000:
                    recommended_streams = min(16, max(4, primary.memory_total_mb // 750))
                else:
                    recommended_streams = 2
                    limitations.append("GPU VRAM < 4GB limits concurrent camera streams to 2-3.")
                
                # Check for TensorRT presence
                try:
                    import tensorrt  # noqa: F401
                    has_tensorrt = True
                    recommended_backend = "tensorrt"
                except ImportError:
                    has_tensorrt = False
            else:
                recommended_backend = "onnx_gpu"
                limitations.append(f"Legacy GPU compute capability {major}.{minor}. FP16 may not be optimal.")
        else:
            limitations.append("No supported NVIDIA GPU detected. Falling back to CPU inference.")
            recommended_backend = "onnx_cpu"
            recommended_streams = max(1, physical_cores // 2)

        if ram_total_mb < 8192:
            limitations.append("Host RAM is below 8GB; potential backpressure frame-dropping under load.")

        profile = HardwareProfile(
            os_name=os_name,
            os_release=os_release,
            os_version=os_version,
            cpu_architecture=cpu_arch,
            cpu_cores_physical=physical_cores,
            cpu_cores_logical=logical_cores,
            ram_total_mb=ram_total_mb,
            ram_available_mb=ram_avail_mb,
            gpus=gpus,
            has_cuda=has_cuda,
            has_tensorrt=has_tensorrt,
            recommended_backend=recommended_backend,
            max_recommended_concurrent_streams=recommended_streams,
            limitations=limitations,
        )

        logger.info(
            "hardware.probed",
            backend=profile.recommended_backend,
            gpus=len(profile.gpus),
            cores=profile.cpu_cores_logical,
            ram_mb=profile.ram_total_mb,
        )
        return profile

    @classmethod
    def _get_ram_info(cls) -> tuple[int, int]:
        """Obtain total and available RAM in megabytes."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return int(mem.total / (1024 * 1024)), int(mem.available / (1024 * 1024))
        except ImportError:
            # Fallback estimation
            return 8192, 4096

    @classmethod
    def _probe_nvidia_gpus(cls) -> tuple[list[GPUCapability], bool]:
        """Probe NVIDIA GPUs via nvidia-smi CLI."""
        gpus: list[GPUCapability] = []
        has_cuda = False

        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,compute_cap,driver_version",
                "--format=csv,noheader,nounits",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=True)
            lines = res.stdout.strip().splitlines()
            for line in lines:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6:
                    idx = int(parts[0])
                    name = parts[1]
                    mem_total = int(float(parts[2]))
                    mem_free = int(float(parts[3]))
                    cc_str = parts[4].split(".")
                    cc = (int(cc_str[0]), int(cc_str[1])) if len(cc_str) >= 2 else (0, 0)
                    driver = parts[5]

                    gpu_cap = GPUCapability(
                        index=idx,
                        name=name,
                        memory_total_mb=mem_total,
                        memory_free_mb=mem_free,
                        compute_capability=cc,
                        cuda_driver_version=driver,
                        is_supported=cc[0] >= 6,
                        recommended_fp16=cc[0] >= 7,
                    )
                    gpus.append(gpu_cap)
                    has_cuda = True
        except (subprocess.SubprocessError, FileNotFoundError, ValueError) as err:
            logger.debug("hardware.nvidia_smi_unavailable", error=str(err))

        return gpus, has_cuda
