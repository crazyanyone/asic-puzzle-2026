"""Concrete gate evaluation and one-active-clock-edge transition semantics."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from typing import Mapping

from tools.logic import evaluate_expression, parse_expression
from tools.netlist_ir import Design, Instance


class EvaluationError(ValueError):
    pass


def _condition_is_true(
    expression: str | None,
    instance: Instance,
    evaluator: CircuitEvaluator,
) -> bool:
    if expression is None:
        return False
    pins = {
        symbol: evaluator.value(instance.pins[symbol].net)
        for symbol in parse_expression(expression).symbols
    }
    return evaluate_expression(expression, pins)


class CircuitEvaluator:
    """Evaluate a combinational cone from fixed input and current-state nets.

    Results are memoized within one evaluator. A sequential Q is a boundary:
    its value must be supplied rather than recursively traversing the flip-flop.
    """

    def __init__(self, design: Design, known_values: Mapping[str, bool]) -> None:
        self.design = design
        self.values: dict[str, bool] = {}
        self.pending: set[str] = set()
        for name, value in known_values.items():
            self.values[design.resolve_net(name).name] = bool(value)
        for alias in ("VGND", "VSS", "VNB"):
            if alias in design.ports:
                self.values[design.ports[alias].name] = False
        for alias in ("VPWR", "VDD", "VPB"):
            if alias in design.ports:
                self.values[design.ports[alias].name] = True

    def value(self, requested_net: str) -> bool:
        net_name = self.design.resolve_net(requested_net).name
        if net_name in self.values:
            return self.values[net_name]
        if net_name in self.pending:
            raise EvaluationError(f"Combinational cycle reaches {net_name}")

        net = self.design.nets[net_name]
        if len(net.drivers) != 1:
            drivers = ", ".join(driver.name for driver in net.drivers) or "none"
            raise EvaluationError(
                f"Cannot evaluate {net_name}: expected one driver, found {drivers}"
            )
        driver = net.drivers[0]
        instance = self.design.instances[driver.instance]
        if instance.sequential:
            raise EvaluationError(
                f"Current-state value required for {driver.name} on {net_name}"
            )

        expression = instance.model.output_expression(driver.pin)
        self.pending.add(net_name)
        try:
            pin_values = {
                symbol: self.value(instance.pins[symbol].net)
                for symbol in parse_expression(expression).symbols
            }
            result = evaluate_expression(expression, pin_values)
        finally:
            self.pending.remove(net_name)
        self.values[net_name] = result
        return result


@dataclass(frozen=True)
class TransitionResult:
    current_state: dict[str, bool]
    next_state: dict[str, bool]
    outputs_before_edge: dict[str, bool]
    outputs_after_edge: dict[str, bool]


def state_net_by_instance(design: Design) -> dict[str, str]:
    return {
        instance.name: instance.pins["Q"].net
        for instance in design.instances.values()
        if instance.sequential and "Q" in instance.pins
    }


def normalize_values(design: Design, values: Mapping[str, bool]) -> dict[str, bool]:
    """Resolve aliases, terminals, and sequential instance names to net ids."""
    state_nets = state_net_by_instance(design)
    normalized: dict[str, bool] = {}
    for name, value in values.items():
        net_name = state_nets.get(name)
        if net_name is None:
            net_name = design.resolve_net(name).name
        normalized[net_name] = bool(value)
    return normalized


def one_clock_transition(
    design: Design,
    current_state: Mapping[str, bool],
    inputs: Mapping[str, bool],
    output_names: Iterable[str] | None = None,
) -> TransitionResult:
    """Compute all DFF next states for one active clock edge.

    The clock waveform itself is abstracted away: this function means “an
    active edge occurs now.” Asynchronous clear/preset conditions take priority,
    matching the official Liberty state records. By default all top-level
    outputs are evaluated before and after the edge; pass an empty iterable to
    step state without evaluating outputs, or names to inspect only those nets.
    """
    state = normalize_values(design, current_state)
    input_values = normalize_values(design, inputs)
    known = {**input_values, **state}
    evaluator = CircuitEvaluator(design, known)
    next_state: dict[str, bool] = {}

    for instance in design.instances.values():
        if not instance.sequential or "Q" not in instance.pins:
            continue
        q_net = instance.pins["Q"].net
        if _condition_is_true(instance.model.clear, instance, evaluator):
            next_state[q_net] = False
        elif _condition_is_true(instance.model.preset, instance, evaluator):
            next_state[q_net] = True
        elif instance.model.next_state is not None:
            expression = instance.model.next_state
            pin_values = {
                symbol: evaluator.value(instance.pins[symbol].net)
                for symbol in parse_expression(expression).symbols
            }
            next_state[q_net] = evaluate_expression(expression, pin_values)
        else:
            raise EvaluationError(f"No next-state function for {instance.name}")

    if output_names is None:
        requested_outputs = [
            alias
            for alias, net in design.ports.items()
            if net.inferred_direction == "output"
        ]
    else:
        requested_outputs = list(output_names)
    output_nets = {
        name: design.resolve_net(name).name for name in requested_outputs
    }
    before = {alias: evaluator.value(net) for alias, net in output_nets.items()}
    after_evaluator = CircuitEvaluator(design, {**input_values, **next_state})
    after = {
        alias: after_evaluator.value(net) for alias, net in output_nets.items()
    }
    return TransitionResult(dict(state), next_state, before, after)
