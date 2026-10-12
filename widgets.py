"""Reusable curses drawing primitives: panels, bars, sparklines, tables."""

from __future__ import annotations

import curses
from dataclasses import dataclass

from . import theme as th
from .util import RingBuffer, clamp, sparkline_points

# ---------------------------------------------------------------------------
# Character sets (Unicode by default, ASCII fallback)
# ---------------------------------------------------------------------------

_UNICODE = True

BOX = {
    "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
    "h": "─", "v": "│", "vr": "│",
    "lt": "├", "rt": "┤",
    "bar": "█", "bar_light": "▒", "track": "░", "track_alt": "─",
    "blocks": "▁▂▃▄▅▆▇█",
    "dot": "•", "arrow": "›", "bullet": "▪",
}

_ASCII = {
    "tl": "+", "tr": "+", "bl": "+", "br": "+",
    "h": "-", "v": "|", "vr": "|",
    "lt": "+", "rt": "+",
    "bar": "#", "bar_light": "=", "track": ".", "track_alt": "-",
    "blocks": ".:-=+*#%@",
    "dot": "*", "arrow": ">", "bullet": "-",
}

_ASCII_SPARK = ".:-=+*#%@"


def set_unicode(enabled: bool) -> None:
    global _UNICODE
    _UNICODE = enabled


def glyph(name: str) -> str:
    return (BOX if _UNICODE else _ASCII)[name]


def spark_chars() -> str:
    return BOX["blocks"] if _UNICODE else _ASCII_SPARK


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def attr(color: tuple[int, int, int] | None = None, bold: bool = False,
         reverse: bool = False, underline: bool = False, dim: bool = False):
    """Build a curses attribute for a palette colour."""
    pair = th.PALETTE.pair(color) if color is not None else 0
    flags = curses.color_pair(pair)
    if bold:
        flags |= curses.A_BOLD
    if reverse:
        flags |= curses.A_REVERSE
    if underline:
        flags |= curses.A_UNDERLINE
    if dim:
        flags |= curses.A_DIM
    return flags


def safe_add(win, y: int, x: int, text: str, attributes: int = 0, max_width: int | None = None) -> int:
    """Write text at a position, clipped to the window and never raising."""
    if max_width is not None and max_width <= 0:
        return 0
    height, width = win.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= width:
        return 0
    text = text.replace("\n", " ")
    if max_width is not None and len(text) > max_width:
        text = text[:max_width]
    if x + len(text) > width:
        text = text[: max(0, width - x - 1)]
    if not text:
        return 0
    try:
        win.addstr(y, x, text, attributes)
    except curses.error:
        try:
            win.addstr(y, x, text.encode("utf-8", "replace").decode("utf-8", "replace"), attributes)
        except curses.error:
            pass
    return len(text)


def pad_to(text: str, width: int, align: str = "left", fill: str = " ") -> str:
    text = text[:width]
    if align == "right":
        return text.rjust(width, fill)
    if align == "center":
        return text.center(width, fill)
    return text.ljust(width, fill)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rect:
    y: int
    x: int
    h: int
    w: int

    @property
    def y2(self) -> int:
        return self.y + self.h - 1

    @property
    def x2(self) -> int:
        return self.x + self.w - 1

    def inner(self) -> "Rect":
        return Rect(self.y + 1, self.x + 1, max(0, self.h - 2), max(0, self.w - 2))

    def shrink(self, top: int = 0, bottom: int = 0, left: int = 0, right: int = 0) -> "Rect":
        return Rect(self.y + top, self.x + left,
                    max(0, self.h - top - bottom), max(0, self.w - left - right))

    def inset(self, amount: int) -> "Rect":
        return self.shrink(amount, amount, amount, amount)

    def height_for(self, rows: int) -> "Rect":
        return Rect(self.y, self.x, max(0, min(rows, self.h)), self.w)

    def contains(self, y: int, x: int) -> bool:
        return self.y <= y < self.y + self.h and self.x <= x < self.x + self.w


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


