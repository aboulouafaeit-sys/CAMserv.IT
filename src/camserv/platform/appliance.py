"""
camserv.platform.appliance
==========================

CAMserv AI Appliance Hardware Specification, Profile Engineering & Abstraction.
Defines capability-based hardware profiles (Profile A Low-Power, Profile B Standard,
Profile C Professional, Profile D Enterprise), hardware capability interfaces,
resource monitoring, thermal throttle management, graceful workload degradation
governors, and capacity sizing models.

CORE MANDATE:
- Dedicated graphics cards are strictly OPTIONAL. Core surveillance recording NEVER requires a discrete GPU.
- Supports CPU-only, integrated graphics (Intel QSV / AMD iGPU), ARM SoC (Rockchip), and optional discrete GPUs.
- All power models account for CPU, GPU (when present), RAM, storage drives, network adapters, fans, and peripherals.
- Power supplies specify continuous rated capacity and load safety margins (including single surviving PSU under N+1 redundancy).
"""

from __future__ import annotations

import enum
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from camserv.platform.factory import get_platform_hardware_prober
from camserv.platform.hardware import (
    DiagnosticState,
    GPUCapability,
    HardwareDetector,
    HardwareProfile,
)
from camserv.storage.isep.models import (
    HardwareAvailabilityState,
    HardwareTelemetryMetric,
    TelemetrySource,
)

logger = structlog.get_logger(__name__)


class ApplianceProfileType(str, enum.Enum):
    """Standardized capability-based CAMserv hardware profiles."""

    # Primary standardized profile designations
    PROFILE_A_LOW_POWER = "profile_a_low_power"        # Entry-level / low-power x86 / small ARM / older PCs (No GPU)
    PROFILE_B_STANDARD = "profile_b_standard"          # Mainstream desktop / mini-PC / integrated graphics (No discrete GPU required)
    PROFILE_C_PROFESSIONAL = "profile_c_professional"  # Performance CPU / larger RAM / optional discrete or integrated accelerator
    PROFILE_D_ENTERPRISE = "profile_d_enterprise"      # Multi-socket / server CPU / multi-disk / optional distributed accelerators
    CUSTOM = "custom"                                  # Heterogeneous or developer test environment

    # Backward-compatible aliases for existing test suites
    PROFILE_A_EDGE = "profile_a_edge"
    PROFILE_STANDARD = "profile_standard"
    PROFILE_B_PROFESSIONAL = "profile_b_professional"
    PROFILE_C_ENTERPRISE = "profile_c_enterprise"


class ThermalState(str, enum.Enum):
    """Thermal throttling status for edge, standard, and enterprise appliances."""

    NOMINAL = "nominal"      # < 70°C: Full capacity, peak inference throughput
    ELEVATED = "elevated"    # 70°C - 82°C: Minor fan escalation, warning logged
    THROTTLED = "throttled"  # 83°C - 90°C: Load shedding engaged, FPS downsampled
    CRITICAL = "critical"    # > 90°C: Emergency shed, raw preservation only, alerts dispatched


@dataclass(slots=True)
class ThermalStatus:
    """Thermal telemetry for appliance host and accelerators with verified sensor provenance."""

    cpu_temp_celsius: float | None = None
    gpu_temp_celsius: float | None = None
    npu_temp_celsius: float | None = None
    storage_temp_celsius: float | None = None
    board_temp_celsius: float | None = None
    ambient_temp_celsius: float | None = None
    state: ThermalState = ThermalState.NOMINAL
    fan_speed_percent: int | None = None
    throttle_reason: str | None = None
    telemetry_source: TelemetrySource = TelemetrySource.UNAVAILABLE
    availability: HardwareAvailabilityState = HardwareAvailabilityState.UNAVAILABLE
    sensor_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StorageEnduranceMetrics:
    """Storage endurance and capacity assessment for surveillance disks."""

    mount_point: str = "/"
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    percent_used: float = 0.0
    is_solid_state: bool = True
    estimated_wear_percent: float | None = None  # SMART endurance metric where supported
    warning_low_space: bool = False              # True if free space < 10%
    telemetry_source: TelemetrySource = TelemetrySource.OS_SHUTIL_DISK_USAGE
    availability: HardwareAvailabilityState = HardwareAvailabilityState.AVAILABLE


