"""Small reusable helpers: bit strings, HTML grids, graph algorithms.

Display lives in ``tools.helpers.display``. Bit-string builders live in
``tools.helpers.bits``. VCD sampling lives in ``tools.helpers.vcd``.
Sequential-graph utilities stay in ``tools.state_graph``; Boolean parsing
stays in ``tools.logic``.
"""

from tools.helpers.bits import as_bits, bits_at
from tools.helpers.vcd import inputs_at_rising_clock_edge
from tools.helpers.display import (
    bit_grid_html,
    bit_strip_html,
    bit_trace_html,
    color_grid_html,
    grid_html,
    row_wrap_table_html,
    show_bit_grid,
    show_bit_trace,
    show_color_grid,
    show_grid,
    show_grids,
    show_row_wrap_table,
    write_grid_dot,
)

__all__ = [
    "as_bits",
    "bit_grid_html",
    "bit_strip_html",
    "bit_trace_html",
    "bits_at",
    "color_grid_html",
    "grid_html",
    "inputs_at_rising_clock_edge",
    "row_wrap_table_html",
    "show_bit_grid",
    "show_bit_trace",
    "show_color_grid",
    "show_grid",
    "show_grids",
    "show_row_wrap_table",
    "write_grid_dot",
]