def draw_panel(win, rect: Rect, title: str, color=None, title_color=None,
               footer: str | None = None, focused: bool = False) -> Rect:
    """Draw a rounded panel and return its inner content rectangle."""
    border_color = color or th.DARK_GREY
    if focused:
        border_color = th.LIGHT_BLUE
    attrs = attr(border_color)
    tl, tr = glyph("tl"), glyph("tr")
    bl, br = glyph("bl"), glyph("br")
    h_line = glyph("h")

    if rect.h >= 2 and rect.w >= 2:
        safe_add(win, rect.y, rect.x, tl + h_line * (rect.w - 2) + tr, attrs)
        for row in range(1, rect.h - 1):
            safe_add(win, rect.y + row, rect.x, glyph("v"), attrs)
            safe_add(win, rect.y + row, rect.x2, glyph("v"), attrs)
        safe_add(win, rect.y2, rect.x, bl + h_line * (rect.w - 2) + br, attrs)

    inner = rect.inner()
    if inner.w > 0 and rect.h >= 2:
        label = f" {title} " if title else ""
        tcolor = title_color or (th.LIGHT_BLUE if focused else th.WHITE)
        safe_add(win, rect.y, rect.x + 2, label, attr(tcolor, bold=True),
                 max_width=max(0, rect.w - 4))
        if footer and rect.h >= 4:
            flabel = f" {footer} "
            flen = len(flabel)
            safe_add(win, rect.y2, max(rect.x + 2, rect.x2 - flen - 1), flabel,
                     attr(th.DARK_GREY), max_width=max(0, rect.w - 4))
    return inner


def draw_section_title(win, y: int, x: int, width: int, text: str, color=None) -> None:
    color = color or th.GREY
    label = f"{glyph('arrow')} {text.upper()}"
    safe_add(win, y, x, label, attr(color, bold=True), max_width=width)


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------


def draw_bar(win, y: int, x: int, width: int, fraction: float,
             color=None, track_color=None, gradient: bool = True,
             filled: str | None = None, track: str | None = None,
             ticks: tuple[float, ...] = ()) -> int:
    """Horizontal progress bar. Returns the number of filled cells.

    Runs of identically-coloured cells are emitted as a single `addstr` call
    rather than one call per cell, which is what keeps dense dashboards cheap
    to redraw.
    """
    if width <= 0:
        return 0
    fraction = clamp(fraction if fraction is not None else 0.0, 0.0, 1.0)
    filled_char = filled or glyph("bar")
    track_char = track or glyph("track")
    base = color or th.BLUE
    filled_cells = int(round(fraction * width))
    if filled_cells < 1 and fraction > 0:
        filled_cells = 1
    filled_cells = min(filled_cells, width)

    tick_positions = set()
    for tick in ticks:
        pos = int(round(clamp(tick, 0.0, 1.0) * width))
        if 0 <= pos < width:
            tick_positions.add(pos)

    if gradient:
        if filled_cells == width and not tick_positions:
            safe_add(win, y, x, filled_char * width,
                     attr(th.cpu_color(100.0), bold=True), max_width=width)
            return width
        for i in range(filled_cells):
            if i in tick_positions:
                continue
            cell = th.cpu_color(100.0 * (i + 1) / width)
            safe_add(win, y, x + i, filled_char, attr(cell, bold=True), max_width=1)
    else:
        safe_add(win, y, x, filled_char * filled_cells,
                 attr(base, bold=True), max_width=width)

    if filled_cells < width:
        start = filled_cells
        run = width - start
        if run > 0:
            safe_add(win, y, x + start, track_char * run,
                     attr(track_color or th.DARK_GREY), max_width=run)

    for pos in sorted(tick_positions):
        if pos < filled_cells:
            safe_add(win, y, x + pos, glyph("v") if _UNICODE else "|",
                     attr(th.RED, bold=True), max_width=1)
        else:
            safe_add(win, y, x + pos, glyph("v") if _UNICODE else "|",
                     attr(th.DARK_GREY), max_width=1)
    return filled_cells


def draw_inline_bar(win, y: int, x: int, width: int, fraction: float, color=None) -> None:
    draw_bar(win, y, x, width, fraction, color=color)


