"""Notebook HTML for black/white bit grids and timed bit traces."""

from __future__ import annotations

from collections.abc import Sequence

from tools.helpers.bits import as_bits

_ON = ("#111", "#111")
_OFF = ("#f2f2f2", "#c8c8c8")
_GAP = "#c8c8c8"
_ROW_RULE = "#e02424"


def _square(bit: object, cell_px: int) -> str:
    fill, edge = _ON if bit else _OFF
    return (
        f'<div style="width:{cell_px}px;height:{cell_px}px;'
        f"background:{fill};border:1px solid {edge};box-sizing:border-box;"
        '"></div>'
    )


def grid_html(bits: str | Sequence[object], cell_px: int = 26) -> str:
    """HTML for an 11×11 board (black = 1). Length must be 121."""
    values = as_bits(bits)
    if len(values) != 121:
        raise ValueError(f"expected 121 bits, got {len(values)}")
    squares = [_square(bit, cell_px) for bit in values]
    return (
        f'<div style="display:inline-grid;grid-template-columns:repeat(11,{cell_px}px);'
        f'gap:2px;line-height:0;">{"".join(squares)}</div>'
    )


def show_grid(bits: str | Sequence[object], cell_px: int = 26) -> None:
    """Draw a 121-bit word as an 11×11 board (black = 1)."""
    from IPython.display import HTML, display

    display(HTML(grid_html(bits, cell_px=cell_px)))


def show_grids(
    *labeled: tuple[str, str | Sequence[object]],
    cell_px: int = 12,
) -> None:
    """Draw several 11×11 boards in one row (black = 1)."""
    from IPython.display import HTML, display

    blocks = []
    for title, bits in labeled:
        heading = (
            f'<div style="font:12px Helvetica,sans-serif;margin:0 0 4px 0;">'
            f"{title}</div>"
        )
        blocks.append(
            f'<div style="display:inline-block;margin:0 16px 8px 0;vertical-align:top;">'
            f"{heading}{grid_html(bits, cell_px=cell_px)}</div>"
        )
    display(HTML("".join(blocks)))


_REGION_COLORS = (
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
    "#8cd17d",
)


def _color_square(label: int, cell_px: int, colors: Sequence[str]) -> str:
    if label < 0:
        fill, edge = _OFF
    else:
        fill = colors[label % len(colors)]
        edge = fill
    return (
        f'<div style="width:{cell_px}px;height:{cell_px}px;'
        f"background:{fill};border:1px solid {edge};box-sizing:border-box;"
        '"></div>'
    )


def color_grid_html(
    labels: Sequence[int],
    *,
    cell_px: int = 18,
    title: str = "",
    colors: Sequence[str] = _REGION_COLORS,
) -> str:
    """HTML for an 11×11 grid colored by integer label. Negative = empty."""
    if len(labels) != 121:
        raise ValueError(f"expected 121 labels, got {len(labels)}")
    squares = [_color_square(int(label), cell_px, colors) for label in labels]
    grid = (
        f'<div style="display:inline-grid;grid-template-columns:repeat(11,{cell_px}px);'
        f'gap:2px;line-height:0;">{"".join(squares)}</div>'
    )
    heading = (
        f'<div style="font:12px Helvetica,sans-serif;margin:0 0 4px 0;">{title}</div>'
        if title
        else ""
    )
    return (
        f'<div style="display:inline-block;margin:0 18px 16px 0;vertical-align:top;">'
        f"{heading}{grid}</div>"
    )


def show_color_grid(
    labels: Sequence[int],
    *,
    cell_px: int = 18,
    title: str = "",
    colors: Sequence[str] = _REGION_COLORS,
) -> None:
    """Draw an 11×11 grid colored by integer label."""
    from IPython.display import HTML, display

    display(
        HTML(
            color_grid_html(
                labels, cell_px=cell_px, title=title, colors=colors
            )
        )
    )


def bit_grid_html(
    rows: Sequence[Sequence[object]],
    *,
    cell_px: int = 16,
    row_labels: Sequence[str] | None = None,
    title: str = "",
) -> str:
    """HTML for a rectangular black/white bit grid (black = 1)."""
    if not rows:
        raise ValueError("expected at least one row")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("all rows must have the same length")
    if row_labels is not None and len(row_labels) != len(rows):
        raise ValueError("row_labels must match the number of rows")
    label_block = ""
    if row_labels is not None:
        labels = "".join(
            f'<div style="height:{cell_px}px;line-height:{cell_px}px;'
            f'font:12px/1 Helvetica,sans-serif;text-align:right;padding-right:6px;">'
            f"{label}</div>"
            for label in row_labels
        )
        label_block = (
            f'<div style="display:grid;grid-template-rows:repeat({len(rows)},{cell_px}px);'
            f'gap:2px;">{labels}</div>'
        )
    squares = [_square(bit, cell_px) for row in rows for bit in row]
    grid = (
        f'<div style="display:inline-grid;grid-template-columns:repeat({width},{cell_px}px);'
        f'gap:2px;line-height:0;">{"".join(squares)}</div>'
    )
    heading = (
        f'<div style="font:12px Helvetica,sans-serif;margin:0 0 4px 0;">{title}</div>'
        if title
        else ""
    )
    return (
        f'<div style="display:inline-block;margin:0 18px 16px 0;vertical-align:top;">'
        f"{heading}"
        f'<div style="display:flex;align-items:start;">{label_block}{grid}</div>'
        "</div>"
    )


