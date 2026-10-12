"""Hardware sensors: temperatures, fans, voltages and power from /sys/class."""

from __future__ import annotations

from .base import Collector, listdir, read_float, read_int, read_text


class SensorsCollector(Collector):
    """Reads hwmon, thermal zones and cooling devices straight from sysfs."""

    name = "sensors"
    interval = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._hwmons: list[dict] | None = None
        self._zones: list[dict] | None = None

    def _discover_hwmons(self) -> list[dict]:
        groups: list[dict] = []
        for entry in listdir("/sys/class/hwmon"):
            path = f"/sys/class/hwmon/{entry}"
            chip = read_text(path + "/name") or entry
            features: list[dict] = []
            for fname in listdir(path):
                if not fname.endswith("_input"):
                    continue
                kind = fname[: -len("_input")]
                if kind.startswith("temp"):
                    unit, scale = "°C", 0.001
                elif kind.startswith("fan"):
                    unit, scale = "RPM", 1.0
                elif kind.startswith("in"):
                    unit, scale = "V", 0.001
                elif kind.startswith("power"):
                    unit, scale = "W", 1e-6
                elif kind.startswith("curr"):
                    unit, scale = "A", 0.001
                else:
                    continue
                label = read_text(f"{path}/{kind}_label") or kind
                max_val = read_float(f"{path}/{kind}_max", None)
                crit_val = read_float(f"{path}/{kind}_crit", None)
                features.append({
                    "label": label, "kind": kind, "path": f"{path}/{fname}",
                    "unit": unit, "scale": scale, "max": max_val, "crit": crit_val,
                    "value": None,
                })
            if features:
                groups.append({"chip": chip, "path": path, "features": features})
        return groups

    def _discover_zones(self) -> list[dict]:
        zones = []
        for entry in listdir("/sys/class/thermal"):
            if not entry.startswith("thermal_zone"):
                continue
            path = f"/sys/class/thermal/{entry}"
            zones.append({
                "label": read_text(path + "/type") or entry,
                "path": path + "/temp",
                "kind": "temp", "unit": "°C", "scale": 0.001,
                "max": read_float(path + "/trip_point_0_temp", None),
                "crit": None, "value": None,
            })
        return zones

    def collect(self) -> dict:
        if self._hwmons is None:
            self._hwmons = self._discover_hwmons()
            self._zones = self._discover_zones()

        temps: list[dict] = []
        fans: list[dict] = []
        voltages: list[dict] = []
        powers: list[dict] = []

        for group in self._hwmons:
            for feature in group["features"]:
                raw = read_float(feature["path"], None)
                if raw is None:
                    continue
                value = raw * feature["scale"]
                feature["value"] = value
                entry = {
                    "chip": group["chip"],
                    "label": feature["label"],
                    "value": value,
                    "unit": feature["unit"],
                    "max": feature["max"] * feature["scale"] if feature["max"] else None,
                    "crit": feature["crit"] * feature["scale"] if feature["crit"] else None,
                }
                kind = feature["kind"]
                if kind.startswith("temp"):
                    temps.append(entry)
                elif kind.startswith("fan"):
                    fans.append(entry)
                elif kind.startswith("in"):
                    voltages.append(entry)
                elif kind.startswith("power"):
                    powers.append(entry)

        for zone in self._zones:
            raw = read_float(zone["path"], None)
            if raw is None:
                continue
            value = raw * zone["scale"]
            temps.append({
                "chip": "thermal",
                "label": zone["label"],
                "value": value,
                "unit": "°C",
                "max": zone["max"] * zone["scale"] if zone["max"] else None,
                "crit": None,
            })

        max_temp = max((t["value"] for t in temps), default=None)
        avg_temp = (sum(t["value"] for t in temps) / len(temps)) if temps else None
        return {
            "temps": temps,
            "fans": fans,
            "voltages": voltages,
            "powers": powers,
            "max_temp": max_temp,
            "avg_temp": avg_temp,
            "fan_total_rpm": sum(f["value"] for f in fans),
        }


class CoolingCollector(Collector):
    """CPU/machine cooling devices and their current throttling level."""

    name = "cooling"
    interval = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._devices: list[dict] | None = None

    def _discover(self) -> list[dict]:
        devices = []
        for entry in listdir("/sys/class/thermal"):
            if not entry.startswith("cooling_device"):
                continue
            path = f"/sys/class/thermal/{entry}"
            devices.append({
                "id": read_int(path + "/type", 0),
                "type": f"cooling_device_{entry.split('_')[-1]}",
                "path": path,
                "cur_state": read_int(path + "/cur_state", 0),
                "max_state": read_int(path + "/max_state", 0),
            })
        return devices

    def collect(self) -> dict:
        if self._devices is None:
            self._devices = self._discover()
        out = []
        throttled = 0
        for device in self._devices:
            cur = read_int(device["path"] + "/cur_state", device["cur_state"])
            max_state = max(1, device["max_state"])
            out.append({**device, "cur_state": cur, "ratio": cur / max_state})
            if cur > 0 and max_state > 1:
                throttled += 1
        return {"devices": out, "throttled": throttled}