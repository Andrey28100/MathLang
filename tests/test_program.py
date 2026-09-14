import unittest

from mathlang import (
    Assignment, Declaration, ExpressionStatement, FunctionDefinition, Identifier,
    NumberLiteral, ParseError, Program, SourceSpan, TypeRef, format_tree,
    parse_expression, parse_program,
)


class ProgramTests(unittest.TestCase):
    def test_declarations_and_type_annotations(self):
        program = parse_program("""
            const c = 2
            parameter a : Real
            variable x : Real
            unknown y : Real
            A : Matrix<Real, 3, 3>
            const zero : T
        """)
        self.assertEqual(program.statements, (
            Declaration("const", "c", value=NumberLiteral("2")),
            Declaration("parameter", "a", TypeRef("Real")),
            Declaration("variable", "x", TypeRef("Real")),
            Declaration("unknown", "y", TypeRef("Real")),
            Declaration("variable", "A", TypeRef("Matrix", (
                TypeRef("Real"), NumberLiteral("3"), NumberLiteral("3"),
            ))),
            Declaration("const", "zero", TypeRef("T")),
        ))

    def test_function_definitions_and_expression_statements(self):
        program = parse_program("f(x, y) = x^2+y; g = f(2, 3)\ng")
        self.assertEqual(program.statements, (
            FunctionDefinition("f", (Identifier("x"), Identifier("y")),
                               parse_expression("x^2+y")),
            Assignment("g", parse_expression("f(2, 3)")),
            ExpressionStatement(Identifier("g")),
        ))
        self.assertEqual(parse_program("f() = 2").statements[0].parameters, ())

    def test_multiline_expressions_types_and_comments(self):
        program = parse_program("""// start
parameter a : Real; variable x : Real
f =
    2*x + // continuation
    a
g(t) = (
    f^2 +
    sin(t)
)
A : Matrix<
    Vector<Real, 2>,
    3, 3
>
/* first
second */
f
""")
        self.assertEqual(len(program.statements), 6)
        self.assertEqual(program.statements[2], Assignment("f", parse_expression("2*x+a")))
        self.assertEqual(program.statements[-1], ExpressionStatement(Identifier("f")))
        self.assertEqual(parse_program("x /* comment\ncomment */ y").statements,
                         (ExpressionStatement(Identifier("x")),
                          ExpressionStatement(Identifier("y"))))

    def test_newlines_do_not_silently_join_complete_statements(self):
        program = parse_program("f = x\n-x\nf\n(x)")
        self.assertEqual(len(program.statements), 4)
        self.assertEqual(program.statements[0], Assignment("f", Identifier("x")))

    def test_empty_program(self):
        for source in ("", " ; ;\n", "// comment\n/* comment */"):
            self.assertEqual(parse_program(source), Program(()))

    def test_program_tree_and_spans(self):
        program = parse_program("const c = 2\r\nf(x) = x+c")
        self.assertEqual(program.statements[1].span, SourceSpan(13, 23, 2, 1))
        rendered = format_tree(program)
        self.assertTrue(rendered.startswith("Program\n"))
        self.assertIn("Declaration(const c)", rendered)
        self.assertIn("FunctionDefinition(f)", rendered)

    def test_invalid_definitions(self):
        for source in (
            "const", "const c", "parameter a", "unknown x = 2", "variable x : Real = 2",
            "parameter a : Real = 1", "unknown x : Real = 0", "const const = 2",
            "f(x,x) = x", "f(x+1) = x", "2 = x", "x+y = 2", "f()(x) = x",
            "x = 1 y = 2", "x = 1 = 2", "x : Matrix<>", "x : Matrix<Real,>",
            "x : Vector<Real, 1.5>", "x : Real; y =", "f(x) =",
        ):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_program(source)


if __name__ == "__main__":
    unittest.main()
