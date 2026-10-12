"""The Pulse application: curses lifecycle, input handling and the render loop."""

from __future__ import annotations

import curses
import sys
import threading
import time

from . import dashboard, views
from . import theme as th
from .alerts import evaluate as evaluate_alerts, severity
from .collectors import Registry
from .history import History
from .layout import pack
from .util import clock, human_duration, terminal_supports_unicode
from .widgets import (
    Rect,
    attr,
    draw_trend,
    glyph,
    pad_to,
    safe_add,
    set_unicode,
)

MIN_WIDTH = 60
MIN_HEIGHT = 18

TABS = ["Overview", "CPU", "Memory", "Disk", "Network", "Processes", "Sensors", "Services"]

KEY_HINTS = [
    ("Tab", "next"), ("1-8", "view"), ("q", "quit"),
    ("/", "filter"), ("s", "sort"), ("p", "pause"), ("r", "reset"),
]


class Sampler(threading.Thread):
    """Runs the collectors on a fixed cadence away from the render thread."""

    daemon = True

    def __init__(self, registry: Registry, interval: float) -> None:
        super().__init__(name="pulse-sampler")
        self.registry = registry
        self.interval = interval
        self._stop_event = threading.Event()
        self.latest: dict = {}
        self.tick_count = 0
        self.last_duration = 0.0

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            start = time.monotonic()
            try:
                payload = self.registry.sample(start)
            except Exception:
                payload = {}
            self.latest = payload
            self.tick_count += 1
            elapsed = time.monotonic() - start
            self.last_duration = elapsed
            self._stop_event.wait(max(0.0, self.interval - elapsed))


