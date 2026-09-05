"""Small reusable helpers: bit strings, HTML grids, graph algorithms.

Display lives in ``tools.helpers.display``. Bit-string builders live in
``tools.helpers.bits``. Sequential-graph utilities stay in
``tools.state_graph``; Boolean parsing stays in ``tools.logic``.
"""

from tools.helpers.bits import as_bits, bits_at
from tools.helpers.display import (
    bit_grid_html,
    bit_trace_html,
    color_grid_html,
    grid_html,
    show_bit_grid,
    show_bit_trace,
    show_color_grid,
    show_grid,
    show_grids,
)

__all__ = [
    "as_bits",
    "bit_grid_html",
    "bit_trace_html",
    "bits_at",
    "color_grid_html",
    "grid_html",
    "show_bit_grid",
    "show_bit_trace",
    "show_color_grid",
    "show_grid",
    "show_grids",
]
