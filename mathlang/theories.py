"""Generic theory contracts and bounded, independently checked implementations.

Abstract operations are ordinary typed symbols. Axioms are obligations, never
rewrite rules. Concrete polynomial identities reuse the existing proof checker;
other obligations keep an explicit unknown/assumed status.
"""

from dataclasses import dataclass, replace
from itertools import islice, product
from uuid import uuid4, uuid5

from .elaboration import Elaborator, SCALARS, scalar_rank, validate_type
from .environment import Definition
from .normalization import Limits
from .proof import EqualityGoal, Proof, ProofSearch, check_proof
from .algebra import AlgebraDefinition
from .symbols import valid_name
from .terms import (Binary, Comparison, Defined, ForAll, Function, FunctionCall,
                    Logical, Number, Symbol, SymbolKind, Term, TermFactory,
                    Truth, TruthValue, Type, Unary, free_symbols)


class TheoryError(ValueError):
    pass


OPERATOR_NAMES = {('+', 2): 'add', ('-', 2): 'subtract', ('-', 1): 'negate',
                  ('+', 1): 'positive', ('*', 2): 'multiply', ('/', 2): 'divide', ('^', 2): 'power'}
STATUSES = ('proved', 'disproved', 'unknown', 'assumed')


@dataclass(frozen=True, slots=True)
class TheoryOperation:
    spelling: str
    symbol: Symbol


@dataclass(frozen=True, slots=True)
class Axiom:
    name: str
    statement: Term


@dataclass(frozen=True, slots=True)
class TheoryParent:
    theory: 'Theory'
    arguments: tuple[Type, ...]

    def __str__(self):
        return self.theory.name + '<' + ', '.join(map(str, self.arguments)) + '>'


@dataclass(frozen=True, slots=True)
class Theory(Term):
    name: str
    parameters: tuple[Type, ...]
    operations: tuple[TheoryOperation, ...]
    constants: tuple[Symbol, ...]
    axioms: tuple[Axiom, ...]
    parents: tuple[TheoryParent, ...] = ()
    __hash__ = Term.__hash__

    @property
    def definitions(self):
        return (*[Definition(o.symbol) for o in self.operations],
                *[Definition(c) for c in self.constants],
                *[Definition(Symbol(a.name, SymbolKind.EXPRESSION), a.statement) for a in self.axioms])

    def definition(self, name):
        return next((d for d in self.definitions if d.symbol.name == name), None)

    def member(self, name):
        found = self.definition(name)
        return None if found is None else found.term

    def origins(self, name):
        """Original declaring theories, with shared diamond ancestors shown once."""
        name = name.removeprefix('_total_')
        def has_member(theory):
            return (any(o.symbol.name == name for o in theory.operations)
                    or any(c.name == name for c in theory.constants)
                    or any(a.name == name for a in theory.axioms))
        result, seen, stack = [], set(), [self]
        while stack:
            theory = stack.pop()
            if id(theory) in seen:
                continue
            seen.add(id(theory))
            parents = [p.theory for p in theory.parents if has_member(p.theory)]
            if parents:
                stack.extend(reversed(parents))
            elif has_member(theory):
                result.append(theory.name)
        return tuple(dict.fromkeys(result))


@dataclass(frozen=True, slots=True)
class PropertyResult(Term):
    name: str
    statement: Term
    status: str
    method: str
    proofs: tuple[Proof, ...] = ()
    counterexample: tuple[Term, ...] = ()
    algebras: tuple[AlgebraDefinition, ...] = ()
    __hash__ = Term.__hash__

    def member(self, name):
        if name == 'statement':
            return self.statement
        if name in STATUSES:
            return Truth(TruthValue.TRUE if self.status == name else TruthValue.FALSE)
        return None


@dataclass(frozen=True, slots=True)
class Implementation(Term):
    name: str
    theory: Theory
    arguments: tuple[Type, ...]
    bindings: tuple[Definition, ...]
    properties: tuple[PropertyResult, ...]
    algebras: tuple[AlgebraDefinition, ...] = ()
    __hash__ = Term.__hash__

    @property
    def valid(self):
        states = {p.status for p in self.properties}
        return (TruthValue.FALSE if 'disproved' in states else
                TruthValue.TRUE if states <= {'proved'} else TruthValue.UNKNOWN)

    @property
    def definitions(self):
        return (*self.bindings,
                *[Definition(Symbol(p.name, SymbolKind.EXPRESSION), p) for p in self.properties],
                Definition(Symbol('valid', SymbolKind.EXPRESSION), Truth(self.valid)))

    def definition(self, name):
        return next((d for d in self.definitions if d.symbol.name == name), None)

    def member(self, name):
        found = self.definition(name)
        return None if found is None else found.term


