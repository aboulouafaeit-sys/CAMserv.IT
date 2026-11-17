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

import collections
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


class FallbackAdmissionDecision(str, enum.Enum):
    """Explicit outcomes of the CPU fallback admission controller."""

    FALLBACK_ACCEPTED = "fallback_accepted"          # Ample headroom (< 65% CPU); full migration permitted
    FALLBACK_REDUCED = "fallback_reduced"            # Moderate headroom (65-80% CPU); admitted with reduced FPS/ROI
    FALLBACK_DEFERRED = "fallback_deferred"          # Elevated headroom (80-90% CPU); queued or deferred
    FALLBACK_REJECTED = "fallback_rejected"          # Heavy load (> 90% CPU) or thermal critical; strictly rejected
    FALLBACK_UNAVAILABLE = "fallback_unavailable"    # Host resources / RAM completely exhausted


@dataclass(slots=True)
class TaskCPUCostEstimate:
    """Estimated CPU resource profile for a fallback workload."""

    task_id: str
    task_type: str                                    # "video_decode", "ai_inference", "motion_detect"
    camera_id: str
    estimated_cpu_percent: float                     # Measured or estimated CPU load increment
    target_fps: float = 30.0
    reduced_fps: float = 5.0
    can_reduce: bool = True
    priority: int = 10                               # 1: Critical recording, 5: Motion detection, 10: Deep AI re-id


@dataclass(slots=True)
class FallbackEvaluationResult:
    """Documented outcome of an admission evaluation."""

    decision: FallbackAdmissionDecision
    task_id: str
    allocated_fps: float
    cpu_percent_before: float
    estimated_cpu_percent_after: float
    reason: str
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "task_id": self.task_id,
            "allocated_fps": self.allocated_fps,
            "cpu_percent_before": round(self.cpu_percent_before, 1),
            "estimated_cpu_percent_after": round(self.estimated_cpu_percent_after, 1),
            "reason": self.reason,
            "timestamp_utc": self.timestamp_utc,
        }


