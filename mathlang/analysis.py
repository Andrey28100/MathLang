"""Exact, bounded real calculus on immutable scalar terms.

Derivatives and primitives are local formulas on the regular domain of the
input. Taylor coefficients use truncated power-series arithmetic. Finite
limits use the same arithmetic with certified cancellation of removable zeros;
neither numerical sampling nor unbounded applications of l'Hopital are used.
"""

from fractions import Fraction

from .normalization import Limits, NormalizationError, _Computation
from .terms import (
    Approach, Binary, CalculusOperator, CalculusRequest, Function, FunctionCall, Number, Symbol, SymbolKind,
    TaylorSeries, Term, TermFactory, Type, Unary, builtin_symbol, free_symbols,
)


class AnalysisError(NormalizationError):
    """Unsupported calculus, an undefined input, or an exhausted resource budget."""


def _numeric(term: Term) -> Fraction | None:
    if isinstance(term, Number):
        return term.value
    if isinstance(term, Unary) and isinstance(term.operand, Number):
        return -term.operand.value if term.op == "-" else term.operand.value
    return None


def _builtin(term: Term, name: str) -> bool:
    return (isinstance(term, FunctionCall) and isinstance(term.callee, Symbol)
            and term.callee.kind == SymbolKind.BUILTIN and term.callee.name == name
            and len(term.arguments) == 1)


class Calculus:
    def __init__(self, factory: TermFactory, limits: Limits | None = None, *, evaluate=None):
        self.factory = factory
        self.limits = Limits() if limits is None else limits
        self.evaluate = evaluate

    def validate_operator(self, operator: CalculusOperator) -> None:
        work = _Analysis(self.factory, self.limits)
        variable = work.coordinate(operator.variable)
        if operator.operation == 'integrate':
            if operator.point is None or operator.upper is None:
                raise AnalysisError('integrate requires lower and upper bounds; use antiderivative for a primitive')
        elif operator.upper is not None:
            raise AnalysisError('Only definite integration accepts an upper bound')
        order = _numeric(work.clean(operator.order))
        minimum = 1 if operator.operation == "series" else 0
        if order is None or order.denominator != 1 or not minimum <= order <= self.limits.max_calculus_order:
            raise AnalysisError(f"{operator.operation} order must be an integer between {minimum} and {self.limits.max_calculus_order}")
        if operator.point is not None:
            point = work.validate(operator.point)
            if not work.independent(point, variable):
                raise AnalysisError("The point must be independent of the calculus variable")
        if operator.upper is not None:
            point = work.validate(operator.upper)
            if not work.independent(point, variable):
                raise AnalysisError('The upper bound must be independent of the calculus variable')

    def apply(self, operator: CalculusOperator, expression: Term) -> Term:
        work = _Analysis(self.factory, self.limits, evaluate=self.evaluate)
        try:
            result = work.apply(operator, expression)
            work.check_size(result)
            return result
        except AnalysisError:
            raise
        except NormalizationError as error:
            raise AnalysisError(str(error)) from None

    def derivative(self, expression: Term, variable: Symbol, order: int = 1) -> Term:
        return self.apply(CalculusOperator("derivative", variable, self.factory.number(order)), expression)

    def antiderivative(self, expression: Term, variable: Symbol) -> Term:
        return self.apply(CalculusOperator("antiderivative", variable, self.factory.number(1)), expression)

    def integrate(self, expression: Term, variable: Symbol, lower: Term, upper: Term) -> Term:
        return self.apply(CalculusOperator('integrate', variable, self.factory.number(1), lower, upper), expression)

    def series(self, expression: Term, variable: Symbol, point: Term, order: int = 6) -> Term:
        return self.apply(CalculusOperator("series", variable, self.factory.number(order), point), expression)

    def limit(self, expression: Term, variable: Symbol, point: Term) -> Term:
        return self.apply(CalculusOperator("limit", variable, self.factory.number(1), point), expression)


