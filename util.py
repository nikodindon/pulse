"""Formatting and small helpers shared across Pulse."""

from __future__ import annotations

import datetime as dt
import math
import shutil
import time

_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB")


def now() -> float:
    return time.monotonic()


def human_bytes(value: float, precision: int = 1) -> str:
    if value is None:
        return "-"
    value = float(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    idx = 0
    while value >= 1024.0 and idx < len(_UNITS) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{sign}{int(value)} {_UNITS[0]}"
    return f"{sign}{value:.{precision}f} {_UNITS[idx]}"


def human_bytes_per_sec(value: float, precision: int = 1) -> str:
    return f"{human_bytes(value, precision)}/s"


def human_bits_per_sec(value: float, precision: int = 1) -> str:
    value = float(value) * 8.0
    idx = 0
    units = ("bit/s", "Kbit/s", "Mbit/s", "Gbit/s", "Tbit/s")
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return f"{value:.{precision}f} {units[idx]}"


def human_count(value: float, precision: int = 1) -> str:
    if value is None:
        return "-"
    for limit, suffix in ((1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= limit:
            return f"{value / limit:.{precision}f}{suffix}"
    return f"{value:.0f}"


def pct(value: float, width: int = 0) -> str:
    if value is None:
        text = "-"
    else:
        text = f"{value:.0f}%"
    return text.rjust(width) if width else text


def hz_to_text(hz: float | None) -> str:
    if not hz:
        return "-"
    hz = float(hz)
    if hz >= 1e9:
        return f"{hz / 1e9:.2f} GHz"
    if hz >= 1e6:
        return f"{hz / 1e6:.0f} MHz"
    return f"{hz:.0f} Hz"


def hz_to_mhz(hz: float | None) -> float:
    if not hz:
        return 0.0
    return float(hz) / 1e6


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def human_time(epoch: float | None) -> str:
    if not epoch:
        return "-"
    return dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def clock() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def term_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        return a / b
    except (ZeroDivisionError, TypeError):
        return default


def percent_of(part: float, whole: float) -> float:
    if not whole:
        return 0.0
    return clamp(100.0 * float(part) / float(whole), 0.0, 100.0)


def read_file(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return default


def read_int(path: str, default: int = 0) -> int:
    try:
        return int(read_file(path, str(default)))
    except (ValueError, OSError):
        return default


def read_float(path: str, default: float = 0.0) -> float:
    try:
        return float(read_file(path, str(default)))
    except (ValueError, OSError):
        return default


def terminal_supports_unicode() -> bool:
    import os

    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        if "utf" in os.environ.get(var, "").lower():
            return True
    return False


class RingBuffer:
    """Fixed-size history for sparklines."""

    def __init__(self, size: int = 120):
        self.size = size
        self._values: list[float] = []

    def push(self, value: float) -> None:
        self._values.append(float(value))
        if len(self._values) > self.size:
            del self._values[: len(self._values) - self.size]

    def values(self) -> list[float]:
        return self._values

    def last(self, count: int = 1) -> list[float]:
        return self._values[-count:]

    def max(self, default: float = 0.0) -> float:
        return max(self._values) if self._values else default

    def average(self, count: int | None = None) -> float:
        data = self._values if count is None else self._values[-count:]
        if not data:
            return 0.0
        return sum(data) / len(data)

    def resize(self, size: int) -> None:
        self.size = size
        if len(self._values) > size:
            del self._values[: len(self._values) - size]

    def clear(self) -> None:
        self._values.clear()


def sparkline_points(values: list[float], width: int, low: float | None = None, high: float | None = None) -> list[float]:
    """Map a series to `width` normalised points in [0, 1]."""
    if width <= 0:
        return []
    data = values[-width:] if len(values) > width else values
    if not data:
        return []
    lo = min(data) if low is None else low
    hi = max(data) if high is None else high
    if hi - lo < 1e-9:
        hi = lo + 1.0
    return [clamp((v - lo) / (hi - lo), 0.0, 1.0) for v in data]


def smooth(values: list[float], factor: float = 0.35) -> float:
    if not values:
        return 0.0
    smoothed = values[0]
    for value in values[1:]:
        smoothed = smoothed * (1 - factor) + value * factor
    return smoothed


def fmt_kv(key: str, value: str, width: int) -> str:
    return f"{key + ':':<{width}}{value}"


def deg(value: float | None, precision: int = 0) -> str:
    if value is None:
        return "-"
    return f"{value:.{precision}f}"


def mib(bytes_value: float | None) -> str:
    if bytes_value is None:
        return "-"
    return f"{bytes_value / (1024 * 1024):,.0f}"


def approx_int(value: float) -> int:
    return int(math.floor(value + 0.5))


def trend(values: list[float], window: int = 6, epsilon: float = 0.5) -> str:
    """Direction of the tail of a series: 'up' / 'down' / 'flat' / 'none'."""
    if not values:
        return "none"
    data = values[-window:]
    if len(data) < 3:
        return "none"
    half = len(data) // 2
    head = sum(data[:-half]) / max(1, len(data) - half)
    tail = sum(data[half:]) / half
    delta = tail - head
    if abs(delta) < epsilon:
        return "flat"
    return "up" if delta > 0 else "down"