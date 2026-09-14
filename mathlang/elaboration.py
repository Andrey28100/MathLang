"""Bounded static type inference and mathematical operation signatures.

Unknown types of unannotated function parameters remain deferred. Known type
errors are rejected without normalizing or changing the stored expression.
"""

from fractions import Fraction

from .normalization import Limits
from .terms import (Approach, ApproxNumber, Binary, CalculusOperator, CalculusRequest, Function,
                    Comparison, Defined, ForAll, Logical, Predicate, Truth, TruthValue,
                    FunctionCall, Number, RewriteRequest, RuleSet, Substitution,
                    Symbol, SymbolKind, TaylorSeries, Term, Type, Unary)
from .typed_ir import Embed, TypedTerm, TypedValue
from .iteration import ITERATION_NAMES, signature as iteration_signature


class ElaborationError(ValueError):
    pass


SCALARS = ('Nat', 'Integer', 'Rational', 'Real', 'Complex')
REAL = Type('Real')


def scalar_rank(type_: Type | None) -> int | None:
    if type_ is not None and type_.identity is None and not type_.arguments and type_.name in SCALARS:
        return SCALARS.index(type_.name)
    return None


def validate_type(type_: Type) -> None:
    stack = [type_]
    while stack:
        current = stack.pop()
        name, arguments = current.name, current.arguments
        if current.identity is None:
            if (name in SCALARS or name == 'Predicate') and arguments:
                raise ElaborationError(f'{name} does not take type arguments')
            if name in ('Vector', 'Matrix'):
                dimensions = 1 if name == 'Vector' else 2
                if (len(arguments) != dimensions+1 or not isinstance(arguments[0], Type)
                        or any(type(d) is not int or d <= 0 for d in arguments[1:])):
                    raise ElaborationError(f'{name} requires an element type and {dimensions} positive integer dimensions')
            if name == 'Function' and arguments and any(not isinstance(a, Type) for a in arguments):
                raise ElaborationError('Function signature arguments must be types; the last is the result type')
        stack.extend(a for a in arguments if isinstance(a, Type))


def compatible(actual: Type, expected: Type) -> bool:
    if actual == expected:
        return True
    a, b = scalar_rank(actual), scalar_rank(expected)
    if a is not None and b is not None:
        return a <= b
    if actual.identity is not None or expected.identity is not None:
        return False
    if actual.name == expected.name == 'Function' and len(actual.arguments) == len(expected.arguments) and actual.arguments:
        return (all(compatible(e, a) for a, e in zip(actual.arguments[:-1], expected.arguments[:-1]))
                and compatible(actual.arguments[-1], expected.arguments[-1]))
    if actual.name == expected.name and actual.name in ('Vector', 'Matrix'):
        return actual.arguments[1:] == expected.arguments[1:] and compatible(actual.arguments[0], expected.arguments[0])
    return False


