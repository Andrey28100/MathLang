"""Immutable mathematical terms, independent of source syntax and locations.

Source-level terms remain independent of implicit coercions. Typed IR is built
by :mod:`mathlang.elaboration` as a parallel graph, while this factory shares
equal source terms without retaining unused expression graphs.
"""

from dataclasses import dataclass, field, fields
from enum import Enum
from fractions import Fraction
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rewriting import RewriteRule


@dataclass(frozen=True, slots=True)
class Type:
    name: str
    arguments: tuple["Type | int", ...] = ()
    identity: UUID | None = field(default=None, repr=False)

    def __str__(self) -> str:
        suffix = ""
        if self.arguments:
            suffix = "<" + ", ".join(map(str, self.arguments)) + ">"
        return self.name + suffix


class SymbolKind(str, Enum):
    CONSTANT = "const"
    PARAMETER = "parameter"
    VARIABLE = "variable"
    UNKNOWN = "unknown"
    EXPRESSION = "expression"
    FUNCTION = "function"
    BUILTIN = "builtin"
    RULE = "rule"
    GENERATOR = "generator"
    ALGEBRA = "algebra"
    NAMESPACE = "namespace"
    THEORY = 'theory'
    IMPLEMENTATION = 'implementation'


@dataclass(frozen=True, slots=True, weakref_slot=True)
class Term:
    _hash: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Hash each node once: hashing a shared DAG recursively can be exponential.
        key = tuple(getattr(self, item.name) for item in fields(self) if item.name != "_hash")
        object.__setattr__(self, "_hash", hash((type(self), *key)))

    def __hash__(self) -> int:
        return self._hash

    @property
    def children(self) -> tuple["Term", ...]:
        return ()


@dataclass(frozen=True, slots=True)
class Number(Term):
    value: Fraction
    __hash__ = Term.__hash__


@dataclass(frozen=True, slots=True)
class ApproxNumber(Term):
    """A deliberately inexact real number produced by ``numeric``.

    ``text`` stores the already-rounded decimal representation.  Approximate
    values are kept distinct from :class:`Number`: decimal literals in source
    are exact rationals, while this node explicitly records loss of exactness.
    """

    text: str
    digits: int
    __hash__ = Term.__hash__


class TruthValue(str, Enum):
    TRUE = 'True'
    FALSE = 'False'
    UNKNOWN = 'Unknown'

    def __bool__(self):
        if self is TruthValue.UNKNOWN:
            raise TypeError('Unknown is not a boolean decision')
        return self is TruthValue.TRUE


@dataclass(frozen=True, slots=True)
class Predicate(Term):
    """A mathematical assertion, distinct from an arithmetic expression."""
    __hash__ = Term.__hash__

    def __bool__(self):
        raise TypeError('Query a predicate before using it as a boolean')


@dataclass(frozen=True, slots=True)
class Truth(Predicate):
    value: TruthValue
    __hash__ = Term.__hash__

    def __bool__(self):
        return bool(self.value)


@dataclass(frozen=True, slots=True)
class Comparison(Predicate):
    op: str
    left: Term
    right: Term
    __hash__ = Term.__hash__

    @property
    def children(self):
        return (self.left, self.right)


@dataclass(frozen=True, slots=True)
class Logical(Predicate):
    op: str
    operands: tuple[Term, ...]
    __hash__ = Term.__hash__

    @property
    def children(self):
        return self.operands


@dataclass(frozen=True, slots=True)
class Defined(Predicate):
    expression: Term
    __hash__ = Term.__hash__

    @property
    def children(self):
        return (self.expression,)


@dataclass(frozen=True, slots=True)
class ForAll(Predicate):
    parameters: tuple['Symbol', ...]
    body: Term
    __hash__ = Term.__hash__

    @property
    def children(self):
        return (*self.parameters, self.body)


@dataclass(frozen=True, slots=True)
class Symbol(Term):
    name: str
    kind: SymbolKind
    annotation: Type | None = None
    # Equal spellings in different scopes must remain distinct symbols.
    identity: UUID = field(default_factory=uuid4, repr=False)
    __hash__ = Term.__hash__


