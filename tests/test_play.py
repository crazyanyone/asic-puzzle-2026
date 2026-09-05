#!/usr/bin/env python3

import unittest
from pathlib import Path

from tools.netlist_ir import Design
from tools.helpers.display import (
    bit_strip_html,
    bit_trace_html,
    color_grid_html,
    grid_html,
    row_wrap_table_html,
    write_grid_dot,
)
from tools.helpers.vcd import inputs_at_rising_clock_edge
from tools.play import Play, as_bits, bits_at, i_toggle_hits


ROOT = Path(__file__).resolve().parents[1]


class VcdHelpersTests(unittest.TestCase):
    def test_inputs_at_rising_clock_edge_reads_example_vcd(self) -> None:
        samples = inputs_at_rising_clock_edge(ROOT / "example_inputs.vcd")
        self.assertGreater(len(samples), 0)
        self.assertIn("clk", samples[0])
        self.assertIn("I", samples[0])
        self.assertTrue(all(sample["clk"] == 1 for sample in samples))

        attempts, current = [], []
        for sample in samples:
            if sample["enable"]:
                current.append(bool(sample["I"]))
            elif current:
                attempts.append(current)
                current = []
        if current:
            attempts.append(current)
        self.assertEqual([len(bits) for bits in attempts], [121, 121])

    def test_inputs_at_rising_clock_edge_requires_clock(self) -> None:
        with self.assertRaises(ValueError):
            inputs_at_rising_clock_edge(
                ROOT / "example_inputs.vcd", clock="nope"
            )


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

    def test_row_wrap_table_html_shows_strip_and_bit_states(self) -> None:
        html = row_wrap_table_html([("10100000000", "10", "00")])
        self.assertIn("grid-template-columns:repeat(11,", html)
        self.assertIn(">2</span>", html)
        self.assertIn(">10</td>", html)
        self.assertIn(">00</td>", html)
        strip = bit_strip_html("110", n=3, show_count=False)
        self.assertNotIn("</span>", strip)

    def test_write_grid_dot_marks_stars_and_pins_cells(self) -> None:
        import tempfile

        regions = [[c % 11 for c in range(11)] for _ in range(11)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.dot"
            write_grid_dot(path, regions, stars={0, 12})
            text = path.read_text()
        self.assertIn('pos="0,10!"', text)
        self.assertIn('label="*"', text)
        self.assertIn("n0 -- n1", text)
        with self.assertRaises(ValueError):
            write_grid_dot(path, [[0]])


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
