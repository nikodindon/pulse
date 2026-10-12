"""Detailed views for CPU, memory, disk, network, processes and services.

Each view is a callable `render(win, rect, data)` that fills the given area.
They share the same `data` dictionary produced by the sampler, plus a
`history` entry for sparklines.
"""

from __future__ import annotations

import curses

from . import theme as th
from .alerts import THRESHOLDS, severity, worst
from .util import (
    human_bytes,
    human_bytes_per_sec,
    human_count,
    hz_to_text,
    pct,
)
from .widgets import (
    Rect,
    attr,
    draw_bar,
    draw_kv_row,
    draw_panel,
    draw_sparkline_column,
    draw_value_bar,
    glyph,
    pad_to,
    safe_add,
)


def _table_header(win, rect: Rect, columns: list[tuple[str, int, str]]) -> None:
    cursor = rect.x
    for label, width, align in columns:
        safe_add(win, rect.y, cursor, pad_to(label, width, align),
                 attr(th.DARK_GREY), max_width=width)
        cursor += width + 1


def _table_row(win, y: int, rect: Rect, cells: list[str],
               columns: list[tuple[str, int, str]], colors: list | None = None,
               bold: bool = False) -> None:
    cursor = rect.x
    for idx, (_, width, align) in enumerate(columns):
        text = cells[idx] if idx < len(cells) else ""
        color = colors[idx] if colors and idx < len(colors) else th.WHITE
        safe_add(win, y, cursor, pad_to(text, width, align),
                 attr(color, bold=bold), max_width=width)
        cursor += width + 1


# ---------------------------------------------------------------------------
# CPU view
# ---------------------------------------------------------------------------


