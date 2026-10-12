"""Storage statistics: block-device throughput, utilisation and filesystems."""

from __future__ import annotations

import os

from .base import Collector, SampleState, listdir, read_int, read_lines, read_text, safe_int

SECTOR = 512

_PARTITION_FILTER = ("sd", "nvme", "vd", "hd", "mmcblk")


class DiskCollector(Collector):
    name = "disk"
    interval = 1.0

    def __init__(self) -> None:
        super().__init__()
        self._rates: dict[str, SampleState] = {}
        self._devices: list[dict] | None = None

    def _discover(self) -> list[dict]:
        devices: list[dict] = []
        for name in listdir("/sys/block"):
            if name.startswith("loop") or name.startswith("ram") or name.startswith("dm-"):
                continue
            base = f"/sys/block/{name}"
            devices.append({
                "name": name,
                "size_bytes": read_int(base + "/size", 0) * SECTOR,
                "rotational": read_int(base + "/queue/rotational", 0) == 1,
                "model": read_text(base + "/device/model").strip() or name,
                "vendor": read_text(base + "/device/vendor").strip(),
                "removable": read_int(base + "/removable", 0) == 1,
            })
        return devices

    def _read_diskstats(self) -> dict[str, dict]:
        stats: dict[str, dict] = {}
        for line in read_lines("/proc/diskstats"):
            parts = line.split()
            if len(parts) < 14:
                continue
            name = parts[2]
            is_partition = bool(name) and name[-1].isdigit() and not name.startswith("nvme")
            if name.startswith("nvme") and "p" in name and name.rsplit("p", 1)[-1].isdigit():
                is_partition = True
            if is_partition:
                continue
            try:
                stats[name] = {
                    "read_sectors": safe_int(parts[3]),
                    "read_ops": safe_int(parts[4]),
                    "write_sectors": safe_int(parts[7]),
                    "write_ops": safe_int(parts[8]),
                    "read_ticks": safe_int(parts[6]),
                    "write_ticks": safe_int(parts[10]),
                    "io_ticks": safe_int(parts[12]),
                    "weighted_ticks": safe_int(parts[13]),
                }
            except (IndexError, ValueError):
                continue
        return stats

    def collect(self) -> dict:
        if self._devices is None:
            self._devices = self._discover()
        stats = self._read_diskstats()

        devices = []
        for dev in self._devices:
            name = dev["name"]
            raw = stats.get(name)
            state = self._rates.setdefault(name, SampleState())
            if raw is None:
                devices.append({**dev, "read_bps": 0.0, "write_bps": 0.0,
                                "read_iops": 0.0, "write_iops": 0.0, "util": 0.0,
                                "read_total": 0, "write_total": 0})
                continue
            read_bps = state.rate(raw["read_sectors"] * SECTOR)
            state_r = self._rates.setdefault(name + ":r", SampleState())
            write_bps = state_r.rate(raw["write_sectors"] * SECTOR)
            state_ri = self._rates.setdefault(name + ":ri", SampleState())
            read_iops = state_ri.rate(raw["read_ops"])
            state_wi = self._rates.setdefault(name + ":wi", SampleState())
            write_iops = state_wi.rate(raw["write_ops"])
            state_u = self._rates.setdefault(name + ":u", SampleState())
            io_ticks_per_sec = state_u.rate(raw["io_ticks"])
            util = min(100.0, io_ticks_per_sec * 10.0 / 100.0)
            state_t = self._rates.setdefault(name + ":await", SampleState())
            read_ticks_rate = state_t.rate(raw["read_ticks"])
            state_tw = self._rates.setdefault(name + ":awaitw", SampleState())
            write_ticks_rate = state_tw.rate(raw["write_ticks"])
            total_io_ms = read_ticks_rate + write_ticks_rate
            total_ops = read_iops + write_iops
            await_ms = (total_io_ms / total_ops) if total_ops > 0 else 0.0
            devices.append({
                **dev,
                "read_bps": read_bps,
                "write_bps": write_bps,
                "read_iops": read_iops,
                "write_iops": write_iops,
                "util": util,
                "await_ms": await_ms,
                "read_total": raw["read_sectors"] * SECTOR,
                "write_total": raw["write_sectors"] * SECTOR,
            })
        return {"devices": devices}


class FilesystemCollector(Collector):
    """Mounted filesystem usage with inode accounting."""

    name = "filesystems"
    interval = 10.0

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[str] = set()

    def _iter_mounts(self):
        for line in read_lines("/proc/mounts"):
            parts = line.split()
            if len(parts) < 3:
                continue
            device, mount, fstype = parts[0], parts[1], parts[2]
            if not mount.startswith("/"):
                continue
            if fstype in ("proc", "sysfs", "devtmpfs", "devpts", "cgroup", "cgroup2",
                          "securityfs", "pstore", "bpf", "tracefs", "debugfs",
                          "hugetlbfs", "mqueue", "configfs", "fusectl", "autofs",
                          "binfmt_misc", "nsfs", "ramfs", "squashfs", "efivarfs",
                          "systemd-1", "rpc_pipefs"):
                continue
            if any(mount.startswith(p) for p in ("/snap", "/var/lib/docker/overlay2/merged")):
                if mount.startswith("/snap"):
                    continue
            yield device, mount, fstype

    def collect(self) -> dict:
        filesystems = []
        seen: set[str] = set()
        for device, mount, fstype in self._iter_mounts():
            try:
                stat = os.statvfs(mount)
            except OSError:
                continue
            size = stat.f_blocks * stat.f_frsize
            free = stat.f_bfree * stat.f_frsize
            avail = stat.f_bavail * stat.f_frsize
            used = max(0, size - free)
            total_inodes = stat.f_files
            free_inodes = stat.f_ffree
            inodes_used = max(0, total_inodes - free_inodes)
            seen.add(mount)
            filesystems.append({
                "device": device,
                "mount": mount,
                "fstype": fstype,
                "total": size,
                "used": used,
                "free": free,
                "available": avail,
                "used_pct": (100.0 * used / size) if size else 0.0,
                "total_inodes": total_inodes,
                "used_inodes": inodes_used,
                "inode_pct": (100.0 * inodes_used / total_inodes) if total_inodes else 0.0,
            })
        # Only refresh the mount cache occasionally to avoid statvfs storms.
        if self._seen and len(self._seen) == len(seen):
            pass
        self._seen = seen
        return {"filesystems": filesystems}