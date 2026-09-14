"""Frontend-neutral plot specifications and numeric sampling."""

from __future__ import annotations

from dataclasses import dataclass
import math

from ..terms import Binary, FunctionCall, Number, Symbol, SymbolKind, Term, Unary
from ..elaboration import scalar_rank


@dataclass(frozen=True, slots=True)
class PlotSeries:
    label: str
    x: tuple[float, ...]
    y: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class PlotSpec:
    title: str
    x_label: str
    y_label: str
    series: tuple[PlotSeries, ...]


_UNARY_FUNCTIONS = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "exp": math.exp,
    "log": math.log,
    "sqrt": math.sqrt,
    "abs": abs,
}


def _numeric_graph(term: Term) -> list[Term]:
    """Validate and order each DAG node once; unsupported calls are never sampled."""
    ordered, seen, stack = [], set(), [(term, False)]
    while stack:
        node, ready = stack.pop()
        if node in seen:
            continue
        if ready:
            seen.add(node)
            ordered.append(node)
            if len(ordered) > 10_000:
                raise ValueError('Plot expression exceeds 10000 nodes')
            continue
        match node:
            case Number():
                children = ()
            case Symbol(annotation=annotation):
                if annotation is not None and scalar_rank(annotation) not in (0, 1, 2, 3):
                    raise ValueError('Plots require real scalar symbols')
                children = ()
            case Unary(op=op) if op in ('+', '-'):
                children = node.children
            case Binary(op=op) if op in ('+', '-', '*', '/', '^'):
                children = node.children
            case FunctionCall(callee=Symbol(kind=SymbolKind.BUILTIN, name=name), arguments=(argument,)) if name in _UNARY_FUNCTIONS:
                children = (argument,)
            case _:
                raise ValueError(f'Expression {type(node).__name__} is not numerically plottable yet')
        stack.append((node, True))
        stack.extend((child, False) for child in reversed(children))
    return ordered


def _evaluate_graph(ordered: list[Term], bindings: dict[str, float]) -> float:
    values = {}
    for node in ordered:
        match node:
            case Number(value=value):
                result = float(value)
            case Symbol(name=name):
                if name not in bindings:
                    raise ValueError(f'No numeric value was supplied for symbol {name!r}')
                result = float(bindings[name])
            case Unary(op=op, operand=operand):
                result = -values[operand] if op == '-' else values[operand]
            case Binary(op=op, left=left, right=right):
                a, b = values[left], values[right]
                if op == '+': result = a+b
                elif op == '-': result = a-b
                elif op == '*': result = a*b
                elif op == '/': result = a/b
                else:
                    if a == 0 and b <= 0:
                        raise ValueError('Zero to a nonpositive power is undefined')
                    result = math.pow(a, b)
            case FunctionCall(callee=Symbol(name=name), arguments=(argument,)):
                result = float(_UNARY_FUNCTIONS[name](values[argument]))
        values[node] = result
    return values[ordered[-1]]


def evaluate_numeric(term: Term, bindings: dict[str, float]) -> float:
    """Evaluate real scalar IR by identity and in bounded DAG order, without eval."""
    return _evaluate_graph(_numeric_graph(term), bindings)


def sample_expression(term: Term, variable: str, start: float, end: float,
                      *, points: int = 600, label: str = "f") -> PlotSpec:
    if type(points) is not int or not 2 <= points <= 10_000:
        raise ValueError("points must be an integer between 2 and 10000")
    if not math.isfinite(start) or not math.isfinite(end) or start >= end:
        raise ValueError("Plot range must contain two finite numbers with start < end")
    ordered = _numeric_graph(term)
    symbols = {node for node in ordered if isinstance(node, Symbol)}
    if any(node.name != variable for node in symbols):
        raise ValueError('Supply values for all parameters before plotting')
    if len(symbols) > 1:
        raise ValueError('Plot coordinate refers to distinct symbols with the same name')
    xs: list[float] = []
    ys: list[float] = []
    for i in range(points):
        fraction = i / (points - 1)
        x = start*(1-fraction) + end*fraction
        xs.append(x)
        try:
            y = _evaluate_graph(ordered, {variable: x})
            ys.append(y if math.isfinite(y) else math.nan)
        except (ArithmeticError, OverflowError, ValueError):
            ys.append(math.nan)
    return PlotSpec(
        title=label,
        x_label=variable,
        y_label=label,
        series=(PlotSeries(label, tuple(xs), tuple(ys)),),
    )
