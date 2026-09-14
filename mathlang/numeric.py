"""Explicit high-precision numerical evaluation for closed real expressions.

MathLang keeps ordinary evaluation exact and symbolic.  This module implements
``numeric`` as an opt-in terminal transformation: it evaluates a closed scalar
expression with ``decimal.Decimal`` and returns an ``ApproxNumber`` so the
result can never be confused with an exact source decimal literal.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, getcontext, localcontext
from fractions import Fraction

from .normalization import Limits, NormalizationError
from .terms import ApproxNumber, Binary, FunctionCall, Number, Symbol, SymbolKind, Term, TermFactory, Unary


DEFAULT_DIGITS = 20
MAX_DIGITS = 500
_GUARD_DIGITS = 12


class NumericError(NormalizationError):
    """Raised when ``numeric`` cannot evaluate an expression as a real number."""


def _decimal_fraction(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def _pi() -> Decimal:
    """Compute pi using the quadratically convergent Gauss-Legendre method."""
    one = Decimal(1)
    two = Decimal(2)
    four = Decimal(4)
    a = one
    b = one / two.sqrt()
    t = one / four
    p = one
    # Each iteration roughly doubles the number of correct digits.  Running
    # until a and b stop changing naturally adapts to the active Decimal context.
    for _ in range(32):
        next_a = (a + b) / two
        b = (a * b).sqrt()
        delta = a - next_a
        t -= p * delta * delta
        a = next_a
        p *= two
        if a == b:
            break
    return (a + b) * (a + b) / (four * t)


def _reduce_angle(value: Decimal) -> Decimal:
    pi = _pi()
    tau = pi * 2
    value %= tau
    if value > pi:
        value -= tau
    elif value < -pi:
        value += tau
    return value


def _sin(value: Decimal) -> Decimal:
    x = _reduce_angle(value)
    term = x
    total = x
    n = 1
    epsilon = Decimal(1).scaleb(-(max(8, getcontext().prec) - 4))
    while abs(term) > epsilon:
        term *= -(x * x) / Decimal((2 * n) * (2 * n + 1))
        total += term
        n += 1
        if n > 10_000:
            raise NumericError("numeric(sin(...)) did not converge within the computation limit")
    return +total


def _cos(value: Decimal) -> Decimal:
    x = _reduce_angle(value)
    term = Decimal(1)
    total = term
    n = 1
    epsilon = Decimal(1).scaleb(-(max(8, getcontext().prec) - 4))
    while abs(term) > epsilon:
        term *= -(x * x) / Decimal((2 * n - 1) * (2 * n))
        total += term
        n += 1
        if n > 10_000:
            raise NumericError("numeric(cos(...)) did not converge within the computation limit")
    return +total


def _format(value: Decimal, digits: int) -> str:
    if not value.is_finite():
        raise NumericError("numeric produced a non-finite value")
    if value == 0:
        return "0"
    # 'g' keeps significant digits and switches to scientific notation only
    # when that is materially shorter/readable.
    text = format(value, f".{digits}g")
    if "E" in text:
        text = text.replace("E", "e")
    return text


def _digits(term: Term | None) -> int:
    if term is None:
        return DEFAULT_DIGITS
    if not isinstance(term, Number) or term.value.denominator != 1:
        raise NumericError("numeric precision must be an integer number of decimal digits")
    digits = int(term.value)
    if not 1 <= digits <= MAX_DIGITS:
        raise NumericError(f"numeric precision must be between 1 and {MAX_DIGITS} digits")
    return digits


def evaluate_numeric(factory: TermFactory, expression: Term, precision: Term | None = None,
                     *, limits: Limits | None = None) -> ApproxNumber:
    """Numerically evaluate a closed real expression.

    Supported operations are ``+ - * / ^`` and the scalar builtins
    ``sin``, ``cos``, ``tan``, ``exp``, ``log``, ``sqrt`` and ``abs``.
    Rational powers are evaluated over the reals, so a negative base with a
    non-integer exponent is rejected rather than silently entering Complex.
    """

    limits = Limits() if limits is None else limits
    digits = _digits(precision)
    memo: dict[Term, Decimal] = {}
    steps = 0

    with localcontext() as context:
        context.prec = digits + _GUARD_DIGITS
        stack = [(expression, False)]
        while stack:
            node, ready = stack.pop()
            if node in memo:
                continue
            steps += 1
            if steps > limits.max_steps:
                raise NumericError("numeric computation step limit exceeded")
            if not ready:
                stack.append((node, True))
                children = node.arguments if isinstance(node, FunctionCall) else node.children
                stack.extend((child, False) for child in reversed(children))
                continue
            try:
                if isinstance(node, Number):
                    value = _decimal_fraction(node.value)
                elif isinstance(node, ApproxNumber):
                    value = Decimal(node.text)
                elif isinstance(node, Unary):
                    operand = memo[node.operand]
                    value = operand if node.op == "+" else -operand
                elif isinstance(node, Binary):
                    left, right = memo[node.left], memo[node.right]
                    if node.op == "+":
                        value = left + right
                    elif node.op == "-":
                        value = left - right
                    elif node.op == "*":
                        value = left * right
                    elif node.op == "/":
                        if right == 0:
                            raise NumericError("Division by zero")
                        value = left / right
                    elif node.op == "^":
                        exponent = node.right.value if isinstance(node.right, Number) else None
                        if exponent is not None and exponent.denominator == 1:
                            if left == 0 and exponent <= 0:
                                raise NumericError("0^0 is undefined" if exponent == 0 else "Division by zero")
                            value = left ** int(exponent)
                        else:
                            if left <= 0:
                                raise NumericError("numeric currently supports fractional powers only for positive real bases")
                            value = (right * left.ln()).exp()
                    else:
                        raise NumericError(f"numeric does not support operator {node.op!r}")
                elif isinstance(node, FunctionCall):
                    if (not isinstance(node.callee, Symbol) or node.callee.kind != SymbolKind.BUILTIN
                            or len(node.arguments) != 1):
                        raise NumericError("numeric can evaluate only closed scalar builtin calls")
                    name = node.callee.name
                    arg = memo[node.arguments[0]]
                    if name == "sqrt":
                        if arg < 0:
                            raise NumericError("sqrt of a negative real value is outside numeric's real domain")
                        value = arg.sqrt()
                    elif name == "exp":
                        value = arg.exp()
                    elif name == "log":
                        if arg <= 0:
                            raise NumericError("log requires a positive real value")
                        value = arg.ln()
                    elif name == "abs":
                        value = abs(arg)
                    elif name == "sin":
                        value = _sin(arg)
                    elif name == "cos":
                        value = _cos(arg)
                    elif name == "tan":
                        cosine = _cos(arg)
                        if cosine == 0:
                            raise NumericError("tan is undefined at this point")
                        value = _sin(arg) / cosine
                    else:
                        raise NumericError(f"numeric does not support builtin {name!r}")
                elif isinstance(node, Symbol):
                    raise NumericError(
                        f"numeric requires a closed real expression; unresolved symbol {node.name!r} remains"
                    )
                else:
                    raise NumericError(
                        f"numeric expects a scalar expression, got {type(node).__name__}"
                    )
            except (InvalidOperation, OverflowError, ZeroDivisionError) as error:
                raise NumericError(f"numeric evaluation failed: {error}") from None
            memo[node] = +value

        return factory.approximate(_format(memo[expression], digits), digits)