def type_key(type_):
    return (type_.name, str(type_.identity), tuple(type_key(a) if isinstance(a, Type) else a for a in type_.arguments))


def replace_type(type_, substitutions):
    if type_ in substitutions:
        return substitutions[type_]
    return Type(type_.name, tuple(replace_type(a, substitutions) if isinstance(a, Type) else a
                                 for a in type_.arguments), type_.identity)


def strip_forall(statement):
    parameters = []
    while isinstance(statement, ForAll):
        parameters.extend(statement.parameters)
        statement = statement.body
    if len(set(parameters)) != len(parameters):
        raise TheoryError('Nested quantifiers must have distinct symbol identities')
    return tuple(parameters), statement


def instances(statement, factory, limits, algebras):
    """A bounded witness search, never a finite-sampling proof of universality."""
    from .algebra import word_term
    parameters, body = strip_forall(statement)
    if len(parameters) > 8:
        return
    domains = []
    for parameter in parameters:
        type_ = parameter.annotation
        if scalar_rank(type_) is not None:
            values = (0, 1, 2) if type_ == Type('Nat') else (0, 1, -1, 2)
            domain = tuple(factory.number(n) for n in values)
        elif type_ == Type('Predicate'):
            domain = (factory.truth(TruthValue.FALSE), factory.truth(TruthValue.TRUE))
        elif type_ is not None and type_.identity in algebras:
            algebra = algebras[type_.identity]
            if algebra.basis is None:
                return
            domain = (factory.number(0), *[word_term(algebra, w, factory) for w in algebra.basis])
        else:
            return
        domains.append(domain)
    for values in islice(product(*domains), limits.max_quantifier_checks):
        yield values, factory.substitute(body, dict(zip(parameters, values)), checker=Elaborator(limits, algebras))


def query_forall(query, statement):
    from .logic import AssumptionSet, Context, PredicateQuery
    parameters, body = strip_forall(statement)
    # Universality over uninterpreted, potentially empty types remains unknown.
    if any(scalar_rank(p.annotation) is None and p.annotation != Type('Predicate')
           and (p.annotation is None or p.annotation.identity not in query.algebras) for p in parameters):
        return TruthValue.UNKNOWN
    # Do not inherit facts about an identity newly bound by a forged/low-level term.
    facts = tuple(p for p in query.context.assumptions.predicates if not free_symbols(p).intersection(parameters))
    local = PredicateQuery(query.f, context=Context(AssumptionSet(facts)), limits=query.limits, algebras=query.algebras)
    # Nested quantifiers under connectives are outside this bounded fragment.
    if any(isinstance(n, ForAll) for n in walk(body, query.limits)):
        return TruthValue.UNKNOWN
    result = local.query(body)
    if result is not TruthValue.UNKNOWN:
        return result
    for _, predicate in instances(statement, query.f, query.limits, query.algebras):
        query.tick()
        value = PredicateQuery(query.f, context=Context(AssumptionSet(facts)), limits=query.limits,
                               algebras=query.algebras).query(predicate)
        if value is TruthValue.FALSE:
            return value
    return TruthValue.UNKNOWN


def walk(term, limits):
    seen, stack = set(), [term]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if len(seen) > min(limits.max_nodes, limits.max_steps):
            raise TheoryError('Theory expression size limit exceeded')
        yield node
        stack.extend(node.children)


