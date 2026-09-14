"""Evaluation of explicit transformations, separate from parsing and storage."""

from contextvars import ContextVar

from .normalization import Limits, NormalizationError, ScalarNormalizer
from .rewriting import RewriteError, Rewriter
from .algebra import AlgebraDefinition, AlgebraError, AlgebraNormalizer
from .analysis import Calculus, calculus_call
from .elaboration import Elaborator
from .iteration import ITERATION_NAMES, IterationBudget, execute as execute_iteration, factorial
from .numeric import evaluate_numeric
from .terms import (
    ForAll,
    Comparison, Defined, Logical, Predicate, Truth,
    Approach, CalculusOperator, CalculusRequest, TaylorSeries,
    Binary, Function, FunctionCall, Number, RewriteRequest, RuleSet, Substitution, Symbol, SymbolKind,
    Term, TermFactory, Unary,
)


class Kernel:
    def __init__(self, factory: TermFactory, limits: Limits | None = None) -> None:
        self.factory = factory
        self.limits = Limits() if limits is None else limits
        self.normalizer = ScalarNormalizer(factory, self.limits)
        self.rewriter = Rewriter(factory, self.limits)
        self.algebras: dict[object, AlgebraDefinition] = {}
        self.calculus = Calculus(factory, self.limits, evaluate=self.evaluate)
        self._iteration_budget = ContextVar('mathlang_iteration_budget', default=None)

    def algebra_for(self, *terms: Term) -> AlgebraDefinition | None:
        domains = set()
        seen = set()
        stack = list(terms)
        while stack:
            term = stack.pop()
            if id(term) in seen:
                continue
            seen.add(id(term))
            if isinstance(term, Symbol) and term.annotation is not None and term.annotation.identity is not None:
                domains.add(term.annotation.identity)
            stack.extend(term.children)
        if len(domains) > 1:
            names = ", ".join(self.algebras[d].name for d in domains if d in self.algebras)
            raise AlgebraError(f"Cannot combine elements of different algebras: {names}; no embedding is declared")
        if not domains:
            return None
        domain = next(iter(domains))
        if domain not in self.algebras:
            raise AlgebraError("Algebra definition is unavailable for this expression")
        return self.algebras[domain]

    def transform(self, name: str, term: Term, *, context=None) -> Term:
        from .logic import PredicateQuery
        query = PredicateQuery(self.factory, context=context, limits=self.limits, algebras=self.algebras)
        if isinstance(term, Predicate):
            return self.factory.truth(query.query(term))
        if isinstance(term, Function):
            return self.factory.function(term.parameters, self.transform(name, self.evaluate(term.body, context=context), context=context), term.return_type)
        if isinstance(term, TaylorSeries):
            return self.factory._intern(TaylorSeries, term.variable, term.point,
                                        tuple(self.transform(name, c, context=context) for c in term.coefficients))
        algebra = self.algebra_for(term)
        normalizer = (ScalarNormalizer(self.factory, self.limits, query=query.query) if algebra is None
                      else AlgebraNormalizer(algebra, self.factory, self.limits, query=query.query))
        return getattr(normalizer, name)(term)

    def validate_algebra_operands(self, term: Term) -> None:
        algebra = self.algebra_for(term)
        if algebra is None:
            return
        ranks = {"Nat": 0, "Integer": 1, "Rational": 2, "Real": 3, "Complex": 4}
        seen = set()
        stack = [term]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, Symbol) and node.annotation != algebra.type:
                annotation = node.annotation
                if (annotation is None or annotation.arguments or annotation.name not in ranks
                        or ranks[annotation.name] > ranks[algebra.scalar_domain.name]):
                    raise AlgebraError(f"Cannot combine {algebra.name} over {algebra.scalar_domain} "
                                       f"with {node.name!r} of type {annotation}; no scalar embedding is declared")
            stack.extend(node.arguments if isinstance(node, FunctionCall) else node.children)

    def evaluate(self, term: Term, *, context=None) -> Term:
        token = None
        if self._iteration_budget.get() is None:
            token = self._iteration_budget.set(IterationBudget())
        try:
            return self._evaluate(term, context=context)
        finally:
            if token is not None:
                self._iteration_budget.reset(token)

    def _evaluate(self, term: Term, *, context=None) -> Term:
        """Run explicit transformations while leaving ordinary arithmetic intact."""
        Elaborator(self.limits, self.algebras).infer(term)
        from .logic import PredicateQuery
        query = PredicateQuery(self.factory, context=context, limits=self.limits, algebras=self.algebras)
        memo: dict[Term, Term] = {}
        steps = 0

        def visit(root: Term) -> Term:
            nonlocal steps
            stack = [(root, False)]
            while stack:
                node, ready = stack.pop()
                if node in memo:
                    continue
                if not ready:
                    self._iteration_budget.get().tick(self.limits)
                    steps += 1
                    if steps > self.limits.max_steps:
                        raise NormalizationError("Kernel computation step limit exceeded")
                    stack.append((node, True))
                    # Function bodies are evaluated on invocation, not creation.
                    children = () if isinstance(node, (Function, ForAll)) else node.children
                    stack.extend((child, False) for child in reversed(children))
                    continue
                match node:
                    case Number() | Symbol() | Function() | ForAll() | RuleSet() | Truth():
                        result = node
                    case Comparison(op=op, left=left, right=right):
                        result = self.factory.comparison(op, memo[left], memo[right])
                    case Logical(op=op, operands=operands):
                        result = self.factory.logical(op, *(memo[p] for p in operands))
                    case Defined(expression=expression):
                        result = self.factory._intern(Defined, memo[expression])
                    case Unary(op=op, operand=operand):
                        result = self.factory.unary(op, memo[operand])
                    case Binary(op=op, left=left, right=right):
                        result = self.factory.binary(op, memo[left], memo[right])
                    case FunctionCall(callee=callee, arguments=arguments):
                        function = memo[callee]
                        args = tuple(memo[arg] for arg in arguments)
                        if (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                                and function.name == 'factorial'):
                            result = factorial(self, args, context, self._iteration_budget.get())
                        elif (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                                and function.name in ITERATION_NAMES):
                            result = execute_iteration(self, function.name, args, context, self._iteration_budget.get())
                        elif (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                                and function.name in ("normalize", "simplify")):
                            if len(args) != 1:
                                raise NormalizationError(f"{function.name} expects one expression")
                            result = self.transform(function.name, args[0], context=context)
                        elif (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                              and function.name == "numeric"):
                            if len(args) not in (1, 2):
                                raise NormalizationError("numeric expects an expression and optional precision")
                            result = evaluate_numeric(self.factory, args[0], args[1] if len(args) == 2 else None,
                                                      limits=self.limits)
                        elif (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                              and function.name in ('query', 'domain')):
                            if len(args) != 1:
                                raise ValueError(f'{function.name} expects one argument')
                            result = (self.factory.truth(query.query(args[0])) if function.name == 'query'
                                      else self.factory._intern(Defined, args[0]))
                        elif (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                              and function.name in ("derivative", "antiderivative", "integrate", "series", "limit")):
                            result = visit(calculus_call(self.factory, function.name, args))
                        elif (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                              and function.name == "polynomial"):
                            if len(args) != 1 or not isinstance(args[0], TaylorSeries):
                                raise NormalizationError("polynomial expects one Taylor series; this explicitly discards its remainder")
                            result = self.normalizer.simplify(args[0].polynomial(self.factory))
                        elif (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                              and function.name == "substitute"):
                            raise NormalizationError("substitute expects one expression and named replacements")
                        elif (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                              and function.name == "rewrite"):
                            if len(args) != 2 or not isinstance(args[1], RuleSet):
                                raise RewriteError("An indirect rewrite call requires an explicit rule set")
                            result = self.rewriter.apply(args[0], args[1], query=query.query).term
                        else:
                            result = self.factory.call(function, args, checker=Elaborator(self.limits, self.algebras))
                            if isinstance(function, (Function, CalculusOperator)):
                                result = visit(result)
                    case Approach(variable=variable, point=point):
                        result = self.factory._intern(Approach, memo[variable], memo[point])
                    case CalculusOperator(operation=operation, variable=variable, order=order, point=point, upper=upper):
                        result = self.factory._intern(CalculusOperator, operation, memo[variable], memo[order],
                                                      None if point is None else memo[point], None if upper is None else memo[upper])
                        self.calculus.validate_operator(result)
                    case CalculusRequest(operator=operator, expression=expression):
                        result = self.calculus.apply(memo[operator], memo[expression])
                    case TaylorSeries(variable=variable, point=point, coefficients=coefficients):
                        result = self.factory._intern(TaylorSeries, variable, memo[point], tuple(memo[c] for c in coefficients))
                    case Substitution(expression=expression, replacements=replacements):
                        values = {symbol: memo[value] for symbol, value in replacements}
                        result = visit(self.factory.substitute(memo[expression], values))
                    case RewriteRequest(expression=expression, rules=rules, strategy=strategy, repeat=repeat):
                        selected = memo[rules]
                        if not isinstance(selected, RuleSet):
                            raise RewriteError("rewrite expects a rule set as its second argument")
                        result = self.rewriter.apply(memo[expression], selected, strategy=strategy, repeat=repeat, query=query.query).term
                    case _:
                        if not node.children:
                            result = node
                        else:
                            raise TypeError(f"Unsupported term: {type(node).__name__}")
                memo[node] = result
            return memo[root]

        try:
            return visit(term)
        except RecursionError:
            raise NormalizationError("Expression nesting is too deep to evaluate") from None
