"""Associative unital quotient algebras, without built-in mathematical families.

Relations remain equalities in IR. This backend orients rational polynomial
relations by degree-lexicographic word order and checks every overlap/inclusion
ambiguity before claiming a canonical form (the terminating diamond criterion).
It does not perform completion or infer confluence from a few sample products.
"""

from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from uuid import uuid4

from .normalization import Limits, NormalizationError, SCALAR_TYPES
from .algebra_coefficients import RationalCoefficients
from .terms import (Binary, FunctionCall, Number, Predicate, Symbol, SymbolKind, Term,
                    TermFactory, Type, Unary)


class AlgebraError(NormalizationError):
    pass


Word = tuple[int, ...]
Polynomial = dict[Word, Fraction]


@dataclass(frozen=True, slots=True)
class Relation:
    left: Term
    right: Term


@dataclass(frozen=True, slots=True)
class WordReduction:
    word: Word
    replacement: tuple[tuple[Word, Fraction], ...]
    relation_index: int


@dataclass(frozen=True, slots=True)
class AlgebraDefinition(Term):
    name: str
    scalar_domain: Type
    type: Type
    generators: tuple[Symbol, ...]
    relations: tuple[Relation, ...]
    reductions: tuple[WordReduction, ...]
    basis: tuple[Word, ...] | None
    bilinear: bool
    confluence: str
    conflict: str | None = None
    properties: tuple[tuple[str, Term], ...] = ()
    __hash__ = Term.__hash__

    @property
    def termination(self) -> str:
        return "known"

    def member(self, name: str) -> Term | None:
        return next((g for g in self.generators if g.name == name),
                    dict(self.properties).get(name))


class _Words:
    def __init__(self, rules: tuple[WordReduction, ...], limits: Limits):
        self.rules, self.limits = rules, limits
        self.steps = self.applications = 0
        self.cache: dict[Word, Polynomial] = {}

    def tick(self):
        self.steps += 1
        if self.steps > self.limits.max_steps:
            raise AlgebraError("Algebra computation step limit exceeded")

    def add(self, target: Polynomial, word: Word, coefficient: Fraction):
        self.tick()
        value = target.get(word, Fraction(0)) + coefficient
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > self.limits.max_integer_bits:
            raise AlgebraError("Exact number size limit exceeded")
        if value:
            target[word] = value
        else:
            target.pop(word, None)
        if len(target) > self.limits.max_terms or len(word) > self.limits.max_nodes:
            raise AlgebraError("Algebra polynomial size limit exceeded")

    def occurrence(self, word: Word):
        for rule in self.rules:
            for index in range(len(word) - len(rule.word) + 1):
                self.tick()
                if word[index:index + len(rule.word)] == rule.word:
                    return rule, index
        return None

    def normalize(self, polynomial: Polynomial) -> Polynomial:
        pending = dict(polynomial)
        result: Polynomial = {}
        while pending:
            self.tick()
            word = max(pending, key=lambda w: (len(w), w))
            coefficient = pending.pop(word)
            if not coefficient:
                continue
            found = self.occurrence(word)
            if found is None:
                self.add(result, word, coefficient)
                continue
            self.applications += 1
            if self.applications > self.limits.max_rewrites:
                raise AlgebraError("Algebra reduction limit exceeded")
            rule, index = found
            for replacement, value in rule.replacement:
                new = word[:index] + replacement + word[index + len(rule.word):]
                self.add(pending, new, coefficient * value)
        return result

    def word(self, word: Word) -> Polynomial:
        if word not in self.cache:
            self.cache[word] = self.normalize({word: Fraction(1)})
        return self.cache[word]

    def multiply(self, left: Polynomial, right: Polynomial) -> Polynomial:
        result: Polynomial = {}
        for a, x in left.items():
            for b, y in right.items():
                self.add(result, a + b, x*y)
        return result


