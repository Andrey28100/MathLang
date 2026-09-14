"""Conservative, bounded predicate queries and immutable assumption contexts.

This is a decision procedure for a small fragment, not a general proof search.
Unresolved statements remain Unknown; assumptions never enter the portable
computational proof checker.
"""

from dataclasses import dataclass

from .terms import (Binary, Comparison, Defined, ForAll, FunctionCall, Logical, Number,
                    Predicate, Symbol, SymbolKind, Term, TermFactory, Truth,
                    TruthValue, Type, Unary)
from .normalization import Limits, ScalarNormalizer
from .elaboration import Elaborator, scalar_rank
from .rewriting import structurally_equal

T, F, U = TruthValue.TRUE, TruthValue.FALSE, TruthValue.UNKNOWN
SIGNS = {'==': {0}, '!=': {-1, 1}, '<': {-1}, '<=': {-1, 0}, '>': {1}, '>=': {0, 1}}
INVERSE = {'==': '!=', '!=': '==', '<': '>=', '<=': '>', '>': '<=', '>=': '<'}
REVERSE = {'==': '==', '!=': '!=', '<': '>', '<=': '>=', '>': '<', '>=': '<='}


class LogicError(ValueError):
    pass


def negate(value: TruthValue) -> TruthValue:
    return {T: F, F: T, U: U}[value]


def conjunction(values) -> TruthValue:
    values = tuple(values)
    return F if F in values else U if U in values else T


def disjunction(values) -> TruthValue:
    values = tuple(values)
    return T if T in values else U if U in values else F


@dataclass(frozen=True, slots=True)
class AssumptionSet:
    predicates: tuple[Term, ...] = ()


@dataclass(frozen=True, slots=True)
class Context:
    assumptions: AssumptionSet = AssumptionSet()