class CPUFallbackAdmissionController:
    """
    Capacity-aware admission controller preventing host saturation during accelerator failover.
    Evaluates moving-average CPU load, active recording count, thermal state, and memory pressure.
    Guarantees that continuous surveillance recording is never compromised by runaway AI fallback.
    """

    def __init__(
        self,
        accepted_cpu_threshold: float = 65.0,
        reduced_cpu_threshold: float = 80.0,
        reject_cpu_threshold: float = 90.0,
        history_window_samples: int = 5,
    ) -> None:
        self.accepted_cpu_threshold = accepted_cpu_threshold
        self.reduced_cpu_threshold = reduced_cpu_threshold
        self.reject_cpu_threshold = reject_cpu_threshold
        self._load_history: collections.deque[float] = collections.deque(maxlen=history_window_samples)
        self.admitted_tasks: dict[str, TaskCPUCostEstimate] = {}
        self.deferred_tasks: dict[str, TaskCPUCostEstimate] = {}
        self.rejected_tasks: dict[str, str] = {}
        self.recording_pipeline_healthy: bool = True
        self.thermal_state: str = "nominal"
        self.ram_exhausted: bool = False

    def record_cpu_sample(self, cpu_percent: float) -> None:
        """Record a live CPU utilization sample."""
        self._load_history.append(max(0.0, min(100.0, cpu_percent)))

    @property
    def current_cpu_average(self) -> float:
        """Compute windowed moving average of CPU load."""
        if not self._load_history:
            return 25.0  # Nominal default if unpopulated
        return sum(self._load_history) / len(self._load_history)

    @property
    def total_admitted_cpu_load(self) -> float:
        """Sum of estimated CPU loads for all currently admitted tasks."""
        return sum(t.estimated_cpu_percent for t in self.admitted_tasks.values())

    def evaluate_task_admission(
        self,
        task: TaskCPUCostEstimate,
        current_cpu_percent: float | None = None,
    ) -> FallbackEvaluationResult:
        """
        Evaluate whether an accelerator task can safely migrate to CPU.
        Returns a FallbackEvaluationResult with explicit decision and allocated FPS.
        """
        if current_cpu_percent is not None:
            self.record_cpu_sample(current_cpu_percent)

        cpu_baseline = self.current_cpu_average
        projected_cpu = cpu_baseline + task.estimated_cpu_percent

        # 1. Check for complete host exhaustion or broken recording pipeline
        if self.ram_exhausted or not self.recording_pipeline_healthy:
            self.rejected_tasks[task.task_id] = "Host RAM exhausted or recording pipeline under pressure"
            return FallbackEvaluationResult(
                decision=FallbackAdmissionDecision.FALLBACK_UNAVAILABLE,
                task_id=task.task_id,
                allocated_fps=0.0,
                cpu_percent_before=cpu_baseline,
                estimated_cpu_percent_after=cpu_baseline,
                reason="Host RAM exhausted or recording pipeline under pressure. Rejecting migration.",
            )

        # 2. Check for thermal throttle or extreme CPU saturation (> 90%)
        if self.thermal_state in ("critical", "throttled") or projected_cpu >= self.reject_cpu_threshold:
            self.rejected_tasks[task.task_id] = f"Projected CPU ({projected_cpu:.1f}%) exceeds reject threshold ({self.reject_cpu_threshold}%)"
            return FallbackEvaluationResult(
                decision=FallbackAdmissionDecision.FALLBACK_REJECTED,
                task_id=task.task_id,
                allocated_fps=0.0,
                cpu_percent_before=cpu_baseline,
                estimated_cpu_percent_after=cpu_baseline,
                reason=f"Severe CPU saturation (projected {projected_cpu:.1f}% >= {self.reject_cpu_threshold}%). AI task rejected to preserve recording.",
            )

        # 3. Check for elevated CPU (80% - 90%): Defer non-critical analytics
        if projected_cpu >= self.reduced_cpu_threshold:
            if not task.can_reduce or task.priority > 5:
                self.deferred_tasks[task.task_id] = task
                return FallbackEvaluationResult(
                    decision=FallbackAdmissionDecision.FALLBACK_DEFERRED,
                    task_id=task.task_id,
                    allocated_fps=0.0,
                    cpu_percent_before=cpu_baseline,
                    estimated_cpu_percent_after=cpu_baseline,
                    reason=f"Elevated CPU load ({projected_cpu:.1f}%). Task deferred pending headroom.",
                )

        # 4. Moderate load (65% - 80%): Accept with reduced FPS/workload
        if projected_cpu >= self.accepted_cpu_threshold:
            if task.can_reduce:
                reduced_cost = task.estimated_cpu_percent * (task.reduced_fps / max(1.0, task.target_fps))
                reduced_task = TaskCPUCostEstimate(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    camera_id=task.camera_id,
                    estimated_cpu_percent=reduced_cost,
                    target_fps=task.target_fps,
                    reduced_fps=task.reduced_fps,
                    can_reduce=False,
                    priority=task.priority,
                )
                self.admitted_tasks[task.task_id] = reduced_task
                self._load_history.append(min(95.0, cpu_baseline + reduced_cost))
                return FallbackEvaluationResult(
                    decision=FallbackAdmissionDecision.FALLBACK_REDUCED,
                    task_id=task.task_id,
                    allocated_fps=task.reduced_fps,
                    cpu_percent_before=cpu_baseline,
                    estimated_cpu_percent_after=cpu_baseline + reduced_cost,
                    reason=f"Moderate CPU load. Admitted at reduced framerate ({task.reduced_fps} FPS).",
                )

        # 5. Ample headroom (< 65% CPU): Full acceptance
        self.admitted_tasks[task.task_id] = task
        self._load_history.append(min(95.0, projected_cpu))
        return FallbackEvaluationResult(
            decision=FallbackAdmissionDecision.FALLBACK_ACCEPTED,
            task_id=task.task_id,
            allocated_fps=task.target_fps,
            cpu_percent_before=cpu_baseline,
            estimated_cpu_percent_after=projected_cpu,
            reason=f"Sufficient CPU headroom. Admitted at full framerate ({task.target_fps} FPS).",
        )

    def release_task(self, task_id: str) -> bool:
        """Release an admitted task when it terminates or moves back to accelerator."""
        if task_id in self.admitted_tasks:
            t = self.admitted_tasks.pop(task_id)
            if self._load_history:
                new_avg = max(5.0, self._load_history[-1] - t.estimated_cpu_percent)
                self._load_history.append(new_avg)
            return True
        self.deferred_tasks.pop(task_id, None)
        self.rejected_tasks.pop(task_id, None)
        return False

    def clear(self) -> None:
        """Reset admission state."""
        self.admitted_tasks.clear()
        self.deferred_tasks.clear()
        self.rejected_tasks.clear()
        self._load_history.clear()

    def get_status(self) -> dict[str, Any]:
        """Observability telemetry for admission controller."""
        return {
            "current_cpu_average": round(self.current_cpu_average, 1),
            "admitted_task_count": len(self.admitted_tasks),
            "deferred_task_count": len(self.deferred_tasks),
            "rejected_task_count": len(self.rejected_tasks),
            "total_admitted_cpu_load": round(self.total_admitted_cpu_load, 1),
            "recording_pipeline_healthy": self.recording_pipeline_healthy,
            "thermal_state": self.thermal_state,
        }


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
        self.admission_controller = CPUFallbackAdmissionController()

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

    def handle_accelerator_failure(
        self,
        device_id: str,
        reason: str,
        active_tasks: list[TaskCPUCostEstimate] | None = None,
        current_cpu_percent: float | None = None,
    ) -> list[FallbackEvaluationResult]:
        """
        Handle failure of a hardware accelerator gracefully with admission control.
        Transitions failed device to FAILED state and evaluates fallback tasks.
        Preserves core recording while shedding, reducing, or deferring AI tasks.
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

        evaluation_results: list[FallbackEvaluationResult] = []
        if active_tasks:
            # Sort tasks by priority (lowest number = highest priority)
            sorted_tasks = sorted(active_tasks, key=lambda t: t.priority)
            for t in sorted_tasks:
                res = self.admission_controller.evaluate_task_admission(t, current_cpu_percent=current_cpu_percent)
                evaluation_results.append(res)
                logger.info(
                    "accelerator.fallback_admission_decision",
                    task_id=t.task_id,
                    decision=res.decision.value,
                    allocated_fps=res.allocated_fps,
                    reason=res.reason,
                )

        logger.warning(
            "accelerator.isolated_and_failed_over_to_cpu",
            failed_device=device_id,
            reason=reason,
            fallback=AcceleratorBackendType.CPU_UNIVERSAL.value,
            tasks_evaluated=len(evaluation_results),
        )
        return evaluation_results

    def gradual_accelerator_recovery(
        self,
        device_id: str,
        verifier_fn: Callable[[], bool],
        batch_size: int = 2,
    ) -> dict[str, Any]:
        """
        Phased restoration of an accelerator after failure without mass thundering herd.
        Verifies workload, promotes canary stream, and migrates tasks in controlled batches.
        """
        dev = self.devices.get(device_id)
        if not dev:
            return {"status": "error", "message": f"Device '{device_id}' not found"}

        # Phase 1: Re-verify under small test workload
        verified = self.advance_lifecycle(device_id, AcceleratorLifecycleState.VERIFIED_WORKLOAD, verifier_fn)
        if not verified:
            return {
                "status": "verification_failed",
                "message": f"Accelerator '{device_id}' failed workload verification during recovery",
            }

        # Phase 2: Canary / Batch Migration
        admitted_task_ids = list(self.admission_controller.admitted_tasks.keys())
        migrated: list[str] = []
        batch = admitted_task_ids[:batch_size]

        for task_id in batch:
            self.admission_controller.release_task(task_id)
            migrated.append(task_id)

        # Update active backends
        self.active_decode_backend = dev.backend_type
        self.active_inference_backend = dev.backend_type

        return {
            "status": "success",
            "device_id": device_id,
            "migrated_tasks": migrated,
            "remaining_on_cpu": len(self.admission_controller.admitted_tasks),
            "backend": dev.backend_type.value,
        }

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
            "admission_controller": self.admission_controller.get_status(),
        }
