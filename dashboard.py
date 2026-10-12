"""Overview dashboard: every panel that composes the main screen."""

from __future__ import annotations

import curses

from . import theme as th
from .alerts import THRESHOLDS, severity, worst
from .layout import Panel
from .util import (
    human_bytes,
    human_bytes_per_sec,
    human_duration,
    hz_to_text,
    pct,
)
from .widgets import (
    Rect,
    attr,
    draw_bar,
    draw_kv_row,
    draw_panel,
    draw_sparkline,
    draw_trend,
    draw_value_bar,
    glyph,
    pad_to,
    safe_add,
)

STATUS_COLORS = {
    "R": th.GREEN, "S": th.CYAN, "D": th.ORANGE, "T": th.BLUE,
    "Z": th.GREY, "I": th.MAGENTA, "t": th.GREY,
}


def _empty(win, rect: Rect, message: str) -> None:
    if rect.h > 0 and rect.w > 0:
        safe_add(win, rect.y + rect.h // 2, rect.x + max(0, (rect.w - len(message)) // 2),
                 message, attr(th.DARK_GREY), max_width=rect.w)


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------


def render_cpu(win, rect: Rect, data: dict) -> None:
    cpu = data.get("cpu") or {}
    history = data["history"]
    static = cpu.get("static") or {}
    total = cpu.get("total", 0.0)
    level = severity(total, "cpu")
    warn_t, high_t, crit_t = THRESHOLDS["cpu"]
    ticks = (warn_t / 100.0, crit_t / 100.0)

    inner = draw_panel(win, rect, "CPU", color=th.alert_color(level),
                       footer=f"{len(cpu.get('cores') or [])} threads")
    if rect.h < 6 or inner.w < 10:
        return

    y = inner.y

    label = safe_add(win, y, inner.x, "TOTAL", attr(th.GREY), max_width=inner.w)
    bar_w = max(0, inner.w - label - 8)
    if bar_w > 0:
        draw_bar(win, y, inner.x + label + 1, bar_w, total / 100.0, ticks=ticks)
    safe_add(win, y, inner.x + inner.w - 6, pct(total),
             attr(th.alert_color(level), bold=True), max_width=6)
    trend = history.trend("cpu", epsilon=1.0)
    draw_trend(win, y, inner.x + inner.w - 8, trend,
               color=th.GREEN if trend == "down" else (th.ORANGE if trend == "up" else th.DARK_GREY))
    y += 2

    freq = cpu.get("freq_avg")
    load1 = static.get("load1", 0.0)
    fmax = static.get("freq_max")
    freq_text = hz_to_text(freq) if freq else "-"
    ratio = f"{100.0 * freq / fmax:.0f}%" if (freq and fmax) else "-"
    draw_kv_row(win, y, inner.x, inner.w, [
        ("freq", freq_text), ("of", ratio),
        ("load", f"{load1:.2f}"),
        ("gov", static.get("governor") or "-"),
    ])
    y += 2

    spark_h = max(3, min(6, inner.h - (y - inner.y) - 2))
    if spark_h >= 3 and inner.h - (y - inner.y) >= spark_h + 1:
        draw_sparkline(win, y, inner.x, inner.w, history.values("cpu"),
                       low=0, high=100)
        y += spark_h

    remaining = inner.h - (y - inner.y)
    if remaining >= 3:
        grid_y = y
        cores = cpu.get("cores") or []
        per_col = max(1, min(len(cores), inner.w // 4))
        cell_w = max(4, inner.w // per_col)
        for idx, value in enumerate(cores):
            cx = inner.x + (idx % per_col) * cell_w
            cy = grid_y + (idx // per_col)
            if cy >= inner.y + inner.h:
                break
            safe_add(win, cy, cx, pad_to(f"{idx:02d}", 3), attr(th.DARK_GREY), max_width=3)
            bar_x = cx + 3
            bar_w = max(1, cell_w - 3)
            draw_bar(win, cy, bar_x, bar_w, value / 100.0,
                     gradient=False, color=th.alert_color(severity(value, "cpu")))


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def render_memory(win, rect: Rect, data: dict) -> None:
    memory = data.get("memory") or {}
    total = memory.get("total", 0)
    used = memory.get("used", 0)
    free = memory.get("available", 0)
    swap_total = memory.get("swap_total", 0)
    swap_used = memory.get("swap_used", 0)

    mem_pct = (100.0 * used / total) if total else 0.0
    swap_pct = (100.0 * swap_used / swap_total) if swap_total else 0.0
    mem_level = severity(mem_pct, "mem")
    swap_level = severity(swap_pct, "swap")
    panel_level = worst(mem_level, swap_level)

    inner = draw_panel(win, rect, "MEMORY", color=th.alert_color(panel_level))
    if rect.h < 7 or inner.w < 12:
        return

    mem_warn, mem_crit = THRESHOLDS["mem"][0], THRESHOLDS["mem"][2]
    swap_warn = THRESHOLDS["swap"][0] / 100.0

    y = inner.y
    draw_value_bar(win, y, inner.x, inner.w, "RAM", pct(mem_pct), mem_pct / 100.0,
                   4, gradient=False, value_color=th.alert_color(mem_level),
                   ticks=(mem_warn / 100.0, mem_crit / 100.0))
    y += 1
    draw_kv_row(win, y, inner.x, inner.w, [
        ("used", human_bytes(used)),
        ("free", human_bytes(free)),
        ("total", human_bytes(total)),
    ])
    y += 2

    swap_label = "SWAP" if swap_total else "SWAP (none)"
    draw_value_bar(win, y, inner.x, inner.w, swap_label, pct(swap_pct),
                   swap_pct / 100.0, 4, gradient=False,
                   value_color=th.alert_color(swap_level), ticks=(swap_warn,))
    y += 1
    draw_kv_row(win, y, inner.x, inner.w, [
        ("used", human_bytes(swap_used)),
        ("total", human_bytes(swap_total)),
    ])
    y += 2

    if y < inner.y + inner.h:
        rows = [
            ("cache", memory.get("pagecache", 0), th.BLUE),
            ("buffers", memory.get("buffers", 0), th.CYAN),
            ("slab", memory.get("slab", 0), th.PURPLE),
        ]
        for label, value, color in rows:
            if y >= inner.y + inner.h:
                break
            safe_add(win, y, inner.x, pad_to(label, 8), attr(th.GREY), max_width=inner.w)
            safe_add(win, y, inner.x + 9, human_bytes(value), attr(color, bold=True),
                     max_width=inner.w - 9)
            y += 1


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------


def render_gpu(win, rect: Rect, data: dict) -> None:
    gpu = data.get("gpu") or {}
    gpus = gpu.get("gpus") or []
    panel_level = worst(
        *[severity(g.get("temp"), "gpu_temp") for g in gpus],
        *[severity(g.get("util"), "gpu_util") for g in gpus],
    ) if gpus else 0
    inner = draw_panel(win, rect, "GPU", color=th.alert_color(panel_level))
    if not gpus:
        _empty(win, inner, "no GPU detected")
        return
    if rect.h < 4:
        return
    y = inner.y
    for index, device in enumerate(gpus[:3]):
        if y >= inner.y + inner.h:
            break
        name = device.get("name", "GPU")
        if len(gpus) > 1:
            name = f"{index}: {name}"
        safe_add(win, y, inner.x, pad_to(name[:inner.w], inner.w),
                 attr(th.WHITE, bold=True))
        y += 1
        util = device.get("util", 0) or 0
        util_level = severity(util, "gpu_util")
        draw_value_bar(win, y, inner.x, inner.w, "util", pct(util), util / 100.0, 5,
                       gradient=False, value_color=th.alert_color(util_level))
        y += 1
        mem_total = device.get("mem_total", 0)
        mem_used = device.get("mem_used", 0)
        if mem_total:
            mem_pct = 100.0 * mem_used / mem_total
            draw_value_bar(win, y, inner.x, inner.w, "vram",
                           f"{human_bytes(mem_used)}/{human_bytes(mem_total, 0)}",
                           mem_pct / 100.0, 5, gradient=False,
                           value_color=th.cpu_color(mem_pct))
            y += 1
        extras = []
        temp = device.get("temp")
        if temp:
            t_level = severity(temp, "gpu_temp")
            extras.append(("temp", f"{temp}°C", th.alert_color(t_level), t_level))
        power = device.get("power")
        if power:
            extras.append(("pwr", f"{power:.0f}W", th.GREY, 0))
        fan = device.get("fan")
        if fan:
            extras.append(("fan", f"{fan}%", th.GREY, 0))
        if extras and y < inner.y + inner.h:
            cursor = inner.x
            for label, value, color, lvl in extras:
                safe_add(win, y, cursor, label + " ", attr(th.DARK_GREY))
                cursor += len(label) + 1
                cursor += safe_add(win, y, cursor, value, attr(color, bold=lvl >= 2))
                cursor += 2
            y += 1
        y += 1


# ---------------------------------------------------------------------------
# Temperatures
# ---------------------------------------------------------------------------


def render_temps(win, rect: Rect, data: dict) -> None:
    sensors = data.get("sensors") or {}
    temps = sensors.get("temps") or []
    max_temp = max((t["value"] for t in temps), default=None)
    panel_level = severity(max_temp, "temp")

    inner = draw_panel(win, rect, "TEMPERATURES", color=th.alert_color(panel_level),
                       footer=f"max {max_temp:.0f}°C" if max_temp is not None else None)
    if not temps:
        _empty(win, inner, "no temperature sensors")
        return
    if rect.h < 3:
        return
    y = inner.y
    sorted_temps = sorted(temps, key=lambda t: -t["value"])
    row_h = 1 if rect.h < len(sorted_temps) * 3 else 3
    warn_t, high_t = THRESHOLDS["temp"][0], THRESHOLDS["temp"][1]
    for temp in sorted_temps:
        if y + row_h > inner.y + inner.h:
            break
        value = temp["value"]
        level = severity(value, "temp")
        label = f"{temp['chip']} {temp['label']}"
        label = label[:max(3, inner.w - 10)]
        safe_add(win, y, inner.x, pad_to(label, inner.w - 9),
                 attr(th.GREY, bold=level >= 3), max_width=inner.w - 9)
        text = f"{value:.0f}°C"
        safe_add(win, y, inner.x + inner.w - len(text), text,
                 attr(th.alert_color(level), bold=True))
        if row_h == 3 and y + 1 < inner.y + inner.h:
            crit = temp.get("max") or 100.0
            draw_bar(win, y + 1, inner.x, inner.w, min(1.0, value / crit),
                     color=th.alert_color(level),
                     ticks=(warn_t / crit, high_t / crit))
        y += row_h


# ---------------------------------------------------------------------------
# Fans / voltages
# ---------------------------------------------------------------------------


def render_fans(win, rect: Rect, data: dict) -> None:
    sensors = data.get("sensors") or {}
    fans = sensors.get("fans") or []
    inner = draw_panel(win, rect, "FANS", color=th.CYAN)
    if not fans:
        _empty(win, inner, "no fans reported")
        return
    y = inner.y
    for fan in fans:
        if y >= inner.y + inner.h:
            break
        label = f"{fan['chip']} {fan['label']}"[:max(3, inner.w - 10)]
        safe_add(win, y, inner.x, pad_to(label, inner.w - 9), attr(th.GREY))
        text = f"{fan['value']:.0f} RPM"
        safe_add(win, y, inner.x + inner.w - len(text), text, attr(th.WHITE, bold=True))
        y += 1


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def render_network(win, rect: Rect, data: dict) -> None:
    network = data.get("network") or {}
    history = data["history"]
    ifaces = [i for i in (network.get("interfaces") or []) if i["name"] != "lo"]
    inner = draw_panel(win, rect, "NETWORK", color=th.CYAN)
    if not ifaces:
        _empty(win, inner, "no active interfaces")
        return
    if rect.h < 4:
        return
    y = inner.y

    total_rx = sum(i["rx_bps"] for i in ifaces)
    total_tx = sum(i["tx_bps"] for i in ifaces)
    label = safe_add(win, y, inner.x, "TOTAL", attr(th.GREY), max_width=inner.w)
    rx_text = f"{glyph('arrow')} {human_bytes_per_sec(total_rx)}"
    tx_text = f"{glyph('arrow')} {human_bytes_per_sec(total_tx)}"
    safe_add(win, y, inner.x + label + 1, rx_text, attr(th.BLUE, bold=True),
             max_width=max(0, inner.w - label - len(tx_text) - 5))
    safe_add(win, y, max(inner.x + label + 2, inner.x + inner.w - len(tx_text)),
             tx_text, attr(th.MAGENTA, bold=True), max_width=inner.w)
    draw_trend(win, y, inner.x + label + len(rx_text) + 2,
               history.trend("net_rx", epsilon=1024.0),
               color=th.GREEN if history.trend("net_rx", epsilon=1024.0) == "down" else th.ORANGE)
    y += 1

    spark_h = 3 if rect.h >= 8 else 0
    if spark_h:
        rx_w = max(1, inner.w // 2 - 1)
        draw_sparkline(win, y, inner.x, rx_w, history.values("net_rx"),
                       gradient=False, color=th.BLUE)
        draw_sparkline(win, y, inner.x + rx_w + 1, rx_w, history.values("net_tx"),
                       gradient=False, color=th.MAGENTA)
        y += spark_h

    for iface in ifaces[:4]:
        if y >= inner.y + inner.h:
            break
        name = iface["name"][:max(3, inner.w // 2)]
        state = iface.get("state", "")
        state_color = th.GREEN if state == "up" else th.DARK_GREY
        safe_add(win, y, inner.x, pad_to(name, inner.w - 20), attr(th.WHITE))
        speed = ""
        if iface.get("speed_mbps", -1) > 0:
            speed = f"{iface['speed_mbps']}Mb"
        text = f"{human_bytes_per_sec(iface['rx_bps'], 0)} {human_bytes_per_sec(iface['tx_bps'], 0)}"
        safe_add(win, y, max(inner.x, inner.x + inner.w - len(text)), text,
                 attr(th.GREY), max_width=inner.w)
        y += 1
        if y + 1 < inner.y + inner.h:
            link = f"{glyph('bullet')} {speed or state}"
            errs = iface.get("rx_errors", 0) + iface.get("tx_errors", 0)
            if errs and (iface.get("speed_mbps", -1) > 0 or state == "up"):
                link += f"  {glyph('dot')} {errs} err"
            safe_add(win, y + 1, inner.x, link,
                     attr(th.ORANGE if errs and state == "up" else state_color),
                     max_width=max(0, inner.w - 14))
            if iface.get("addresses"):
                addr = iface["addresses"][0]
                safe_add(win, y + 1, inner.x + inner.w - len(addr), addr,
                         attr(th.DARK_GREY), max_width=inner.w)
        y += 2


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------


def _more_line(win, rect: Rect, y: int, hidden: int) -> None:
    """Draw a '+N more' hint so a truncated list never hides silently."""
    if hidden <= 0:
        return
    label = f"{glyph('arrow')} {hidden} more"
    safe_add(win, y, rect.x + rect.w - len(label) - 1, label,
             attr(th.DARK_GREY, bold=True), max_width=rect.w)


def render_disk(win, rect: Rect, data: dict) -> None:
    disk = data.get("disk") or {}
    history = data["history"]
    devices = disk.get("devices") or []
    panel_level = worst(*[severity(d.get("util"), "disk") for d in devices]) if devices else 0

    inner = draw_panel(win, rect, "DISK I/O", color=th.alert_color(panel_level))
    if not devices:
        _empty(win, inner, "no block devices")
        return

    y = inner.y
    rows_left = inner.h
    capacity = max(1, rows_left // 2)
    visible = devices[:capacity]
    hidden = len(devices) - len(visible)
    if hidden > 0 and rows_left % 2 == 0:
        visible = devices[:capacity - 1] if capacity > 1 else devices[:1]
        hidden = len(devices) - len(visible)

    for index, device in enumerate(visible):
        if y >= inner.y + inner.h:
            break
        name = device["name"][:8]
        kind = "SSD" if not device.get("rotational", True) else "HDD"
        util = device.get("util", 0.0)
        level = severity(util, "disk")
        safe_add(win, y, inner.x, pad_to(name, 6), attr(th.WHITE, bold=True))
        safe_add(win, y, inner.x + 6, pad_to(kind, 4), attr(th.DARK_GREY))
        util_w = max(3, min(12, inner.w - 24))
        draw_bar(win, y, inner.x + 10, util_w, util / 100.0,
                 gradient=False, color=th.alert_color(level))
        safe_add(win, y, inner.x + 10 + util_w + 1,
                 pad_to(f"{util:.0f}%", 5), attr(th.alert_color(level), bold=True))
        y += 1
        if y < inner.y + inner.h:
            safe_add(win, y, inner.x,
                     f"  R {human_bytes_per_sec(device.get('read_bps', 0.0), 0)}",
                     attr(th.BLUE), max_width=inner.w)
            write = f"W {human_bytes_per_sec(device.get('write_bps', 0.0), 0)}"
            safe_add(win, y, inner.x + inner.w - len(write), write,
                     attr(th.MAGENTA), max_width=inner.w)
            draw_trend(win, y, inner.x + inner.w - len(write) - 2,
                       history.device_trend("disk_write", device["name"], epsilon=1024.0),
                       color=th.GREEN if history.device_trend(
                           "disk_write", device["name"], epsilon=1024.0) == "down" else th.ORANGE)
            y += 1

    _more_line(win, inner, y, hidden)


# ---------------------------------------------------------------------------
# Filesystems
# ---------------------------------------------------------------------------


def render_filesystems(win, rect: Rect, data: dict) -> None:
    fs_data = data.get("filesystems") or {}
    filesystems = sorted(fs_data.get("filesystems") or [],
                         key=lambda f: -f["used_pct"])
    panel_level = worst(*[severity(f.get("used_pct"), "fs") for f in filesystems]) if filesystems else 0

    inner = draw_panel(win, rect, "FILESYSTEMS", color=th.alert_color(panel_level))
    if not filesystems:
        _empty(win, inner, "no mounted filesystems")
        return

    warn_t, high_t = THRESHOLDS["fs"][0] / 100.0, THRESHOLDS["fs"][2] / 100.0
    y = inner.y
    capacity = max(1, inner.h // 2)
    visible = filesystems[:capacity]
    hidden = len(filesystems) - len(visible)
    if hidden > 0 and inner.h % 2 == 0 and capacity > 1:
        visible = filesystems[:capacity - 1]
        hidden = len(filesystems) - len(visible)

    for fs in visible:
        if y >= inner.y + inner.h:
            break
        used_pct = fs["used_pct"]
        level = severity(used_pct, "fs")
        mount = fs["mount"][:max(4, inner.w // 2 - 2)]
        safe_add(win, y, inner.x, pad_to(mount, inner.w - 16),
                 attr(th.WHITE, bold=level >= 2))
        safe_add(win, y, inner.x + inner.w - 15, pad_to(human_bytes(fs["used"], 0), 9),
                 attr(th.GREY))
        safe_add(win, y, inner.x + inner.w - 6, pct(used_pct),
                 attr(th.alert_color(level), bold=True))
        y += 1
        if y < inner.y + inner.h:
            draw_bar(win, y, inner.x, inner.w, used_pct / 100.0,
                     gradient=False, color=th.alert_color(level),
                     ticks=(warn_t, high_t))
            y += 1

    _more_line(win, inner, y, hidden)


# ---------------------------------------------------------------------------
# Sockets
# ---------------------------------------------------------------------------


def render_sockets(win, rect: Rect, data: dict) -> None:
    sockets = data.get("sockets") or {}
    inner = draw_panel(win, rect, "NETWORK SOCKETS", color=th.BLUE)
    if rect.h < 3:
        return
    states = sockets.get("states") or {}
    total = sockets.get("total", 0)
    udp = sockets.get("udp", 0)
    listening = sockets.get("listening_total", 0)
    y = inner.y
    draw_kv_row(win, y, inner.x, inner.w, [
        ("tcp", str(total)), ("udp", str(udp)), ("listen", str(listening)),
    ])
    y += 2
    interesting = ["ESTABLISHED", "LISTEN", "TIME_WAIT", "CLOSE_WAIT", "SYN_SENT", "SYN_RECV"]
    colors = {"ESTABLISHED": th.GREEN, "LISTEN": th.BLUE, "TIME_WAIT": th.ORANGE,
              "CLOSE_WAIT": th.RED, "SYN_SENT": th.CYAN, "SYN_RECV": th.CYAN}
    shown = False
    for state in interesting:
        count = states.get(state, 0)
        if not count:
            continue
        if y >= inner.y + inner.h:
            break
        shown = True
        safe_add(win, y, inner.x, pad_to(state, 14), attr(th.GREY), max_width=inner.w)
        safe_add(win, y, inner.x + 14, str(count), attr(colors.get(state, th.WHITE), bold=True))
        y += 1
    if not shown and y < inner.y + inner.h:
        _empty(win, Rect(y, inner.x, 1, inner.w), "idle")


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------


def _process_table(win, rect: Rect, rows: list[dict], highlight: str = "cpu") -> None:
    """Mini process table used by the overview panels.

    Rows are tinted by severity so a single runaway process is visible without
    having to read the numbers.
    """
    y = rect.y
    if rect.h < 2:
        return
    header = f"{'PID':>7} {'NAME':<18} {'CPU%':>6} {'MEM':>8}"
    safe_add(win, y, rect.x, pad_to(header, rect.w), attr(th.DARK_GREY))
    y += 1
    for row in rows:
        if y >= rect.y + rect.h:
            break
        cpu = row["cpu"]
        mem = row["mem_rss"]
        cpu_level = severity(min(100.0, cpu), "cpu")
        mem_level = severity(min(100.0, row.get("mem_percent", 0.0) * 4), "mem")
        level = cpu_level if highlight == "cpu" else mem_level
        hot = level >= 2
        name = row["name"][:18]
        cpu_text = f"{cpu:.1f}"
        cells = (f"{row['pid']:>7} " + pad_to(name, 18) +
                 f" {cpu_text:>6}" + f" {human_bytes(mem, 1):>8}")
        base = attr(th.WHITE, bold=hot)
        reversed_row = level >= 3
        if reversed_row:
            base |= curses.A_REVERSE
        safe_add(win, y, rect.x, pad_to(cells, rect.w), base)
        if hot and not reversed_row:
            # Re-draw just the numeric tail so the hot values stand out.
            tail = f"{cpu_text:>6}"
            safe_add(win, y, rect.x + len(cells) - len(tail) - 9, tail,
                     attr(th.alert_color(level), bold=True), max_width=len(tail))
        y += 1


def render_top_cpu(win, rect: Rect, data: dict) -> None:
    processes = data.get("processes") or {}
    rows = processes.get("by_cpu") or []
    inner = draw_panel(win, rect, "TOP CPU PROCESSES", color=th.ORANGE)
    _process_table(win, inner, rows[:8], "cpu")


def render_top_mem(win, rect: Rect, data: dict) -> None:
    processes = data.get("processes") or {}
    rows = processes.get("by_mem") or []
    inner = draw_panel(win, rect, "TOP MEMORY PROCESSES", color=th.GREEN)
    _process_table(win, inner, rows[:8], "mem")


def render_top_io(win, rect: Rect, data: dict) -> None:
    processes = data.get("processes") or {}
    rows = processes.get("by_io") or []
    inner = draw_panel(win, rect, "TOP I/O PROCESSES", color=th.MAGENTA)
    y = inner.y
    safe_add(win, y, inner.x,
             pad_to(f"{'PID':>7} {'NAME':<20} {'READ/s':>9} {'WRITE/s':>9}", inner.w),
             attr(th.DARK_GREY))
    y += 1
    for row in rows[:8]:
        if y >= inner.y + inner.h:
            break
        total_rate = row["read_bps"] + row["write_bps"]
        level = severity(min(100.0, total_rate / (10 * 1024 * 1024) * 100.0), "disk")
        cells = (f"{row['pid']:>7} " + pad_to(row["name"][:20], 20) +
                 f" {human_bytes_per_sec(row['read_bps'], 0):>9}" +
                 f" {human_bytes_per_sec(row['write_bps'], 0):>9}")
        safe_add(win, y, inner.x, pad_to(cells, inner.w),
                 attr(th.WHITE, bold=level >= 2) | (curses.A_REVERSE if level >= 3 else 0))
        y += 1


# ---------------------------------------------------------------------------
# System summary
# ---------------------------------------------------------------------------


def render_system(win, rect: Rect, data: dict) -> None:
    system = data.get("system") or {}
    services = data.get("services") or {}
    containers = data.get("containers") or {}
    battery = data.get("battery") or {}
    inner = draw_panel(win, rect, "SYSTEM", color=th.GREY)
    y = inner.y

    host = system.get("hostname", "?")
    distro = system.get("distro", "?")
    safe_add(win, y, inner.x, pad_to(f"{host} {glyph('dot')} {distro}", inner.w),
             attr(th.WHITE, bold=True))
    y += 2

    counts = services.get("counts") or {}
    uptime = system.get("uptime", 0)
    draw_kv_row(win, y, inner.x, inner.w, [
        ("up", human_duration(uptime)),
        ("svc", str(counts.get("running", 0))),
    ])
    y += 1
    if counts.get("failed"):
        draw_kv_row(win, y, inner.x, inner.w, [
            ("failed", str(counts["failed"])),
        ])
        y += 1
    if containers.get("available"):
        draw_kv_row(win, y, inner.x, inner.w, [
            (containers.get("engine", "docker"), str(containers.get("running", 0))),
        ])
        y += 1
    for pack in battery.get("batteries") or []:
        if y >= inner.y + inner.h:
            break
        cap = pack.get("capacity", 0)
        col = th.GREEN if cap > 50 else (th.ORANGE if cap > 20 else th.RED)
        safe_add(win, y, inner.x, pad_to("BAT", 5), attr(th.GREY))
        draw_bar(win, y, inner.x + 4, max(3, inner.w - 12), cap / 100.0,
                 gradient=False, color=col)
        safe_add(win, y, inner.x + inner.w - 5, f"{cap}%", attr(col, bold=True))
        y += 1

    kernel = system.get("kernel", "")
    if y < inner.y + inner.h:
        safe_add(win, y, inner.x, pad_to(f"kernel {kernel}", inner.w), attr(th.DARK_GREY))


# ---------------------------------------------------------------------------
# Panel registry
# ---------------------------------------------------------------------------


def _disk_height(data: dict) -> int:
    devices = (data.get("disk") or {}).get("devices") or []
    # Two rows per device, plus the two border rows.
    return min(2 * len(devices) + 2, 14)


def _fs_height(data: dict) -> int:
    filesystems = (data.get("filesystems") or {}).get("filesystems") or []
    return min(2 * min(len(filesystems), 7) + 2, 16)


def overview_panels() -> list[Panel]:
    return [
        Panel("cpu", "CPU", 14, 8, 26, render_fn=render_cpu),
        Panel("mem", "MEMORY", 11, 8, 26, render_fn=render_memory),
        Panel("gpu", "GPU", 8, 4, 26, render_fn=render_gpu),
        Panel("temps", "TEMPERATURES", 10, 4, 26, render_fn=render_temps),
        Panel("fans", "FANS", 6, 3, 26, render_fn=render_fans),
        Panel("net", "NETWORK", 11, 6, 30, render_fn=render_network),
        Panel("disk", "DISK I/O", 10, 5, 30, render_fn=render_disk,
              height_fn=_disk_height),
        Panel("fs", "FILESYSTEMS", 8, 4, 26, render_fn=render_filesystems,
              height_fn=_fs_height),
        Panel("sockets", "SOCKETS", 8, 4, 26, render_fn=render_sockets),
        Panel("sys", "SYSTEM", 8, 5, 26, render_fn=render_system),
        Panel("topcpu", "TOP CPU", 10, 5, 34, render_fn=render_top_cpu),
        Panel("topmem", "TOP MEMORY", 10, 5, 34, render_fn=render_top_mem),
        Panel("topio", "TOP I/O", 10, 5, 34, render_fn=render_top_io),
    ]


TAB_INDEX = {
    "Overview": overview_panels,
}