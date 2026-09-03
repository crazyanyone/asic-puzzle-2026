#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

from tools.extract_netlist import DSU, extract
from tools.netlist_ir import Design


ROOT = Path(__file__).resolve().parents[1]


class UnionFindTests(unittest.TestCase):
    def test_union_is_transitive(self) -> None:
        dsu = DSU()
        dsu.union("metal-a", "via")
        dsu.union("via", "metal-b")

        self.assertEqual(dsu.find("metal-a"), dsu.find("metal-b"))


class WarmupExtractionTests(unittest.TestCase):
    def test_gds_reextracts_checked_in_connectivity_without_gaps(self) -> None:
        result = extract(str(ROOT / "warmup" / "04_final.gds"))

        self.assertEqual(result.top_cell, "adder_demo")
        self.assertEqual(result.unresolved_pins, [])
        self.assertEqual(result.unresolved_ports, [])
        self.assertTrue(
            all(total == stitched for total, stitched in result.via_stats.values())
        )

        expected = json.loads(
            (ROOT / "artifacts" / "netlists" / "warmup.json").read_text()
        )
        actual_groups = {
            frozenset(record["terminals"])
            for record in result.to_dict()["nets"].values()
        }
        expected_groups = {
            frozenset(record["terminals"])
            for record in expected["nets"].values()
        }
        self.assertEqual(actual_groups, expected_groups)

    def test_schema_records_ports_explicitly(self) -> None:
        raw = {
            "schema_version": 1,
            "nets": {
                "n0000": {
                    "aliases": [],
                    "terminals": ["U0_inv.Y", "U1_inv.A"],
                },
                "input": {
                    "aliases": ["input"],
                    "terminals": ["U0_inv.A"],
                },
                "output": {
                    "aliases": ["output"],
                    "terminals": ["U1_inv.Y"],
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schema.json"
            path.write_text(json.dumps(raw))
            design = Design.load(path)

        self.assertFalse(design.nets["n0000"].is_port)
        self.assertEqual(design.ports["input"].inferred_direction, "input")
        self.assertEqual(design.ports["output"].inferred_direction, "output")


if __name__ == "__main__":
    unittest.main()