def validate_theory(theory, limits=None):
    """Validate parents before children and independently reconstruct inheritance."""
    limits = limits or Limits()
    checked, visiting, depths, work = set(), set(), {}, 0
    stack = [(theory, False)]
    factory = TermFactory()
    while stack:
        current, ready = stack.pop()
        if id(current) in checked:
            continue
        if ready:
            depth = 1 + max((depths[id(p.theory)] for p in current.parents), default=0)
            if depth > limits.max_theory_depth:
                raise TheoryError('Theory inheritance depth limit exceeded')
            _validate_theory(current, limits)
            operations, constants, axioms = inherited_members(
                current.parents, current.parameters, factory, limits,
                members=(*[o.symbol for o in current.operations], *current.constants))
            if (current.operations[:len(operations)] != operations
                    or current.constants[:len(constants)] != constants
                    or len(current.axioms) < len(axioms)
                    or any(a.name != b.name or not alpha_equal(a.statement, b.statement, limits)
                           for a, b in zip(current.axioms, axioms))):
                raise TheoryError('Theory does not preserve its inherited members and axioms')
            visiting.remove(id(current))
            checked.add(id(current))
            depths[id(current)] = depth
        else:
            if id(current) in visiting:
                raise TheoryError('Cyclic theory inheritance is not supported')
            work += 1 + len(current.parents) + len(current.operations) + len(current.constants) + len(current.axioms)
            if work > min(limits.max_nodes, limits.max_steps):
                raise TheoryError('Theory hierarchy size limit exceeded')
            visiting.add(id(current))
            stack.append((current, True))
            stack.extend((p.theory, False) for p in reversed(current.parents))
    return theory


def declared_type(type_, parameters):
    validate_type(type_)
    if type_ in parameters:
        return
    if type_.identity is not None or type_.name not in (*SCALARS, 'Predicate', 'Function', 'Matrix', 'Vector', 'Series'):
        raise TheoryError(f'Theory signature refers to undeclared type {type_}')
    for argument in type_.arguments:
        if isinstance(argument, Type):
            declared_type(argument, parameters)


def _validate_theory(theory, limits):
    if not valid_name(theory.name) or not theory.parameters or len(theory.parameters) > 8:
        raise TheoryError('A theory requires a name and between one and eight type parameters')
    names = [p.name for p in theory.parameters]
    if (len(set(names)) != len(names) or len({p.identity for p in theory.parameters}) != len(names)
            or any(not valid_name(p.name) or p.identity is None or p.arguments
                   or p.name in (*SCALARS, 'Predicate', 'Function', 'Vector', 'Matrix', 'Series') for p in theory.parameters)):
        raise TheoryError('Theory type parameters must be distinct nominal type names')
    members = [o.symbol for o in theory.operations] + list(theory.constants)
    public = [s.name for s in members] + [a.name for a in theory.axioms]
    if (len(set(public)) != len(public) or any(not valid_name(n) or n == 'valid' or n.startswith('_total_') for n in public)
            or len({o.spelling for o in theory.operations}) != len(theory.operations)):
        raise TheoryError('Theory members must have distinct names; valid and _total_ names are reserved')
    if len(public) > min(limits.max_nodes, limits.max_steps):
        raise TheoryError('Theory member count limit exceeded')
    for operation in theory.operations:
        symbol, type_ = operation.symbol, operation.symbol.annotation
        if (symbol.kind != SymbolKind.FUNCTION or type_ is None or type_.name != 'Function'
                or type_.identity is not None or len(type_.arguments) < 2):
            raise TheoryError('A theory operation requires a complete function signature')
        if not valid_name(operation.spelling):
            expected = OPERATOR_NAMES.get((operation.spelling, len(type_.arguments)-1))
            if expected is None or expected != symbol.name:
                raise TheoryError('Unsupported operator signature')
        elif operation.spelling != symbol.name:
            raise TheoryError('An operation name must match its symbol')
    if any(c.kind != SymbolKind.CONSTANT or c.annotation is None for c in theory.constants):
        raise TheoryError('Theory constants require declared types')
    checker = Elaborator(limits)
    allowed = set(members)
    for member in members:
        declared_type(member.annotation, theory.parameters)
    for axiom in theory.axioms:
        checker.require(axiom.statement, Type('Predicate'), 'Axiom body')
        if not free_symbols(axiom.statement) <= allowed:
            raise TheoryError('An axiom may refer only to its bound variables and declared theory members')
        for node in walk(axiom.statement, limits):
            if not isinstance(node, (Number, Symbol, ForAll, Comparison, Logical, Truth, FunctionCall)):
                raise TheoryError('Axioms use declared operations, quantified variables and predicates')
            if isinstance(node, FunctionCall) and node.callee not in allowed:
                raise TheoryError('Axiom calls must refer to declared operations')
            if isinstance(node, Symbol) and node.annotation is not None:
                declared_type(node.annotation, theory.parameters)
    return theory


