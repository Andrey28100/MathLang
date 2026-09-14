from pathlib import Path
import tempfile
import unittest

from mathlang import (Session, DefinitionError, ParseError, MATH_ALIASES, dumps_ir,
                      loads_ir, parse_expression, format_term, format_tree, parse_program)
from mathlang.lexer import tokenize, TokenKind


class MathematicalSymbolTests(unittest.TestCase):
    def test_aliases_are_identifiers_with_original_source_positions(self):
        tokens = tokenize('$alpha + $my_symbol')
        self.assertEqual(tokens[0].kind, TokenKind.IDENTIFIER)
        self.assertEqual(tokens[0].text, '$alpha')
        self.assertEqual((tokens[0].span.start, tokens[0].span.end), (0, 6))
        expression = parse_expression('$alpha + $my_symbol')
        self.assertEqual(expression.left.name, 'α')
        self.assertEqual(expression.right.name, '$my_symbol')
        self.assertEqual(expression.left.span.end, 6)
        for spelling, symbol in MATH_ALIASES.items():
            with self.subTest(spelling=spelling):
                self.assertEqual(parse_expression(spelling), parse_expression(symbol))

    def test_arbitrary_names_are_distinct_and_require_declarations(self):
        session = Session()
        session.execute('parameter $name:Real; parameter name:Real; variable $x:Real')
        self.assertIsNot(session['$name'], session['name'])
        self.assertEqual(session.execute('derivative($name*$x^2,$x)').output, ('2*$name*$x',))
        with self.assertRaisesRegex(DefinitionError, 'Undefined name'):
            session.execute('$missing')
        for source in ('$', '$1', '$ alpha', '$$alpha', 'x$alpha', '$alpha$beta'):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_expression(source)

    def test_greek_bindings_capture_substitution_and_duplicate_detection(self):
        session = Session()
        session.execute('parameter $alpha:Real; variable β:Real; f($beta)=$alpha*$beta^2')
        self.assertIs(session['$alpha'], session['α'])
        self.assertEqual(session.execute('f(β) |> substitute($alpha=2, $beta=3) |> normalize').output, ('18',))
        with self.assertRaises(DefinitionError):
            session.execute('variable α:Real')
        for source in ('f($alpha,α)=α', '($alpha,α)=>α', 'series(β,$beta=0,β=1)'):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_program(source)

    def test_algebra_rules_and_proofs_use_the_same_symbol(self):
        session = Session()
        result = session.execute('''algebra D over Real {
            generators {$epsilon}
            relations {$epsilon^2=0}
            basis {1, ε}
        }
        with D {normalize((1+ε)^3); prove $epsilon^2=0}
        parameter $alpha:Real
        rule twice { $term+$term -> 2*$term }
        rewrite($alpha+$alpha) using twice
        ''')
        self.assertEqual(result.output[0], '3*ε + 1')
        self.assertEqual(result.values[1].status, 'proved')
        self.assertEqual(result.output[-1], '2*α')

    def test_module_members_and_ir_round_trip(self):
        session = Session()
        session.execute('module demo; namespace N {parameter $alpha:Real; f($arg)=$arg+$alpha}; const $infty:ExtendedReal; const $partial:Operator')
        value = loads_ir(dumps_ir(session.export_module()))
        self.assertIs(value.member('N').member('α'), value.member('N').member('f').body.right)
        self.assertEqual(format_term(session['$infty']), '∞')
        self.assertEqual(format_term(session['$partial']), '∂')
        self.assertIs(session.resolve('N.$alpha'), session.resolve('N.α'))
        self.assertIn('NamespaceDeclaration(N)', format_tree(parse_program('namespace N {const $alpha=2}')))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'demo.mathir'
            session.save_module(path)
            restored = Session()
            restored.load_module(path)
            self.assertEqual(restored.execute('normalize(demo.N.f(2)-demo.N.$alpha)').output, ('2',))

    def test_error_span_counts_dollar_spelling_not_display_width(self):
        session = Session()
        source = 'const $alpha=2\n$missing'
        with self.assertRaises(DefinitionError) as result:
            session.execute(source)
        self.assertEqual(result.exception.span.start, source.index('$missing'))
        self.assertIsNone(session.environment.get('α'))


if __name__ == '__main__':
    unittest.main()
