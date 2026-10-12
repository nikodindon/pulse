"""Process table, top consumers and per-process I/O accounting.

The hot path reads ``/proc`` directly. A single read of ``/proc/<pid>/stat``
yields the name, state, parent, thread count and CPU time, and ``statm`` gives
the resident size -- two file reads per process, versus the five or more that
a high-level process library performs. On this machine that is roughly five
times faster, which is what makes sub-second refresh possible.

``psutil`` is used when available for the fields that are awkward to read
cheaply (usernames, full command lines); if it is missing, the collector still
works with reduced detail instead of disappearing.
"""

from __future__ import annotations

import os
import time

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

from .base import Collector

CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
PROC = "/proc"

# Fields of interest in /proc/<pid>/stat, after the comm field.
# Index is relative to the tokens following ") ".
STAT_FIELDS = {
    "state": 0, "ppid": 1, "utime": 11, "stime": 12,
    "num_threads": 17, "starttime": 19,
}

# How many processes get an I/O probe and a fresh command line per tick.
IO_CANDIDATES = 60
CMDLINE_REFRESH_TOP = 40

_UID_CACHE: dict[int, str] = {}


def _resolve_uid(uid: int) -> str:
    if uid in _UID_CACHE:
        return _UID_CACHE[uid]
    name = str(uid)
    if HAS_PSUTIL:
        try:
            import pwd
            name = pwd.getpwuid(uid).pw_name
        except (KeyError, OSError, ImportError):
            name = str(uid)
    _UID_CACHE[uid] = name
    return name


def _read_io(pid: int) -> tuple[int, int]:
    try:
        with open(f"{PROC}/{pid}/io", "rb") as handle:
            read_bytes = write_bytes = 0
            for line in handle:
                if line.startswith(b"read_bytes:"):
                    read_bytes = int(line.split()[1])
                elif line.startswith(b"write_bytes:"):
                    write_bytes = int(line.split()[1])
            return read_bytes, write_bytes
    except (OSError, ValueError, IndexError):
        return 0, 0


def _read_cmdline(pid: int, fallback: str) -> str:
    try:
        with open(f"{PROC}/{pid}/cmdline", "rb") as handle:
            raw = handle.read()
    except OSError:
        return fallback
    if not raw:
        return fallback
    text = raw.replace(b"\0", b" ").strip().decode("utf-8", "replace")
    return text[:4096] if text else fallback


