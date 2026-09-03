#!/usr/bin/env python3
"""Enumerate every warm-up register state using only extracted connectivity.

Run from the repository root with ``python3 -m examples.warmup_exhaustive``.
"""

from __future__ import annotations

from tools.circuit_eval import CircuitEvaluator
from tools.netlist_ir import Design


def main() -> None:
    design = Design.load("artifacts/netlists/warmup.json")
    registers = {
        register.name: register
        for register in design.strict_shift_registers().shift_registers
    }
    a_nets = registers["shift_A"].parallel_output_nets
    b_nets = registers["shift_B"].parallel_output_nets

    successful: list[tuple[int, int]] = []
    for a in range(256):
        for b in range(256):
            state = {
                **{net: bool(a & (1 << bit)) for bit, net in enumerate(a_nets)},
                **{net: bool(b & (1 << bit)) for bit, net in enumerate(b_nets)},
            }
            if CircuitEvaluator(design, state).value("S"):
                successful.append((a, b))

    sums = sorted({a + b for a, b in successful})
    print(f"evaluated states: {256 * 256}")
    print(f"successful states: {len(successful)}")
    print(f"successful pairs: {successful}")
    print(f"distinct A+B values: {sums}")


if __name__ == "__main__":
    main()