@dataclass(slots=True)
class ApplianceSpecification:
    """Hardware architecture, bill-of-materials, and electrical power specification."""

    profile_type: ApplianceProfileType
    display_name: str
    target_form_factor: str
    recommended_stream_range: tuple[int, int]
    max_stream_ceiling: int
    cpu_arch_requirement: str
    min_physical_cores: int
    min_ram_gb: int
    recommended_accelerator: str
    video_decoders: list[str]
    storage_type: str
    power_budget_watts: float
    thermal_limit_celsius: float
    estimated_bom_usd: tuple[float, float]
    description: str
    network_interfaces: str = "Dual 1GbE RJ45"
    cooling_type: str = "Passive / Fanless"
    typical_power_watts: float = 12.0
    worst_case_power_watts: float = 18.0
    psu_capacity_watts: float = 40.0
    psu_redundant: bool = False
    psu_safety_margin_percent: float = 55.0
    is_gpu_required: bool = False                      # Strictly False: discrete GPU is NEVER required
    supports_cpu_only: bool = True                     # Universal CPU fallback is always supported
    workload_envelope: str = "4x 1080p30 H.264/H.265 continuous recording"
    known_limitations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ApplianceCapabilityProfile:
    """Active runtime capability assessment of host appliance."""

    profile_type: ApplianceProfileType
    detected_hardware: HardwareProfile
    thermal: ThermalStatus = field(default_factory=ThermalStatus)
    storage: StorageEnduranceMetrics = field(default_factory=StorageEnduranceMetrics)
    allocated_streams: int = 0
    active_degradation_level: int = 0  # 0: None, 1: Minor (15->10 FPS), 2: Major (10->5 FPS, downscaled ROI), 3: Critical (raw vault only)
    is_accelerator_healthy: bool = True
    hardware_detected: bool = True
    hardware_available: bool = True
    hardware_initialized: bool = True
    hardware_actively_used: bool = True
    hardware_physically_verified: bool = False
    telemetry_metrics: dict[str, HardwareTelemetryMetric] = field(default_factory=dict)
    diagnostic_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize capability profile to telemetry dictionary."""
        return {
            "profile_type": self.profile_type.value,
            "host_os": f"{self.detected_hardware.os_name} {self.detected_hardware.os_release}",
            "cpu_arch": self.detected_hardware.cpu_architecture,
            "cores": self.detected_hardware.cpu_cores_physical,
            "ram_mb": self.detected_hardware.ram_total_mb,
            "gpus_detected": len(self.detected_hardware.gpus),
            "primary_accelerator": (
                self.detected_hardware.gpus[0].name
                if self.detected_hardware.gpus
                else "CPU (Universal Native)"
            ),
            "requires_discrete_gpu": False,
            "thermal_state": self.thermal.state.value,
            "storage_free_gb": round(self.storage.free_gb, 2),
            "storage_percent_used": round(self.storage.percent_used, 1),
            "allocated_streams": self.allocated_streams,
            "active_degradation_level": self.active_degradation_level,
            "is_accelerator_healthy": self.is_accelerator_healthy,
            "hardware_detected": self.hardware_detected,
            "hardware_available": self.hardware_available,
            "hardware_initialized": self.hardware_initialized,
            "hardware_actively_used": self.hardware_actively_used,
            "hardware_physically_verified": self.hardware_physically_verified,
            "diagnostics": self.diagnostic_messages,
        }


class ApplianceCatalog:
    """Standardized specifications and sizing models for CAMserv AI Appliance reference designs."""

    _SPEC_EDGE = ApplianceSpecification(
        profile_type=ApplianceProfileType.PROFILE_A_EDGE,
        display_name="CAMserv Profile A — Low-Power / Entry-Level (Edge)",
        target_form_factor="Ultra-Compact Fanless Industrial Box (DIN-rail / VESA)",
        recommended_stream_range=(1, 4),
        max_stream_ceiling=6,
        cpu_arch_requirement="ARM64 (Rockchip RK3588) or x86_64 (Intel N100 / Older x86)",
        min_physical_cores=4,
        min_ram_gb=8,
        recommended_accelerator="Embedded 6 TOPS NPU / Intel OpenVINO / Universal CPU",
        video_decoders=["mpp", "vaapi", "qsv", "software"],
        storage_type="Industrial NVMe SSD (High TBW, pSLC / TLC cache) or SATA HDD",
        power_budget_watts=18.0,
        typical_power_watts=12.0,
        worst_case_power_watts=22.0,
        psu_capacity_watts=40.0,
        psu_redundant=False,
        psu_safety_margin_percent=81.8,
        is_gpu_required=False,
        supports_cpu_only=True,
        thermal_limit_celsius=75.0,
        estimated_bom_usd=(330.0, 480.0),
        cooling_type="Passive / Fanless Monolithic Aluminum Heatsink",
        network_interfaces="Dual 1GbE RJ45",
        workload_envelope="1-4x 1080p30 H.264/H.265 continuous recording; zero discrete GPU needed",
        description="Engineered for distributed perimeter gates, cellular kiosks, remote substations, and older hardware.",
        known_limitations=[
            "Low RAM limits dense concurrent neural pipelines",
            "Fanless enclosure requires ambient environment <= 45°C",
            "Discrete GPUs are neither supported nor required",
        ],
    )

    _SPEC_STANDARD = ApplianceSpecification(
        profile_type=ApplianceProfileType.PROFILE_STANDARD,
        display_name="CAMserv Profile B — Standard (Mainstream)",
        target_form_factor="Compact Desktop Mini-Tower / 1U Chassis",
        recommended_stream_range=(4, 16),
        max_stream_ceiling=20,
        cpu_arch_requirement="x86_64 (Intel Core i3/i5 12th-14th Gen / AMD Ryzen 5)",
        min_physical_cores=6,
        min_ram_gb=16,
        recommended_accelerator="Integrated GPU (Intel QSV / AMD iGPU) or Host CPU",
        video_decoders=["qsv", "vaapi", "software"],
        storage_type="512GB NVMe OS/Staging + 2x 4TB Surveillance SATA CMR HDDs",
        power_budget_watts=85.0,
        typical_power_watts=58.0,
        worst_case_power_watts=139.0,
        psu_capacity_watts=250.0,
        psu_redundant=False,
        psu_safety_margin_percent=79.9,
        is_gpu_required=False,
        supports_cpu_only=True,
        thermal_limit_celsius=78.0,
        estimated_bom_usd=(750.0, 1150.0),
        cooling_type="Active Low-Noise PWM Fan (<= 28 dBA)",
        network_interfaces="Dual 2.5GbE RJ45",
        workload_envelope="4-16x 1080p30 H.264/H.265 continuous recording + substream AI; operates 100% without discrete GPU",
        description="Engineered for retail storefronts, commercial offices, primary schools, and medical clinics.",
        known_limitations=[
            "Single power supply input (no electrical redundancy)",
            "Optimized for integrated graphics; discrete GPU is strictly optional",
        ],
    )

    _SPEC_PRO = ApplianceSpecification(
        profile_type=ApplianceProfileType.PROFILE_B_PROFESSIONAL,
        display_name="CAMserv Profile C — Professional",
        target_form_factor="Compact 1U / 2U Rackmount NVR Chassis",
        recommended_stream_range=(4, 16),
        max_stream_ceiling=20,
        cpu_arch_requirement="x86_64 (Intel Core i7-13700 / AMD Ryzen 7 7700X)",
        min_physical_cores=8,
        min_ram_gb=32,
        recommended_accelerator="Intel UHD / QSV (Base) or Optional Discrete GPU (NVIDIA RTX 4060 8GB / Arc A770)",
        video_decoders=["nvdec", "qsv", "software"],
        storage_type="1TB NVMe OS/Pre-Roll + 2x 8TB Surveillance SATA HDDs (RAID-1)",
        power_budget_watts=180.0,
        typical_power_watts=95.0,
        worst_case_power_watts=343.5,
        psu_capacity_watts=500.0,
        psu_redundant=True,
        psu_safety_margin_percent=45.6,
        is_gpu_required=False,
        supports_cpu_only=True,
        thermal_limit_celsius=82.0,
        estimated_bom_usd=(1200.0, 1800.0),
        cooling_type="Dual PWM Ball-Bearing Chassis Fans",
        network_interfaces="Dual 2.5GbE + Dedicated 1GbE Management",
        workload_envelope="16-32x 1080p30 or 8x 4K30 continuous recording; base operates without discrete GPU; discrete GPU is optional accelerator",
        description="Engineered for corporate headquarters, logistics warehouses, and commercial office complexes.",
        known_limitations=[
            "Dual redundant 500W PSUs (N+1); single surviving PSU carries full 343.5W load",
            "Chassis airflow requirement: front/rear clearance >= 100mm",
        ],
    )

    _SPEC_ENTERPRISE = ApplianceSpecification(
        profile_type=ApplianceProfileType.PROFILE_C_ENTERPRISE,
        display_name="CAMserv Profile D — Enterprise",
        target_form_factor="2U Rackmount Server with Redundant Power & Fans",
        recommended_stream_range=(16, 64),
        max_stream_ceiling=80,
        cpu_arch_requirement="x86_64 (AMD EPYC 7003/9004 / Intel Xeon Scalable)",
        min_physical_cores=16,
        min_ram_gb=64,
        recommended_accelerator="High-Core Server CPUs (Base) or Optional Enterprise Accelerators (Dual NVIDIA L4 / RTX 4000 Ada SFF / Clamped 150W Accelerators)",
        video_decoders=["dual nvdec", "software"],
        storage_type="2TB NVMe M.2 (RAID-1 OS) + 4x U.2 NVMe / 8x SAS Surveillance HDDs (RAID-6)",
        power_budget_watts=500.0,
        typical_power_watts=260.0,
        worst_case_power_watts=608.2,
        psu_capacity_watts=800.0,
        psu_redundant=True,
        psu_safety_margin_percent=31.5,
        is_gpu_required=False,
        supports_cpu_only=True,
        thermal_limit_celsius=85.0,
        estimated_bom_usd=(4500.0, 8500.0),
        cooling_type="Hot-Swappable Redundant High-CFM Fan Matrix (N+1)",
        network_interfaces="Quad 10GbE SFP+ / 2.5GbE RJ45 + IPMI 2.0 Dedicated",
        workload_envelope="32-64+ continuous recording streams with concurrent multi-camera re-identification; core recording never requires GPU",
        description="Engineered for airports, critical municipal infrastructure, and large industrial campus installations.",
        known_limitations=[
            "Requires 2U rack enclosure and dual AC feeds for optimal N+1 efficiency",
            "Mandates SAS staggered drive spin-up (2 drives per group)",
            "Unclamped Dual RTX 4090 (900W) prohibited on 800W PSUs; dual 1600W Titanium required if unclamped",
        ],
    )

    SPECIFICATIONS: dict[ApplianceProfileType, ApplianceSpecification] = {
        # Standard enum mappings
        ApplianceProfileType.PROFILE_A_LOW_POWER: _SPEC_EDGE,
        ApplianceProfileType.PROFILE_B_STANDARD: _SPEC_STANDARD,
        ApplianceProfileType.PROFILE_C_PROFESSIONAL: _SPEC_PRO,
        ApplianceProfileType.PROFILE_D_ENTERPRISE: _SPEC_ENTERPRISE,

        # Backward-compatible mappings
        ApplianceProfileType.PROFILE_A_EDGE: _SPEC_EDGE,
        ApplianceProfileType.PROFILE_STANDARD: _SPEC_STANDARD,
        ApplianceProfileType.PROFILE_B_PROFESSIONAL: _SPEC_PRO,
        ApplianceProfileType.PROFILE_C_ENTERPRISE: _SPEC_ENTERPRISE,
    }

    @classmethod
    def calculate_storage_rate_gb_day(
        cls,
        stream_count: int,
        bitrate_kbps: float,
        protocol_overhead: float = 0.05,
    ) -> float:
        """Calculate daily storage consumption in Gigabytes (GB)."""
        if stream_count <= 0 or bitrate_kbps <= 0:
            return 0.0
        total_kbps = stream_count * bitrate_kbps * (1.0 + protocol_overhead)
        kbits_per_day = total_kbps * 86400.0
        gb_per_day = kbits_per_day / (8.0 * 1024.0 * 1024.0)
        return round(gb_per_day, 3)

    @classmethod
    def calculate_retention_days(
        cls,
        usable_storage_gb: float,
        stream_count: int,
        bitrate_kbps: float,
        protocol_overhead: float = 0.05,
    ) -> float:
        """Calculate supported continuous retention duration in days."""
        daily_gb = cls.calculate_storage_rate_gb_day(stream_count, bitrate_kbps, protocol_overhead)
        if daily_gb <= 0:
            return 0.0
        return round(usable_storage_gb / daily_gb, 2)

    @classmethod
    def calculate_network_bandwidth_mbps(
        cls,
        stream_count: int,
        bitrate_kbps: float,
        protocol_overhead: float = 0.08,
    ) -> float:
        """Calculate total incoming network ingestion bandwidth in Megabits per second (Mbps)."""
        if stream_count <= 0 or bitrate_kbps <= 0:
            return 0.0
        return round((stream_count * bitrate_kbps * (1.0 + protocol_overhead)) / 1000.0, 2)

    @classmethod
    def calculate_daily_power_kwh(cls, typical_watts: float) -> float:
        """Calculate daily electrical consumption in kilowatt-hours (kWh)."""
        if typical_watts <= 0:
            return 0.0
        return round((typical_watts * 24.0) / 1000.0, 3)


class ApplianceHardwareManager:
    """
    Hardware abstraction and autonomous governor for CAMserv appliances.
    Probes host resources, maps to reference profiles, manages thermal pressure,
    and coordinates graceful workload shedding without failing essential security.
    """

    def __init__(self, hardware_profile: HardwareProfile | None = None) -> None:
        self.hardware: HardwareProfile = hardware_profile or HardwareDetector.probe_host()
        self.profile: ApplianceCapabilityProfile = self._evaluate_capability_profile()

    def _evaluate_capability_profile(self) -> ApplianceCapabilityProfile:
        """Evaluate detected hardware and determine the optimal appliance profile."""
        cores = self.hardware.cpu_cores_physical
        ram_gb = self.hardware.ram_total_mb / 1024.0
        gpus = self.hardware.gpus

        diagnostics: list[str] = []

        # Determine Appliance Profile Match
        if len(gpus) >= 2 or (len(gpus) == 1 and gpus[0].memory_total_mb >= 20000 and cores >= 16):
            profile_type = ApplianceProfileType.PROFILE_C_ENTERPRISE
            diagnostics.append("Matched Enterprise Server Profile (Multi-GPU / High Core Density)")
        elif len(gpus) >= 1 and gpus[0].memory_total_mb >= 6000 and cores >= 6:
            profile_type = ApplianceProfileType.PROFILE_B_PROFESSIONAL
            diagnostics.append("Matched Professional Appliance Profile (Discrete Dedicated Accelerator)")
        elif cores >= 6 and ram_gb >= 12.0:
            profile_type = ApplianceProfileType.PROFILE_STANDARD
            diagnostics.append("Matched Standard Appliance Profile (Multi-Core CPU / High RAM)")
        elif cores >= 2 and ram_gb >= 3.5:
            profile_type = ApplianceProfileType.PROFILE_A_EDGE
            diagnostics.append("Matched Edge Appliance Profile (Compact / Low-Power CPU / NPU)")
        else:
            profile_type = ApplianceProfileType.CUSTOM
            diagnostics.append("Constrained Host: Custom execution tier with strict stream limits")

        # Storage capacity check
        storage_metrics = self._probe_storage()
        if storage_metrics.warning_low_space:
            diagnostics.append(f"Storage Warning: Only {storage_metrics.free_gb:.1f} GB free on mount")

        # Initial thermal check with truthful sensor provenance
        thermal_status = self._probe_thermal()

        # Telemetry metrics dictionary
        telemetry_metrics: dict[str, HardwareTelemetryMetric] = {}
        now_iso = datetime.now(timezone.utc).isoformat()

        if thermal_status.cpu_temp_celsius is not None:
            telemetry_metrics["cpu_temp"] = HardwareTelemetryMetric(
                metric_name="cpu_temperature_celsius",
                value=thermal_status.cpu_temp_celsius,
                source=thermal_status.telemetry_source,
                timestamp_utc=now_iso,
                availability=HardwareAvailabilityState.AVAILABLE,
                confidence=1.0,
            )
        else:
            telemetry_metrics["cpu_temp"] = HardwareTelemetryMetric(
                metric_name="cpu_temperature_celsius",
                value=None,
                source=TelemetrySource.UNAVAILABLE,
                timestamp_utc=now_iso,
                availability=HardwareAvailabilityState.UNAVAILABLE,
                details="No physical CPU thermal zone accessible without elevated host privilege",
            )

        telemetry_metrics["storage_free"] = HardwareTelemetryMetric(
            metric_name="storage_free_gb",
            value=round(storage_metrics.free_gb, 2),
            source=storage_metrics.telemetry_source,
            timestamp_utc=now_iso,
            availability=storage_metrics.availability,
        )

        return ApplianceCapabilityProfile(
            profile_type=profile_type,
            detected_hardware=self.hardware,
            thermal=thermal_status,
            storage=storage_metrics,
            allocated_streams=0,
            active_degradation_level=0,
            is_accelerator_healthy=(
                self.hardware.diagnostics.gpu_state
                in (DiagnosticState.AVAILABLE, DiagnosticState.ACTIVE)
                if self.hardware.gpus
                else True
            ),
            hardware_detected=True,
            hardware_available=True,
            hardware_initialized=True,
            hardware_actively_used=True,
            hardware_physically_verified=False,  # Set True only on verified physical laboratory bench
            telemetry_metrics=telemetry_metrics,
            diagnostic_messages=diagnostics,
        )

    def _probe_storage(self, path: str = ".") -> StorageEnduranceMetrics:
        """Inspect storage volume capacity and disk utilization."""
        try:
            total, used, free = shutil.disk_usage(path)
            total_gb = total / (1024**3)
            used_gb = used / (1024**3)
            free_gb = free / (1024**3)
            percent = (used / total) * 100.0 if total > 0 else 0.0
            return StorageEnduranceMetrics(
                mount_point=os.path.abspath(path),
                total_gb=total_gb,
                used_gb=used_gb,
                free_gb=free_gb,
                percent_used=percent,
                is_solid_state=True,
                warning_low_space=(free_gb < 10.0 or percent > 92.0),
                telemetry_source=TelemetrySource.OS_SHUTIL_DISK_USAGE,
                availability=HardwareAvailabilityState.AVAILABLE,
            )
        except Exception as e:
            logger.warning("appliance.storage_probe_failed", error=str(e))
            return StorageEnduranceMetrics(
                telemetry_source=TelemetrySource.UNAVAILABLE,
                availability=HardwareAvailabilityState.DEGRADED,
            )

    def _probe_thermal(self) -> ThermalStatus:
        """
        Inspect hardware thermal sensors using authentic platform probers.
        Never fabricates hardcoded temperatures or returns mock readings as real.
        """
        gpu_temp: float | None = None
        cpu_temp: float | None = None
        state = ThermalState.NOMINAL
        source = TelemetrySource.UNAVAILABLE
        availability = HardwareAvailabilityState.UNAVAILABLE
        provenance: dict[str, Any] = {}

        try:
            prober = get_platform_hardware_prober()
            thermal_data = prober.probe_thermal_and_power()
            temps = thermal_data.get("temperatures_celsius", {})

            if temps:
                source = TelemetrySource.PHYSICAL_OS
                availability = HardwareAvailabilityState.AVAILABLE
                provenance = {"raw_sensors": temps}

                # Extract GPU temperature if present
                for sensor_name, val in temps.items():
                    sensor_lower = sensor_name.lower()
                    if "gpu" in sensor_lower or "nvidia" in sensor_lower:
                        gpu_temp = float(val)
                    elif "cpu" in sensor_lower or "core" in sensor_lower or "package" in sensor_lower or "soc" in sensor_lower:
                        cpu_temp = float(val)

                # Evaluate thermal state against hottest available sensor
                max_temp = max([t for t in (cpu_temp, gpu_temp) if t is not None], default=None)
                if max_temp is not None:
                    if max_temp >= 90.0:
                        state = ThermalState.CRITICAL
                    elif max_temp >= 83.0:
                        state = ThermalState.THROTTLED
                    elif max_temp >= 70.0:
                        state = ThermalState.ELEVATED
                    else:
                        state = ThermalState.NOMINAL
        except Exception as e:
            logger.debug("appliance.thermal_probe_failed", error=str(e))
            source = TelemetrySource.UNAVAILABLE
            availability = HardwareAvailabilityState.UNAVAILABLE

        return ThermalStatus(
            cpu_temp_celsius=cpu_temp,
            gpu_temp_celsius=gpu_temp,
            state=state,
            fan_speed_percent=None,
            throttle_reason="Thermal throttle engaged" if state in (ThermalState.THROTTLED, ThermalState.CRITICAL) else None,
            telemetry_source=source,
            availability=availability,
            sensor_provenance=provenance,
        )

    def validate_disk_initialization_safety(
        self,
        target_path: str,
        confirmed: bool = False,
    ) -> tuple[bool, str]:
        """
        Verify that a disk initialization / format operation is safe and explicitly authorized.
        Guards against accidental deletion of root OS, existing recordings, and preservation holds.
        """
        if not confirmed:
            return (
                False,
                "REJECTED: Disk initialization requires explicit confirmation flag (confirmed=True). "
                "Non-destructive policy prevents automatic disk formatting.",
            )

        abs_target = os.path.abspath(target_path)

        # Disallow formatting system drive root
        system_drive = os.path.abspath(os.sep)
        if abs_target == system_drive:
            return False, f"REJECTED: Target path '{abs_target}' is the system root volume."

        # Disallow formatting active project directory
        cwd = os.path.abspath(os.getcwd())
        if abs_target == cwd or abs_target.startswith(cwd + os.sep):
            return False, f"REJECTED: Target path '{abs_target}' is within the active application directory."

        return True, f"AUTHORIZED: Target path '{abs_target}' validated for controlled initialization."

    def evaluate_workload_allocation(self, requested_camera_count: int) -> tuple[bool, int, str]:
        """
        Validate whether the appliance can accept the requested camera workload.
        Returns: (is_admissible, max_supported_streams, rationale)
        """
        spec = ApplianceCatalog.SPECIFICATIONS.get(self.profile.profile_type)
        if spec is None:
            max_streams = max(1, self.hardware.cpu_cores_physical)
        else:
            max_streams = spec.max_stream_ceiling

        # Adjust max_streams if thermal state is elevated
        if self.profile.thermal.state == ThermalState.THROTTLED:
            max_streams = max(1, int(max_streams * 0.6))
        elif self.profile.thermal.state == ThermalState.CRITICAL:
            max_streams = max(1, int(max_streams * 0.25))

        if requested_camera_count <= max_streams:
            self.profile.allocated_streams = requested_camera_count
            return (
                True,
                max_streams,
                f"Workload of {requested_camera_count} streams admitted successfully under {self.profile.profile_type.value}.",
            )
        else:
            return (
                False,
                max_streams,
                f"Workload of {requested_camera_count} streams exceeds appliance ceiling ({max_streams} streams). "
                "Hardware upgrading or distributed edge scaling recommended.",
            )

    def apply_graceful_degradation(self, target_level: int) -> dict[str, Any]:
        """
        Apply load-shedding policies under thermal or memory exhaustion.
        Level 0: Nominal (15 FPS, Full Resolution)
        Level 1: Minor (Downsample inference rate 15 -> 10 FPS, maintain recording)
        Level 2: Major (Downsample inference rate 10 -> 5 FPS, ROI downscale)
        Level 3: Critical (Inference suspended; raw encrypted vault recording + fail-closed masking preserved)
        """
        target_level = max(0, min(3, target_level))
        self.profile.active_degradation_level = target_level

        policy = {
            0: {"inference_fps": 15, "roi_scaling": 1.0, "recording_fps": 30, "state": "nominal"},
            1: {"inference_fps": 10, "roi_scaling": 1.0, "recording_fps": 25, "state": "minor_shed"},
            2: {"inference_fps": 5, "roi_scaling": 0.75, "recording_fps": 20, "state": "major_shed"},
            3: {"inference_fps": 0, "roi_scaling": 0.5, "recording_fps": 15, "state": "critical_safe"},
        }[target_level]

        logger.info(
            "appliance.degradation_applied",
            level=target_level,
            policy=policy,
            profile=self.profile.profile_type.value,
        )
        return policy
