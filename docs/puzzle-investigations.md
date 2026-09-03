# Focused puzzle investigations

These findings use only `puzzle.gds` and its extracted connectivity.

## The 12-bit serial register

The permissive motif pass found one unbranched 12-stage mux/DFF chain from `I`.
The original strict pass rejected the group for exactly one reason: its DFFs
use four clock leaf nets instead of one literal net.

All four leaves trace through clock buffers to the same source:

```text
n0121 <- U205_clkbuf_8 <- n0050 <- U193_clkbuf_16 <- clk
n0327 <- U371_clkbuf_8 <- n0050 <- U193_clkbuf_16 <- clk
n0338 <- U368_clkbuf_8 <- n0050 <- U193_clkbuf_16 <- clk
n0177 <- U413_clkbuf_8 <- n0050 <- U193_clkbuf_16 <- clk
```

Clock-tree buffering is not a functional mismatch. The strict recognizer now
compares the source reached through transparent buffers and records the four
physical leaves separately. It therefore verifies `shift_I: ShiftRegister[12]`.
There were no missing serial-data or extra internal connections; the old test
was simply comparing the four leaf-net names literally.

The verified stage order is:

| stage | flip-flop | mux | Q net |
|---:|---|---|---|
| 0 | `U361_dfrtp_2` | `U383_mux2_1` | `n0342` |
| 1 | `U390_dfrtp_2` | `U365_mux2_1` | `n0351` |
| 2 | `U370_dfrtp_2` | `U364_mux2_1` | `n0350` |
| 3 | `U388_dfrtp_2` | `U367_mux2_1` | `n0355` |
| 4 | `U362_dfrtp_2` | `U392_mux2_1` | `n0348` |
| 5 | `U384_dfrtp_2` | `U372_mux2_1` | `n0361` |
| 6 | `U359_dfrtp_2` | `U377_mux2_1` | `n0340` |
| 7 | `U395_dfrtp_2` | `U378_mux2_1` | `n0370` |
| 8 | `U385_dfrtp_2` | `U394_mux2_1` | `n0376` |
| 9 | `U386_dfrtp_2` | `U391_mux2_1` | `n0364` |
| 10 | `U382_dfrtp_2` | `U387_mux2_1` | `n0366` |
| 11 | `U380_dfrtp_2` | `U389_mux2_1` | `n0344` |

Inspect the primitive graph and its clock tree with:

```bash
.venv/bin/python -m tools.analyze_netlist \
  artifacts/netlists/puzzle.json shift-chains \
  --dot docs/diagrams/puzzle-shift-chain.dot
dot -Tsvg docs/diagrams/puzzle-shift-chain.dot \
  -o docs/diagrams/puzzle-shift-chain.svg
```

Generate the collapsed block view with:

```bash
.venv/bin/python -m tools.analyze_netlist \
  artifacts/netlists/puzzle.json shift-registers \
  --dot docs/diagrams/puzzle-shift-register-block.dot
dot -Tsvg docs/diagrams/puzzle-shift-register-block.dot \
  -o docs/diagrams/puzzle-shift-register-block.svg
```

## The undriven `n0550` net

This is not just a missing entry in the typed graph. Rechecking the GDS shows a
real routed component spanning `li1`, `met1`, and `met2`, with bounds roughly
`x=174.895..179.330`, `y=90.450..91.875` micrometers. Its only pin labels are:

```text
U516_a31oi_2.A1
U521_a311o_2.A1
```

There is no top-level label, standard-cell output label, power connection, or
unrecognized instance label on that conductor component. Electrically, it is a
floating input shared by two gates.

It is not algebraically irrelevant for arbitrary states. Treating `n0550` as a
free Boolean value produces counterexamples where it changes intermediate net
`n0526` and top-level outputs `O[1]` and `O[4]`. It has no structural path to
`success`, so it cannot affect whether `success` asserts.

Reproduce those checks with:

```bash
.venv/bin/python -m tools.check_influence \
  artifacts/netlists/puzzle.json n0550 n0526
.venv/bin/python -m tools.check_influence \
  artifacts/netlists/puzzle.json n0550 'O[1]'
.venv/bin/python -m tools.check_influence \
  artifacts/netlists/puzzle.json n0550 success
```

Generate and render the logic neighborhood with:

```bash
.venv/bin/python -m tools.analyze_netlist \
  artifacts/netlists/puzzle.json net n0550 --depth 1 \
  --dot docs/diagrams/n0550-neighborhood.dot
dot -Tsvg docs/diagrams/n0550-neighborhood.dot \
  -o docs/diagrams/n0550-neighborhood.svg
```

To inspect the physical route in KLayout, open `puzzle.gds`, navigate to the
bounds above, and show layers `li1`, `met1`, `met2`, `mcon`, `via`, and `via2`.

“Prove the gates cancel its influence” means compare the target once with the
floating value forced to 0 and once forced to 1, for every assignment of the
other cone inputs. If the two target values are always equal, the variable is
absent from the target's effective Boolean function. Here that proof succeeds
for `success` but fails for `O[1]`, `O[4]`, and `n0526`.

The counterexample states found for `O[1]` and `O[4]` are arbitrary states. A
separate reachability analysis would be needed to decide whether any such state
can actually occur after reset. That distinction—arbitrary-state influence
versus reachable-state influence—is important in sequential reverse
engineering.
