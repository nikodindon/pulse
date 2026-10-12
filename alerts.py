"""Threshold evaluation.

Every metric that can go wrong is mapped onto a four-level severity scale
(ok / warn / high / critical) so the interface can colour things consistently:
a red number always means the same thing, whatever panel it appears in.
"""

from __future__ import annotations

from dataclasses import dataclass

OK, WARN, HIGH, CRITICAL = 0, 1, 2, 3

LEVEL_NAMES = {OK: "ok", WARN: "warn", HIGH: "high", CRITICAL: "critical"}

# (warn, high, critical) thresholds per metric family, in percent or degrees.
# Swap is deliberately lax: Linux swaps proactively long before memory runs
# out, so only a nearly-full swap is worth reporting.
THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "cpu": (60.0, 80.0, 92.0),
    "mem": (70.0, 85.0, 94.0),
    "swap": (55.0, 78.0, 92.0),
    "temp": (60.0, 72.0, 84.0),
    "disk": (60.0, 80.0, 92.0),
    "fs": (75.0, 88.0, 95.0),
    "inodes": (70.0, 85.0, 93.0),
    "gpu_temp": (65.0, 78.0, 88.0),
    "gpu_util": (85.0, 93.0, 98.0),
    "load": (80.0, 140.0, 200.0),
}

COLORS = {
    OK: (46, 204, 113),
    WARN: (241, 196, 15),
    HIGH: (243, 156, 18),
    CRITICAL: (231, 76, 60),
}


def severity(value: float | None, family: str) -> int:
    """Map a measurement onto the severity scale for its metric family."""
    if value is None:
        return OK
    warn, high, critical = THRESHOLDS.get(family, THRESHOLDS["cpu"])
    if value >= critical:
        return CRITICAL
    if value >= high:
        return HIGH
    if value >= warn:
        return WARN
    return OK


def worst(*levels: int) -> int:
    result = OK
    for level in levels:
        if level > result:
            result = level
    return result


@dataclass
class Alert:
    key: str
    label: str
    level: int
    value: str
    hint: str = ""


def evaluate(data: dict) -> list[Alert]:
    """Scan a sampling snapshot and return every metric above 'warn'.

    The list is ordered by severity so the UI can show the worst offender
    first and the header can summarise the rest with a count.
    """
    alerts: list[Alert] = []

    cpu = data.get("cpu") or {}
    if cpu:
        total = cpu.get("total", 0.0)
        level = severity(total, "cpu")
        if level >= WARN:
            alerts.append(Alert("cpu", "CPU", level, f"{total:.0f}%",
                                "load élevé" if level < CRITICAL else "surchauffe CPU"))
        run = cpu.get("running", 0)
        if run > 0:
            run_level = severity(min(100.0, run * 100.0 / max(1, len(cpu.get("cores") or [1]))), "cpu")
            if run_level >= HIGH and level < run_level:
                alerts.append(Alert("runq", "RUN QUEUE", run_level, str(run),
                                    "processus en attente"))

    memory = data.get("memory") or {}
    if memory:
        total_mem = memory.get("total") or 0
        used_pct = 100.0 * memory.get("used", 0) / total_mem if total_mem else 0.0
        level = severity(used_pct, "mem")
        if level >= WARN:
            alerts.append(Alert("mem", "RAM", level, f"{used_pct:.0f}%", "mémoire saturée"))
        swap_total = memory.get("swap_total") or 0
        if swap_total:
            swap_pct = 100.0 * memory.get("swap_used", 0) / swap_total
            swap_level = severity(swap_pct, "swap")
            if swap_level >= WARN:
                alerts.append(Alert("swap", "SWAP", swap_level, f"{swap_pct:.0f}%",
                                    "pression mémoire"))

    sensors = data.get("sensors") or {}
    for temp in sensors.get("temps") or []:
        level = severity(temp.get("value"), "temp")
        if level >= WARN:
            alerts.append(Alert(
                f"temp-{temp['chip']}-{temp['label']}",
                f"{temp['chip']} {temp['label']}", level,
                f"{temp['value']:.0f}°C", "surchauffe"))

    gpu = data.get("gpu") or {}
    for index, device in enumerate(gpu.get("gpus") or []):
        temp = device.get("temp")
        if temp:
            level = severity(temp, "gpu_temp")
            if level >= WARN:
                alerts.append(Alert(f"gputemp-{index}", f"GPU {index}", level,
                                    f"{temp:.0f}°C", "GPU surchauffée"))
        util = device.get("util")
        if util is not None:
            level = severity(util, "gpu_util")
            if level >= WARN:
                alerts.append(Alert(f"gpuutil-{index}", f"GPU {index}", level,
                                    f"{util:.0f}%", "GPU saturée"))

    for fs in (data.get("filesystems") or {}).get("filesystems") or []:
        level = severity(fs.get("used_pct"), "fs")
        if level >= HIGH:
            alerts.append(Alert(f"fs-{fs['mount']}", fs["mount"], level,
                                f"{fs['used_pct']:.0f}%", "disque plein"))

    for device in (data.get("disk") or {}).get("devices") or []:
        level = severity(device.get("util"), "disk")
        if level >= CRITICAL:
            alerts.append(Alert(f"disk-{device['name']}", device["name"], level,
                                f"{device['util']:.0f}%", "I/O saturé"))

    services = data.get("services") or {}
    failed = (services.get("counts") or {}).get("failed", 0)
    if failed:
        alerts.append(Alert("services", "SERVICES", HIGH if failed > 2 else WARN,
                            str(failed), "unités systemd en échec"))

    if not alerts:
        return []

    alerts.sort(key=lambda a: (-a.level, a.label))
    return alerts