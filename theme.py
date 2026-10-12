"""Colour palette and curses colour-pair management.

Supports truecolor terminals (COLORTERM=truecolor), 256-colour terminals and
falls back to the 8/16 base curses colours on dumb terminals.
"""

from __future__ import annotations

import curses
import os

# ---------------------------------------------------------------------------
# Palette definition
# ---------------------------------------------------------------------------

_RESET = (-1, -1, -1)


class Palette:
    """A 24-bit palette mapped onto curses colour pairs.

    Only the colours actually requested get an allocated pair, so a curses
    `COLOR_PAIRS` limit is not a problem even on large screens.
    """

    def __init__(self) -> None:
        self.mode = "dumb"
        self._pairs: dict[int, int] = {}
        self._next_pair = 1
        self.max_colors = 8

    def init(self) -> None:
        try:
            curses.start_color()
            curses.use_default_colors()
            self.max_colors = curses.COLORS
            self.max_pairs = curses.COLORS_PAIRS
        except (curses.error, AttributeError):
            self.mode = "dumb"
            return

        colorterm = os.environ.get("COLORTERM", "").lower()
        if self.max_colors >= 2 ** 24 and "truecolor" in colorterm:
            self.mode = "truecolor"
        elif self.max_colors >= 256:
            self.mode = "256"
        elif self.max_colors >= 16:
            self.mode = "16"
        else:
            self.mode = "8"

    @property
    def max_pairs(self) -> int:
        return getattr(self, "_max_pairs", 32767)

    @max_pairs.setter
    def max_pairs(self, value: int) -> None:
        self._max_pairs = value

    # -- colour pair management ---------------------------------------------
    def _rgb(self, color: tuple[int, int, int]) -> tuple[int, int, int]:
        return color

    def _to_256(self, color: tuple[int, int, int]) -> int:
        r, g, b = (max(0, min(255, c)) for c in color)
        if abs(r - g) < 10 and abs(g - b) < 10:
            grey = max(0, min(23, round((r + g + b) / 3 / 10.7)))
            return 232 + grey
        def cube(c: int) -> int:
            steps = (0, 95, 135, 175, 215, 255)
            best, dist = 0, 1e9
            for i, s in enumerate(steps):
                d = abs(c - s)
                if d < dist:
                    best, dist = i, d
            return best
        return 16 + 36 * cube(r) + 6 * cube(g) + cube(b)

    def _to_basic(self, color: tuple[int, int, int]) -> int:
        r, g, b = color
        if r > 128 and g > 128 and b > 128:
            return curses.COLOR_WHITE
        if r > 128 and g < 128 and b < 128:
            return curses.COLOR_RED
        if r < 128 and g > 128 and b < 128:
            return curses.COLOR_GREEN
        if r < 128 and g < 128 and b > 128:
            return curses.COLOR_BLUE
        if r > 128 and g > 128 and b < 128:
            return curses.COLOR_YELLOW
        if r > 128 and g < 128 and b > 128:
            return curses.COLOR_MAGENTA
        if r < 128 and g > 128 and b > 128:
            return curses.COLOR_CYAN
        return curses.COLOR_YELLOW

    def pair(self, color: tuple[int, int, int] | None) -> int:
        """Return a curses colour-pair number for an RGB colour."""
        if color is None or self.mode == "dumb":
            return 0
        key = color
        cached = self._pairs.get(key)
        if cached is not None:
            return cached
        if self._next_pair >= min(self.max_pairs, 256):
            return 0
        pair_id = self._next_pair
        self._next_pair += 1
        self._pairs[key] = pair_id
        try:
            if self.mode == "truecolor":
                curses.init_color(pair_id, *self._rgb(color))
                curses.init_pair(pair_id, pair_id, -1)
            elif self.mode == "256":
                curses.init_pair(pair_id, self._to_256(color), -1)
            else:
                curses.init_pair(pair_id, self._to_basic(color), -1)
        except (curses.error, ValueError):
            self._pairs[key] = 0
            return 0
        return pair_id


PALETTE = Palette()

# ---------------------------------------------------------------------------
# Colour ramps used for load-based colouring
# ---------------------------------------------------------------------------

GREEN = (46, 204, 113)
YELLOW = (241, 196, 15)
ORANGE = (243, 156, 18)
RED = (231, 76, 60)
BLUE = (52, 152, 219)
CYAN = (26, 188, 156)
MAGENTA = (155, 89, 182)
PURPLE = (142, 68, 173)
GREY = (149, 165, 166)
DARK_GREY = (99, 110, 114)
WHITE = (236, 240, 241)
LIGHT_BLUE = (93, 173, 226)

CPU_COLORS = [BLUE, LIGHT_BLUE, CYAN]
MEM_COLORS = [GREEN, (46, 204, 113)]
NET_COLORS = [CYAN, BLUE]
DISK_COLORS = [PURPLE, MAGENTA]


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _mix(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (
        _lerp(c1[0], c2[0], t),
        _lerp(c1[1], c2[1], t),
        _lerp(c1[2], c2[2], t),
    )


def cpu_color(percent: float) -> tuple[int, int, int]:
    """Green -> yellow -> red ramp for a 0..100 usage percentage."""
    if percent is None:
        return GREY
    if percent < 50:
        return _mix(GREEN, YELLOW, percent / 50.0)
    if percent < 80:
        return _mix(YELLOW, ORANGE, (percent - 50) / 30.0)
    return _mix(ORANGE, RED, min(1.0, (percent - 80) / 20.0))


def alert_color(level: int) -> tuple[int, int, int]:
    """Colour for a 0..3 severity level (ok / warn / high / critical)."""
    from .alerts import COLORS
    return COLORS.get(level, GREY)


def temp_color(celsius: float | None) -> tuple[int, int, int]:
    if celsius is None:
        return GREY
    if celsius < 55:
        return _mix(GREEN, YELLOW, max(0.0, (celsius - 35) / 20.0))
    if celsius < 75:
        return _mix(YELLOW, ORANGE, (celsius - 55) / 20.0)
    return _mix(ORANGE, RED, min(1.0, (celsius - 75) / 15.0))


def net_color(rate: float) -> tuple[int, int, int]:
    if rate is None:
        return GREY
    if rate < 1024:
        return _mix(GREEN, CYAN, min(1.0, rate / 1024.0))
    if rate < 1024 ** 2:
        return _mix(CYAN, BLUE, (rate - 1024) / (1024 ** 2 - 1024))
    return _mix(BLUE, PURPLE, min(1.0, rate / (50 * 1024 ** 2)))