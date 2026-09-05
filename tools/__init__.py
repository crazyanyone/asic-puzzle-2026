"""GDS reverse-engineering toolkit.

Layout:

- **helpers** (``tools.helpers``, ``tools.logic``, ``tools.state_graph``):
  bit strings, HTML grids, Boolean parsing, SCC / dependency graphs.
- **simulators** (``tools.circuit_eval``, ``tools.play``):
  evaluate gates and tick flip-flops.
- **runners** (``tools.extract_netlist``, ``tools.analyze_netlist``,
  ``tools.inspect_gds``, ``tools.simulate_netlist``, ``tools.check_influence``):
  command-line entry points.
- **ir** (``tools.netlist_ir``): typed netlist graph.
"""
