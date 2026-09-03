#!/usr/bin/env python3
"""Exhaustively test whether toggling one net can change a target cone.

This is intentionally a small truth-table check, not SAT. It is practical only
when the target's primary-input and current-state boundary is small.

Example:
    python3 -m tools.check_influence artifacts/netlists/puzzle.json \
      n0550 O[1]
"""

from __future__ import annotations

import argparse
import itertools
import sys

from tools.circuit_eval import CircuitEvaluator, EvaluationError
from tools.netlist_ir import Design


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nets")
    parser.add_argument("candidate", help="Net to force to 0 and 1")
    parser.add_argument("target", help="Target net or port")
    parser.add_argument("--max-variables", type=int, default=20)
    args = parser.parse_args()

    try:
        design = Design.load(args.nets)
        candidate = design.resolve_net(args.candidate).name
        target = design.resolve_net(args.target).name
        cone = design.backward_cone(target)
        variables = {
            design.instances[name].pins["Q"].net
            for name in cone.state_boundaries
        }
        variables.update(
            net.name
            for net in design.nets.values()
            if net.name in cone.nets and net.inferred_direction == "input"
        )
        variables.discard(candidate)
        ordered = sorted(variables)
        if len(ordered) > args.max_variables:
            raise ValueError(
                f"cone has {len(ordered)} variables; raise --max-variables "
                "or use SAT/BDD analysis"
            )

        tested = 0
        for bits in itertools.product((False, True), repeat=len(ordered)):
            assignment = dict(zip(ordered, bits))
            low = CircuitEvaluator(
                design, {**assignment, candidate: False}
            ).value(target)
            high = CircuitEvaluator(
                design, {**assignment, candidate: True}
            ).value(target)
            tested += 1
            if low != high:
                readable = {
                    design.source_description(net): int(value)
                    for net, value in assignment.items()
                }
                print(f"INFLUENTIAL after {tested} assignments")
                print(f"  {args.candidate}=0 -> {args.target}={int(low)}")
                print(f"  {args.candidate}=1 -> {args.target}={int(high)}")
                print(f"  witness: {readable}")
                return 0

        print(
            f"NO INFLUENCE across all {tested} assignments: toggling "
            f"{args.candidate} cannot change {args.target}"
        )
        return 0
    except (OSError, ValueError, KeyError, EvaluationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
