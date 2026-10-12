"""Network statistics: interface rates, addresses and TCP/UDP state counts."""

from __future__ import annotations

import socket
import struct

from .base import Collector, SampleState, listdir, read_int, read_lines, read_text, safe_int

_TCP_STATES = {
    "01": "ESTABLISHED", "02": "SYN_SENT", "03": "SYN_RECV", "04": "FIN_WAIT1",
    "05": "FIN_WAIT2", "06": "TIME_WAIT", "07": "CLOSE", "08": "CLOSE_WAIT",
    "09": "LAST_ACK", "0A": "LISTEN", "0B": "CLOSING",
}

WELL_KNOWN_PORTS = {
    22: "ssh", 25: "smtp", 53: "dns", 80: "http", 110: "pop3", 143: "imap",
    443: "https", 445: "smb", 993: "imaps", 995: "pop3s", 3306: "mysql",
    5432: "postgres", 6379: "redis", 8080: "http-alt", 8443: "https-alt",
    27017: "mongodb", 5000: "flask", 3000: "node", 9000: "portainer",
}


class NetworkCollector(Collector):
    name = "network"
    interval = 1.0

    def __init__(self) -> None:
        super().__init__()
        self._rates: dict[str, SampleState] = {}
        self._addresses: dict[str, list[str]] | None = None
        self._meta_cache: dict[str, dict] = {}

    def _read_net_dev(self) -> dict[str, dict]:
        data: dict[str, dict] = {}
        lines = read_lines("/proc/net/dev")
        for line in lines[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            cols = rest.split()
            if len(cols) < 16:
                continue
            data[name] = {
                "rx_bytes": safe_int(cols[0]), "rx_packets": safe_int(cols[1]),
                "rx_errors": safe_int(cols[2]), "rx_drop": safe_int(cols[3]),
                "tx_bytes": safe_int(cols[8]), "tx_packets": safe_int(cols[9]),
                "tx_errors": safe_int(cols[10]), "tx_drop": safe_int(cols[11]),
            }
        return data

    def _iface_meta(self, name: str) -> dict:
        base = f"/sys/class/net/{name}"
        # Neg speed/duplex/mtu are stable for the life of an interface, so they
        # are read once instead of on every tick.
        static = self._meta_cache.get(name)
        if static is None:
            static = self._meta_cache[name] = {
                "speed_mbps": read_int(base + "/speed", -1),
                "mtu": read_int(base + "/mtu", 0),
                "duplex": read_text(base + "/duplex", ""),
            }
        return {
            **static,
            "state": read_text(base + "/operstate", "unknown"),
            "carrier": read_int(base + "/carrier", 0) == 1,
        }

    def _read_addresses(self) -> dict[str, list[str]]:
        addrs: dict[str, list[str]] = {}
        try:
            import fcntl
        except ImportError:
            return addrs
        for name in listdir("/sys/class/net"):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                packed = struct.pack("256s", name.encode("utf-8")[:15])
                addr = fcntl.ioctl(sock.fileno(), 0x8915, packed)[20:24]
                ip = socket.inet_ntoa(addr)
                sock.close()
                if ip and ip != "0.0.0.0":
                    addrs.setdefault(name, []).append(ip)
            except OSError:
                pass
        return addrs

    def collect(self) -> dict:
        raw = self._read_net_dev()
        if self._addresses is None:
            self._addresses = self._read_addresses()
        addrs = self._addresses or {}

        interfaces = []
        for name, counters in raw.items():
            state = self._rates.setdefault(name, SampleState())
            rx_bps = state.rate(counters["rx_bytes"])
            st_rx = self._rates.setdefault(name + ":tx", SampleState())
            tx_bps = st_rx.rate(counters["tx_bytes"])
            st_rxp = self._rates.setdefault(name + ":rxp", SampleState())
            rx_pps = st_rxp.rate(counters["rx_packets"])
            st_txp = self._rates.setdefault(name + ":txp", SampleState())
            tx_pps = st_txp.rate(counters["tx_packets"])
            meta = self._iface_meta(name)
            interfaces.append({
                "name": name,
                "rx_bps": rx_bps, "tx_bps": tx_bps,
                "rx_pps": rx_pps, "tx_pps": tx_pps,
                "rx_total": counters["rx_bytes"], "tx_total": counters["tx_bytes"],
                "rx_errors": counters["rx_errors"] + counters["rx_drop"],
                "tx_errors": counters["tx_errors"] + counters["tx_drop"],
                "addresses": addrs.get(name, []),
                **meta,
            })
        interfaces.sort(key=lambda i: -(i["rx_bps"] + i["tx_bps"]))
        return {"interfaces": interfaces}


class SocketsCollector(Collector):
    """Counts TCP states and listening ports straight from /proc/net."""

    name = "sockets"
    interval = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._states: dict[str, int] = {}
        self._listening: list[dict] | None = None
        self._listening_ts = 0.0
        self._udp_states: dict[str, int] = {}

    def _parse(self, path: str) -> tuple[dict[str, int], list[dict]]:
        states: dict[str, int] = {}
        listening: list[dict] = []
        for line in read_lines(path)[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            state_code = parts[3]
            state_name = _TCP_STATES.get(state_code, state_code)
            states[state_name] = states.get(state_name, 0) + 1
            if state_code == "0A":
                local = parts[1]
                port_hex = local.rsplit(":", 1)[-1]
                try:
                    port = int(port_hex, 16)
                except ValueError:
                    port = 0
                listening.append({"port": port, "service": WELL_KNOWN_PORTS.get(port, "")})
        return states, listening

    def collect(self) -> dict:
        states: dict[str, int] = {}
        listening: list[dict] = []

        # Parse each socket table once and reuse it for both the state tally and
        # the listening-port list.
        for path in ("/proc/net/tcp", "/proc/net/tcp6"):
            part_states, part_listening = self._parse(path)
            for key, value in part_states.items():
                states[key] = states.get(key, 0) + value
            listening.extend(part_listening)

        udp_count = 0
        for path in ("/proc/net/udp", "/proc/net/udp6"):
            udp_count += len(read_lines(path)) - 1

        listening.sort(key=lambda entry: entry["port"])
        unique_listening: list[dict] = []
        last_port = None
        for entry in listening:
            if entry["port"] == last_port:
                continue
            last_port = entry["port"]
            unique_listening.append(entry)

        return {
            "states": states,
            "total": sum(states.values()),
            "udp": max(0, udp_count),
            "listening": unique_listening[:64],
            "listening_total": len(unique_listening),
        }