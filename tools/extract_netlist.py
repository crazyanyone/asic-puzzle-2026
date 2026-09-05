#!/usr/bin/env python3
"""Reconstruct a gate-level netlist from a placed-and-routed Sky130 GDS.

The whole idea (pure geometric extraction, i.e. a mini "LVS extract"):

  1. Keep only the logic standard-cell instances (drop vias/fillers).
  2. Read every pin as a (name, chip-coordinate, layer) triple.
  3. Recover NETS from geometry:
       - merge touching shapes WITHIN each conductor layer   -> boolean "or"
       - stitch conductors ACROSS layers at each via cut       -> union-find
       - a pin belongs to whichever merged conductor contains its point
     Two pins on the same net = electrically connected.

Usage (from the repository root):
    python3 -m tools.extract_netlist warmup/04_final.gds
    python3 -m tools.extract_netlist warmup/04_final.gds --json artifacts/netlists/warmup.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

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
POWER_NAMES = {"VPWR", "VGND", "VPB", "VNB", "VDD", "VSS"}


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


@dataclass
class ExtractionResult:
    """Connectivity plus the evidence needed to audit the extraction."""

    source_gds: str
    top_cell: str
    net_members: dict[object, set[str]]
    net_aliases: dict[object, set[str]]
    via_stats: dict[str, tuple[int, int]]
    unresolved_pins: list[str]
    unresolved_ports: list[str]

    def rows(self) -> list[tuple[str, tuple[str, ...], list[str]]]:
        """Return deterministic (id, aliases, terminals) records.

        Internal ids are deliberately semantic-free. Unlike the old tuple
        repr names, they do not expose polygon ordering as circuit meaning.
        """
        roots = set(self.net_members) | set(self.net_aliases)
        named: list[tuple[tuple[str, ...], list[str]]] = []
        internal: list[list[str]] = []
        for root in roots:
            aliases = tuple(sorted(self.net_aliases.get(root, ())))
            members = sorted(self.net_members.get(root, ()))
            if aliases:
                named.append((aliases, members))
            elif members:
                internal.append(members)

        rows: list[tuple[str, tuple[str, ...], list[str]]] = []
        for aliases, members in sorted(named):
            rows.append(("|".join(aliases), aliases, members))
        for index, members in enumerate(sorted(internal)):
            rows.append((f"n{index:04d}", (), members))
        for index, terminal in enumerate(sorted(self.unresolved_pins)):
            rows.append((f"unresolved_{index:04d}", (), [terminal]))
        return rows

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "source_gds": self.source_gds,
            "top_cell": self.top_cell,
            "nets": {
                net_id: {
                    "aliases": list(aliases),
                    "terminals": terminals,
                }
                for net_id, aliases, terminals in self.rows()
            },
            "diagnostics": {
                "unresolved_pins": sorted(self.unresolved_pins),
                "unresolved_ports": sorted(self.unresolved_ports),
                "via_cuts": {
                    stack: {"total": total, "stitched": stitched}
                    for stack, (total, stitched) in self.via_stats.items()
                },
            },
        }


def extract(gds_path: str, top_name: str | None = None) -> ExtractionResult:
    lib = gdstk.read_gds(gds_path)
    tops = lib.top_level()
    if top_name is not None:
        matches = [cell for cell in tops if cell.name == top_name]
        if len(matches) != 1:
            available = ", ".join(cell.name for cell in tops) or "(none)"
            raise ValueError(
                f"top cell {top_name!r} not found; available top cells: {available}"
            )
        top = matches[0]
    elif len(tops) == 1:
        top = tops[0]
    else:
        available = ", ".join(cell.name for cell in tops) or "(none)"
        raise ValueError(
            "GDS must contain exactly one top-level cell unless --top is used; "
            f"found: {available}"
        )

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
    via_stats: dict[str, tuple[int, int]] = {}
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
        via_stats[f"{low}->{high}"] = (len(cuts), joined)

    # Assign pins (from logic instances) to whichever region contains them.
    print("assigning pins to nets...", file=sys.stderr)
    terminal_roots: dict[str, set[object]] = defaultdict(set)
    unresolved_pins: set[str] = set()
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
                unresolved_pins.add(terminal)
                continue
            terminal_roots[terminal].add(dsu.find((layer_name, idx)))

    multiply_connected = {
        terminal: roots
        for terminal, roots in terminal_roots.items()
        if len(roots) != 1
    }
    if multiply_connected:
        terminals = ", ".join(sorted(multiply_connected))
        raise ValueError(f"pin labels touch multiple disconnected nets: {terminals}")
    net_members: dict[object, set[str]] = defaultdict(set)
    for terminal, roots in terminal_roots.items():
        net_members[next(iter(roots))].add(terminal)

    # Name nets using top-level port labels where possible.
    net_names: dict[object, set[str]] = defaultdict(set)
    alias_roots: dict[str, set[object]] = defaultdict(set)
    unresolved_ports: set[str] = set()
    for lab in top.labels:
        layer_name = PORT_LABELS.get((lab.layer, lab.texttype))
        if layer_name is None:
            continue
        point = (float(lab.origin[0]), float(lab.origin[1]))
        idx = region_index_containing(regions[layer_name], point)
        if idx is None:
            unresolved_ports.add(lab.text)
            continue
        root = dsu.find((layer_name, idx))
        net_names[root].add(lab.text)
        alias_roots[lab.text].add(root)

    duplicate_aliases = {
        alias: roots for alias, roots in alias_roots.items() if len(roots) != 1
    }
    if duplicate_aliases:
        aliases = ", ".join(sorted(duplicate_aliases))
        raise ValueError(f"top-level labels occur on multiple nets: {aliases}")

    if unresolved_pins:
        print(f"  unresolved pins: {len(unresolved_pins)}", file=sys.stderr)
    if unresolved_ports:
        print(f"  unresolved ports: {len(unresolved_ports)}", file=sys.stderr)
    return ExtractionResult(
        source_gds=str(gds_path),
        top_cell=top.name,
        net_members=dict(net_members),
        net_aliases=dict(net_names),
        via_stats=via_stats,
        unresolved_pins=sorted(unresolved_pins),
        unresolved_ports=sorted(unresolved_ports),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gds", help="Path to a .gds file")
    ap.add_argument("--top", help="Top-level cell name (required only if ambiguous)")
    ap.add_argument("--json", metavar="OUT", help="Write nets to a JSON file")
    args = ap.parse_args()

    try:
        result = extract(args.gds, args.top)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    rows = result.rows()
    print(f"\n=== {len(rows)} nets extracted ===")
    if not args.json:
        print()
        for net_id, aliases, members in rows:
            is_power = bool(POWER_NAMES & set(aliases))
            tag = " [power]" if is_power else ""
            print(f"net {net_id}{tag}  ({len(members)} terminals)")
            for m in members:
                print(f"    {m}")
            print()

    if args.json:
        output_path = Path(args.json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w") as fh:
            json.dump(result.to_dict(), fh, indent=2)
            fh.write("\n")
        print(f"wrote {args.json}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