class PulseApp:
    def __init__(self, refresh: float = 0.5, start_tab: int = 0,
                 ascii_mode: bool = False, hide_keys: bool = False) -> None:
        self.refresh = refresh
        self.tab_index = start_tab
        self.ascii_mode = ascii_mode
        self.hide_keys = hide_keys
        self.registry = Registry()
        self.history = History()
        self.proc_state = views.ProcessState()
        self.sampler = Sampler(self.registry, refresh)
        self.paused = False
        self.snapshot: dict = {}
        self.toast = ""
        self.toast_until = 0.0
        self.show_help = False
        self.filter_active = False
        self.should_quit = False
        self._panels = dashboard.overview_panels()

    # -- notifications ------------------------------------------------------
    def notify(self, message: str, seconds: float = 2.0) -> None:
        self.toast = message
        self.toast_until = time.monotonic() + seconds

    def cycle_sort(self) -> None:
        keys = ["cpu", "mem", "pid", "name", "user", "read", "write"]
        current = self.proc_state.sort_key
        idx = (keys.index(current) + 1) % len(keys) if current in keys else 0
        self.proc_state.sort_key = keys[idx]
        self.notify(f"sort by {keys[idx]}")

    # -- input --------------------------------------------------------------
    def handle_key(self, key: int) -> bool:
        if key in (17,):  # ctrl-q
            return False
        if key in (ord("q"), 27):
            return False
        if key == ord("\t"):
            self.tab_index = (self.tab_index + 1) % len(TABS)
            return True
        if key == curses.KEY_BTAB:
            self.tab_index = (self.tab_index - 1) % len(TABS)
            return True
        if ord("1") <= key <= ord("8"):
            self.tab_index = key - ord("1")
            return True
        if key in (curses.KEY_DOWN, ord("j")):
            self.proc_state.selected += 1
            return True
        if key in (curses.KEY_UP, ord("k")):
            self.proc_state.selected = max(0, self.proc_state.selected - 1)
            return True
        if key == curses.KEY_PPAGE:
            self.proc_state.selected = max(0, self.proc_state.selected - 10)
            return True
        if key == curses.KEY_NPAGE:
            self.proc_state.selected += 10
            return True
        if key == ord("g"):
            self.proc_state.selected = 0
            return True
        if key == curses.KEY_HOME:
            self.proc_state.selected = 0
            return True
        if key == curses.KEY_END:
            total = len(self.proc_state.filtered(
                (self.sampler.latest.get("processes") or {}).get("processes") or []))
            self.proc_state.selected = max(0, total - 1)
            return True
        if key == ord("s"):
            self.cycle_sort()
            return True
        if key == ord("/"):
            self.filter_active = True
            self.proc_state.filter_text = ""
            return True
        if key == ord("p"):
            self.paused = not self.paused
            if self.paused:
                self.snapshot = dict(self.sampler.latest)
            self.notify("paused" if self.paused else "resumed")
            return True
        if key == ord("r"):
            self.history.clear()
            self.notify("history reset")
            return True
        if key == ord("+") or key == ord("="):
            self._change_refresh(-0.1)
            return True
        if key == ord("-") or key == ord("_"):
            self._change_refresh(+0.1)
            return True
        if key == ord("c"):
            self.tab_index = 0
            self.notify("top view")
            return True
        if key == ord("?"):
            self.show_help = not self.show_help
            return True
        return True

    def _change_refresh(self, delta: float) -> None:
        self.refresh = max(0.1, min(10.0, self.refresh + delta))
        self.sampler.interval = self.refresh
        self.notify(f"refresh {self.refresh:.2g}s")

    # -- chrome -------------------------------------------------------------
    def draw_header(self, win, rect: Rect, data: dict) -> None:
        system = data.get("system") or {}
        cpu = data.get("cpu") or {}
        memory = data.get("memory") or {}
        alerts = data.get("alerts") or []
        history = data.get("history")

        hostname = system.get("hostname", "")
        distro = system.get("distro", "")
        uptime = system.get("uptime", 0)

        worst_level = alerts[0].level if alerts else 0
        bar_color = th.alert_color(worst_level) if alerts else th.BLUE
        bar_attrs = attr(bar_color, reverse=True)
        safe_add(win, rect.y, rect.x, " " * rect.w, bar_attrs, max_width=rect.w)

        title = f" {glyph('dot')} PULSE "
        safe_add(win, rect.y, rect.x + 1, title, attr(th.WHITE, bold=True, reverse=True))
        cursor = rect.x + 1 + len(title)

        info = f"{hostname}  {glyph('dot')}  {distro}  {glyph('dot')}  up {human_duration(uptime)} "
        consumed = safe_add(win, rect.y, cursor, info,
                            attr(th.WHITE, reverse=True),
                            max_width=max(0, rect.x + rect.w - cursor - 24))
        cursor += consumed

        if alerts:
            badge = f" {glyph('dot')} {len(alerts)}  {alerts[0].label} {alerts[0].value} "
            safe_add(win, rect.y, max(cursor, rect.x + rect.w - len(badge) - 10),
                     badge, attr(th.WHITE, bold=True, reverse=True))

        right = clock()
        safe_add(win, rect.y, rect.x + rect.w - len(right) - 1, right,
                 attr(th.WHITE, bold=True, reverse=True))

        total_cpu = cpu.get("total", 0.0)
        mem_pct = (100.0 * (memory.get("used", 0) / memory["total"])
                   if memory.get("total") else 0.0)
        cpu_level = severity(total_cpu, "cpu")
        mem_level = severity(mem_pct, "mem")

        cursor = rect.x + 1
        for label, value, level, series in (
            ("CPU", f"{total_cpu:>4.0f}%", cpu_level, "cpu"),
            ("RAM", f"{mem_pct:>4.0f}%", mem_level, "mem"),
        ):
            safe_add(win, rect.y + 1, cursor, label + " ",
                     attr(th.GREY, reverse=True))
            cursor += len(label) + 1
            safe_add(win, rect.y + 1, cursor, value,
                     attr(th.alert_color(level), bold=True, reverse=True))
            cursor += len(value) + 1
            if history is not None:
                direction = history.trend(series, epsilon=0.8)
                if direction != "none":
                    draw_trend(win, rect.y + 1, cursor, direction,
                               color=th.GREEN if direction == "down" else th.ORANGE)
            cursor += 3

        if self.paused:
            label = " PAUSED "
            safe_add(win, rect.y + 1, rect.x + rect.w - len(label) - 1, label,
                     attr(th.YELLOW, bold=True, reverse=True))
        else:
            cost = self.sampler.last_duration
            over = cost > self.refresh * 0.5
            label = f" {self.refresh:.2g}s{'!' if over else ''} "
            safe_add(win, rect.y + 1, rect.x + rect.w - len(label) - 1, label,
                     attr(th.ORANGE if over else th.GREY, reverse=True))

    def draw_tabs(self, win, rect: Rect) -> None:
        safe_add(win, rect.y, rect.x, " " * rect.w, attr(th.DARK_GREY, reverse=True),
                 max_width=rect.w)
        cursor = rect.x + 1
        for idx, tab in enumerate(TABS):
            label = f" {tab} "
            if idx == self.tab_index:
                color = th.BLUE
                flags = attr(color, bold=True, reverse=True)
            else:
                color = th.GREY
                flags = attr(color, reverse=True)
            consumed = safe_add(win, rect.y, cursor, label, flags,
                                max_width=max(0, rect.x + rect.w - cursor - 1))
            cursor += consumed
            if cursor >= rect.x + rect.w:
                break

    def draw_footer(self, win, rect: Rect, data: dict) -> None:
        safe_add(win, rect.y, rect.x, " " * rect.w, attr(th.DARK_GREY, reverse=True),
                 max_width=rect.w)
        if self.hide_keys:
            return
        cursor = rect.x + 1
        for key, label in KEY_HINTS:
            if cursor + len(key) + len(label) + 3 > rect.x + rect.w:
                break
            consumed = safe_add(win, rect.y, cursor, key,
                                attr(th.YELLOW, bold=True, reverse=True))
            cursor += consumed
            consumed = safe_add(win, rect.y, cursor, f" {label}",
                                attr(th.GREY, reverse=True))
            cursor += consumed + 2

    def draw_toast(self, win, height: int, width: int) -> None:
        if not self.toast or time.monotonic() > self.toast_until:
            return
        text = f" {self.toast} "
        w = len(text) + 2
        x = width // 2 - w // 2
        y = max(1, height // 2 + 3)
        for dy in range(3):
            safe_add(win, y + dy, x - 1, " " * (w + 2), attr(th.BLUE, reverse=True))
        safe_add(win, y + 1, x, text, attr(th.WHITE, bold=True, reverse=True))

    def draw_help(self, win, height: int, width: int) -> None:
        lines = [
            "PULSE — key bindings",
            "",
            "  Tab / Shift-Tab    cycle views",
            "  1 - 8              jump to a view",
            "  c                  overview dashboard",
            "  q / Esc            quit",
            "",
            "  /                  filter processes (type, Esc to clear)",
            "  s                  cycle process sort key",
            "  Up/Down, j/k       move process selection",
            "  PgUp/PgDn          jump 10 rows",
            "  g / Home           first row",
            "  End                last row",
            "",
            "  p                  pause live refresh",
            "  r                  reset sparkline history",
            "  + / -              refresh interval",
            "  ?                  toggle this help",
        ]
        box_w = 52
        box_h = len(lines) + 2
        x = max(0, width // 2 - box_w // 2)
        y = max(0, height // 2 - box_h // 2)
        rect = Rect(y, x, box_h, box_w)
        from .widgets import draw_panel
        fill = attr(th.BLUE, reverse=True)
        for row in range(rect.y, rect.y + rect.h):
            if row < 0 or row >= height:
                continue
            safe_add(win, row, rect.x, " " * rect.w, fill, max_width=rect.w)
        inner = draw_panel(win, rect, "Help", color=th.BLUE, focused=True)
        for idx, line in enumerate(lines):
            if idx >= inner.h:
                break
            color = th.WHITE if line and not line.startswith("  ") else th.GREY
            if idx == 0:
                color = th.YELLOW
            safe_add(win, inner.y + idx, inner.x, pad_to(line, inner.w),
                     attr(color), max_width=inner.w)

    # -- rendering ----------------------------------------------------------
    def render_view(self, win, rect: Rect, data: dict) -> None:
        tab = TABS[self.tab_index]
        if tab == "Overview":
            for panel, panel_rect in pack(self._panels, rect, data):
                panel.render(win, panel_rect, data)
        elif tab == "CPU":
            views.cpu_view(win, rect, data)
        elif tab == "Memory":
            views.memory_view(win, rect, data)
        elif tab == "Disk":
            views.disk_view(win, rect, data)
        elif tab == "Network":
            views.network_view(win, rect, data)
        elif tab == "Processes":
            views.process_view(win, rect, data, self.proc_state)
        elif tab == "Sensors":
            views.sensors_view(win, rect, data)
        elif tab == "Services":
            views.services_view(win, rect, data)

    def draw(self, win) -> None:
        win.erase()
        height, width = win.getmaxyx()
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            message = f"Terminal too small: {width}x{height} (need {MIN_WIDTH}x{MIN_HEIGHT})"
            safe_add(win, max(0, height // 2), max(0, (width - len(message)) // 2),
                     message, attr(th.YELLOW, bold=True))
            win.refresh()
            return

        data = dict(self.snapshot) if self.paused else dict(self.sampler.latest)
        data["history"] = self.history
        if not self.paused:
            self.history.update(self.sampler.latest)
        data["alerts"] = evaluate_alerts(self.sampler.latest)

        header = Rect(0, 0, 2, width)
        tabs = Rect(2, 0, 1, width)
        footer = Rect(height - 1, 0, 1, width)
        body = Rect(3, 0, max(0, height - 5), width)

        self.draw_header(win, header, data)
        self.draw_tabs(win, tabs)
        self.render_view(win, body, data)
        self.draw_footer(win, footer, data)
        self.draw_toast(win, height, width)
        if self.show_help:
            self.draw_help(win, height, width)
        win.noutrefresh()
        curses.doupdate()

    # -- lifecycle ----------------------------------------------------------
    def run(self, stdscr) -> None:
        self.sampler.start()
        while True:
            self.draw(stdscr)
            timeout = 100 if self.paused else int(max(50, (self.refresh - 0.05) * 1000))
            try:
                stdscr.timeout(timeout)
                key = stdscr.getch()
            except curses.error:
                continue
            if key == -1:
                continue
            if self.filter_active:
                if key in (10, 13, curses.KEY_ENTER):
                    self.filter_active = False
                elif key == 27:
                    self.filter_active = False
                    self.proc_state.filter_text = ""
                elif key == curses.KEY_BACKSPACE or key in (127, 8):
                    self.proc_state.filter_text = self.proc_state.filter_text[:-1]
                elif key == curses.KEY_RESIZE:
                    pass
                elif 32 <= key < 127:
                    self.proc_state.filter_text += chr(key)
                continue
            if not self.handle_key(key):
                break
        self.sampler.stop()
        self.sampler.join(timeout=1.0)


def _boot(stdscr, app: PulseApp) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    th.PALETTE.init()
    if app.ascii_mode:
        set_unicode(False)
    elif not terminal_supports_unicode():
        set_unicode(False)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    app.run(stdscr)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="pulse",
        description="Pulse — live hardware and services dashboard for Linux.",
    )
    parser.add_argument("-r", "--refresh", type=float, default=0.5,
                        help="refresh interval in seconds, 0.1-10 (default: 0.5)")
    parser.add_argument("-v", "--view", default="Overview",
                        choices=TABS, help="view to start on (default: Overview)")
    parser.add_argument("--ascii", action="store_true",
                        help="ASCII-only glyphs (no Unicode box drawing)")
    parser.add_argument("--keys", action="store_true",
                        help="show the key hints footer")
    parser.add_argument("--version", action="version", version="pulse 0.1.0")
    args = parser.parse_args(argv)

    if not sys.stdout.isatty():
        print("pulse: needs an interactive terminal (tty).", file=sys.stderr)
        return 1

    start_index = TABS.index(args.view) if args.view in TABS else 0
    app = PulseApp(refresh=args.refresh, start_tab=start_index,
                   ascii_mode=args.ascii, hide_keys=not args.keys)
    try:
        curses.wrapper(_boot, app)
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        print(f"pulse: terminal error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())