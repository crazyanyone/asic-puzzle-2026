#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

from tools.netlist_ir import Design


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class StrictShiftRegisterTests(unittest.TestCase):
    def test_toy_is_one_strict_two_stage_shift_register(self) -> None:
        design = Design.load(FIXTURES / "toy_nets.json")

        analysis = design.strict_shift_registers()

        self.assertEqual(len(analysis.shift_registers), 1)
        shift_register = analysis.shift_registers[0]
        self.assertEqual(shift_register.name, "shift_din")
        self.assertEqual(shift_register.width, 2)
        self.assertEqual(
            [stage.flip_flop for stage in shift_register.stages],
            ["FF0_dfrtp", "FF1_dfrtp"],
        )
        self.assertEqual(shift_register.serial_input_net, "din")
        self.assertEqual(shift_register.enable_net, "en")
        self.assertEqual(shift_register.clock_net, "clk")
        self.assertEqual(shift_register.reset_net, "rst_n")
        self.assertEqual(
            shift_register.member_instances,
            frozenset({"FF0_dfrtp", "M0_mux2", "FF1_dfrtp", "M1_mux2"}),
        )

    def test_puzzle_has_one_twelve_stage_register_behind_clock_buffers(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "puzzle.json")

        analysis = design.strict_shift_registers()

        self.assertEqual(len(analysis.shift_registers), 1)
        shift_register = analysis.shift_registers[0]
        self.assertEqual(shift_register.name, "shift_I")
        self.assertEqual(shift_register.width, 12)
        self.assertEqual(shift_register.clock_net, "clk")
        self.assertEqual(
            set(shift_register.clock_leaf_nets),
            {"n0121", "n0177", "n0327", "n0338"},
        )

    def test_stray_pin_on_member_mux_rejects_whole_chain(self) -> None:
        raw = json.loads((FIXTURES / "toy_nets.json").read_text())
        raw["('toy', 1)"].append("M0_mux2.EXTRA")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stray.json"
            path.write_text(json.dumps(raw))
            design = Design.load(path)

        analysis = design.strict_shift_registers()

        self.assertEqual(analysis.shift_registers, [])
        reasons = [
            reason
            for rejection in analysis.rejections
            for reason in rejection.reasons
        ]
        self.assertTrue(
            any("mux signal pins differ from model" in reason for reason in reasons),
            reasons,
        )

    def test_downstream_mux_consumer_is_exposed_as_boundary_load(self) -> None:
        raw = json.loads((FIXTURES / "toy_nets.json").read_text())
        raw["('toy', 1)"].append("DOWNSTREAM_mux2.A0")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "downstream-mux.json"
            path.write_text(json.dumps(raw))
            design = Design.load(path)

        analysis = design.strict_shift_registers()

        self.assertEqual(len(analysis.shift_registers), 1)
        shift_register = analysis.shift_registers[0]
        self.assertIn(
            "DOWNSTREAM_mux2.A0",
            shift_register.external_q_loads["('toy', 1)"],
        )

    def test_nonexclusive_d_net_rejects_whole_chain(self) -> None:
        raw = json.loads((FIXTURES / "toy_nets.json").read_text())
        raw["('toy', 0)"].append("TAP_and2.A")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tapped-d.json"
            path.write_text(json.dumps(raw))
            design = Design.load(path)

        analysis = design.strict_shift_registers()

        self.assertEqual(analysis.shift_registers, [])
        reasons = [
            reason
            for rejection in analysis.rejections
            for reason in rejection.reasons
        ]
        self.assertTrue(
            any("D net is not point-to-point" in reason for reason in reasons),
            reasons,
        )

    def test_mixed_enable_controls_reject_whole_chain(self) -> None:
        raw = json.loads((FIXTURES / "toy_nets.json").read_text())
        raw["en"].remove("M1_mux2.S")
        raw["en2"] = ["M1_mux2.S"]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed-enable.json"
            path.write_text(json.dumps(raw))
            design = Design.load(path)

        analysis = design.strict_shift_registers()

        self.assertEqual(analysis.shift_registers, [])
        reasons = [
            reason
            for rejection in analysis.rejections
            for reason in rejection.reasons
        ]
        self.assertIn("stages do not share one enable net", reasons)

    def test_branched_shift_path_rejects_whole_group(self) -> None:
        raw = json.loads((FIXTURES / "toy_nets.json").read_text())
        raw["en"].append("M2_mux2.S")
        raw["clk"].append("FF2_dfrtp.CLK")
        raw["rst_n"].append("FF2_dfrtp.RESET_B")
        raw["('toy', 1)"].append("M2_mux2.A1")
        raw["('toy', 5)"] = ["M2_mux2.X", "FF2_dfrtp.D"]
        raw["('toy', 6)"] = ["FF2_dfrtp.Q", "M2_mux2.A0"]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "branched.json"
            path.write_text(json.dumps(raw))
            design = Design.load(path)

        analysis = design.strict_shift_registers()

        self.assertEqual(analysis.shift_registers, [])
        reasons = [
            reason
            for rejection in analysis.rejections
            for reason in rejection.reasons
        ]
        self.assertTrue(any("chain branches" in reason for reason in reasons), reasons)


if __name__ == "__main__":
    unittest.main()
