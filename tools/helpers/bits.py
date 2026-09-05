"""Tiny bit-string constructors used by simulation and display."""

from __future__ import annotations

from collections.abc import Sequence


def as_bits(bits: str | Sequence[object]) -> list[bool]:
    """A ``'0101…'`` string, or a sequence of 0/1/bool, as a list of bool."""
    if isinstance(bits, str):
        return [ch == "1" for ch in bits]
    return [bool(b) for b in bits]


def bits_at(*positions: int, length: int = 121) -> str:
    """Build a bit string with ``1`` at each given cell index."""
    chars = ["0"] * length
    for position in positions:
        chars[position] = "1"
    return "".join(chars)
