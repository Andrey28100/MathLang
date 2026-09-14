from fractions import Fraction
import unittest

from mathlang import AlgebraNormalizer, Limits, Session
from mathlang.algebra import _AlgebraComputation
from mathlang.analytic_lift import function_domain, lift_function, supports_function
from mathlang.logic import AssumptionSet, Context, PredicateQuery
from mathlang.normalization import NormalizationError
from mathlang.terms import TruthValue, Type


class AnalyticLiftTests(unittest.TestCase):
    def computation(self, relation="e^2=0", *, domain="Real", limits=None, declaration=None):
        self.session = Session()
        self.session.execute(declaration or
                             f"algebra A over {domain} {{ generator e; relation {relation}; derive basis }}")
        self.session.execute("use A; parameter a:Real; parameter b:Real; parameter x:Real")
        self.f = self.session.factory
        self.algebra = self.session["A"]
        self.work = _AlgebraComputation(AlgebraNormalizer(self.algebra, self.f, limits))
        self.work.query = None
        return self.work

    def term(self, text):
        return self.session.resolve(text)

    def assert_expression(self, coordinates, expected):
        normalizer = AlgebraNormalizer(self.algebra, self.f, query=self.work.query)
        self.assertEqual(normalizer.normalize(self.work.render(coordinates)),
                         normalizer.normalize(self.term(expected)))

    def test_dual_formula_uses_scalar_derivatives_for_symbolic_coefficients(self):
        work = self.computation()
        coordinates = {(): self.term("a"), (0,): self.term("b")}
        for name, expected in (
            ("exp", "exp(a)+b*exp(a)*e"),
            ("sin", "sin(a)+b*cos(a)*e"),
            ("cos", "cos(a)-b*sin(a)*e"),
        ):
            with self.subTest(name=name):
                self.assert_expression(lift_function(name, coordinates, work), expected)

    def test_nilpotent_order_and_mixed_powers_are_not_hardcoded(self):
        work = self.computation("e^5=0")
        coordinates = {(0,): self.f.number(1), (0, 0): self.f.number(1)}
        self.assert_expression(lift_function("exp", coordinates, work),
                               "1+e+3/2*e^2+7/6*e^3+25/24*e^4")
        self.assert_expression(lift_function("cos", {(0,): self.f.number(1)}, work),
                               "1-e^2/2+e^4/24")

    def test_nilpotent_part_can_contain_noncommuting_generators(self):
        work = self.computation(declaration="""algebra A over Real {
            generators p,q; relations {p^2=0,q^2=0,q*p=0}; derive basis
        }""")
        self.assert_expression(lift_function("exp", {(0,): self.f.number(1),
                                                     (1,): self.f.number(1)}, work),
                               "1+p+q+p*q/2")

    def test_regular_log_and_sqrt_at_positive_numeric_centers(self):
        work = self.computation("e^4=0")
        self.assert_expression(lift_function("log", {(): self.f.number(1),
                                                     (0,): self.f.number(1)}, work),
                               "e-e^2/2+e^3/3")
        self.assert_expression(lift_function("sqrt", {(): self.f.number(4),
                                                      (0,): self.f.number(1)}, work),
                               "2+e/4-e^2/64+e^3/512")

    def test_symbolic_regular_center_requires_and_uses_an_assumption(self):
        work = self.computation()
        a, b = self.term("a"), self.term("b")
        coordinates = {(): a, (0,): b}
        for name in ("log", "sqrt"):
            with self.subTest(name=name), self.assertRaisesRegex(NormalizationError, "positive scalar center"):
                lift_function(name, coordinates, work)
            self.assertEqual(function_domain(name, coordinates, work),
                             self.f.comparison(">", a, self.f.number(0)))
        query = PredicateQuery(self.f, context=Context(AssumptionSet(
            (self.f.comparison(">", a, self.f.number(0)),))))
        work.query = query.query
        work.scalar.query = query.query
        self.assert_expression(lift_function("log", coordinates, work), "log(a)+(b/a)*e")
        self.assert_expression(lift_function("sqrt", coordinates, work), "sqrt(a)+(b/(2*sqrt(a)))*e")

    def test_euler_identity_follows_from_a_relation_with_an_arbitrary_name(self):
        work = self.computation("e^2=-1")
        coordinates = {(0,): self.term("x")}
        self.assert_expression(lift_function("exp", coordinates, work), "cos(x)+sin(x)*e")
        self.assert_expression(lift_function("exp", {(): self.term("a"), **coordinates}, work),
                               "exp(a)*cos(x)+exp(a)*sin(x)*e")

    def test_quadratic_direction_uses_its_checked_scale_and_sign(self):
        work = self.computation("e^2=-4")
        self.assert_expression(lift_function("exp", {(0,): self.term("x")}, work),
                               "cos(2*x)+sin(2*x)/2*e")
        work = self.computation("e^2=4")
        self.assert_expression(lift_function("exp", {(0,): self.term("x")}, work),
                               "(exp(2*x)+exp(-2*x))/2+(exp(2*x)-exp(-2*x))/4*e")
        self.assert_expression(lift_function("sin", {(0,): self.term("x")}, work),
                               "sin(2*x)/2*e")
        self.assert_expression(lift_function("cos", {(0,): self.term("x")}, work), "cos(2*x)")

    def test_functions_reject_unproved_nilpotence_instead_of_truncating(self):
        work = self.computation("e^3=2")
        with self.assertRaisesRegex(NormalizationError, "No exact algebra reduction"):
            lift_function("exp", {(0,): self.f.number(1)}, work)
        self.assertEqual(function_domain("exp", {(0,): self.f.number(1)}, work),
                         self.f.truth(TruthValue.TRUE))
        self.assertIsNone(function_domain("log", {(0,): self.f.number(1)}, work))

    def test_nilpotence_certificate_respects_the_calculus_order_limit(self):
        work = self.computation("e^4=0", limits=Limits(max_calculus_order=3))
        with self.assertRaisesRegex(NormalizationError, "within order 3"):
            lift_function("exp", {(0,): self.f.number(1)}, work)
        work = self.computation("e^4=0", limits=Limits(max_calculus_order=4))
        self.assertEqual(lift_function("exp", {(0,): self.f.number(1)}, work)[(0, 0, 0)],
                         self.f.number(Fraction(1, 6)))

    def test_signature_keeps_scalar_field_and_branches_explicit(self):
        for name in ("exp", "sin", "cos", "log", "sqrt"):
            self.assertTrue(supports_function(name, Type("Real")))
            self.assertFalse(supports_function(name, Type("Rational")))
        self.assertTrue(supports_function("exp", Type("Complex")))
        self.assertFalse(supports_function("log", Type("Complex")))
        self.assertFalse(supports_function("abs", Type("Real")))
        work = self.computation(domain="Rational")
        with self.assertRaisesRegex(NormalizationError, "No analytic algebra signature"):
            lift_function("exp", {(0,): self.f.number(1)}, work)


if __name__ == "__main__":
    unittest.main()
