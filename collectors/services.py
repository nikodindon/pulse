"""systemd service inventory: running, failed and enabled units.

Invoking `systemctl` is expensive (hundreds of milliseconds), so the whole
inventory is gathered with a *single* call: `list-units --all` already reports
the state of every loaded unit, from which running/failed counts are derived.
The (much slower) unit-file listing is refreshed far less often.
"""

from __future__ import annotations

import shutil
import subprocess
import time

from .base import Collector


class ServicesCollector(Collector):
    name = "services"
    interval = 8.0
    unit_file_interval = 120.0

    def __init__(self) -> None:
        super().__init__()
        self._systemctl = shutil.which("systemctl")
        self._enabled_count = 0
        self._enabled_ts = 0.0
        self._cache: dict = {"services": [], "failed_units": [],
                             "counts": {}, "available": False}

    def _run(self, args: list[str], timeout: float = 4.0) -> str:
        if not self._systemctl:
            return ""
        try:
            proc = subprocess.run(
                [self._systemctl, *args],
                capture_output=True, text=True, timeout=timeout,
            )
            return proc.stdout if proc.returncode == 0 else ""
        except (subprocess.SubprocessError, OSError):
            return ""

    def _refresh_enabled(self, now: float) -> int:
        if now - self._enabled_ts < self.unit_file_interval:
            return self._enabled_count
        self._enabled_ts = now
        output = self._run(["list-unit-files", "--type=service", "--state=enabled",
                            "--no-pager", "--plain", "--no-legend"])
        count = 0
        for line in output.splitlines():
            unit = line.split()
            if unit and unit[0].endswith(".service") and not unit[0].startswith("#"):
                count += 1
        self._enabled_count = count
        return count

    def collect(self) -> dict:
        if not self._systemctl:
            self._cache["available"] = False
            return self._cache

        now = time.monotonic()
        output = self._run([
            "list-units", "--type=service", "--all",
            "--no-pager", "--plain", "--no-legend",
        ])

        services: list[dict] = []
        failed: list[str] = []
        running = 0
        for line in output.splitlines():
            parts = line.split()
            if not parts or not parts[0].endswith(".service"):
                continue
            # systemctl --plain columns: UNIT LOAD ACTIVE SUB DESCRIPTION...
            state = parts[3] if len(parts) > 3 else ""
            if state == "running":
                running += 1
                services.append({
                    "unit": parts[0],
                    "description": " ".join(parts[4:]) if len(parts) > 4 else "",
                })
            elif state == "failed":
                failed.append(parts[0])

        services.sort(key=lambda s: s["unit"])
        enabled = self._refresh_enabled(now)

        self._cache = {
            "available": True,
            "services": services,
            "failed_units": failed,
            "counts": {
                "running": running,
                "failed": len(failed),
                "enabled": enabled,
                "total": running + len(failed),
            },
        }
        return self._cache