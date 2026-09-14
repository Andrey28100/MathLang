import unittest
from dataclasses import FrozenInstanceError
from fractions import Fraction

from mathlang import (
    BinaryPattern, DefinitionError, Limits, LiteralPattern, Matcher, Number, RewriteError,
    RewriteRule, Rewriter, RuleSet, Session, Symbol, SymbolKind, TermFactory, Type, Wildcard,
    format_term, rewrite,
)


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.factory = TermFactory()
        self.x = Wildcard("x")
        self.a = Symbol("a", SymbolKind.VARIABLE, Type("Real"))

    def test_wildcards_capture_whole_expressions(self):
        pattern = BinaryPattern("+", self.x, LiteralPattern(self.factory.number(0)))
        nested = self.factory.binary("^", self.a, self.factory.number(2))
        expression = self.factory.binary("+", nested, self.factory.number(0))
        self.assertEqual(Matcher().match(pattern, expression), {"x": nested})

    def test_repeated_wildcards_require_equal_structures(self):
        pattern = BinaryPattern("+", self.x, self.x)
        same = self.factory.binary("+", self.a, self.a)
        different = self.factory.binary("+", self.a, self.factory.number(1))
        self.assertEqual(Matcher().match(pattern, same), {"x": self.a})
        self.assertIsNone(Matcher().match(pattern, different))
        shadow = Symbol("a", SymbolKind.VARIABLE, Type("Real"))
        self.assertIsNone(Matcher().match(pattern, self.factory.binary("+", self.a, shadow)))

    def test_distinct_factories_and_deep_dags_compare_structurally(self):
        other = TermFactory()
        a, b = self.a, self.a
        for _ in range(80):
            a = self.factory.binary("*", a, a)
            b = other.binary("*", b, b)
        pattern = BinaryPattern("+", self.x, self.x)
        matched = Matcher().match(pattern, self.factory.binary("+", a, b))
        self.assertIsNotNone(matched)

    def test_rules_are_immutable_and_validate_free_placeholders(self):
        with self.assertRaises(RewriteError):
            RewriteRule(self.x, Wildcard("missing"))
        rule = RewriteRule(self.x, self.x)
        with self.assertRaises(FrozenInstanceError):
            rule.replacement = LiteralPattern(Number(Fraction(0)))
        group = RuleSet("identity", (rule,))
        self.assertEqual(group.termination, "unknown")
        self.assertEqual(group.confluence, "unknown")

    def test_matcher_obeys_its_budget(self):
        pattern = BinaryPattern("+", self.x, self.x)
        with self.assertRaises(RewriteError):
            Matcher(Limits(max_steps=1)).match(pattern, self.factory.binary("+", self.a, self.a))


class RewriteSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute("variable a:Real; variable b:Real; variable x:Real")

    def test_named_rule_pipeline_and_original_memory(self):
        self.session.execute("rule double_angle {sin(2*x) -> 2*sin(x)*cos(x)}; f=sin(2*a)")
        self.assertEqual(self.session.execute("rewrite f using double_angle").output,
                         ("2*sin(a)*cos(a)",))
        self.assertEqual(self.session.execute("f |> rewrite(double_angle)").output,
                         ("2*sin(a)*cos(a)",))
        self.assertEqual(format_term(self.session["f"]), "sin(2*a)")
        self.assertEqual(self.session.execute("sin(a*2) |> rewrite(double_angle)").output,
                         ("sin(a*2)",))
        self.assertEqual(self.session.execute("sin(a*2) |> normalize |> rewrite(double_angle)").output,
                         ("2*sin(a)*cos(a)",))

    def test_anonymous_rules_and_declaration_order(self):
        self.session.execute("rule {x+0->x}; rule named {x+0->0}; rule {x*1->x}")
        self.assertEqual(self.session.execute("rewrite(a+0); rewrite(a*1)").output, ("a", "a"))
        self.assertEqual(self.session.execute("rewrite a+0 using named").output, ("0",))
        self.assertEqual(len(self.session.environment.visible_rules().rules), 3)

    def test_traversal_strategies_and_fixed_point(self):
        self.session.execute("rule drop {x+0->x}")
        for modifier, expected in (("once", "a + 0"), ("top_down", "a + 0"),
                                   ("bottom_up", "a"), ("top_down recursively", "a")):
            with self.subTest(modifier=modifier):
                self.assertEqual(self.session.execute(f"rewrite (a+0)+0 using drop {modifier}").output,
                                 (expected,))
        self.assertEqual(self.session.execute("rewrite((a+0)+0,drop,strategy=recursively)").output, ("a",))

    def test_once_changes_exactly_one_shared_occurrence(self):
        self.session.execute("rule drop{x+0->x}; f=(a+0)*(a+0)")
        original = self.session["f"]
        self.assertIs(original.left, original.right)
        result = self.session.resolve("rewrite(f,drop,strategy=once)")
        self.assertIs(result.left, self.session["a"])
        self.assertIs(result.right, original.right)
        all_nodes = self.session.kernel.rewriter.apply(original, self.session["drop"])
        self.assertIs(all_nodes.term.left, all_nodes.term.right)
        self.assertEqual(all_nodes.applications, 1)

    def test_repeated_wildcards_and_local_pattern_scope(self):
        self.session.execute("rule collect{x+x->2*x}")
        self.assertEqual(self.session.execute("rewrite(a+a,collect); rewrite(a+b,collect)").output,
                         ("2*a", "a + b"))
        self.assertEqual(self.session["x"].kind, SymbolKind.VARIABLE)
        self.session.execute("rule fresh{temporary+0->temporary}")
        self.assertNotIn("temporary", self.session.environment.definitions)

    def test_constants_and_expression_definitions_are_literal_snapshots(self):
        self.session.execute("const two=2; literal=a+1; rule r{x+two->x; literal->b}; literal=a+2")
        self.assertEqual(self.session.execute("rewrite(a+2,r); rewrite(a+1,r); rewrite(a+3,r)").output,
                         ("a", "b", "a + 3"))
        self.session.execute("rule introduce{q+0->b}")
        self.assertIs(self.session.resolve("rewrite(a+0,introduce)"), self.session["b"])

    def test_known_and_wildcard_function_heads(self):
        self.session.execute("h:Function<Real,Real>; rule h_rule{h(x)->x}; rule any_call{fun(t)->t}")
        self.assertEqual(self.session.execute("rewrite(h(a),h_rule); rewrite(sin(a),h_rule)").output,
                         ("a", "sin(a)"))
        self.assertEqual(self.session.execute("rewrite(sin(a),any_call)").output, ("a",))

    def test_conditions_require_a_proven_numeric_comparison(self):
        self.session.execute("rule sqrt_square{sqrt(t^2)->t when t>=0}")
        for source, expected in (("sqrt(3^2)", "3"), ("sqrt((-3)^2)", "sqrt((-3)^2)"),
                                 ("sqrt(a^2)", "sqrt(a^2)"), ("sqrt((1/2)^2)", "1/2")):
            with self.subTest(source=source):
                self.assertEqual(self.session.execute(f"rewrite {source} using sqrt_square").output,
                                 (expected,))
        self.session.execute("rule guarded{x/x->1 when x!=0}")
        self.assertEqual(self.session.execute("rewrite 2/2 using guarded").output, ("1",))
        self.assertEqual(self.session.execute("rewrite 0/0 using guarded").output, ("0/0",))
        self.assertEqual(self.session.execute("rewrite a/a using guarded").output, ("a/a",))

    def test_all_numeric_comparisons_and_unknown_conditions(self):
        for index, (op, rhs) in enumerate((("==", 2), ("!=", 3), ("<", 3), ("<=", 2), (">", 1), (">=", 2))):
            name = f"r{index}"
            self.session.execute(f"rule {name}{{sin(t)->t when t{op}{rhs}}}")
            self.assertEqual(self.session.execute(f"rewrite sin(2) using {name}").output, ("2",))
        self.session.execute("rule undefined{sin(t)->0 when t/0>1}")
        self.assertEqual(self.session.execute("rewrite sin(2) using undefined").output, ("sin(2)",))

    def test_rules_do_not_change_scalar_normalization_implicitly(self):
        self.session.execute("rule replace{x+0->9}")
        self.assertEqual(self.session.execute("normalize(a+0); simplify(a+0); rewrite(a+0)").output,
                         ("a", "a", "9"))
        self.session.execute("A:Matrix<Real,2,2>; rule drop{x+x->x}")
        self.assertIs(self.session.resolve("rewrite(A+A,drop)"), self.session["A"])

    def test_function_bodies_are_opaque_to_traversal(self):
        self.session.execute("rule drop{x+0->x}; f(t)=t+0")
        self.assertIs(self.session.resolve("rewrite(f,drop)"), self.session["f"])
        self.assertEqual(self.session.execute("rewrite(f(a),drop)").output, ("a",))

    def test_rule_arguments_aliases_and_captured_defaults(self):
        self.session.execute("rule drop{x+0->x}; saved=drop; clean(t)=rewrite(t); apply(t,r)=rewrite(t,r)")
        self.session.execute("rule one{x*1->x}")
        self.assertEqual(self.session.execute("clean(a*1); rewrite(a*1); apply(a+0,saved)").output,
                         ("a*1", "a", "a"))
        self.session.execute("R=rewrite; apply_transform(h,t,r)=h(t,r)")
        self.assertEqual(self.session.execute("apply_transform(R,a+0,drop)").output, ("a",))
        with self.assertRaises(DefinitionError):
            self.session.execute("apply(a,2)")

    def test_scopes_hide_rules_without_mutating_parent(self):
        self.session.execute("rule r{x+0->x}")
        child = Session(self.session.environment.child())
        child.execute("rule r{x+0->0}")
        self.assertEqual(child.execute("rewrite(a+0)").output, ("0",))
        self.assertEqual(self.session.execute("rewrite(a+0)").output, ("a",))

    def test_errors_roll_back_rules_and_expressions(self):
        self.session.execute("f=a")
        before = self.session.environment.local_rule_sets
        for source in ("rule temp{x+0->x}; f=2; missing", "rule {x*1->x}; bad=1/0 |> normalize",
                       "rule temp{x+0->x}; rule temp{x*1->x}"):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.session.execute(source)
            self.assertEqual(self.session.environment.local_rule_sets, before)
            self.assertNotIn("temp", self.session.environment.definitions)
            self.assertIs(self.session["f"], self.session["a"])

    def test_invalid_rules_and_rewrite_arguments(self):
        for source in ("rule r{x+0->missing}", "rule r{x+0->x when missing>0}",
                       "rule r{x+0->simplify(x)}", "rule r{normalize(x)->x}",
                       "rewrite()", "rewrite(a,2)", "rewrite(a,strategy=bad)",
                       "rewrite(a,other=once)", "rewrite a using missing"):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.session.execute(source)
        self.session.execute("rule r{x+0->x}")
        with self.assertRaises(DefinitionError):
            self.session.execute("r=2")

    def test_cycle_detection_and_noop_rules(self):
        self.session.execute("rule cycle{0->1; 1->0}; rule noop{x->x; x+0->x}")
        with self.assertRaisesRegex(DefinitionError, "cycle detected"):
            self.session.execute("f=2; rewrite 0 using cycle recursively")
        self.assertNotIn("f", self.session.environment.definitions)
        self.assertEqual(self.session.execute("rewrite a+0 using noop recursively").output, ("a",))

    def test_growth_limits_abort_without_partial_results(self):
        small = Session(limits=Limits(max_rewrites=5, max_passes=5, max_nodes=20))
        small.execute("variable a:Real; rule grow{x->x+1}")
        for suffix in ("recursively", "top_down"):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(DefinitionError, "limit exceeded"):
                small.execute(f"result=2; rewrite a using grow {suffix}")
            self.assertNotIn("result", small.environment.definitions)

    def test_python_api_and_empty_rules(self):
        factory = self.session.factory
        x = Wildcard("x")
        rule = RewriteRule(BinaryPattern("+", x, LiteralPattern(factory.number(0))), x)
        original = self.session.resolve("a+0")
        result = Rewriter(factory).apply(original, (rule,))
        self.assertIs(result.term, self.session["a"])
        self.assertEqual((result.applications, result.passes), (1, 1))
        self.assertIs(rewrite(original, (), factory=factory), original)
        self.assertIs(self.session.resolve("rewrite(a)"), self.session["a"])
        with self.assertRaises(RewriteError):
            rewrite(original, (rule,), strategy="invalid")
        with self.assertRaises(RewriteError):
            rewrite(original, (rule,), strategy="once", repeat=True)


if __name__ == "__main__":
    unittest.main()