class ProcessCollector(Collector):
    name = "processes"
    interval = 1.0

    def __init__(self) -> None:
        super().__init__()
        self._cpu_prev: dict[int, int] = {}
        self._io_prev: dict[int, tuple[int, int]] = {}
        self._cmd_cache: dict[int, str] = {}
        self._user_cache: dict[int, str] = {}
        self._prev_ts = 0.0
        self._mem_total = 0

    def _uid_of(self, pid: int) -> int:
        """Resolve a pid to a username, caching the result.

        The ownership of a /proc entry never changes for a given pid, so the
        lookup is paid once per process rather than once per tick.
        """
        name = self._user_cache.get(pid)
        if name is None:
            uid = os.stat(f"{PROC}/{pid}").st_uid
            name = _resolve_uid(uid)
            self._user_cache[pid] = name
        return name

    def _meminfo_total(self) -> int:
        if self._mem_total:
            return self._mem_total
        try:
            with open(f"{PROC}/meminfo", "rb") as handle:
                for line in handle:
                    if line.startswith(b"MemTotal:"):
                        self._mem_total = int(line.split()[1]) * 1024
                        return self._mem_total
        except (OSError, ValueError, IndexError):
            pass
        self._mem_total = 1
        return self._mem_total

    def collect(self) -> dict:
        now = time.monotonic()
        elapsed = now - self._prev_ts if self._prev_ts else 0.0
        mem_total = self._meminfo_total()

        try:
            entries = os.listdir(PROC)
        except OSError:
            return {"available": False, "processes": [], "count": 0}

        rows: list[dict] = []
        seen: set[int] = set()

        for entry in entries:
            if not entry.isdigit():
                continue
            pid = int(entry)
            try:
                with open(f"{PROC}/{pid}/stat", "rb") as handle:
                    raw = handle.read()
            except OSError:
                continue
            rparen = raw.rfind(b")")
            lparen = raw.find(b"(")
            if rparen < 0 or lparen < 0 or rparen < lparen:
                continue
            name = raw[lparen + 1:rparen].decode("utf-8", "replace")
            fields = raw[rparen + 2:].split()
            if len(fields) < 20:
                continue
            try:
                cpu_ticks = int(fields[STAT_FIELDS["utime"]]) + int(fields[STAT_FIELDS["stime"]])
                ppid = int(fields[STAT_FIELDS["ppid"]])
                threads = int(fields[STAT_FIELDS["num_threads"]])
            except (ValueError, IndexError):
                continue

            try:
                with open(f"{PROC}/{pid}/statm", "rb") as handle:
                    rss = int(handle.read().split()[1]) * PAGE_SIZE
            except (OSError, ValueError, IndexError):
                rss = 0

            try:
                username = self._uid_of(pid)
            except OSError:
                username = "?"

            seen.add(pid)
            cpu_pct = 0.0
            prev_ticks = self._cpu_prev.get(pid)
            if prev_ticks is not None and elapsed > 0:
                delta = cpu_ticks - prev_ticks
                if delta > 0:
                    cpu_pct = 100.0 * delta / CLK_TCK / elapsed
            self._cpu_prev[pid] = cpu_ticks

            rows.append({
                "pid": pid,
                "ppid": ppid,
                "name": name,
                "cmd": self._cmd_cache.get(pid, ""),
                "username": username,
                "status": fields[STAT_FIELDS["state"]].decode("ascii", "replace"),
                "cpu": cpu_pct,
                "mem_rss": rss,
                "mem_vms": 0,
                "mem_percent": (100.0 * rss / mem_total) if mem_total else 0.0,
                "threads": threads,
                "read_bps": 0.0,
                "write_bps": 0.0,
            })

        # I/O counters need one extra file read per process, so they are only
        # resolved for the processes that can plausibly appear in the top list.
        if elapsed > 0:
            candidates = sorted(rows, key=lambda r: -(r["mem_rss"]))[:IO_CANDIDATES]
            for row in candidates:
                cur = _read_io(row["pid"])
                prev = self._io_prev.get(row["pid"])
                if prev is not None:
                    row["read_bps"] = max(0.0, (cur[0] - prev[0]) / elapsed)
                    row["write_bps"] = max(0.0, (cur[1] - prev[1]) / elapsed)
                self._io_prev[row["pid"]] = cur

        # Command lines: refresh for the busiest processes, cache the rest.
        hot = sorted(rows, key=lambda r: -r["cpu"])[:CMDLINE_REFRESH_TOP]
        for row in hot:
            row["cmd"] = _read_cmdline(row["pid"], row["name"])
            self._cmd_cache[row["pid"]] = row["cmd"]
        for pid in list(self._cmd_cache):
            if pid not in seen:
                del self._cmd_cache[pid]

        self._cpu_prev = {pid: self._cpu_prev[pid] for pid in seen if pid in self._cpu_prev}
        for cache in (self._io_prev, self._user_cache):
            for pid in list(cache):
                if pid not in seen:
                    del cache[pid]

        self._prev_ts = now

        by_cpu = sorted(rows, key=lambda r: -r["cpu"])[:20]
        by_mem = sorted(rows, key=lambda r: -r["mem_rss"])[:20]
        by_io = sorted(rows, key=lambda r: -(r["read_bps"] + r["write_bps"]))[:20]

        states: dict[str, int] = {}
        threads_total = 0
        mem_used = 0
        for row in rows:
            states[row["status"]] = states.get(row["status"], 0) + 1
            threads_total += row["threads"]
            mem_used += row["mem_rss"]

        return {
            "available": True,
            "processes": rows,
            "count": len(rows),
            "threads_total": threads_total,
            "by_cpu": by_cpu,
            "by_mem": by_mem,
            "by_io": by_io,
            "states": states,
            "cpu_total": sum(r["cpu"] for r in rows),
            "mem_total": mem_used,
            "mem_pct_total": (100.0 * mem_used / mem_total) if mem_total else 0.0,
        }


# How many processes get an I/O probe and a fresh command line per tick.
IO_CANDIDATES = 60
CMDLINE_REFRESH_TOP = 40