def builtin_symbol(name: str) -> Symbol:
    """Builtins denote the same mathematical operation across sessions."""
    return Symbol(name, SymbolKind.BUILTIN, identity=uuid5(NAMESPACE_URL, "mathlang:builtin:" + name))


@dataclass(frozen=True, slots=True)
class Unary(Term):
    op: str
    operand: Term
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.operand,)


@dataclass(frozen=True, slots=True)
class Binary(Term):
    op: str
    left: Term
    right: Term
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, slots=True)
class FunctionCall(Term):
    callee: Term
    arguments: tuple[Term, ...]
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.callee, *self.arguments)


@dataclass(frozen=True, slots=True)
class Function(Term):
    parameters: tuple[Symbol, ...]
    body: Term
    return_type: Type | None = None
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (*self.parameters, self.body)


@dataclass(frozen=True, slots=True)
class Substitution(Term):
    expression: Term
    replacements: tuple[tuple[Symbol, Term], ...]
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.expression, *(value for _, value in self.replacements))


@dataclass(frozen=True, slots=True)
class RuleSet(Term):
    name: str | None
    rules: tuple["RewriteRule", ...]
    __hash__ = Term.__hash__

    @property
    def termination(self) -> str:
        return "unknown"

    @property
    def confluence(self) -> str:
        return "unknown"


@dataclass(frozen=True, slots=True)
class RewriteRequest(Term):
    expression: Term
    rules: Term
    strategy: str = "bottom_up"
    repeat: bool = False
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.expression, self.rules)


@dataclass(frozen=True, slots=True)
class Approach(Term):
    variable: Term
    point: Term
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.variable, self.point)


@dataclass(frozen=True, slots=True)
class CalculusOperator(Term):
    operation: str
    variable: Term
    order: Term
    point: Term | None = None
    upper: Term | None = None
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.variable, self.order, *((self.point,) if self.point is not None else ()),
                *((self.upper,) if self.upper is not None else ()))


@dataclass(frozen=True, slots=True)
class CalculusRequest(Term):
    operator: CalculusOperator
    expression: Term
    __hash__ = Term.__hash__

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.operator, self.expression)


@dataclass(frozen=True, slots=True)
class TaylorSeries(Term):
    variable: Symbol
    point: Term
    coefficients: tuple[Term, ...]
    __hash__ = Term.__hash__

    @property
    def order(self) -> int:
        return len(self.coefficients)

    @property
    def children(self) -> tuple[Term, ...]:
        return (self.variable, self.point, *self.coefficients)

    def polynomial(self, factory: "TermFactory") -> Term:
        delta = (self.variable if isinstance(self.point, Number) and self.point.value == 0
                 else factory.binary("-", self.variable, self.point))
        result: Term = factory.number(0)
        for exponent, coefficient in enumerate(self.coefficients):
            if isinstance(coefficient, Number) and coefficient.value == 0:
                continue
            negative = isinstance(coefficient, Number) and coefficient.value < 0
            if negative:
                coefficient = factory.number(-coefficient.value)
            if isinstance(coefficient, Unary) and coefficient.op == "-":
                coefficient, negative = coefficient.operand, not negative
            power = delta if exponent == 1 else factory.binary("^", delta, factory.number(exponent))
            term = coefficient if exponent == 0 else (power if isinstance(coefficient, Number) and coefficient.value == 1
                                                     else factory.binary("*", coefficient, power))
            result = ((factory.unary("-", term) if negative else term)
                      if isinstance(result, Number) and result.value == 0
                      else factory.binary("-" if negative else "+", result, term))
        return result