def _raw(term: Term, generators: tuple[Symbol, ...], engine: _Words) -> Polynomial:
    """Elaborated relation -> free polynomial; coefficients must be rational."""
    memo: dict[Term, Polynomial] = {}
    stack = [(term, False)]
    while stack:
        node, ready = stack.pop()
        if node in memo:
            continue
        engine.tick()
        if not ready:
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node.children))
            continue
        match node:
            case Number(value=value):
                result = {}
                engine.add(result, (), value)
            case Symbol() if node in generators:
                result = {(generators.index(node),): Fraction(1)}
            case Unary(op=op, operand=operand):
                result = {w: (-c if op == "-" else c) for w, c in memo[operand].items()}
            case Binary(op=op, left=left, right=right):
                a, b = memo[left], memo[right]
                if op in ("+", "-"):
                    result = dict(a)
                    for word, coefficient in b.items():
                        engine.add(result, word, coefficient if op == "+" else -coefficient)
                elif op == "*":
                    result = engine.multiply(a, b)
                elif op == "/" and set(b) == {()} and b[()]:
                    result = {}
                    for word, coefficient in a.items():
                        engine.add(result, word, coefficient / b[()])
                elif op == "^" and (not b or set(b) == {()}):
                    exponent = b.get((), Fraction(0))
                    if exponent.denominator != 1 or not 0 <= exponent <= engine.limits.max_power:
                        raise AlgebraError("Algebra powers require bounded nonnegative integers")
                    if not a and exponent == 0:
                        raise AlgebraError("0^0 is undefined")
                    result = {(): Fraction(1)}
                    for _ in range(int(exponent)):
                        result = engine.multiply(result, a)
                else:
                    raise AlgebraError("Relations require polynomials and nonzero rational denominators")
            case _:
                raise AlgebraError("Relations require rational coefficients and declared generators")
        memo[node] = result
    return memo[term]


def _confluence(engine: _Words) -> str | None:
    """Check intersecting redexes, including containment and competing heads."""
    for first, second in product(engine.rules, repeat=2):
        a, b = first.word, second.word
        for offset in range(-len(b) + 1, len(a)):
            engine.tick()
            start, end = min(0, offset), max(len(a), offset + len(b))
            letters: dict[int, int] = dict(enumerate(a))
            if any(i + offset in letters and letters[i + offset] != letter for i, letter in enumerate(b)):
                continue
            letters.update((i + offset, letter) for i, letter in enumerate(b))
            word = tuple(letters[i] for i in range(start, end))
            positions = (-start, offset - start)
            branches = []
            for rule, position in zip((first, second), positions):
                polynomial: Polynomial = {}
                for replacement, coefficient in rule.replacement:
                    engine.add(polynomial, word[:position] + replacement + word[position + len(rule.word):], coefficient)
                branches.append(engine.normalize(polynomial))
            if branches[0] != branches[1]:
                return (f"Conflicting reductions of generator word {word}: "
                        f"relations {first.relation_index + 1} and {second.relation_index + 1}")
    return None


def _basis(count: int, engine: _Words) -> tuple[Word, ...]:
    result: list[Word] = [()]
    position = 0
    while position < len(result):
        prefix = result[position]
        position += 1
        for generator in range(count):
            word = (*prefix, generator)
            if engine.occurrence(word) is None:
                result.append(word)
                if len(result) > engine.limits.max_terms or len(word) > engine.limits.max_power:
                    raise AlgebraError("Cannot derive a finite basis within limits; the algebra may be infinite-dimensional")
    return tuple(result)


def algebra_symbols(name: str, names: tuple[str, ...]) -> tuple[Type, tuple[Symbol, ...]]:
    if len(set(names)) != len(names) or not names:
        raise AlgebraError("An algebra requires distinct generator names")
    type_ = Type(name, identity=uuid4())
    return type_, tuple(Symbol(n, SymbolKind.GENERATOR, type_) for n in names)


def compile_algebra(name: str, scalar_domain: Type, type_: Type, generators: tuple[Symbol, ...],
                    relations: tuple[Relation, ...], basis: tuple[Term, ...] | None,
                    *, derive_basis: bool = False, bilinear: bool = False,
                    limits: Limits | None = None) -> AlgebraDefinition:
    limits = Limits() if limits is None else limits
    if (not generators or len(set(generators)) != len(generators)
            or len({g.name for g in generators}) != len(generators)
            or type_.identity is None or type_.name != name
            or any(g.kind != SymbolKind.GENERATOR or g.annotation != type_ for g in generators)):
        raise AlgebraError("Generators must have distinct identities and the owning algebra type")
    if scalar_domain.identity is not None:
        raise AlgebraError("Algebras over other user algebras are not supported by this backend")
    if scalar_domain.arguments or scalar_domain.name not in ("Rational", "Real", "Complex"):
        raise AlgebraError("This algebra backend requires Rational, Real or Complex scalars")
    raw = _Words((), limits)
    rules = []
    for index, relation in enumerate(relations):
        difference = _raw(relation.left, generators, raw)
        for word, coefficient in _raw(relation.right, generators, raw).items():
            raw.add(difference, word, -coefficient)
        if not difference:
            continue
        leading = max(difference, key=lambda w: (len(w), w))
        if not leading:
            raise AlgebraError("Inconsistent scalar relation: a nonzero scalar cannot equal zero")
        coefficient = difference.pop(leading)
        replacement = {}
        for word, value in difference.items():
            raw.add(replacement, word, -value/coefficient)
        rules.append(WordReduction(leading, tuple(sorted(replacement.items())), index))
    reductions = tuple(rules)
    engine = _Words(reductions, limits)
    conflict = _confluence(engine)
    words = None
    if basis is not None:
        provided = []
        for term in basis:
            polynomial = _raw(term, generators, raw)
            if len(polynomial) != 1 or next(iter(polynomial.values())) != 1:
                raise AlgebraError("A basis entry must be a generator word with coefficient 1")
            word = next(iter(polynomial))
            if engine.occurrence(word) is not None:
                raise AlgebraError("Basis entries must be irreducible generator words")
            provided.append(word)
        if len(set(provided)) != len(provided):
            raise AlgebraError("Basis entries must be distinct")
        words = tuple(provided)
    if basis is not None or derive_basis:
        if conflict:
            raise AlgebraError("Cannot certify a basis: rewrite system is not confluent. " + conflict)
        actual = _basis(len(generators), engine)
        if words is not None and set(actual) != set(words):
            raise AlgebraError("Declared basis does not contain exactly all irreducible generator words")
        words = actual if words is None else words
    return AlgebraDefinition(name, scalar_domain, type_, generators, relations, reductions,
                             words, bilinear, "known" if conflict is None else "unknown", conflict)


