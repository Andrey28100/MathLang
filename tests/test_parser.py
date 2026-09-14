import unittest
from dataclasses import FrozenInstanceError

from mathlang import (
    BinaryExpr, CallExpr, Identifier, NumberLiteral, ParseError, SourceSpan,
    UnaryExpr, format_tree, parse_expression,
)
from mathlang.lexer import TokenKind, tokenize


class ExpressionTests(unittest.TestCase):
    def test_sum_of_products_stays_syntax(self):
        self.assertEqual(
            parse_expression("2*x + 3*x"),
            BinaryExpr("+", BinaryExpr("*", NumberLiteral("2"), Identifier("x")),
                       BinaryExpr("*", NumberLiteral("3"), Identifier("x"))),
        )

    def test_precedence_and_associativity(self):
        a, b, c = Identifier("a"), Identifier("b"), Identifier("c")
        cases = [
            ("a+b*c", BinaryExpr("+", a, BinaryExpr("*", b, c))),
            ("(a+b)*c", BinaryExpr("*", BinaryExpr("+", a, b), c)),
            ("a-b-c", BinaryExpr("-", BinaryExpr("-", a, b), c)),
            ("a/b*c", BinaryExpr("*", BinaryExpr("/", a, b), c)),
            ("a/b/c", BinaryExpr("/", BinaryExpr("/", a, b), c)),
            ("a^b^c", BinaryExpr("^", a, BinaryExpr("^", b, c))),
            ("-a^b", UnaryExpr("-", BinaryExpr("^", a, b))),
            ("(-a)^b", BinaryExpr("^", UnaryExpr("-", a), b)),
            ("a^-b^c", BinaryExpr("^", a, UnaryExpr("-", BinaryExpr("^", b, c)))),
            ("a*-b", BinaryExpr("*", a, UnaryExpr("-", b))),
            ("--a", UnaryExpr("-", UnaryExpr("-", a))),
            ("+a", UnaryExpr("+", a)),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(parse_expression(source), expected)

    def test_literals_preserve_exact_spelling(self):
        for text in ("0", "42", "0003", "0.1", "12.3400", "9" * 5000):
            with self.subTest(length=len(text), text=text[:20]):
                self.assertEqual(parse_expression(text), NumberLiteral(text))

    def test_rational_is_syntactic_division(self):
        self.assertEqual(parse_expression("1/2"),
                         BinaryExpr("/", NumberLiteral("1"), NumberLiteral("2")))
        self.assertIsInstance(parse_expression("1/0"), BinaryExpr)

    def test_unicode_identifiers(self):
        for name in ("x", "_value2", "quaternion_norm", "α", "Δ", "имя", "e\u0301"):
            with self.subTest(name=name):
                self.assertEqual(parse_expression(name), Identifier(name))

    def test_nested_function_calls(self):
        x = Identifier("x")
        self.assertEqual(
            parse_expression("derivative(sin(x^2), x)"),
            CallExpr(Identifier("derivative"), (
                CallExpr(Identifier("sin"), (BinaryExpr("^", x, NumberLiteral("2")),)),
                x,
            )),
        )
        self.assertEqual(parse_expression("f()"), CallExpr(Identifier("f"), ()))
        self.assertEqual(parse_expression("f()(x)"),
                         CallExpr(CallExpr(Identifier("f"), ()), (x,)))

    def test_call_precedes_power(self):
        self.assertEqual(
            parse_expression("sin(x)^2"),
            BinaryExpr("^", CallExpr(Identifier("sin"), (Identifier("x"),)),
                       NumberLiteral("2")),
        )

    def test_comments_and_newlines(self):
        self.assertEqual(
            parse_expression(" // heading\r\n 2 /* first\n second */ *\n x // end"),
            parse_expression("2*x"),
        )
        self.assertEqual(parse_expression("x/**//2"), parse_expression("x/2"))

    def test_spans_include_grouping_and_ignore_surrounding_spaces(self):
        source = "  (x + 1) *\n α "
        tree = parse_expression(source)
        self.assertEqual(tree.span, SourceSpan(2, 14, 1, 3))
        self.assertEqual(source[tree.left.span.start:tree.left.span.end], "(x + 1)")
        self.assertEqual(tree.left.left.span, SourceSpan(3, 4, 1, 4))
        self.assertEqual(tree.right.span, SourceSpan(13, 14, 2, 2))

    def test_call_and_unary_spans(self):
        tree = parse_expression(" -f(x, 2) ")
        self.assertEqual(tree.span, SourceSpan(1, 9, 1, 2))
        self.assertEqual(tree.operand.span, SourceSpan(2, 9, 1, 3))

    def test_nodes_are_immutable_and_structurally_comparable(self):
        tree = parse_expression("x+1")
        with self.assertRaises(FrozenInstanceError):
            tree.op = "*"
        other = parse_expression("  x + 1 ")
        self.assertEqual(tree, other)
        self.assertEqual(hash(tree), hash(other))
        self.assertEqual(tree.children, (Identifier("x"), NumberLiteral("1")))
        self.assertIsInstance(parse_expression("f(x)").arguments, tuple)

    def test_tree_rendering(self):
        self.assertEqual(format_tree(parse_expression("i*(i+i)")), "\n".join([
            "BinaryExpr(*)",
            "|-- Identifier(i)",
            "`-- BinaryExpr(+)",
            "    |-- Identifier(i)",
            "    `-- Identifier(i)",
        ]))
        self.assertEqual(format_tree(parse_expression("f(x)")), "\n".join([
            "CallExpr", "|-- Identifier(f)", "`-- Identifier(x)",
        ]))

    def test_long_left_associative_expression(self):
        tree = parse_expression("+".join(["x"] * 1200))
        self.assertEqual(len(format_tree(tree).splitlines()), 2399)


class ErrorTests(unittest.TestCase):
    def test_invalid_input_is_rejected_in_full(self):
        for source in (
            "", "  ", "// comment", "/* comment */", "()", "2 +", "*x", "x^",
            "(x+1", "x+1)", "f(,x)", "f(x,)", "f(x y)", "f(x", "x y", "2x",
            "x; y", "1.2.3", ".5", "1.", "$", "x @ y", "²",
        ):
            with self.subTest(source=source):
                with self.assertRaises(ParseError):
                    parse_expression(source)

    def test_error_points_to_missing_operand(self):
        with self.assertRaises(ParseError) as result:
            parse_expression("x +\n  * y")
        error = result.exception
        self.assertEqual(error.span, SourceSpan(6, 7, 2, 3))
        self.assertIn("found '*'", error.message)
        self.assertEqual(str(error).splitlines()[1:], ["  * y", "  ^"])

    def test_error_at_eof_and_after_crlf(self):
        for source, expected in (
            ("x +", SourceSpan(3, 3, 1, 4)),
            ("x +\n", SourceSpan(4, 4, 2, 1)),
            ("x +\r\n)", SourceSpan(5, 6, 2, 1)),
        ):
            with self.subTest(source=source):
                with self.assertRaises(ParseError) as result:
                    parse_expression(source)
                self.assertEqual(result.exception.span, expected)

    def test_unclosed_comment_points_to_opening(self):
        with self.assertRaises(ParseError) as result:
            parse_expression("x + /* unfinished\ncomment")
        self.assertEqual(result.exception.span.start, 4)
        self.assertEqual(result.exception.span.column, 5)
        self.assertIn("Unterminated block comment", str(result.exception))

    def test_error_caret_expands_tabs(self):
        with self.assertRaises(ParseError) as result:
            parse_expression("\t@")
        self.assertEqual(str(result.exception).splitlines()[1:], ["    @", "    ^"])

    def test_excessive_nesting_reports_parse_error(self):
        with self.assertRaises(ParseError) as result:
            parse_expression("(" * 2000 + "x" + ")" * 2000)
        self.assertIn("nesting is too deep", str(result.exception))


class LexerTests(unittest.TestCase):
    def test_token_kinds_and_offsets(self):
        tokens = tokenize("α + 12.50")
        self.assertEqual([t.kind for t in tokens], [
            TokenKind.IDENTIFIER, TokenKind.PLUS, TokenKind.NUMBER, TokenKind.EOF,
        ])
        self.assertEqual([t.text for t in tokens], ["α", "+", "12.50", ""])
        self.assertEqual(tokens[2].span, SourceSpan(4, 9, 1, 5))
        self.assertEqual(tokens[-1].span, SourceSpan(9, 9, 1, 10))


if __name__ == "__main__":
    unittest.main()
