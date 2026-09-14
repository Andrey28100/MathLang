"""Exact analytic functions on certified classes of algebra elements.

The nilpotent path reuses the scalar calculus coefficient recurrences. It only
evaluates their polynomial after proving that the omitted powers are zero;
ordinary truncated Taylor series never become equalities through this module.
The quadratic path sums the even and odd coefficients using a checked relation
for the direction, independently of any algebra or generator name.
"""

from fractions import Fraction

from .analysis import _Analysis
from .normalization import NormalizationError
from .terms import Number, Predicate, Term, TruthValue, Type, builtin_symbol


ENTIRE_FUNCTIONS = frozenset({"exp", "sin", "cos"})
SUPPORTED_FUNCTIONS = ENTIRE_FUNCTIONS | {"log", "sqrt"}


def supports_function(name: str, scalar_domain: Type) -> bool:
    """Signature availability, distinct from support for a particular element."""
    if scalar_domain.identity is not None or scalar_domain.arguments:
        return False
    return ((scalar_domain.name == "Real" and name in SUPPORTED_FUNCTIONS)
            or (scalar_domain.name == "Complex" and name in ENTIRE_FUNCTIONS))


class _LiftAnalysis(_Analysis):
    """Scalar recurrences with the caller's proved regular-domain conditions."""

    def __init__(self, computation):
        super().__init__(computation.f, computation.limits)
        self.query = getattr(computation, "query", None)
        self.scalar.query = self.query

    def positive(self, term):
        return (super().positive(term)
                or (self.query is not None
                    and self.query(self.f.comparison(">", term, self.zero)) is TruthValue.TRUE))

    def nonzero(self, term):
        return (super().nonzero(term)
                or (self.query is not None
                    and self.query(self.f.comparison("!=", term, self.zero)) is TruthValue.TRUE))


def _split(coordinates, computation):
    scalar = coordinates.get((), computation.f.number(0))
    remainder = {word: value for word, value in coordinates.items() if word}
    return scalar, remainder


def _nilpotent_powers(remainder, computation):
    """Return 1,n,...,n^(m-1) only after a normalized product certifies n^m=0."""
    powers = [{(): computation.f.number(1)}]
    current = remainder
    for degree in range(1, computation.limits.max_calculus_order + 1):
        if not current:
            return powers
        if degree < computation.limits.max_calculus_order:
            powers.append(current)
            current = computation.multiply(current, remainder)
    return None


def _quadratic_direction(remainder, computation):
    """Recognize t*w with a checked rational scalar relation w*w=d != 0."""
    if len(remainder) != 1:
        return None
    word, coefficient = next(iter(remainder.items()))
    direction = {word: computation.f.number(1)}
    square = computation.multiply(direction, direction)
    value = square.get(())
    if set(square) == {()} and isinstance(value, Number) and value.value:
        return word, coefficient, value.value
    return None


def function_domain(name: str, coordinates, computation) -> Predicate | None:
    """Additional domain condition; the caller must also check input domains.

    None means this backend cannot characterize the domain. Entire functions
    exist on every finite-dimensional real/complex algebra, even when their
    exact reduction is unsupported. For log/sqrt only the regular nilpotent
    real branch is certified here; other branches remain unknown.
    """
    if not supports_function(name, computation.algebra.scalar_domain):
        return None
    center, remainder = _split(coordinates, computation)
    if name in ENTIRE_FUNCTIONS:
        if (computation.algebra.basis is not None or not remainder
                or _quadratic_direction(remainder, computation) is not None
                or _nilpotent_powers(remainder, computation) is not None):
            return computation.f.truth(TruthValue.TRUE)
        return None
    if not remainder:
        return computation.f.comparison(">=" if name == "sqrt" else ">", center,
                                        computation.f.number(0))
    if _nilpotent_powers(remainder, computation) is not None:
        return computation.f.comparison(">", center, computation.f.number(0))
    return None


def _quadratic_function(name, center, shape, computation):
    word, coefficient, square = shape
    scalar = _LiftAnalysis(computation)
    root = scalar.call("sqrt", computation.f.number(abs(square)))
    argument = scalar.mul(root, coefficient)
    if (name == "exp" and square < 0) or (name != "exp" and square > 0):
        even = scalar.call("cos", argument)
        odd = scalar.div(scalar.call("sin", argument), root)
    else:
        positive = scalar.call("exp", argument)
        negative = scalar.call("exp", scalar.neg(argument))
        even = scalar.mul(computation.f.number(Fraction(1, 2)), scalar.add(positive, negative))
        odd = scalar.div(scalar.sub(positive, negative), scalar.mul(computation.f.number(2), root))
    if name == "exp":
        factor = scalar.call("exp", center)
        even, odd = scalar.mul(factor, even), scalar.mul(factor, odd)
    elif name == "sin":
        even, odd = scalar.mul(scalar.call("sin", center), even), scalar.mul(scalar.call("cos", center), odd)
    else:
        even, odd = scalar.mul(scalar.call("cos", center), even), scalar.neg(scalar.mul(scalar.call("sin", center), odd))
    result = {}
    computation.add(result, (), even)
    computation.add(result, word, odd)
    return result


def lift_function(name: str, coordinates, computation) -> dict[tuple[int, ...], Term]:
    """Evaluate a builtin exactly using normalized coordinate arithmetic.

    computation provides algebra, f, limits, coefficient, multiply, add and an
    optional query(Predicate)->TruthValue callback. Unsupported classes raise
    an explicit error instead of returning an approximation or recurring into
    the original algebra-valued call.
    """
    if not supports_function(name, computation.algebra.scalar_domain):
        raise NormalizationError(f"No analytic algebra signature for {name!r} over {computation.algebra.scalar_domain}")
    center, remainder = _split(coordinates, computation)
    if not remainder:
        result = {}
        computation.add(result, (), computation.f.call(builtin_symbol(name), (center,)))
        return result
    if name in ENTIRE_FUNCTIONS:
        shape = _quadratic_direction(remainder, computation)
        if shape is not None:
            return _quadratic_function(name, center, shape, computation)
    powers = _nilpotent_powers(remainder, computation)
    if powers is None:
        raise NormalizationError(
            f"No exact algebra reduction for {name!r}: the nonscalar part is not certified "
            f"nilpotent within order {computation.limits.max_calculus_order} or a supported quadratic direction")
    scalar = _LiftAnalysis(computation)
    if name in {"log", "sqrt"} and not scalar.positive(center):
        raise NormalizationError(f"A regular real algebra {name} requires a proved positive scalar center")
    count = len(powers)
    argument = (center, scalar.one, *(scalar.zero for _ in range(count - 2)))
    coefficients = scalar.function_jet(name, argument[:count], count)
    result = {}
    for coefficient, power in zip(coefficients, powers):
        for word, value in power.items():
            computation.add(result, word, scalar.mul(coefficient, value))
    return result
