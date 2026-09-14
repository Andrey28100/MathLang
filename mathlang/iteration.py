"""Finite higher-order iteration and ordered indexed reductions.

The source binder forms are lowered to ordinary Function/FunctionCall IR.
All runtime loops share the enclosing kernel evaluation's iteration budget.
"""

from dataclasses import dataclass

from .terms import Function, Number, Symbol, SymbolKind, TruthValue, Type, builtin_symbol

ITERATION_NAMES = frozenset({'iterate', 'sum', 'product', 'all', 'any'})


class IterationError(ValueError):
    pass


@dataclass
class IterationBudget:
    iterations: int = 0
    steps: int = 0

    def tick(self, limits, *, iteration=False):
        self.steps += 1
        self.iterations += int(iteration)
        if self.iterations > limits.max_iterations:
            raise IterationError('Iteration count limit exceeded')
        if self.steps > limits.max_steps:
            raise IterationError('Iteration computation step limit exceeded')


def signature(checker, name, arguments):
    """Return result and expected argument types without evaluating any body."""
    from .elaboration import ElaborationError, compatible, scalar_rank
    if len(arguments) != 3:
        raise ElaborationError(f'{name} expects a function and two arguments')
    function, first, last = arguments
    checker.require(last, Type('Nat' if name == 'iterate' else 'Integer'),
                    f'{name} '+('count' if name == 'iterate' else 'upper bound'), allow_unknown=True)

    def called(type_):
        values = (Symbol('index' if name != 'iterate' else 'state', SymbolKind.VARIABLE, type_),)
        if name == 'iterate' and step_arity(checker, function) == 2:
            values += (Symbol('index', SymbolKind.VARIABLE, Type('Nat')),)
        return checker.check_call(function, values)

    if name != 'iterate':
        checker.require(first, Type('Integer'), f'{name} lower bound', allow_unknown=True)
        checker.infer(first)
        lower = checker.numbers.get(first)
        index = Type('Nat' if (lower is not None and lower >= 0) or checker.infer(first) == Type('Nat') else 'Integer')
        result = called(index)
        if name in ('all', 'any'):
            if result is not None and result != Type('Predicate'):
                raise ElaborationError(f'{name} requires a predicate-valued function, got {result}')
            result = Type('Predicate')
        elif result is not None and scalar_rank(result) is None and result.identity is None:
            raise ElaborationError(f'{name} requires scalar or algebra values, got {result}')
        return result, (Type('Function', (index, result)) if result is not None else None,
                        checker.infer(first), checker.infer(last))

    state = checker.infer(first)
    # An explicitly annotated state domain is stable even when exact results
    # have a narrower type. Otherwise widen through safe existing embeddings.
    declared = (function.parameters[0].annotation if isinstance(function, Function) and len(function.parameters) in (1, 2)
                else None)
    if declared is not None:
        checker.require(first, declared, 'iterate initial state', allow_unknown=True)
        state = declared
    for _ in range(8):
        result = called(state)
        if result is None or state is None:
            return None, (None, state, Type('Nat'))
        if compatible(result, state):
            inputs = (state, Type('Nat')) if step_arity(checker, function) == 2 else (state,)
            return state, (Type('Function', (*inputs, state)), state, Type('Nat'))
        if declared is not None:
            raise ElaborationError(f'iterate step returns {result}, outside state type {state}')
        if compatible(state, result) or checker.algebra_embedding(state, result):
            state = result
        else:
            raise ElaborationError(f'iterate step changes state from {state} to incompatible {result}')
    raise ElaborationError('iterate cannot establish a stable state type')


def step_arity(checker, function):
    if isinstance(function, Function):
        return len(function.parameters)
    type_ = checker.infer(function)
    return len(type_.arguments)-1 if type_ is not None and type_.name == 'Function' and type_.arguments else 1


def factorial(kernel, arguments, context, budget):
    from .elaboration import Elaborator, ElaborationError
    if len(arguments) != 1:
        raise ElaborationError('factorial expects one nonnegative integer')
    Elaborator(kernel.limits, kernel.algebras).require(arguments[0], Type('Nat'), 'factorial argument', allow_unknown=True)
    value = kernel.transform('simplify', arguments[0], context=context)
    if not isinstance(value, Number):
        return kernel.factory.call(builtin_symbol('factorial'), arguments)
    if value.value.denominator != 1 or value.value < 0:
        raise IterationError('factorial expects a nonnegative integer')
    count = int(value.value)
    if count > kernel.limits.max_iterations-budget.iterations:
        raise IterationError('Factorial iteration count limit exceeded')
    result = 1
    for n in range(1, count+1):
        budget.tick(kernel.limits, iteration=True)
        result *= n
        if result.bit_length() > kernel.limits.max_integer_bits:
            raise IterationError('Factorial number size limit exceeded')
    return kernel.factory.number(result)


def execute(kernel, name, arguments, context, budget):
    from .elaboration import Elaborator
    from .logic import PredicateQuery
    checker = Elaborator(kernel.limits, kernel.algebras)
    signature(checker, name, arguments)
    function, first, last = arguments
    f, limits = kernel.factory, kernel.limits

    def integer(term, label, *, natural=False):
        term = kernel.transform('simplify', term, context=context)
        if not isinstance(term, Number):
            return None
        if term.value.denominator != 1 or natural and term.value < 0:
            raise IterationError(f'{name} {label} must be an exact '+('nonnegative ' if natural else '')+'integer')
        return int(term.value)

    def compact(term):
        term = kernel.transform('simplify', term, context=context)
        seen, stack = set(), [term]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            budget.tick(limits)
            seen.add(id(node))
            if len(seen) > limits.max_nodes:
                raise IterationError('Iteration result node limit exceeded')
            stack.extend(node.children)
        return term

    def apply(argument, index=None):
        budget.tick(limits, iteration=True)
        values = (argument,) if index is None else (argument, f.number(index))
        return kernel.evaluate(f.call(function, values), context=context)

    if name == 'iterate':
        count = integer(last, 'count', natural=True)
        if count is None:
            return f.call(builtin_symbol(name), arguments)
        if count > limits.max_iterations-budget.iterations:
            raise IterationError('Iteration count limit exceeded')
        state = first
        indexed = step_arity(checker, function) == 2
        for index in range(1, count+1):
            state = compact(apply(state, index if indexed else None))
        return state

    lower, upper = integer(first, 'lower bound'), integer(last, 'upper bound')
    if lower is None or upper is None:
        return f.call(builtin_symbol(name), arguments)
    count = max(0, upper-lower+1)
    if count > limits.max_iterations-budget.iterations:
        raise IterationError('Iteration count limit exceeded')
    if name in ('all', 'any'):
        decisive = TruthValue.FALSE if name == 'all' else TruthValue.TRUE
        unknown = False
        for index in range(lower, upper+1):
            # A fresh query sees each substituted predicate; its memo does not
            # retain the entire index range or consume unrelated query budgets.
            value = PredicateQuery(f, context=context, limits=limits, algebras=kernel.algebras).query(apply(f.number(index)))
            if value is decisive:
                return f.truth(value)
            unknown |= value is TruthValue.UNKNOWN
        return f.truth(TruthValue.UNKNOWN if unknown else TruthValue.TRUE if name == 'all' else TruthValue.FALSE)
    state = f.number(0 if name == 'sum' else 1)
    for index in range(lower, upper+1):
        value = apply(f.number(index))
        state = compact(f.binary('+' if name == 'sum' else '*', state, value))
    return state