def alpha_equal(left, right, limits):
    """Compare axiom syntax modulo bound names, preserving free member identities."""
    stack, seen = [(left, right, ())], set()
    while stack:
        a, b, bindings = stack.pop()
        key = (a, b, bindings)
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > min(limits.max_nodes, limits.max_steps):
            raise TheoryError('Axiom comparison size limit exceeded')
        if type(a) is not type(b):
            return False
        if isinstance(a, Symbol):
            mapping = dict(bindings)
            if (mapping.get(a, a) != b or (a not in mapping and b in mapping.values())):
                return False
        elif isinstance(a, ForAll):
            if (len(a.parameters) != len(b.parameters)
                    or any(x.annotation != y.annotation or x.kind != y.kind
                           for x, y in zip(a.parameters, b.parameters))):
                return False
            stack.append((a.body, b.body, (*bindings, *zip(a.parameters, b.parameters))))
        elif isinstance(a, (Comparison, Logical)):
            if a.op != b.op or len(a.children) != len(b.children):
                return False
            stack.extend((x, y, bindings) for x, y in zip(a.children, b.children))
        elif isinstance(a, FunctionCall):
            if len(a.arguments) != len(b.arguments):
                return False
            stack.extend((x, y, bindings) for x, y in zip(a.children, b.children))
        elif a != b:
            return False
    return True


def inherited_members(parents, parameters, factory, limits, *, members=None):
    """Unify compatible signatures, then specialize and merge every parent axiom."""
    if len(set(parents)) != len(parents):
        raise TheoryError('A theory cannot repeat the same direct parent')
    available = None if members is None else {s.name: s for s in members}
    signatures, symbols, operations, constants, axioms = {}, {}, [], [], {}
    work = 0
    for parent in parents:
        work += 1 + len(parent.theory.operations) + len(parent.theory.constants) + len(parent.theory.axioms)
        if work > min(limits.max_nodes, limits.max_steps):
            raise TheoryError('Inherited member count limit exceeded')
        if len(parent.arguments) != len(parent.theory.parameters):
            raise TheoryError(f'Parent {parent.theory.name} requires {len(parent.theory.parameters)} type arguments')
        for argument in parent.arguments:
            if not isinstance(argument, Type):
                raise TheoryError('Parent theory arguments must be types')
            declared_type(argument, parameters)
        substitutions = dict(zip(parent.theory.parameters, parent.arguments))
        declarations = [(o.symbol, o.spelling) for o in parent.theory.operations]
        declarations += [(c, None) for c in parent.theory.constants]
        for symbol, spelling in declarations:
            signature = (symbol.kind, replace_type(symbol.annotation, substitutions), spelling)
            if symbol.name in signatures:
                if signatures[symbol.name] != signature:
                    raise TheoryError(f'Conflicting inherited member {symbol.name!r}')
                continue
            if available is None:
                new = Symbol(symbol.name, symbol.kind, signature[1])
            else:
                new = available.get(symbol.name)
                if new is None or (new.kind, new.annotation) != signature[:2]:
                    raise TheoryError(f'Missing or changed inherited member {symbol.name!r}')
            signatures[symbol.name], symbols[symbol.name] = signature, new
            if spelling is None:
                constants.append(new)
            else:
                operations.append(TheoryOperation(spelling, new))
        for axiom in parent.theory.axioms:
            statement = instantiate(parent.theory, parent.arguments, symbols, axiom.statement, factory, limits, {})
            previous = axioms.get(axiom.name)
            if previous is not None and not alpha_equal(previous.statement, statement, limits):
                raise TheoryError(f'Conflicting inherited axiom {axiom.name!r}')
            axioms.setdefault(axiom.name, Axiom(axiom.name, statement))
            if len(signatures) + len(axioms) > min(limits.max_nodes, limits.max_steps):
                raise TheoryError('Inherited member count limit exceeded')
    return tuple(operations), tuple(constants), tuple(axioms.values())