def free_symbols(term: Term) -> frozenset[Symbol]:
    """Free symbol identities, with function and substitution scopes respected."""
    memo: dict[Term, frozenset[Symbol]] = {}
    stack = [(term, False)]
    while stack:
        node, ready = stack.pop()
        if node in memo:
            continue
        if not ready:
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node.children))
            continue
        if isinstance(node, Symbol):
            result = frozenset({node})
        elif isinstance(node, (Function, ForAll)):
            result = memo[node.body].difference(node.parameters)
        elif isinstance(node, Substitution):
            targets = (symbol for symbol, _ in node.replacements)
            result = memo[node.expression].difference(targets)
            result = result.union(*(memo[value] for _, value in node.replacements))
        else:
            result = frozenset().union(*(memo[child] for child in node.children))
        memo[node] = result
    return memo[term]


class TermFactory:
    """Hash-cons terms: one live object per structure within this factory."""

    def __init__(self) -> None:
        self._pool: WeakValueDictionary[tuple, Term] = WeakValueDictionary()

    def _intern(self, cls, *parts):
        key = (cls, *parts)
        existing = self._pool.get(key)
        if existing is not None:
            return existing
        term = cls(*parts)
        self._pool[key] = term
        return term

    def number(self, value: str | int | Fraction) -> Number:
        return self._intern(Number, Fraction(value))

    def approximate(self, text: str, digits: int) -> ApproxNumber:
        return self._intern(ApproxNumber, text, digits)

    def unary(self, op: str, operand: Term) -> Unary:
        return self._intern(Unary, op, operand)

    def binary(self, op: str, left: Term, right: Term) -> Binary:
        return self._intern(Binary, op, left, right)

    def comparison(self, op: str, left: Term, right: Term) -> Comparison:
        return self._intern(Comparison, '==' if op == '=' else op, left, right)

    def logical(self, op: str, *operands: Term) -> Logical:
        return self._intern(Logical, op, tuple(operands))

    def truth(self, value: TruthValue) -> Truth:
        return self._intern(Truth, value)

    def function(self, parameters: tuple[Symbol, ...], body: Term, return_type: Type | None = None) -> Function:
        return self._intern(Function, parameters, body, return_type)

    def substitution(self, expression: Term, replacements: tuple[tuple[Symbol, Term], ...]) -> Substitution:
        return self._intern(Substitution, expression, replacements)

    def rewrite(self, expression: Term, rules: Term, strategy: str = "bottom_up",
                repeat: bool = False) -> RewriteRequest:
        return self._intern(RewriteRequest, expression, rules, strategy, repeat)

    def call(self, callee: Term, arguments: tuple[Term, ...], *, checker=None) -> Term:
        if isinstance(callee, CalculusOperator):
            if len(arguments) != 1:
                raise ValueError("A calculus operator expects one expression or function")
            return self._intern(CalculusRequest, callee, arguments[0])
        if isinstance(callee, Function):
            if len(arguments) != len(callee.parameters):
                raise ValueError(
                    f"Expected {len(callee.parameters)} arguments, got {len(arguments)}"
                )
            from .elaboration import Elaborator
            checker = Elaborator() if checker is None else checker
            checker.check_call(callee, arguments)
            result = self.substitute(callee.body, dict(zip(callee.parameters, arguments)), checker=checker)
            checker.infer(result)
            if callee.return_type is not None:
                checker.require(result, callee.return_type, "Function result", allow_unknown=True)
            return result
        if not isinstance(callee, (Symbol, FunctionCall)):
            raise ValueError("Only a function or symbolic name can be called")
        if isinstance(callee, Symbol) and callee.annotation is not None:
            annotation = callee.annotation
            if annotation.name not in ("Function", "CalculusOperator"):
                raise ValueError(f"Cannot call {callee.name!r} with annotation {annotation}")
            if annotation.arguments and len(arguments) != len(annotation.arguments)-1:
                raise ValueError(f"Expected {len(annotation.arguments)-1} arguments, got {len(arguments)}")
            from .elaboration import Elaborator
            (Elaborator() if checker is None else checker).check_call(callee, arguments)
        return self._intern(FunctionCall, callee, arguments)

    def substitute(self, term: Term, replacements: dict[Symbol, Term], *, checker=None) -> Term:
        """Simultaneous substitution by symbol identity, preserving lexical scope."""
        if not replacements:
            return term
        memo: dict[Term, Term] = {}

        def substitute(node, bindings):
            return self.substitute(node, bindings, checker=checker)

        def visit(node: Term) -> Term:
            if node in memo:
                return memo[node]
            match node:
                case Symbol():
                    result = replacements.get(node, node)
                case Number() | RuleSet() | Truth():
                    result = node
                case Comparison(op=op, left=left, right=right):
                    result = self.comparison(op, visit(left), visit(right))
                case Logical(op=op, operands=operands):
                    result = self.logical(op, *map(visit, operands))
                case Defined(expression=expression):
                    result = self._intern(Defined, visit(expression))
                case ForAll(parameters=parameters, body=body):
                    # Reuse the capture-avoiding function binder implementation.
                    mapped = substitute(self.function(parameters, body), replacements)
                    result = self._intern(ForAll, mapped.parameters, mapped.body)
                case Unary(op=op, operand=operand):
                    result = self.unary(op, visit(operand))
                case Binary(op=op, left=left, right=right):
                    result = self.binary(op, visit(left), visit(right))
                case FunctionCall(callee=callee, arguments=arguments):
                    result = self.call(visit(callee), tuple(map(visit, arguments)), checker=checker)
                case Function(parameters=parameters, body=body):
                    free = {key: value for key, value in replacements.items()
                            if key in free_symbols(node)}
                    if not free:
                        result = node
                    else:
                        captures = frozenset().union(*(free_symbols(value) for value in free.values()))
                        fresh = tuple(Symbol(p.name, p.kind, p.annotation) if p in captures else p
                                      for p in parameters)
                        renames = {p: q for p, q in zip(parameters, fresh) if p is not q}
                        renamed = substitute(body, renames)
                        result = self.function(fresh, substitute(renamed, free), node.return_type)
                case Substitution(expression=expression, replacements=bindings):
                    # A delayed explicit substitution keeps its targets symbolic.
                    # A function argument may itself introduce occurrences of a
                    # target: replace_x(t)=substitute(t, x=2); replace_x(x^2).
                    targets = {symbol for symbol, _ in bindings}
                    external = {s: value for s, value in replacements.items() if s not in targets}
                    result = self.substitution(substitute(expression, external), tuple(
                        (symbol, visit(value)) for symbol, value in bindings
                    ))
                case RewriteRequest(expression=expression, rules=rules, strategy=strategy, repeat=repeat):
                    result = self.rewrite(visit(expression), visit(rules), strategy, repeat)
                case Approach(variable=variable, point=point):
                    result = self._intern(Approach, visit(variable), visit(point))
                case CalculusOperator(operation=operation, variable=variable, order=order, point=point, upper=upper):
                    result = self._intern(CalculusOperator, operation, visit(variable), visit(order),
                                          None if point is None else visit(point), None if upper is None else visit(upper))
                case CalculusRequest(operator=operator, expression=expression):
                    # Differentiate/integrate in the symbolic coordinate before
                    # evaluating a function argument at a particular value.
                    variable = operator.variable
                    external = {s: value for s, value in replacements.items() if s != variable}
                    request = self._intern(CalculusRequest, substitute(operator, external),
                                           substitute(expression, external))
                    result = (self.substitution(request, ((variable, replacements[variable]),))
                              if variable in replacements else request)
                case TaylorSeries(variable=variable, point=point, coefficients=coefficients):
                    target = visit(variable)
                    if not isinstance(target, Symbol):
                        raise ValueError("Cannot evaluate a series by substitution; use polynomial(series) for its explicit approximation")
                    new_point = visit(point)
                    new_coefficients = tuple(map(visit, coefficients))
                    if target in free_symbols(new_point) or any(target in free_symbols(c) for c in new_coefficients):
                        raise ValueError("Series coefficients and expansion point must be independent of its variable")
                    result = self._intern(TaylorSeries, target, new_point, new_coefficients)
                case _:
                    if not node.children:
                        result = node
                    else:
                        raise TypeError(f"Unsupported term: {type(node).__name__}")
            memo[node] = result
            return result

        return visit(term)