def draw_value_bar(win, y: int, x: int, width: int, label: str, value: str,
                   fraction: float, label_width: int, color=None,
                   gradient: bool = True, value_color=None,
                   ticks: tuple[float, ...] = ()) -> None:
    """`<label> <bar> <value>` row, the workhorse of the metric panels.

    `ticks` places faint markers on the track (e.g. the warn/critical
    thresholds) so the reader can see how close a value is to trouble.
    """
    if width <= 0:
        return
    value_width = max(6, len(value))
    safe_add(win, y, x, pad_to(label, label_width), attr(th.GREY), max_width=width)
    bar_start = x + label_width
    bar_width = max(0, width - label_width - value_width - 1)
    if bar_width > 0:
        draw_bar(win, y, bar_start, bar_width, fraction,
                 color=color, gradient=gradient, ticks=ticks)
    safe_add(win, y, x + width - value_width, value,
             attr(value_color or th.WHITE, bold=True), max_width=value_width)


TREND_GLYPHS = {"up": "▲", "down": "▼", "flat": "▬", "none": " "}


def draw_trend(win, y: int, x: int, direction: str, color=None) -> None:
    """Small arrow showing whether a series is rising or falling."""
    glyph = TREND_GLYPHS.get(direction)
    if not glyph:
        return
    safe_add(win, y, x, glyph, attr(color or th.GREY), max_width=1)


# ---------------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------------

_SPARK_INDEX = {}


def draw_sparkline(win, y: int, x: int, width: int, values: list[float],
                   color=None, low: float | None = None, high: float | None = None,
                   gradient: bool = True, fill: bool = False) -> None:
    """Single-row block sparkline."""
    if width <= 0:
        return
    chars = spark_chars()
    points = sparkline_points(values, width, low, high)
    if not points:
        for i in range(width):
            safe_add(win, y, x + i, glyph("track_alt"), attr(th.DARK_GREY), max_width=1)
        return
    attributes = []
    for v in points:
        c = th.cpu_color(v * 100.0) if gradient else (color or th.CYAN)
        attributes.append(attr(c))
    pad = width - len(points)
    for i in range(pad):
        safe_add(win, y, x + i, " ", 0, max_width=1)
    for i, value in enumerate(points):
        idx = int(round(value * (len(chars) - 1)))
        idx = max(0, min(len(chars) - 1, idx))
        safe_add(win, y, x + pad + i, chars[idx], attributes[i], max_width=1)


def draw_sparkline_column(win, rect: Rect, values: list[float], color=None,
                          low: float | None = None, high: float | None = None,
                          gradient: bool = True) -> None:
    """Vertical multi-row sparkline filling the given rectangle."""
    if rect.w <= 0 or rect.h <= 0:
        return
    chars = spark_chars()
    series = values[-rect.w:] if len(values) > rect.w else values
    if not series:
        return
    points = sparkline_points(series, rect.w, low, high)
    for col, value in enumerate(points):
        c = th.cpu_color(value * 100.0) if gradient else (color or th.CYAN)
        col_attrs = attr(c)
        height_cells = value * rect.h
        for row in range(rect.h):
            screen_row = rect.y2 - row
            cell = height_cells - row
            if cell >= 1:
                safe_add(win, screen_row, rect.x + col, glyph("bar"), col_attrs, max_width=1)
            elif cell > 0.05:
                idx = max(0, min(len(chars) - 1, int(cell * len(chars))))
                safe_add(win, screen_row, rect.x + col, chars[idx], col_attrs, max_width=1)


