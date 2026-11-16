"""
camserv.platform.windows.hardware
=================================

Microsoft Windows hardware telemetry, GPU discovery, and memory diagnostics.
Integrates nvidia-smi parsing, Windows Win32 memory status, and DirectX telemetry.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from camserv.platform.shared.interfaces import PlatformHardwareProber


class WindowsHardwareProber(PlatformHardwareProber):
    """Probes Windows host hardware, memory status, and GPU accelerators."""

    def probe_cpu_and_ram(self) -> dict[str, Any]:
        logical_cores = os.cpu_count() or 1
        ram_total_mb = 2048
        ram_avail_mb = 1024

        try:
            import psutil
            vm = psutil.virtual_memory()
            ram_total_mb = int(vm.total / (1024 * 1024))
            ram_avail_mb = int(vm.available / (1024 * 1024))
        except ImportError:
            # Fallback to kernel32 GlobalMemoryStatusEx via ctypes
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_total_mb = int(stat.ullTotalPhys / (1024 * 1024))
                ram_avail_mb = int(stat.ullAvailPhys / (1024 * 1024))

        return {
            "os": "Windows",
            "logical_cores": logical_cores,
            "physical_cores": max(1, logical_cores // 2),
            "ram_total_mb": ram_total_mb,
            "ram_available_mb": ram_avail_mb,
        }

    def probe_gpus(self) -> list[dict[str, Any]]:
        gpus: list[dict[str, Any]] = []
        nvsmi = shutil.which("nvidia-smi") or (
            os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "nvidia-smi.exe")
        )

        if os.path.exists(nvsmi):
            try:
                out = subprocess.check_output(
                    [nvsmi, "--query-gpu=index,name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"],
                    text=True,
                    timeout=5,
                )
                for line in out.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 5:
                        gpus.append({
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_total_mb": int(parts[2]),
                            "memory_free_mb": int(parts[3]),
                            "driver_version": parts[4],
                        })
            except Exception:
                pass
        return gpus

    def probe_thermal_and_power(self) -> dict[str, Any]:
        """Query GPU temperature via nvidia-smi if dedicated graphics present."""
        nvsmi = shutil.which("nvidia-smi")
        temps: dict[str, float] = {}
        if nvsmi:
            try:
                out = subprocess.check_output(
                    [nvsmi, "--query-gpu=name,temperature.gpu", "--format=csv,noheader,nounits"],
                    text=True,
                    timeout=5,
                )
                for line in out.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2:
                        temps[parts[0]] = float(parts[1])
            except Exception:
                pass
        return {"temperatures_celsius": temps}