class AlgebraNormalizer:
    def __init__(self, algebra: AlgebraDefinition, factory: TermFactory, limits: Limits | None = None,
                 *, query=None):
        self.algebra, self.factory = algebra, factory
        self.limits = Limits() if limits is None else limits
        self.query = query

    def _computation(self):
        if self.algebra.confluence != "known":
            raise AlgebraError("Cannot derive a canonical normal form: rewrite system is not confluent. "
                               + (self.algebra.conflict or ""))
        return _AlgebraComputation(self)

    def normalize(self, term: Term) -> Term:
        computation = self._computation()
        return computation.render(computation.coordinates(term))

    def coordinates(self, term: Term) -> dict[Word, Term]:
        """Express an element in irreducible generator words with central scalars."""
        return self._computation().coordinates(term)

    def from_coordinates(self, coordinates: dict[Word, Term]) -> Term:
        computation = self._computation()
        result = {}
        for word, coefficient in coordinates.items():
            if any(not isinstance(i, int) or not 0 <= i < len(self.algebra.generators) for i in word):
                raise AlgebraError('Invalid generator index in algebra coordinates')
            value = computation.coefficient(coefficient)
            for reduced, factor in computation.words.word(word).items():
                computation.add(result, reduced, self.factory.binary('*', value, self.factory.number(factor)))
        return computation.render(result)

    def invertibility(self, term: Term) -> Predicate:
        """Return the scalar condition for invertibility without assuming it."""
        computation = self._computation()
        coordinates = computation.coordinates(term)
        if not set(coordinates) - {()}:
            determinant = coordinates.get((), self.factory.number(0))
        else:
            determinant, _ = computation.adjugate(coordinates)
        return computation.nonzero_condition(determinant)

    def function_domain(self, name: str, term: Term) -> Predicate | None:
        from .analytic_lift import function_domain
        computation = self._computation()
        return function_domain(name, computation.coordinates(term), computation)

    def simplify(self, term: Term) -> Term:
        return self.normalize(term)


