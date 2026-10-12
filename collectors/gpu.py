"""GPU statistics: NVIDIA via nvidia-smi, DRM/Intel/AMD via sysfs."""

from __future__ import annotations

import os
import shutil
import subprocess

from .base import Collector, listdir, read_float, read_int, read_text, safe_int

NVIDIA_FIELDS = (
    "name", "utilization.gpu", "utilization.memory",
    "memory.total", "memory.used", "memory.free",
    "temperature.gpu", "power.draw", "power.limit", "fan.speed",
    "clocks.current.graphics", "clocks.current.memory", "clocks.current.sm",
)


class GpuCollector(Collector):
    name = "gpu"
    interval = 3.0

    def __init__(self) -> None:
        super().__init__()
        self._vendor = None
        self._nvidia_bin = shutil.which("nvidia-smi")
        self._cards: list[str] | None = None
        self._nvidia_cache: list[dict] = []

    def _detect_vendor(self) -> str:
        if self._nvidia_bin and "nvidia" in read_text("/proc/driver/nvidia/version", ""):
            return "nvidia"
        if os.path.exists("/sys/class/drm/card1/device/vendor") or any(
                read_text(f"/sys/class/drm/{card}/device/vendor", "").strip() == "0x10de"
                for card in listdir("/sys/class/drm") if card.startswith("card")):
            return "nvidia"
        for card in listdir("/sys/class/drm"):
            if not card.startswith("card") or card[4:].isdigit() and "-" in card:
                continue
            vendor = read_text(f"/sys/class/drm/{card}/device/vendor", "")
            if vendor == "0x10de":
                return "nvidia"
            if vendor == "0x8086":
                return "intel"
            if vendor == "0x1002":
                return "amd"
        if os.path.exists("/dev/dri/card0"):
            return "unknown"
        return "none"

    def _query_nvidia(self) -> list[dict]:
        if not self._nvidia_bin:
            return []
        try:
            proc = subprocess.run(
                [self._nvidia_bin, "--query-gpu=" + ",".join(NVIDIA_FIELDS),
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3.0,
            )
            if proc.returncode != 0:
                return []
            gpus = []
            for line in proc.stdout.strip().splitlines():
                cols = [c.strip() for c in line.split(",")]
                if len(cols) != len(NVIDIA_FIELDS):
                    continue
                gpu = dict(zip(NVIDIA_FIELDS, cols))
                gpus.append({
                    "name": gpu["name"],
                    "util": safe_int(gpu["utilization.gpu"]),
                    "util_mem": safe_int(gpu["utilization.memory"]),
                    "mem_total": safe_int(gpu["memory.total"]) * 1024 * 1024,
                    "mem_used": safe_int(gpu["memory.used"]) * 1024 * 1024,
                    "mem_pct": round(100.0 * safe_int(gpu["memory.used"]) / max(1, safe_int(gpu["memory.total"]))) if safe_int(gpu.get("memory.total", 0)) else None,
                    "mem_free": safe_int(gpu["memory.free"]) * 1024 * 1024,
                    "temp": safe_int(gpu["temperature.gpu"]),
                    "power": safe_int(gpu["power.draw"]),
                    "power_limit": safe_int(gpu["power.limit"]),
                    "fan": safe_int(gpu["fan.speed"]),
                    "clock_gfx": safe_int(gpu["clocks.current.graphics"]),
                    "clock_mem": safe_int(gpu["clocks.current.memory"]),
                    "clock_sm": safe_int(gpu["clocks.current.sm"]),
                })
            return gpus
        except (subprocess.SubprocessError, OSError):
            return []

    def _query_drm(self) -> list[dict]:
        gpus = []
        for entry in listdir("/sys/class/drm"):
            if not entry.startswith("card") or not entry[4:].isdigit():
                continue
            base = f"/sys/class/drm/{entry}/device"
            if not os.path.exists(base):
                continue
            vendor_map = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}
            vendor_id = read_text(base + "/vendor", "")
            vendor = vendor_map.get(vendor_id, vendor_id)
            util = read_int(base + "/gpu_busy_percent", -1)
            mem_total = read_int(base + "/mem_info_vram_total", 0)
            mem_used = read_int(base + "/mem_info_vram_used", 0)
            power_watts = None
            for entry_name in listdir(base):
                if entry_name.startswith("power"):
                    ppath = f"{base}/{entry_name}"
                    for attr_file in ("power1_average", "power1_input"):
                        value = read_float(f"{ppath}/{attr_file}", None)
                        if value is not None:
                            power_watts = value / 1e6
                            break
                    if power_watts is not None:
                        break
            gpus.append({
                "name": f"{vendor} GPU ({entry})" if vendor else entry,
                "util": util if util >= 0 else 0,
                "util_known": util >= 0,
                "mem_total": mem_total,
                "mem_used": mem_used,
                "mem_pct": round(100.0 * mem_used / mem_total, 1) if mem_total else None,
                "power": power_watts,
                "driver": read_text(base + "/driver", "").split("/")[-1],
            })
        return gpus

    def collect(self) -> dict:
        if self._vendor is None:
            self._vendor = self._detect_vendor()
        if self._vendor == "nvidia":
            gpus = self._query_nvidia()
            if gpus:
                return {"vendor": "nvidia", "gpus": gpus}
        gpus = self._query_drm()
        return {"vendor": self._vendor, "gpus": gpus}