"""Memory statistics: RAM, cache, swap, paging and slab usage."""

from __future__ import annotations

from .base import Collector, SampleState, listdir, read_int, read_lines, safe_int

KIB = 1024


class MemoryCollector(Collector):
    name = "memory"
    interval = 1.0

    def __init__(self) -> None:
        super().__init__()
        self._meminfo: dict[str, int] | None = None
        self._vm_states: dict[str, SampleState] = {}
        self._modules: list[dict] | None = None

    def _read_meminfo(self) -> dict[str, int]:
        info: dict[str, int] = {}
        for line in read_lines("/proc/meminfo"):
            key, _, rest = line.partition(":")
            parts = rest.split()
            if not parts:
                continue
            value = safe_int(parts[0])
            unit = parts[1] if len(parts) > 1 else "kB"
            if unit.lower() == "kb":
                value *= KIB
            info[key.strip()] = value
        return info

    def _read_vmstat(self) -> dict[str, int]:
        vm: dict[str, int] = {}
        for line in read_lines("/proc/vmstat"):
            key, _, rest = line.partition(":")
            vm[key.strip()] = safe_int(rest.strip())
        return vm

    def _read_slabs(self) -> dict[str, int]:
        slabs: dict[str, int] = {}
        for entry in listdir("/sys/kernel/slab"):
            path = f"/sys/kernel/slab/{entry}/object_size"
            size = read_int(path, 0)
            if not size:
                continue
            slabs[entry] = size
        return slabs

    def collect(self) -> dict:
        if self._meminfo is None:
            self._meminfo = self._read_meminfo()
            self._modules = self._read_modules()
        mem = self._meminfo
        vm = self._read_vmstat()

        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", mem.get("MemFree", 0))
        free = mem.get("MemFree", 0)
        shared = mem.get("Shmem", 0)
        buffers = mem.get("Buffers", 0)
        slab = mem.get("Slab", 0)
        reclaimable = mem.get("SReclaimable", 0)
        unreclaimable = max(0, slab - reclaimable)
        cached = mem.get("Cached", 0)
        pagecache = cached + reclaimable
        used = max(0, total - free - buffers - pagecache - slab)
        # `used` for display purposes should agree with `top`: total - available
        top_used = max(0, total - available)

        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapCached", 0)
        swap_avail = mem.get("SwapFree", 0)
        swap_used = max(0, swap_total - swap_avail)

        def rate(key: str, counter: float) -> float:
            state = self._vm_states.get(key)
            if state is None:
                state = self._vm_states[key] = SampleState()
            return state.rate(counter)

        pages_in = vm.get("pswpin", 0) * KIB
        pages_out = vm.get("pswpout", 0) * KIB

        huge_total = mem.get("HugePages_Total", 0)
        huge_free = mem.get("HugePages_Free", 0)
        huge_size = mem.get("Hugepagesize", 0)

        return {
            "total": total,
            "available": available,
            "free": free,
            "used": top_used,
            "app_used": used,
            "buffers": buffers,
            "cached": cached,
            "pagecache": pagecache,
            "shared": shared,
            "slab": slab,
            "reclaimable": reclaimable,
            "unreclaimable": unreclaimable,
            "swap_total": swap_total,
            "swap_used": swap_used,
            "swap_free": swap_avail,
            "swap_cached": swap_free,
            "paged_in_rate": rate("pswpin", pages_in),
            "paged_out_rate": rate("pswpout", pages_out),
            "pgfault_rate": rate("pgfault", vm.get("pgfault", 0)),
            "pgmajfault_rate": rate("pgmajfault", vm.get("pgmajfault", 0)),
            "huge_pages_total": huge_total,
            "huge_pages_free": huge_free,
            "huge_page_size": huge_size,
            "committed_as": mem.get("Committed_AS", 0),
            "commit_limit": mem.get("CommitLimit", 0),
            "vm": vm,
            "modules": self._modules or [],
        }

    def _read_modules(self) -> list[dict]:
        modules = []
        for line in read_lines("/proc/modules"):
            parts = line.split()
            if len(parts) >= 3:
                modules.append({"name": parts[0], "size": safe_int(parts[1])})
        modules.sort(key=lambda m: -m["size"])
        return modules[:40]