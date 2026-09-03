#!/usr/bin/env python3
"""Import the cell subset used by the extracted designs from Sky130 Liberty.

This is a development-time provenance tool. Runtime analysis uses the checked-in
``sky130_hd_cells.json`` snapshot and does not require a local PDK checkout.

Example:
    python3 -m tools.import_sky130_models \
      /path/to/skywater-pdk-libs-sky130_fd_sc_hd \
      --output tools/sky130_hd_cells.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_NETLISTS = (
    Path("artifacts/netlists/warmup.json"),
    Path("artifacts/netlists/puzzle.json"),
)
CELL_NAME = re.compile(r"_([a-z][a-z0-9_]*)_[0-9]+$")
SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def used_cell_types(netlists: tuple[Path, ...]) -> set[str]:
    result: set[str] = set()
    for path in netlists:
        raw = json.loads(path.read_text())
        records = raw["nets"].values() if raw.get("schema_version") == 1 else (
            {"terminals": terminals} for terminals in raw.values()
        )
        for record in records:
            for terminal in record["terminals"]:
                instance = terminal.rsplit(".", 1)[0]
                match = CELL_NAME.search(instance)
                if match:
                    result.add(match.group(1))
    return result


def liberty_path(root: Path, cell: str) -> Path:
    pattern = f"sky130_fd_sc_hd__{cell}_1__tt_025C_1v80.lib.json"
    matches = list((root / "cells" / cell).glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one Liberty file for {cell}, found {matches}")
    return matches[0]


def condition_pins(expression: str | None) -> list[str]:
    return sorted(set(SYMBOL.findall(expression or "")) - {"IQ", "IQ_N"})


def import_cell(root: Path, cell: str) -> dict[str, object]:
    definition = json.loads((root / "cells" / cell / "definition.json").read_text())
    liberty = json.loads(liberty_path(root, cell).read_text())

    inputs: list[str] = []
    outputs: dict[str, str] = {}
    for key, value in liberty.items():
        if not key.startswith("pin,") or not isinstance(value, dict):
            continue
        pin = key.split(",", 1)[1]
        if value.get("direction") == "input":
            inputs.append(pin)
        elif value.get("direction") == "output":
            function = value.get("function")
            if not isinstance(function, str):
                raise ValueError(f"{cell}.{pin} has no Liberty function")
            outputs[pin] = function

    state_records = [
        value
        for key, value in liberty.items()
        if key.startswith(("ff,", "latch,")) and isinstance(value, dict)
    ]
    if len(state_records) > 1:
        raise ValueError(f"{cell} has multiple state records")
    state = state_records[0] if state_records else {}
    clock_pins = condition_pins(state.get("clocked_on"))
    reset_pins = condition_pins(state.get("clear"))
    set_pins = condition_pins(state.get("preset"))
    controls = set(clock_pins + reset_pins + set_pins)

    return {
        "description": definition["description"],
        "inputs": sorted(set(inputs) - controls),
        "outputs": outputs,
        "clock_pins": clock_pins,
        "reset_pins": reset_pins,
        "set_pins": set_pins,
        "sequential": bool(state_records),
        "clocked_on": state.get("clocked_on"),
        "next_state": state.get("next_state"),
        "clear": state.get("clear"),
        "preset": state.get("preset"),
    }


def git_revision(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdk_root", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("tools/sky130_hd_cells.json")
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if importing the PDK would change the checked-in snapshot",
    )
    args = parser.parse_args()

    cell_types = sorted(used_cell_types(DEFAULT_NETLISTS))
    result = {
        "schema_version": 1,
        "source": "https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd",
        "source_revision": git_revision(args.pdk_root),
        "liberty_corner": "tt_025C_1v80",
        "cells": {
            cell: import_cell(args.pdk_root, cell) for cell in cell_types
        },
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text() != rendered:
            print(f"error: {args.output} is not synchronized with the PDK", file=sys.stderr)
            return 1
        print(f"Validated {len(cell_types)} cell models against {args.pdk_root}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered)
    print(f"Imported {len(cell_types)} cell models into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
