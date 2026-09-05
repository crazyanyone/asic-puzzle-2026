"""Read scalar VCD inputs at rising clock edges."""

from __future__ import annotations

from pathlib import Path


def inputs_at_rising_clock_edge(
    path: str | Path,
    *,
    clock: str = "clk",
) -> list[dict[str, int]]:
    """Snapshot 1-bit signals at each rising edge of ``clock``.

    Understands the compact VCD this puzzle ships: ``$var`` declarations
    plus ``0X`` / ``1X`` value changes. Wider buses are ignored.
    """
    names: dict[str, str] = {}
    for raw_line in Path(path).read_text().splitlines():
        parts = raw_line.split()
        if (
            len(parts) >= 5
            and parts[0] == "$var"
            and parts[2] == "1"
        ):
            names[parts[3]] = parts[4]
    if clock not in names.values():
        raise ValueError(f"no 1-bit signal named {clock!r}")

    values = {symbol: 0 for symbol in names}
    clock_id = next(symbol for symbol, name in names.items() if name == clock)
    samples: list[dict[str, int]] = []
    time = 0
    for raw_line in Path(path).read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("#") and line[1:].isdigit():
            time = int(line[1:])
            continue
        if len(line) == 2 and line[0] in "01" and line[1] in values:
            symbol = line[1]
            old = values[symbol]
            values[symbol] = int(line[0])
            if symbol == clock_id and old == 0 and values[symbol] == 1:
                samples.append(
                    {"time": time, **{names[s]: values[s] for s in names}}
                )
    return samples
