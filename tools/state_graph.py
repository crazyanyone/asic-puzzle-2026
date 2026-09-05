"""State-dependency graph and SCC helpers for sequential reverse engineering.

An edge A → B means flop A's Q appears in flop B's next-state (D) cone.
A multi-flop strongly connected component is a machine with feedback: each
bit's next value can depend on the others, i.e. a small FSM. A shift register
is a one-way chain, so each stage is its own SCC of size 1.
"""

from __future__ import annotations

from collections import Counter

from tools.netlist_ir import Design


TwoBitInfo = tuple[set[str], int, frozenset[str], bool]


def state_dependency_graph(design: Design) -> dict[str, set[str]]:
    """Map each flop to the flops whose Q can affect its next state.

    The stored set is the *incoming* side of the A → B picture: ``deps[B]``
    contains A whenever A's Q sits in B's D cone. Later sections use that
    incoming set directly.
    """
    deps: dict[str, set[str]] = {}
    for instance in design.instances.values():
        if not instance.sequential or "D" not in instance.pins:
            continue
        deps[instance.name] = set(
            design.backward_cone(instance.pins["D"].net).state_boundaries
        )
    return deps


def strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[list[str]]:
    """Tarjan SCCs. ``graph[node]`` is the set of outgoing neighbors."""
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    result: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph.get(node, ()):
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            result.append(component)

    for node in graph:
        if node not in indices:
            visit(node)
    return result


def classify_two_bit_sccs(
    design: Design,
    sccs: list[list[str]],
    hide: set[str] | frozenset[str] = frozenset(),
    thin_gate_limit: int = 30,
) -> tuple[list[TwoBitInfo], list[TwoBitInfo], list[TwoBitInfo], list[str]]:
    """Split 2-bit SCCs by combinational-cone size and collect singleton flops.

    Returns ``(thin, fat, reused, loners)``. Each 2-bit record is
    ``(pair, n_comb_cells, extra_state, has_mux)``, the same shape later
    sections already read.
    """
    thin: list[TwoBitInfo] = []
    fat: list[TwoBitInfo] = []
    reused: list[TwoBitInfo] = []
    for component in sccs:
        if len(component) != 2:
            continue
        pair = set(component)
        comb_cells: set[str] = set()
        extra: set[str] = set()
        has_mux = False
        for name in pair:
            cone = design.backward_cone(design.instances[name].pins["D"].net)
            extra |= cone.state_boundaries - pair
            for cell in cone.cells:
                instance = design.instances[cell]
                if instance.sequential:
                    continue
                comb_cells.add(cell)
                if instance.cell_type == "mux2":
                    has_mux = True
        info: TwoBitInfo = (pair, len(comb_cells), frozenset(extra), has_mux)
        if has_mux and len(comb_cells) < thin_gate_limit:
            reused.append(info)
        elif len(comb_cells) < thin_gate_limit:
            thin.append(info)
        else:
            fat.append(info)

    loners = [
        component[0]
        for component in sccs
        if len(component) == 1 and component[0] not in hide
    ]
    return thin, fat, reused, loners


def print_scc_inventory(
    design: Design,
    sccs: list[list[str]],
    hide: set[str] | frozenset[str] = frozenset(),
) -> None:
    print("SCC size histogram:", dict(sorted(Counter(map(len, sccs)).items())))
    print()
    print("multi-bit SCCs (shift_I hidden):")
    grouped: dict[tuple[int, tuple[tuple[str, int], ...]], list[str]] = {}
    for component in sccs:
        if len(component) == 1 or set(component) <= hide:
            continue
        types = tuple(
            sorted(
                Counter(
                    design.instances[name].cell_type for name in component
                ).items()
            )
        )
        grouped.setdefault((len(component), types), []).append(sorted(component)[0])
    for (size, types), examples in sorted(
        grouped.items(), key=lambda item: (-item[0][0], item[1][0])
    ):
        type_dict = dict(types)
        print(
            f"  {len(examples):2} × size {size:2}  {type_dict}  "
            f"e.g. {examples[0]}"
        )


def print_two_bit_split(
    design: Design,
    thin: list[TwoBitInfo],
    fat: list[TwoBitInfo],
    reused: list[TwoBitInfo],
    loners: list[str],
) -> None:
    print(f"tiny 2-bit SCCs (a handful of gates):     {len(thin)}")
    print(f"tiny 2-bit SCC that also has a mux:       {len(reused)}")
    print(f"fat  2-bit SCCs (~150 gates each):        {len(fat)}")
    if fat:
        fat_comb: list[set[str]] = []
        for pair, *_ in fat:
            cells: set[str] = set()
            for name in pair:
                cells |= {
                    cell
                    for cell in design.backward_cone(
                        design.instances[name].pins["D"].net
                    ).cells
                    if not design.instances[cell].sequential
                }
            fat_comb.append(cells)
        shared = set.intersection(*fat_comb)
        union = set.union(*fat_comb)
        print(
            f"  shared combinational cells among fat ones: "
            f"{len(shared)} / {len(union)}"
        )

    print()
    print("the mux-y pair:", sorted(reused[0][0]) if reused else None)
    print(f"singletons outside shift_I: {len(loners)}")
    print("  ", ", ".join(sorted(loners)))
    print()
    print(
        "and success is literally this flop's Q:",
        [terminal.name for terminal in design.resolve_net("success").drivers],
    )
