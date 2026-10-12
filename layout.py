"""Responsive column packing for the dashboard.

Panels declare a preferred height and a minimum width; the packer distributes
them across as many columns as the terminal can afford, then stacks them so
each column fills its available height before spilling into a new column.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .widgets import Rect

MIN_PANEL_WIDTH = 26
COLUMN_GAP = 1


@dataclass
class Panel:
    """A titled block of content that the packer can position."""

    key: str
    title: str
    preferred_height: int = 6
    min_height: int = 3
    min_width: int = MIN_PANEL_WIDTH
    expand: bool = False
    render_fn: object = field(default=None, repr=False)
    # Optional (data) -> int: lets a panel ask for the height its content
    # actually needs, instead of a fixed guess that silently truncates lists.
    height_fn: object = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.height = self.preferred_height

    def height_for(self, data: dict | None = None) -> int:
        if self.height_fn is not None:
            try:
                return max(self.min_height, int(self.height_fn(data or {})))
            except (TypeError, ValueError, KeyError):
                return self.preferred_height
        return self.preferred_height

    def render(self, win, rect: Rect, data: dict) -> None:
        if self.render_fn is not None:
            self.render_fn(win, rect, data)


def column_count(width: int) -> int:
    """How many columns fit at a comfortable panel width."""
    if width >= 200:
        return 4
    if width >= 140:
        return 3
    if width >= 90:
        return 2
    return 1


def pack(panels: list[Panel], area: Rect, data: dict | None = None) -> list[tuple[Panel, Rect]]:
    """Position panels inside `area`, returning placed (panel, rect) pairs.

    Panels that declare a `height_fn` are measured against the current data,
    so a list panel grows to fit its rows instead of being cut off at an
    arbitrary fixed height.
    """
    if not panels or area.w <= 0 or area.h <= 0:
        return []

    columns = column_count(area.w)
    usable_w = area.w - COLUMN_GAP * (columns - 1)
    col_w = usable_w // columns
    if col_w < MIN_PANEL_WIDTH:
        columns = 1
        col_w = area.w

    placed: list[tuple[Panel, Rect]] = []
    col_panels: list[list[Panel]] = [[] for _ in range(columns)]
    heights: dict[str, int] = {p.key: p.height_for(data) for p in panels}

    cursor_col = 0
    used_h = 0
    for panel in panels:
        if panel.min_width > col_w and columns > 1:
            # This panel wants the full width: flush the current column first.
            cursor_col = 0
            used_h = 0
        if used_h + panel.min_height > area.h and used_h > 0:
            cursor_col += 1
            used_h = 0
            if cursor_col >= columns:
                # No more columns: overflow is dropped rather than clipped.
                break
        col_panels[cursor_col].append(panel)
        used_h += heights[panel.key]

    for idx, group in enumerate(col_panels):
        if not group:
            continue
        col_x = area.x + idx * (col_w + COLUMN_GAP)
        y = area.y
        for panel in group:
            if y >= area.y + area.h:
                break
            avail_h = area.y + area.h - y
            height = min(heights[panel.key], avail_h)
            if height < panel.min_height:
                break
            rect = Rect(y, col_x, height, col_w)
            placed.append((panel, rect))
            y += height + COLUMN_GAP

    return placed