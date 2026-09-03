#!/usr/bin/env python3

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tools.analyze_netlist import write_dot
from tools.netlist_ir import Design


ROOT = Path(__file__).resolve().parents[1]


class AbstractVisualizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.design = Design.load(ROOT / "artifacts" / "netlists" / "warmup.json")

    def render_dot(
        self,
        cells: set[str],
        nets: set[str],
        title: str,
    ) -> str:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.dot"
            with contextlib.redirect_stdout(io.StringIO()):
                write_dot(self.design, cells, nets, str(path), title)
            return path.read_text()

    def assert_shift_registers_are_collapsed(self, dot: str) -> None:
        self.assertIn('"block:shift_A"', dot)
        self.assertIn('"block:shift_B"', dot)
        for shift_register in self.design.strict_shift_registers().shift_registers:
            for member in shift_register.member_instances:
                self.assertNotIn(f'"cell:{member}"', dot)

    def test_success_cone_collapses_shift_register_cells(self) -> None:
        cone = self.design.backward_cone("S")

        dot = self.render_dot(cone.cells, cone.nets, "Success cone")

        self.assert_shift_registers_are_collapsed(dot)

    def test_register_visualization_collapses_shift_register_cells(self) -> None:
        cells: set[str] = set()
        nets: set[str] = set()
        for shift_register in self.design.strict_shift_registers().shift_registers:
            cells.update(shift_register.member_instances)
            for member in shift_register.member_instances:
                nets.update(
                    terminal.net
                    for terminal in self.design.signal_terminals(
                        self.design.instances[member]
                    )
                )

        dot = self.render_dot(cells, nets, "Registers")

        self.assert_shift_registers_are_collapsed(dot)


if __name__ == "__main__":
    unittest.main()
