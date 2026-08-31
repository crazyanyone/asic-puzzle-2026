#!/usr/bin/env python3
"""Semantic, queryable representation of an extracted standard-cell netlist.

The extractor's JSON is deliberately simple: net name -> ["instance.pin", ...].
This module keeps that representation as the source of truth and derives:

* an instance -> pin -> net index;
* terminal direction and role from a small Sky130 cell dictionary;
* net drivers and loads;
* inferred top-level port directions;
* backward cones, local neighborhoods, enabled registers, and shift chains.

Unknown cells and pins are retained and reported rather than discarded.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


POWER_PINS = {"VPWR", "VGND", "VPB", "VNB", "VDD", "VSS"}


@dataclass(frozen=True)
class CellModel:
    name: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    clock_pins: tuple[str, ...] = ()
    reset_pins: tuple[str, ...] = ()
    function: str = ""
    sequential: bool = False
    known: bool = True

    def pin_direction(self, pin: str) -> str:
        if pin in POWER_PINS:
            return "power"
        if pin in self.outputs:
            return "output"
        if pin in self.inputs or pin in self.clock_pins or pin in self.reset_pins:
            return "input"
        return "unknown"

    def pin_role(self, pin: str) -> str:
        if pin in POWER_PINS:
            return "power"
        if pin in self.clock_pins:
            return "clock"
        if pin in self.reset_pins:
            return "reset"
        if pin in self.outputs:
            return "state" if self.sequential else "data"
        if pin in self.inputs:
            return "data"
        return "unknown"


def _comb(
    name: str,
    inputs: Iterable[str],
    output: str,
    function: str,
) -> CellModel:
    return CellModel(
        name=name,
        inputs=tuple(inputs),
        outputs=(output,),
        function=function,
    )


# This intentionally covers the warm-up and common Sky130-HD combinational
# cells. Add models from the official PDK as new cell types are encountered.
CELL_MODELS: dict[str, CellModel] = {
    "buf": _comb("buf", ("A",), "X", "X = A"),
    "clkbuf": _comb("clkbuf", ("A",), "X", "X = A"),
    "inv": _comb("inv", ("A",), "Y", "Y = !A"),
    "mux2": _comb("mux2", ("A0", "A1", "S"), "X", "X = S ? A1 : A0"),
    "and2": _comb("and2", ("A", "B"), "X", "X = A & B"),
    "and3": _comb("and3", ("A", "B", "C"), "X", "X = A & B & C"),
    "and4": _comb("and4", ("A", "B", "C", "D"), "X", "X = A & B & C & D"),
    "and4bb": _comb(
        "and4bb",
        ("A_N", "B_N", "C", "D"),
        "X",
        "X = !A_N & !B_N & C & D",
    ),
    "or2": _comb("or2", ("A", "B"), "X", "X = A | B"),
    "or3": _comb("or3", ("A", "B", "C"), "X", "X = A | B | C"),
    "or4": _comb("or4", ("A", "B", "C", "D"), "X", "X = A | B | C | D"),
    "nand2": _comb("nand2", ("A", "B"), "Y", "Y = !(A & B)"),
    "nand3": _comb("nand3", ("A", "B", "C"), "Y", "Y = !(A & B & C)"),
    "nand4": _comb(
        "nand4", ("A", "B", "C", "D"), "Y", "Y = !(A & B & C & D)"
    ),
    "nor2": _comb("nor2", ("A", "B"), "Y", "Y = !(A | B)"),
    "nor3": _comb("nor3", ("A", "B", "C"), "Y", "Y = !(A | B | C)"),
    "nor4": _comb(
        "nor4", ("A", "B", "C", "D"), "Y", "Y = !(A | B | C | D)"
    ),
    "xor2": _comb("xor2", ("A", "B"), "X", "X = A ^ B"),
    "xnor2": _comb("xnor2", ("A", "B"), "Y", "Y = !(A ^ B)"),
    "a21o": _comb(
        "a21o", ("A1", "A2", "B1"), "X", "X = (A1 & A2) | B1"
    ),
    "a21oi": _comb(
        "a21oi", ("A1", "A2", "B1"), "Y", "Y = !((A1 & A2) | B1)"
    ),
    "a21bo": _comb(
        "a21bo", ("A1", "A2", "B1_N"), "X", "X = (A1 & A2) | !B1_N"
    ),
    "a21boi": _comb(
        "a21boi",
        ("A1", "A2", "B1_N"),
        "Y",
        "Y = !((A1 & A2) | !B1_N)",
    ),
    "a22o": _comb(
        "a22o",
        ("A1", "A2", "B1", "B2"),
        "X",
        "X = (A1 & A2) | (B1 & B2)",
    ),
    "a22oi": _comb(
        "a22oi",
        ("A1", "A2", "B1", "B2"),
        "Y",
        "Y = !((A1 & A2) | (B1 & B2))",
    ),
    "a31o": _comb(
        "a31o",
        ("A1", "A2", "A3", "B1"),
        "X",
        "X = (A1 & A2 & A3) | B1",
    ),
    "a31oi": _comb(
        "a31oi",
        ("A1", "A2", "A3", "B1"),
        "Y",
        "Y = !((A1 & A2 & A3) | B1)",
    ),
    "o21a": _comb(
        "o21a", ("A1", "A2", "B1"), "X", "X = (A1 | A2) & B1"
    ),
    "o21ai": _comb(
        "o21ai", ("A1", "A2", "B1"), "Y", "Y = !((A1 | A2) & B1)"
    ),
    "o21ba": _comb(
        "o21ba", ("A1", "A2", "B1_N"), "X", "X = (A1 | A2) & !B1_N"
    ),
    "o21bai": _comb(
        "o21bai",
        ("A1", "A2", "B1_N"),
        "Y",
        "Y = !((A1 | A2) & !B1_N)",
    ),
    "dfrtp": CellModel(
        name="dfrtp",
        inputs=("D",),
        outputs=("Q",),
        clock_pins=("CLK",),
        reset_pins=("RESET_B",),
        function="positive-edge D flip-flop; asynchronous active-low reset",
        sequential=True,
    ),
    "dfxtp": CellModel(
        name="dfxtp",
        inputs=("D",),
        outputs=("Q",),
        clock_pins=("CLK",),
        function="positive-edge D flip-flop",
        sequential=True,
    ),
}


def infer_cell_type(instance_name: str) -> str:
    """Find a known cell token near the end of a synthetic instance name."""
    without_drive = re.sub(r"_\d+$", "", instance_name)
    for name in sorted(CELL_MODELS, key=len, reverse=True):
        if without_drive == name or without_drive.endswith(f"_{name}"):
            return name

    # Preserve a useful unknown type string for diagnostics.
    tail = without_drive.rsplit("_", 1)[-1]
    return tail or "unknown"


def unknown_cell_model(cell_type: str, pins: Iterable[str]) -> CellModel:
    """Conservative fallback; output guesses are clearly marked as unknown."""
    pin_set = set(pins)
    conventional_outputs = tuple(
        pin for pin in ("Q", "Q_N", "X", "Y", "Z") if pin in pin_set
    )
    inputs = tuple(
        sorted(pin_set - set(conventional_outputs) - POWER_PINS)
    )
    return CellModel(
        name=cell_type,
        inputs=inputs,
        outputs=conventional_outputs,
        function="unknown cell; directions use output-pin naming conventions",
        sequential=False,
        known=False,
    )


@dataclass
class Terminal:
    instance: str
    pin: str
    net: str
    direction: str = "unknown"
    role: str = "unknown"

    @property
    def name(self) -> str:
        return f"{self.instance}.{self.pin}"


@dataclass
class Instance:
    name: str
    cell_type: str
    model: CellModel
    pins: dict[str, Terminal] = field(default_factory=dict)

    @property
    def sequential(self) -> bool:
        return self.model.sequential


@dataclass
class Net:
    name: str
    aliases: tuple[str, ...]
    terminals: list[Terminal] = field(default_factory=list)
    drivers: list[Terminal] = field(default_factory=list)
    loads: list[Terminal] = field(default_factory=list)
    unknowns: list[Terminal] = field(default_factory=list)
    is_port: bool = False
    is_power: bool = False

    @property
    def inferred_direction(self) -> str:
        if not self.is_port:
            return "internal"
        if self.is_power:
            return "power"
        if not self.drivers and self.loads:
            return "input"
        if self.drivers and not self.loads:
            return "output"
        if self.drivers and self.loads:
            return "inout-or-aliased"
        return "unknown"


@dataclass
class EnabledRegister:
    flip_flop: str
    mux: str
    q_net: str
    d_net: str
    hold_pin: str
    data_pin: str
    data_net: str
    select_net: str


@dataclass
class Cone:
    target_net: str
    cells: set[str]
    nets: set[str]
    state_boundaries: set[str]


@dataclass
class Design:
    instances: dict[str, Instance]
    nets: dict[str, Net]
    terminals: dict[str, Terminal]
    source_path: str

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        source = Path(path)
        with source.open() as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError("Expected a JSON object mapping nets to terminal lists")

        pin_maps: dict[str, dict[str, str]] = {}
        net_terms: dict[str, list[tuple[str, str]]] = {}

        for net_name, terminal_names in raw.items():
            if not isinstance(net_name, str) or not isinstance(terminal_names, list):
                raise ValueError("Each net must map from a string to a list")
            net_terms[net_name] = []
            for terminal_name in terminal_names:
                if not isinstance(terminal_name, str) or "." not in terminal_name:
                    raise ValueError(
                        f"Invalid terminal {terminal_name!r} on net {net_name!r}"
                    )
                instance_name, pin = terminal_name.rsplit(".", 1)
                existing = pin_maps.setdefault(instance_name, {}).get(pin)
                if existing is not None and existing != net_name:
                    raise ValueError(
                        f"{instance_name}.{pin} occurs on both {existing!r} "
                        f"and {net_name!r}"
                    )
                pin_maps[instance_name][pin] = net_name
                net_terms[net_name].append((instance_name, pin))

        instances: dict[str, Instance] = {}
        for instance_name, pins in pin_maps.items():
            cell_type = infer_cell_type(instance_name)
            model = CELL_MODELS.get(cell_type)
            if model is None:
                model = unknown_cell_model(cell_type, pins)
            instances[instance_name] = Instance(instance_name, cell_type, model)

        terminals: dict[str, Terminal] = {}
        nets: dict[str, Net] = {}
        for net_name, members in net_terms.items():
            aliases = tuple(net_name.split("|"))
            is_internal = net_name.startswith("(")
            net = Net(
                name=net_name,
                aliases=aliases,
                is_port=not is_internal,
                is_power=any(alias in POWER_PINS for alias in aliases),
            )
            nets[net_name] = net
            for instance_name, pin in members:
                instance = instances[instance_name]
                terminal = Terminal(
                    instance=instance_name,
                    pin=pin,
                    net=net_name,
                    direction=instance.model.pin_direction(pin),
                    role=instance.model.pin_role(pin),
                )
                if terminal.name in terminals:
                    raise ValueError(f"Duplicate terminal {terminal.name}")
                terminals[terminal.name] = terminal
                instance.pins[pin] = terminal
                net.terminals.append(terminal)
                if terminal.direction == "output":
                    net.drivers.append(terminal)
                elif terminal.direction == "input":
                    net.loads.append(terminal)
                elif terminal.direction != "power":
                    net.unknowns.append(terminal)

        return cls(instances, nets, terminals, str(source))

    @property
    def ports(self) -> dict[str, Net]:
        return {
            alias: net
            for net in self.nets.values()
            if net.is_port
            for alias in net.aliases
        }

    def resolve_net(self, name_or_terminal: str) -> Net:
        if name_or_terminal in self.nets:
            return self.nets[name_or_terminal]
        if name_or_terminal in self.ports:
            return self.ports[name_or_terminal]
        if name_or_terminal in self.terminals:
            return self.nets[self.terminals[name_or_terminal].net]
        raise KeyError(f"Unknown net, alias, or terminal: {name_or_terminal}")

    def resolve_instance(self, name: str) -> Instance:
        if name in self.instances:
            return self.instances[name]
        matches = [instance for key, instance in self.instances.items() if key.startswith(name)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise KeyError(f"Ambiguous instance prefix {name!r}")
        raise KeyError(f"Unknown instance: {name}")

    def signal_terminals(self, instance: Instance) -> list[Terminal]:
        return [terminal for terminal in instance.pins.values() if terminal.role != "power"]

    def driver_of(self, net_name: str) -> Terminal | None:
        drivers = self.nets[net_name].drivers
        return drivers[0] if len(drivers) == 1 else None

    def source_description(self, net_name: str) -> str:
        net = self.nets[net_name]
        if net.is_port and net.inferred_direction == "input":
            return "|".join(net.aliases)
        if len(net.drivers) == 1:
            return net.drivers[0].name
        if len(net.drivers) > 1:
            return ", ".join(terminal.name for terminal in net.drivers)
        return net_name

    def validation_issues(self) -> list[str]:
        issues: list[str] = []
        for instance in self.instances.values():
            if not instance.model.known:
                issues.append(
                    f"unknown cell model {instance.cell_type!r} on {instance.name}"
                )
            for terminal in instance.pins.values():
                if terminal.direction == "unknown":
                    issues.append(f"unknown pin direction: {terminal.name}")
        for net in self.nets.values():
            if net.is_power:
                continue
            if len(net.drivers) > 1:
                names = ", ".join(terminal.name for terminal in net.drivers)
                issues.append(f"multiple drivers on {net.name}: {names}")
            if net.unknowns:
                names = ", ".join(terminal.name for terminal in net.unknowns)
                issues.append(f"unknown terminals on {net.name}: {names}")
            if (
                not net.is_port
                and not net.drivers
                and net.loads
                and not net.name.startswith("('UNRESOLVED'")
            ):
                issues.append(f"undriven internal net {net.name}")
        return issues

    def neighborhood(
        self, instance_name: str, radius: int = 1
    ) -> tuple[set[str], set[str]]:
        start = self.resolve_instance(instance_name).name
        cells = {start}
        frontier = {start}
        nets: set[str] = set()

        for _ in range(max(radius, 0)):
            next_frontier: set[str] = set()
            for cell_name in frontier:
                instance = self.instances[cell_name]
                for terminal in self.signal_terminals(instance):
                    net = self.nets[terminal.net]
                    if net.is_power:
                        continue
                    nets.add(net.name)
                    for neighbor in net.terminals:
                        if neighbor.role != "power" and neighbor.instance not in cells:
                            next_frontier.add(neighbor.instance)
            cells.update(next_frontier)
            frontier = next_frontier

        # Include all signal nets connecting selected cells.
        for cell_name in cells:
            for terminal in self.signal_terminals(self.instances[cell_name]):
                net = self.nets[terminal.net]
                if any(member.instance in cells for member in net.terminals):
                    nets.add(net.name)
        return cells, nets

    def backward_cone(
        self, target: str, stop_at_flops: bool = True
    ) -> Cone:
        target_net = self.resolve_net(target)
        pending = [target_net.name]
        seen_nets: set[str] = set()
        cells: set[str] = set()
        boundaries: set[str] = set()

        while pending:
            net_name = pending.pop()
            if net_name in seen_nets:
                continue
            seen_nets.add(net_name)
            net = self.nets[net_name]
            for driver in net.drivers:
                instance = self.instances[driver.instance]
                cells.add(instance.name)
                if stop_at_flops and instance.sequential:
                    boundaries.add(instance.name)
                    continue
                for terminal in self.signal_terminals(instance):
                    if terminal.direction == "input" and terminal.role == "data":
                        pending.append(terminal.net)

        return Cone(target_net.name, cells, seen_nets, boundaries)

    def enabled_registers(self) -> list[EnabledRegister]:
        found: list[EnabledRegister] = []
        for flip_flop in self.instances.values():
            if not flip_flop.sequential:
                continue
            if "D" not in flip_flop.pins or "Q" not in flip_flop.pins:
                continue
            d_net = flip_flop.pins["D"].net
            q_net = flip_flop.pins["Q"].net
            driver = self.driver_of(d_net)
            if driver is None:
                continue
            mux = self.instances[driver.instance]
            if mux.cell_type != "mux2" or driver.pin != "X":
                continue
            if not all(pin in mux.pins for pin in ("A0", "A1", "S")):
                continue
            if mux.pins["A0"].net == q_net:
                hold_pin, data_pin = "A0", "A1"
            elif mux.pins["A1"].net == q_net:
                hold_pin, data_pin = "A1", "A0"
            else:
                continue
            found.append(
                EnabledRegister(
                    flip_flop=flip_flop.name,
                    mux=mux.name,
                    q_net=q_net,
                    d_net=d_net,
                    hold_pin=hold_pin,
                    data_pin=data_pin,
                    data_net=mux.pins[data_pin].net,
                    select_net=mux.pins["S"].net,
                )
            )
        return found

    def shift_chains(self) -> list[list[EnabledRegister]]:
        registers = self.enabled_registers()
        by_ff = {register.flip_flop: register for register in registers}
        q_driver_to_ff = {
            register.flip_flop: register.flip_flop for register in registers
        }

        predecessor: dict[str, str | None] = {}
        successors: dict[str, list[str]] = {name: [] for name in by_ff}
        for register in registers:
            source = self.driver_of(register.data_net)
            pred = source.instance if source and source.instance in q_driver_to_ff else None
            predecessor[register.flip_flop] = pred
            if pred is not None:
                successors[pred].append(register.flip_flop)

        chains: list[list[EnabledRegister]] = []
        visited: set[str] = set()
        heads = [name for name, pred in predecessor.items() if pred is None]
        for head in sorted(heads):
            chain: list[EnabledRegister] = []
            current: str | None = head
            while current is not None and current not in visited:
                visited.add(current)
                chain.append(by_ff[current])
                next_cells = successors[current]
                current = next_cells[0] if len(next_cells) == 1 else None
            chains.append(chain)

        for name in sorted(set(by_ff) - visited):
            chains.append([by_ff[name]])
        return chains

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source_path,
            "ports": {
                alias: {
                    "net": net.name,
                    "direction": net.inferred_direction,
                }
                for alias, net in sorted(self.ports.items())
            },
            "instances": {
                name: {
                    "cell_type": instance.cell_type,
                    "known_model": instance.model.known,
                    "sequential": instance.sequential,
                    "function": instance.model.function,
                    "pins": {
                        pin: {
                            "net": terminal.net,
                            "direction": terminal.direction,
                            "role": terminal.role,
                        }
                        for pin, terminal in sorted(instance.pins.items())
                    },
                }
                for name, instance in sorted(self.instances.items())
            },
            "nets": {
                name: {
                    "aliases": list(net.aliases),
                    "is_port": net.is_port,
                    "is_power": net.is_power,
                    "inferred_direction": net.inferred_direction,
                    "drivers": [terminal.name for terminal in net.drivers],
                    "loads": [terminal.name for terminal in net.loads],
                    "unknowns": [terminal.name for terminal in net.unknowns],
                }
                for name, net in sorted(self.nets.items())
            },
            "validation_issues": self.validation_issues(),
        }