class PredicateQuery:
    def __init__(self, factory=None, *, context=None, limits=None, algebras=None):
        self.f = TermFactory() if factory is None else factory
        self.context = Context() if context is None else context
        self.limits = Limits() if limits is None else limits
        self.algebras = {} if algebras is None else algebras
        self.types = Elaborator(self.limits, self.algebras)
        self.normalizer = ScalarNormalizer(self.f, self.limits, query=self._query)
        self.memo, self.active, self.constants = {}, set(), {}
        self.steps = self.normalizations = 0
        # Computing necessary algebraic domain conditions may ask scalar queries.
        # The initial closure is not yet available during that computation.
        self.facts = ()
        self.facts = self._facts()

    def tick(self):
        self.steps += 1
        if self.steps > self.limits.max_steps:
            raise LogicError('Predicate query step limit exceeded')

    def _facts(self):
        result, seen, stack = [], set(), list(self.context.assumptions.predicates)
        while stack:
            self.tick()
            item = stack.pop()
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
            if isinstance(item, Logical) and item.op == 'and':
                stack.extend(item.operands)
            elif (isinstance(item, Logical) and item.op == 'not'
                  and isinstance(item.operands[0], Comparison) and item.operands[0].op in INVERSE):
                operand = item.operands[0]
                stack.append(self.f.comparison(INVERSE[operand.op], operand.left, operand.right))
            elif isinstance(item, Comparison) and item.op in SIGNS:
                # A true mathematical comparison entails defined operands.
                stack.extend((Defined(item.left), Defined(item.right)))
            elif isinstance(item, Defined):
                stack.extend(self._domain_requirements(item.expression))
        return tuple(result)

    def _domain_requirements(self, term):
        """Necessary conditions only; sufficient power conditions cannot be reversed."""
        zero = self.f.number(0)
        if isinstance(term, (Unary, Binary, Logical)) or (isinstance(term, Comparison) and term.op != '==='):
            yield from (Defined(c) for c in term.children)
        if isinstance(term, Binary):
            if term.op == '/':
                yield self._invertibility_condition(term.right)
            elif term.op == '^':
                self.types.infer(term.right)
                exponent = self.types.numbers.get(term.right)
                if exponent is not None and exponent.denominator == 1 and exponent <= 0:
                    yield (self._invertibility_condition(term.left) if exponent < 0
                           else self.f.comparison('!=', term.left, zero))
        if isinstance(term, FunctionCall):
            yield from (Defined(a) for a in term.arguments)
            if isinstance(term.callee, Symbol) and term.callee.kind == SymbolKind.BUILTIN and len(term.arguments) == 1:
                arg, name = term.arguments[0], term.callee.name
                if self._algebra(arg) is not None:
                    # A supported real analytic lift has scalar branch guards.
                    # Never compare an algebra element with zero using ordering.
                    if name in ('log', 'sqrt'):
                        condition = self._algebra_function_condition(name, arg)
                        if condition is not None:
                            yield condition
                    return
                if name == 'sqrt' and scalar_rank(self.types.infer(arg)) != 4:
                    yield self.f.comparison('>=', arg, zero)
                elif name == 'log':
                    op = '!=' if scalar_rank(self.types.infer(arg)) == 4 else '>'
                    yield self.f.comparison(op, arg, zero)
                elif name == 'tan':
                    from .terms import builtin_symbol
                    yield self.f.comparison('!=', self.f.call(builtin_symbol('cos'), (arg,)), zero)

    def query(self, predicate: Term) -> TruthValue:
        if self.types.infer(predicate) != Type('Predicate'):
            raise LogicError('A predicate is required')
        try:
            return self._query(predicate)
        except RecursionError:
            raise LogicError('Predicate nesting is too deep') from None

    def _query(self, predicate):
        self.tick()
        if predicate in self.memo:
            return self.memo[predicate]
        if predicate in self.active:
            return U
        self.active.add(predicate)
        try:
            if isinstance(predicate, Truth):
                result = predicate.value
            elif any(structurally_equal(predicate, fact, self.tick) for fact in self.facts):
                result = T
            elif any(isinstance(fact, Logical) and fact.op == 'not'
                     and structurally_equal(predicate, fact.operands[0], self.tick) for fact in self.facts):
                result = F
            elif isinstance(predicate, Logical):
                if predicate.op == 'not':
                    result = negate(self._query(predicate.operands[0]))
                else:
                    operation = conjunction if predicate.op == 'and' else disjunction
                    result = operation(self._query(p) for p in predicate.operands)
            elif isinstance(predicate, Comparison):
                result = self._comparison(predicate)
            elif isinstance(predicate, Defined):
                result = self._defined(predicate.expression)
            elif isinstance(predicate, ForAll):
                from .theories import query_forall
                result = query_forall(self, predicate)
            else:
                result = U
            self.memo[predicate] = result
            return result
        finally:
            self.active.remove(predicate)

    def constant(self, term):
        if term not in self.constants:
            self.types.infer(term)
            value = self.types.numbers.get(term)
            if value is None and isinstance(term, FunctionCall) and all(isinstance(a, Number) for a in term.arguments):
                normalized = self.normalize(term, expand=False)
                value = normalized.value if isinstance(normalized, Number) else None
            self.constants[term] = value
        return self.constants[term]

    def normalize(self, term, *, expand=True):
        self.normalizations += 1
        if self.normalizations > self.limits.max_passes:
            raise LogicError('Predicate normalization pass limit exceeded')
        try:
            type_ = self.types.infer(term)
            algebra = None if type_ is None else self.algebras.get(type_.identity)
            if algebra is not None:
                from .algebra import AlgebraNormalizer
                normalizer = AlgebraNormalizer(algebra, self.f, self.limits, query=self._query)
            else:
                normalizer = self.normalizer
            return normalizer.normalize(term) if expand else normalizer.simplify(term)
        except LogicError:
            raise
        except ValueError:
            return term

    def compare(self, op, left, right):
        return self._query(self.f.comparison(op, left, right))

    def _algebra(self, term):
        type_ = self.types.infer(term)
        return None if type_ is None else self.algebras.get(type_.identity)

    def _invertibility_condition(self, term):
        algebra = self._algebra(term)
        if algebra is None:
            return self.f.comparison('!=', term, self.f.number(0))
        from .algebra import AlgebraError, AlgebraNormalizer
        try:
            return AlgebraNormalizer(algebra, self.f, self.limits, query=self._query).invertibility(term)
        except AlgebraError:
            # Lack of a coordinate representation is not noninvertibility.
            return self.f.truth(U)

    def _algebra_function_condition(self, name, term):
        from .algebra import AlgebraError, AlgebraNormalizer
        algebra = self._algebra(term)
        try:
            return AlgebraNormalizer(algebra, self.f, self.limits, query=self._query).function_domain(name, term)
        except AlgebraError:
            return None

    def _comparison(self, predicate):
        op, left, right = predicate.op, predicate.left, predicate.right
        if op == '===':
            return T if structurally_equal(left, right, self.tick) else F
        if conjunction((self._query(Defined(left)), self._query(Defined(right)))) is not T:
            return U
        if self.types.infer(left) == Type('Predicate'):
            a, b = self._query(left), self._query(right)
            return U if U in (a, b) else (T if (a == b) == (op == '==') else F)
        a, b = self.constant(left), self.constant(right)
        if a is not None and b is not None:
            sign = (a > b)-(a < b)
            return T if sign in SIGNS[op] else F
        if structurally_equal(left, right, self.tick):
            return T if 0 in SIGNS[op] else F
        possible = {-1, 0, 1}
        for fact in self.facts:
            self.tick()
            if not isinstance(fact, Comparison) or fact.op not in SIGNS:
                continue
            if structurally_equal(left, fact.left, self.tick) and structurally_equal(right, fact.right, self.tick):
                possible &= SIGNS[fact.op]
            elif structurally_equal(left, fact.right, self.tick) and structurally_equal(right, fact.left, self.tick):
                possible &= {-s for s in SIGNS[fact.op]}
            # Compare bounds on the same expression, e.g. x > 2 entails x >= 0.
            target, point, query_reversed = (left, b, False) if b is not None else (right, a, True)
            if point is None:
                continue
            bound, relation = self.constant(fact.right), fact.op
            expression = fact.left
            if bound is None:
                bound, relation, expression = self.constant(fact.left), REVERSE[fact.op], fact.right
            if bound is None or not structurally_equal(target, expression, self.tick):
                continue
            signs = {-1, 0, 1}
            if relation == '==':
                signs = {(bound > point)-(bound < point)}
            elif relation == '!=' and bound == point:
                signs = {-1, 1}
            elif relation in ('>', '>=') and bound >= point:
                signs = {1} if bound > point or relation == '>' else {0, 1}
            elif relation in ('<', '<=') and bound <= point:
                signs = {-1} if bound < point or relation == '<' else {-1, 0}
            possible &= {-s for s in signs} if query_reversed else signs
        if not possible:
            raise LogicError('Inconsistent assumption context')
        if possible <= SIGNS[op]:
            return T
        if not possible & SIGNS[op]:
            return F
        # A real even power is nonnegative, but need not be strictly positive.
        if b == 0 and isinstance(left, Binary) and left.op == '^':
            exponent = self.constant(left.right)
            # A positive real base raised to any defined real scalar exponent
            # stays strictly positive.  This also makes the canonical exact
            # form q^(1/2) carry the same nonzero fact as sqrt(q).
            if (scalar_rank(self.types.infer(left.left)) in (0, 1, 2, 3)
                    and scalar_rank(self.types.infer(left.right)) in (0, 1, 2, 3)
                    and self.compare('>', left.left, right) is T):
                if op in ('>', '>=', '!='):
                    return T
                if op in ('<', '<=', '=='):
                    return F
            if (op in ('==', '!=') and exponent is not None
                    and exponent.denominator == 1 and exponent > 0
                    and scalar_rank(self.types.infer(left.left)) is not None):
                return self.compare(op, left.left, right)
            if (exponent is not None and exponent.denominator == 1 and exponent > 0 and exponent % 2 == 0
                    and scalar_rank(self.types.infer(left.left)) in (0, 1, 2, 3)):
                if op in ('>=', '<'):
                    return T if op == '>=' else F
        if b == 0 and self.types.infer(left) == Type('Nat') and op in ('>=', '<'):
            return T if op == '>=' else F
        if b == 0 and isinstance(left, FunctionCall) and isinstance(left.callee, Symbol):
            if left.callee.kind == SymbolKind.BUILTIN and len(left.arguments) == 1:
                if left.callee.name == 'exp':
                    if op in ('==', '!='):
                        return F if op == '==' else T
                    if scalar_rank(self.types.infer(left.arguments[0])) in (0, 1, 2, 3):
                        return T if 1 in SIGNS[op] else F
                if (left.callee.name == 'sqrt' and scalar_rank(self.types.infer(left.arguments[0])) is not None
                        and self.compare('>', left.arguments[0], right) is T):
                    return T if 1 in SIGNS[op] else F
        if b == 0 and op in ('==', '!=') and isinstance(left, Binary) and left.op == '*':
            if scalar_rank(self.types.infer(left)) is not None:
                nonzero = conjunction(self.compare('!=', value, right) for value in left.children)
                if nonzero is not U:
                    return nonzero if op == '!=' else negate(nonzero)
        # Equal normal forms prove equality; different symbolic forms do not disprove it.
        if op in ('==', '!='):
            lhs, rhs = self.normalize(left), self.normalize(right)
            if structurally_equal(lhs, rhs, self.tick):
                return T if op == '==' else F
            difference = self.normalize(self.f.binary('-', lhs, rhs))
            if isinstance(difference, Number):
                equal = difference.value == 0
                return T if equal == (op == '==') else F
            algebra = self._algebra(left) or self._algebra(right)
            if algebra is not None and algebra.basis is not None:
                from .algebra import AlgebraError, AlgebraNormalizer
                try:
                    coordinates = AlgebraNormalizer(algebra, self.f, self.limits, query=self._query).coordinates(difference)
                    equal = conjunction(self.compare('==', c, self.f.number(0)) for c in coordinates.values())
                    return equal if op == '==' else negate(equal)
                except AlgebraError:
                    pass
        return U

    def _defined(self, term):
        if isinstance(term, (Number, Symbol, Truth)):
            return T
        if isinstance(term, Defined):
            return T
        if isinstance(term, Comparison):
            return T if term.op == '===' else conjunction(self._query(Defined(c)) for c in term.children)
        if isinstance(term, Logical):
            return conjunction(self._query(Defined(c)) for c in term.children)
        if isinstance(term, Unary):
            return self._query(Defined(term.operand))
        if isinstance(term, Binary):
            children = conjunction(self._query(Defined(c)) for c in term.children)
            if children is F:
                return F
            if term.op in ('+', '-', '*'):
                return children
            zero = self.f.number(0)
            if term.op == '/':
                return conjunction((children, self._query(self._invertibility_condition(term.right))))
            exponent = self.constant(term.right)
            if exponent is not None and exponent.denominator == 1:
                if exponent > 0:
                    return children
                condition = (self._invertibility_condition(term.left) if exponent < 0
                             else self.f.comparison('!=', term.left, zero))
                return conjunction((children, self._query(condition)))
            if self._algebra(term.left) is not None:
                return U
            # General powers need branch information. Positivity is sufficient,
            # failure to establish positivity is not a proof of undefinedness.
            if self.compare('>', term.left, zero) is T:
                return children
            return U
        if isinstance(term, FunctionCall) and isinstance(term.callee, Symbol):
            arguments = conjunction(self._query(Defined(a)) for a in term.arguments)
            if arguments is F:
                return F
            if term.callee.kind != SymbolKind.BUILTIN:
                return U
            if len(term.arguments) == 1:
                arg, name = term.arguments[0], term.callee.name
                zero = self.f.number(0)
                algebra = self._algebra(arg)
                if algebra is not None:
                    if name in ('sin', 'cos', 'exp'):
                        # Entire functions exist in finite-dimensional real or
                        # complex associative algebras even if reduction fails.
                        return arguments if algebra.basis is not None and algebra.confluence == 'known' else U
                    if name in ('log', 'sqrt'):
                        condition = self._algebra_function_condition(name, arg)
                        return U if condition is None else conjunction((arguments, self._query(condition)))
                    return U
                if name in ('sin', 'cos', 'exp', 'abs', 'factorial'):
                    return arguments
                if name == 'sqrt':
                    condition = T if scalar_rank(self.types.infer(arg)) == 4 else self.compare('>=', arg, zero)
                    return conjunction((arguments, condition))
                if name == 'log':
                    op = '!=' if scalar_rank(self.types.infer(arg)) == 4 else '>'
                    return conjunction((arguments, self.compare(op, arg, zero)))
                if name == 'tan':
                    from .terms import builtin_symbol
                    return conjunction((arguments, self.compare('!=', self.f.call(builtin_symbol('cos'), (arg,)), zero)))
        return U

    def assuming(self, predicate: Term) -> Context:
        result = self.query(predicate)
        if result is U:
            stack, closed = [predicate], True
            while stack:
                node = stack.pop()
                if isinstance(node, Logical):
                    stack.extend(node.operands)
                elif not isinstance(node, Truth):
                    closed = False
                    break
            if closed:
                raise LogicError('Cannot assume the truth value Unknown; assume a predicate')
        if self._query(Defined(predicate)) is F:
            raise LogicError('Cannot assume a predicate outside its domain')
        if result is F:
            raise LogicError('Assumption contradicts the current context')
        if result is T:
            return self.context
        if len(self.context.assumptions.predicates) >= self.limits.max_terms:
            raise LogicError('Assumption count limit exceeded')
        # Check conjunctions incrementally so x>0 and x<0 is rejected atomically.
        if isinstance(predicate, Logical) and predicate.op == 'and':
            context = self.context
            for operand in predicate.operands:
                context = PredicateQuery(self.f, context=context, limits=self.limits, algebras=self.algebras).assuming(operand)
            return context
        context = Context(AssumptionSet((*self.context.assumptions.predicates, predicate)))
        # Recheck each fact against the others. Looking it up in its own fact
        # closure would mask contradictions such as not domain(1/x), then x!=0.
        facts = context.assumptions.predicates
        for index, fact in enumerate(facts):
            other = Context(AssumptionSet(facts[:index]+facts[index+1:]))
            check = PredicateQuery(self.f, context=other, limits=self.limits, algebras=self.algebras)
            if check.query(fact) is F or check._query(Defined(fact)) is F:
                raise LogicError('Assumption contradicts the current context')
            self.steps += check.steps
            self.tick()
        return context
