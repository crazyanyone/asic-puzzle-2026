"""Notebook-facing helpers for clocking an extracted netlist.

Low-level evaluation lives in ``tools.circuit_eval``. This module is the
small API used by the walkthrough: reset, tick, scan a bit-string, replay
an attempt, and draw a 121-bit word as an 11×11 board.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Mapping

from tools.circuit_eval import one_clock_transition, state_net_by_instance
from tools.netlist_ir import Design


def as_bits(bits: str | Sequence[object]) -> list[bool]:
    """A ``'0101…'`` string, or a sequence of 0/1/bool, as a list of bool."""
    if isinstance(bits, str):
        return [ch == "1" for ch in bits]
    return [bool(b) for b in bits]


def bits_at(*positions: int, length: int = 121) -> str:
    """Build a bit string with ``1`` at each given cell index."""
    chars = ["0"] * length
    for position in positions:
        chars[position] = "1"
    return "".join(chars)


def grid_html(bits: str | Sequence[object], cell_px: int = 26) -> str:
    """HTML for an 11×11 board (black = 1). Length must be 121."""
    values = as_bits(bits)
    if len(values) != 121:
        raise ValueError(f"expected 121 bits, got {len(values)}")
    squares = []
    for bit in values:
        fill = "#111" if bit else "#f2f2f2"
        edge = "#111" if bit else "#c8c8c8"
        squares.append(
            f'<div style="width:{cell_px}px;height:{cell_px}px;'
            f"background:{fill};border:1px solid {edge};box-sizing:border-box;"
            '"></div>'
        )
    return (
        f'<div style="display:inline-grid;grid-template-columns:repeat(11,{cell_px}px);'
        f'gap:2px;line-height:0;">{"".join(squares)}</div>'
    )


def show_grid(bits: str | Sequence[object], cell_px: int = 26) -> None:
    """Draw a 121-bit word as an 11×11 board (black = 1)."""
    from IPython.display import HTML, display

    display(HTML(grid_html(bits, cell_px=cell_px)))


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
