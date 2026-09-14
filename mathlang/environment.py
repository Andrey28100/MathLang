"""Lexical environments store declarations and immutable definitions, not cells."""

from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterator, Mapping

from .terms import RuleSet, Symbol, SymbolKind, Term, builtin_symbol
from .symbols import canonical_name


@dataclass(frozen=True, slots=True)
class Definition:
    symbol: Symbol
    value: Term | None = None

    @property
    def term(self) -> Term:
        return self.symbol if self.value is None else self.value


class Environment:
    def __init__(self, parent: "Environment | None" = None) -> None:
        from .logic import Context
        self.parent = parent
        self.context = Context() if parent is None else parent.context
        self._definitions: dict[str, Definition] = {}
        self._rule_order: list[RuleSet] = []
        self.active_algebra = None
        self.active_namespace = None
        self.imported_modules: dict[str, object] = {}

    @property
    def definitions(self) -> Mapping[str, Definition]:
        return MappingProxyType(self._definitions)

    def child(self) -> "Environment":
        return Environment(self)

    def get(self, name: str) -> Definition | None:
        name = '.'.join(canonical_name(part) for part in name.split('.'))
        if "." in name:
            first, *parts = name.split(".")
            definition = self.get(first)
            for part in parts:
                owner = None if definition is None else definition.term
                if hasattr(owner, "definition"):
                    definition = owner.definition(part)
                elif hasattr(owner, "member"):
                    member = owner.member(part)
                    definition = (None if member is None else Definition(member)
                                  if isinstance(member, Symbol) else Definition(Symbol(part, SymbolKind.CONSTANT), member))
                else:
                    return None
            return definition
        scope: Environment | None = self
        while scope is not None:
            if name in scope._definitions:
                return scope._definitions[name]
            if scope.active_namespace is not None:
                member = scope.active_namespace.definition(name)
                if member is not None:
                    return member
            if scope.active_algebra is not None:
                member = scope.active_algebra.member(name)
                if member is not None:
                    return Definition(member) if isinstance(member, Symbol) else Definition(Symbol(name, SymbolKind.CONSTANT), member)
            scope = scope.parent
        return None

    def __getitem__(self, name: str) -> Definition:
        definition = self.get(name)
        if definition is None:
            raise KeyError(name)
        return definition

    def define(self, definition: Definition, *, replace: bool = False) -> None:
        name = definition.symbol.name
        if definition.symbol.kind == SymbolKind.RULE and not isinstance(definition.value, RuleSet):
            raise ValueError("Rule definitions must contain a RuleSet")
        previous = self._definitions.get(name)
        if previous is not None:
            if not replace:
                raise ValueError(f"Name {name!r} is already declared in this scope")
            if previous.symbol.kind not in (SymbolKind.EXPRESSION, SymbolKind.FUNCTION):
                raise ValueError(
                    f"Cannot redefine {previous.symbol.kind.value} {name!r}"
                )
        self._definitions[name] = definition
        if definition.symbol.kind == SymbolKind.RULE:
            self._rule_order.append(definition.value)

    def add_anonymous_rules(self, rules: RuleSet) -> None:
        if rules.name is not None:
            raise ValueError("Named rule sets must be declared as definitions")
        self._rule_order.append(rules)

    @property
    def local_rule_sets(self) -> tuple[RuleSet, ...]:
        return tuple(self._rule_order)

    def visible_rules(self) -> RuleSet:
        scopes: list[Environment] = []
        scope: Environment | None = self
        while scope is not None:
            scopes.append(scope)
            scope = scope.parent
        rules = []
        for scope in reversed(scopes):
            groups = list(scope._rule_order)
            definitions = list(scope.definitions.values())
            if scope.active_namespace is not None:
                groups = list(scope.active_namespace.rules) + groups
                definitions = list(scope.active_namespace.definitions) + definitions
            for group in groups:
                names = [d.symbol.name for d in definitions if d.value is group]
                if group.name is None or any(self.get(n) is not None and self.get(n).term is group for n in names):
                    rules.extend(group.rules)
        return RuleSet(None, tuple(rules))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """An unsuccessful input must not partially change the session's memory."""
        snapshot = self._definitions.copy()
        rule_snapshot = self._rule_order.copy()
        algebra_snapshot = self.active_algebra
        namespace_snapshot = self.active_namespace
        imports_snapshot = self.imported_modules.copy()
        context_snapshot = self.context
        try:
            yield
        except BaseException:
            self.context = context_snapshot
            self._definitions.clear()
            self._definitions.update(snapshot)
            self._rule_order[:] = rule_snapshot
            self.active_algebra = algebra_snapshot
            self.active_namespace = namespace_snapshot
            self.imported_modules.clear()
            self.imported_modules.update(imports_snapshot)
            raise


def builtin_environment() -> Environment:
    environment = Environment()
    # Most names below are symbolic transformations/functions. ``numeric`` is
    # intentionally explicit and is the only builtin here that introduces an
    # inexact decimal approximation.
    for name in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs", "print",
                 "query", "domain",
                 "iterate", "sum", "product", "all", "any", "factorial", "antiderivative",
                 "normalize", "simplify", "substitute", "rewrite", "derivative",
                 "integrate", "series", "limit", "polynomial", "numeric"):
        environment.define(Definition(builtin_symbol(name)))
    return environment
