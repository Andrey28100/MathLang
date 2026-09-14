import unittest

from mathlang import (
    CallExpr, DefinitionError, Identifier, KeywordArgument, NumberLiteral, ParseError,
    PipelineExpr, Session, SubstitutionExpr, format_term, format_tree, parse_expression,
    parse_program,
)


class TransformationSyntaxTests(unittest.TestCase):
    def test_named_arguments_have_their_own_ast_nodes(self):
        expression = parse_expression("substitute(f, x=2)")
        self.assertEqual(expression, CallExpr(Identifier("substitute"), (Identifier("f"),),
                                             (KeywordArgument("x", NumberLiteral("2")),)))
        self.assertIn("KeywordArgument(x)", format_tree(expression))

    def test_pipeline_precedence_and_associativity(self):
        expression = parse_expression("x+1 |> substitute(x=2) |> normalize")
        self.assertIsInstance(expression, PipelineExpr)
        self.assertEqual(expression.target, Identifier("normalize"))
        self.assertIsInstance(expression.value, PipelineExpr)
        self.assertEqual(expression.value.value, parse_expression("x+1"))

    def test_where_ast_and_block_inside_function_call(self):
        for source in ("x^2 where x=2", "x^2 where {x=2}"):
            expression = parse_expression(source)
            self.assertIsInstance(expression, SubstitutionExpr)
            self.assertEqual(expression.replacements, (KeywordArgument("x", NumberLiteral("2")),))
        program = parse_program("""variable x:Real
variable y:Real
print((x+y) where {
 x=2
 y=3
})
""")
        self.assertEqual(len(program.statements), 3)

    def test_multiline_pipeline_is_one_expression(self):
        program = parse_program("""f = x + 1
    |> substitute(x=2)
    |> normalize
g = 3
""")
        self.assertEqual(len(program.statements), 2)
        self.assertIsInstance(program.statements[0].value, PipelineExpr)

    def test_invalid_transformation_syntax(self):
        for source in ("f(x=2, 3)", "f(x=2,x=3)", "x |> 2", "x | > f", "x |>",
                       "x where {}", "x where {x=2; x=3}", "x where {x=2 y=3}",
                       "x where {x=2", "x where x=", "f(x=)"):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_expression(source)


class TransformationSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute("variable x:Real; variable y:Real; parameter a:Real; f=x^2+a")

    def test_substitution_syntax_variants(self):
        for source in ("substitute(f,x=2,a=3)", "f where { x=2; a=3 }",
                       "f |> substitute(x=2,a=3)"):
            with self.subTest(source=source):
                result = self.session.resolve(source)
                self.assertEqual(format_term(result), "2^2 + 3")
                self.assertEqual(self.session.execute(f"({source}) |> normalize").output, ("7",))
        self.assertEqual(self.session.execute("x^2 where x=3 |> normalize").output, ("9",))
        self.assertEqual(format_term(self.session["f"]), "x^2 + a")

    def test_replacements_are_simultaneous_and_do_not_change_memory(self):
        x, y = self.session["x"], self.session["y"]
        result = self.session.resolve("substitute(x-y,x=y,y=x)")
        self.assertIs(result.left, y)
        self.assertIs(result.right, x)
        self.assertIs(self.session["x"], x)
        self.assertIs(self.session["y"], y)

    def test_transformations_work_inside_functions_and_through_aliases(self):
        self.session.execute("clean(t)=normalize(t^2+2*t+1); N=normalize; S=substitute; apply(h,t)=h(t)")
        self.assertEqual(self.session.execute("clean(2); N(2+3); apply(N,x+x)").output,
                         ("9", "5", "2*x"))
        self.assertEqual(self.session.execute("S(f,x=2,a=3) |> N").output, ("7",))

    def test_delayed_substitution_in_function_body(self):
        self.session.execute("replace_x(t)=substitute(t,x=2); replace_local(t)=t^2 where t=3")
        self.assertEqual(self.session.execute("replace_x(x^2); replace_local(100)").output,
                         ("2^2", "3^2"))
        self.assertEqual(format_term(self.session["replace_x"]), "(t) => substitute(t, x = 2)")

    def test_lexical_targets_and_capture_avoidance(self):
        self.session.execute("h(x)=x+a; k=substitute(h,a=x)")
        self.assertEqual(self.session.execute("k(2)").output, ("2 + x",))
        self.assertEqual(self.session.execute("substitute(h,x=2)").values[0].body,
                         self.session["h"].body)

    def test_pipeline_to_user_function_inserts_first_argument(self):
        self.session.execute("add(t,s)=t+s")
        self.assertEqual(self.session.execute("2 |> add(3) |> normalize").output, ("5",))

    def test_invalid_arguments_and_targets(self):
        for source in ("normalize()", "simplify(x,y)", "substitute(f)", "substitute(f,z=2)",
                       "substitute(f,f=2)", "sin(x=2)", "print(x=2)"):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.session.execute(source)
        self.session.execute("alias=x")
        with self.assertRaises(DefinitionError):
            self.session.execute("substitute(f,x=2,alias=3)")

    def test_failed_transformation_rolls_back_program(self):
        original = self.session["f"]
        with self.assertRaises(DefinitionError) as caught:
            self.session.execute("f=2; print(f); g=normalize(1/0)")
        self.assertIs(self.session["f"], original)
        self.assertIn("Division by zero", str(caught.exception))
        self.assertNotIn("g", self.session.environment.definitions)


if __name__ == "__main__":
    unittest.main()
