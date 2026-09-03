#!/usr/bin/env python3

import itertools
import unittest

from tools.logic import evaluate_expression, parse_expression
from tools.netlist_ir import CELL_MODELS, CELL_MODEL_PROVENANCE


class LibertyExpressionTests(unittest.TestCase):
    def test_every_combinational_output_function_parses_and_evaluates(self) -> None:
        checked = 0
        for model in CELL_MODELS.values():
            if model.sequential:
                continue
            for _, expression in model.output_functions:
                parsed = parse_expression(expression)
                symbols = sorted(parsed.symbols)
                for bits in itertools.product((False, True), repeat=len(symbols)):
                    evaluate_expression(expression, dict(zip(symbols, bits)))
                checked += 1

        self.assertGreater(checked, 50)

    def test_mux_function_comes_from_liberty_and_selects_expected_input(self) -> None:
        expression = CELL_MODELS["mux2"].output_expression("X")

        self.assertFalse(
            evaluate_expression(
                expression, {"A0": False, "A1": True, "S": False}
            )
        )
        self.assertTrue(
            evaluate_expression(
                expression, {"A0": False, "A1": True, "S": True}
            )
        )

    def test_snapshot_records_official_revision(self) -> None:
        self.assertEqual(CELL_MODEL_PROVENANCE["schema_version"], 1)
        self.assertRegex(CELL_MODEL_PROVENANCE["source_revision"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
