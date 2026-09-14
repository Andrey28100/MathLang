import random
import unittest
from fractions import Fraction

from mathlang import (
    Binary, DefinitionError, Limits, NormalizationError, Number, Session, Symbol, Unary,
    format_term, normalize, simplify,
)


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute("variable x:Real; variable y:Real; parameter a:Real")

    def transform(self, source, operation="normalize"):
        return self.session.resolve(f"{operation}({source})")

    def test_mvp_example_and_preservation_of_original_definition(self):
        self.session.execute("f=2*x+3*x; g=simplify(f)")
        self.assertEqual(format_term(self.session["f"]), "2*x + 3*x")
        self.assertEqual(format_term(self.session["g"]), "5*x")
        self.assertIs(self.session["g"], self.transform("f"))

    def test_exact_arithmetic(self):
        for source, expected in (
            ("1/2+1/3", Fraction(5, 6)), ("0.1+0.2", Fraction(3, 10)),
            ("2^-3", Fraction(1, 8)), ("(3/2)^-2", Fraction(4, 9)),
            ("-2^2", Fraction(-4)), ("(-2)^3", Fraction(-8)),
            ("0^2", Fraction(0)), ("2^0", Fraction(1)), ("2^3^2", Fraction(512)),
        ):
            with self.subTest(source=source):
                value = self.transform(source, "simplify")
                self.assertEqual(value, Number(expected))

    def test_canonical_polynomial_forms(self):
        for source, expected in (
            ("(x+1)^3", "x^3 + 3*x^2 + 3*x + 1"),
            ("(x+y)*(x-y)", "x^2 - y^2"),
            ("(x+y)^2", "x^2 + 2*x*y + y^2"),
            ("x*y+y*x", "2*x*y"),
            ("x/2+x/3", "5/6*x"),
            ("(x^2)^3", "x^6"),
            ("(x+1)^2-x^2-2*x-1", "0"),
            ("x/(y-y+2)", "1/2*x"),
        ):
            with self.subTest(source=source):
                self.assertEqual(format_term(self.transform(source)), expected)

    def test_simplify_preserves_factored_forms(self):
        for source, expected in (
            ("(x+1)^3", "(x + 1)^3"),
            ("(x+1)*(y+1)", "(x + 1)*(y + 1)"),
            ("x*x*x", "x^3"), ("x+0", "x"), ("1*x", "x"),
            ("x-x", "0"), ("--x", "x"), ("0*x", "0"),
        ):
            with self.subTest(source=source):
                self.assertEqual(format_term(self.transform(source, "simplify")), expected)

    def test_elementary_functions(self):
        for source, expected in (
            ("sin(0)", "0"), ("cos(0)", "1"), ("exp(0)", "1"),
            ("log(1)", "0"), ("abs(-3/2)", "3/2"), ("sqrt(4/9)", "2/3"),
            ("sin(x)^2+cos(x)^2", "1"),
            ("2*sin(x)^2+2*cos(x)^2", "2"),
            ("exp(x)+exp(x)", "2*exp(x)"),
        ):
            with self.subTest(source=source):
                self.assertEqual(format_term(self.transform(source, "simplify")), expected)

    def test_arguments_of_symbolic_functions_are_normalized(self):
        left = self.transform("sin((x+1)^2)")
        right = self.transform("sin(x^2+2*x+1)")
        self.assertIs(left, right)
        self.assertEqual(format_term(self.transform("sin((x+1)^2)-sin(x^2+2*x+1)")), "0")
        self.session.execute("h:Function<Real,Real>")
        self.assertEqual(format_term(self.transform("h(x)+h(x)")), "2*h(x)")

    def test_polynomial_normalization_is_distinct_from_trig_simplification(self):
        normal = self.transform("(sin(x)+cos(x))^2")
        self.assertIs(normalize(normal, self.session.factory), normal)
        self.assertEqual(format_term(self.transform("sin(x)^2+cos(x)^2")),
                         "cos(x)^2 + sin(x)^2")
        self.assertEqual(format_term(self.transform("sin(x)^2+cos(x)^2", "simplify")), "1")

    def test_domain_sensitive_expressions_are_preserved_by_simplify(self):
        for source in ("x/x", "0/x", "0*(1/x)", "x^0", "sqrt(x^2)",
                       "log(x)-log(x)", "sin(1/x)^2+cos(1/x)^2", "(1/x)^0"):
            with self.subTest(source=source):
                original = self.session.resolve(source)
                result = self.transform(source, "simplify")
                self.assertEqual(result, original)

    def test_unsupported_polynomial_operations_are_diagnosed(self):
        for source in ("x/x", "1/x", "x^y", "x^-1", "x^0", "sqrt(x)", "log(x)"):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.transform(source)

    def test_undefined_arithmetic_cannot_be_hidden_by_zero_or_cancellation(self):
        for source in ("1/0", "0/0", "0^0", "0^-1", "x/(x-x)", "0*(1/0)",
                       "(1/0)-(1/0)", "(1/0)^0", "log(0)"):
            for operation in ("simplify", "normalize"):
                with self.subTest(source=source, operation=operation), self.assertRaises(DefinitionError):
                    self.transform(source, operation)

    def test_noncommutative_and_unknown_domains_are_not_silently_normalized(self):
        self.session.execute("A:Matrix<Real,2,2>; q:Quaternion; z:Custom; f(t)=t^2")
        for source in ("A+A", "q*q", "0*A", "z+1", "f", "sin(A)"):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.transform(source)
        self.assertEqual(format_term(self.transform("f(x)")), "x^2")

    def test_shadowed_functions_do_not_receive_builtin_rules(self):
        self.session.execute("sin(t)=t; cos(t)=t")
        self.assertEqual(format_term(self.transform("sin(x)^2+cos(x)^2")), "2*x^2")
        self.session.execute("normalize(t)=t+1")
        self.assertEqual(self.session.execute("normalize(2)").output, ("2 + 1",))

    def test_limits_and_rollback(self):
        session = Session(limits=Limits(max_terms=4, max_power=8, max_integer_bits=32))
        session.execute("variable x:Real; variable y:Real; f=x")
        before = session["f"]
        for source in ("(x+y+1)^4", "x^9", "65536^3"):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                session.execute(f"f=2; g=normalize({source})")
            self.assertIs(session["f"], before)
            self.assertNotIn("g", session.environment.definitions)
        with self.assertRaises(NormalizationError):
            normalize(self.session.resolve("(x+y)^3"), limits=Limits(max_steps=5))

    def test_deep_shared_dag_is_computed_once_per_node(self):
        self.session.execute("e=1")
        for _ in range(80):
            self.session.execute("e=e+e")
        self.assertEqual(self.transform("e", "simplify"), Number(Fraction(2**80)))

    def test_python_api_does_not_depend_on_source_or_session(self):
        term = self.session.resolve("2*x+3*x")
        self.assertEqual(format_term(normalize(term)), "5*x")
        self.assertEqual(format_term(simplify(term)), "5*x")

    def test_polynomial_semantics_and_idempotence_on_generated_examples(self):
        rng = random.Random(701)

        def source(depth):
            if depth == 0:
                return rng.choice(["x", "y", "1", "2", "3"])
            lhs, rhs = source(depth-1), source(depth-1)
            return f"({lhs}{rng.choice(['+', '-', '*'])}{rhs})"

        def evaluate(term, values):
            match term:
                case Number(value=value):
                    return value
                case Symbol(name=name):
                    return values[name]
                case Unary(op=op, operand=operand):
                    value = evaluate(operand, values)
                    return value if op == "+" else -value
                case Binary(op=op, left=left, right=right):
                    a, b = evaluate(left, values), evaluate(right, values)
                    return {"+": lambda: a+b, "-": lambda: a-b, "*": lambda: a*b,
                            "/": lambda: a/b, "^": lambda: a**int(b)}[op]()
            raise AssertionError(term)

        for _ in range(40):
            original = self.session.resolve(source(3))
            normal = normalize(original, self.session.factory)
            self.assertEqual(normalize(normal, self.session.factory), normal)
            for x, y in ((-2, 0), (0, 1), (Fraction(1, 3), Fraction(-2, 5))):
                values = {"x": Fraction(x), "y": Fraction(y)}
                self.assertEqual(evaluate(original, values), evaluate(normal, values))


if __name__ == "__main__":
    unittest.main()
