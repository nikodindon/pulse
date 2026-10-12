"""Shared collector infrastructure and /proc + /sys reading helpers."""

from __future__ import annotations

import os
import threading
import time


class SampleState:
    """Holds the previous value of a monotonic counter to derive a rate."""

    __slots__ = ("prev", "prev_ts")

    def __init__(self) -> None:
        self.prev: float | None = None
        self.prev_ts: float | None = None

    def rate(self, current: float) -> float:
        now = time.monotonic()
        if self.prev is None or self.prev_ts is None:
            self.prev = current
            self.prev_ts = now
            return 0.0
        delta = float(current) - float(self.prev)
        elapsed = now - self.prev_ts
        self.prev = current
        self.prev_ts = now
        if elapsed <= 0:
            return 0.0
        return delta / elapsed

    def reset(self) -> None:
        self.prev = None
        self.prev_ts = None


class Collector:
    """Base collector. `collect()` must be fast and must never raise."""

    name = "collector"
    interval = 1.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_error: str | None = None
        self._last_payload: dict | None = None

    def collect(self) -> dict:
        raise NotImplementedError

    def take(self) -> dict:
        with self._lock:
            try:
                result = self.collect()
                self.last_error = None
                return result
            except Exception as exc:  # a broken probe must not kill the UI
                self.last_error = f"{type(exc).__name__}: {exc}"
                return {}

    def slow_collect(self) -> dict:
        """For collectors that only need refreshing every few seconds."""
        return self.take()


# ---------------------------------------------------------------------------
# File readers
# ---------------------------------------------------------------------------


def read_text(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return default


def read_int(path: str, default: int = 0) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return default


def read_float(path: str, default: float | None = 0.0) -> float | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return float(handle.read().strip())
    except (OSError, ValueError):
        return default


def read_lines(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except OSError:
        return []


def exists(path: str) -> bool:
    return os.path.exists(path)


def listdir(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default