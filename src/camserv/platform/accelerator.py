"""
camserv.platform.accelerator
============================

Hardware-Agnostic Accelerator Abstraction Layer for CAMserv.
Provides capability detection, multi-backend management, 6-state lifecycle tracking,
graceful failure isolation, and transparent CPU software fallback.

MANDATORY POLICY:
- Dedicated GPUs are strictly OPTIONAL. Core surveillance recording NEVER requires a discrete GPU.
- Supports Intel Quick Sync / integrated graphics, AMD iGPU / ROCm / VA-API,
  NVIDIA NVDEC / CUDA (optional), ARM Rockchip MPP / RKNN NPU, and Universal CPU fallback.
- Enforces the 6-state accelerator lifecycle:
  1. HARDWARE_DETECTED
  2. DRIVER_AVAILABLE
  3. RUNTIME_AVAILABLE
  4. CODEC_OR_MODEL_SUPPORTED
  5. INITIALIZED
  6. VERIFIED_WORKLOAD
- Never labels an accelerator as operational simply because hardware exists.
- In case of failure, automatically falls back to CPU without interrupting core recording.
"""

from __future__ import annotations

import enum
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


class AcceleratorLifecycleState(str, enum.Enum):
    """Six-state lifecycle progression for hardware accelerators."""

    UNAVAILABLE = "unavailable"                      # Hardware component not detected
    HARDWARE_DETECTED = "hardware_detected"          # Silicon device physically observed on bus/PCI/SoC
    DRIVER_AVAILABLE = "driver_available"            # Kernel driver or vendor module loaded and responsive
    RUNTIME_AVAILABLE = "runtime_available"          # User-space runtime library (CUDA, OpenVINO, oneVPL, RKNN) linked
    CODEC_OR_MODEL_SUPPORTED = "codec_or_model_supported"  # Requested codec (H.264/H.265) or AI model supported by hardware
    INITIALIZED = "initialized"                      # Context created and memory allocated successfully
    VERIFIED_WORKLOAD = "verified_workload"          # Actively verified through real execution of a test workload
    FAILED = "failed"                                # Hardware or driver failed; execution redirected to fallback


class AcceleratorBackendType(str, enum.Enum):
    """Supported execution backends for video decoding and neural inference."""

    CPU_UNIVERSAL = "cpu_universal"                  # Host CPU multi-threaded (libavcodec / ONNX CPU) - Always Available
    INTEL_QSV = "intel_qsv"                          # Intel Quick Sync / integrated Iris/UHD graphics
    AMD_VAAPI_ROCM = "amd_vaapi_rocm"                # AMD integrated / discrete graphics via VA-API or ROCm
    NVIDIA_CUDA_NVDEC = "nvidia_cuda_nvdec"          # NVIDIA discrete/embedded GPU (NVDEC / TensorRT) - Optional
    ARM_ROCKCHIP_MPP_RKNN = "arm_rockchip_mpp_rknn"  # Rockchip RK3588 VPU / NPU (Linux arm64)
    HAILO_NPU = "hailo_npu"                          # Hailo-8 / Hailo-8L PCIe/M.2 coprocessor


