#!/usr/bin/env python3
"""Reconstruct a gate-level netlist from a placed-and-routed Sky130 GDS.

The whole idea (pure geometric extraction, i.e. a mini "LVS extract"):

  1. Keep only the logic standard-cell instances (drop vias/fillers).
  2. Read every pin as a (name, chip-coordinate, layer) triple.
  3. Recover NETS from geometry:
       - merge touching shapes WITHIN each conductor layer   -> boolean "or"
       - stitch conductors ACROSS layers where a via overlaps -> overlap + union-find
       - a pin belongs to whichever merged conductor contains its point
     Two pins on the same net = electrically connected.

Usage:
    python3 extract_netlist.py warmup/04_final.gds
    python3 extract_netlist.py warmup/04_final.gds --json nets.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

import gdstk

# --- Sky130 layer map (layer, datatype) ------------------------------------
# Conductor sheets, bottom -> top. datatype 20 == "drawing" (the real metal).
CONDUCTORS = {
    "li1":  (67, 20),
    "met1": (68, 20),
    "met2": (69, 20),
    "met3": (70, 20),
    "met4": (71, 20),
    "met5": (72, 20),
}

# Via "cut" layers that connect a lower sheet to the next one up.
# (lower_conductor, upper_conductor, (cut_layer, cut_datatype))
VIA_STACK = [
    ("li1",  "met1", (67, 44)),  # mcon
    ("met1", "met2", (68, 44)),  # via
    ("met2", "met3", (69, 44)),  # via2
    ("met3", "met4", (70, 44)),  # via3
    ("met4", "met5", (71, 44)),  # via4
]

# Cell signal-pin labels live on li1 and met1 with texttype 5.
PIN_LABELS = {(67, 5): "li1", (68, 5): "met1"}

# Top-level PORT labels (A, B, S, clk, VPWR, ...) live higher up the stack.
PORT_LABELS = {
    (67, 5): "li1", (68, 5): "met1", (69, 5): "met2",
    (70, 5): "met3", (71, 5): "met4", (72, 5): "met5",
}

FILLER_PREFIXES = (
    "sky130_fd_sc_hd__decap",
    "sky130_fd_sc_hd__tap",
    "sky130_fd_sc_hd__fill",
    "sky130_fd_sc_hd__diode",
)

# Pins we treat as power/ground rather than signal nets.
POWER_NAMES = {"VPWR", "VGND", "VPB", "VNB"}


def is_logic(name: str) -> bool:
    return name.startswith("sky130_fd_sc_hd__") and not any(
        name.startswith(p) for p in FILLER_PREFIXES
    )


# --- union-find -------------------------------------------------------------
class DSU:
    def __init__(self) -> None:
        self.parent: dict[object, object] = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


# --- geometry helpers -------------------------------------------------------
def bbox_center(poly: gdstk.Polygon) -> tuple[float, float]:
    (x0, y0), (x1, y1) = poly.bounding_box()
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def build_regions(top: gdstk.Cell) -> dict[str, list[gdstk.Polygon]]:
    """For each conductor layer, flatten the whole design and OR-merge the
    metal into disjoint 'regions' (each returned polygon == one connected net
    fragment on that layer)."""
    regions: dict[str, list[gdstk.Polygon]] = {}
    for name, (layer, dt) in CONDUCTORS.items():
        raw = top.get_polygons(depth=None, layer=layer, datatype=dt)
        merged = gdstk.boolean(raw, [], "or") if raw else []
        regions[name] = merged
        print(f"  {name:5} raw={len(raw):5}  merged regions={len(merged)}",
              file=sys.stderr)
    return regions


def region_index_containing(regions: list[gdstk.Polygon],
                            point: tuple[float, float]) -> int | None:
    """Which merged region (index) contains `point`? bbox prefilter + contain."""
    px, py = point
    for i, poly in enumerate(regions):
        bb = poly.bounding_box()
        if bb is None:
            continue
        (x0, y0), (x1, y1) = bb
        if x0 <= px <= x1 and y0 <= py <= y1 and poly.contain(point):
            return i
    return None


def extract(gds_path: str):
    lib = gdstk.read_gds(gds_path)
    top = lib.top_level()[0]

    print(f"top cell: {top.name}", file=sys.stderr)
    print("merging conductor layers...", file=sys.stderr)
    regions = build_regions(top)

    # Every merged region is a node in the union-find, keyed by (layer, index).
    dsu = DSU()
    for layer, polys in regions.items():
        for i in range(len(polys)):
            dsu.find((layer, i))

    # Stitch layers through vias: a via cut whose center lands inside a region
    # on both adjacent layers joins those two regions into one net.
    print("stitching layers through vias...", file=sys.stderr)
    for low, high, (vl, vdt) in VIA_STACK:
        cuts = top.get_polygons(depth=None, layer=vl, datatype=vdt)
        joined = 0
        for cut in cuts:
            c = bbox_center(cut)
            li = region_index_containing(regions[low], c)
            hi = region_index_containing(regions[high], c)
            if li is not None and hi is not None:
                dsu.union((low, li), (high, hi))
                joined += 1
        print(f"  {low}->{high}: {len(cuts)} cuts, {joined} stitched",
              file=sys.stderr)

    # Assign pins (from logic instances) to whichever region contains them.
    print("assigning pins to nets...", file=sys.stderr)
    net_members: dict[object, list[str]] = defaultdict(list)
    unresolved = 0
    inst_id = 0
    for ref in top.references:
        if not is_logic(ref.cell.name):
            continue
        gate = f"U{inst_id}_{ref.cell.name.split('__')[-1]}"
        inst_id += 1
        for lab in ref.get_labels():
            layer_name = PIN_LABELS.get((lab.layer, lab.texttype))
            if layer_name is None:
                continue
            point = (float(lab.origin[0]), float(lab.origin[1]))
            idx = region_index_containing(regions[layer_name], point)
            terminal = f"{gate}.{lab.text}"
            if idx is None:
                unresolved += 1
                net_members[("UNRESOLVED", terminal)].append(terminal)
                continue
            net_members[dsu.find((layer_name, idx))].append(terminal)

    # Name nets using top-level port labels where possible.
    print("naming nets from top-level ports...", file=sys.stderr)
    net_names: dict[object, set[str]] = defaultdict(set)
    for lab in top.labels:
        layer_name = PORT_LABELS.get((lab.layer, lab.texttype))
        if layer_name is None:
            continue
        point = (float(lab.origin[0]), float(lab.origin[1]))
        idx = region_index_containing(regions[layer_name], point)
        if idx is not None:
            net_names[dsu.find((layer_name, idx))].add(lab.text)

    print(f"  unresolved pins: {unresolved}", file=sys.stderr)
    return net_members, net_names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gds", help="Path to a .gds file")
    ap.add_argument("--json", metavar="OUT", help="Write nets to a JSON file")
    args = ap.parse_args()

    net_members, net_names = extract(args.gds)

    # Order: power nets last, biggest signal nets first.
    def net_label(root) -> str:
        names = net_names.get(root)
        if names:
            return "|".join(sorted(names))
        return str(root)

    rows = []
    for root, members in net_members.items():
        label = net_label(root)
        is_power = any(n in POWER_NAMES for n in net_names.get(root, ()))
        rows.append((is_power, -len(members), label, sorted(set(members))))
    rows.sort()

    print(f"\n=== {len(rows)} nets extracted ===\n")
    for is_power, _, label, members in rows:
        tag = " [power]" if is_power else ""
        print(f"net {label}{tag}  ({len(members)} terminals)")
        for m in members:
            print(f"    {m}")
        print()

    if args.json:
        out = {
            net_label(root): sorted(set(members))
            for root, members in net_members.items()
        }
        with open(args.json, "w") as fh:
            json.dump(out, fh, indent=2)
        print(f"wrote {args.json}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
