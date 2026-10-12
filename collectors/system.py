"""System identity: host, distro, kernel, DMI hardware and battery state."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time

from .base import Collector, listdir, read_text


class SystemCollector(Collector):
    name = "system"
    interval = 3.0

    def __init__(self) -> None:
        super().__init__()
        self._static: dict | None = None
        self._boot_time = None

    def _os_release(self) -> dict:
        info = {}
        for line in read_text("/etc/os-release", "").splitlines():
            key, _, value = line.partition("=")
            info[key.strip()] = value.strip().strip('"')
        return info

    def _dmi(self, name: str) -> str:
        return read_text(f"/sys/class/dmi/id/{name}", "")

    def _load_static(self) -> dict:
        osr = self._os_release()
        uname = os.uname()
        try:
            with open("/etc/hostname", "r") as handle:
                hostname = handle.read().strip()
        except OSError:
            hostname = uname.nodename
        return {
            "hostname": hostname,
            "kernel": uname.release,
            "distro": osr.get("PRETTY_NAME", "Linux"),
            "distro_id": osr.get("ID", ""),
            "arch": uname.machine,
            "vendor": self._dmi("sys_vendor"),
            "product": self._dmi("product_name"),
            "board": self._dmi("board_name"),
            "bios_vendor": self._dmi("bios_vendor"),
            "bios_version": self._dmi("bios_version"),
            "chassis": self._dmi("chassis_type"),
            "python": platform.python_version(),
        }

    def _uptime(self) -> float:
        try:
            with open("/proc/uptime", "r") as handle:
                return float(handle.read().split()[0])
        except (OSError, ValueError):
            return 0.0

    def collect(self) -> dict:
        if self._static is None:
            self._static = self._load_static()
            self._boot_time = time.time() - self._uptime()
        uptime = self._uptime()
        return {
            **self._static,
            "uptime": uptime,
            "boot_time": self._boot_time,
            "loadavg": os.getloadavg(),
            "load_per_core": os.getloadavg()[0] / (os.cpu_count() or 1),
        }


class BatteryCollector(Collector):
    """Laptop battery charge, power draw and time remaining."""

    name = "battery"
    interval = 10.0

    def __init__(self) -> None:
        super().__init__()
        self._batteries: list[str] | None = None

    def collect(self) -> dict:
        if self._batteries is None:
            self._batteries = [
                entry for entry in listdir("/sys/class/power_supply")
                if read_text(f"/sys/class/power_supply/{entry}/type", "") == "Battery"
            ]
        packs = []
        for name in self._batteries:
            base = f"/sys/class/power_supply/{name}"
            try:
                capacity = int(read_text(base + "/capacity", "0"))
            except ValueError:
                capacity = 0
            status = read_text(base + "/status", "Unknown")
            energy_now = read_text(base + "/energy_now", "")
            power_now = read_text(base + "/power_now", "")
            try:
                discharge_w = int(power_now) / 1_000_000 if power_now else 0.0
            except ValueError:
                discharge_w = 0.0
            remaining = 0.0
            try:
                if energy_now and discharge_w > 0:
                    remaining = int(energy_now) / 1_000_000 / discharge_w
            except ValueError:
                remaining = 0.0
            packs.append({
                "name": name,
                "capacity": capacity,
                "status": status,
                "power_w": discharge_w,
                "remaining": remaining,
                "charging": status == "Charging",
            })
        return {"batteries": packs, "present": bool(packs)}


class ContainerCollector(Collector):
    """Docker / Podman container counts when a local socket is available."""

    name = "containers"
    interval = 30.0

    def __init__(self) -> None:
        super().__init__()
        self._docker = shutil.which("docker")
        self._podman = shutil.which("podman")

    def collect(self) -> dict:
        binary = self._docker or self._podman
        if not binary:
            return {"available": False, "running": 0, "total": 0, "engine": "none"}
        try:
            proc = subprocess.run(
                [binary, "ps", "-q"], capture_output=True, text=True, timeout=4.0,
            )
            if proc.returncode != 0:
                return {"available": False, "running": 0, "total": 0, "engine": "none"}
            running = len([line for line in proc.stdout.splitlines() if line.strip()])
        except (subprocess.SubprocessError, OSError):
            return {"available": False, "running": 0, "total": 0, "engine": "none"}
        return {
            "available": True,
            "running": running,
            "engine": "docker" if self._docker else "podman",
        }