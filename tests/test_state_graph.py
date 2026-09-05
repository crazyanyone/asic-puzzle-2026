#!/usr/bin/env python3

import unittest
from collections import Counter
from pathlib import Path

from tools.netlist_ir import Design
from tools.state_graph import (
    classify_two_bit_sccs,
    state_dependency_graph,
    strongly_connected_components,
)


ROOT = Path(__file__).resolve().parents[1]


class StateGraphTests(unittest.TestCase):
    def test_toy_shift_register_is_a_chain_of_singleton_sccs(self) -> None:
        design = Design.load(ROOT / "tests" / "fixtures" / "toy_nets.json")
        deps = state_dependency_graph(design)
        sccs = strongly_connected_components(deps)

        self.assertEqual(sorted(map(len, sccs)), [1, 1])
        self.assertIn("FF0_dfrtp", deps["FF1_dfrtp"])

    def test_puzzle_scc_histogram_and_two_bit_split(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "puzzle.json")
        shift_ffs = {
            stage.flip_flop
            for stage in design.strict_shift_registers().shift_registers[0].stages
        }
        deps = state_dependency_graph(design)
        sccs = strongly_connected_components(deps)
        self.assertEqual(
            dict(sorted(Counter(map(len, sccs)).items())),
            {1: 25, 2: 23, 4: 1, 8: 1, 9: 1},
        )

        thin, fat, reused, loners = classify_two_bit_sccs(
            design, sccs, hide=shift_ffs
        )
        self.assertEqual(len(thin), 11)
        self.assertEqual(len(fat), 11)
        self.assertEqual(len(reused), 1)
        self.assertEqual(len(loners), 13)
        self.assertIn("U410_dfrtp_2", loners)
        self.assertIn("U26_dfrtp_2", loners)
        self.assertIn("U27_dfrtp_2", loners)


if __name__ == "__main__":
    unittest.main()