def draw_vertical_gauge(win, rect: Rect, fraction: float, value_text: str = "",
                        label: str = "", color=None) -> None:
    """Vertical filled gauge with a value in the middle."""
    if rect.h <= 0 or rect.w <= 0:
        return
    fraction = clamp(fraction or 0.0, 0.0, 1.0)
    filled = int(round(fraction * rect.h))
    bar_w = min(rect.w, 1) if rect.w < 6 else max(1, rect.w // 2)
    bar_x = rect.x + (rect.w - bar_w) // 2
    for row in range(rect.h):
        screen_row = rect.y2 - row
        if row < filled:
            safe_add(win, screen_row, bar_x, glyph("bar") * bar_w,
                     attr(color or th.cpu_color(fraction * 100.0), bold=True), max_width=bar_w)
        else:
            safe_add(win, screen_row, bar_x, glyph("track") * bar_w,
                     attr(th.DARK_GREY), max_width=bar_w)
    if value_text and rect.w >= len(value_text):
        safe_add(win, rect.y + rect.h // 2, rect.x + (rect.w - len(value_text)) // 2,
                 value_text, attr(th.WHITE, bold=True), max_width=rect.w)
    if label and rect.h >= 3 and rect.w >= len(label):
        safe_add(win, rect.y, rect.x + (rect.w - len(label)) // 2, label,
                 attr(th.DARK_GREY), max_width=rect.w)


def draw_donut(win, y: int, x: int, size: int, fraction: float, color=None) -> None:
    """Small circular gauge rendered with block characters."""
    if size < 3:
        return
    fraction = clamp(fraction or 0.0, 0.0, 1.0)
    color = color or th.cpu_color(fraction * 100.0)
    rows = ["▔▔▔", "█ █", "▁▁▁"]
    half = len(rows[1]) // 2 + len(rows[1]) % 2
    filled = int(round(fraction * half * 2))
    for idx, line in enumerate(rows):
        for col, ch in enumerate(line):
            pos = idx * half + col
            if ch == " ":
                continue
            if pos < filled:
                safe_add(win, y + idx, x + col, ch, attr(color, bold=True), max_width=1)
            else:
                safe_add(win, y + idx, x + col, ch, attr(th.DARK_GREY), max_width=1)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class Table:
    """Fixed-column text table with per-column alignment and colours."""

    def __init__(self, columns: list[dict], row_gap: int = 0) -> None:
        self.columns = columns
        self.row_gap = row_gap

    @property
    def width(self) -> int:
        return sum(col.get("width", 0) for col in self.columns) + len(self.columns)

    def visible_columns(self, width: int) -> list[dict]:
        cols = list(self.columns)
        while cols and sum(c.get("width", 0) for c in cols) + len(cols) > width:
            cols.pop()
        return cols

    def render_row(self, win, y: int, x: int, cells: list[str],
                   max_width: int | None = None, default_color=None,
                   row_colors: list | None = None, bold: bool = False) -> None:
        cursor = x
        for idx, col in enumerate(self.columns):
            if max_width is not None and cursor - x >= max_width:
                return
            w = col.get("width", 0)
            if w <= 0:
                continue
            text = cells[idx] if idx < len(cells) else ""
            color = (row_colors[idx] if row_colors and idx < len(row_colors)
                     else col.get("color")) or default_color
            attrs = attr(color, bold=bold or col.get("bold", False),
                         dim=col.get("dim", False))
            safe_add(win, y, cursor, pad_to(text, w, col.get("align", "left")),
                     attrs, max_width=w)
            cursor += w + 1


def draw_kv_row(win, y: int, x: int, width: int, pairs: list[tuple[str, str]],
                key_color=None, value_color=None, key_width: int = 0) -> None:
    """Lay out `label: value` pairs horizontally until the width runs out."""
    cursor = x
    key_color = key_color or th.DARK_GREY
    value_color = value_color or th.WHITE
    for key, value in pairs:
        entry = f"{key} {value}"
        w = len(entry)
        if cursor + w > x + width:
            break
        safe_add(win, y, cursor, key + " ", attr(key_color), max_width=w)
        consumed = safe_add(win, y, cursor + len(key) + 1, value,
                            attr(value_color, bold=True), max_width=x + width - cursor - len(key) - 1)
        cursor += len(key) + 1 + consumed + 2


def draw_columns(win, y: int, x: int, width: int, items: list[tuple[str, str]]) -> None:
    """Evenly spread short label/value columns across the available width."""
    if not items:
        return
    col_width = width // len(items)
    for idx, (label, value) in enumerate(items):
        col_x = x + idx * col_width
        if col_x + col_width > x + width:
            break
        safe_add(win, y, col_x, pad_to(label, col_width - 1, "right"),
                 attr(th.DARK_GREY), max_width=col_width - 1)
        safe_add(win, y, col_x, value, attr(th.WHITE, bold=True), max_width=col_width - 1)


def history_bars() -> RingBuffer:
    return RingBuffer(180)