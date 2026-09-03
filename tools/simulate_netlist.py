#!/usr/bin/env python3
"""Play a sequence of inputs through an extracted synchronous circuit.

Example for the two-bit toy:
    python3 -m tools.simulate_netlist tests/fixtures/toy_nets.json \
      --input din=1,0,1,1 --input en=1 --input rst_n=1 \
      --watch FF0_dfrtp.Q --watch FF1_dfrtp.Q --watch success
"""

from __future__ import annotations

import argparse
import sys

from tools.circuit_eval import EvaluationError, one_clock_transition, state_net_by_instance
from tools.netlist_ir import Design


def parse_sequence(specification: str) -> tuple[str, list[bool]]:
    if "=" not in specification:
        raise ValueError(f"Expected NAME=0,1,..., got {specification!r}")
    name, raw_values = specification.split("=", 1)
    values = raw_values.split(",")
    if not name or not values or any(value not in {"0", "1"} for value in values):
        raise ValueError(f"Expected NAME=0,1,..., got {specification!r}")
    return name, [value == "1" for value in values]


def bit(value: bool) -> str:
    return "1" if value else "0"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nets")
    parser.add_argument(
        "--input", action="append", default=[], metavar="NAME=BITS"
    )
    parser.add_argument(
        "--initial", action="append", default=[], metavar="STATE=BIT"
    )
    parser.add_argument(
        "--watch", action="append", default=[], help="Net, port, or terminal"
    )
    args = parser.parse_args()

    try:
        design = Design.load(args.nets)
        sequences = dict(parse_sequence(item) for item in args.input)
        initial_items = dict(parse_sequence(item) for item in args.initial)
        if any(len(values) != 1 for values in initial_items.values()):
            raise ValueError("Each --initial value must contain exactly one bit")
        cycles = max((len(values) for values in sequences.values()), default=1)
        if any(len(values) not in {1, cycles} for values in sequences.values()):
            raise ValueError("Input sequences must have length 1 or the maximum length")

        state = {
            net: False for net in state_net_by_instance(design).values()
        }
        for name, values in initial_items.items():
            instance_net = state_net_by_instance(design).get(name)
            net = instance_net or design.resolve_net(name).name
            state[net] = values[0]

        watches = args.watch or sorted(
            alias
            for alias, net in design.ports.items()
            if net.inferred_direction == "output"
        )
        watch_nets = {name: design.resolve_net(name).name for name in watches}

        print("edge  inputs  | before -> after")
        for cycle in range(cycles):
            inputs = {
                name: values[0] if len(values) == 1 else values[cycle]
                for name, values in sequences.items()
            }
            result = one_clock_transition(
                design,
                state,
                inputs,
                output_names=watches,
            )
            before_eval = result.outputs_before_edge
            after_eval = result.outputs_after_edge
            input_text = " ".join(f"{name}={bit(value)}" for name, value in inputs.items())
            watch_text = " ".join(
                f"{name}:{bit(before_eval[name])}->{bit(after_eval[name])}"
                for name in watches
            )
            print(f"{cycle + 1:>4}  {input_text:<24} | {watch_text}")
            state = result.next_state
        return 0
    except (OSError, ValueError, KeyError, EvaluationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