class _Analysis:
    def __init__(self, factory: TermFactory, limits: Limits, *, evaluate=None):
        self.f, self.limits = factory, limits
        # One shared arithmetic budget for the entire transformation, including
        # repeated derivatives and every coefficient of a series.
        self.scalar = _Computation(factory, limits)
        self.depends: dict[tuple[Term, Symbol], bool] = {}
        self.jets: dict[tuple[Term, int], tuple[Term, ...]] = {}
        self.fractions = {}
        self.regular_denominators = set()
        self.zero, self.one = self.f.number(0), self.f.number(1)
        self.evaluate = evaluate

    def tick(self):
        self.scalar.tick()

    def clean(self, term: Term) -> Term:
        value = self.scalar.run(term, expand=False)
        number = _numeric(value)
        return self.f.number(number) if number is not None else value

    def binary(self, op: str, a: Term, b: Term) -> Term:
        self.tick()
        if op == "*" and (_numeric(a) == 0 or _numeric(b) == 0):
            return self.zero
        if op == "+" and _numeric(a) == 0:
            return b
        if op == "-" and a is b:
            return self.zero
        result = self.scalar.binary(op, a, b)
        value = _numeric(result)
        return self.f.number(value) if value is not None else result

    def add(self, a, b):
        return self.binary("+", a, b)

    def sub(self, a, b):
        return self.binary("-", a, b)

    def mul(self, a, b):
        return self.binary("*", a, b)

    def div(self, a, b):
        if _numeric(a) == 0 and self.nonzero(b):
            return self.zero
        return self.binary("/", a, b)

    def power(self, a, exponent):
        if exponent == 0 or _numeric(a) == 1:
            return self.one
        return self.binary("^", a, self.f.number(exponent))

    def neg(self, a):
        return self.mul(self.f.number(-1), a)

    def call(self, name: str, value: Term):
        return self.clean(self.f.call(builtin_symbol(name), (value,)))

    def independent(self, term: Term, variable: Symbol) -> bool:
        key = (term, variable)
        stack = [(term, False)]
        while stack:
            node, ready = stack.pop()
            current = (node, variable)
            if current in self.depends:
                continue
            self.tick()
            if isinstance(node, Symbol):
                self.depends[current] = node != variable
            elif isinstance(node, Function):
                self.depends[current] = variable not in free_symbols(node)
            elif ready:
                self.depends[current] = all(self.depends[(child, variable)] for child in node.children)
            else:
                stack.append((node, True))
                stack.extend((child, False) for child in reversed(node.children))
        return self.depends[key]

    def check_size(self, term: Term):
        seen = set()
        stack = [term]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            self.tick()
            if len(seen) > self.limits.max_nodes:
                raise AnalysisError("Calculus result node limit exceeded")
            stack.extend(node.children)
        if isinstance(term, TaylorSeries) and sum(_numeric(c) != 0 for c in term.coefficients) > self.limits.max_terms:
            raise AnalysisError("Taylor coefficient count limit exceeded")

    def positive(self, term: Term) -> bool:
        value = _numeric(term)
        if value is not None:
            return value > 0
        return _builtin(term, "exp")

    def nonzero(self, term: Term) -> bool:
        value = _numeric(term)
        if value is not None:
            return value != 0
        if _builtin(term, "exp"):
            return True
        if isinstance(term, Unary):
            return self.nonzero(term.operand)
        if isinstance(term, Binary) and term.op in ("*", "/"):
            return self.nonzero(term.left) and self.nonzero(term.right)
        if isinstance(term, Binary) and term.op == "^":
            return self.nonzero(term.left)
        if _builtin(term, "sqrt"):
            return self.positive(term.arguments[0])
        return False

    def validate(self, term: Term) -> Term:
        """Reject bad types and known undefined subterms before discarding zeros."""
        visited = set()
        stack = [term]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            self.tick()
            if len(visited) > self.limits.max_nodes:
                raise AnalysisError("Calculus expression node limit exceeded")
            if isinstance(node, Symbol):
                annotation = node.annotation
                if (annotation is None or annotation.arguments or annotation.identity is not None
                        or annotation.name not in ("Nat", "Integer", "Rational", "Real")
                        or node.kind in (SymbolKind.BUILTIN, SymbolKind.GENERATOR)):
                    raise AnalysisError(f"Real calculus requires scalar symbols; {node.name!r} has type {annotation}")
            elif isinstance(node, FunctionCall):
                if not isinstance(node.callee, Symbol):
                    raise AnalysisError("Calculus requires a resolved scalar function")
                if len(node.arguments) != 1:
                    raise AnalysisError("Calculus currently supports unary scalar function calls")
                if node.callee.kind == SymbolKind.BUILTIN and node.callee.name not in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs"):
                    raise AnalysisError(f"No calculus rule for {node.callee.name}")
                value = _numeric(self.clean(node.arguments[0]))
                if value is not None and ((_builtin(node, "log") and value <= 0)
                                          or (_builtin(node, "sqrt") and value < 0)):
                    raise AnalysisError("The function argument is outside its real domain")
            elif isinstance(node, Binary) and node.op == "^":
                base, exponent = _numeric(self.clean(node.left)), _numeric(self.clean(node.right))
                if base is not None and base < 0 and exponent is not None and exponent.denominator % 2 == 0:
                    raise AnalysisError("A negative base with an even root is outside the real domain")
            elif not isinstance(node, (Number, Unary, Binary)):
                raise AnalysisError(f"No scalar calculus for {type(node).__name__}")
            stack.extend(node.arguments if isinstance(node, FunctionCall) else node.children)
        return self.clean(term)

    def coordinate(self, variable: Term) -> Symbol:
        if (not isinstance(variable, Symbol) or variable.kind not in
                (SymbolKind.VARIABLE, SymbolKind.PARAMETER, SymbolKind.UNKNOWN)):
            raise AnalysisError("A calculus variable must be a declared real symbol")
        if variable.annotation is not None and variable.annotation != Type("Real"):
            raise AnalysisError(f"Calculus variable {variable.name!r} must have type Real")
        return variable

    def apply(self, operator: CalculusOperator, expression: Term) -> Term:
        try:
            variable = self.coordinate(operator.variable)
            order = _numeric(self.clean(operator.order))
            minimum = 1 if operator.operation == "series" else 0
            if order is None or order.denominator != 1 or not minimum <= order <= self.limits.max_calculus_order:
                raise AnalysisError(f"{operator.operation} order must be an integer between {minimum} and {self.limits.max_calculus_order}")
            order = int(order)
            if isinstance(expression, TaylorSeries):
                return self.transform_series(operator, expression, variable, order)
            if (isinstance(expression, FunctionCall) and isinstance(expression.callee, Symbol)
                    and expression.callee.kind == SymbolKind.BUILTIN and expression.callee.name == 'sum'
                    and len(expression.arguments) == 3):
                function, lower, upper = expression.arguments
                if operator.operation == 'series':
                    raise AnalysisError('Substitute finite sum bounds before constructing a Taylor series')
                if not self.independent(lower, variable) or not self.independent(upper, variable):
                    raise AnalysisError('Termwise calculus requires bounds independent of its variable')
                if not isinstance(function, Function) or len(function.parameters) != 1:
                    raise AnalysisError('Termwise calculus requires an explicit unary summand function')
                index = function.parameters[0]
                # The calculus coordinate cannot capture the bound summation index.
                fresh = Symbol(index.name, index.kind, index.annotation)
                body = self.f.substitute(function.body, {index: fresh})
                mapped = self.f.function((fresh,), self.f._intern(CalculusRequest, operator, body))
                return self.f.call(expression.callee, (mapped, lower, upper))
            if (isinstance(expression, Symbol) and expression.kind == SymbolKind.BUILTIN
                    and expression.name in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs")):
                parameter = Symbol(variable.name, SymbolKind.VARIABLE, Type("Real"))
                expression = self.f.function((parameter,), self.f.call(expression, (parameter,)))
            if isinstance(expression, Function):
                if operator.operation in ("series", "limit", "integrate") and len(expression.parameters) != 1:
                    raise AnalysisError("Series, limits and definite integrals of function objects require a unary function")
                candidates = [p for p in expression.parameters if p.name == variable.name]
                parameter = (candidates[0] if len(candidates) == 1 else
                             variable if variable in free_symbols(expression) else
                             expression.parameters[0] if len(expression.parameters) == 1 else None)
                if parameter is None:
                    raise AnalysisError("The differentiation variable must identify a function parameter")
                self.coordinate(parameter)
                # Short mathematical functions infer scalar parameter types here.
                renames = {p: Symbol(p.name, p.kind, Type("Real"))
                           for p in expression.parameters if p.annotation is None}
                parameters = tuple(renames.get(p, p) for p in expression.parameters)
                body = self.f.substitute(expression.body, renames)
                selected = renames.get(parameter, parameter)
                if operator.operation in ("series", "limit", "integrate"):
                    if parameter not in expression.parameters:
                        raise AnalysisError("For a series, limit or definite integral in a captured parameter, pass a function call as an expression")
                    body = self.f.substitute(body, {selected: variable})
                    return self.apply(operator, body)
                result = self.apply(CalculusOperator(operator.operation, selected, operator.order, operator.point, operator.upper), body)
                return self.f.function(parameters, result)
            original_variable = variable
            if variable.annotation is None:
                variable = Symbol(variable.name, variable.kind, Type("Real"), variable.identity)
                expression = self.f.substitute(expression, {original_variable: variable})
            if self.evaluate is not None:
                expression = self.evaluate(expression)
            expression = self.validate(expression)
            if operator.operation == "derivative":
                result = expression
                for _ in range(order):
                    result = self.differentiate(result, variable)
            elif operator.operation == "antiderivative":
                result = self.primitive(expression, variable)
            elif operator.operation == 'integrate':
                if operator.point is None or operator.upper is None:
                    raise AnalysisError('integrate requires lower and upper bounds; use antiderivative for a primitive')
                lower, upper = self.validate(operator.point), self.validate(operator.upper)
                if not self.independent(lower, variable) or not self.independent(upper, variable):
                    raise AnalysisError('Integration bounds must be independent of the integration variable')
                self.regular_on_interval(expression, variable, lower, upper)
                primitive = self.primitive(expression, variable)
                result = self.sub(self.validate(self.f.substitute(primitive, {variable: upper})),
                                  self.validate(self.f.substitute(primitive, {variable: lower})))
            elif operator.operation in ("series", "limit"):
                if operator.point is None:
                    raise AnalysisError("An expansion or limit point is required")
                point = self.validate(operator.point)
                if not self.independent(point, variable):
                    raise AnalysisError("The point must be independent of the calculus variable")
                self.variable, self.point = variable, point
                self.mode = operator.operation
                count = order if operator.operation == "series" else 1
                coefficients = self.jet(expression, count)
                result = (self.f._intern(TaylorSeries, variable, point, coefficients)
                          if operator.operation == "series" else coefficients[0])
            else:
                raise AnalysisError(f"Unknown calculus operation {operator.operation!r}")
            if variable is not original_variable:
                result = self.f.substitute(result, {variable: original_variable})
            return result
        except RecursionError:
            raise AnalysisError("Expression nesting is too deep for calculus") from None

    def regular_on_interval(self, expression, variable, lower, upper):
        """Conservative interval proof for a proper real integral, never sampling.

        None is an unknown enclosure, not an undefined expression. Partial
        operations must establish their domain over the entire closed interval.
        """
        a, b = _numeric(lower), _numeric(upper)
        domain = (min(a,b), max(a,b)) if a is not None and b is not None else None
        memo = {}

        def require(condition):
            if not condition:
                raise AnalysisError('Cannot establish a regular real integrand on the whole interval; singular or improper integrals are not supported')

        def visit(node):
            if node in memo:
                return memo[node]
            self.tick()
            result = None
            if isinstance(node, Number):
                result = (node.value, node.value)
            elif isinstance(node, Symbol):
                result = domain if node == variable else None
            elif isinstance(node, Unary):
                value = visit(node.operand)
                result = value if value is None or node.op == '+' else (-value[1], -value[0])
            elif isinstance(node, Binary):
                left, right = visit(node.left), visit(node.right)
                if node.op == '/':
                    require(right is not None and (right[0]>0 or right[1]<0) or self.nonzero(node.right))
                    if left is not None and right is not None:
                        values = [x/y for x in left for y in right]
                        result = min(values), max(values)
                elif node.op == '^':
                    exponent = _numeric(self.clean(node.right))
                    if exponent is not None and exponent.denominator == 1:
                        require(exponent > 0 or left is not None and (left[0]>0 or left[1]<0) or self.nonzero(node.left))
                        if abs(exponent) > self.limits.max_power:
                            raise AnalysisError('Integration interval power limit exceeded')
                        if left is not None:
                            n = int(exponent)
                            # Use bounded exact arithmetic before constructing powers.
                            values = [_numeric(self.power(self.f.number(x), n)) for x in left]
                            if n > 0 and n % 2 == 0 and left[0] <= 0 <= left[1]:
                                values.append(Fraction(0))
                            if all(v is not None for v in values):
                                result = min(values), max(values)
                    else:
                        require(left is not None and (left[0]>0 or left[0]==0 and exponent is not None and exponent>0)
                                or self.positive(node.left))
                elif left is not None and right is not None:
                    if node.op == '+':
                        result = left[0]+right[0], left[1]+right[1]
                    elif node.op == '-':
                        result = left[0]-right[1], left[1]-right[0]
                    elif node.op == '*':
                        values = [x*y for x in left for y in right]
                        result = min(values), max(values)
            elif isinstance(node, FunctionCall):
                argument = node.arguments[0]
                interval = visit(argument)
                name = node.callee.name
                require(node.callee.kind == SymbolKind.BUILTIN)
                if name == 'log':
                    require(interval is not None and interval[0]>0 or self.positive(argument))
                elif name == 'sqrt':
                    require(interval is not None and interval[0]>=0 or self.positive(argument))
                elif name == 'tan':
                    require(interval is not None and -1 <= interval[0] <= interval[1] <= 1)
                elif name in ('sin','cos'):
                    result = (Fraction(-1),Fraction(1))
                elif name == 'abs' and interval is not None:
                    result = (Fraction(0) if interval[0]<=0<=interval[1] else min(map(abs,interval)), max(map(abs,interval)))
            if result is not None:
                for value in result:
                    self.scalar.check_number(value)
            memo[node] = result
            return result

        visit(expression)

    def differentiate(self, term: Term, variable: Symbol) -> Term:
        memo = {}
        stack = [(term, False)]
        while stack:
            node, ready = stack.pop()
            if node in memo:
                continue
            self.tick()
            if self.independent(node, variable):
                memo[node] = self.zero
                continue
            log_abs = _builtin(node, "log") and _builtin(node.arguments[0], "abs")
            if not ready:
                stack.append((node, True))
                children = ((node.arguments[0].arguments[0],) if log_abs else
                            node.arguments if isinstance(node, FunctionCall) else node.children)
                stack.extend((child, False) for child in reversed(children))
                continue
            if node == variable:
                result = self.one
            elif isinstance(node, Unary):
                result = memo[node.operand] if node.op == "+" else self.neg(memo[node.operand])
            elif isinstance(node, Binary):
                a, b = node.left, node.right
                da, db = memo[a], memo[b]
                if node.op in ("+", "-"):
                    result = self.binary(node.op, da, db)
                elif node.op == "*":
                    result = self.add(self.mul(da, b), self.mul(a, db))
                elif node.op == "/":
                    result = self.div(self.sub(self.mul(da, b), self.mul(a, db)), self.power(b, 2))
                else:
                    exponent = _numeric(b)
                    if exponent is not None:
                        result = self.zero if exponent == 0 else self.mul(self.mul(b, self.power(a, exponent-1)), da)
                    elif self.independent(b, variable):
                        result = self.mul(self.mul(b, self.binary("^", a, self.sub(b, self.one))), da)
                    elif _numeric(a) is None or self.positive(a):
                        # The logarithm explicitly restricts the variable-power
                        # formula to the positive real branch of the base.
                        result = self.mul(node, self.add(self.mul(db, self.call("log", a)), self.div(self.mul(b, da), a)))
                    else:
                        raise AnalysisError("A symbolic exponent requires a known positive base")
            elif isinstance(node, FunctionCall):
                u = node.arguments[0].arguments[0] if log_abs else node.arguments[0]
                du = memo[u]
                if log_abs or _builtin(node, "log"):
                    result = self.div(du, u)
                elif _builtin(node, "sin"):
                    result = self.mul(self.call("cos", u), du)
                elif _builtin(node, "cos"):
                    result = self.neg(self.mul(self.call("sin", u), du))
                elif _builtin(node, "exp"):
                    result = self.mul(node, du)
                elif _builtin(node, "tan"):
                    result = self.div(du, self.power(self.call("cos", u), 2))
                elif _builtin(node, "sqrt"):
                    result = self.div(du, self.mul(self.f.number(2), node))
                else:
                    raise AnalysisError(f"No derivative rule for {node.callee.name!r}; piecewise and abstract derivatives are not implemented")
            else:
                raise AnalysisError("No derivative rule for this expression")
            memo[node] = result
        return self.clean(memo[term])

    def polynomial(self, term: Term, variable: Symbol) -> dict[int, Term] | None:
        self.tick()
        if self.independent(term, variable):
            return {0: term}
        if term == variable:
            return {1: self.one}
        if isinstance(term, Unary):
            value = self.polynomial(term.operand, variable)
            return None if value is None else {k: c if term.op == "+" else self.neg(c) for k, c in value.items()}
        if not isinstance(term, Binary):
            return None
        a, b = self.polynomial(term.left, variable), self.polynomial(term.right, variable)
        if a is None or b is None:
            return None
        if term.op in ("+", "-"):
            result = dict(a)
            for k, c in b.items():
                result[k] = self.binary(term.op, result.get(k, self.zero), c)
            return result
        if term.op == "*":
            return self.poly_product(a, b)
        if term.op == "/" and set(b) <= {0}:
            return {k: self.div(c, b.get(0, self.zero)) for k, c in a.items()}
        if term.op == "^" and set(b) == {0}:
            exponent = _numeric(b[0])
            if exponent is not None and exponent.denominator == 1 and 0 <= exponent <= self.limits.max_power:
                result = {0: self.one}
                for _ in range(int(exponent)):
                    result = self.poly_product(result, a)
                return result
        return None

    def poly_product(self, a, b):
        result = {}
        for i, x in a.items():
            for j, y in b.items():
                if i+j > self.limits.max_power:
                    raise AnalysisError("Integration polynomial degree limit exceeded")
                result[i+j] = self.add(result.get(i+j, self.zero), self.mul(x, y))
                if len(result) > self.limits.max_terms:
                    raise AnalysisError("Integration polynomial term limit exceeded")
        return result

    def primitive(self, term: Term, variable: Symbol) -> Term:
        self.tick()
        polynomial = self.polynomial(term, variable)
        if polynomial is not None:
            result = self.zero
            for exponent, coefficient in sorted(polynomial.items(), reverse=True):
                result = self.add(result, self.div(self.mul(coefficient, self.power(variable, exponent+1)), self.f.number(exponent+1)))
            return self.clean(result)
        if isinstance(term, Unary):
            result = self.primitive(term.operand, variable)
            return result if term.op == "+" else self.neg(result)
        if isinstance(term, Binary) and term.op in ("+", "-"):
            return self.binary(term.op, self.primitive(term.left, variable), self.primitive(term.right, variable))
        if isinstance(term, Binary) and term.op == "*":
            for constant, dependent in ((term.left, term.right), (term.right, term.left)):
                if self.independent(constant, variable):
                    return self.mul(constant, self.primitive(dependent, variable))
        if isinstance(term, Binary) and term.op == "/":
            if self.independent(term.right, variable):
                return self.div(self.primitive(term.left, variable), term.right)
            if self.independent(term.left, variable):
                return self.mul(term.left, self.primitive(self.power(term.right, -1), variable))
        u, exponent, name = None, None, None
        if isinstance(term, Binary) and term.op == "^" and _numeric(term.right) is not None:
            u, exponent = term.left, _numeric(term.right)
        elif isinstance(term, FunctionCall) and isinstance(term.callee, Symbol) and term.callee.kind == SymbolKind.BUILTIN:
            u, name = term.arguments[0], term.callee.name
        if u is None:
            raise AnalysisError("No supported exact primitive; integration supports polynomials and elementary functions of affine arguments")
        slope = self.differentiate(u, variable)
        if not self.independent(slope, variable) or not self.nonzero(slope):
            raise AnalysisError("Elementary integration requires an affine argument with a known nonzero slope")
        if exponent is not None:
            primitive = (self.call("log", self.call("abs", u)) if exponent == -1 else
                         self.div(self.power(u, exponent+1), self.f.number(exponent+1)))
        elif name == "sin":
            primitive = self.neg(self.call("cos", u))
        elif name == "cos":
            primitive = self.call("sin", u)
        elif name == "exp":
            primitive = self.call("exp", u)
        elif name == "log":
            primitive = self.sub(self.mul(u, self.call("log", u)), u)
        elif name == "sqrt":
            primitive = self.div(self.power(u, Fraction(3, 2)), self.f.number(Fraction(3, 2)))
        else:
            raise AnalysisError(f"No supported exact primitive for {name!r}")
        return self.clean(self.div(primitive, slope))

    def convolution(self, a, b, count):
        return tuple(self.sum(self.mul(a[j], b[k-j]) for j in range(k+1)) for k in range(count))

    def sum(self, terms):
        result = self.zero
        for term in terms:
            result = self.add(result, term)
        return result

    def divide_coefficients(self, a, b, count):
        if not self.nonzero(b[0]):
            raise AnalysisError("Cannot certify that the denominator is nonzero at the expansion point")
        result = []
        for k in range(count):
            result.append(self.div(self.sub(a[k], self.sum(self.mul(b[j], result[k-j]) for j in range(1, k+1))), b[0]))
        return tuple(result)

    def jet(self, term: Term, count: int) -> tuple[Term, ...]:
        if not 1 <= count <= self.limits.max_calculus_order+1:
            raise AnalysisError("Taylor/limit expansion order limit exceeded during cancellation")
        key = (term, count)
        if key in self.jets:
            return self.jets[key]
        self.tick()
        numerator, denominator, constraints = self.fraction(term)
        for constraint in constraints:
            if constraint not in self.regular_denominators:
                self.leading_coefficient(constraint, 1)
                self.regular_denominators.add(constraint)
        if denominator != self.one or numerator is not term:
            result = (self.jet(numerator, count) if denominator == self.one
                      else self.quotient_jet(numerator, denominator, count))
            self.jets[key] = result
            return result
        if self.independent(term, self.variable):
            result = (term, *((self.zero,)*(count-1)))
        elif term == self.variable:
            result = (self.point, *((self.one,) if count > 1 else ()), *((self.zero,)*max(0, count-2)))
        elif isinstance(term, Unary):
            values = self.jet(term.operand, count)
            result = values if term.op == "+" else tuple(map(self.neg, values))
        elif isinstance(term, Binary):
            if term.op == "/":
                result = self.quotient_jet(term.left, term.right, count)
            else:
                a, b = self.jet(term.left, count), self.jet(term.right, count)
                if term.op in ("+", "-"):
                    result = tuple(self.binary(term.op, x, y) for x, y in zip(a, b))
                elif term.op == "*":
                    result = self.convolution(a, b, count)
                else:
                    exponent = _numeric(term.right)
                    if exponent is not None and exponent.denominator == 1:
                        if abs(exponent) > self.limits.max_power:
                            raise AnalysisError("Taylor power limit exceeded")
                        if exponent < 0:
                            result = self.quotient_jet(self.one, self.power(term.left, -exponent), count)
                        else:
                            result = (self.one, *((self.zero,)*(count-1)))
                            power = int(exponent)
                            while power:
                                if power & 1:
                                    result = self.convolution(result, a, count)
                                power //= 2
                                if power:
                                    a = self.convolution(a, a, count)
                    elif exponent is not None and self.positive(a[0]):
                        result = self.rational_power_jet(a, exponent, count)
                    elif self.positive(a[0]):
                        logarithm = self.function_jet("log", a, count)
                        result = self.function_jet("exp", self.convolution(b, logarithm, count), count)
                    else:
                        raise AnalysisError("A noninteger Taylor power requires a known positive constant term")
        elif isinstance(term, FunctionCall) and isinstance(term.callee, Symbol) and term.callee.kind == SymbolKind.BUILTIN:
            result = self.function_jet(term.callee.name, self.jet(term.arguments[0], count), count)
        else:
            raise AnalysisError("No local analytic expansion for this expression")
        result = tuple(self.clean(c) for c in result)
        self.jets[key] = result
        return result

    def quotient_jet(self, numerator: Term, denominator: Term, count: int):
        leading = self.leading_coefficient(denominator, count)
        a = self.jet(numerator, count+leading)
        for coefficient in a[:leading]:
            if _numeric(coefficient) != 0:
                raise AnalysisError("No finite two-sided limit/regular Taylor series: a pole or an unresolved singularity remains")
        b = self.jet(denominator, count+leading)
        return self.divide_coefficients(a[leading:], b[leading:], count)

    def leading_coefficient(self, denominator, probe):
        while True:
            b = self.jet(denominator, probe)
            leading = next((k for k, c in enumerate(b) if _numeric(c) != 0), None)
            if leading is not None:
                break
            if probe == self.limits.max_calculus_order+1:
                raise AnalysisError("Denominator is zero or its vanishing order exceeds the limit")
            probe = min(self.limits.max_calculus_order+1, max(probe+1, probe*2))
        if not self.nonzero(b[leading]):
            raise AnalysisError("Cannot certify the denominator's leading coefficient at this point")
        return leading

    def fraction(self, term):
        """Collect rational operations without forgetting cancelled denominators."""
        if term in self.fractions:
            return self.fractions[term]
        self.tick()
        result = (term, self.one, ())
        if isinstance(term, Unary):
            n, d, guards = self.fraction(term.operand)
            if d != self.one:
                result = (n if term.op == "+" else self.neg(n), d, guards)
            else:
                result = (term, self.one, guards)
        elif isinstance(term, Binary):
            a, b, left_guards = self.fraction(term.left)
            c, d, right_guards = self.fraction(term.right)
            guards = (*left_guards, *right_guards)
            if term.op == "/":
                result = (self.mul(a, d), self.mul(b, c), (*guards, c))
            elif term.op in ("+", "-") and (b != self.one or d != self.one):
                result = (self.binary(term.op, self.mul(a, d), self.mul(b, c)), self.mul(b, d), guards)
            elif term.op == "*" and (b != self.one or d != self.one):
                result = (self.mul(a, c), self.mul(b, d), guards)
            elif term.op == "^":
                exponent = _numeric(term.right)
                if exponent is not None and exponent.denominator == 1:
                    if abs(exponent) > self.limits.max_power:
                        raise AnalysisError("Taylor power limit exceeded")
                    if exponent <= 0:
                        result = (self.power(b, -exponent), self.power(a, -exponent), (*guards, a))
                    elif b != self.one:
                        result = (self.power(a, exponent), self.power(b, exponent), guards)
                    else:
                        result = (term, self.one, guards)
            else:
                result = (term, self.one, guards)
        self.fractions[term] = result
        return result

    def function_jet(self, name: str, u, count):
        if name in ("sin", "cos", "tan"):
            sine, cosine = [self.call("sin", u[0])], [self.call("cos", u[0])]
            for k in range(1, count):
                sine.append(self.div(self.sum(self.mul(self.mul(self.f.number(j), u[j]), cosine[k-j]) for j in range(1, k+1)), self.f.number(k)))
                cosine.append(self.neg(self.div(self.sum(self.mul(self.mul(self.f.number(j), u[j]), sine[k-j]) for j in range(1, k+1)), self.f.number(k))))
            if name == "tan":
                return self.divide_coefficients(sine, cosine, count)
            return tuple(sine if name == "sin" else cosine)
        if name == "exp":
            result = [self.call("exp", u[0])]
            for k in range(1, count):
                result.append(self.div(self.sum(self.mul(self.mul(self.f.number(j), u[j]), result[k-j]) for j in range(1, k+1)), self.f.number(k)))
            return tuple(result)
        if name in ("log", "sqrt") and not self.positive(u[0]):
            raise AnalysisError(f"A regular real {name} expansion requires a known positive argument at the point")
        if name == "log":
            derivative = tuple(self.mul(self.f.number(k+1), u[k+1]) for k in range(count-1))
            quotient = self.divide_coefficients(derivative, u, count-1) if count > 1 else ()
            return (self.call("log", u[0]), *(self.div(c, self.f.number(k+1)) for k, c in enumerate(quotient)))
        if name == "sqrt":
            result = [self.call("sqrt", u[0])]
            for k in range(1, count):
                result.append(self.div(self.sub(u[k], self.sum(self.mul(result[j], result[k-j]) for j in range(1, k))), self.mul(self.f.number(2), result[0])))
            return tuple(result)
        if name == "abs":
            if self.mode == "limit" and count == 1:
                return (self.call("abs", u[0]),)
            if self.positive(u[0]):
                return tuple(u)
            if self.positive(self.neg(u[0])):
                return tuple(map(self.neg, u))
        raise AnalysisError(f"No regular analytic expansion for {name!r} at this point")

    def rational_power_jet(self, u, exponent, count):
        result = [self.power(u[0], exponent)]
        if count > 1:
            derivative = tuple(self.mul(self.f.number(k+1), u[k+1]) for k in range(count-1))
            quotient = self.divide_coefficients(derivative, u, count-1)
            for k in range(1, count):
                result.append(self.mul(self.f.number(exponent/k), self.sum(self.mul(quotient[j], result[k-1-j]) for j in range(k))))
        return tuple(result)

    def transform_series(self, operator, series, variable, order):
        if variable != series.variable:
            raise AnalysisError("Series calculus requires its own expansion variable")
        coefficients = series.coefficients
        if operator.operation == 'limit':
            if operator.point is None or self.clean(operator.point) != self.clean(series.point):
                raise AnalysisError('A truncated Taylor series determines a limit only at its expansion point')
            if not coefficients:
                raise AnalysisError('An O(1) remainder does not determine a limit')
            return self.clean(coefficients[0])
        if operator.operation == 'integrate':
            if operator.point is not None and operator.upper is not None and self.clean(operator.point) == self.clean(operator.upper):
                if self.clean(operator.point) == self.clean(series.point) and coefficients:
                    return self.zero
            raise AnalysisError('A truncated series cannot determine an exact definite integral; use polynomial(series) explicitly for an approximation')
        if operator.operation == "derivative":
            if order > series.order:
                raise AnalysisError("Not enough Taylor coefficients for this derivative order")
            for _ in range(order):
                coefficients = tuple(self.mul(self.f.number(k), c) for k, c in enumerate(coefficients) if k)
        elif operator.operation == "antiderivative":
            if series.order >= self.limits.max_calculus_order:
                raise AnalysisError("Integrated Taylor order exceeds the calculus limit")
            coefficients = (self.zero, *(self.div(c, self.f.number(k+1)) for k, c in enumerate(coefficients)))
        elif (operator.operation == "series" and operator.point is not None
              and self.clean(operator.point) == series.point and order <= series.order):
            coefficients = coefficients[:order]
        else:
            raise AnalysisError("Use the original expression for this operation; a truncated series is not an exact function")
        return self.f._intern(TaylorSeries, variable, series.point, tuple(self.clean(c) for c in coefficients))


def derivative(expression: Term, variable: Symbol, order: int = 1, *, factory: TermFactory | None = None, limits: Limits | None = None) -> Term:
    return Calculus(factory or TermFactory(), limits).derivative(expression, variable, order)


def antiderivative(expression: Term, variable: Symbol, *, factory: TermFactory | None = None, limits: Limits | None = None) -> Term:
    return Calculus(factory or TermFactory(), limits).antiderivative(expression, variable)


def integrate(expression: Term, variable: Symbol, lower: Term, upper: Term, *, factory: TermFactory | None = None, limits: Limits | None = None) -> Term:
    return Calculus(factory or TermFactory(), limits).integrate(expression, variable, lower, upper)


def series(expression: Term, variable: Symbol, point: Term, order: int = 6, *, factory: TermFactory | None = None, limits: Limits | None = None) -> Term:
    return Calculus(factory or TermFactory(), limits).series(expression, variable, point, order)


def limit(expression: Term, variable: Symbol, point: Term, *, factory: TermFactory | None = None, limits: Limits | None = None) -> Term:
    return Calculus(factory or TermFactory(), limits).limit(expression, variable, point)


def calculus_call(factory: TermFactory, operation: str, arguments: tuple[Term, ...],
                  *, order: Term | None = None, binding: Approach | None = None) -> Term:
    """Construct a delayed transformation; resolution of named bindings is external."""
    expression = None
    point = None
    upper = None
    if operation == 'integrate':
        if binding is not None or order is not None or len(arguments) not in (3, 4):
            raise AnalysisError('integrate expects (expression, variable, lower, upper) or (variable, lower, upper); use antiderivative for a primitive')
        variable, point, upper = arguments[-3:]
        expression = arguments[0] if len(arguments) == 4 else None
    elif operation in ("derivative", "antiderivative"):
        if binding is not None or len(arguments) not in (1, 2):
            raise AnalysisError(f"{operation} expects a variable, or an expression and a variable")
        variable = arguments[-1]
        if len(arguments) == 2:
            expression = arguments[0]
    else:
        if binding is None and arguments and isinstance(arguments[-1], Approach):
            binding, arguments = arguments[-1], arguments[:-1]
        if binding is not None:
            if len(arguments) > 1:
                raise AnalysisError(f"{operation} expects one expression and one coordinate binding")
            variable, point = binding.variable, binding.point
            expression = arguments[0] if arguments else None
        elif len(arguments) in (2, 3):
            variable, point = arguments[-2:]
            expression = arguments[0] if len(arguments) == 3 else None
        else:
            raise AnalysisError(f"{operation} requires a point, such as x=0 or x -> 0")
    operator = factory._intern(CalculusOperator, operation, variable,
                               order if order is not None else factory.number(6 if operation == "series" else 1), point, upper)
    return operator if expression is None else factory._intern(CalculusRequest, operator, expression)
