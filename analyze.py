#!/usr/bin/env python3
"""Query and visualize netlists produced by extract_netlist.py.

Examples:
    python3 analyze.py toynets.json summary
    python3 analyze.py nets.json net rst_n
    python3 analyze.py nets.json instance U12 --depth 2
    python3 analyze.py nets.json instance U12 --depth 2 --dot u12.dot
    python3 analyze.py nets.json cone S --dot success-cone.dot
    python3 analyze.py nets.json registers
    python3 analyze.py nets.json shift-chains --dot shift-chains.dot
    python3 analyze.py nets.json export --out design.json

Render a DOT file with Graphviz:
    dot -Tsvg success-cone.dot -o success-cone.svg
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from netlist_ir import Design, EnabledRegister, Instance, Net, Terminal


def natural_key(value: str) -> tuple[object, ...]:
    import re

    return tuple(
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", value)
    )


def quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def terminal_list(terminals: list[Terminal]) -> str:
    if not terminals:
        return "(none)"
    return ", ".join(terminal.name for terminal in terminals)


def instance_title(instance: Instance) -> str:
    marker = " [sequential]" if instance.sequential else ""
    known = "" if instance.model.known else " [inferred directions]"
    return f"{instance.name} ({instance.cell_type}){marker}{known}"


def write_dot(
    design: Design,
    cell_names: set[str],
    net_names: set[str],
    output_path: str,
    title: str,
) -> None:
    """Write a focused directed bipartite cell/net graph."""
    lines = [
        "digraph netlist {",
        "  rankdir=LR;",
        "  graph [fontname=\"Helvetica\", labelloc=t];",
        "  node [fontname=\"Helvetica\"];",
        "  edge [fontname=\"Helvetica\", fontsize=9];",
        f"  label={quoted(title)};",
    ]

    for cell_name in sorted(cell_names, key=natural_key):
        instance = design.instances[cell_name]
        shape = "doubleoctagon" if instance.sequential else "box"
        label = f"{instance.name}\\n{instance.cell_type}"
        lines.append(
            f"  {quoted('cell:' + cell_name)} "
            f"[shape={shape}, label={quoted(label)}];"
        )

    for net_name in sorted(net_names, key=natural_key):
        net = design.nets[net_name]
        if net.is_power:
            continue
        if net.is_port:
            shape = "diamond"
            label = "|".join(net.aliases)
        else:
            shape = "ellipse"
            label = net.name
        lines.append(
            f"  {quoted('net:' + net_name)} "
            f"[shape={shape}, label={quoted(label)}];"
        )

    for net_name in sorted(net_names, key=natural_key):
        net = design.nets[net_name]
        if net.is_power:
            continue
        for terminal in net.terminals:
            if terminal.instance not in cell_names:
                continue
            cell_id = quoted("cell:" + terminal.instance)
            net_id = quoted("net:" + net_name)
            label = quoted(terminal.pin)
            if terminal.direction == "output":
                lines.append(f"  {cell_id} -> {net_id} [label={label}];")
            elif terminal.direction == "input":
                lines.append(f"  {net_id} -> {cell_id} [label={label}];")
            else:
                lines.append(
                    f"  {net_id} -> {cell_id} "
                    f"[label={label}, style=dashed, dir=none];"
                )

    lines.append("}")
    Path(output_path).write_text("\n".join(lines) + "\n")
    svg_path = Path(output_path).with_suffix(".svg")
    print(f"Wrote {output_path}")
    print(f"Render with: dot -Tsvg {output_path} -o {svg_path}")


def print_summary(design: Design) -> None:
    signal_nets = [net for net in design.nets.values() if not net.is_power]
    sequential = [instance for instance in design.instances.values() if instance.sequential]
    counts = Counter(instance.cell_type for instance in design.instances.values())

    print(f"Source:          {design.source_path}")
    print(f"Instances:       {len(design.instances)}")
    print(f"Nets:            {len(design.nets)} ({len(signal_nets)} non-power)")
    print(f"Terminals:       {len(design.terminals)}")
    print(f"State elements:  {len(sequential)}")
    print()

    print("Ports (direction inferred from cell pin directions):")
    for alias, net in sorted(design.ports.items()):
        print(
            f"  {alias:<16} {net.inferred_direction:<17} "
            f"drivers={len(net.drivers):<2} loads={len(net.loads)}"
        )

    print()
    print("Cell inventory:")
    for cell_type, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count:>5}  {cell_type}")

    issues = design.validation_issues()
    print()
    print(f"Validation issues: {len(issues)}")
    for issue in issues[:25]:
        print(f"  - {issue}")
    if len(issues) > 25:
        print(f"  ... {len(issues) - 25} more")


def print_net(design: Design, requested_name: str) -> None:
    net = design.resolve_net(requested_name)
    print(f"Net:        {net.name}")
    print(f"Aliases:    {', '.join(net.aliases)}")
    print(f"Port:       {net.is_port}")
    print(f"Direction:  {net.inferred_direction}")
    print(f"Drivers:    {terminal_list(net.drivers)}")
    print(f"Loads:      {terminal_list(net.loads)}")
    if net.unknowns:
        print(f"Unknowns:   {terminal_list(net.unknowns)}")

    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for terminal in net.loads:
        instance = design.instances[terminal.instance]
        grouped[(instance.cell_type, terminal.pin, terminal.role)].append(instance.name)
    if grouped:
        print()
        print("Grouped loads:")
        for (cell_type, pin, role), names in sorted(grouped.items()):
            print(f"  {len(names):>4} × {cell_type}.{pin:<12} role={role}")


def pin_connection_description(
    design: Design, instance: Instance, terminal: Terminal
) -> str:
    net = design.nets[terminal.net]
    if terminal.direction == "input":
        source = design.source_description(net.name)
        return f"{terminal.pin:<10} <- {net.name} <- {source}"
    if terminal.direction == "output":
        loads = [load.name for load in net.loads]
        destination = ", ".join(loads) if loads else "(top-level output or unused)"
        return f"{terminal.pin:<10} -> {net.name} -> {destination}"
    return f"{terminal.pin:<10} -- {net.name} [direction unknown]"


def print_instance(
    design: Design,
    requested_name: str,
    depth: int,
    dot_path: str | None,
) -> None:
    instance = design.resolve_instance(requested_name)
    print(instance_title(instance))
    print(f"Function: {instance.model.function or '(not recorded)'}")
    print()
    for terminal in sorted(
        design.signal_terminals(instance),
        key=lambda item: (item.direction != "input", item.pin),
    ):
        print("  " + pin_connection_description(design, instance, terminal))

    if dot_path:
        cells, nets = design.neighborhood(instance.name, depth)
        write_dot(
            design,
            cells,
            nets,
            dot_path,
            f"{instance.name}: radius {depth}",
        )


def print_cone(
    design: Design,
    target: str,
    stop_at_flops: bool,
    dot_path: str | None,
) -> None:
    cone = design.backward_cone(target, stop_at_flops=stop_at_flops)
    combinational = [
        name for name in cone.cells if not design.instances[name].sequential
    ]
    print(f"Target net:         {cone.target_net}")
    print(f"Cells in cone:      {len(cone.cells)}")
    print(f"Combinational:      {len(combinational)}")
    print(f"State boundaries:   {len(cone.state_boundaries)}")
    print(f"Nets visited:       {len(cone.nets)}")
    print()
    if cone.state_boundaries:
        print("State boundaries (traversal stopped at these Q drivers):")
        for name in sorted(cone.state_boundaries, key=natural_key):
            print(f"  {name}")

    counts = Counter(design.instances[name].cell_type for name in combinational)
    if counts:
        print()
        print("Combinational cells:")
        for cell_type, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            print(f"  {count:>5}  {cell_type}")

    if dot_path:
        write_dot(
            design,
            cone.cells,
            cone.nets,
            dot_path,
            f"Backward cone of {target}",
        )


def register_equation(design: Design, register: EnabledRegister) -> str:
    source = design.source_description(register.data_net)
    if register.hold_pin == "A0":
        return f"Q_next = {register.select_net} ? {source} : Q"
    return f"Q_next = {register.select_net} ? Q : {source}"


def print_registers(design: Design, dot_path: str | None) -> None:
    sequential = sorted(
        (instance for instance in design.instances.values() if instance.sequential),
        key=lambda instance: natural_key(instance.name),
    )
    enabled = {register.flip_flop: register for register in design.enabled_registers()}

    print(f"Sequential instances: {len(sequential)}")
    print(f"Enabled-register motifs: {len(enabled)}")
    print()
    for instance in sequential:
        d_net = instance.pins.get("D")
        q_net = instance.pins.get("Q")
        clk = instance.pins.get("CLK")
        reset = instance.pins.get("RESET_B")
        print(instance.name)
        if d_net:
            print(f"  D source: {design.source_description(d_net.net)}")
        if q_net:
            print(f"  Q net:    {q_net.net}")
        if clk:
            print(f"  clock:    {clk.net}")
        if reset:
            print(f"  reset:    {reset.net}")
        if instance.name in enabled:
            register = enabled[instance.name]
            print(
                f"  motif:    mux={register.mux}, hold={register.hold_pin}, "
                f"data={register.data_pin}"
            )
            print(f"  equation: {register_equation(design, register)}")
        print()

    if dot_path:
        cells: set[str] = set()
        nets: set[str] = set()
        for instance in sequential:
            cells.add(instance.name)
            for terminal in design.signal_terminals(instance):
                nets.add(terminal.net)
        for register in enabled.values():
            cells.add(register.mux)
            nets.update(
                terminal.net
                for terminal in design.signal_terminals(design.instances[register.mux])
            )
        write_dot(design, cells, nets, dot_path, "Sequential elements and enable muxes")


def print_shift_chains(design: Design, dot_path: str | None) -> None:
    chains = design.shift_chains()
    multi_stage = [chain for chain in chains if len(chain) > 1]
    print(f"Candidate chains: {len(chains)} ({len(multi_stage)} multi-stage)")
    print()

    cells: set[str] = set()
    nets: set[str] = set()
    for index, chain in enumerate(chains, start=1):
        if not chain:
            continue
        head_source = design.source_description(chain[0].data_net)
        select_nets = sorted({register.select_net for register in chain})
        print(
            f"Chain {index}: {len(chain)} stage(s), "
            f"input={head_source}, select={','.join(select_nets)}"
        )
        for stage, register in enumerate(chain):
            print(
                f"  [{stage}] {register.flip_flop} "
                f"(mux {register.mux}, Q={register.q_net})"
            )
            cells.update((register.flip_flop, register.mux))
            nets.update(
                (register.q_net, register.d_net, register.data_net, register.select_net)
            )
        print()

    if dot_path:
        write_dot(design, cells, nets, dot_path, "Detected enabled shift chains")


def export_design(design: Design, output_path: str) -> None:
    with Path(output_path).open("w") as fh:
        json.dump(design.to_dict(), fh, indent=2)
        fh.write("\n")
    print(f"Wrote {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nets", help="Extracted net JSON to analyze")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary", help="Show design, port, and cell summary")

    net_parser = subparsers.add_parser("net", help="Describe one net or port")
    net_parser.add_argument("name", help="Net name, port alias, or instance.pin")

    instance_parser = subparsers.add_parser(
        "instance", help="Describe one instance and optionally draw its neighborhood"
    )
    instance_parser.add_argument("name", help="Exact instance name or unique prefix")
    instance_parser.add_argument(
        "--depth", type=int, default=1, help="Neighborhood radius for DOT output"
    )
    instance_parser.add_argument("--dot", help="Write neighborhood as Graphviz DOT")

    cone_parser = subparsers.add_parser(
        "cone", help="Trace the backward combinational cone of a net"
    )
    cone_parser.add_argument("target", help="Target net, alias, or instance.pin")
    cone_parser.add_argument(
        "--through-flops",
        action="store_true",
        help="Continue through sequential cells instead of stopping at Q",
    )
    cone_parser.add_argument("--dot", help="Write cone as Graphviz DOT")

    register_parser = subparsers.add_parser(
        "registers", help="List state elements and enabled-register motifs"
    )
    register_parser.add_argument("--dot", help="Write register/mux graph as DOT")

    chain_parser = subparsers.add_parser(
        "shift-chains", help="Detect enabled shift-register chains"
    )
    chain_parser.add_argument("--dot", help="Write detected chains as DOT")

    export_parser = subparsers.add_parser(
        "export", help="Write the derived semantic structure as JSON"
    )
    export_parser.add_argument("--out", required=True, help="Output JSON path")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        design = Design.load(args.nets)
        if args.command == "summary":
            print_summary(design)
        elif args.command == "net":
            print_net(design, args.name)
        elif args.command == "instance":
            print_instance(design, args.name, args.depth, args.dot)
        elif args.command == "cone":
            print_cone(design, args.target, not args.through_flops, args.dot)
        elif args.command == "registers":
            print_registers(design, args.dot)
        elif args.command == "shift-chains":
            print_shift_chains(design, args.dot)
        elif args.command == "export":
            export_design(design, args.out)
        else:
            parser.error(f"Unknown command {args.command}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