def compile_theory(node, resolver):
    local = resolver.environment.child()
    work = type(resolver)(resolver.source, local, resolver.factory, resolver.kernel, defer=True)
    parameters = tuple(Type(name, identity=uuid4()) for name in node.parameters)
    work.type_parameters = {p.name: p for p in parameters}
    parents = []
    from .ast import TypeRef
    for reference in node.parents:
        definition = resolver.environment.get(reference.name)
        if definition is None or not isinstance(definition.term, Theory):
            raise resolver.error(f'Parent {reference.name!r} must name an existing theory', reference)
        if any(not isinstance(a, TypeRef) for a in reference.arguments):
            raise resolver.error('Parent theory arguments must be types', reference)
        parents.append(TheoryParent(definition.term, tuple(work.annotation(a) for a in reference.arguments)))
    inherited_ops, inherited_constants, inherited_axioms = inherited_members(
        tuple(parents), parameters, resolver.factory, resolver.kernel.limits)
    operations, constants = list(inherited_ops), list(inherited_constants)
    for operation in operations:
        local.define(Definition(operation.symbol))
        if operation.spelling in '+-*/^':
            work.operations[(operation.spelling, len(operation.symbol.annotation.arguments)-1)] = operation.symbol
    for constant in constants:
        local.define(Definition(constant))
    for declaration in node.operations:
        signature = Type('Function', tuple(work.annotation(t) for t in (*declaration.inputs, declaration.output)))
        name = OPERATOR_NAMES.get((declaration.name, len(declaration.inputs)), declaration.name)
        symbol = Symbol(name, SymbolKind.FUNCTION, signature)
        operations.append(TheoryOperation(declaration.name, symbol))
        local.define(Definition(symbol))
        if declaration.name in '+-*/^':
            work.operations[(declaration.name, len(declaration.inputs))] = symbol
    for declaration in node.constants:
        symbol = Symbol(declaration.name, SymbolKind.CONSTANT, work.annotation(declaration.annotation))
        local.define(Definition(symbol))
        constants.append(symbol)
    axioms = (*inherited_axioms, *(Axiom(a.name, work.expression(a.predicate)) for a in node.axioms))
    return validate_theory(Theory(node.name, parameters, tuple(operations), tuple(constants), axioms, tuple(parents)), resolver.kernel.limits)


def instantiate(theory, arguments, bindings, statement, factory, limits, algebras):
    substitutions = dict(zip(theory.parameters, arguments))
    values = {o.symbol: bindings[o.symbol.name] for o in theory.operations}
    values.update((c, bindings[c.name]) for c in theory.constants)
    key = repr(tuple(type_key(t) for t in arguments))
    memo = {}

    def visit(node):
        if node in memo:
            return memo[node]
        if len(memo) >= limits.max_nodes:
            raise TheoryError('Instantiated axiom size limit exceeded')
        if isinstance(node, Symbol):
            result = values.get(node)
            if result is None:
                type_ = None if node.annotation is None else replace_type(node.annotation, substitutions)
                result = Symbol(node.name, node.kind, type_, uuid5(node.identity, key))
        elif isinstance(node, ForAll):
            result = factory._intern(ForAll, tuple(visit(p) for p in node.parameters), visit(node.body))
        elif isinstance(node, Comparison):
            result = factory.comparison(node.op, visit(node.left), visit(node.right))
        elif isinstance(node, Logical):
            result = factory.logical(node.op, *(visit(p) for p in node.operands))
        elif isinstance(node, FunctionCall):
            result = factory.call(visit(node.callee), tuple(visit(p) for p in node.arguments), checker=Elaborator(limits, algebras))
        elif isinstance(node, (Number, Truth)):
            result = node
        else:
            raise TheoryError('Unsupported axiom term')
        memo[node] = result
        return result

    return visit(statement)


def polynomial(term, limits):
    """Certifiable total polynomial fragment, excluding opaque function atoms."""
    for node in walk(term, limits):
        if isinstance(node, Number):
            continue
        if isinstance(node, Symbol):
            if scalar_rank(node.annotation) is not None or node.annotation is not None and node.annotation.identity is not None:
                continue
        if isinstance(node, Unary) and node.op in ('+', '-'):
            continue
        if isinstance(node, Binary):
            if node.op in ('+', '-', '*'):
                continue
            if node.op == '/' and isinstance(node.right, Number) and node.right.value != 0:
                continue
            if (node.op == '^' and isinstance(node.right, Number) and node.right.value.denominator == 1
                    and 0 < node.right.value <= limits.max_power):
                continue
        return False
    return True


