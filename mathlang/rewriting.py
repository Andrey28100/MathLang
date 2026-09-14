"""Structural patterns and bounded, deterministic rewriting of immutable terms.

Rules are directed user declarations, not proofs. Matching never reorders
operands or silently invokes the scalar normalizer. Binders remain opaque.
"""

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Callable

from .normalization import Limits
from .terms import (
    CalculusOperator,
    Binary, Function, FunctionCall, Number, RewriteRequest, RuleSet, Substitution,
    Symbol, Term, TermFactory, Unary,
    Comparison, Defined, Logical, TruthValue,
)


class RewriteError(ValueError):
    """An invalid rule, unsupported strategy, cycle, or exhausted rewrite budget."""


@dataclass(frozen=True, slots=True)
class Pattern:
    @property
    def children(self) -> tuple["Pattern", ...]:
        return ()


@dataclass(frozen=True, slots=True)
class Wildcard(Pattern):
    name: str


@dataclass(frozen=True, slots=True)
class LiteralPattern(Pattern):
    value: Term


@dataclass(frozen=True, slots=True)
class UnaryPattern(Pattern):
    op: str
    operand: Pattern

    @property
    def children(self) -> tuple[Pattern, ...]:
        return (self.operand,)


@dataclass(frozen=True, slots=True)
class BinaryPattern(Pattern):
    op: str
    left: Pattern
    right: Pattern

    @property
    def children(self) -> tuple[Pattern, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, slots=True)
class CallPattern(Pattern):
    callee: Pattern
    arguments: tuple[Pattern, ...]

    @property
    def children(self) -> tuple[Pattern, ...]:
        return (self.callee, *self.arguments)


def wildcard_names(pattern: Pattern) -> frozenset[str]:
    names: set[str] = set()
    stack = [pattern]
    while stack:
        node = stack.pop()
        if isinstance(node, Wildcard):
            names.add(node.name)
        stack.extend(node.children)
    return frozenset(names)


@dataclass(frozen=True, slots=True)
class RuleCondition:
    left: Pattern
    op: str
    right: Pattern

    def __post_init__(self) -> None:
        if self.op not in ("==", "!=", "<", "<=", ">", ">="):
            raise RewriteError(f"Unsupported rule comparison {self.op!r}")


@dataclass(frozen=True, slots=True)
class RewriteRule:
    pattern: Pattern
    replacement: Pattern
    condition: RuleCondition | None = None

    def __post_init__(self) -> None:
        available = wildcard_names(self.pattern)
        required = wildcard_names(self.replacement)
        if self.condition is not None:
            required |= wildcard_names(self.condition.left) | wildcard_names(self.condition.right)
        if missing := required - available:
            raise RewriteError("Unbound rule placeholders: " + ", ".join(sorted(missing)))


class RewriteStrategy(str, Enum):
    ONCE = "once"
    BOTTOM_UP = "bottom_up"
    TOP_DOWN = "top_down"


@dataclass(frozen=True, slots=True)
class RewriteResult:
    term: Term
    applications: int
    passes: int


class _Budget:
    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self.steps = 0
        self.applications = 0

    def tick(self) -> None:
        self.steps += 1
        if self.steps > self.limits.max_steps:
            raise RewriteError("Rewrite computation step limit exceeded")

    def applied(self) -> None:
        self.applications += 1
        if self.applications > self.limits.max_rewrites:
            raise RewriteError("Rewrite application limit exceeded")


def structurally_equal(left: Term, right: Term, tick: Callable[[], None] = lambda: None) -> bool:
    """Compare a DAG without recursive equality or exponential repeated work."""
    stack = [(left, right)]
    seen: set[tuple[int, int]] = set()
    while stack:
        a, b = stack.pop()
        tick()
        if a is b:
            continue
        pair = (id(a), id(b))
        if pair in seen:
            continue
        seen.add(pair)
        if type(a) is not type(b) or hash(a) != hash(b):
            return False
        if not a.children:
            if a != b:
                return False
        elif hasattr(a, 'op') and a.op != b.op:
            return False
        elif isinstance(a, Substitution):
            if tuple(s for s, _ in a.replacements) != tuple(s for s, _ in b.replacements):
                return False
        elif isinstance(a, RewriteRequest):
            if (a.strategy, a.repeat) != (b.strategy, b.repeat):
                return False
        elif isinstance(a, CalculusOperator) and a.operation != b.operation:
            return False
        elif isinstance(a, Function) and a.return_type != b.return_type:
            return False
        if len(a.children) != len(b.children):
            return False
        stack.extend(zip(a.children, b.children))
    return True


