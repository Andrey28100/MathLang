import unittest

from mathlang import (
    ParseError, RewriteExpr, RuleDeclaration, format_tree, parse_expression, parse_program,
)
from mathlang.lexer import TokenKind, tokenize


class RuleSyntaxTests(unittest.TestCase):
    def test_named_and_anonymous_rules(self):
        program = parse_program("rule {x+0->x}; rule drop {x*1->x}")
        self.assertIsInstance(program.statements[0], RuleDeclaration)
        self.assertIsNone(program.statements[0].name)
        self.assertEqual(program.statements[1].name, "drop")
        self.assertEqual(program.statements[0].clauses[0].pattern, parse_expression("x+0"))
        self.assertIn("RuleDeclaration(anonymous)", format_tree(program))

    def test_multiline_arrows_conditions_and_comments(self):
        program = parse_program("""rule double_angle {
    sin(2*x)
        -> 2*sin(x)*cos(x)
}
rule square {
    sqrt(x^2) -> x
        when x >= 0
    sin(0) -> 0 // second clause
}
rule
{
    x+0 -> x
}
""")
        self.assertEqual(len(program.statements), 3)
        clauses = program.statements[1].clauses
        self.assertEqual(len(clauses), 2)
        self.assertEqual(clauses[0].condition.op, ">=")
        self.assertIsNone(clauses[1].condition)

    def test_prefix_rewriting_and_grouping(self):
        for source in ("rewrite x+0 using drop", "rewrite (x+0) using drop", "rewrite (x+0)+0 using drop"):
            with self.subTest(source=source):
                expression = parse_expression(source)
                self.assertIsInstance(expression, RewriteExpr)
                self.assertEqual(expression.rules.name, "drop")
        expression = parse_expression("rewrite sin(x) using r top_down recursively")
        self.assertEqual((expression.strategy, expression.repeat), ("top_down", True))
        self.assertEqual(parse_expression("rewrite x once").strategy, "once")

    def test_prefix_span_is_preserved_inside_a_call(self):
        source = "print(rewrite (x+0)+0 using r)"
        node = parse_expression(source).arguments[0]
        self.assertEqual(source[node.span.start:node.span.end], "rewrite (x+0)+0 using r")

    def test_new_tokens_and_signed_exponents(self):
        tokens = tokenize("-> >= <= != ==")
        self.assertEqual([token.kind for token in tokens[:-1]], [
            TokenKind.ARROW, TokenKind.GREATEREQUAL, TokenKind.LESSEQUAL,
            TokenKind.NOTEQUAL, TokenKind.EQEQ,
        ])
        self.assertEqual(parse_expression("2^-3").right.op, "-")

    def test_invalid_rules(self):
        for source in ("rule {}", "rule r{}", "rule r{x+0=x}", "rule r{x->}",
                       "rule r{x->x y->y}", "rule r{x->x", "rule r{x->x when x}",
                       "rule r{x->x when x=0}", "rule r{x->x when x>=}",
                       "rewrite x using", "rewrite x once recursively", "rewrite x once top_down"):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_program(source)


if __name__ == "__main__":
    unittest.main()