def equality_goals(statement, factory, limits, algebras):
    """Reconstruct universal polynomial proof goals without trusting certificates."""
    from .algebra import word_term
    parameters, body = strip_forall(statement)
    if any(scalar_rank(p.annotation) is None and (p.annotation is None or p.annotation.identity not in algebras)
           for p in parameters):
        return None
    equations, stack = [], [body]
    while stack:
        node = stack.pop()
        if isinstance(node, Logical) and node.op == 'and':
            stack.extend(reversed(node.operands))
        elif isinstance(node, Comparison) and node.op == '==' and polynomial(node.left, limits) and polynomial(node.right, limits):
            equations.append(node)
        else:
            return None
        if len(equations)+len(stack) > limits.max_nodes:
            raise TheoryError('Axiom goal count limit exceeded')
    used = {s.annotation.identity for s in free_symbols(body) if s.annotation is not None and s.annotation.identity is not None}
    if used - algebras.keys() or len(used) > 1:
        return None
    algebra = algebras[next(iter(used))] if used else None
    replacements = {}
    if algebra is not None:
        if algebra.basis is None:
            return None
        for parameter in parameters:
            if parameter.annotation != algebra.type:
                continue
            value = factory.number(0)
            for index, word in enumerate(algebra.basis):
                coordinate = Symbol(f'{parameter.name}_{index}', SymbolKind.VARIABLE, algebra.scalar_domain,
                                    uuid5(parameter.identity, f'theory-coordinate:{index}'))
                value = factory.binary('+', value, factory.binary('*', coordinate, word_term(algebra, word, factory)))
            replacements[parameter] = value
    return tuple((EqualityGoal(factory.substitute(e.left, replacements), factory.substitute(e.right, replacements)), algebra)
                 for e in equations)


def check_property(name, statement, factory, limits, algebras, *, assumed=False):
    result = _check_property(name, statement, factory, limits, algebras, assumed=assumed)
    used = {n.annotation.identity for n in walk(statement, limits) if isinstance(n, Symbol) and n.annotation is not None}
    return replace(result, algebras=tuple(a for identity, a in algebras.items() if identity in used))


def _check_property(name, statement, factory, limits, algebras, *, assumed=False):
    from .logic import PredicateQuery
    parameters, body = strip_forall(statement)
    if isinstance(body, Defined):
        result = PredicateQuery(factory, limits=limits, algebras=algebras).query(body)
        if result is TruthValue.TRUE:
            return PropertyResult(name, statement, 'proved', 'domain')
    goals = equality_goals(statement, factory, limits, algebras)
    if goals is not None:
        results = tuple(ProofSearch(factory, limits).equality(goal.left, goal.right, algebra) for goal, algebra in goals)
        if all(r.status == 'proved' for r in results):
            return PropertyResult(name, statement, 'proved', 'polynomial', tuple(r.proof for r in results))
    if not any(isinstance(n, ForAll) for n in walk(body, limits)):
        for values, instance in instances(statement, factory, limits, algebras):
            if refuted(instance, factory, limits, algebras):
                if assumed:
                    raise TheoryError(f'Cannot assume {name!r}: an exact counterexample was found')
                return PropertyResult(name, statement, 'disproved', 'counterexample', counterexample=values)
    return PropertyResult(name, statement, 'assumed' if assumed else 'unknown', 'assumption' if assumed else 'unsupported')


def refuted(predicate, factory, limits, algebras):
    """Check a concrete witness by arithmetic, without proof search."""
    from .logic import PredicateQuery
    from .algebra import AlgebraNormalizer
    from .proof import _rational_coordinates
    if PredicateQuery(factory, limits=limits, algebras=algebras).query(predicate) is TruthValue.FALSE:
        return True
    if isinstance(predicate, Logical) and predicate.op == 'and':
        return any(refuted(p, factory, limits, algebras) for p in predicate.operands)
    if isinstance(predicate, Comparison) and predicate.op == '==':
        if any(s.kind != SymbolKind.GENERATOR for s in free_symbols(predicate)):
            return False
        checker = Elaborator(limits, algebras)
        type_ = checker.infer(factory.binary('-', predicate.left, predicate.right))
        algebra = None if type_ is None else algebras.get(type_.identity)
        if algebra is not None:
            try:
                difference = AlgebraNormalizer(algebra, factory, limits).normalize(factory.binary('-', predicate.left, predicate.right))
            except ValueError:
                return False
            return _rational_coordinates(difference) and (not isinstance(difference, Number) or difference.value != 0)
    return False