class Matcher:
    def __init__(self, limits: Limits | None = None) -> None:
        self.limits = Limits() if limits is None else limits

    def match(self, pattern: Pattern, term: Term) -> dict[str, Term] | None:
        return self._match(pattern, term, _Budget(self.limits))

    @staticmethod
    def _match(pattern: Pattern, term: Term, budget: _Budget) -> dict[str, Term] | None:
        bindings: dict[str, Term] = {}
        stack = [(pattern, term)]
        while stack:
            template, node = stack.pop()
            budget.tick()
            match template:
                case Wildcard(name=name):
                    previous = bindings.get(name)
                    if previous is not None and not structurally_equal(previous, node, budget.tick):
                        return None
                    bindings[name] = node
                case LiteralPattern(value=value):
                    if not structurally_equal(value, node, budget.tick):
                        return None
                case UnaryPattern(op=op, operand=operand):
                    if not isinstance(node, Unary) or node.op != op:
                        return None
                    stack.append((operand, node.operand))
                case BinaryPattern(op=op, left=left, right=right):
                    if not isinstance(node, Binary) or node.op != op:
                        return None
                    stack.extend(((right, node.right), (left, node.left)))
                case CallPattern(callee=callee, arguments=arguments):
                    if not isinstance(node, FunctionCall) or len(arguments) != len(node.arguments):
                        return None
                    stack.extend(reversed(tuple(zip(arguments, node.arguments))))
                    stack.append((callee, node.callee))
                case _:
                    raise RewriteError(f"Unsupported pattern {type(template).__name__}")
        return bindings


class Rewriter:
    def __init__(self, factory: TermFactory, limits: Limits | None = None) -> None:
        self.factory = factory
        self.limits = Limits() if limits is None else limits

    def apply(self, term: Term, rules: RuleSet | tuple[RewriteRule, ...], *,
              strategy: RewriteStrategy | str = RewriteStrategy.BOTTOM_UP,
              repeat: bool = False, query=None) -> RewriteResult:
        try:
            strategy = RewriteStrategy(strategy)
        except ValueError:
            raise RewriteError(f"Unknown rewrite strategy {strategy!r}") from None
        if strategy == RewriteStrategy.ONCE and repeat:
            raise RewriteError("'once' cannot be combined with recursive rewriting")
        selected = rules.rules if isinstance(rules, RuleSet) else tuple(rules)
        computation = _Rewriting(self.factory, self.limits, selected, query)
        try:
            return computation.run(term, strategy, repeat)
        except RecursionError:
            raise RewriteError("Expression or pattern nesting is too deep to rewrite") from None


