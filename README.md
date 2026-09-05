# ASIC reverse-engineering puzzle

This repository works from the physical layout upward:

```text
GDS polygons -> connected conductor regions -> nets and terminals
             -> typed gate graph -> conservative circuit abstractions
```

The objective is not merely to guess the circuit. Every abstraction should be
traceable back to geometry and carry enough checks to make false recognition
unlikely. See [docs/workflow.md](docs/workflow.md) for the reasoning behind each
stage.

## Ground-truth discipline

For the warm-up, use only `warmup/04_final.gds` as input. The other files in
`warmup/` are provided ground truth and should stay unopened until an
independent behavioral result is ready for a final cross-check. The analysis
commands below do not read them.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

`gdstk` is the only third-party dependency. Graphviz is optional and is used
only to render `.dot` files.

## Reproduce the warm-up pipeline

```bash
# 1. Inventory cells and labels without extracting connectivity.
.venv/bin/python -m tools.inspect_gds warmup/04_final.gds

# 2. Reconstruct nets from conductor and via geometry.
.venv/bin/python -m tools.extract_netlist \
  warmup/04_final.gds --json artifacts/netlists/warmup.json

# 3. Validate and query the typed graph.
.venv/bin/python -m tools.analyze_netlist \
  artifacts/netlists/warmup.json summary
.venv/bin/python -m tools.analyze_netlist \
  artifacts/netlists/warmup.json shift-registers --show-rejected
.venv/bin/python -m tools.analyze_netlist \
  artifacts/netlists/warmup.json cone S --dot generated/warmup-success.dot

# 4. Run unit and end-to-end extraction regression tests.
.venv/bin/python -m unittest discover -v
```

To render a graph:

```bash
dot -Tsvg generated/warmup-success.dot -o generated/warmup-success.svg
```

`generated/` is intentionally ignored. Checked-in extracted netlists are
reproducible snapshots, not additional sources of truth.

## Repository map

- `tools/helpers/`: bit strings and HTML bit-grids.
- `tools/play.py`, `tools/circuit_eval.py`: simulators (reset, tick, scan).
- `tools/extract_netlist.py`, `tools/analyze_netlist.py`, `tools/inspect_gds.py`,
  `tools/simulate_netlist.py`, `tools/check_influence.py`: command-line runners.
- `tools/netlist_ir.py`: cell models and the queryable graph representation.
- `tools/logic.py`: safe parser/evaluator for the Liberty Boolean subset.
- `tools/state_graph.py`: flop dependency graphs and SCCs.
- `tools/import_sky130_models.py`: refresh/check the official cell snapshot.
- `tests/fixtures/toy_nets.json`: a graph small enough to follow by hand.
- `tests/`: focused motif tests plus a real warm-up re-extraction test.
- `artifacts/netlists/`: reproducible extracted connectivity snapshots.
- `examples/warmup_exhaustive.py`: the complete 65,536-state warm-up search.
- `docs/`: first-principles explanation and current limitations.
- `warmup/`: competition-provided warm-up files; only `04_final.gds` is an input.

Detailed worked examples and investigations:

- [Toy glass-box walkthrough](docs/toy-walkthrough.md)
- [12-bit register and `n0550`](docs/puzzle-investigations.md)

The 64 cell types used by the extracted designs are loaded from the checked-in
official Liberty snapshot `tools/sky130_hd_cells.json`. To refresh or validate
it against a Sky130-HD checkout:

```bash
.venv/bin/python -m tools.import_sky130_models /path/to/sky130_fd_sc_hd --check
```