def validate_bindings(theory, arguments, definitions, limits, algebras):
    if len(arguments) != len(theory.parameters):
        raise TheoryError('Implementation type argument count does not match the theory')
    if any(not isinstance(t, Type) for t in arguments):
        raise TheoryError('Implementation arguments must be types')
    substitutions = dict(zip(theory.parameters, arguments))
    bindings = {d.symbol.name: d.term for d in definitions}
    members = tuple(o.symbol for o in theory.operations) + theory.constants
    if len(bindings) != len(definitions) or set(bindings) != {s.name for s in members}:
        raise TheoryError('Implementation must bind every declared operation and constant exactly once')
    checker = Elaborator(limits, algebras)
    for member in members:
        expected = replace_type(member.annotation, substitutions)
        actual = checker.infer(bindings[member.name])
        if actual is None or not checker.algebra_embedding(actual, expected):
            checker.require(bindings[member.name], expected, f'Implementation member {member.name!r}')
    return bindings


def obligations(theory, arguments, bindings, factory, limits, algebras):
    substitutions = dict(zip(theory.parameters, arguments))
    result = []
    for operation in theory.operations:
        symbol = operation.symbol
        inputs = replace_type(symbol.annotation, substitutions).arguments[:-1]
        key = repr(tuple(type_key(t) for t in arguments))
        parameters = tuple(Symbol(f'arg{i+1}', SymbolKind.VARIABLE, t, uuid5(symbol.identity, key+f':arg{i}'))
                           for i, t in enumerate(inputs))
        body = factory.call(bindings[symbol.name], parameters, checker=Elaborator(limits, algebras))
        result.append(('_total_'+symbol.name, factory._intern(ForAll, parameters, factory._intern(Defined, body))))
    # A declared constant also denotes a defined value of its stated type.
    for constant in theory.constants:
        result.append(('_total_'+constant.name, factory._intern(Defined, bindings[constant.name])))
    for axiom in theory.axioms:
        result.append((axiom.name, instantiate(theory, arguments, bindings, axiom.statement, factory, limits, algebras)))
    return tuple(result)


def compile_implementation(node, resolver):
    from .ast import TypeRef
    owner = resolver.environment.get(node.theory.name)
    if owner is None or not isinstance(owner.term, Theory):
        raise TheoryError(f'{node.theory.name!r} must name a declared theory')
    theory = owner.term
    if any(not isinstance(t, TypeRef) for t in node.theory.arguments):
        raise TheoryError('Implementation arguments must be types, not dimensions')
    arguments = tuple(resolver.annotation(t) for t in node.theory.arguments)
    definitions = []
    operations = {o.spelling: o.symbol.name for o in theory.operations}
    constants = {c.name for c in theory.constants}
    for binding in node.bindings:
        names = operations if binding.operation else constants
        if binding.name not in names:
            raise TheoryError(f'Unknown theory member {binding.name!r}')
        name = operations[binding.name] if binding.operation else binding.name
        definitions.append(Definition(Symbol(name, SymbolKind.EXPRESSION), resolver.expression(binding.value)))
    bindings = validate_bindings(theory, arguments, tuple(definitions), resolver.kernel.limits, resolver.kernel.algebras)
    if (len(set(node.assumptions)) != len(node.assumptions)
            or set(node.assumptions) - {a.name for a in theory.axioms}):
        raise TheoryError('Implementation assumptions must name distinct declared axioms')
    if resolver.environment.context.assumptions.predicates:
        raise TheoryError('Implementation certificates require an assumption-free context')
    properties = tuple(check_property(name, statement, resolver.factory, resolver.kernel.limits, resolver.kernel.algebras,
                                      assumed=name in node.assumptions)
                       for name, statement in obligations(theory, arguments, bindings, resolver.factory, resolver.kernel.limits, resolver.kernel.algebras))
    used = set()
    types = list(arguments)
    for definition in definitions:
        types.extend(n.annotation for n in walk(definition.term, resolver.kernel.limits)
                     if isinstance(n, Symbol) and n.annotation is not None)
    while types:
        type_ = types.pop()
        used.add(type_.identity)
        types.extend(a for a in type_.arguments if isinstance(a, Type))
    dependencies = tuple(a for identity, a in resolver.kernel.algebras.items() if identity in used)
    value = Implementation(node.name, theory, arguments, tuple(definitions), properties, dependencies)
    validate_implementation(value, resolver.factory, resolver.kernel.limits, resolver.kernel.algebras)
    return value


