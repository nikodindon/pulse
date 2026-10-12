"""Rolling history buffers that back every sparkline in the UI."""

from __future__ import annotations

from .util import RingBuffer

DEFAULT_SIZE = 180


class History:
    """Named ring buffers plus lazily created per-device series."""

    def __init__(self, size: int = DEFAULT_SIZE) -> None:
        self.size = size
        self.series: dict[str, RingBuffer] = {}
        self._device_series: dict[str, dict[str, RingBuffer]] = {}

    def buffer(self, name: str) -> RingBuffer:
        buf = self.series.get(name)
        if buf is None:
            buf = self.series[name] = RingBuffer(self.size)
        return buf

    def device_buffer(self, group: str, device: str) -> RingBuffer:
        bucket = self._device_series.setdefault(group, {})
        buf = bucket.get(device)
        if buf is None:
            buf = bucket[device] = RingBuffer(self.size)
        return buf

    def prune_devices(self, group: str, live_devices: list[str]) -> None:
        bucket = self._device_series.get(group)
        if not bucket:
            return
        live = set(live_devices)
        for name in list(bucket):
            if name not in live:
                del bucket[name]

    def update(self, data: dict) -> None:
        """Push one sample of every tracked metric."""
        cpu = data.get("cpu") or {}
        if cpu:
            self.buffer("cpu").push(cpu.get("total", 0.0))
            self.buffer("load").push(cpu.get("load1", 0.0) if "load1" in cpu else 0.0)
            self.buffer("user").push((cpu.get("breakdown") or {}).get("user", 0.0))
            self.buffer("system").push((cpu.get("breakdown") or {}).get("system", 0.0))
            self.buffer("iowait").push((cpu.get("breakdown") or {}).get("iowait", 0.0))
            self.buffer("steal").push((cpu.get("breakdown") or {}).get("steal", 0.0))
            freq = cpu.get("freq_avg")
            if freq:
                self.buffer("freq").push(freq / 1e9)
            cores = cpu.get("cores") or []
            for idx, value in enumerate(cores):
                self.device_buffer("core", str(idx)).push(value)

        memory = data.get("memory") or {}
        if memory:
            total = memory.get("total") or 1
            self.buffer("mem").push(100.0 * memory.get("used", 0) / total)
            swap_total = memory.get("swap_total") or 0
            if swap_total:
                self.buffer("swap").push(100.0 * memory.get("swap_used", 0) / swap_total)

        system = data.get("system") or {}
        if system:
            loadavg = system.get("loadavg") or (0.0, 0.0, 0.0)
            self.buffer("loadavg").push(loadavg[0])

        network = data.get("network") or {}
        ifaces = network.get("interfaces") or []
        total_rx = total_tx = 0.0
        for iface in ifaces:
            name = iface["name"]
            self.device_buffer("net_rx", name).push(iface.get("rx_bps", 0.0))
            self.device_buffer("net_tx", name).push(iface.get("tx_bps", 0.0))
            if name != "lo":
                total_rx += iface.get("rx_bps", 0.0)
                total_tx += iface.get("tx_bps", 0.0)
        self.prune_devices("net_rx", [i["name"] for i in ifaces])
        self.prune_devices("net_tx", [i["name"] for i in ifaces])
        if ifaces:
            self.buffer("net_rx").push(total_rx)
            self.buffer("net_tx").push(total_tx)

        disk = data.get("disk") or {}
        for device in disk.get("devices") or []:
            name = device["name"]
            self.device_buffer("disk_read", name).push(device.get("read_bps", 0.0))
            self.device_buffer("disk_write", name).push(device.get("write_bps", 0.0))
            self.device_buffer("disk_util", name).push(device.get("util", 0.0))
        self.prune_devices("disk_read", [d["name"] for d in disk.get("devices") or []])
        self.prune_devices("disk_write", [d["name"] for d in disk.get("devices") or []])

        filesystems = data.get("filesystems") or {}
        for fs in filesystems.get("filesystems") or []:
            self.device_buffer("fs", fs["mount"]).push(fs.get("used_pct", 0.0))

        gpu = data.get("gpu") or {}
        for gpu_index, g in enumerate(gpu.get("gpus") or []):
            if g.get("util") is not None:
                self.buffer(f"gpu_util_{gpu_index}").push(g.get("util", 0.0))
            if g.get("temp"):
                self.buffer(f"gpu_temp_{gpu_index}").push(g["temp"])

        sensors = data.get("sensors") or {}
        if sensors:
            for temp in sensors.get("temps") or []:
                self.device_buffer("temp", f"{temp['chip']}/{temp['label']}").push(temp["value"])

        processes = data.get("processes") or {}
        if processes:
            self.buffer("proc_count").push(processes.get("count", 0))

    def values(self, name: str) -> list[float]:
        buf = self.series.get(name)
        return buf.values() if buf else []

    def trend(self, name: str, window: int = 6, epsilon: float = 0.5) -> str:
        """Direction of the last few samples: up / down / flat / none."""
        buf = self.series.get(name)
        if buf is None:
            return "none"
        data = buf.last(window)
        if len(data) < 3:
            return "none"
        head = sum(data[:-len(data) // 2]) / max(1, len(data) - len(data) // 2)
        tail = sum(data[len(data) // 2:]) / max(1, len(data) // 2)
        delta = tail - head
        if abs(delta) < epsilon:
            return "flat"
        return "up" if delta > 0 else "down"

    def device_trend(self, group: str, device: str, window: int = 6,
                     epsilon: float = 0.5) -> str:
        bucket = self._device_series.get(group) or {}
        buf = bucket.get(device)
        if buf is None:
            return "none"
        data = buf.last(window)
        if len(data) < 3:
            return "none"
        half = len(data) // 2
        head = sum(data[:-half]) / max(1, len(data) - half)
        tail = sum(data[half:]) / half
        delta = tail - head
        if abs(delta) < epsilon:
            return "flat"
        return "up" if delta > 0 else "down"

    def device_values(self, group: str, device: str) -> list[float]:
        bucket = self._device_series.get(group) or {}
        buf = bucket.get(device)
        return buf.values() if buf else []

    def resize(self, size: int) -> None:
        self.size = size
        for buf in self.series.values():
            buf.resize(size)
        for bucket in self._device_series.values():
            for buf in bucket.values():
                buf.resize(size)

    def clear(self) -> None:
        for buf in self.series.values():
            buf.clear()
        for bucket in self._device_series.values():
            for buf in bucket.values():
                buf.clear()