class _AlgebraComputation:
    def __init__(self, normalizer: AlgebraNormalizer):
        self.normalizer, self.query = normalizer, normalizer.query
        self.algebra, self.f, self.limits = normalizer.algebra, normalizer.factory, normalizer.limits
        self.words = _Words(self.algebra.reductions, self.limits)
        self.scalar = RationalCoefficients(self.f, self.limits, self.query)
        self.indices = {g: i for i, g in enumerate(self.algebra.generators)}
        self.coefficients: dict[Term, Term] = {}

    def coefficient(self, term: Term) -> Term:
        self.words.tick()
        if term not in self.coefficients:
            try:
                value = self.scalar.normalize(term)
            except NormalizationError as error:
                raise AlgebraError(str(error)) from error
            if isinstance(value, Unary) and isinstance(value.operand, Number):
                value = self.f.number(-value.operand.value if value.op == "-" else value.operand.value)
            self.coefficients[term] = value
        return self.coefficients[term]

    def nonzero_condition(self, term: Term) -> Predicate:
        return self.scalar.condition(term)

    def require_nonzero(self, term: Term):
        try:
            self.scalar.require_nonzero(term)
        except NormalizationError as error:
            raise AlgebraError(str(error)) from error

    def add(self, result: dict[Word, Term], word: Word, coefficient: Term):
        if word in result:
            coefficient = self.f.binary("+", result[word], coefficient)
        value = self.coefficient(coefficient)
        if isinstance(value, Number) and not value.value:
            result.pop(word, None)
        else:
            result[word] = value
        if len(result) > self.limits.max_terms:
            raise AlgebraError("Algebra polynomial size limit exceeded")

    def multiply(self, left: dict[Word, Term], right: dict[Word, Term]) -> dict[Word, Term]:
        result: dict[Word, Term] = {}
        for a, x in left.items():
            for b, y in right.items():
                for word, value in self.words.word(a+b).items():
                    self.add(result, word, self.f.binary("*", self.f.binary("*", x, y), self.f.number(value)))
        return result

    def adjugate(self, coordinates: dict[Word, Term]):
        """Compute det(L_q) and adj(L_q) by a division-free-in-parameters recurrence.

        Faddeev-LeVerrier divides only by positive integer dimensions. Unlike
        symbolic Gaussian elimination, it needs no guesses about pivot values.
        """
        basis = self.algebra.basis
        if basis is None:
            raise AlgebraError('Algebra inversion requires a certified finite basis')
        size = len(basis)
        if size * size > self.limits.max_terms:
            raise AlgebraError('Algebra inverse matrix size limit exceeded')
        if not size or () not in basis:
            raise AlgebraError('Algebra inverse requires a basis containing the unit')
        zero, one = self.f.number(0), self.f.number(1)
        positions = {word: index for index, word in enumerate(basis)}
        matrix = [[zero for _ in basis] for _ in basis]
        for column, word in enumerate(basis):
            for output, value in self.multiply(coordinates, {word: one}).items():
                if output not in positions:
                    raise AlgebraError('Algebra product lies outside the certified basis')
                matrix[positions[output]][column] = value
        previous = [[one if i == j else zero for j in range(size)] for i in range(size)]
        for order in range(1, size + 1):
            following = [[zero for _ in basis] for _ in basis]
            for i in range(size):
                for j in range(size):
                    value = zero
                    for k in range(size):
                        self.words.tick()
                        if matrix[i][k] == zero or previous[k][j] == zero:
                            continue
                        value = self.f.binary('+', value, self.f.binary('*', matrix[i][k], previous[k][j]))
                    following[i][j] = self.coefficient(value)
            trace = zero
            for i in range(size):
                trace = self.f.binary('+', trace, following[i][i])
            coefficient = self.coefficient(self.f.binary('/', self.f.unary('-', trace), self.f.number(order)))
            if order == size:
                sign = -1 if size % 2 else 1
                determinant = self.coefficient(self.f.binary('*', self.f.number(sign), coefficient))
                adjugate_sign = -sign
                column = positions[()]
                adjugate = {word: self.coefficient(self.f.binary('*', self.f.number(adjugate_sign), previous[i][column]))
                            for i, word in enumerate(basis) if previous[i][column] != zero}
                return determinant, adjugate
            for i in range(size):
                following[i][i] = self.coefficient(self.f.binary('+', following[i][i], coefficient))
            previous = following
        raise AlgebraError('Unable to compute algebra inverse')

    def inverse(self, coordinates: dict[Word, Term]) -> dict[Word, Term]:
        if not set(coordinates) - {()}:
            value = coordinates.get((), self.f.number(0))
            self.require_nonzero(value)
            return {(): self.coefficient(self.f.binary('/', self.f.number(1), value))}
        determinant, adjugate = self.adjugate(coordinates)
        self.require_nonzero(determinant)
        inverse = {word: self.coefficient(self.f.binary('/', value, determinant))
                   for word, value in adjugate.items()}
        unit = {(): self.f.number(1)}
        if self.multiply(coordinates, inverse) != unit or self.multiply(inverse, coordinates) != unit:
            raise AlgebraError('Cannot verify both sides of the derived algebra inverse within this backend')
        return inverse

    def coordinates(self, term: Term) -> dict[Word, Term]:
        memo: dict[Term, dict[Word, Term]] = {}
        stack = [(term, False)]
        while stack:
            node, ready = stack.pop()
            if node in memo:
                continue
            self.words.tick()
            if not ready:
                stack.append((node, True))
                children = node.arguments if isinstance(node, FunctionCall) else node.children
                stack.extend((child, False) for child in reversed(children))
                continue
            match node:
                case Number():
                    value = self.coefficient(node)
                    result = {} if value.value == 0 else {(): value}
                case Symbol() if node in self.indices:
                    result = {w: self.f.number(c) for w, c in self.words.word((self.indices[node],)).items()}
                case Symbol():
                    annotation = node.annotation
                    ranks = {"Nat": 0, "Integer": 1, "Rational": 2, "Real": 3, "Complex": 4}
                    if (node.kind == SymbolKind.GENERATOR or annotation is None or annotation.arguments
                            or annotation.identity is not None or annotation.name not in SCALAR_TYPES
                            or ranks[annotation.name] > ranks[self.algebra.scalar_domain.name]):
                        raise AlgebraError(f"Cannot embed {node.name!r} of type {annotation} into {self.algebra.name} over {self.algebra.scalar_domain}")
                    result = {(): self.coefficient(node)}
                case Unary(op=op, operand=operand):
                    result = {w: self.coefficient(self.f.unary(op, c)) for w, c in memo[operand].items()}
                case Binary(op=op, left=left, right=right):
                    a, b = memo[left], memo[right]
                    if op == "^" and not (set(a) - {()}) and not (set(b) - {()}):
                        # A scalar power remains a scalar coefficient of the
                        # algebra.  It may have a non-integer exponent (for
                        # example 2^(1/2)); the coefficient backend already
                        # checks its domain and preserves it exactly.
                        result = {(): self.coefficient(node)}
                    elif op in ("+", "-"):
                        result = dict(a)
                        for word, coefficient in b.items():
                            self.add(result, word, coefficient if op == "+" else self.f.unary("-", coefficient))
                    elif op == "*":
                        result = self.multiply(a, b)
                    elif op == "/":
                        result = self.multiply(a, self.inverse(b))
                    elif op == "^":
                        exponent = b.get((), self.f.number(0))
                        if (set(b) - {()} or not isinstance(exponent, Number) or exponent.value.denominator != 1
                                or abs(exponent.value) > self.limits.max_power):
                            raise AlgebraError("Algebra powers require bounded integers")
                        if not a and not exponent.value:
                            raise AlgebraError("0^0 is undefined")
                        result = {(): self.f.number(1)}
                        power = int(exponent.value)
                        if power < 0:
                            a, power = self.inverse(a), -power
                        while power:
                            if power & 1:
                                result = self.multiply(result, a)
                            power //= 2
                            if power:
                                a = self.multiply(a, a)
                    else:
                        raise AlgebraError(f"Unsupported algebra operation {op}")
                case FunctionCall(callee=callee, arguments=arguments):
                    if any(set(memo[a]) - {()} for a in arguments):
                        from .analytic_lift import lift_function
                        if (not isinstance(callee, Symbol) or callee.kind != SymbolKind.BUILTIN
                                or len(arguments) != 1):
                            raise AlgebraError('Only supported built-in functions can be lifted to algebra elements')
                        result = lift_function(callee.name, memo[arguments[0]], self)
                    else:
                        scalar_arguments = tuple(memo[a].get((), self.f.number(0)) for a in arguments)
                        result = {(): self.coefficient(self.f.call(callee, scalar_arguments))}
                case _:
                    raise AlgebraError(f"No algebra normalizer for {type(node).__name__}")
            memo[node] = {w: c for w, c in result.items() if not isinstance(c, Number) or c.value != 0}
        return memo[term]

    def render(self, polynomial: dict[Word, Term]) -> Term:
        result = None
        for word in sorted(polynomial, key=lambda w: (-len(w), w)):
            coefficient = polynomial[word]
            negative = isinstance(coefficient, Number) and coefficient.value < 0
            if negative:
                coefficient = self.f.number(-coefficient.value)
            if isinstance(coefficient, Unary) and coefficient.op == "-":
                coefficient, negative = coefficient.operand, not negative
            factors = [] if word and isinstance(coefficient, Number) and coefficient.value == 1 else [coefficient]
            index = 0
            while index < len(word):
                end = index + 1
                while end < len(word) and word[end] == word[index]:
                    end += 1
                generator = self.algebra.generators[word[index]]
                factors.append(generator if end - index == 1 else self.f.binary("^", generator, self.f.number(end-index)))
                index = end
            item = factors[0]
            for factor in factors[1:]:
                item = self.f.binary("*", item, factor)
            if result is None:
                result = self.f.unary("-", item) if negative else item
            else:
                result = self.f.binary("-" if negative else "+", result, item)
        return self.f.number(0) if result is None else result


def word_term(algebra: AlgebraDefinition, word: Word, factory: TermFactory) -> Term:
    if not word:
        return factory.number(1)
    result: Term = algebra.generators[word[0]]
    for index in word[1:]:
        result = factory.binary("*", result, algebra.generators[index])
    return result
