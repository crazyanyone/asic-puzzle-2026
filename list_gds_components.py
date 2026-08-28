#!/usr/bin/env python3
"""List placed components (standard cells) in a GDS file.

Usage:
    python3 list_gds_components.py warmup/04_final.gds
    python3 list_gds_components.py puzzle.gds
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

import gdstk

# Sky130 pin-label layer/datatype. Signal pins live on 67/5.
PIN_LAYER = 67
PIN_DATATYPE = 5

FILLER_PREFIXES = (
    "sky130_fd_sc_hd__decap",
    "sky130_fd_sc_hd__tap",
    "sky130_fd_sc_hd__fill",
    "sky130_fd_sc_hd__diode",
)


def classify(name: str) -> str:
    if name.startswith("VIA_") or name.startswith("via"):
        return "via"
    if any(name.startswith(p) for p in FILLER_PREFIXES):
        return "filler"
    if name.startswith("sky130_fd_sc_hd__"):
        return "logic"
    return "other"


def unique_pin_labels(ref: gdstk.Reference) -> dict[str, list[tuple[float, float]]]:
    """Pin name -> chip-coordinate points (transform already applied)."""
    pins: dict[str, list[tuple[float, float]]] = {}
    for lab in ref.get_labels():
        if lab.layer != PIN_LAYER or lab.texttype != PIN_DATATYPE:
            continue
        pins.setdefault(lab.text, []).append((float(lab.origin[0]), float(lab.origin[1])))
    return pins


def iter_components(cell: gdstk.Cell):
    """Yield every direct instance placed in `cell`."""
    for i, ref in enumerate(cell.references):
        yield {
            "id": i,
            "cell": ref.cell.name,
            "kind": classify(ref.cell.name),
            "origin_um": (float(ref.origin[0]), float(ref.origin[1])),
            "rotation_rad": float(ref.rotation),
            "x_reflection": bool(ref.x_reflection),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("gds", help="Path to a .gds file")
    ap.add_argument(
        "--json",
        action="store_true",
        help="Dump logic cells + pin coordinates as JSON",
    )
    args = ap.parse_args()

    lib = gdstk.read_gds(args.gds)
    tops = lib.top_level()
    if not tops:
        print("No top-level cell found", file=sys.stderr)
        return 1
    top = tops[0]
    print(f"library cells: {len(lib.cells)}")
    print(f"top cell: {top.name}")
    print(f"direct instances: {len(top.references)}")
    print(f"top-level labels: {[lab.text for lab in top.labels]}")
    print()

    counts = Counter(classify(r.cell.name) for r in top.references)
    print("by kind:", dict(counts))
    print()

    type_counts = Counter(r.cell.name for r in top.references)
    print("instances by cell type:")
    for name, n in type_counts.most_common():
        print(f"  {n:5}  {name}  [{classify(name)}]")

    logic = [c for c in iter_components(top) if c["kind"] == "logic"]
    print(f"\n{len(logic)} logic cells (first 8):")
    refs = list(top.references)
    for c in logic[:8]:
        ref = refs[c["id"]]
        pins = sorted(unique_pin_labels(ref))
        print(
            f"  U{c['id']:<4} {c['cell']:<32} "
            f"@ ({c['origin_um'][0]:7.3f}, {c['origin_um'][1]:7.3f}) "
            f"refl={c['x_reflection']} pins={pins}"
        )

    if args.json:
        out = []
        for c in logic:
            ref = refs[c["id"]]
            out.append({**c, "pins": unique_pin_labels(ref)})
        json.dump(out, sys.stdout, indent=2)
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
