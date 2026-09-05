#!/usr/bin/env python3

import unittest
from pathlib import Path

from tools.netlist_ir import Design
from tools.helpers.display import bit_trace_html, color_grid_html, grid_html
from tools.play import Play, as_bits, bits_at, i_toggle_hits


ROOT = Path(__file__).resolve().parents[1]


class BitHelpersTests(unittest.TestCase):
    def test_as_bits_accepts_string_and_sequence(self) -> None:
        self.assertEqual(as_bits("101"), [True, False, True])
        self.assertEqual(as_bits([1, 0, True]), [True, False, True])

    def test_bits_at_places_ones(self) -> None:
        bits = bits_at(0, 2, length=4)
        self.assertEqual(bits, "1010")

    def test_grid_html_requires_121_bits(self) -> None:
        with self.assertRaises(ValueError):
            grid_html("1")
        html = grid_html(bits_at(0))
        self.assertIn("grid-template-columns:repeat(11,", html)
        self.assertEqual(html.count("<div style="), 122)  # 121 cells + wrapper

    def test_bit_trace_html_labels_times_and_separates_windows(self) -> None:
        trace = [[0, 1], [1, 0], [1, 1]]
        html = bit_trace_html(trace, windows=[[0, 1], [2]], row_labels=["a", "b"])
        self.assertIn(">0</div>", html)
        self.assertIn(">1</div>", html)
        self.assertIn(">2</div>", html)
        self.assertIn(">a</div>", html)
        self.assertIn("width:16px;flex:0 0 16px", html)
        self.assertIn("overflow-x:auto", html)
        self.assertIn("background:#c8c8c8", html)
        with self.assertRaises(IndexError):
            bit_trace_html(trace, windows=[[3]])

    def test_bit_trace_html_draws_red_row_rules(self) -> None:
        trace = [[0] * 9]
        html = bit_trace_html(trace, windows=[[0]], row_groups=[4, 4, 1])
        self.assertEqual(html.count("background:#e02424"), 2)
        with self.assertRaises(ValueError):
            bit_trace_html(trace, windows=[[0]], row_groups=[4, 4])

    def test_color_grid_html_requires_121_labels(self) -> None:
        with self.assertRaises(ValueError):
            color_grid_html([0])
        html = color_grid_html([i % 11 for i in range(121)], title="regions")
        self.assertIn("regions", html)
        self.assertIn("#4e79a7", html)
        self.assertEqual(html.count("<div style="), 124)  # title + 2 wrappers + 121


class ToyPlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.design = Design.load(ROOT / "tests" / "fixtures" / "toy_nets.json")
        cls.sim = Play(
            cls.design,
            data="din",
            enable="en",
            reset="rst_n",
            floating={},
            success="success",
            output_width=0,
        )

    def test_reset_clears_toy_flops(self) -> None:
        state = self.sim.reset_state()
        self.assertEqual(self.sim.q(state, "FF0_dfrtp"), 0)
        self.assertEqual(self.sim.q(state, "FF1_dfrtp"), 0)

    def test_scan_shifts_serial_ones(self) -> None:
        state = self.sim.scan("10", clocks=2)
        self.assertEqual(self.sim.q(state, "FF0_dfrtp"), 0)
        self.assertEqual(self.sim.q(state, "FF1_dfrtp"), 1)


if __name__ == "__main__":
    unittest.main()