class _Rewriting:
    def __init__(self, factory: TermFactory, limits: Limits, rules: tuple[RewriteRule, ...], query=None) -> None:
        self.f = factory
        self.budget = _Budget(limits)
        self.rules = rules
        self.query = query

    def instantiate(self, pattern: Pattern, bindings: dict[str, Term]) -> Term:
        memo: dict[int, Term] = {}
        stack = [(pattern, False)]
        while stack:
            node, ready = stack.pop()
            if id(node) in memo:
                continue
            self.budget.tick()
            if not ready:
                stack.append((node, True))
                stack.extend((child, False) for child in reversed(node.children))
                continue
            match node:
                case Wildcard(name=name):
                    result = bindings[name]
                case LiteralPattern(value=value):
                    result = value
                case UnaryPattern(op=op, operand=operand):
                    result = self.f.unary(op, memo[id(operand)])
                case BinaryPattern(op=op, left=left, right=right):
                    result = self.f.binary(op, memo[id(left)], memo[id(right)])
                case CallPattern(callee=callee, arguments=arguments):
                    try:
                        result = self.f.call(memo[id(callee)], tuple(memo[id(a)] for a in arguments))
                    except ValueError as error:
                        raise RewriteError(f"Invalid replacement call: {error}") from None
                case _:
                    raise RewriteError(f"Unsupported pattern {type(node).__name__}")
            memo[id(node)] = result
        return memo[id(pattern)]

    def numeric(self, term: Term) -> Fraction | None:
        """Evaluate only rational arithmetic; a symbolic or undefined test is unknown."""
        memo: dict[Term, Fraction | None] = {}
        stack = [(term, False)]
        while stack:
            node, ready = stack.pop()
            if node in memo:
                continue
            self.budget.tick()
            if not ready:
                stack.append((node, True))
                children = node.children if isinstance(node, (Unary, Binary)) else ()
                stack.extend((child, False) for child in reversed(children))
                continue
            value = None
            if isinstance(node, Number):
                value = node.value
            elif isinstance(node, Unary) and memo[node.operand] is not None:
                value = memo[node.operand] if node.op == "+" else -memo[node.operand]
            elif isinstance(node, Binary):
                a, b = memo[node.left], memo[node.right]
                if a is not None and b is not None:
                    if node.op == "+":
                        value = a+b
                    elif node.op == "-":
                        value = a-b
                    elif node.op == "*":
                        value = a*b
                    elif node.op == "/" and b:
                        value = a/b
                    elif node.op == "^" and b.denominator == 1 and not (a == 0 and b <= 0):
                        exponent = int(b)
                        if abs(exponent) > self.budget.limits.max_power:
                            raise RewriteError("Rule condition power limit exceeded")
                        bits = max(a.numerator.bit_length(), a.denominator.bit_length())
                        if (bits-1) * abs(exponent) > self.budget.limits.max_integer_bits:
                            raise RewriteError("Rule condition number size limit exceeded")
                        value = a ** exponent
            if value is not None and max(value.numerator.bit_length(), value.denominator.bit_length()) > self.budget.limits.max_integer_bits:
                raise RewriteError("Rule condition number size limit exceeded")
            memo[node] = value
        return memo[term]

    def allowed(self, condition: RuleCondition | None, bindings: dict[str, Term]) -> bool:
        if condition is None:
            return True
        left = self.instantiate(condition.left, bindings)
        right = self.instantiate(condition.right, bindings)
        a = self.numeric(left)
        b = self.numeric(right)
        if a is None or b is None:
            return self.query is not None and self.query(Comparison(condition.op, left, right)) is TruthValue.TRUE
        return {"==": a == b, "!=": a != b, "<": a < b,
                "<=": a <= b, ">": a > b, ">=": a >= b}[condition.op]

    def at_root(self, term: Term) -> Term:
        for rule in self.rules:
            self.budget.tick()
            bindings = Matcher._match(rule.pattern, term, self.budget)
            if bindings is None or not self.allowed(rule.condition, bindings):
                continue
            result = self.instantiate(rule.replacement, bindings)
            if structurally_equal(term, result, self.budget.tick):
                continue
            self.budget.applied()
            self.check_size(result)
            return result
        return term

    @staticmethod
    def children(term: Term) -> tuple[Term, ...]:
        if isinstance(term, FunctionCall):
            return term.arguments
        return term.children if isinstance(term, (Unary, Binary, Comparison, Logical, Defined)) else ()

    def rebuild(self, term: Term, children: tuple[Term, ...]) -> Term:
        if all(a is b for a, b in zip(self.children(term), children)):
            return term
        if isinstance(term, Unary):
            return self.f.unary(term.op, children[0])
        if isinstance(term, Binary):
            return self.f.binary(term.op, *children)
        if isinstance(term, Comparison):
            return self.f.comparison(term.op, *children)
        if isinstance(term, Logical):
            return self.f.logical(term.op, *children)
        if isinstance(term, Defined):
            return self.f._intern(Defined, children[0])
        if isinstance(term, FunctionCall):
            return self.f.call(term.callee, children)
        return term

    def once(self, term: Term) -> Term:
        # A zipper replaces exactly one tree occurrence, even if two edges share
        # the same DAG node. It does not replace both occurrences via memoization.
        stack = [(term, None)]
        while stack:
            node, path = stack.pop()
            self.budget.tick()
            replacement = self.at_root(node)
            if replacement is not node:
                while path is not None:
                    parent, index, path = path
                    children = list(self.children(parent))
                    children[index] = replacement
                    replacement = self.rebuild(parent, tuple(children))
                return replacement
            children = self.children(node)
            for index in reversed(range(len(children))):
                stack.append((children[index], (node, index, path)))
        return term

    def pass_(self, term: Term, strategy: RewriteStrategy) -> Term:
        if strategy == RewriteStrategy.ONCE:
            return self.once(term)
        memo: dict[Term, Term] = {}
        stack = [(term, None)]
        while stack:
            original, processed = stack.pop()
            if original in memo:
                continue
            self.budget.tick()
            if processed is None:
                processed = self.at_root(original) if strategy == RewriteStrategy.TOP_DOWN else original
                stack.append((original, processed))
                stack.extend((child, None) for child in reversed(self.children(processed)))
            else:
                result = self.rebuild(processed, tuple(memo[child] for child in self.children(processed)))
                if strategy == RewriteStrategy.BOTTOM_UP:
                    result = self.at_root(result)
                memo[original] = result
        return memo[term]

    def check_size(self, term: Term) -> None:
        seen: set[int] = set()
        stack = [term]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            self.budget.tick()
            seen.add(id(node))
            if len(seen) > self.budget.limits.max_nodes:
                raise RewriteError("Rewritten expression node limit exceeded")
            stack.extend(node.children)

    def run(self, term: Term, strategy: RewriteStrategy, repeat: bool) -> RewriteResult:
        self.check_size(term)
        seen: dict[int, list[Term]] = {hash(term): [term]}
        for pass_number in range(1, self.budget.limits.max_passes+1):
            before = self.budget.applications
            term = self.pass_(term, strategy)
            self.check_size(term)
            if not repeat or self.budget.applications == before:
                return RewriteResult(term, self.budget.applications, pass_number)
            previous = seen.setdefault(hash(term), [])
            if any(structurally_equal(term, old, self.budget.tick) for old in previous):
                raise RewriteError("Rewrite cycle detected; rules are not known to terminate")
            previous.append(term)
        raise RewriteError("Rewrite pass limit exceeded")


def rewrite(term: Term, rules: RuleSet | tuple[RewriteRule, ...], *,
            factory: TermFactory | None = None, strategy: RewriteStrategy | str = RewriteStrategy.BOTTOM_UP,
            repeat: bool = False, limits: Limits | None = None) -> Term:
    rewriter = Rewriter(TermFactory() if factory is None else factory, limits)
    return rewriter.apply(term, rules, strategy=strategy, repeat=repeat).term
