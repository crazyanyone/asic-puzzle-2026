"""Tiny evaluator for the Boolean-expression subset used by Liberty files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping


TOKEN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*|[01!&|^+*()])")


class LogicExpressionError(ValueError):
    pass


@dataclass(frozen=True)
class Expression:
    operation: str
    arguments: tuple["Expression", ...] = ()
    symbol: str | None = None

    def evaluate(self, values: Mapping[str, bool]) -> bool:
        if self.operation == "symbol":
            if self.symbol not in values:
                raise KeyError(f"No value supplied for {self.symbol}")
            return bool(values[self.symbol])
        if self.operation == "constant":
            return self.symbol == "1"
        if self.operation == "not":
            return not self.arguments[0].evaluate(values)
        left = self.arguments[0].evaluate(values)
        right = self.arguments[1].evaluate(values)
        if self.operation == "and":
            return left and right
        if self.operation == "xor":
            return left != right
        if self.operation == "or":
            return left or right
        raise LogicExpressionError(f"Unknown operation {self.operation}")

    @property
    def symbols(self) -> frozenset[str]:
        if self.operation == "symbol":
            return frozenset((self.symbol,))
        return frozenset().union(*(argument.symbols for argument in self.arguments))


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = self._tokenize(text)
        self.index = 0

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens: list[str] = []
        position = 0
        while position < len(text):
            match = TOKEN.match(text, position)
            if match is None:
                raise LogicExpressionError(
                    f"Unsupported Liberty expression near {text[position:]!r}"
                )
            tokens.append(match.group(1))
            position = match.end()
        return tokens

    def peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise LogicExpressionError(
                f"Expected {expected or 'token'} in {self.text!r}, got {token!r}"
            )
        self.index += 1
        return token

    def parse(self) -> Expression:
        expression = self.parse_or()
        if self.peek() is not None:
            raise LogicExpressionError(
                f"Unexpected token {self.peek()!r} in {self.text!r}"
            )
        return expression

    def parse_or(self) -> Expression:
        result = self.parse_xor()
        while self.peek() in {"|", "+"}:
            self.take()
            result = Expression("or", (result, self.parse_xor()))
        return result

    def parse_xor(self) -> Expression:
        result = self.parse_and()
        while self.peek() == "^":
            self.take()
            result = Expression("xor", (result, self.parse_and()))
        return result

    def parse_and(self) -> Expression:
        result = self.parse_unary()
        while self.peek() in {"&", "*"}:
            self.take()
            result = Expression("and", (result, self.parse_unary()))
        return result

    def parse_unary(self) -> Expression:
        if self.peek() == "!":
            self.take("!")
            return Expression("not", (self.parse_unary(),))
        if self.peek() == "(":
            self.take("(")
            result = self.parse_or()
            self.take(")")
            return result
        token = self.take()
        if token in {"0", "1"}:
            return Expression("constant", symbol=token)
        if not token[0].isalpha() and token[0] != "_":
            raise LogicExpressionError(f"Expected symbol in {self.text!r}")
        return Expression("symbol", symbol=token)


@lru_cache(maxsize=None)
def parse_expression(text: str) -> Expression:
    return _Parser(text).parse()


def evaluate_expression(text: str, values: Mapping[str, bool]) -> bool:
    return parse_expression(text).evaluate(values)
