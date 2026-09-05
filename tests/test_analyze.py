#!/usr/bin/env python3

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tools.analyze_netlist import (
    print_instance,
    print_net,
    print_shift_registers,
    write_dot,
    write_gate_inputs_dot,
    write_shift_register_dot,
)
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


class ShiftRegisterReportTests(unittest.TestCase):
    def test_print_is_compact(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "warmup.json")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_shift_registers(design, show_rejected=False, dot_path=None)
        text = buffer.getvalue()
        self.assertIn("Number of shift registers: 2", text)
        self.assertIn("8 mux, 8 flip-flops", text)
        self.assertNotIn("Rejected candidate", text)
        self.assertNotIn("strict evidence", text)
        self.assertNotIn("clock leaves", text)

    def test_dot_fans_out_every_q_bit(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "puzzle.json")
        shift_registers = design.strict_shift_registers().shift_registers
        self.assertEqual(len(shift_registers), 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shift.dot"
            with contextlib.redirect_stdout(io.StringIO()):
                write_shift_register_dot(design, shift_registers, str(path))
            dot = path.read_text()
        self.assertNotIn("parallel Q", dot)
        for index in (0, 9, 10, 11):
            self.assertIn(f'"q:shift_I:{index}"', dot)
        for index in range(1, 9):
            self.assertNotIn(f'"q:shift_I:{index}"', dot)
        self.assertIn("U360_a22o_2", dot)
        self.assertIn("U374_a221o_2", dot)

    def test_gate_inputs_dot_shows_every_pin(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "puzzle.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.dot"
            with contextlib.redirect_stdout(io.StringIO()):
                write_gate_inputs_dot(
                    design, ["U360_a22o_2", "U374_a221o_2"], str(path)
                )
            dot = path.read_text()
        for pin in ("A1", "A2", "B1", "B2", "C1"):
            self.assertIn(f"[label=\"{pin}\"]", dot)
        self.assertIn("U416_or4_2", dot)
        self.assertIn("U415_or4bb_2", dot)
        self.assertIn("U422_conb_1", dot)
        self.assertIn("Q[0]", dot)
        self.assertIn("Q[11]", dot)


class NetReportTests(unittest.TestCase):
    def test_drivers_flag_omits_loads(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "puzzle.json")
        full = io.StringIO()
        with contextlib.redirect_stdout(full):
            print_net(design, "n0005", depth=1, dot_path=None)
        drivers = io.StringIO()
        with contextlib.redirect_stdout(drivers):
            print_net(design, "n0005", depth=1, dot_path=None, driver_only=True)
        full_text = full.getvalue()
        driver_text = drivers.getvalue()
        self.assertIn("Drivers:", full_text)
        self.assertIn("Loads:", full_text)
        self.assertIn("Grouped loads:", full_text)
        self.assertIn("Driver:", driver_text)
        self.assertNotIn("Drivers:", driver_text)
        self.assertIn("U351_and2b_2.X", driver_text)
        self.assertNotIn("Aliases:", driver_text)
        self.assertNotIn("Port:", driver_text)
        self.assertNotIn("Direction:", driver_text)
        self.assertNotIn("Loads:", driver_text)
        self.assertNotIn("Grouped loads:", driver_text)

    def test_inputs_flag_omits_function_and_outputs(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "puzzle.json")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_instance(
                design, "U351", depth=1, dot_path=None, inputs_only=True
            )
        text = buffer.getvalue()
        self.assertIn("Instance:   U351_and2b_2", text)
        self.assertIn("<-", text)
        self.assertNotIn("Function:", text)
        self.assertNotIn(" -> ", text)


if __name__ == "__main__":
    unittest.main()
