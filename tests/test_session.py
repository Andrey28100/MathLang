import gc
import unittest
import weakref
from dataclasses import FrozenInstanceError
from fractions import Fraction

from mathlang import (
    Binary, Definition, DefinitionError, Environment, Function, Number, ParseError,
    RenderError, Session, SourceSpan, Symbol, SymbolKind, TermFactory, Type,
    format_definition, format_term,
)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()

    def test_memory_persists_between_inputs(self):
        self.assertEqual(self.session.execute("const c = 2; variable x : Real").output, ())
        self.session.execute("f = c*x + 3*x")
        self.assertEqual(self.session.execute("f").output, ("2*x + 3*x",))
        self.assertIs(self.session.resolve("f"), self.session["f"])
        self.assertEqual(self.session.execute("print(f, c)").output, ("2*x + 3*x 2",))
        self.assertEqual(self.session.execute("print()").output, ("",))

    def test_symbol_roles_and_type_metadata(self):
        self.session.execute("""
            parameter a : Real
            variable x : Real
            unknown y : Real
            A : Matrix<Real, 3, 3>
            const zero : T
        """)
        for name, kind in (("a", SymbolKind.PARAMETER), ("x", SymbolKind.VARIABLE),
                           ("y", SymbolKind.UNKNOWN), ("zero", SymbolKind.CONSTANT)):
            self.assertIsInstance(self.session[name], Symbol)
            self.assertEqual(self.session[name].kind, kind)
        self.assertEqual(self.session["A"].annotation, Type("Matrix", (Type("Real"), 3, 3)))
        self.assertEqual(str(self.session["A"].annotation), "Matrix<Real, 3, 3>")

    def test_unknown_names_are_not_implicitly_created(self):
        source = "variable x : Real\nf = x + missing"
        with self.assertRaises(DefinitionError) as caught:
            self.session.execute(source)
        self.assertEqual(caught.exception.span, SourceSpan(26, 33, 2, 9))
        self.assertIn("Undefined name 'missing'", str(caught.exception))
        self.assertEqual(dict(self.session.environment.definitions), {})

    def test_redefinition_captures_current_expression(self):
        self.session.execute("variable x : Real; f = x+1; g = f^2")
        original = self.session["f"]
        self.session.execute("f = f+2")
        self.assertIs(self.session["g"].left, original)
        self.assertEqual(self.session.execute("f; g").output, ("x + 1 + 2", "(x + 1)^2"))

    def test_declarations_cannot_be_redefined(self):
        self.session.execute("const c=2; parameter a:Real; variable x:Real; unknown y:Real")
        for name in ("c", "a", "x", "y"):
            before = self.session[name]
            for source in (f"{name}=3", f"{name}(t)=t", f"const {name}=4"):
                with self.subTest(source=source), self.assertRaises(DefinitionError):
                    self.session.execute(source)
                self.assertIs(self.session[name], before)

    def test_failed_program_rolls_back_and_produces_no_result(self):
        self.session.execute("a=1")
        before = dict(self.session.environment.definitions)
        for source in ("a=2; print(a); b=missing", "a=3; const c=1; const c=2",
                       "a=4; f(t)=t; f(1,2)", "a=5; b=("):
            with self.subTest(source=source), self.assertRaises((DefinitionError, ParseError)):
                self.session.execute(source)
            self.assertEqual(dict(self.session.environment.definitions), before)

    def test_first_definition_cannot_refer_to_itself_or_future_names(self):
        for source in ("f=f+1", "f(t)=f(t)", "f=g; g=2"):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.session.execute(source)

    def test_function_call_substitutes_without_evaluating_arithmetic(self):
        self.session.execute("parameter a:Real; variable x:Real; f(x)=exp(a*x)*sin(x)")
        self.assertEqual(self.session.execute("f(2)").output, ("exp(a*2)*sin(2)",))
        self.assertIsInstance(self.session["f"], Function)
        self.assertIsNot(self.session["f"].parameters[0], self.session["x"])
        self.assertEqual(self.session["f"].parameters[0].annotation, Type("Real"))
        self.assertEqual(self.session["x"].kind, SymbolKind.VARIABLE)

    def test_parameters_are_local_and_substitution_is_simultaneous(self):
        self.session.execute("variable x:Real; variable y:Real; swap(x,y)=x-y; f(t)=t+x")
        self.assertEqual(self.session.execute("swap(y,x); f(y)").output, ("y - x", "y + x"))
        self.assertNotIn("t", self.session.environment.definitions)
        self.assertIs(self.session["f"].body.right, self.session["x"])

    def test_functions_capture_definitions_and_can_be_passed_as_values(self):
        self.session.execute("a=2; f(t)=a*t; old=f; a=3; f(t)=t^2")
        self.assertEqual(self.session.execute("old(5); f(5)").output, ("2*5", "5^2"))
        self.session.execute("apply(h,t)=h(t); identity(h)=h; empty()=2")
        self.assertEqual(self.session.execute("apply(f,3); identity(f)(4); empty()").output,
                         ("3^2", "4^2", "2"))

    def test_invalid_calls_and_arity_have_source_diagnostics(self):
        self.session.execute("f(t)=t; variable x:Real; h:Function<Real,Real>")
        for source in ("f()", "f(1,2)", "2(3)", "x(3)", "h()", "1+print(2)"):
            with self.subTest(source=source), self.assertRaises(DefinitionError) as caught:
                self.session.execute(source)
            self.assertIn("line 1", str(caught.exception))
        self.assertEqual(self.session.execute("h(2)").output, ("h(2)",))

    def test_independent_sessions_and_child_scopes(self):
        self.session.execute("variable x:Real; f=x+1")
        other = Session()
        other.execute("variable x:Real")
        self.assertNotEqual(self.session["x"], other["x"])
        local = Session(self.session.environment.child())
        local.execute("variable x:Real; g=x+2")
        self.assertNotEqual(local["x"], self.session["x"])
        self.assertIs(local["f"], self.session["f"])
        self.assertNotIn("g", self.session.environment.definitions)

    def test_builtin_names_can_be_shadowed_in_user_scope(self):
        self.session.execute("sin(t)=t^2; print(t)=t+1")
        self.assertEqual(self.session.execute("sin(2); print(3)").output, ("2^2", "3 + 1"))

    def test_exact_numbers_and_no_automatic_simplification(self):
        self.session.execute("a=0.125; b=1/2; c=1/0")
        self.assertEqual(self.session["a"], Number(Fraction(1, 8)))
        self.assertIsInstance(self.session["b"], Binary)
        self.assertEqual(self.session.execute("a; b; c").output, ("1/8", "1/2", "1/0"))

    def test_annotations_are_preserved_and_known_type_errors_are_rejected(self):
        self.session.execute("const c:Real = 2; A:Matrix<Real,3,3>")
        self.assertEqual(self.session.environment["c"].symbol.annotation, Type("Real"))
        self.assertEqual(format_definition(self.session.environment["c"]),
                         "const c : Real = 2")
        for source in ('const invalid:CustomType=2', 'f=A+1'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.session.execute(source)

    def test_unicode_definitions(self):
        self.session.execute("parameter α:Real; variable β:Real; ψ=α*β")
        self.assertEqual(self.session.execute("ψ").output, ("α*β",))

    def test_resolution_depth_error_leaves_memory_intact(self):
        self.session.execute("variable x:Real")
        with self.assertRaises(DefinitionError):
            self.session.execute("f=" + "+".join(["x"] * 1500))
        self.assertNotIn("f", self.session.environment.definitions)


class TermTests(unittest.TestCase):
    def test_hash_consing_across_inputs_and_inside_a_dag(self):
        session = Session()
        session.execute("variable x:Real; e=(x+1)^2 + sin(x+1)")
        shared = session["e"].left.left
        self.assertIs(shared, session["e"].right.arguments[0])
        self.assertIs(session.resolve("x + 1"), shared)
        session.execute("f=x+1")
        self.assertIs(session["f"], shared)
        self.assertIs(session.resolve("0.50"), session.resolve("0.5"))

    def test_deep_sharing_does_not_require_exponential_hashing(self):
        session = Session()
        session.execute("e=1")
        for _ in range(80):
            session.execute("e=e+e")
        self.assertIs(session["e"].left, session["e"].right)
        self.assertIsInstance(hash(session["e"]), int)

    def test_immutability_and_unused_term_collection(self):
        factory = TermFactory()
        expression = factory.binary("+", factory.number(1), factory.number(2))
        with self.assertRaises(FrozenInstanceError):
            expression.left = factory.number(3)
        reference = weakref.ref(expression)
        del expression
        gc.collect()
        self.assertIsNone(reference())

    def test_substitution_avoids_capture(self):
        factory = TermFactory()
        x = Symbol("x", SymbolKind.VARIABLE)
        y = Symbol("y", SymbolKind.VARIABLE)
        function = factory.function((x,), factory.binary("+", x, y))
        substituted = factory.substitute(function, {y: x})
        result = factory.call(substituted, (factory.number(2),))
        self.assertEqual(result, factory.binary("+", factory.number(2), x))
        self.assertIsNot(substituted.parameters[0], x)

    def test_renderer_preserves_grouping(self):
        session = Session()
        session.execute("variable a:Real; variable b:Real; variable c:Real")
        for source in ("a+(b+c)", "a-(b-c)", "a/(b/c)", "a*(b*c)", "(a^b)^c",
                       "a^(b^c)", "(-a)^b", "a^-b", "-(a+b)", "a^(b*c)"):
            with self.subTest(source=source):
                term = session.resolve(source)
                self.assertIs(session.resolve(format_term(term)), term)
        self.assertEqual(format_term(session.resolve("0.125^2")), "(1/8)^2")

    def test_renderer_handles_deep_memory_and_limits_expanded_output(self):
        factory = TermFactory()
        one = factory.number(1)
        term = one
        for _ in range(1500):
            term = factory.binary("+", term, one)
        self.assertEqual(format_term(term), " + ".join(["1"] * 1501))
        session = Session()
        session.execute("e=1")
        for _ in range(80):
            session.execute("e=e+e")
        with self.assertRaises(RenderError):
            format_term(session["e"])
        with self.assertRaisesRegex(DefinitionError, "too large to display"):
            session.execute("f=1; print(e)")
        self.assertNotIn("f", session.environment.definitions)

    def test_rendering_function_constant_keeps_its_role(self):
        session = Session()
        session.execute("f(t)=t^2; const g=f")
        self.assertEqual(format_definition(session.environment["g"]), "const g = (t) => t^2")

    def test_environment_does_not_expose_mutable_definitions(self):
        environment = Environment()
        symbol = Symbol("x", SymbolKind.VARIABLE)
        environment.define(Definition(symbol))
        with self.assertRaises(TypeError):
            environment.definitions["x"] = Definition(symbol)
        with self.assertRaises(ValueError):
            environment.define(Definition(symbol), replace=True)


if __name__ == "__main__":
    unittest.main()