def validate_property(result, factory, limits, algebras):
    """Independent metadata/certificate checking; no call to proof search."""
    from .logic import PredicateQuery
    if not valid_name(result.name) or result.status not in STATUSES:
        raise TheoryError('Invalid property metadata')
    if (len({a.type.identity for a in result.algebras}) != len(result.algebras)
            or any(a.type.identity not in algebras or not same_algebra(a, algebras[a.type.identity]) for a in result.algebras)):
        raise TheoryError('Invalid property algebra dependencies')
    Elaborator(limits, algebras).require(result.statement, Type('Predicate'), 'Property statement')
    parameters, body = strip_forall(result.statement)
    if result.status == 'proved':
        if result.counterexample:
            raise TheoryError('A proved property cannot have a counterexample')
        if result.method == 'domain' and isinstance(body, Defined) and not result.proofs:
            if PredicateQuery(factory, limits=limits, algebras=algebras).query(body) is TruthValue.TRUE:
                return
        if result.method == 'polynomial':
            goals = equality_goals(result.statement, factory, limits, algebras)
            if goals is not None and len(goals) == len(result.proofs) and all(
                    proof.goal == goal and same_algebra(proof.algebra, algebra) and check_proof(proof, goal, limits=limits)
                    for proof, (goal, algebra) in zip(result.proofs, goals)):
                return
        raise TheoryError('Property proof does not certify its quantified statement')
    if result.proofs:
        raise TheoryError('An unproved property cannot carry certificates')
    if result.status == 'disproved':
        if result.method != 'counterexample' or len(result.counterexample) != len(parameters):
            raise TheoryError('Invalid property counterexample')
        checker = Elaborator(limits, algebras)
        for parameter, value in zip(parameters, result.counterexample):
            actual = checker.infer(value)
            if not (actual is not None and checker.algebra_embedding(actual, parameter.annotation)):
                checker.require(value, parameter.annotation, 'Counterexample coordinate')
        predicate = factory.substitute(body, dict(zip(parameters, result.counterexample)), checker=checker)
        if not refuted(predicate, factory, limits, algebras):
            raise TheoryError('Property counterexample does not refute its statement')
    elif result.counterexample or result.method != ('assumption' if result.status == 'assumed' else 'unsupported'):
        raise TheoryError('Invalid unproved property metadata')
    elif result.status == 'assumed':
        if any(refuted(instance, factory, limits, algebras) for _, instance in instances(result.statement, factory, limits, algebras)):
            raise TheoryError('An assumed property has an exact counterexample')


def validate_implementation(value, factory, limits, algebras):
    if not valid_name(value.name):
        raise TheoryError('Invalid implementation name')
    validate_theory(value.theory, limits)
    if len({a.type.identity for a in value.algebras}) != len(value.algebras):
        raise TheoryError('Duplicate implementation algebra dependencies')
    if any(a.type.identity not in algebras or not same_algebra(a, algebras[a.type.identity]) for a in value.algebras):
        raise TheoryError('Implementation algebra dependencies are not registered presentations')
    bindings = validate_bindings(value.theory, value.arguments, value.bindings, limits, algebras)
    expected = obligations(value.theory, value.arguments, bindings, factory, limits, algebras)
    if len(expected) != len(value.properties):
        raise TheoryError('Implementation is missing an obligation')
    for (name, statement), result in zip(expected, value.properties):
        if name != result.name or statement != result.statement:
            raise TheoryError('Implementation property is not the instantiated theory obligation')
        if name.startswith('_total_') and result.status == 'assumed':
            raise TheoryError('Operation totality cannot be assumed')
        validate_property(result, factory, limits, algebras)


def same_algebra(left, right):
    if left is None or right is None:
        return left is right
    return replace(left, properties=()) == replace(right, properties=())