def show_bit_grid(
    rows: Sequence[Sequence[object]],
    *,
    cell_px: int = 16,
    row_labels: Sequence[str] | None = None,
    title: str = "",
) -> None:
    """Draw a rectangular bit grid (black = 1)."""
    from IPython.display import HTML, display

    display(
        HTML(
            bit_grid_html(
                rows, cell_px=cell_px, row_labels=row_labels, title=title
            )
        )
    )


def _row_bands(n_rows: int, row_groups: Sequence[int] | None) -> list[range]:
    if row_groups is None:
        return [range(n_rows)]
    sizes = list(row_groups)
    if any(size <= 0 for size in sizes) or sum(sizes) != n_rows:
        raise ValueError(
            f"row_groups {sizes} must be positive and sum to {n_rows}"
        )
    bands = []
    start = 0
    for size in sizes:
        bands.append(range(start, start + size))
        start += size
    return bands


def _row_rule() -> str:
    return (
        f'<div style="height:2px;background:{_ROW_RULE};margin:3px 0;'
        'flex:0 0 2px;"></div>'
    )


def _label_band(names: Sequence[str], cell_px: int) -> str:
    labels = "".join(
        f'<div style="height:{cell_px}px;line-height:{cell_px}px;'
        f'font:11px/1 Helvetica,sans-serif;text-align:right;padding-right:6px;">'
        f"{name}</div>"
        for name in names
    )
    return (
        f'<div style="display:grid;grid-template-rows:repeat({len(names)},{cell_px}px);'
        f'gap:2px;">{labels}</div>'
    )


def bit_trace_html(
    trace: Sequence[Sequence[object]],
    windows: Sequence[Sequence[int]],
    *,
    row_labels: Sequence[str] | None = None,
    row_groups: Sequence[int] | None = None,
    cell_px: int = 14,
    group_gap_px: int = 16,
) -> str:
    """One horizontal strip of timed bit-windows (black = 1).

    ``trace[t][row]`` is the bit at clock ``t``. Each window is a list of
    clocks shown as consecutive columns, with the time index above each
    column. Windows are separated by a gray gutter of ``group_gap_px``.
    ``row_groups`` splits the bit rows (for example ``[4, 4, 1]``) with a
    red rule between bands.
    """
    if not trace:
        raise ValueError("expected at least one time step")
    n_rows = len(trace[0])
    if any(len(step) != n_rows for step in trace):
        raise ValueError("every time step must have the same number of bits")
    if row_labels is not None and len(row_labels) != n_rows:
        raise ValueError("row_labels must match the number of bits")
    bands = _row_bands(n_rows, row_groups)

    header_h = 16
    label_block = ""
    if row_labels is not None:
        stacked = []
        for i, band in enumerate(bands):
            stacked.append(_label_band([row_labels[r] for r in band], cell_px))
            if i < len(bands) - 1:
                stacked.append(_row_rule())
        label_block = (
            f'<div style="display:flex;flex-direction:column;">'
            f'<div style="height:{header_h}px;"></div>'
            f"{''.join(stacked)}</div>"
        )

    groups = []
    for times in windows:
        clocks = list(times)
        if not clocks:
            continue
        if any(t < 0 or t >= len(trace) for t in clocks):
            raise IndexError(
                f"window {clocks} is outside trace length {len(trace)}"
            )
        headers = "".join(
            f'<div style="width:{cell_px}px;height:{header_h}px;'
            f"font:8px/16px Helvetica,sans-serif;text-align:center;"
            f'letter-spacing:-0.4px;">{t}</div>'
            for t in clocks
        )
        cols = f"repeat({len(clocks)},{cell_px}px)"
        header_row = (
            f'<div style="display:grid;grid-template-columns:{cols};gap:2px;">'
            f"{headers}</div>"
        )
        stacked = []
        for i, band in enumerate(bands):
            squares = [
                _square(trace[t][row], cell_px) for row in band for t in clocks
            ]
            stacked.append(
                f'<div style="display:grid;grid-template-columns:{cols};'
                f"gap:2px;line-height:0;background:{_GAP};"
                f'">{"".join(squares)}</div>'
            )
            if i < len(bands) - 1:
                stacked.append(_row_rule())
        groups.append(
            f'<div style="display:flex;flex-direction:column;">'
            f"{header_row}{''.join(stacked)}</div>"
        )

    gutter_parts = [f'<div style="height:{header_h}px;"></div>']
    for i, band in enumerate(bands):
        band_h = len(band) * cell_px + max(0, len(band) - 1) * 2
        gutter_parts.append(
            f'<div style="height:{band_h}px;background:{_GAP};"></div>'
        )
        if i < len(bands) - 1:
            gutter_parts.append(_row_rule())
    gutter = (
        f'<div style="width:{group_gap_px}px;flex:0 0 {group_gap_px}px;'
        f'display:flex;flex-direction:column;">{"".join(gutter_parts)}</div>'
    )
    strip = gutter.join(groups)
    return (
        f'<div style="display:flex;align-items:start;line-height:0;overflow-x:auto;">'
        f"{label_block}{strip}</div>"
    )


def show_bit_trace(
    trace: Sequence[Sequence[object]],
    windows: Sequence[Sequence[int]],
    *,
    row_labels: Sequence[str] | None = None,
    row_groups: Sequence[int] | None = None,
    cell_px: int = 14,
    group_gap_px: int = 16,
) -> None:
    """Draw a horizontal timed bit-trace (black = 1)."""
    from IPython.display import HTML, display

    display(
        HTML(
            bit_trace_html(
                trace,
                windows,
                row_labels=row_labels,
                row_groups=row_groups,
                cell_px=cell_px,
                group_gap_px=group_gap_px,
            )
        )
    )