def cpu_view(win, rect: Rect, data: dict) -> None:
    cpu = data.get("cpu") or {}
    history = data["history"]
    static = cpu.get("static") or {}
    inner = draw_panel(win, rect, "CPU DETAIL", color=th.BLUE)
    if inner.h < 4:
        return

    total = cpu.get("total", 0.0)
    cores = cpu.get("cores") or []
    core_level = worst(*[severity(c, "cpu") for c in cores]) if cores else 0
    total_level = severity(total, "cpu")
    inner = draw_panel(win, rect, "CPU DETAIL",
                       color=th.alert_color(worst(total_level, core_level)))
    left_w = inner.w // 2 - 1
    left = Rect(inner.y, inner.x, inner.h, left_w)
    right = Rect(inner.y, inner.x + left_w + 1, inner.h, inner.w - left_w - 1)

    freq = cpu.get("freq_avg")
    breakdown = cpu.get("breakdown") or {}
    warn_t, crit_t = THRESHOLDS["cpu"][0] / 100.0, THRESHOLDS["cpu"][2] / 100.0

    y = left.y
    safe_add(win, y, left.x, pad_to("Total utilisation", left.w), attr(th.GREY, bold=True))
    y += 1
    draw_bar(win, y, left.x, left.w, total / 100.0, ticks=(warn_t, crit_t))
    safe_add(win, y, max(left.x, left.x + left.w - 6), pct(total),
             attr(th.alert_color(total_level), bold=True))
    y += 2

    for key in ("user", "system", "iowait", "steal", "irq", "nice"):
        value = breakdown.get(key, 0.0)
        draw_value_bar(win, y, left.x, left.w, key, f"{value:.1f}%", value / 100.0, 7,
                       gradient=False,
                       value_color=th.alert_color(severity(value, "cpu")) if value > 2 else th.GREY)
        y += 1
    y += 1

    if y + 6 <= left.y + left.h:
        safe_add(win, y, left.x, pad_to("CPU usage history", left.w),
                 attr(th.GREY, bold=True))
        y += 1
        spark_rect = Rect(y, left.x, min(left.y + left.h - y, 10), left.w)
        draw_sparkline_column(win, spark_rect, history.values("cpu"), low=0, high=100)

    y = right.y
    model = static.get("model", "?")
    safe_add(win, y, right.x, pad_to(model[:right.w], right.w), attr(th.WHITE, bold=True))
    y += 2

    rows = [
        ("physical cores", str(static.get("physical", "?"))),
        ("logical threads", str(static.get("logical", "?"))),
        ("sockets", str(static.get("sockets", "?"))),
        ("cache", static.get("l3") or "-"),
        ("frequency", hz_to_text(freq) if freq else "-"),
        ("freq range", (f"{hz_to_text(static.get('freq_min'))} - {hz_to_text(static.get('freq_max'))}"
                        if static.get("freq_min") and static.get("freq_max") else "-")),
        ("governor", ", ".join(sorted(static.get("governors") or [])) or "-"),
        ("load avg", (f"{static.get('load1', 0):.2f} {static.get('load5', 0):.2f} "
                      f"{static.get('load15', 0):.2f}")),
        ("running procs", str(cpu.get("running", 0))),
        ("blocked procs", str(cpu.get("blocked", 0))),
        ("context switch/s", human_count(cpu.get("ctxt_rate", 0), 1)),
        ("interrupts/s", human_count(cpu.get("intr_rate", 0), 1)),
    ]
    for label, value in rows:
        if y >= right.y + right.h:
            break
        safe_add(win, y, right.x, pad_to(label, 20), attr(th.GREY), max_width=right.w)
        safe_add(win, y, right.x + 21, value, attr(th.WHITE, bold=True),
                 max_width=max(0, right.w - 21))
        y += 1

    if cores and y + 2 < right.y + right.h:
        y += 1
        safe_add(win, y, right.x, pad_to("Per-core load", right.w), attr(th.GREY, bold=True))
        y += 1
        bar_w = max(6, min(30, right.w // 2 - 6))
        per_row = max(1, right.w // (bar_w + 6))
        for idx, value in enumerate(cores):
            col = idx % per_row
            row = idx // per_row
            cx = right.x + col * (bar_w + 6)
            cy = y + row
            if cy >= right.y + right.h:
                break
            label_w = 3 if idx < 10 else 4
            safe_add(win, cy, cx, pad_to(f"{idx:>2} ", label_w), attr(th.DARK_GREY))
            level = severity(value, "cpu")
            draw_bar(win, cy, cx + label_w, bar_w, value / 100.0,
                     gradient=False, color=th.alert_color(level))
            if bar_w + label_w + 4 < right.w:
                safe_add(win, cy, cx + label_w + bar_w + 1, f"{value:>3.0f}",
                         attr(th.alert_color(level), bold=True))


# ---------------------------------------------------------------------------
# Memory view
# ---------------------------------------------------------------------------


def memory_view(win, rect: Rect, data: dict) -> None:
    memory = data.get("memory") or {}
    history = data["history"]
    total = memory.get("total", 0)
    used = memory.get("used", 0)
    swap_total = memory.get("swap_total", 0)
    swap_used = memory.get("swap_used", 0)
    mem_pct = (100.0 * used / total) if total else 0.0
    swap_pct = (100.0 * swap_used / swap_total) if swap_total else 0.0
    mem_level = severity(mem_pct, "mem")
    swap_level = severity(swap_pct, "swap")
    inner = draw_panel(win, rect, "MEMORY DETAIL",
                       color=th.alert_color(worst(mem_level, swap_level)))
    if inner.h < 4:
        return
    left_w = inner.w // 2 - 1
    left = Rect(inner.y, inner.x, inner.h, left_w)
    right = Rect(inner.y, inner.x + left_w + 1, inner.h, inner.w - left_w - 1)

    y = left.y
    draw_value_bar(win, y, left.x, left.w, "RAM", pct(mem_pct), mem_pct / 100.0, 5,
                   gradient=False, value_color=th.alert_color(mem_level),
                   ticks=(THRESHOLDS["mem"][0] / 100.0, THRESHOLDS["mem"][2] / 100.0))
    y += 1
    safe_add(win, y, left.x, pad_to(f"{human_bytes(used)} / {human_bytes(total)}", left.w),
             attr(th.WHITE, bold=True))
    y += 2

    segments = [
        ("processes", used, th.GREEN),
        ("cache", memory.get("pagecache", 0), th.BLUE),
        ("buffers", memory.get("buffers", 0), th.CYAN),
        ("slab", memory.get("slab", 0), th.PURPLE),
        ("free", memory.get("free", 0), th.DARK_GREY),
    ]
    for label, value, color in segments:
        if y >= left.y + left.h:
            break
        frac = (value / total) if total else 0
        safe_add(win, y, left.x, pad_to(label, 12), attr(th.GREY), max_width=left.w)
        bar_x = left.x + 12
        bar_w = max(3, left.w - 12 - 10)
        draw_bar(win, y, bar_x, bar_w, frac, gradient=False, color=color)
        safe_add(win, y, left.x + left.w - 9, human_bytes(value, 0), attr(color, bold=True))
        y += 1

    if y + 6 <= left.y + left.h:
        y += 1
        safe_add(win, y, left.x, pad_to("RAM usage history", left.w), attr(th.GREY, bold=True))
        y += 1
        draw_sparkline_column(win, Rect(y, left.x, min(left.y + left.h - y, 8), left.w),
                              history.values("mem"), low=0, high=100)

    y = right.y
    safe_add(win, y, right.x, pad_to("Swap", right.w),
             attr(th.GREY, bold=swap_level >= 2))
    y += 1
    draw_bar(win, y, right.x, right.w, swap_pct / 100.0,
             ticks=(THRESHOLDS["swap"][0] / 100.0,))
    safe_add(win, y, max(right.x, right.x + right.w - 6), pct(swap_pct),
             attr(th.alert_color(swap_level), bold=True))
    y += 1
    safe_add(win, y, right.x,
             pad_to(f"{human_bytes(swap_used)} / {human_bytes(swap_total)}", right.w),
             attr(th.WHITE))
    y += 2

    rows = [
        ("available", human_bytes(memory.get("available", 0))),
        ("free", human_bytes(memory.get("free", 0))),
        ("buffers", human_bytes(memory.get("buffers", 0))),
        ("cached", human_bytes(memory.get("cached", 0))),
        ("shared", human_bytes(memory.get("shared", 0))),
        ("slab", human_bytes(memory.get("slab", 0))),
        ("reclaimable", human_bytes(memory.get("reclaimable", 0))),
        ("page in/s", human_bytes_per_sec(memory.get("paged_in_rate", 0), 0)),
        ("page out/s", human_bytes_per_sec(memory.get("paged_out_rate", 0), 0)),
        ("page faults/s", human_count(memory.get("pgfault_rate", 0), 1)),
        ("major faults/s", human_count(memory.get("pgmajfault_rate", 0), 1)),
        ("committed", f"{human_bytes(memory.get('committed_as', 0))} / {human_bytes(memory.get('commit_limit', 0))}"),
    ]
    for label, value in rows:
        if y >= right.y + right.h:
            break
        safe_add(win, y, right.x, pad_to(label, 18), attr(th.GREY), max_width=right.w)
        safe_add(win, y, right.x + 19, value, attr(th.WHITE, bold=True),
                 max_width=max(0, right.w - 19))
        y += 1


# ---------------------------------------------------------------------------
# Disk view
# ---------------------------------------------------------------------------


def disk_view(win, rect: Rect, data: dict) -> None:
    disk = data.get("disk") or {}
    filesystems = data.get("filesystems") or {}
    all_devices = (disk.get("devices") or [])
    fs_list = sorted(filesystems.get("filesystems") or [],
                     key=lambda f: -f["used_pct"])
    disk_level = worst(*[severity(d.get("util"), "disk") for d in all_devices]) if all_devices else 0
    fs_level = worst(*[severity(f.get("used_pct"), "fs") for f in fs_list]) if fs_list else 0
    inner = draw_panel(win, rect, "STORAGE", color=th.alert_color(worst(disk_level, fs_level)))
    if inner.h < 4:
        return

    # Each table gets exactly the rows it needs (title + header + entries), so
    # neither list is truncated while the other leaves empty space behind.
    dev_rows = len(all_devices) + 2 if all_devices else 0
    fs_rows = len(fs_list) + 2 if fs_list else 0
    spacer = 1 if (dev_rows and fs_rows) else 0
    wanted = dev_rows + fs_rows + spacer
    dev_rect = Rect(inner.y, inner.x, 0, inner.w)
    fs_rect = Rect(inner.y, inner.x, 0, inner.w)

    if not all_devices:
        fs_rect = Rect(inner.y, inner.x, min(inner.h, wanted), inner.w)
    elif not fs_list:
        dev_rect = Rect(inner.y, inner.x, min(inner.h, wanted), inner.w)
    else:
        if wanted <= inner.h:
            dev_rect = Rect(inner.y, inner.x, dev_rows, inner.w)
            fs_rect = Rect(inner.y + dev_rows + spacer, inner.x, fs_rows, inner.w)
        else:
            # Not enough room for both: give each at least half, and let the
            # filesystem table take the remainder since it is usually longer.
            avail = inner.h - spacer
            dev_h = max(3, min(dev_rows, avail // 2))
            dev_rect = Rect(inner.y, inner.x, dev_h, inner.w)
            fs_rect = Rect(inner.y + dev_h + spacer, inner.x,
                           max(0, inner.h - dev_h - spacer), inner.w)

    columns = [("DEVICE", 8, "left"), ("SIZE", 10, "right"), ("READ/s", 10, "right"),
               ("WRITE/s", 10, "right"), ("IOPS", 8, "right"), ("UTIL", 7, "right"),
               ("AWAIT", 8, "right")]
    if inner.w < 96:
        columns = [c for c in columns if c[0] not in ("IOPS", "AWAIT")]

    if dev_rect.h > 1:
        safe_add(win, dev_rect.y, dev_rect.x, "Block devices", attr(th.GREY, bold=True))
        _table_header(win, Rect(dev_rect.y + 1, dev_rect.x, 1, dev_rect.w), columns)
        y = dev_rect.y + 2
        for device in all_devices:
            if y >= dev_rect.y + dev_rect.h:
                break
            cells = [
                device["name"],
                human_bytes(device.get("size_bytes", 0), 0),
                human_bytes_per_sec(device.get("read_bps", 0), 0),
                human_bytes_per_sec(device.get("write_bps", 0), 0),
                human_count(device.get("read_iops", 0) + device.get("write_iops", 0), 1),
                f"{device.get('util', 0):.0f}%",
                f"{min(99999.0, device.get('await_ms', 0)):.1f}ms",
            ]
            util = device.get("util", 0)
            u_level = severity(util, "disk")
            _table_row(win, y, Rect(dev_rect.y, dev_rect.x, dev_rect.h, dev_rect.w),
                       cells, columns,
                       [th.WHITE, th.GREY, th.BLUE, th.MAGENTA, th.GREY,
                        th.alert_color(u_level), th.GREY],
                       bold=u_level >= 2)
            y += 1

    fs_cols = [("MOUNT", 22, "left"), ("TYPE", 10, "left"), ("SIZE", 9, "right"),
               ("USED", 9, "right"), ("AVAIL", 9, "right"), ("USE%", 7, "right"),
               ("INODES", 7, "right")]
    if inner.w < 96:
        fs_cols = [c for c in fs_cols if c[0] != "INODES"]

    if fs_rect.h > 1:
        safe_add(win, fs_rect.y, fs_rect.x, "Mounted filesystems", attr(th.GREY, bold=True))
        _table_header(win, Rect(fs_rect.y + 1, fs_rect.x, 1, fs_rect.w), fs_cols)
        y = fs_rect.y + 2
        for fs in fs_list:
            if y >= fs_rect.y + fs_rect.h:
                break
            cells = [
                fs["mount"], fs["fstype"], human_bytes(fs["total"], 0),
                human_bytes(fs["used"], 0), human_bytes(fs["available"], 0),
                f"{fs['used_pct']:.0f}%", f"{fs['inode_pct']:.0f}%",
            ]
            u_level = severity(fs["used_pct"], "fs")
            i_level = severity(fs["inode_pct"], "inodes")
            _table_row(win, y, Rect(fs_rect.y, fs_rect.x, fs_rect.h, fs_rect.w),
                       cells, fs_cols,
                       [th.WHITE, th.DARK_GREY, th.GREY, th.GREY, th.GREY,
                        th.alert_color(u_level), th.alert_color(i_level)],
                       bold=u_level >= 2)
            y += 1


# ---------------------------------------------------------------------------
# Network view
# ---------------------------------------------------------------------------


def network_view(win, rect: Rect, data: dict) -> None:
    network = data.get("network") or {}
    sockets = data.get("sockets") or {}
    history = data["history"]
    close_wait = (sockets.get("states") or {}).get("CLOSE_WAIT", 0)
    conn_level = 3 if close_wait > 20 else (2 if close_wait > 5 else 0)
    inner = draw_panel(win, rect, "NETWORK DETAIL",
                       color=th.alert_color(conn_level) if conn_level else th.CYAN)
    if inner.h < 4:
        return
    left_w = inner.w // 2 - 1
    left = Rect(inner.y, inner.x, inner.h, left_w)
    right = Rect(inner.y, inner.x + left_w + 1, inner.h, inner.w - left_w - 1)

    y = left.y
    safe_add(win, y, left.x, pad_to("Interfaces", left.w), attr(th.GREY, bold=True))
    y += 1
    ifaces = [i for i in (network.get("interfaces") or []) if i["name"] != "lo"]
    name_w = max(8, min(20, left.w - 18))
    state_w = 7
    rate_w = max(0, left.w - name_w - state_w)
    for iface in ifaces[:8]:
        if y >= left.y + left.h:
            break
        state = iface.get("state", "?")
        color = th.GREEN if state == "up" else th.DARK_GREY
        safe_add(win, y, left.x, pad_to(iface["name"][:name_w], name_w),
                 attr(th.WHITE, bold=True), max_width=name_w)
        if rate_w > 0:
            safe_add(win, y, left.x + name_w, pad_to(state, state_w), attr(color))
            safe_add(win, y, left.x + name_w + state_w,
                     pad_to(human_bytes_per_sec(iface["rx_bps"], 0), rate_w, "right"),
                     attr(th.BLUE, bold=True))
        y += 1
        if y < left.y + left.h:
            detail = f"{iface['tx_bps'] / 1024:.0f} KiB/s tx"
            if iface.get("rx_errors") or iface.get("tx_errors"):
                detail += f"   err {iface['rx_errors'] + iface['tx_errors']}"
            safe_add(win, y, left.x + 1, detail, attr(th.MAGENTA), max_width=left.w - 1)
            y += 1

    if y + 6 <= left.y + left.h:
        y += 1
        safe_add(win, y, left.x, pad_to("Throughput history", left.w),
                 attr(th.GREY, bold=True))
        y += 1
        half = max(1, left.w // 2 - 1)
        height = min(left.y + left.h - y, 8)
        draw_sparkline_column(win, Rect(y, left.x, height, half),
                              history.values("net_rx"), gradient=False, color=th.BLUE)
        draw_sparkline_column(win, Rect(y, left.x + half + 1, height, half),
                              history.values("net_tx"), gradient=False, color=th.MAGENTA)

    y = right.y
    safe_add(win, y, right.x, pad_to("TCP states", right.w), attr(th.GREY, bold=True))
    y += 1
    states = sockets.get("states") or {}
    colors = {"ESTABLISHED": th.GREEN, "LISTEN": th.BLUE, "TIME_WAIT": th.ORANGE,
              "CLOSE_WAIT": th.RED}
    for state in sorted(states, key=lambda s: -states[s]):
        if y >= right.y + right.h:
            break
        count = states[state]
        # A pile of CLOSE_WAIT / TIME_WAIT sockets is the classic sign of a
        # leaking application, so those get a severity colour.
        level = 3 if state == "CLOSE_WAIT" and count > 20 else (
            2 if state in ("CLOSE_WAIT", "TIME_WAIT") and count > 50 else 0)
        color = th.alert_color(level) if level else colors.get(state, th.WHITE)
        safe_add(win, y, right.x, pad_to(state, 16),
                 attr(th.GREY, bold=level >= 2))
        safe_add(win, y, right.x + 16, str(count), attr(color, bold=True))
        y += 1
    y += 1

    safe_add(win, y, right.x, pad_to("Listening ports", right.w), attr(th.GREY, bold=True))
    y += 1
    for entry in (sockets.get("listening") or [])[:12]:
        if y >= right.y + right.h:
            break
        safe_add(win, y, right.x, pad_to(str(entry["port"]), 7), attr(th.BLUE, bold=True))
        safe_add(win, y, right.x + 7, entry.get("service") or "-", attr(th.GREY))
        y += 1


# ---------------------------------------------------------------------------
# Process view
# ---------------------------------------------------------------------------


class ProcessState:
    """Sort/filter state for the process table."""

    SORT_KEYS = {
        "cpu": lambda p: -p["cpu"],
        "mem": lambda p: -p["mem_rss"],
        "pid": lambda p: p["pid"],
        "name": lambda p: p["name"].lower(),
        "user": lambda p: p["username"],
        "read": lambda p: -p["read_bps"],
        "write": lambda p: -p["write_bps"],
    }

    def __init__(self) -> None:
        self.sort_key = "cpu"
        self.filter_text = ""
        self.selected = 0
        self.scroll = 0
        self.tree_mode = False

    def filtered(self, processes: list[dict]) -> list[dict]:
        rows = processes
        if self.filter_text:
            needle = self.filter_text.lower()
            rows = [p for p in rows
                    if needle in p["name"].lower()
                    or needle in p.get("cmd", "").lower()
                    or needle in p["username"].lower()
                    or needle == str(p["pid"])]
        key = self.SORT_KEYS.get(self.sort_key, self.SORT_KEYS["cpu"])
        return sorted(rows, key=key)


def process_view(win, rect: Rect, data: dict, state: ProcessState) -> None:
    processes = data.get("processes") or {}
    rows = state.filtered(processes.get("processes") or [])
    total = len(rows)

    inner = draw_panel(win, rect, "PROCESSES", color=th.ORANGE,
                       footer=f"{total} shown" + (f" / {processes.get('count', 0)}"
                                                  if state.filter_text else ""))
    if inner.h < 3:
        return

    columns = [
        ("PID", 7, "right"), ("USER", 10, "left"), ("NAME", 22, "left"),
        ("S", 2, "left"), ("CPU%", 7, "right"), ("MEM%", 7, "right"),
        ("RSS", 9, "right"), ("THR", 5, "right"),
        ("READ/s", 10, "right"), ("WRITE/s", 10, "right"), ("COMMAND", 20, "left"),
    ]
    if inner.w < 70:
        columns = [c for c in columns if c[0] not in ("THR", "READ/s", "WRITE/s")]
    if inner.w < 48:
        columns = [c for c in columns if c[0] not in ("MEM%", "RSS")]

    filter_text = ""
    if state.filter_text:
        filter_text = f"filter: {state.filter_text}"
    elif total:
        filter_text = f"sort: {state.sort_key}"
    safe_add(win, inner.y, inner.x + inner.w - min(inner.w, 40),
             pad_to(filter_text, min(inner.w, 40), "right"),
             attr(th.YELLOW if state.filter_text else th.DARK_GREY))

    header_rect = Rect(inner.y + 1, inner.x, 1, inner.w)
    _table_header(win, header_rect, columns)

    body_top = inner.y + 2
    body_h = inner.h - 2
    state.scroll = max(0, min(state.scroll, max(0, total - body_h)))
    if state.selected < state.scroll:
        state.scroll = state.selected
    elif state.selected >= state.scroll + body_h:
        state.scroll = state.selected - body_h + 1

    for offset in range(body_h):
        idx = state.scroll + offset
        if idx >= total:
            break
        proc = rows[idx]
        cpu = proc["cpu"]
        cells = [
            str(proc["pid"]),
            proc["username"][:10],
            proc["name"][:22],
            proc["status"],
            f"{cpu:.1f}",
            f"{proc['mem_percent']:.1f}",
            human_bytes(proc["mem_rss"], 0),
            str(proc["threads"]),
            human_bytes_per_sec(proc["read_bps"], 0),
            human_bytes_per_sec(proc["write_bps"], 0),
            proc.get("cmd", "")[:24],
        ]
        cpu_level = severity(min(100.0, cpu), "cpu")
        mem_level = severity(min(100.0, proc["mem_percent"] * 4), "mem")
        colors = [th.WHITE, th.GREY, th.WHITE,
                  th.GREEN if proc["status"] == "R" else th.GREY,
                  th.alert_color(cpu_level), th.alert_color(mem_level),
                  th.WHITE, th.GREY, th.BLUE, th.MAGENTA, th.DARK_GREY]
        row_attrs = 0
        if idx == state.selected:
            row_attrs = curses.A_REVERSE
        elif cpu_level >= 3 or mem_level >= 3:
            row_attrs = curses.A_BOLD
        cursor = inner.x
        for idx_col, (_, width, align) in enumerate(columns):
            text = cells[idx_col] if idx_col < len(cells) else ""
            color = colors[idx_col] if idx_col < len(colors) else th.WHITE
            flags = attr(color) | row_attrs
            safe_add(win, body_top + offset, cursor,
                     pad_to(text, width, align), flags, max_width=width)
            cursor += width + 1


# ---------------------------------------------------------------------------
# Sensors view
# ---------------------------------------------------------------------------


def sensors_view(win, rect: Rect, data: dict) -> None:
    sensors = data.get("sensors") or {}
    cooling = data.get("cooling") or {}
    inner = draw_panel(win, rect, "SENSORS", color=th.ORANGE)
    if inner.h < 3:
        return
    y = inner.y

    temps = sensors.get("temps") or []
    if temps:
        safe_add(win, y, inner.x, "Temperatures", attr(th.GREY, bold=True))
        y += 1
        for temp in sorted(temps, key=lambda t: -t["value"]):
            if y >= inner.y + inner.h:
                break
            value = temp["value"]
            level = severity(value, "temp")
            label = f"{temp['chip']}/{temp['label']}"[:max(4, inner.w - 26)]
            safe_add(win, y, inner.x, pad_to(label, inner.w - 24),
                     attr(th.WHITE if level >= 3 else th.GREY, bold=level >= 3))
            safe_add(win, y, inner.x + inner.w - 24,
                     pad_to(f"{value:.1f}°C", 9), attr(th.alert_color(level), bold=True))
            draw_bar(win, y, inner.x + inner.w - 14, 14, min(1.0, value / 100.0),
                     gradient=False, color=th.alert_color(level))
            y += 1
        y += 1

    for title, key, fmt in (("Fans", "fans", "{:.0f} RPM"),
                            ("Voltages", "voltages", "{:.2f} V"),
                            ("Power", "powers", "{:.2f} W")):
        entries = sensors.get(key) or []
        if not entries or y >= inner.y + inner.h:
            continue
        safe_add(win, y, inner.x, title, attr(th.GREY, bold=True))
        y += 1
        for entry in entries:
            if y >= inner.y + inner.h:
                break
            label = f"{entry['chip']}/{entry['label']}"[:max(4, inner.w - 18)]
            safe_add(win, y, inner.x, pad_to(label, inner.w - 16), attr(th.GREY))
            safe_add(win, y, inner.x + inner.w - 15, pad_to(fmt.format(entry["value"]), 14),
                     attr(th.WHITE, bold=True))
            y += 1
        y += 1

    devices = cooling.get("devices") or []
    if devices and y < inner.y + inner.h:
        safe_add(win, y, inner.x, "Cooling devices", attr(th.GREY, bold=True))
        y += 1
        for device in devices[:8]:
            if y >= inner.y + inner.h:
                break
            safe_add(win, y, inner.x, pad_to(device["type"], 22), attr(th.GREY))
            safe_add(win, y, inner.x + 23,
                     f"{device['cur_state']}/{device['max_state']}",
                     attr(th.ORANGE if device["cur_state"] else th.WHITE, bold=True))
            y += 1


# ---------------------------------------------------------------------------
# Services view
# ---------------------------------------------------------------------------


def services_view(win, rect: Rect, data: dict) -> None:
    services = data.get("services") or {}
    containers = data.get("containers") or {}
    inner = draw_panel(win, rect, "SERVICES", color=th.GREEN)
    if rect.h < 3:
        return
    y = inner.y

    counts = services.get("counts") or {}
    draw_kv_row(win, y, inner.x, inner.w, [
        ("running", str(counts.get("running", 0))),
        ("failed", str(counts.get("failed", 0))),
        ("enabled", str(counts.get("enabled", 0))),
    ])
    if containers.get("available"):
        draw_kv_row(win, y, inner.x + inner.w // 2, inner.w // 2, [
            (containers.get("engine", "docker"), str(containers.get("running", 0))),
        ])
    y += 2

    failed = services.get("failed_units") or []
    if failed:
        safe_add(win, y, inner.x, "Failed units", attr(th.RED, bold=True))
        y += 1
        for unit in failed[:4]:
            if y >= inner.y + inner.h:
                break
            safe_add(win, y, inner.x, pad_to(unit, inner.w), attr(th.RED))
            y += 1
        y += 1

    safe_add(win, y, inner.x, "Running units", attr(th.GREY, bold=True))
    y += 1
    for service in services.get("services") or []:
        if y >= inner.y + inner.h:
            break
        safe_add(win, y, inner.x, pad_to(f"{glyph('dot')} {service['unit']}", 40),
                 attr(th.GREEN, bold=True), max_width=inner.w)
        if service.get("description"):
            safe_add(win, y, inner.x + 42, service["description"][:max(0, inner.w - 42)],
                     attr(th.GREY), max_width=max(0, inner.w - 42))
        y += 1