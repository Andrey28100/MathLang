from fractions import Fraction
import math
import random
import unittest

from mathlang import (
    AnalysisError, ApproachExpr, Calculus, CalculusOperator, CalculusRequest,
    DefinitionError, Function, LambdaExpr, Limits, Number, ParseError, Session,
    Symbol, SymbolKind, TaylorSeries, TermFactory, Type, derivative, format_term,
    format_tree, free_symbols, parse_expression, parse_program,
)


class AnalysisSyntaxTests(unittest.TestCase):
    def test_limit_approach_and_lambda_have_separate_syntax_nodes(self):
        node = parse_expression("limit(sin(x)/x, x -> 0)")
        self.assertIsInstance(node.arguments[1], ApproachExpr)
        self.assertEqual(node.arguments[1].span.start, 16)
        self.assertIn("ApproachExpr", format_tree(node))
        function = parse_expression("x => x^2+1")
        self.assertIsInstance(function, LambdaExpr)
        self.assertEqual(function.body.op, "+")
        self.assertIn("LambdaExpr", format_tree(function))

    def test_multiline_calculus_and_lambda(self):
        program = parse_program("f = x =>\n x^2\ng = f\n |> derivative(x, order=2)\n")
        self.assertEqual(len(program.statements), 2)
        expression = parse_expression("limit( sin(x)/x, x ->\n 0 )")
        self.assertEqual(expression.arguments[1].point.text, "0")

    def test_invalid_syntax_is_not_partially_consumed(self):
        for text in ("x =>", "x -> 0", "limit(x,x ->)", "x => => x", "2 => x", "series(x,x=0,x=1)"):
            with self.subTest(text=text), self.assertRaises(ParseError):
                parse_expression(text)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute("variable x : Real; variable y : Real; parameter a : Real")

    def resolve(self, text):
        return self.session.resolve(text)

    def same(self, actual, expected):
        left = actual if not isinstance(actual, str) else self.resolve(actual)
        right = self.resolve(expected)
        self.assertEqual(self.session.kernel.transform("normalize", left),
                         self.session.kernel.transform("normalize", right))

    def test_polynomial_and_elementary_derivatives(self):
        cases = {
            "x^4+3*x^2+a*x+7": "4*x^3+6*x+a",
            "sin(x^2)": "2*x*cos(x^2)",
            "cos(3*x)": "-3*sin(3*x)",
            "exp(a*x)*sin(x)": "a*exp(a*x)*sin(x)+exp(a*x)*cos(x)",
            "a*y": "0", "x^1": "1", "x^0": "0", "(x+1)*(x-1)": "2*x",
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.same(f"derivative({expression},x)", expected)
        for source in ("derivative(log(x),x)", "derivative(sqrt(x),x)", "derivative(tan(x),x)", "derivative(x^(-2),x)"):
            result = self.resolve(source)
            self.assertNotIsInstance(result, CalculusRequest)
        self.same("derivative(log(abs(x)),x) |> substitute(x=2)", "1/2")

    def test_higher_derivatives_and_exact_order_arguments(self):
        self.same("derivative(x^5,x,order=3)", "60*x^2")
        self.same("derivative(x^2,x,order=5)", "0")
        self.same("derivative(x^2,x,order=0)", "x^2")
        self.same("derivative(sin(x),x,order=4)", "sin(x)")
        self.same("derivative(x^4,x,order=1+1)", "12*x^2")
        self.same("derivative(x^a,x) |> substitute(x=2,a=3)", "12")
        self.same("derivative(x^x,x) |> substitute(x=1) |> simplify", "1")

    def test_first_class_functions_operators_and_pipeline(self):
        self.session.execute("f = x => x^3; D=derivative(x); g=D(f); apply(h,t)=h(t)")
        self.assertIsInstance(self.session["D"], CalculusOperator)
        self.assertIsInstance(self.session["g"], Function)
        self.same("g(2)", "12")
        self.same("apply(D,x^2)", "2*x")
        self.same("sin(x) |> derivative(x) |> substitute(x=0) |> simplify", "1")
        self.session.execute("h(t)=exp(t); dh=derivative(h,x) |> simplify")
        self.same("dh(0) |> simplify", "1")
        self.assertEqual(self.resolve("f |> series(x=0,order=5)").coefficients[3], self.session.factory.number(1))
        self.same("limit(f,x -> 2)", "8")
        self.session.execute("apply2(h,u,v)=h(u,v); d=derivative; S=series(x=0,order=3)")
        self.same("apply2(d,x^2,x)", "2*x")
        self.assertEqual(self.resolve("S(exp(x))").order, 3)

    def test_deferred_derivatives_preserve_the_coordinate_before_argument_substitution(self):
        self.session.execute("slope(t)=derivative(t^2,t); nth(n)=derivative(x^5,x,order=n); diff(t)=derivative(t,x)")
        self.same("slope(3)", "6")
        self.same("slope(y)", "2*y")
        self.same("nth(2)", "20*x^3")
        self.same("diff(sin(x))", "cos(x)")
        self.session.execute("clean(t)=normalize(t^2+2*t+1); dclean=derivative(clean,x)")
        self.same("dclean(2)", "6")

    def test_builtin_functions_are_first_class_calculus_arguments(self):
        self.session.execute("D=derivative(x); dsin=D(sin); F=antiderivative(cos,x)")
        self.same("dsin(0) |> simplify", "1")
        self.same("F(0) |> simplify", "0")
        self.same("limit(sin,x -> 0)", "0")
        result = self.resolve("series(exp,x=0,order=4)")
        self.assertEqual([c.value for c in result.coefficients], [1,1,Fraction(1,2),Fraction(1,6)])

    def test_multivariable_function_and_capture_identity(self):
        self.session.execute("f(x,y)=x^2*y+a; dx=derivative(f,x); dy=derivative(f,y)")
        self.same("dx(2,3)", "12")
        self.same("dy(2,3)", "4")
        self.assertNotEqual(self.session["f"].parameters[0], self.session["x"])
        self.session.execute("h(t)=derivative(t^2,t)+x; h2=substitute(h,x=y)")
        self.same("h2(3)", "6+y")
        self.session.execute("wave(t)=exp(a*t); da=derivative(wave,a)")
        self.same("da(2)", "2*exp(2*a)")
        with self.assertRaises(DefinitionError):
            self.resolve("series(wave,a=0,order=3)")

    def test_primitives_and_round_trip_by_differentiation(self):
        for expression in ("x^4+3*x^2+a*x+7", "sin(2*x+1)", "cos(3*x)", "exp(2*x)", "1/x", "1/(2*x+1)", "x^(-2)"):
            with self.subTest(expression=expression):
                primitive = self.resolve(f"antiderivative({expression},x)")
                back = Calculus(self.session.factory).derivative(primitive, self.session["x"])
                # Rational formulas are compared at several exact regular points.
                for point in (1, 2, 3):
                    bindings = {self.session["x"]: self.session.factory.number(point)}
                    actual = self.session.factory.substitute(back, bindings)
                    expected = self.session.factory.substitute(self.resolve(expression), bindings)
                    self.assertEqual(self.session.kernel.transform("simplify", actual),
                                     self.session.kernel.transform("simplify", expected))
        self.session.execute("f=x=>x^2; F=antiderivative(f,x)")
        self.same("F(3)", "9")

    def test_exact_taylor_coefficients(self):
        cases = {
            "exp(x)": [1, 1, Fraction(1,2), Fraction(1,6), Fraction(1,24), Fraction(1,120)],
            "sin(x)": [0, 1, 0, Fraction(-1,6), 0, Fraction(1,120)],
            "cos(x)": [1, 0, Fraction(-1,2), 0, Fraction(1,24), 0],
            "1/(1-x)": [1]*6,
            "log(1+x)": [0, 1, Fraction(-1,2), Fraction(1,3), Fraction(-1,4), Fraction(1,5)],
            "sqrt(1+x)": [1, Fraction(1,2), Fraction(-1,8), Fraction(1,16), Fraction(-5,128), Fraction(7,256)],
            "sin(x)/x": [1, 0, Fraction(-1,6), 0, Fraction(1,120), 0],
            "tan(x)": [0, 1, 0, Fraction(1,3), 0, Fraction(2,15)],
            "(1+x)^(1/3)": [1, Fraction(1,3), Fraction(-1,9), Fraction(5,81), Fraction(-10,243), Fraction(22,729)],
        }
        for expression, coefficients in cases.items():
            with self.subTest(expression=expression):
                result = self.resolve(f"series({expression},x=0,order=6)")
                self.assertIsInstance(result, TaylorSeries)
                self.assertEqual(result.order, 6)
                self.assertEqual([c.value for c in result.coefficients], coefficients)

    def test_shifted_series_symbolic_coefficients_and_function_example(self):
        result = self.resolve("series(x^3,x=2,order=5)")
        self.assertEqual([c.value for c in result.coefficients], [8,12,6,1,0])
        self.session.execute("f(x)=exp(a*x)*sin(x)")
        result = self.resolve("f |> series(x=0,order=6)")
        for coefficient, expected in zip(result.coefficients, ("0", "1", "a", "a^2/2-1/6", "a^3/6-a/6", "a^4/24-a^2/12+1/120")):
            self.same(coefficient, expected)
        self.assertNotIn(self.session["x"], free_symbols(result.coefficients[3]))
        self.assertIn("O(x^6)", format_term(result))

    def test_series_remainder_survives_transformations(self):
        self.session.execute("s=series(exp(x),x=0,order=5); t=s |> antiderivative(x) |> simplify; d=derivative(s,x)")
        self.assertEqual(self.session["s"].order, 5)
        self.assertEqual(self.session["t"].order, 6)
        self.assertEqual(self.session["d"].order, 4)
        self.assertIn("O(x^6)", format_term(self.session["t"]))
        self.same("polynomial(d)", "1+x+x^2/2+x^3/6")
        proof = self.session.execute("prove s=polynomial(s)").values[0]
        self.assertEqual(proof.status, "unknown")
        with self.assertRaises(DefinitionError):
            self.resolve("substitute(s,x=2)")
        self.same("polynomial(s) |> substitute(x=0)", "1")
        self.assertEqual(self.resolve("series(s,x=0+0,order=2)").order, 2)
        self.assertEqual(self.resolve("derivative(s,x,order=5)").order, 0)
        self.assertEqual(format_term(self.resolve("derivative(s,x,order=5)")), "O(1)")

    def test_finite_limits_and_removable_singularities(self):
        cases = {
            "sin(x)/x": "1", "(exp(x)-1)/x": "1", "(exp(x)-1-x)/x^2": "1/2",
            "(1-cos(x))/x^2": "1/2", "(sin(x)/x-1)/x^2": "-1/6",
            "x^2*sin(x)/x": "0", "1/(sin(x)/x)": "1", "(sqrt(1+x)-1)/x": "1/2",
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.same(f"limit({expression},x -> 0)", expected)
        self.same("limit((x^2-1)/(x-1),x -> 1)", "2")
        self.same("limit(x^2+a,x -> 2)", "4+a")
        self.same("sin(x)/x |> limit(x -> 0)", "1")
        self.session.execute("L=limit(x -> 0)")
        self.same("L(sin(x)/x)", "1")
        self.same("limit(abs(x),x -> 0)", "0")
        self.same("limit(x*(1/x),x -> 0)", "1")
        self.same("limit(1/(1/x),x -> 0)", "0")
        self.same("limit(1/x-1/x,x -> 0)", "0")

    def test_unsupported_or_undefined_analysis_is_diagnosed(self):
        expressions = (
            "derivative(abs(x),x)", "derivative((-2)^x,x)", "antiderivative(sin(x^2),x)",
            "antiderivative(exp(a*x),x)", "limit(1/x,x -> 0)", "limit(abs(x)/x,x -> 0)",
            "limit(1/(a+x),x -> 0)", "series(log(x),x=0)", "series(sqrt(x),x=0)",
            "derivative(log(-1),x)", "derivative(0*(1/0),x)", "derivative(0^0,x)",
            "series(sin(1/x),x=0)", "series(x,x=x)", "limit(x,x -> x+1)",
            "limit((1/(a*x))^0,x -> 0)", "derivative((-2)^(1/2),x)",
        )
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(DefinitionError):
                self.resolve(expression)

    def test_invalid_arguments_types_and_limits(self):
        self.session.execute("n:Integer; A:Matrix<Real,2,2>; c:Complex")
        expressions = (
            "derivative()", "derivative(2)", "derivative(x,2)", "derivative(x,n)",
            "derivative(A,x)", "derivative(c,x)", "derivative(x,x,order=a)",
            "derivative(x,x,order=-1)", "derivative(x,x,order=1/2)", "derivative(x,x,order=33)",
            "series(x,x=0,order=0)", "series(x)", "series(x,x=0,y=0)", "antiderivative(x,x,order=2)",
            "limit(x,x -> 0,order=2)", "polynomial(x)", "series(x,missing=0)",
        )
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(DefinitionError):
                self.resolve(expression)
        small = Session(limits=Limits(max_calculus_order=3))
        small.execute("x:Real")
        with self.assertRaises(DefinitionError):
            small.resolve("series(exp(x),x=0,order=4)")

    def test_failure_rolls_back_output_and_all_new_definitions(self):
        before = dict(self.session.environment.definitions)
        with self.assertRaises(DefinitionError):
            self.session.execute("D=derivative(x); print(D(x^2)); s=series(exp(x),x=0); limit(1/x,x -> 0)")
        self.assertEqual(dict(self.session.environment.definitions), before)

    def test_builtin_shadowing_does_not_change_calculus_rules(self):
        self.session.execute("f=sin(x); sin(t)=t^2; cos(t)=t^3")
        self.same("derivative(sin(x),x)", "2*x")
        result = self.resolve("derivative(f,x)")
        self.assertEqual(result.callee.kind, SymbolKind.BUILTIN)
        self.assertEqual(result.callee.name, "cos")
        self.session.execute("derivative(t)=t+1")
        self.same("derivative(2)", "3")

    def test_python_api_and_dag_sharing(self):
        x = Symbol("x", SymbolKind.VARIABLE, Type("Real"))
        f = TermFactory()
        expression = f.binary("*", x, x)
        self.assertEqual(format_term(derivative(expression, x, factory=f)), "2*x")
        self.assertEqual(derivative(expression, x, factory=f).right, x)
        with self.assertRaises(AnalysisError):
            derivative(expression, x, factory=f, limits=Limits(max_steps=1))

    def test_polynomial_calculus_against_independent_coefficient_formulas(self):
        rng = random.Random(193)
        for _ in range(15):
            coefficients = [rng.randint(-5, 5) for _ in range(7)]
            source = "+".join(f"({c})*x^{k}" if k else str(c) for k, c in enumerate(coefficients))
            count, center = rng.randint(1, 6), rng.randint(-3, 3)
            expansion = self.resolve(f"series({source},x={center},order={count})")
            expected = [sum(Fraction(c)*math.comb(k, j)*center**(k-j)
                            for k, c in enumerate(coefficients) if k >= j) for j in range(count)]
            self.assertEqual([c.value for c in expansion.coefficients], expected)
            order = rng.randint(1, 3)
            derivative_source = "+".join(f"({c*math.factorial(k)//math.factorial(k-order)})" + (f"*x^{k-order}" if k > order else "")
                                        for k, c in enumerate(coefficients) if k >= order)
            self.same(f"derivative({source},x,order={order})", derivative_source)

    def test_shifted_integration_keeps_the_series_coordinate_and_constant(self):
        self.session.execute("s=series(x^2,x=2,order=4); integral=antiderivative(s,x)")
        self.same("polynomial(integral)", "(x^3-8)/3")
        self.assertEqual(self.session["integral"].point.value, 2)
        self.assertEqual(self.session["integral"].order, 5)
        self.session.execute("symbolic=series(exp(x),x=a,order=3)")
        self.same(self.session["symbolic"].coefficients[2], "exp(a)/2")

    def test_analysis_budgets_cover_coefficients_and_cancellation(self):
        for limits, source in (
            (Limits(max_steps=50), "series(exp(sin(x)),x=0,order=10)"),
            (Limits(max_terms=2), "series(exp(x),x=0,order=5)"),
            (Limits(max_calculus_order=3), "limit(sin(x^5)/x^5,x -> 0)"),
        ):
            session = Session(limits=limits)
            session.execute("x:Real")
            with self.subTest(limits=limits), self.assertRaises(DefinitionError):
                session.resolve(source)


if __name__ == "__main__":
    unittest.main()
