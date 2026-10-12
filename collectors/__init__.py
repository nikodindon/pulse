"""Collector registry. Owns every probe and exposes a single `sample()` call."""

from __future__ import annotations

from .base import Collector, SampleState
from .cpu import CpuCollector
from .disk import DiskCollector, FilesystemCollector
from .memory import MemoryCollector
from .network import NetworkCollector, SocketsCollector
from .processes import ProcessCollector
from .sensors import CoolingCollector, SensorsCollector
from .services import ServicesCollector
from .system import BatteryCollector, ContainerCollector, SystemCollector

try:
    from .gpu import GpuCollector
except Exception:
    GpuCollector = None


class Registry:
    """Instantiates the collectors and dispatches `sample()` based on each
    collector's declared interval. Fast collectors run every cycle; slow ones
    only run when their interval has elapsed."""

    def __init__(self) -> None:
        self.collectors: dict[str, Collector] = {}
        self.intervals: dict[str, float] = {}
        self._last_run: dict[str, float] = {}

        self._register("system", SystemCollector())
        self._register("cpu", CpuCollector())
        self._register("memory", MemoryCollector())
        self._register("disk", DiskCollector())
        self._register("filesystems", FilesystemCollector())
        self._register("network", NetworkCollector())
        self._register("sockets", SocketsCollector())
        self._register("sensors", SensorsCollector())
        self._register("cooling", CoolingCollector())
        self._register("processes", ProcessCollector())
        self._register("services", ServicesCollector())
        self._register("battery", BatteryCollector())
        self._register("containers", ContainerCollector())
        if GpuCollector is not None:
            self._register("gpu", GpuCollector())

    def _register(self, name: str, collector: Collector) -> None:
        self.collectors[name] = collector
        self.intervals[name] = collector.interval
        self._last_run[name] = 0.0

    def sample(self, now: float) -> dict:
        result: dict = {}
        for name, collector in self.collectors.items():
            if now - self._last_run[name] >= self.intervals[name] - 1e-6:
                result[name] = collector.take()
                self._last_run[name] = now
            else:
                # Not due yet: serve the previous payload so the UI can render
                # every frame without waiting on a slow probe.
                if collector._last_payload is not None:
                    result[name] = collector._last_payload
            payload = result.get(name)
            if payload is not None:
                collector._last_payload = payload
        return result


__all__ = [
    "Registry", "SampleState", "Collector",
    "CpuCollector", "MemoryCollector", "DiskCollector", "FilesystemCollector",
    "NetworkCollector", "SocketsCollector", "SensorsCollector", "CoolingCollector",
    "ProcessCollector", "ServicesCollector", "SystemCollector",
    "BatteryCollector", "ContainerCollector",
]