class Elaborator:
    def __init__(self, limits: Limits | None = None, algebras=None):
        self.limits = Limits() if limits is None else limits
        self.algebras = {} if algebras is None else algebras
        self.types: dict[Term, Type | None] = {}
        self.numbers: dict[Term, Fraction | None] = {}
        self.specializations: dict[tuple[Function, tuple[Type | None, ...]], Function] = {}
        self.steps = 0

    def tick(self):
        self.steps += 1
        if self.steps > self.limits.max_steps:
            raise ElaborationError('Type inference step limit exceeded')

    def require(self, value: Term, expected: Type, label='Value', *, allow_unknown=False):
        validate_type(expected)
        actual = self.infer(value)
        if actual is not None and self.algebra_embedding(actual, expected):
            return
        if (isinstance(value, Function) and actual == Type('Function')
                and expected.name == 'Function' and expected.arguments
                and len(value.parameters) == len(expected.arguments)-1):
            for parameter, parameter_type in zip(value.parameters, expected.arguments[:-1]):
                if parameter.annotation is not None and not compatible(parameter_type, parameter.annotation):
                    raise ElaborationError(f'{label} cannot accept {parameter_type} as {parameter.name}')
            specialized = self.specialize(value, expected.arguments[:-1])
            self.require(specialized.body, expected.arguments[-1], label+' result', allow_unknown=allow_unknown)
            return
        if actual is None and allow_unknown:
            return
        if actual is None or not compatible(actual, expected):
            raise ElaborationError(f'{label} requires {expected}, got {actual or "an unknown type"}')

    def specialize(self, function: Function, arguments: tuple[Type | None, ...]) -> Function:
        """Give unannotated parameters contextual types without evaluating a call."""
        key = (function, arguments)
        if key not in self.specializations:
            from .terms import TermFactory
            replacements = {
                p: Symbol(p.name, p.kind, type_) for p, type_ in zip(function.parameters, arguments)
                if p.annotation is None and type_ is not None
            }
            factory = TermFactory()
            self.specializations[key] = factory.function(
                tuple(replacements.get(p, p) for p in function.parameters),
                factory.substitute(function.body, replacements), function.return_type,
            ) if replacements else function
        return self.specializations[key]

    def infer(self, term: Term) -> Type | None:
        stack = [(term, False)]
        while stack:
            node, ready = stack.pop()
            if node in self.types:
                continue
            self.tick()
            if not ready:
                stack.append((node, True))
                stack.extend((c, False) for c in reversed(node.children))
                continue
            number = self.constant(node)
            self.numbers[node] = number
            if isinstance(node, Number):
                result = self.number_type(node.value)
            elif isinstance(node, ApproxNumber):
                result = REAL
            elif isinstance(node, Truth):
                if not isinstance(node.value, TruthValue):
                    raise ElaborationError('Invalid truth value')
                result = Type('Predicate')
            elif isinstance(node, Comparison):
                if node.op not in ('==', '===', '!=', '<', '<=', '>', '>='):
                    raise ElaborationError('Invalid comparison operator')
                left, right = self.types[node.left], self.types[node.right]
                if node.op != '===' and left is not None and right is not None:
                    if node.op in ('<', '<=', '>', '>='):
                        if scalar_rank(left) not in (0, 1, 2, 3) or scalar_rank(right) not in (0, 1, 2, 3):
                            raise ElaborationError('Ordering requires real scalar operands')
                    elif not (compatible(left, right) or compatible(right, left)
                              or self.algebra_embedding(left, right) or self.algebra_embedding(right, left)):
                        raise ElaborationError(f'Cannot compare {left} and {right}')
                result = Type('Predicate')
            elif isinstance(node, Logical):
                if node.op not in ('and', 'or', 'not') or len(node.operands) != (1 if node.op == 'not' else 2):
                    raise ElaborationError('Invalid logical operation')
                for operand in node.operands:
                    self.require(operand, Type('Predicate'), 'Logical operand', allow_unknown=True)
                result = Type('Predicate')
            elif isinstance(node, Defined):
                result = Type('Predicate')
            elif isinstance(node, ForAll):
                if (not node.parameters or len(set(node.parameters)) != len(node.parameters)
                        or len({p.name for p in node.parameters}) != len(node.parameters)
                        or any(p.kind != SymbolKind.VARIABLE or p.annotation is None for p in node.parameters)):
                    raise ElaborationError('forall requires distinct typed variable parameters')
                self.require(node.body, Type('Predicate'), 'Quantified body')
                result = Type('Predicate')
            elif isinstance(node, Symbol):
                result = node.annotation
                if node.kind == SymbolKind.BUILTIN:
                    result = (Type('Function', (REAL, REAL)) if node.name in ('sin','cos','tan','exp','log','sqrt','abs')
                              else Type('Function'))
                if result is not None:
                    validate_type(result)
            elif isinstance(node, Unary):
                result = self.types[node.operand]
                if result is not None and scalar_rank(result) is None and result.name not in ('Matrix','Vector') and result.identity is None:
                    raise ElaborationError(f'No unary {node.op} signature for {result}')
                if node.op == '-' and result == Type('Nat'):
                    result = Type('Integer')
            elif isinstance(node, Binary):
                result = self.binary_type(node.op, self.types[node.left], self.types[node.right], self.numbers[node.right])
            elif isinstance(node, Function):
                result_type = node.return_type or self.types[node.body]
                if node.return_type is not None:
                    self.require(node.body, node.return_type, 'Function return', allow_unknown=False)
                result = (Type('Function', (*[p.annotation for p in node.parameters], result_type))
                          if result_type is not None and all(p.annotation is not None for p in node.parameters)
                          else Type('Function'))
            elif isinstance(node, FunctionCall):
                result = self.check_call(node.callee, node.arguments)
            elif isinstance(node, CalculusOperator):
                result = Type('CalculusOperator')
            elif isinstance(node, CalculusRequest):
                value_type = self.types[node.expression]
                if node.operator.operation == 'series':
                    result = Type('Series', (REAL,))
                elif node.operator.operation in ('limit', 'integrate'):
                    result = REAL
                elif value_type == Type('Series', (REAL,)):
                    result = value_type
                elif isinstance(node.expression, Function):
                    result = value_type
                else:
                    result = None if value_type is None else REAL
            elif isinstance(node, TaylorSeries):
                result = Type('Series', (REAL,))
            elif isinstance(node, Substitution):
                # A calculus substitution applies after the transformation, so
                # its scalar result type is already known. Ordinary substitution
                # is checked structurally, without evaluating transformations.
                if isinstance(node.expression, CalculusRequest):
                    result = self.types[node.expression]
                else:
                    from .terms import TermFactory
                    substituted = TermFactory().substitute(node.expression, dict(node.replacements))
                    result = self.infer(substituted)
            elif isinstance(node, RewriteRequest):
                result = None
            elif isinstance(node, Approach):
                result = Type('Approach')
            elif isinstance(node, RuleSet):
                result = Type('RuleSet')
            else:
                result = Type(type(node).__name__)
            if number is not None:
                result = self.number_type(number)
            self.types[node] = result
        return self.types[term]


    def elaborate(self, term: Term) -> TypedValue:
        """Build typed IR for *term*, inserting safe implicit embeddings explicitly.

        The returned graph is inspection/analysis IR; it does not mutate the
        source ``Term`` graph used by normalization and evaluation.
        """
        self.infer(term)
        built: dict[Term, TypedValue] = {}
        stack = [(term, False)]
        while stack:
            node, ready = stack.pop()
            if node in built:
                continue
            self.tick()
            if not ready:
                stack.append((node, True))
                stack.extend((child, False) for child in reversed(node.children))
                continue
            children = tuple(built[child] for child in node.children)
            expected = self._expected_child_types(node)
            if expected is not None:
                converted = []
                for child, expected_type in zip(children, expected):
                    if (isinstance(child.term, Function) and expected_type is not None
                            and expected_type.name == 'Function' and expected_type.arguments
                            and child.type == Type('Function')):
                        child = self.elaborate(self.specialize(child.term, expected_type.arguments[:-1]))
                    if expected_type is None or child.type is None or child.type == expected_type:
                        converted.append(child)
                    elif compatible(child.type, expected_type) or self.algebra_embedding(child.type, expected_type):
                        converted.append(Embed(child, child.type, expected_type))
                    else:
                        # Inference should already have rejected this. Keep this
                        # guard to make the Typed IR contract independently strict.
                        raise ElaborationError(
                            f'Cannot embed {child.type} into {expected_type} while elaborating {type(node).__name__}'
                        )
                children = tuple(converted)
            if (isinstance(node, FunctionCall) and isinstance(node.callee, Symbol)
                    and node.callee.kind == SymbolKind.BUILTIN
                    and node.callee.name in (*ITERATION_NAMES, 'factorial', 'sin','cos','tan','exp','log','sqrt','abs','numeric')):
                # Elementary builtins are overloaded. Record the signature chosen
                # for this call, rather than a misleading Real -> Real default.
                signature = Type('Function', (*[c.type for c in children[1:]], self.types[node]))
                children = (TypedTerm(node.callee, signature), *children[1:])
            built[node] = TypedTerm(node, self.types[node], children)
        return built[term]

    def algebra_embedding(self, actual: Type, expected: Type) -> bool:
        algebra = self.algebras.get(expected.identity)
        return (algebra is not None and scalar_rank(actual) is not None
                and compatible(actual, algebra.scalar_domain))

    def _expected_child_types(self, node: Term) -> tuple[Type | None, ...] | None:
        """Return operation-signature types for direct children of *node*."""
        if isinstance(node, Comparison) and node.op != '===':
            left, right = self.types[node.left], self.types[node.right]
            if scalar_rank(left) is not None and scalar_rank(right) is not None:
                common = Type(SCALARS[max(scalar_rank(left), scalar_rank(right))])
                return (common, common)
            if left is not None and right is not None:
                if self.algebra_embedding(left, right):
                    return (right, right)
                if self.algebra_embedding(right, left):
                    return (left, left)
        if isinstance(node, Logical):
            return (Type('Predicate'),)*len(node.operands)
        if isinstance(node, Binary):
            left, right = self.types[node.left], self.types[node.right]
            result = self.types[node]
            if left is None or right is None or result is None:
                return (None, None)
            a, b = scalar_rank(left), scalar_rank(right)
            if a is not None and b is not None:
                # Exact constants may refine the result to Nat (e.g. -2+3).
                # Operand coercions still follow the operation's domain.
                domain = self.binary_type(node.op, left, right, self.numbers[node.right])
                if node.op == '^':
                    return (domain, right)
                return (domain, domain)
            if result.identity is not None:
                return (result if self.algebra_embedding(left, result) else left,
                        result if node.op in ('+', '-', '*') and self.algebra_embedding(right, result) else right)
            if result.name in ('Matrix', 'Vector'):
                if left.name in ('Matrix', 'Vector'):
                    left_expected = Type(left.name, (result.arguments[0], *left.arguments[1:]))
                elif scalar_rank(left) is not None:
                    left_expected = result.arguments[0]
                else:
                    left_expected = left
                if right.name in ('Matrix', 'Vector'):
                    right_expected = Type(right.name, (result.arguments[0], *right.arguments[1:]))
                elif scalar_rank(right) is not None and node.op != '^':
                    right_expected = result.arguments[0]
                else:
                    right_expected = right
                return (left_expected, right_expected)
            return (left, right)
        if isinstance(node, Unary):
            operand = self.types[node.operand]
            return (Type('Integer') if node.op == '-' and operand == Type('Nat') else operand,)
        if isinstance(node, Function):
            expected = [p.annotation for p in node.parameters]
            expected.append(node.return_type or self.types[node.body])
            return tuple(expected)
        if isinstance(node, FunctionCall):
            signature = self.types[node.callee]
            expected: list[Type | None] = [signature]
            if isinstance(node.callee, Function):
                specialized = self.specialize(node.callee, tuple(self.types[a] for a in node.arguments))
                expected = [self.infer(specialized)]
                expected.extend(p.annotation for p in specialized.parameters)
            elif isinstance(node.callee, Symbol) and node.callee.kind == SymbolKind.BUILTIN:
                if node.callee.name in ITERATION_NAMES:
                    _, inputs = iteration_signature(self, node.callee.name, node.arguments)
                    expected.extend(inputs)
                elif node.callee.name in ('sin','cos','tan','exp','log','sqrt'):
                    expected.extend(self.types[node] for _ in node.arguments)
                else:
                    expected.extend(self.types[a] for a in node.arguments)
            elif signature is not None and signature.name == 'Function' and signature.arguments:
                expected.extend(signature.arguments[:-1])
            else:
                expected.extend(self.types[a] for a in node.arguments)
            return tuple(expected)
        return tuple(self.types[c] for c in node.children)

    @staticmethod
    def number_type(value):
        return Type('Rational' if value.denominator != 1 else 'Integer' if value < 0 else 'Nat')

    def constant(self, node):
        if isinstance(node, Number):
            return node.value
        if isinstance(node, Unary):
            value = self.numbers[node.operand]
            return None if value is None else -value if node.op == '-' else value
        if not isinstance(node, Binary):
            return None
        a, b = self.numbers[node.left], self.numbers[node.right]
        if a is None or b is None:
            return None
        if node.op == '+':
            value = a+b
        elif node.op == '-':
            value = a-b
        elif node.op == '*':
            value = a*b
        elif node.op == '/' and b:
            value = a/b
        elif node.op == '^' and b.denominator == 1 and abs(b) <= self.limits.max_power and (a or b > 0):
            if max(a.numerator.bit_length(), a.denominator.bit_length()) * abs(b) > self.limits.max_integer_bits:
                return None
            value = a**int(b)
        else:
            return None
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > self.limits.max_integer_bits:
            return None
        return value

    def binary_type(self, op, left, right, exponent=None):
        if left is None or right is None:
            return None
        a, b = scalar_rank(left), scalar_rank(right)
        if a is not None and b is not None:
            rank = max(a, b)
            if op == '-':
                rank = max(rank, 1)
            elif op == '/':
                rank = max(rank, 2)
            elif op == '^':
                if b > 1:
                    rank = max(rank, 3)
                elif exponent is not None and exponent < 0 or exponent is None and b == 1:
                    rank = max(rank, 2)
            return Type(SCALARS[rank])
        if left.identity is not None or right.identity is not None:
            domain = left if left.identity is not None else right
            algebra = self.algebras.get(domain.identity)
            if left == right and (op in ('+','-','*') or op == '/' and algebra is not None):
                return domain
            scalar = right if left == domain else left
            rank = scalar_rank(scalar)
            if rank is not None and (algebra is None or rank <= scalar_rank(algebra.scalar_domain)):
                if (op in ('+','-','*') or op == '/' and algebra is not None
                        or left == domain and (op == '/' or op == '^' and rank <= 1)):
                    return domain
            raise ElaborationError(f'No {op} signature for {left} and {right}; no embedding is declared')
        structured = ('Matrix','Vector')
        if left.name in structured or right.name in structured:
            if a is not None and right.name in structured and op == '*':
                field = self.binary_type('*', left, right.arguments[0])
                return Type(right.name, (field, *right.arguments[1:]))
            if b is not None and left.name in structured and op in ('*','/'):
                field = self.binary_type(op, left.arguments[0], right)
                return Type(left.name, (field, *left.arguments[1:]))
            if left.name == right.name and op in ('+','-'):
                if left.arguments[1:] != right.arguments[1:]:
                    raise ElaborationError(f'Cannot {op}: {left} and {right}; dimensions must match')
                field = self.binary_type(op, left.arguments[0], right.arguments[0])
                return Type(left.name, (field, *left.arguments[1:]))
            if left.name == 'Matrix' and right.name in structured and op == '*':
                if left.arguments[2] != right.arguments[1]:
                    raise ElaborationError(f'Cannot multiply {left} by {right}: left.columns = right.rows is required; {left.arguments[2]} != {right.arguments[1]}')
                field = self.binary_type('*', left.arguments[0], right.arguments[0])
                dimensions = (left.arguments[1], right.arguments[2]) if right.name == 'Matrix' else (left.arguments[1],)
                return Type(right.name, (field, *dimensions))
            if left.name == 'Matrix' and op == '^' and b is not None and b <= 1:
                if left.arguments[1] != left.arguments[2]:
                    raise ElaborationError('Matrix powers require a square matrix')
                if exponent is not None and exponent < 0 or exponent is None and b == 1:
                    raise ElaborationError('Matrix powers require a nonnegative exponent; invertibility is not known')
                return left
        raise ElaborationError(f'No {op} signature for {left} and {right}')

    def check_call(self, callee, arguments):
        if isinstance(callee, Function):
            if len(arguments) != len(callee.parameters):
                raise ElaborationError(f'Expected {len(callee.parameters)} arguments, got {len(arguments)}')
            for parameter, argument in zip(callee.parameters, arguments):
                if parameter.annotation is not None:
                    self.require(argument, parameter.annotation, f'Argument {parameter.name!r}', allow_unknown=True)
            specialized = self.specialize(callee, tuple(self.infer(a) for a in arguments))
            self.infer(specialized)
            return callee.return_type or self.infer(specialized.body)
        if isinstance(callee, CalculusOperator):
            return None
        if isinstance(callee, Symbol) and callee.kind == SymbolKind.BUILTIN:
            name = callee.name
            if name == 'factorial':
                if len(arguments) != 1:
                    raise ElaborationError('factorial expects one nonnegative integer')
                self.require(arguments[0], Type('Nat'), 'factorial argument', allow_unknown=True)
                return Type('Nat')
            if name in ITERATION_NAMES:
                return iteration_signature(self, name, arguments)[0]
            if name in ('query', 'domain'):
                if len(arguments) != 1:
                    raise ElaborationError(f'{name} expects one argument')
                if name == 'query':
                    self.require(arguments[0], Type('Predicate'), 'query', allow_unknown=True)
                return Type('Predicate')
            if name in ('sin','cos','tan','exp','log','sqrt','abs'):
                if len(arguments) != 1:
                    raise ElaborationError(f'{name} expects one scalar argument')
                actual = self.infer(arguments[0])
                if actual is None:
                    return None
                rank = scalar_rank(actual)
                if rank is None:
                    from .analytic_lift import supports_function
                    algebra = self.algebras.get(actual.identity)
                    if algebra is not None and supports_function(name, algebra.scalar_domain):
                        return actual
                    raise ElaborationError(f'{name} expects a scalar argument, got {actual}')
                if name == 'abs':
                    return Type(SCALARS[0 if rank <= 1 else min(rank, 3)])
                return Type('Complex') if rank == 4 else REAL
            if name == 'numeric':
                if len(arguments) not in (1, 2):
                    raise ElaborationError('numeric expects an expression and optional precision')
                actual = self.infer(arguments[0])
                if actual is not None and scalar_rank(actual) not in (0, 1, 2, 3):
                    raise ElaborationError(f'numeric currently expects a real scalar expression, got {actual}')
                if len(arguments) == 2:
                    precision = self.constant(arguments[1])
                    if precision is None or precision.denominator != 1:
                        raise ElaborationError('numeric precision must be an integer literal/exact constant')
                return REAL
            if name in ('normalize','simplify'):
                if len(arguments) != 1:
                    raise ElaborationError(f'{name} expects one expression')
                return self.infer(arguments[0])
            if name == 'polynomial':
                if len(arguments) != 1:
                    raise ElaborationError('polynomial expects one Taylor series')
                actual = self.infer(arguments[0])
                if actual is not None and actual != Type('Series', (REAL,)):
                    raise ElaborationError('polynomial expects one Taylor series')
                return REAL
            return None
        signature = self.infer(callee)
        if signature is None:
            return None
        if signature == Type('CalculusOperator'):
            if len(arguments) != 1:
                raise ElaborationError('A calculus operator expects one expression or function')
            return None
        if signature.name != 'Function':
            raise ElaborationError(f'Cannot call an object of type {signature}')
        if not signature.arguments:
            return None
        if len(arguments) != len(signature.arguments)-1:
            raise ElaborationError(f'Expected {len(signature.arguments)-1} arguments, got {len(arguments)}')
        for index, (argument, expected) in enumerate(zip(arguments, signature.arguments[:-1]), 1):
            self.require(argument, expected, f'Argument {index}', allow_unknown=True)
        return signature.arguments[-1]
