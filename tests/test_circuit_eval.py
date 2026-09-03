#!/usr/bin/env python3

import unittest
from pathlib import Path

from tools.circuit_eval import CircuitEvaluator, one_clock_transition
from tools.netlist_ir import Design


ROOT = Path(__file__).resolve().parents[1]


class ToyEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.design = Design.load(ROOT / "tests" / "fixtures" / "toy_nets.json")

    def test_combinational_output_from_explicit_state(self) -> None:
        evaluator = CircuitEvaluator(
            self.design,
            {"FF0_dfrtp.Q": False, "FF1_dfrtp.Q": True},
        )
        self.assertTrue(evaluator.value("success"))

    def test_one_edge_shifts_old_q0_into_q1(self) -> None:
        result = one_clock_transition(
            self.design,
            {"FF0_dfrtp": True, "FF1_dfrtp": False},
            {"din": False, "en": True, "rst_n": True},
        )
        self.assertFalse(result.next_state[self.design.resolve_net("FF0_dfrtp.Q").name])
        self.assertTrue(result.next_state[self.design.resolve_net("FF1_dfrtp.Q").name])
        self.assertTrue(result.outputs_after_edge["success"])

    def test_active_low_reset_overrides_data(self) -> None:
        result = one_clock_transition(
            self.design,
            {"FF0_dfrtp": True, "FF1_dfrtp": True},
            {"din": True, "en": True, "rst_n": False},
        )
        self.assertFalse(any(result.next_state.values()))

    def test_transition_can_watch_an_internal_net(self) -> None:
        result = one_clock_transition(
            self.design,
            {"FF0_dfrtp": False, "FF1_dfrtp": False},
            {"din": True, "en": True, "rst_n": True},
            output_names=["M0_mux2.X"],
        )
        self.assertTrue(result.outputs_before_edge["M0_mux2.X"])


class PuzzleTransitionTests(unittest.TestCase):
    def test_all_state_elements_have_an_executable_next_state(self) -> None:
        design = Design.load(ROOT / "artifacts" / "netlists" / "puzzle.json")
        current_state = {
            instance.pins["Q"].net: False
            for instance in design.instances.values()
            if instance.sequential and "Q" in instance.pins
        }
        result = one_clock_transition(
            design,
            current_state,
            {"I": False, "enable": False, "rst_n": False},
            output_names=(),
        )
        self.assertEqual(len(result.next_state), 92)


if __name__ == "__main__":
    unittest.main()
