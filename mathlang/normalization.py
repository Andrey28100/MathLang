"""Exact, bounded transformations of expressions in commutative scalar domains.

This backend deliberately does not infer algebraic laws for arbitrary types.
Normalization is polynomial expansion over rational coefficients; simplification
collects terms and factors without distributing products over sums.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import isqrt

from .terms import ApproxNumber, Binary, Comparison, Defined, FunctionCall, Number, Symbol, SymbolKind, Term, TermFactory, TruthValue, Unary


SCALAR_TYPES = frozenset({"Nat", "Integer", "Rational", "Real", "Complex"})
SCALAR_FUNCTIONS = frozenset({"sin", "cos", "tan", "exp", "log", "sqrt", "abs"})
TOTAL_FUNCTIONS = frozenset({"sin", "cos", "exp", "abs"})


class NormalizationError(ValueError):
    """An undefined operation, unsupported domain, or exhausted computation limit."""


@dataclass(frozen=True, slots=True)
class Limits:
    max_steps: int = 100_000
    max_terms: int = 4096
    max_power: int = 1000
    max_integer_bits: int = 8192
    max_rewrites: int = 1000
    max_passes: int = 100
    max_nodes: int = 10_000
    max_calculus_order: int = 32
    max_modules: int = 128
    max_import_depth: int = 32
    max_module_bytes: int = 1_000_000
    max_ir_bytes: int = 10_000_000
    max_iterations: int = 10_000
    max_quantifier_checks: int = 128
    max_theory_depth: int = 32

    def __post_init__(self) -> None:
        if min(self.max_steps, self.max_terms, self.max_power, self.max_integer_bits,
               self.max_rewrites, self.max_passes, self.max_nodes, self.max_calculus_order,
               self.max_modules, self.max_import_depth, self.max_module_bytes, self.max_ir_bytes,
               self.max_iterations, self.max_quantifier_checks, self.max_theory_depth) < 1:
            raise ValueError("Computation limits must be positive")


Monomial = tuple[tuple[Term, int], ...]
Polynomial = dict[Monomial, Fraction]


class ScalarNormalizer:
    def __init__(self, factory: TermFactory, limits: Limits | None = None, *, query=None) -> None:
        self.factory = factory
        self.limits = Limits() if limits is None else limits
        self.query = query

    def simplify(self, term: Term) -> Term:
        return _Computation(self.factory, self.limits, self.query).run(term, expand=False)

    def normalize(self, term: Term) -> Term:
        return _Computation(self.factory, self.limits, self.query).run(term, expand=True)


class _Computation:
    def __init__(self, factory: TermFactory, limits: Limits, query=None) -> None:
        self.f = factory
        self.limits = limits
        self.steps = 0
        self.keys: dict[Term, tuple] = {}
        self.total: dict[Term, bool] = {}
        self.trigonometric = False
        self.query = query

    def tick(self, amount: int = 1) -> None:
        self.steps += amount
        if self.steps > self.limits.max_steps:
            raise NormalizationError("Computation step limit exceeded")

    def check_number(self, value: Fraction) -> Fraction:
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > self.limits.max_integer_bits:
            raise NormalizationError("Exact number size limit exceeded")
        return value

    def number(self, value: Fraction | int) -> Number:
        return self.f.number(self.check_number(Fraction(value)))

    def key(self, term: Term) -> tuple:
        if term not in self.keys:
            match term:
                case Symbol(name=name, identity=identity):
                    result = (0, name, identity.int)
                case FunctionCall(callee=callee, arguments=arguments):
                    result = (1, self.key(callee), tuple(self.key(a) for a in arguments))
                case Binary(op=op, left=left, right=right):
                    result = (2, op, self.key(left), self.key(right))
                case Unary(op=op, operand=operand):
                    result = (3, op, self.key(operand))
                case Number(value=value):
                    result = (4, value)
                case ApproxNumber(text=text, digits=digits):
                    result = (5, text, digits)
                case _:
                    raise NormalizationError("Expected a scalar expression; call the function first")
            self.keys[term] = result
        return self.keys[term]

    def is_total(self, term: Term) -> bool:
        """Whether removing this term can preserve the domain of the expression."""
        if term not in self.total:
            if self.query is not None:
                defined = self.query(Defined(term))
                if defined is not TruthValue.UNKNOWN:
                    self.total[term] = defined is TruthValue.TRUE
                    return self.total[term]
            match term:
                case Number() | ApproxNumber() | Symbol():
                    result = True
                case Unary(operand=operand):
                    result = self.is_total(operand)
                case Binary(op=op, left=left, right=right):
                    result = self.is_total(left) and self.is_total(right)
                    if op == "/":
                        result = result and isinstance(right, Number) and right.value != 0
                    elif op == "^":
                        result = (result and isinstance(right, Number)
                                  and right.value.denominator == 1 and right.value > 0)
                case FunctionCall(callee=Symbol(kind=kind, name=name), arguments=arguments):
                    result = (kind != SymbolKind.BUILTIN or name in TOTAL_FUNCTIONS)
                    result = result and all(self.is_total(a) for a in arguments)
                case _:
                    result = False
            self.total[term] = result
        return self.total[term]

    def validate_symbol(self, symbol: Symbol) -> None:
        annotation = symbol.annotation
        if (annotation is None or annotation.arguments or annotation.name not in SCALAR_TYPES
                or annotation.identity is not None
                or symbol.kind in (SymbolKind.BUILTIN, SymbolKind.GENERATOR)):
            domain = "unknown" if annotation is None else str(annotation)
            raise NormalizationError(
                f"No scalar normalizer for {symbol.name!r} with type {domain}; "
                "expected Nat, Integer, Rational, Real or Complex"
            )

    def function(self, callee: Term, arguments: tuple[Term, ...]) -> Term:
        if not isinstance(callee, Symbol):
            raise NormalizationError("Cannot determine the scalar result type of this call")
        if callee.kind == SymbolKind.BUILTIN:
            if callee.name not in SCALAR_FUNCTIONS or len(arguments) != 1:
                raise NormalizationError(f"{callee.name} expects one scalar argument")
            arg = arguments[0]
            if self.query is not None:
                from .elaboration import Elaborator, scalar_rank
                candidate = arg
                if (callee.name == 'sqrt' and isinstance(arg, Binary) and arg.op == '^'
                        and isinstance(arg.right, Number) and arg.right.value == 2):
                    candidate = arg.left
                elif callee.name != 'abs':
                    candidate = None
                if candidate is not None and not isinstance(candidate, Number) and scalar_rank(Elaborator(self.limits).infer(candidate)) in (0, 1, 2, 3):
                    zero = self.f.number(0)
                    if self.query(Comparison('>=', candidate, zero)) is TruthValue.TRUE:
                        return candidate
                    if self.query(Comparison('<=', candidate, zero)) is TruthValue.TRUE:
                        return self.simplify(self.f.unary('-', candidate))
            if isinstance(arg, Number):
                value = arg.value
                if callee.name in ("sin", "tan") and value == 0:
                    return self.number(0)
                if callee.name in ("cos", "exp") and value == 0:
                    return self.number(1)
                if callee.name == "log":
                    if value == 0:
                        raise NormalizationError("log(0) is undefined")
                    if value == 1:
                        return self.number(0)
                if callee.name == "abs":
                    return self.number(abs(value))
                if callee.name == "sqrt" and value >= 0:
                    p, q = isqrt(value.numerator), isqrt(value.denominator)
                    if p*p == value.numerator and q*q == value.denominator:
                        return self.number(Fraction(p, q))
                    # Keep exact irrational square roots canonical with the
                    # equivalent rational power.  This lets the proof/query
                    # layer identify sqrt(q) and q^(1/2) without introducing
                    # any floating-point approximation.
                    return self.f.binary("^", arg, self.number(Fraction(1, 2)))
        else:
            annotation = callee.annotation
            if (annotation is None or annotation.name != "Function"
                    or not annotation.arguments
                    or getattr(annotation.arguments[-1], "name", None) not in SCALAR_TYPES
                    or getattr(annotation.arguments[-1], "arguments", ())
                    or len(arguments) != len(annotation.arguments)-1):
                raise NormalizationError(f"Cannot determine the scalar result type of {callee.name!r}")
        return self.f.call(callee, arguments)

    def numeric_power(self, left: Fraction, right: Fraction) -> Term | None:
        if left == 0 and right <= 0:
            raise NormalizationError("0^0 is undefined" if right == 0 else "Division by zero")
        if left in (0, 1):
            return self.number(left)
        if right.denominator != 1:
            if right.denominator == 2 and left > 0:
                numerator, denominator = isqrt(left.numerator), isqrt(left.denominator)
                if numerator*numerator == left.numerator and denominator*denominator == left.denominator:
                    return self.numeric_power(Fraction(numerator, denominator), Fraction(right.numerator))
            return None
        exponent = int(right)
        if left in (0, 1, -1):
            return self.number(left ** exponent)
        if abs(exponent) > self.limits.max_power:
            raise NormalizationError("Power limit exceeded")
        bits = max(left.numerator.bit_length(), left.denominator.bit_length())
        if (bits - 1) * abs(exponent) > self.limits.max_integer_bits:
            raise NormalizationError("Exact number size limit exceeded")
        return self.number(left ** exponent)

    def factors(self, term: Term) -> tuple[Fraction, dict[Term, int]]:
        coefficient = Fraction(1)
        powers: dict[Term, int] = {}
        stack = [term]
        while stack:
            self.tick()
            node = stack.pop()
            if isinstance(node, Number):
                coefficient = self.check_number(coefficient * node.value)
            elif isinstance(node, Unary):
                if node.op == "-":
                    coefficient = -coefficient
                stack.append(node.operand)
            elif isinstance(node, Binary) and node.op == "*":
                stack.extend((node.left, node.right))
            elif (isinstance(node, Binary) and node.op == "^" and isinstance(node.right, Number)
                  and node.right.value.denominator == 1 and node.right.value > 0):
                powers[node.left] = powers.get(node.left, 0) + int(node.right.value)
            else:
                powers[node] = powers.get(node, 0) + 1
        return coefficient, powers

    def monomial(self, powers: dict[Term, int]) -> Monomial:
        return tuple(sorted(powers.items(), key=lambda item: self.key(item[0])))

    def product(self, coefficient: Fraction, monomial: Monomial) -> Term:
        if not coefficient:
            return self.number(0)
        factors: list[Term] = []
        if abs(coefficient) != 1 or not monomial:
            factors.append(self.number(abs(coefficient)))
        for base, power in monomial:
            factors.append(base if power == 1 else self.f.binary("^", base, self.number(power)))
        result = factors[0]
        for factor in factors[1:]:
            result = self.f.binary("*", result, factor)
        return self.f.unary("-", result) if coefficient < 0 else result

    def polynomial_term(self, polynomial: Polynomial) -> Term:
        if not polynomial:
            return self.number(0)
        ordered = sorted(polynomial, key=lambda m: (
            -sum(power for _, power in m), tuple((self.key(base), -power) for base, power in m),
        ))
        result = None
        for monomial in ordered:
            coefficient = polynomial[monomial]
            positive = self.product(abs(coefficient), monomial)
            if result is None:
                result = positive if coefficient > 0 else self.f.unary("-", positive)
            else:
                result = self.f.binary("+" if coefficient > 0 else "-", result, positive)
        assert result is not None
        return result

    def sum(self, term: Term) -> Term:
        polynomial: Polynomial = {}
        stack = [(term, Fraction(1))]
        while stack:
            self.tick()
            node, sign = stack.pop()
            if isinstance(node, Binary) and node.op in ("+", "-"):
                stack.extend(((node.left, sign), (node.right, sign if node.op == "+" else -sign)))
            elif isinstance(node, Unary):
                stack.append((node.operand, sign if node.op == "+" else -sign))
            else:
                coefficient, powers = self.factors(node)
                monomial = self.monomial(powers)
                self.accumulate(polynomial, monomial, sign * coefficient)
        # The identity is valid for real and complex scalar arguments, provided
        # the argument itself is defined. It is not a rule for user-defined sin/cos.
        for monomial in tuple(polynomial) if self.trigonometric else ():
            if len(monomial) != 1:
                continue
            atom, power = monomial[0]
            if (power != 2 or not isinstance(atom, FunctionCall)
                    or not isinstance(atom.callee, Symbol)
                    or atom.callee.kind != SymbolKind.BUILTIN or atom.callee.name != "sin"):
                continue
            for other in tuple(polynomial):
                self.tick()
                if len(other) != 1:
                    continue
                cosine, exponent = other[0]
                if (exponent == 2 and isinstance(cosine, FunctionCall)
                        and isinstance(cosine.callee, Symbol)
                        and cosine.callee.kind == SymbolKind.BUILTIN and cosine.callee.name == "cos"
                        and cosine.arguments == atom.arguments
                        and polynomial[other] == polynomial[monomial]):
                    coefficient = polynomial.pop(monomial)
                    polynomial.pop(other)
                    self.accumulate(polynomial, (), coefficient)
                    break
        return self.polynomial_term(polynomial)

    def binary(self, op: str, left: Term, right: Term) -> Term:
        if isinstance(left, Number) and isinstance(right, Number):
            a, b = left.value, right.value
            if op == "+":
                return self.number(a+b)
            if op == "-":
                return self.number(a-b)
            if op == "*":
                return self.number(a*b)
            if op == "/":
                if b == 0:
                    raise NormalizationError("Division by zero")
                return self.number(a/b)
            if op == "^":
                value = self.numeric_power(a, b)
                if value is not None:
                    return value
        zero_left = isinstance(left, Number) and left.value == 0
        zero_right = isinstance(right, Number) and right.value == 0
        one_left = isinstance(left, Number) and left.value == 1
        one_right = isinstance(right, Number) and right.value == 1
        if op == "/" and zero_right:
            raise NormalizationError("Division by zero")
        if op in ("+", "-") and zero_right:
            return left
        if op == "+" and zero_left:
            return right
        if op in ("*", "/", "^") and one_right:
            return left
        if op == "*" and one_left:
            return right
        result = self.f.binary(op, left, right)
        if self.query is not None and op in ('/', '^'):
            if (op == '/' and (left == right or zero_left)) or (op == '^' and zero_right):
                if self.query(Defined(result)) is TruthValue.TRUE:
                    return self.number(0 if op == '/' and zero_left else 1)
        if not (self.is_total(left) and self.is_total(right)):
            return result
        if op in ("+", "-"):
            return self.sum(result)
        if op == "*":
            coefficient, powers = self.factors(result)
            return self.product(coefficient, self.monomial(powers))
        if op == "/" and isinstance(right, Number):
            return self.binary("*", self.number(1/right.value), left)
        return result

    def children(self, term: Term) -> tuple[Term, ...]:
        if isinstance(term, FunctionCall):
            return term.arguments
        if isinstance(term, (Binary, Unary, Number, ApproxNumber, Symbol)):
            return term.children
        raise NormalizationError("Expected a scalar expression; call the function first")

    def walk(self, term: Term):
        visited: set[Term] = set()
        stack = [(term, False)]
        while stack:
            node, ready = stack.pop()
            if node in visited:
                continue
            if not ready:
                self.tick()
                stack.append((node, True))
                stack.extend((child, False) for child in reversed(self.children(node)))
            else:
                visited.add(node)
                yield node

    def simplify(self, term: Term) -> Term:
        memo: dict[Term, Term] = {}
        for node in self.walk(term):
            match node:
                case Number(value=value):
                    result = self.number(value)
                case ApproxNumber():
                    result = node
                case Symbol():
                    self.validate_symbol(node)
                    result = node
                case Unary(op=op, operand=operand):
                    operand = memo[operand]
                    if op == "+":
                        result = operand
                    elif isinstance(operand, Number):
                        result = self.number(-operand.value)
                    elif isinstance(operand, Unary) and operand.op == "-":
                        result = operand.operand
                    else:
                        result = self.f.unary(op, operand)
                case Binary(op=op, left=left, right=right):
                    result = self.binary(op, memo[left], memo[right])
                case FunctionCall(callee=callee, arguments=arguments):
                    result = self.function(callee, tuple(memo[a] for a in arguments))
            memo[node] = result
        return memo[term]

    def accumulate(self, polynomial: Polynomial, monomial: Monomial, value: Fraction) -> None:
        self.tick()
        coefficient = self.check_number(polynomial.get(monomial, Fraction(0)) + value)
        if coefficient:
            polynomial[monomial] = coefficient
        else:
            polynomial.pop(monomial, None)
        if len(polynomial) > self.limits.max_terms:
            raise NormalizationError("Polynomial term limit exceeded")

    def add(self, left: Polynomial, right: Polynomial, sign: int = 1) -> Polynomial:
        result = left.copy()
        for monomial, coefficient in right.items():
            self.accumulate(result, monomial, sign * coefficient)
        return result

    def multiply(self, left: Polynomial, right: Polynomial) -> Polynomial:
        result: Polynomial = {}
        for lm, lc in left.items():
            for rm, rc in right.items():
                powers = dict(lm)
                for base, exponent in rm:
                    powers[base] = powers.get(base, 0) + exponent
                self.accumulate(result, self.monomial(powers), self.check_number(lc*rc))
        return result

    def power(self, base: Polynomial, exponent: int) -> Polynomial:
        if exponent > self.limits.max_power:
            raise NormalizationError("Power limit exceeded")
        result: Polynomial = {(): Fraction(1)}
        while exponent:
            if exponent & 1:
                result = self.multiply(result, base)
            exponent //= 2
            if exponent:
                base = self.multiply(base, base)
        return result

    def expand(self, term: Term) -> Term:
        memo: dict[Term, Polynomial] = {}
        for node in self.walk(term):
            match node:
                case Number(value=value):
                    result = {(): value} if value else {}
                case ApproxNumber():
                    result = {((node, 1),): Fraction(1)}
                case Symbol():
                    result = {((node, 1),): Fraction(1)}
                case FunctionCall():
                    if not self.is_total(node):
                        raise NormalizationError("Cannot normalize a potentially partial function without assumptions")
                    # Arguments have already been simplified; normalize them too
                    # so sin(x+x) and sin(2*x) have the same atom identity.
                    arguments = tuple(self.polynomial_term(memo[a]) for a in node.arguments)
                    atom = self.function(node.callee, arguments)
                    result = ({(): atom.value} if isinstance(atom, Number)
                              else {((atom, 1),): Fraction(1)})
                    result = {m: c for m, c in result.items() if c}
                case Unary(op=op, operand=operand):
                    result = {m: c if op == "+" else -c for m, c in memo[operand].items()}
                case Binary(op=op, left=left, right=right):
                    lhs, rhs = memo[left], memo[right]
                    if op in ("+", "-"):
                        result = self.add(lhs, rhs, 1 if op == "+" else -1)
                    elif op == "*":
                        result = self.multiply(lhs, rhs)
                    elif op == "/":
                        if not rhs:
                            raise NormalizationError("Division by zero")
                        if set(rhs) != {()}:
                            raise NormalizationError("Polynomial normalization requires a nonzero numeric denominator")
                        result = {m: self.check_number(c/rhs[()]) for m, c in lhs.items()}
                    else:
                        exponent = rhs.get((), Fraction(0))
                        if (set(rhs) - {()} or exponent.denominator != 1 or exponent <= 0):
                            raise NormalizationError("Polynomial normalization requires positive integer powers")
                        result = self.power(lhs, int(exponent))
            memo[node] = result
        return self.polynomial_term(memo[term])

    def run(self, term: Term, *, expand: bool) -> Term:
        try:
            self.trigonometric = not expand
            result = self.simplify(term)
            return self.expand(result) if expand else result
        except RecursionError:
            raise NormalizationError("Expression nesting is too deep to transform") from None


def normalize(term: Term, factory: TermFactory | None = None, *, limits: Limits | None = None) -> Term:
    return ScalarNormalizer(TermFactory() if factory is None else factory, limits).normalize(term)


def simplify(term: Term, factory: TermFactory | None = None, *, limits: Limits | None = None) -> Term:
    return ScalarNormalizer(TermFactory() if factory is None else factory, limits).simplify(term)