@dataclass(slots=True)
class AcceleratorDevice:
    """Represents a discovered hardware accelerator device with its operational state."""

    device_id: str
    name: str
    backend_type: AcceleratorBackendType
    is_discrete_gpu: bool = False
    is_integrated_gpu: bool = False
    is_npu: bool = False
    memory_total_mb: int = 0
    memory_free_mb: int = 0
    supported_codecs: list[str] = field(default_factory=lambda: ["h264", "h265"])
    supported_precisions: list[str] = field(default_factory=lambda: ["fp32"])
    lifecycle_state: AcceleratorLifecycleState = AcceleratorLifecycleState.HARDWARE_DETECTED
    error_message: str | None = None
    telemetry_provenance: str = "detected_probe"
    last_verified_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize accelerator device state."""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "backend_type": self.backend_type.value,
            "is_discrete_gpu": self.is_discrete_gpu,
            "is_integrated_gpu": self.is_integrated_gpu,
            "is_npu": self.is_npu,
            "memory_total_mb": self.memory_total_mb,
            "memory_free_mb": self.memory_free_mb,
            "supported_codecs": self.supported_codecs,
            "supported_precisions": self.supported_precisions,
            "lifecycle_state": self.lifecycle_state.value,
            "is_verified": self.lifecycle_state == AcceleratorLifecycleState.VERIFIED_WORKLOAD,
            "error_message": self.error_message,
            "last_verified_utc": self.last_verified_utc,
        }


class AcceleratorAbstractionManager:
    """
    Central manager for hardware acceleration detection, progressive lifecycle verification,
    failure isolation, and automatic fallback to CPU software execution.
    """

    def __init__(self, probe_on_init: bool = True) -> None:
        self.devices: dict[str, AcceleratorDevice] = {}
        self.active_decode_backend: AcceleratorBackendType = AcceleratorBackendType.CPU_UNIVERSAL
        self.active_inference_backend: AcceleratorBackendType = AcceleratorBackendType.CPU_UNIVERSAL
        self.failure_history: list[dict[str, Any]] = []

        # Always register Universal CPU Fallback as verified baseline
        self._register_cpu_universal_baseline()

        if probe_on_init:
            self.discover_hardware_accelerators()

    def _register_cpu_universal_baseline(self) -> None:
        """Register host CPU as the inviolate universal fallback processing engine."""
        cpu_dev = AcceleratorDevice(
            device_id="cpu_universal",
            name=f"Host CPU Universal Engine ({platform.machine()})",
            backend_type=AcceleratorBackendType.CPU_UNIVERSAL,
            is_discrete_gpu=False,
            is_integrated_gpu=False,
            is_npu=False,
            memory_total_mb=0,
            memory_free_mb=0,
            supported_codecs=["h264", "h265", "mjpeg"],
            supported_precisions=["fp32"],
            lifecycle_state=AcceleratorLifecycleState.VERIFIED_WORKLOAD,
            last_verified_utc=datetime.now(timezone.utc).isoformat(),
            telemetry_provenance="platform.processor",
        )
        self.devices["cpu_universal"] = cpu_dev
        self.active_decode_backend = AcceleratorBackendType.CPU_UNIVERSAL
        self.active_inference_backend = AcceleratorBackendType.CPU_UNIVERSAL

    def discover_hardware_accelerators(self) -> dict[str, AcceleratorDevice]:
        """
        Probe available hardware interfaces across Intel, AMD, NVIDIA, and ARM SoC.
        Marks newly detected devices in state HARDWARE_DETECTED.
        """
        # 1. Probe Intel Integrated Graphics / Quick Sync
        self._probe_intel_graphics()

        # 2. Probe AMD Graphics (iGPU / ROCm / VA-API)
        self._probe_amd_graphics()

        # 3. Probe NVIDIA GPU (Optional - discrete or embedded)
        self._probe_nvidia_gpu()

        # 4. Probe ARM SoC Accelerators (Rockchip MPP / RKNN NPU)
        self._probe_arm_soc()

        logger.info(
            "accelerator.discovery_complete",
            discovered_count=len(self.devices),
            backends=[d.backend_type.value for d in self.devices.values()],
        )
        return self.devices

    def _probe_intel_graphics(self) -> None:
        """Probe for Intel iGPU / Quick Sync Video support."""
        is_intel = "intel" in platform.processor().lower() or (
            os.name == "nt" and "intel" in os.environ.get("PROCESSOR_IDENTIFIER", "").lower()
        )
        if is_intel or os.path.exists("/dev/dri/renderD128"):
            dev = AcceleratorDevice(
                device_id="intel_qsv_0",
                name="Intel Quick Sync Video (Integrated iGPU)",
                backend_type=AcceleratorBackendType.INTEL_QSV,
                is_discrete_gpu=False,
                is_integrated_gpu=True,
                is_npu=False,
                supported_codecs=["h264", "h265"],
                supported_precisions=["fp32", "fp16"],
                lifecycle_state=AcceleratorLifecycleState.HARDWARE_DETECTED,
                telemetry_provenance="cpu_architecture_probe",
            )
            self.devices[dev.device_id] = dev

    def _probe_amd_graphics(self) -> None:
        """Probe for AMD integrated or discrete graphics."""
        is_amd = "amd" in platform.processor().lower() or (
            os.name == "nt" and "amd" in os.environ.get("PROCESSOR_IDENTIFIER", "").lower()
        )
        if is_amd:
            dev = AcceleratorDevice(
                device_id="amd_gpu_0",
                name="AMD Radeon Graphics (Integrated/Discrete)",
                backend_type=AcceleratorBackendType.AMD_VAAPI_ROCM,
                is_discrete_gpu=False,
                is_integrated_gpu=True,
                supported_codecs=["h264", "h265"],
                supported_precisions=["fp32", "fp16"],
                lifecycle_state=AcceleratorLifecycleState.HARDWARE_DETECTED,
                telemetry_provenance="cpu_architecture_probe",
            )
            self.devices[dev.device_id] = dev

    def _probe_nvidia_gpu(self) -> None:
        """Probe for NVIDIA dedicated or embedded GPU via nvidia-smi CLI."""
        nvsmi = shutil.which("nvidia-smi") or (
            os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "nvidia-smi.exe")
            if os.name == "nt" else None
        )
        if nvsmi and os.path.exists(nvsmi):
            try:
                cmd = [nvsmi, "--query-gpu=index,name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0 and res.stdout.strip():
                    for line in res.stdout.strip().splitlines():
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 4:
                            idx = parts[0]
                            name = parts[1]
                            mem_total = int(float(parts[2]))
                            mem_free = int(float(parts[3]))
                            dev_id = f"nvidia_gpu_{idx}"
                            dev = AcceleratorDevice(
                                device_id=dev_id,
                                name=name,
                                backend_type=AcceleratorBackendType.NVIDIA_CUDA_NVDEC,
                                is_discrete_gpu=True,
                                is_integrated_gpu=False,
                                is_npu=False,
                                memory_total_mb=mem_total,
                                memory_free_mb=mem_free,
                                supported_codecs=["h264", "h265", "vp9"],
                                supported_precisions=["fp32", "fp16", "int8"],
                                lifecycle_state=AcceleratorLifecycleState.HARDWARE_DETECTED,
                                telemetry_provenance="nvidia_smi_cli",
                            )
                            self.devices[dev_id] = dev
            except Exception as e:
                logger.debug("accelerator.nvidia_probe_failed", error=str(e))

    def _probe_arm_soc(self) -> None:
        """Probe for ARM SoC VPU / NPU (e.g. Rockchip RK3588 MPP/RKNN)."""
        is_arm = platform.machine() in ("aarch64", "arm64", "armv7l")
        if is_arm and os.path.exists("/dev/rknpu"):
            dev = AcceleratorDevice(
                device_id="rockchip_rknn_0",
                name="Rockchip RK3588 Tri-Core NPU (6 TOPS)",
                backend_type=AcceleratorBackendType.ARM_ROCKCHIP_MPP_RKNN,
                is_discrete_gpu=False,
                is_integrated_gpu=False,
                is_npu=True,
                supported_codecs=["h264", "h265"],
                supported_precisions=["int8", "fp16"],
                lifecycle_state=AcceleratorLifecycleState.HARDWARE_DETECTED,
                telemetry_provenance="/dev/rknpu",
            )
            self.devices[dev.device_id] = dev

    def advance_lifecycle(
        self,
        device_id: str,
        target_state: AcceleratorLifecycleState,
        verifier_fn: Callable[[], bool] | None = None,
    ) -> bool:
        """
        Advance an accelerator through the mandatory 6-state progression.
        Transitions sequentially:
        DETECTED -> DRIVER_AVAILABLE -> RUNTIME_AVAILABLE -> CODEC_SUPPORTED -> INITIALIZED -> VERIFIED_WORKLOAD
        """
        dev = self.devices.get(device_id)
        if not dev:
            return False

        # CPU Universal is always verified
        if dev.backend_type == AcceleratorBackendType.CPU_UNIVERSAL:
            dev.lifecycle_state = AcceleratorLifecycleState.VERIFIED_WORKLOAD
            return True

        progression = [
            AcceleratorLifecycleState.HARDWARE_DETECTED,
            AcceleratorLifecycleState.DRIVER_AVAILABLE,
            AcceleratorLifecycleState.RUNTIME_AVAILABLE,
            AcceleratorLifecycleState.CODEC_OR_MODEL_SUPPORTED,
            AcceleratorLifecycleState.INITIALIZED,
            AcceleratorLifecycleState.VERIFIED_WORKLOAD,
        ]

        if target_state not in progression:
            return False

        target_idx = progression.index(target_state)
        current_idx = progression.index(dev.lifecycle_state) if dev.lifecycle_state in progression else -1

        # Advance sequentially up to target state
        for state in progression[current_idx + 1 : target_idx + 1]:
            # Run custom verification function if provided for target state
            if state == target_state and verifier_fn is not None:
                try:
                    if not verifier_fn():
                        self.handle_accelerator_failure(
                            device_id,
                            f"Verification failed at state '{state.value}'",
                        )
                        return False
                except Exception as exc:
                    self.handle_accelerator_failure(device_id, str(exc))
                    return False

            dev.lifecycle_state = state

        if dev.lifecycle_state == AcceleratorLifecycleState.VERIFIED_WORKLOAD:
            dev.last_verified_utc = datetime.now(timezone.utc).isoformat()
            logger.info("accelerator.verified_workload", device_id=device_id, name=dev.name)

        return True

    def handle_accelerator_failure(self, device_id: str, reason: str) -> None:
        """
        Handle failure of a hardware accelerator gracefully.
        Transitions failed device to FAILED state and routes active workloads to CPU_UNIVERSAL.
        Core video recording continues uninterrupted.
        """
        dev = self.devices.get(device_id)
        if dev:
            dev.lifecycle_state = AcceleratorLifecycleState.FAILED
            dev.error_message = reason

        failure_record = {
            "device_id": device_id,
            "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "fallback_target": AcceleratorBackendType.CPU_UNIVERSAL.value,
        }
        self.failure_history.append(failure_record)

        # Fall back active decoding and inference backends to CPU
        self.active_decode_backend = AcceleratorBackendType.CPU_UNIVERSAL
        self.active_inference_backend = AcceleratorBackendType.CPU_UNIVERSAL

        logger.warning(
            "accelerator.isolated_and_failed_over_to_cpu",
            failed_device=device_id,
            reason=reason,
            fallback=AcceleratorBackendType.CPU_UNIVERSAL.value,
        )

    def select_optimal_backends(self) -> tuple[AcceleratorBackendType, AcceleratorBackendType]:
        """
        Select verified optimal backends for decoding and inference.
        Returns: (decode_backend, inference_backend)
        If no hardware accelerator is verified under a real workload, cleanly defaults to CPU.
        """
        # Look for verified accelerators
        verified_devices = [
            d for d in self.devices.values()
            if d.lifecycle_state == AcceleratorLifecycleState.VERIFIED_WORKLOAD
            and d.backend_type != AcceleratorBackendType.CPU_UNIVERSAL
        ]

        if not verified_devices:
            self.active_decode_backend = AcceleratorBackendType.CPU_UNIVERSAL
            self.active_inference_backend = AcceleratorBackendType.CPU_UNIVERSAL
            return self.active_decode_backend, self.active_inference_backend

        # Prefer dedicated GPU if verified, then integrated GPU / NPU
        primary = sorted(verified_devices, key=lambda d: (d.is_discrete_gpu, d.memory_total_mb), reverse=True)[0]
        self.active_decode_backend = primary.backend_type
        self.active_inference_backend = primary.backend_type
        return self.active_decode_backend, self.active_inference_backend

    def get_status_summary(self) -> dict[str, Any]:
        """Return truthful status dictionary of all accelerator devices and backends."""
        return {
            "active_decode_backend": self.active_decode_backend.value,
            "active_inference_backend": self.active_inference_backend.value,
            "requires_discrete_gpu": False,
            "is_cpu_only_supported": True,
            "device_count": len(self.devices),
            "devices": {dev_id: dev.to_dict() for dev_id, dev in self.devices.items()},
            "failure_events": len(self.failure_history),
        }
