"""Notebook-facing simulator: reset, tick, scan, and replay.

Display helpers live in ``tools.helpers.display``. Low-level evaluation
lives in ``tools.circuit_eval``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Mapping

from tools.circuit_eval import one_clock_transition, state_net_by_instance
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
from tools.netlist_ir import Design

__all__ = [
    "Play",
    "as_bits",
    "bit_grid_html",
    "bit_trace_html",
    "bits_at",
    "color_grid_html",
    "grid_html",
    "i_toggle_hits",
    "show_bit_grid",
    "show_bit_trace",
    "show_color_grid",
    "show_grid",
    "show_grids",
]


class Play:
    """Clock-boundary driver for one extracted ``Design``.

    Defaults match the puzzle ports. Override ``data`` / ``enable`` / ``reset``
    for other netlists (the toy uses ``din`` and ``en``).
    """

    def __init__(
        self,
        design: Design,
        *,
        data: str = "I",
        enable: str = "enable",
        reset: str = "rst_n",
        floating: Mapping[str, bool] | None = None,
        success: str = "success",
        output_bus: str = "O",
        output_width: int = 8,
    ) -> None:
        self.design = design
        self.data = data
        self.enable = enable
        self.reset = reset
        self.floating = dict(floating) if floating is not None else {"n0550": False}
        self.success = success
        self.output_bus = output_bus
        self.output_width = output_width
        self.state_net = state_net_by_instance(design)

    def q(self, state: Mapping[str, bool], instance: str) -> int:
        """Current Q of a flip-flop, as 0 or 1."""
        return int(state[self.state_net[instance]])

    def _pins(self, enable: bool, bit: bool = False) -> dict[str, bool]:
        return {
            self.reset: True,
            self.enable: bool(enable),
            self.data: bool(bit),
            **self.floating,
        }

    def reset_state(self, clocks: int = 3) -> dict[str, bool]:
        """Assert reset, then release it. Do not assume every flop clears to 0."""
        state = {net: False for net in self.state_net.values()}
        held = {
            self.reset: False,
            self.enable: False,
            self.data: False,
            **self.floating,
        }
        for _ in range(clocks):
            state = one_clock_transition(
                self.design, state, held, output_names=()
            ).next_state
        idle = self._pins(False)
        return one_clock_transition(
            self.design, state, idle, output_names=()
        ).next_state

    def tick(
        self,
        state: Mapping[str, bool],
        enable: bool,
        bit: bool = False,
        outputs: Iterable[str] = (),
    ):
        """One active clock edge. ``outputs`` names extra nets to evaluate."""
        return one_clock_transition(
            self.design,
            state,
            self._pins(enable, bit),
            output_names=list(outputs),
        )

    def scan(
        self, bits: str | Sequence[object], clocks: int | None = None
    ) -> dict[str, bool]:
        """Clock an enabled bit-string into the data pin. Default: ``len(bits)`` edges."""
        values = as_bits(bits)
        if clocks is None:
            clocks = len(values)
        state = self.reset_state()
        for position in range(clocks):
            bit = values[position] if position < len(values) else False
            state = self.tick(state, True, bit).next_state
        return state

    def replay_attempt(
        self,
        bits: str | Sequence[object],
        trailing_edges: int = 16,
    ) -> tuple[list[int], list[bool]]:
        """Scan ``bits``, drop enable, and collect output-bus bytes plus ``success``."""
        state = self.reset_state()
        for bit in as_bits(bits):
            state = self.tick(state, True, bit).next_state
        watches = [self.success] + [
            f"{self.output_bus}[{i}]" for i in range(self.output_width)
        ]
        byte_values: list[int] = []
        success_values: list[bool] = []
        for _ in range(trailing_edges):
            result = self.tick(state, False, False, outputs=watches)
            byte_values.append(
                sum(
                    int(result.outputs_after_edge[f"{self.output_bus}[{i}]"]) << i
                    for i in range(self.output_width)
                )
            )
            success_values.append(bool(result.outputs_after_edge[self.success]))
            state = result.next_state
        return byte_values, success_values


def i_toggle_hits(
    play: Play,
    pairs: Sequence[Collection[str]],
    length: int = 121,
) -> list[set[int]]:
    """Cells where flipping ``I`` changes a 2-bit pair's next state.

    Walk the scan once. At each position, take one edge with ``I = 0`` and
    one with ``I = 1`` from the same state. A pair "listens" here if any of
    its flops would store a different bit.
    """
    hits = [set() for _ in pairs]
    state = play.reset_state()
    for position in range(length):
        low = play.tick(state, True, False).next_state
        high = play.tick(state, True, True).next_state
        for index, pair in enumerate(pairs):
            if any(
                low[play.state_net[name]] != high[play.state_net[name]]
                for name in pair
            ):
                hits[index].add(position)
        state = low
    return hits
