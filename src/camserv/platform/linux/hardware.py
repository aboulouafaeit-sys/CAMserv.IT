"""
camserv.platform.linux.hardware
===============================

Linux hardware telemetry, thermal probing, and GPU metrics discovery.
Inspects sysfs (/sys/class/thermal) and /proc filesystem.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from typing import Any

from camserv.platform.shared.interfaces import PlatformHardwareProber


class LinuxHardwareProber(PlatformHardwareProber):
    """Probes Linux hardware diagnostics and sensors."""

    def probe_cpu_and_ram(self) -> dict[str, Any]:
        logical_cores = os.cpu_count() or 1
        ram_total_mb = 1024
        ram_avail_mb = 512

        try:
            import psutil
            vm = psutil.virtual_memory()
            ram_total_mb = int(vm.total / (1024 * 1024))
            ram_avail_mb = int(vm.available / (1024 * 1024))
        except ImportError:
            if os.path.exists("/proc/meminfo"):
                try:
                    with open("/proc/meminfo", "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("MemTotal:"):
                                ram_total_mb = int(line.split()[1]) // 1024
                            elif line.startswith("MemAvailable:"):
                                ram_avail_mb = int(line.split()[1]) // 1024
                except OSError:
                    pass

        return {
            "os": "Linux",
            "logical_cores": logical_cores,
            "physical_cores": max(1, logical_cores // 2),
            "ram_total_mb": ram_total_mb,
            "ram_available_mb": ram_avail_mb,
        }

    def probe_gpus(self) -> list[dict[str, Any]]:
        gpus: list[dict[str, Any]] = []
        nvsmi = shutil.which("nvidia-smi")
        if nvsmi:
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
        temps: dict[str, float] = {}
        for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
            name_file = os.path.join(zone, "type")
            temp_file = os.path.join(zone, "temp")
            if os.path.exists(temp_file):
                try:
                    name = os.path.basename(zone)
                    if os.path.exists(name_file):
                        with open(name_file, "r", encoding="utf-8") as f:
                            name = f.read().strip()
                    with open(temp_file, "r", encoding="utf-8") as f:
                        milli_c = int(f.read().strip())
                        temps[name] = round(milli_c / 1000.0, 1)
                except (OSError, ValueError):
                    pass
        return {"temperatures_celsius": temps}
