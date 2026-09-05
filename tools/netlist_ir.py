#!/usr/bin/env python3
"""Semantic, queryable representation of an extracted standard-cell netlist.

The extractor's JSON is deliberately simple: each net has an id, optional
top-level aliases, and a list of ``instance.pin`` terminals. This module keeps
that representation as the source of truth and derives:

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
from dataclasses import dataclass, field, replace
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
    set_pins: tuple[str, ...] = ()
    function: str = ""
    output_functions: tuple[tuple[str, str], ...] = ()
    clocked_on: str | None = None
    next_state: str | None = None
    clear: str | None = None
    preset: str | None = None
    sequential: bool = False
    known: bool = True

    def output_expression(self, pin: str) -> str:
        functions = dict(self.output_functions)
        if pin not in functions:
            raise KeyError(f"No output function for {self.name}.{pin}")
        return functions[pin]

    def pin_direction(self, pin: str) -> str:
        if pin in POWER_PINS:
            return "power"
        if pin in self.outputs:
            return "output"
        if (
            pin in self.inputs
            or pin in self.clock_pins
            or pin in self.reset_pins
            or pin in self.set_pins
        ):
            return "input"
        return "unknown"

    def pin_role(self, pin: str) -> str:
        if pin in POWER_PINS:
            return "power"
        if pin in self.clock_pins:
            return "clock"
        if pin in self.reset_pins:
            return "reset"
        if pin in self.set_pins:
            return "set"
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


def _const(name: str, outputs: Iterable[str], function: str) -> CellModel:
    return CellModel(
        name=name,
        outputs=tuple(outputs),
        function=function,
    )


# These readable declarations are assertions about the expected cell subset,
# not the runtime source of Boolean behavior.  The loader below checks every
# pin/control role, then replaces every function and state equation with the
# checked-in official Liberty snapshot.  A mismatch fails at import time.
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
    "dfstp": CellModel(
        name="dfstp",
        inputs=("D",),
        outputs=("Q",),
        clock_pins=("CLK",),
        set_pins=("SET_B",),
        function="positive-edge D flip-flop; asynchronous active-low set",
        sequential=True,
    ),
    # --- Puzzle netlist cells (from Sky130 HD functional Verilog) ---
    "conb": _const("conb", ("HI", "LO"), "HI=1, LO=0"),
    "and2b": _comb("and2b", ("A_N", "B"), "X", "X = !A_N & B"),
    "and3b": _comb("and3b", ("A_N", "B", "C"), "X", "X = !A_N & B & C"),
    "and4b": _comb("and4b", ("A_N", "B", "C", "D"), "X", "X = !A_N & B & C & D"),
    "nand2b": _comb("nand2b", ("A_N", "B"), "Y", "Y = !(!A_N & B)"),
    "nand3b": _comb("nand3b", ("A_N", "B", "C"), "Y", "Y = !(!A_N & B & C)"),
    "nor3b": _comb("nor3b", ("A", "B", "C_N"), "Y", "Y = !((A | B) | !C_N)"),
    "nor4b": _comb("nor4b", ("A", "B", "C", "D_N"), "Y", "Y = !((A | B | C) | !D_N)"),
    "or3b": _comb("or3b", ("A", "B", "C_N"), "X", "X = A | B | !C_N"),
    "or4b": _comb("or4b", ("A", "B", "C", "D_N"), "X", "X = A | B | C | !D_N"),
    "or4bb": _comb(
        "or4bb", ("A", "B", "C_N", "D_N"), "X", "X = A | B | !C_N | !D_N"
    ),
    "a211o": _comb(
        "a211o", ("A1", "A2", "B1", "C1"), "X", "X = (A1 & A2) | B1 | C1"
    ),
    "a211oi": _comb(
        "a211oi", ("A1", "A2", "B1", "C1"), "Y", "Y = !((A1 & A2) | B1 | C1)"
    ),
    "a2111oi": _comb(
        "a2111oi",
        ("A1", "A2", "B1", "C1", "D1"),
        "Y",
        "Y = !((A1 & A2) | B1 | C1 | D1)",
    ),
    "a221o": _comb(
        "a221o",
        ("A1", "A2", "B1", "B2", "C1"),
        "X",
        "X = (A1 & A2) | (B1 & B2) | C1",
    ),
    "a221oi": _comb(
        "a221oi",
        ("A1", "A2", "B1", "B2", "C1"),
        "Y",
        "Y = !((A1 & A2) | (B1 & B2) | C1)",
    ),
    "a311o": _comb(
        "a311o",
        ("A1", "A2", "A3", "B1", "C1"),
        "X",
        "X = (A1 & A2 & A3) | B1 | C1",
    ),
    "a32o": _comb(
        "a32o",
        ("A1", "A2", "A3", "B1", "B2"),
        "X",
        "X = (A1 & A2 & A3) | (B1 & B2)",
    ),
    "a41oi": _comb(
        "a41oi",
        ("A1", "A2", "A3", "A4", "B1"),
        "Y",
        "Y = !((A1 & A2 & A3 & A4) | B1)",
    ),
    "o211a": _comb(
        "o211a",
        ("A1", "A2", "B1", "C1"),
        "X",
        "X = (A1 | A2) & B1 & C1",
    ),
    "o211ai": _comb(
        "o211ai",
        ("A1", "A2", "B1", "C1"),
        "Y",
        "Y = !((A1 | A2) & B1 & C1)",
    ),
    "o221a": _comb(
        "o221a",
        ("A1", "A2", "B1", "B2", "C1"),
        "X",
        "X = (A1 | A2) & (B1 | B2) & C1",
    ),
    "o22a": _comb(
        "o22a", ("A1", "A2", "B1", "B2"), "X", "X = (A1 | A2) & (B1 | B2)"
    ),
    "o22ai": _comb(
        "o22ai", ("A1", "A2", "B1", "B2"), "Y", "Y = !((A1 | A2) & (B1 | B2))"
    ),
    "o2bb2a": _comb(
        "o2bb2a",
        ("A1_N", "A2_N", "B1", "B2"),
        "X",
        "X = !(A1_N & A2_N) & (B1 | B2)",
    ),
    "o311a": _comb(
        "o311a",
        ("A1", "A2", "A3", "B1", "C1"),
        "X",
        "X = (A1 | A2 | A3) & B1 & C1",
    ),
    "o31a": _comb(
        "o31a", ("A1", "A2", "A3", "B1"), "X", "X = (A1 | A2 | A3) & B1"
    ),
    "o31ai": _comb(
        "o31ai", ("A1", "A2", "A3", "B1"), "Y", "Y = !((A1 | A2 | A3) & B1)"
    ),
    "o32a": _comb(
        "o32a",
        ("A1", "A2", "A3", "B1", "B2"),
        "X",
        "X = (A1 | A2 | A3) & (B1 | B2)",
    ),
    "o32ai": _comb(
        "o32ai",
        ("A1", "A2", "A3", "B1", "B2"),
        "Y",
        "Y = !((A1 | A2 | A3) & (B1 | B2))",
    ),
}


def _apply_official_model_snapshot(
    models: dict[str, CellModel],
) -> tuple[dict[str, CellModel], dict[str, object]]:
    """Validate pin metadata and replace behavior with official Liberty data."""
    path = Path(__file__).with_name("sky130_hd_cells.json")
    raw = json.loads(path.read_text())
    official = raw.get("cells")
    if not isinstance(official, dict):
        raise RuntimeError(f"Invalid cell-model snapshot: {path}")
    if set(models) != set(official):
        raise RuntimeError(
            "Cell-model table and official snapshot disagree: "
            f"table_only={sorted(set(models) - set(official))}, "
            f"snapshot_only={sorted(set(official) - set(models))}"
        )

    validated: dict[str, CellModel] = {}
    for name, model in models.items():
        record = official[name]
        output_functions = record["outputs"]
        expected = {
            "inputs": set(model.inputs),
            "outputs": set(model.outputs),
            "clock_pins": set(model.clock_pins),
            "reset_pins": set(model.reset_pins),
            "set_pins": set(model.set_pins),
        }
        observed = {
            "inputs": set(record["inputs"]),
            "outputs": set(output_functions),
            "clock_pins": set(record["clock_pins"]),
            "reset_pins": set(record["reset_pins"]),
            "set_pins": set(record["set_pins"]),
        }
        if expected != observed or model.sequential != record["sequential"]:
            raise RuntimeError(
                f"Hand-written metadata disagrees with official model for {name}: "
                f"expected={expected}, observed={observed}"
            )
        equations = "; ".join(
            f"{pin} = {expression}"
            for pin, expression in sorted(output_functions.items())
        )
        description = record["description"]
        function = f"{description} {equations}" if equations else description
        validated[name] = replace(
            model,
            inputs=tuple(record["inputs"]),
            outputs=tuple(output_functions),
            clock_pins=tuple(record["clock_pins"]),
            reset_pins=tuple(record["reset_pins"]),
            set_pins=tuple(record["set_pins"]),
            function=function,
            output_functions=tuple(sorted(output_functions.items())),
            clocked_on=record["clocked_on"],
            next_state=record["next_state"],
            clear=record["clear"],
            preset=record["preset"],
            sequential=record["sequential"],
        )
    return validated, raw


CELL_MODELS, CELL_MODEL_PROVENANCE = _apply_official_model_snapshot(CELL_MODELS)


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
        # Internal fan-out from an output net is normal and does not make the
        # top-level port bidirectional. A cell driver is the decisive evidence.
        if self.drivers:
            return "output"
        if self.loads:
            return "input"
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
class ShiftRegister:
    """A strictly verified serial shift-register abstraction.

    `stages` are ordered from the serial-input stage toward the final stage.
    The original cells and nets remain in `Design`; this object is a view over
    them, not a destructive replacement.
    """

    name: str
    stages: tuple[EnabledRegister, ...]
    serial_input_net: str
    enable_net: str
    clock_net: str
    clock_leaf_nets: tuple[str, ...]
    reset_net: str | None
    parallel_output_nets: tuple[str, ...]
    external_q_loads: dict[str, tuple[str, ...]]
    evidence: tuple[str, ...]

    @property
    def width(self) -> int:
        return len(self.stages)

    @property
    def member_instances(self) -> frozenset[str]:
        return frozenset(
            instance
            for stage in self.stages
            for instance in (stage.flip_flop, stage.mux)
        )


@dataclass
class ShiftRegisterRejection:
    candidates: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass
class ShiftRegisterAnalysis:
    shift_registers: list[ShiftRegister]
    rejections: list[ShiftRegisterRejection]


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
            raise ValueError("Expected a JSON object containing extracted nets")

        # Schema v1 records port aliases explicitly. The legacy format was a
        # bare net-name -> terminal-list mapping and inferred ports from names.
        schema_v1 = raw.get("schema_version") == 1
        if schema_v1:
            raw_nets = raw.get("nets")
            if not isinstance(raw_nets, dict):
                raise ValueError("Schema v1 requires a 'nets' object")
        else:
            raw_nets = raw

        pin_maps: dict[str, dict[str, str]] = {}
        net_terms: dict[str, list[tuple[str, str]]] = {}
        net_aliases: dict[str, tuple[str, ...]] = {}

        for net_name, record in raw_nets.items():
            if not isinstance(net_name, str):
                raise ValueError("Each net id must be a string")
            if schema_v1:
                if not isinstance(record, dict):
                    raise ValueError(f"Net {net_name!r} must be an object")
                terminal_names = record.get("terminals")
                aliases = record.get("aliases")
                if not isinstance(terminal_names, list) or not isinstance(aliases, list):
                    raise ValueError(
                        f"Net {net_name!r} requires 'terminals' and 'aliases' lists"
                    )
                if not all(isinstance(alias, str) for alias in aliases):
                    raise ValueError(f"Net {net_name!r} has a non-string alias")
                net_aliases[net_name] = tuple(aliases)
            else:
                terminal_names = record
                is_internal = net_name.startswith("(")
                net_aliases[net_name] = (
                    () if is_internal else tuple(net_name.split("|"))
                )
            if not isinstance(terminal_names, list):
                raise ValueError(f"Net {net_name!r} terminals must be a list")
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
            aliases = net_aliases[net_name]
            net = Net(
                name=net_name,
                aliases=aliases,
                is_port=bool(aliases),
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
        # ``U28`` must not match ``U280_…``. Treat ``_`` as the end of the
        # instance number so a short id is a unique prefix of ``U28_dfrtp_2``.
        matches = [
            instance
            for key, instance in self.instances.items()
            if key == name or key.startswith(f"{name}_")
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            shown = ", ".join(sorted(instance.name for instance in matches)[:8])
            extra = "" if len(matches) <= 8 else f", … ({len(matches)} total)"
            raise KeyError(
                f"Ambiguous instance prefix {name!r}: {shown}{extra}"
            )
        raise KeyError(f"Unknown instance: {name}")

    def signal_terminals(self, instance: Instance) -> list[Terminal]:
        return [terminal for terminal in instance.pins.values() if terminal.role != "power"]

    def driver_of(self, net_name: str) -> Terminal | None:
        drivers = self.nets[net_name].drivers
        return drivers[0] if len(drivers) == 1 else None

    def transparent_source_net(
        self,
        net_name: str,
        cell_types: frozenset[str] = frozenset({"buf", "clkbuf"}),
    ) -> str:
        """Walk backward through one-input transparent buffers."""
        seen: set[str] = set()
        while net_name not in seen:
            seen.add(net_name)
            driver = self.driver_of(net_name)
            if driver is None:
                return net_name
            instance = self.instances[driver.instance]
            if (
                instance.cell_type not in cell_types
                or driver.pin not in instance.model.outputs
                or "A" not in instance.pins
            ):
                return net_name
            net_name = instance.pins["A"].net
        return net_name

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
                and not net.name.startswith("unresolved_")
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

    def net_neighborhood(
        self, net_name: str, radius: int = 1
    ) -> tuple[set[str], set[str]]:
        """Return the bipartite neighborhood starting from a net."""
        start = self.resolve_net(net_name).name
        nets = {start}
        frontier = {start}
        cells: set[str] = set()

        for _ in range(max(radius, 0)):
            next_frontier: set[str] = set()
            for current_net in frontier:
                for terminal in self.nets[current_net].terminals:
                    if terminal.role == "power":
                        continue
                    cells.add(terminal.instance)
                    for neighbor in self.signal_terminals(
                        self.instances[terminal.instance]
                    ):
                        if not self.nets[neighbor.net].is_power:
                            next_frontier.add(neighbor.net)
            next_frontier -= nets
            nets.update(next_frontier)
            frontier = next_frontier
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

    def strict_shift_registers(self) -> ShiftRegisterAnalysis:
        """Recognize only structurally exact mux/DFF serial shift registers.

        Strictness rules:

        * every stage is a known sequential cell with its complete expected
          signal-pin set;
        * D is driven only by one mux X, and that D net has no other terminals;
        * the mux has exactly A0/A1/S/X and exactly one data input is own Q;
        * Q has exactly one driver, the stage's Q pin;
        * stages form one unbranched, acyclic, multi-stage chain;
        * all stages share a clock source (buffer leaves may differ), reset,
          enable, and mux orientation;
        * loads on muxes inside the abstraction exactly match the expected
          self-hold and next-stage serial connections.

        Loads on cells outside the abstraction, including downstream muxes,
        are legal parallel-output taps and are recorded on the boundary.
        """
        local_stages: dict[str, EnabledRegister] = {}
        rejections: list[ShiftRegisterRejection] = []

        for flip_flop in sorted(
            (
                instance
                for instance in self.instances.values()
                if instance.sequential
            ),
            key=lambda instance: instance.name,
        ):
            reasons: list[str] = []
            if not flip_flop.model.known:
                reasons.append("sequential cell model is not authoritative")

            expected_ff_pins = set(
                flip_flop.model.inputs
                + flip_flop.model.outputs
                + flip_flop.model.clock_pins
                + flip_flop.model.reset_pins
                + flip_flop.model.set_pins
            )
            actual_ff_pins = {
                terminal.pin for terminal in self.signal_terminals(flip_flop)
            }
            if actual_ff_pins != expected_ff_pins:
                reasons.append(
                    "flip-flop signal pins differ from model: "
                    f"expected={sorted(expected_ff_pins)}, "
                    f"actual={sorted(actual_ff_pins)}"
                )
            if "D" not in flip_flop.pins or "Q" not in flip_flop.pins:
                reasons.append("flip-flop does not expose both D and Q")
            if flip_flop.model.set_pins:
                reasons.append(
                    "asynchronous-set flip-flops are not supported by this "
                    "shift-register abstraction"
                )

            mux: Instance | None = None
            hold_pin = ""
            data_pin = ""
            d_net_name = flip_flop.pins["D"].net if "D" in flip_flop.pins else ""
            q_net_name = flip_flop.pins["Q"].net if "Q" in flip_flop.pins else ""

            if d_net_name:
                d_net = self.nets[d_net_name]
                if len(d_net.drivers) != 1:
                    reasons.append(
                        f"D net has {len(d_net.drivers)} drivers instead of one"
                    )
                else:
                    driver = d_net.drivers[0]
                    candidate_mux = self.instances[driver.instance]
                    if candidate_mux.cell_type != "mux2" or driver.pin != "X":
                        reasons.append(
                            f"D driver is {driver.name}, not a mux2.X output"
                        )
                    else:
                        mux = candidate_mux

                functional_d_terminals = {
                    terminal.name
                    for terminal in d_net.terminals
                    if terminal.role != "power"
                }
                expected_d_terminals = {f"{flip_flop.name}.D"}
                if d_net.drivers:
                    expected_d_terminals.add(d_net.drivers[0].name)
                if functional_d_terminals != expected_d_terminals:
                    reasons.append(
                        "D net is not point-to-point mux.X -> flip-flop.D: "
                        f"{sorted(functional_d_terminals)}"
                    )

            if q_net_name:
                q_net = self.nets[q_net_name]
                if [terminal.name for terminal in q_net.drivers] != [
                    f"{flip_flop.name}.Q"
                ]:
                    reasons.append(
                        "Q net is not driven exclusively by this flip-flop.Q"
                    )

            if mux is not None:
                expected_mux_pins = set(
                    mux.model.inputs
                    + mux.model.outputs
                    + mux.model.clock_pins
                    + mux.model.reset_pins
                )
                actual_mux_pins = {
                    terminal.pin for terminal in self.signal_terminals(mux)
                }
                if not mux.model.known:
                    reasons.append("mux cell model is not authoritative")
                if actual_mux_pins != expected_mux_pins:
                    reasons.append(
                        "mux signal pins differ from model: "
                        f"expected={sorted(expected_mux_pins)}, "
                        f"actual={sorted(actual_mux_pins)}"
                    )
                required_mux_pins = {"A0", "A1", "S", "X"}
                if not required_mux_pins <= set(mux.pins):
                    reasons.append("mux is missing one of A0/A1/S/X")
                elif q_net_name:
                    self_inputs = [
                        pin
                        for pin in ("A0", "A1")
                        if mux.pins[pin].net == q_net_name
                    ]
                    if len(self_inputs) != 1:
                        reasons.append(
                            "exactly one mux data input must be the stage's own Q"
                        )
                    else:
                        hold_pin = self_inputs[0]
                        data_pin = "A1" if hold_pin == "A0" else "A0"

            if reasons or mux is None or not hold_pin:
                rejections.append(
                    ShiftRegisterRejection(
                        candidates=(flip_flop.name,),
                        reasons=tuple(dict.fromkeys(reasons)),
                    )
                )
                continue

            local_stages[flip_flop.name] = EnabledRegister(
                flip_flop=flip_flop.name,
                mux=mux.name,
                q_net=q_net_name,
                d_net=d_net_name,
                hold_pin=hold_pin,
                data_pin=data_pin,
                data_net=mux.pins[data_pin].net,
                select_net=mux.pins["S"].net,
            )

        predecessor: dict[str, str | None] = {}
        successors: dict[str, list[str]] = {
            flip_flop: [] for flip_flop in local_stages
        }
        adjacency: dict[str, set[str]] = {
            flip_flop: set() for flip_flop in local_stages
        }
        for flip_flop, stage in local_stages.items():
            source = self.driver_of(stage.data_net)
            pred = (
                source.instance
                if source is not None
                and source.pin == "Q"
                and source.instance in local_stages
                else None
            )
            predecessor[flip_flop] = pred
            if pred is not None:
                successors[pred].append(flip_flop)
                adjacency[pred].add(flip_flop)
                adjacency[flip_flop].add(pred)

        components: list[set[str]] = []
        unvisited = set(local_stages)
        while unvisited:
            seed = min(unvisited)
            component: set[str] = set()
            pending = [seed]
            while pending:
                current = pending.pop()
                if current in component:
                    continue
                component.add(current)
                pending.extend(adjacency[current] - component)
            unvisited -= component
            components.append(component)

        abstractions: list[ShiftRegister] = []
        used_names: set[str] = set()
        for component in sorted(components, key=lambda item: sorted(item)):
            reasons: list[str] = []
            if len(component) < 2:
                reasons.append(
                    "only one enabled stage; insufficient evidence for a shift chain"
                )

            heads = [
                flip_flop
                for flip_flop in component
                if predecessor[flip_flop] not in component
            ]
            if len(heads) != 1:
                reasons.append(
                    f"chain must have exactly one head, found {len(heads)}"
                )
            branched = {
                flip_flop: [
                    successor
                    for successor in successors[flip_flop]
                    if successor in component
                ]
                for flip_flop in component
                if len(
                    [
                        successor
                        for successor in successors[flip_flop]
                        if successor in component
                    ]
                )
                > 1
            }
            if branched:
                reasons.append(
                    "chain branches at "
                    + ", ".join(
                        f"{name}->{sorted(children)}"
                        for name, children in sorted(branched.items())
                    )
                )

            ordered_names: list[str] = []
            if len(heads) == 1 and not branched:
                current: str | None = heads[0]
                while current is not None and current not in ordered_names:
                    ordered_names.append(current)
                    children = [
                        successor
                        for successor in successors[current]
                        if successor in component
                    ]
                    current = children[0] if children else None
                if len(ordered_names) != len(component):
                    reasons.append(
                        "chain is cyclic or does not cover every candidate stage"
                    )

            ordered_stages = [
                local_stages[name] for name in ordered_names
            ]
            if ordered_stages:
                enable_nets = {stage.select_net for stage in ordered_stages}
                hold_pins = {stage.hold_pin for stage in ordered_stages}
                data_pins = {stage.data_pin for stage in ordered_stages}
                clock_leaf_nets: set[str] = set()
                clock_source_nets: set[str] = set()
                reset_nets: set[str | None] = set()

                for stage in ordered_stages:
                    flip_flop = self.instances[stage.flip_flop]
                    clocks = [
                        flip_flop.pins[pin].net
                        for pin in flip_flop.model.clock_pins
                        if pin in flip_flop.pins
                    ]
                    resets = [
                        flip_flop.pins[pin].net
                        for pin in flip_flop.model.reset_pins
                        if pin in flip_flop.pins
                    ]
                    if len(clocks) != 1:
                        reasons.append(
                            f"{stage.flip_flop} does not have exactly one clock"
                        )
                    else:
                        clock_leaf_nets.add(clocks[0])
                        clock_source_nets.add(
                            self.transparent_source_net(clocks[0])
                        )
                    if len(resets) > 1:
                        reasons.append(
                            f"{stage.flip_flop} has multiple reset controls"
                        )
                    else:
                        reset_nets.add(resets[0] if resets else None)

                if len(enable_nets) != 1:
                    reasons.append("stages do not share one enable net")
                if len(clock_source_nets) != 1:
                    reasons.append("stages do not share one buffered clock source")
                if len(reset_nets) != 1:
                    reasons.append("stages do not share one reset net")
                if len(hold_pins) != 1 or len(data_pins) != 1:
                    reasons.append("mux hold/data orientation changes within chain")

                member_muxes = {stage.mux for stage in ordered_stages}
                for index, stage in enumerate(ordered_stages):
                    q_net = self.nets[stage.q_net]
                    actual_internal_mux_loads = {
                        terminal.name
                        for terminal in q_net.loads
                        if terminal.instance in member_muxes
                    }
                    allowed_internal_mux_loads = {
                        f"{stage.mux}.{stage.hold_pin}"
                    }
                    if index + 1 < len(ordered_stages):
                        successor = ordered_stages[index + 1]
                        allowed_internal_mux_loads.add(
                            f"{successor.mux}.{successor.data_pin}"
                        )
                    if (
                        actual_internal_mux_loads
                        != allowed_internal_mux_loads
                    ):
                        reasons.append(
                            f"{stage.flip_flop} Q has incorrect internal mux loads: "
                            f"expected={sorted(allowed_internal_mux_loads)}, "
                            f"actual={sorted(actual_internal_mux_loads)}"
                        )

            if reasons:
                rejections.append(
                    ShiftRegisterRejection(
                        candidates=tuple(sorted(component)),
                        reasons=tuple(dict.fromkeys(reasons)),
                    )
                )
                continue

            first = ordered_stages[0]
            serial_net = self.nets[first.data_net]
            if serial_net.is_port:
                input_label = "_".join(serial_net.aliases)
            else:
                input_label = "internal"
            safe_label = re.sub(r"[^A-Za-z0-9_]+", "_", input_label).strip("_")
            base_name = f"shift_{safe_label or 'register'}"
            name = base_name
            suffix = 2
            while name in used_names:
                name = f"{base_name}_{suffix}"
                suffix += 1
            used_names.add(name)

            external_q_loads: dict[str, tuple[str, ...]] = {}
            for stage in ordered_stages:
                q_net = self.nets[stage.q_net]
                internal_muxes = {
                    f"{stage.mux}.{stage.hold_pin}",
                    *(
                        f"{candidate.mux}.{candidate.data_pin}"
                        for candidate in ordered_stages
                        if candidate.data_net == stage.q_net
                    ),
                }
                external_q_loads[stage.q_net] = tuple(
                    sorted(
                        terminal.name
                        for terminal in q_net.loads
                        if terminal.name not in internal_muxes
                    )
                )

            abstractions.append(
                ShiftRegister(
                    name=name,
                    stages=tuple(ordered_stages),
                    serial_input_net=first.data_net,
                    enable_net=first.select_net,
                    clock_net=next(iter(clock_source_nets)),
                    clock_leaf_nets=tuple(sorted(clock_leaf_nets)),
                    reset_net=next(iter(reset_nets)),
                    parallel_output_nets=tuple(
                        stage.q_net for stage in ordered_stages
                    ),
                    external_q_loads=external_q_loads,
                    evidence=(
                        "exclusive point-to-point mux.X -> D wiring",
                        "exactly one self-feedback mux input per stage",
                        "single unbranched acyclic serial chain",
                        "uniform buffered clock source, reset, enable, and mux orientation",
                        "internal mux loads exactly match hold/shift wiring",
                    ),
                )
            )

        return ShiftRegisterAnalysis(abstractions, rejections)

    def to_dict(self) -> dict[str, object]:
        shift_analysis = self.strict_shift_registers()
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
            "abstractions": {
                "shift_registers": [
                    {
                        "name": shift_register.name,
                        "kind": "shift_register",
                        "width": shift_register.width,
                        "serial_input_net": shift_register.serial_input_net,
                        "enable_net": shift_register.enable_net,
                        "clock_net": shift_register.clock_net,
                        "clock_leaf_nets": list(shift_register.clock_leaf_nets),
                        "reset_net": shift_register.reset_net,
                        "parallel_output_nets": list(
                            shift_register.parallel_output_nets
                        ),
                        "member_instances": sorted(
                            shift_register.member_instances
                        ),
                        "stages": [
                            {
                                "index": index,
                                "flip_flop": stage.flip_flop,
                                "mux": stage.mux,
                                "q_net": stage.q_net,
                                "d_net": stage.d_net,
                            }
                            for index, stage in enumerate(
                                shift_register.stages
                            )
                        ],
                        "external_q_loads": {
                            net: list(loads)
                            for net, loads in shift_register.external_q_loads.items()
                        },
                        "evidence": list(shift_register.evidence),
                    }
                    for shift_register in shift_analysis.shift_registers
                ],
                "shift_register_rejections": [
                    {
                        "candidates": list(rejection.candidates),
                        "reasons": list(rejection.reasons),
                    }
                    for rejection in shift_analysis.rejections
                ],
            },
            "validation_issues": self.validation_issues(),
        }
