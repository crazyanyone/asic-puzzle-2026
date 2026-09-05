#!/usr/bin/env python3

import unittest
from collections import Counter
from pathlib import Path

from tools.netlist_ir import Design
from tools.play import Play, i_toggle_hits
from tools.state_graph import (
    classify_two_bit_sccs,
    print_two_bit_report,
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

        thin, fat, reused, singletons = classify_two_bit_sccs(
            design, sccs, hide=shift_ffs
        )
        self.assertEqual(len(thin), 11)
        self.assertEqual(len(fat), 11)
        self.assertEqual(len(reused), 1)
        self.assertEqual(len(singletons), 13)
        self.assertIn("U410_dfrtp_2", singletons)
        self.assertIn("U26_dfrtp_2", singletons)
        self.assertIn("U27_dfrtp_2", singletons)

        from io import StringIO
        import contextlib

        buffer = StringIO()
        with contextlib.redirect_stdout(buffer):
            print_two_bit_report(thin, fat, reused, design)
        text = buffer.getvalue()
        self.assertIn("tiny", text)
        self.assertIn("fat", text)
        self.assertIn("  6", text)
        self.assertIn("153", text)
        self.assertIn("share 148", text)

    def test_i_toggle_hits_are_columns_and_a_partition(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "puzzle.json")
        shift_ffs = {
            stage.flip_flop
            for stage in design.strict_shift_registers().shift_registers[0].stages
        }
        deps = state_dependency_graph(design)
        sccs = strongly_connected_components(deps)
        thin, fat, reused, _singletons = classify_two_bit_sccs(
            design, sccs, hide=shift_ffs
        )
        sim = Play(design)
        thin_pairs = [info[0] for info in thin]
        fat_pairs = [info[0] for info in fat]
        row_pair = reused[0][0]
        hits = i_toggle_hits(sim, thin_pairs + [row_pair] + fat_pairs)

        for positions in hits[:11]:
            self.assertEqual(len(positions), 11)
            self.assertEqual(len({cell % 11 for cell in positions}), 1)
        self.assertEqual(sorted(set(range(121)) - hits[11]), list(range(10, 121, 11)))
        covered: set[int] = set()
        for positions in hits[12:]:
            self.assertTrue(positions)
            self.assertFalse(covered & positions)
            covered |= positions
        self.assertEqual(covered, set(range(121)))


if __name__ == "__main__":
    unittest.main()
