"""CPU statistics: utilisation, per-core breakdown, frequency and topology."""

from __future__ import annotations

import os

from .base import Collector, SampleState, listdir, read_int, read_lines, read_text, safe_int

CPU_STAT_FIELDS = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")


class CpuCollector(Collector):
    name = "cpu"
    interval = 1.0

    def __init__(self) -> None:
        super().__init__()
        self._prev_total: list[int] | None = None
        self._prev_cores: list[list[int]] | None = None
        self._prev_extra: dict[str, int] | None = None
        self._per_core_freq_state: dict[int, SampleState] = {}
        self._static: dict | None = None
        self._core_paths: list[str] | None = None

    # -- /proc/stat ---------------------------------------------------------
    def _read_stat(self) -> tuple[list[int], list[list[int]], dict[str, int]]:
        total: list[int] = []
        cores: list[list[int]] = []
        extra: dict[str, int] = {}
        in_cpu_section = True
        for line in read_lines("/proc/stat"):
            if in_cpu_section and line.startswith("cpu"):
                parts = line.split()
                fields = [safe_int(p) for p in parts[1:8]]
                if parts[0] == "cpu":
                    total = fields
                else:
                    cores.append(fields)
                continue
            in_cpu_section = False
            parts = line.split()
            if len(parts) < 2:
                continue
            key = parts[0]
            if key in ("intr", "ctxt", "processes", "procs_running",
                       "procs_blocked", "btime"):
                extra[key] = safe_int(parts[1])
        return total, cores, extra

    @staticmethod
    def _split(parts: list[int], prev: list[int] | None) -> dict[str, float]:
        """Per-field percentages between two /proc/stat snapshots."""
        if not prev or len(prev) != len(parts) or len(parts) < 4:
            return {name: 0.0 for name in CPU_STAT_FIELDS}
        delta = [max(0, parts[i] - prev[i]) for i in range(len(parts))]
        total = sum(delta)
        if total <= 0:
            return {name: 0.0 for name in CPU_STAT_FIELDS}
        result = {}
        for idx, name in enumerate(CPU_STAT_FIELDS[: len(delta)]):
            result[name] = 100.0 * delta[idx] / total
        return result

    # -- static info --------------------------------------------------------
    def _load_static(self) -> dict:
        info = {
            "model": "Unknown",
            "vendor": "",
            "logical": os.cpu_count() or 0,
            "physical": 0,
            "sockets": 1,
            "cores_per_socket": 0,
            "l2": None,
            "l3": None,
            "hypervisor": False,
            "flags": set(),
            "online": [],
            "freq_min": None,
            "freq_max": None,
            "governor": None,
            "governors": set(),
            "scaling": True,
        }
        self._parse_cpuinfo(info)
        self._parse_topology(info)
        self._parse_freq(info)
        return info

    def _parse_cpuinfo(self, info: dict) -> None:
        for line in read_lines("/proc/cpuinfo"):
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if key == "model name" and rest:
                info["model"] = rest
            elif key == "vendor_id" and rest and not info["vendor"]:
                info["vendor"] = rest
            elif key == "cache size" and rest:
                info["l3"] = rest
            elif key == "flags" and rest:
                flags = set(rest.split())
                info["flags"] = flags
                if "hypervisor" in flags:
                    info["hypervisor"] = True
        info["logical"] = os.cpu_count() or info["logical"]

    def _parse_topology(self, info: dict) -> None:
        cores: dict[tuple[str, str], int] = {}
        sockets: set[str] = set()
        for line in read_lines("/proc/cpuinfo"):
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if key == "physical id":
                sockets.add(rest)
            elif key == "core id" and sockets:
                cores[(sorted(sockets)[0], rest)] = 1
        # A second pass pairing physical id with core id per processor.
        pairs: set[tuple[str, str]] = set()
        current_socket = ""
        for line in read_lines("/proc/cpuinfo"):
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if key == "physical id":
                current_socket = rest
            elif key == "core id" and current_socket:
                pairs.add((current_socket, rest))
        sockets_count = len(sockets) or 1
        info["sockets"] = sockets_count
        info["physical"] = len(pairs) or max(1, (info["logical"] // 2))
        info["cores_per_socket"] = info["physical"] // sockets_count if sockets_count else info["physical"]

    def _parse_freq(self, info: dict) -> None:
        cpu0 = "/sys/devices/system/cpu/cpu0/cpufreq"
        if not os.path.isdir(cpu0):
            info["scaling"] = False
            info["governor"] = read_text("/sys/devices/system/cpu/cpufreq/scaling_governor") or None
            return
        info["scaling"] = True
        fmin = read_int(cpu0 + "/scaling_min_freq", 0)
        fmax = read_int(cpu0 + "/scaling_max_freq", 0)
        info["freq_min"] = fmin * 1000 if fmin else None
        info["freq_max"] = fmax * 1000 if fmax else None
        info["governor"] = read_text(cpu0 + "/scaling_governor") or None
        governors: set[str] = set()
        for entry in listdir("/sys/devices/system/cpu"):
            if not entry.startswith("cpu") or not entry[3:].isdigit():
                continue
            gov = read_text(f"/sys/devices/system/cpu/{entry}/cpufreq/scaling_governor")
            if gov:
                governors.add(gov)
        info["governors"] = governors

    def _discover_core_paths(self, count: int) -> list[str]:
        paths = []
        for idx in range(count):
            path = f"/sys/devices/system/cpu/cpu{idx}/cpufreq/scaling_cur_freq"
            if os.path.exists(path):
                paths.append(path)
        return paths

    def _read_loadavg(self) -> tuple[float, float, float]:
        try:
            with open("/proc/loadavg", "r", encoding="utf-8") as handle:
                one, five, fifteen, _rest = handle.read().split()[:4]
            return float(one), float(five), float(fifteen)
        except (OSError, ValueError):
            return 0.0, 0.0, 0.0

    # -- collection ---------------------------------------------------------
    def collect(self) -> dict:
        if self._static is None:
            self._static = self._load_static()
        static = self._static

        total, cores, extra = self._read_stat()

        if self._prev_total is None:
            self._prev_total, self._prev_cores, self._prev_extra = total, cores, extra
            total_pct = 0.0
            core_pct = [0.0] * len(cores)
            breakdown = {name: 0.0 for name in CPU_STAT_FIELDS}
            core_breakdowns = [dict(breakdown) for _ in cores]
            ctxt_rate = intr_rate = procs_rate = 0.0
        else:
            breakdown = self._split(total, self._prev_total)
            total_pct = 100.0 - breakdown.get("idle", 0.0) - breakdown.get("iowait", 0.0)
            core_pct = []
            core_breakdowns = []
            for cur, prev in zip(cores, self._prev_cores or []):
                parts = self._split(cur, prev)
                core_pct.append(100.0 - parts.get("idle", 0.0) - parts.get("iowait", 0.0))
                core_breakdowns.append(parts)
            state = self._per_core_freq_state.setdefault("__ctxt", SampleState())
            ctxt_rate = state.rate(extra.get("ctxt", 0))
            state = self._per_core_freq_state.setdefault("__intr", SampleState())
            intr_rate = state.rate(extra.get("intr", 0))
            state = self._per_core_freq_state.setdefault("__proc", SampleState())
            procs_rate = state.rate(extra.get("processes", 0))
            self._prev_total, self._prev_cores, self._prev_extra = total, cores, extra

        if self._core_paths is None:
            self._core_paths = self._discover_core_paths(len(cores))
        freqs = []
        for path in self._core_paths:
            khz = read_int(path, 0)
            freqs.append(khz * 1000 if khz else None)

        load1, load5, load15 = self._read_loadavg()
        static["load1"] = load1
        static["load5"] = load5
        static["load15"] = load15

        avg_freq = None
        valid = [f for f in freqs if f]
        if valid:
            avg_freq = sum(valid) / len(valid)

        online = listdir("/sys/devices/system/cpu")
        online = [e for e in online if e.startswith("cpu") and e[3:].isdigit()
                  and read_text(f"/sys/devices/system/cpu/{e}/online", "1") == "1"]

        return {
            "total": max(0.0, min(100.0, total_pct)),
            "cores": core_pct,
            "breakdown": breakdown,
            "core_breakdowns": core_breakdowns,
            "frequencies": freqs,
            "freq_avg": avg_freq,
            "static": static,
            "running": extra.get("procs_running", 0),
            "blocked": extra.get("procs_blocked", 0),
            "ctxt_rate": ctxt_rate,
            "intr_rate": intr_rate,
            "proc_rate": procs_rate,
            "online_count": len(online),
        }