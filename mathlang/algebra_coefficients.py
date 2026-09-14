"""Guarded rational scalar coefficients for finite-dimensional algebra work.

Fractions enter the coefficient field only after their denominators are known
to be nonzero. This makes cancellation and collecting zero coefficients safe:
an unknown partial expression never disappears as a side effect of a relation.
The polynomial implementation is shared with the scalar normalizer.
"""

from fractions import Fraction

from .normalization import NormalizationError, TOTAL_FUNCTIONS, _Computation
from .terms import (Binary, Comparison, Defined, FunctionCall, Logical, Number,
                    Symbol, SymbolKind, Truth, TruthValue, Unary)


class RationalCoefficients:
    def __init__(self, factory, limits, query=None):
        self.f, self.limits, self.query = factory, limits, query
        self.poly = _Computation(factory, limits, query)
        self.memo = {}
        self.nonzero = set()
        self.one = {(): Fraction(1)}
        self._fallback = None

    def decision(self, predicate):
        if isinstance(predicate, Truth):
            return predicate.value
        if isinstance(predicate, Logical) and predicate.op == 'and':
            values = [self.decision(p) for p in predicate.operands]
            if TruthValue.FALSE in values:
                return TruthValue.FALSE
            if all(v is TruthValue.TRUE for v in values):
                return TruthValue.TRUE
        if self.query is not None:
            return self.query(predicate)
        if self._fallback is None:
            from .logic import PredicateQuery
            self._fallback = PredicateQuery(self.f, limits=self.limits)
        return self._fallback.query(predicate)

    def condition(self, term):
        """The nonzero condition of an already defined scalar expression."""
        numerator, _ = self.fraction(term)
        if not numerator:
            return self.f.truth(TruthValue.FALSE)
        if len(numerator) == 1:
            monomial = next(iter(numerator))
            conditions = [self.f.comparison('!=', atom, self.f.number(0))
                          for atom, _ in monomial]
            if not conditions:
                return self.f.truth(TruthValue.TRUE)
            condition = conditions[0]
            for following in conditions[1:]:
                condition = self.f.logical('and', condition, following)
            return condition
        return self.f.comparison('!=', self.poly.polynomial_term(numerator), self.f.number(0))

    def require_nonzero(self, term):
        if term in self.nonzero:
            return
        condition = self.condition(term)
        result = self.decision(condition)
        if result is TruthValue.UNKNOWN and self.query is not None:
            result = self.query(self.f.comparison('!=', term, self.f.number(0)))
        if result is not TruthValue.TRUE:
            from .renderer import format_term
            if result is TruthValue.FALSE:
                raise NormalizationError('Cannot invert a zero scalar or a noninvertible algebra element')
            raise NormalizationError('Cannot establish invertibility; required condition: '
                                     + format_term(condition))
        self.nonzero.add(term)

    def reduce(self, numerator, denominator):
        if not denominator:
            raise NormalizationError('Division by zero')
        if not numerator:
            return {}, self.one
        # Remove common monomial factors. More general polynomial gcds are not
        # needed for correctness: cross multiplication still detects equality.
        common = None
        for monomial in (*numerator, *denominator):
            powers = dict(monomial)
            common = powers if common is None else {
                atom: min(power, powers.get(atom, 0)) for atom, power in common.items()
                if powers.get(atom, 0)
            }
        if common:
            def remove(polynomial):
                return {tuple((atom, power-common.get(atom, 0)) for atom, power in monomial
                              if power > common.get(atom, 0)): coefficient
                        for monomial, coefficient in polynomial.items()}
            numerator, denominator = remove(numerator), remove(denominator)
        # A monic denominator fixes signs and rational scaling deterministically.
        leading = next(iter(sorted(denominator, key=lambda m: (
            -sum(power for _, power in m), tuple((self.poly.key(atom), -power) for atom, power in m)))))
        scale = denominator[leading]
        numerator = {m: self.poly.check_number(c/scale) for m, c in numerator.items()}
        denominator = {m: self.poly.check_number(c/scale) for m, c in denominator.items()}
        if numerator == denominator:
            return self.one, self.one
        return numerator, denominator

    def render(self, value):
        numerator, denominator = value
        top = self.poly.polynomial_term(numerator)
        if denominator == self.one:
            return top
        return self.f.binary('/', top, self.poly.polynomial_term(denominator))

    def normalize(self, term):
        return self.render(self.fraction(term))

    def fraction(self, term):
        if term in self.memo:
            return self.memo[term]
        stack = [(term, False)]
        while stack:
            node, ready = stack.pop()
            if node in self.memo:
                continue
            self.poly.tick()
            if not ready:
                stack.append((node, True))
                children = node.arguments if isinstance(node, FunctionCall) else node.children
                stack.extend((child, False) for child in reversed(children))
                continue
            match node:
                case Number(value=value):
                    result = ({(): self.poly.check_number(value)} if value else {}, self.one)
                case Symbol():
                    self.poly.validate_symbol(node)
                    result = ({((node, 1),): Fraction(1)}, self.one)
                case Unary(op=op, operand=operand):
                    numerator, denominator = self.memo[operand]
                    result = ({m: -c if op == '-' else c for m, c in numerator.items()}, denominator)
                case Binary(op=op, left=left, right=right):
                    a, b = self.memo[left]
                    c, d = self.memo[right]
                    if op in ('+', '-'):
                        result = (self.poly.add(self.poly.multiply(a, d), self.poly.multiply(c, b),
                                                1 if op == '+' else -1), self.poly.multiply(b, d))
                    elif op == '*':
                        result = (self.poly.multiply(a, c), self.poly.multiply(b, d))
                    elif op == '/':
                        self.require_nonzero(right)
                        result = (self.poly.multiply(a, d), self.poly.multiply(b, c))
                    elif op == '^':
                        exponent = self.render((c, d))
                        if not isinstance(exponent, Number) or exponent.value.denominator != 1:
                            base = self.render((a, b))
                            atom = self.poly.binary('^', base, exponent)
                            if self.decision(Defined(atom)) is not TruthValue.TRUE:
                                raise NormalizationError('A scalar coefficient power requires a proved domain')
                            result = (({(): atom.value} if atom.value else {}, self.one)
                                      if isinstance(atom, Number) else
                                      ({((atom, 1),): Fraction(1)}, self.one))
                            self.memo[node] = self.reduce(*result)
                            continue
                        if abs(exponent.value) > self.limits.max_power:
                            raise NormalizationError('Scalar coefficient power limit exceeded')
                        power = int(exponent.value)
                        if power <= 0:
                            self.require_nonzero(left)
                        if power < 0:
                            a, b, power = b, a, -power
                        result = (self.poly.power(a, power), self.poly.power(b, power))
                    else:
                        raise NormalizationError(f'Unsupported scalar coefficient operation {op}')
                case FunctionCall(callee=callee, arguments=arguments):
                    args = tuple(self.render(self.memo[arg]) for arg in arguments)
                    atom = self.poly.function(callee, args)
                    if isinstance(atom, Number):
                        result = ({(): atom.value} if atom.value else {}, self.one)
                    else:
                        total = (isinstance(callee, Symbol) and callee.kind == SymbolKind.BUILTIN
                                 and callee.name in TOTAL_FUNCTIONS)
                        if not total and self.decision(Defined(atom)) is not TruthValue.TRUE:
                            raise NormalizationError('Cannot normalize a potentially partial function without assumptions')
                        result = ({((atom, 1),): Fraction(1)}, self.one)
                case _:
                    raise NormalizationError('Expected a scalar coefficient')
            self.memo[node] = self.reduce(*result)
        return self.memo[term]
