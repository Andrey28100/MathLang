"""Typed intermediate representation produced by elaboration.

The symbolic kernel deliberately keeps :class:`Term` syntax-oriented and free of
implicit coercion nodes.  Elaboration builds this parallel immutable graph where
all known node types are attached and safe mathematical embeddings are explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .renderer import format_term
from .terms import Term, Type


@dataclass(frozen=True, slots=True)
class TypedTerm:
    """A symbolic term annotated with its elaborated mathematical type."""

    term: Term
    type: Type | None
    children: tuple["TypedValue", ...] = ()


@dataclass(frozen=True, slots=True)
class Embed:
    """An implicit, safe mathematical embedding inserted by elaboration."""

    value: "TypedValue"
    source_type: Type
    target_type: Type

    @property
    def type(self) -> Type:
        return self.target_type

    @property
    def term(self) -> Term:
        return self.value.term

    @property
    def children(self) -> tuple["TypedValue", ...]:
        return (self.value,)


TypedValue: TypeAlias = TypedTerm | Embed


def _name(value: TypedValue) -> str:
    if isinstance(value, Embed):
        return f"Embed<{value.source_type}, {value.target_type}>"
    return type(value.term).__name__


def format_typed_ir(value: TypedValue, *, max_length: int = 100_000) -> str:
    """Render a compact tree intended for diagnostics and IDE inspection."""

    lines: list[str] = []
    length = 0
    stack: list[tuple[TypedValue, str, bool]] = [(value, "", True)]
    while stack:
        node, prefix, last = stack.pop()
        branch = "└─ " if last else "├─ "
        if isinstance(node, Embed):
            text = f"{_name(node)} : {node.target_type}"
            children = node.children
        else:
            type_text = "?" if node.type is None else str(node.type)
            try:
                source = format_term(node.term, max_length=max_length)
            except (TypeError, ValueError):
                source = type(node.term).__name__
            if len(source) > 100:
                source = source[:97] + "..."
            text = f"{_name(node)} : {type_text}  [{source}]"
            children = node.children
        line = prefix + branch + text
        length += len(line) + bool(lines)
        if length > max_length:
            raise ValueError(f"Typed IR is too large to display (limit {max_length} characters)")
        lines.append(line)
        child_prefix = prefix + ("   " if last else "│  ")
        for index in range(len(children) - 1, -1, -1):
            stack.append((children[index], child_prefix, index == len(children) - 1))
    return "\n".join(lines)
