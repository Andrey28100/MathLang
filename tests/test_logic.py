"""Executable contracts for the bounded logic/assumptions stage 0.8."""

import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mathlang import (AssumptionSet, Comparison, Context, Defined, DefinitionError,
                      Embed, Limits, LogicError, Logical, ParseError, Predicate,
                      PredicateQuery, SerializationError, Session, TermFactory,
                      Truth, TruthValue, Type, dumps_ir, format_term, format_tree,
                      loads_ir, parse_expression, parse_program)

T, F, U = TruthValue.TRUE, TruthValue.FALSE, TruthValue.UNKNOWN


class PredicateTests(unittest.TestCase):
    def test_all_kleene_truth_tables(self):
        session = Session()
        for a, b in itertools.product((T, F, U), repeat=2):
            expected_and = F if F in (a, b) else U if U in (a, b) else T
            expected_or = T if T in (a, b) else U if U in (a, b) else F
            self.assertIs(session.query(f'{a.value} and {b.value}'), expected_and)
            self.assertIs(session.query(f'{a.value} or {b.value}'), expected_or)
        for a, expected in ((T, F), (F, T), (U, U)):
            self.assertIs(session.query('not '+a.value), expected)

    def test_predicates_and_unknown_cannot_silently_become_python_true(self):
        session = Session()
        session.execute('x:Real')
        for value in (U, session.resolve('Unknown'), session.resolve('x>0')):
            with self.assertRaises(TypeError):
                bool(value)
        self.assertTrue(bool(session.resolve('True')))
        self.assertFalse(bool(session.resolve('False')))

    def test_precedence_ast_and_equality_syntax(self):
        session = Session()
        self.assertIs(session.query('not 2 < 1 and False or True'), T)
        self.assertIs(session.query('2+3*4 == 14'), T)
        session.execute('x:Real; y=2; p=(x=0)')
        self.assertIsInstance(session['p'], Comparison)
        self.assertEqual(format_term(session['y']), '2')
        self.assertIn('ComparisonExpr(=)', format_tree(parse_expression('x = 0')))
        self.assertIn('ComparisonExpr(===)', format_tree(parse_expression('x === x')))
        self.assertIn('AssumingStatement', format_tree(parse_program('assuming {True} {False}')))
        for source in ('x<y<z', 'True and', 'not', 'True===', '1====2', 'assume', 'assuming {True}'):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_program(source)

    def test_exact_comparisons_and_unknown_mathematical_equality(self):
        session = Session()
        session.execute('x:Real; y:Real')
        cases = {'1/2 < 2/3': T, '3!=3': F, 'x+x == 2*x': T,
                 'x+x === 2*x': F, 'x === x': T, 'x === y': F,
                 'x==0': U, 'x==y': U, 'x+1==x': F, 'x^2>=0': T,
                 'x^2>0': U, 'Unknown==Unknown': U, 'Unknown===Unknown': T}
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertIs(session.query(source), expected)

    def test_predicate_storage_requeries_in_the_current_context(self):
        session = Session()
        result = session.execute('x:Real; p=x>0; p; assume x>0; p')
        self.assertEqual(result.output, ('Unknown', 'True'))
        self.assertIsInstance(session['p'], Comparison)
        self.assertIs(session.query(session['p']), T)

    def test_types_coercions_and_invalid_logical_operations(self):
        session = Session()
        session.execute('x:Real; c:Complex; A:Matrix<Real,2,2>')
        ir = session.typed_ir('1 < x')
        self.assertEqual(ir.type, Type('Predicate'))
        self.assertIsInstance(ir.children[0], Embed)
        self.assertEqual(ir.children[0].type, Type('Real'))
        self.assertNotIsInstance(session.typed_ir('1 === x').children[0], Embed)
        for source in ('x and True', 'not x', 'c > 0', 'A < A', 'A == x', 'query(2)', 'True+1', 'assume x'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                session.execute(source)

    def test_predicate_functions_and_substitution(self):
        session = Session()
        result = session.execute('''x:Real
function positive(t:Real):Predicate {return t>0}
positive(2); positive(-1)
p=positive(x)
substitute(p,x=3)
''')
        self.assertEqual(result.output, ('True', 'False', 'True'))
        self.assertEqual(session.typed_ir('positive(2)').type, Type('Predicate'))
        self.assertIs(session.query('p'), U)

    def test_algebra_equality_and_symbol_identity(self):
        session = Session()
        session.execute('import std.complex {Complex}; namespace N {x:Real}; x:Real')
        self.assertIs(session.query('Complex.i^2 == -1'), T)
        self.assertIs(session.query('N.x === x'), F)
        session.execute('assume x>0')
        self.assertIs(session.query('N.x>0'), U)


class AssumptionTests(unittest.TestCase):
    def test_domain_obligations_reject_conflicts_in_both_orders(self):
        pairs = (
            ('1/x>0', 'x==0'),
            ('domain(log(x))', 'x<=0'),
            ('domain(sqrt(x))', 'x<0'),
            ('domain(x^-2)', 'x==0'),
            ('domain(1/log(x))', 'x==0'),
            ('not domain(1/x)', 'x!=0'),
            ('not domain(sqrt(x))', 'x>=0'),
        )
        for pair in pairs:
            for first, second in (pair, tuple(reversed(pair))):
                with self.subTest(first=first, second=second):
                    session = Session()
                    session.execute('x:Real; assume '+first)
                    original = session.context
                    with self.assertRaises(DefinitionError):
                        session.execute('assume '+second)
                    self.assertEqual(session.context, original)

    def test_bound_queries_are_sound_against_independent_numeric_models(self):
        from fractions import Fraction
        from operator import eq, ne, lt, le, gt, ge
        operators = {'==': eq, '!=': ne, '<': lt, '<=': le, '>': gt, '>=': ge}
        for conditions in ((('>', -2), ('<=', 3)), (('>=', 1), ('<=', 1)),
                           (('!=', 0),), (('==', -1),)):
            session = Session()
            session.execute('x:Real; '+'; '.join(f'assume x{op}{n}' for op, n in conditions))
            models = [Fraction(n, 2) for n in range(-12, 13)
                      if all(operators[op](Fraction(n, 2), bound) for op, bound in conditions)]
            for op, compare in operators.items():
                for bound in range(-4, 5):
                    result = session.query(f'x{op}{bound}')
                    with self.subTest(conditions=conditions, query=(op, bound)):
                        if result is T:
                            self.assertTrue(all(compare(x, bound) for x in models))
                        elif result is F:
                            self.assertTrue(all(not compare(x, bound) for x in models))

    def test_nested_blocks_restore_context_and_definitions(self):
        session = Session()
        result = session.execute('''x:Real; x>=0
assuming {x>=0} {
    x>=0; simplify(sqrt(x^2))
    assuming {x>2} {x>1; const local=2}
    x>1
}
x>=0
''')
        self.assertEqual(result.output, ('Unknown', 'True', 'x', 'True', 'Unknown', 'Unknown'))
        self.assertEqual(session.context, Context())
        self.assertIsNone(session.environment.get('local'))

    def test_simple_bounds_reverse_comparisons_and_negations(self):
        session = Session()
        session.execute('x:Real; assume 2<x; assume x<=4')
        for source, result in (('x>=0', T), ('x!=0', T), ('x<=2', F), ('x>4', F),
                               ('x==3', U), ('0<x', T), ('not x<=2', T)):
            self.assertIs(session.query(source), result, source)
        other = Session()
        other.execute('x:Real; assume not x>=0')
        self.assertIs(other.query('x<0'), T)

    def test_contradictions_fail_atomically(self):
        for assumption in ('x<0', 'x==0', 'not x>0', 'x<=0 and x>2'):
            session = Session()
            session.execute('x:Real; assume x>0')
            context = session.context
            with self.assertRaises(DefinitionError):
                session.execute('temporary=2; assume '+assumption)
            self.assertEqual(session.context, context)
            self.assertIsNone(session.environment.get('temporary'))
        session = Session()
        with self.assertRaises(DefinitionError):
            session.execute('x:Real; assume x>0 and x<0')
        self.assertIsNone(session.environment.get('x'))

    def test_assumptions_roll_back_after_unrelated_errors(self):
        session = Session()
        session.execute('x:Real')
        with self.assertRaises(DefinitionError):
            session.execute('assume x>0; undefined_name')
        self.assertEqual(session.context, Context())
        with self.assertRaises(DefinitionError):
            session.execute('assuming {x>0} {unknown_name}')
        self.assertIs(session.query('x>0'), U)

    def test_disjunction_does_not_assert_either_branch(self):
        session = Session()
        session.execute('x:Real; y:Real; assume x>0 or y>0')
        self.assertIs(session.query('x>0 or y>0'), T)
        self.assertIs(session.query('x>0'), U)
        self.assertIs(session.query('y>0'), U)
        session.execute('assume x<=0')
        with self.assertRaises(DefinitionError):
            session.execute('assume y<=0')

    def test_assumptions_are_not_shared_between_sessions_or_namespaces(self):
        first, second = Session(), Session()
        first.execute('x:Real; assume x>0')
        second.execute('x:Real')
        self.assertIs(second.query('x>0'), U)
        result = second.execute('namespace N {assuming {x>0} {x>0}}; x>0')
        self.assertEqual(result.output, ('True', 'Unknown'))

    def test_unknown_and_false_literals_cannot_be_assumed(self):
        for condition in ('Unknown', 'not Unknown', 'Unknown or False', 'False', '1==2', '1/0==1'):
            with self.subTest(condition=condition), self.assertRaises(DefinitionError):
                Session().execute('assume '+condition)

    def test_conditional_results_do_not_enter_unconditional_certificates_or_modules(self):
        session = Session()
        session.execute('module sample; x:Real; assume x>=0')
        with self.assertRaisesRegex(DefinitionError, 'assumption-free'):
            session.execute('prove simplify(sqrt(x^2)) = x')
        with self.assertRaisesRegex(ValueError, 'active assumptions'):
            session.export_module()
        with self.assertRaisesRegex(DefinitionError, 'cannot be exported'):
            Session().execute('namespace N {x:Real; assume x>0; value=simplify(sqrt(x^2))}')


class ConditionalSimplificationTests(unittest.TestCase):
    def test_known_undefined_opaque_call_cannot_be_discarded(self):
        session = Session()
        session.execute('x:Real; h:Function<Real,Real>; assume not domain(h(x))')
        self.assertIs(session.query('domain(h(x))'), F)
        self.assertEqual(session.execute('simplify(0*h(x))').output, ('0*h(x)',))

    def test_explicit_rewriting_visits_predicate_operands(self):
        session = Session()
        session.execute('x:Real; y:Real; rule double {t+t -> 2*t}')
        result = session.resolve('rewrite(not (x+x==y) or domain(x+x)) using double')
        self.assertEqual(format_term(result), 'not 2*x == y or domain(2*x)')
        self.assertEqual(session.resolve(format_term(result)), result)

    def test_sqrt_square_and_abs_need_proved_sign(self):
        session = Session()
        result = session.execute('''x:Real
simplify(sqrt(x^2))
assuming {x>=0} {simplify(sqrt(x^2)); simplify(abs(x)); sqrt(x^2)==x}
assuming {x<0} {simplify(sqrt(x^2)); simplify(abs(x)); sqrt(x^2)==-x}
simplify(sqrt(x^2))
''')
        self.assertEqual(result.output, ('sqrt(x^2)', 'x', 'x', 'True', '-x', '-x', 'True', 'sqrt(x^2)'))

    def test_rule_conditions_use_local_assumptions_only(self):
        session = Session()
        result = session.execute('''x:Real
rule square_root {sqrt(t^2) -> t when t>=0}
rewrite(sqrt(x^2)) using square_root
assuming {x>=0} {rewrite(sqrt(x^2)) using square_root}
rewrite(sqrt(x^2)) using square_root
''')
        self.assertEqual(result.output, ('sqrt(x^2)', 'x', 'sqrt(x^2)'))

    def test_domain_predicates_and_partial_reflexivity(self):
        session = Session()
        session.execute('x:Real')
        for source, expected in (('domain(1/x)', U), ('domain(1/0)', F), ('domain(0^0)', F),
                                 ('domain(log(0))', F), ('domain(sqrt(-1))', F),
                                 ('domain(sqrt(x^2))', T), ('1/x==1/x', U), ('1/0===1/0', T)):
            with self.subTest(source=source):
                self.assertIs(session.query(source), expected)
        session.execute('assume x!=0')
        self.assertIs(session.query(session.domain('1/x')), T)
        self.assertIs(session.query('1/x==1/x'), T)
        self.assertEqual(session.execute('simplify(x/x); simplify(0/x); simplify(x^0)').output, ('1', '0', '1'))
        other = Session()
        other.execute('x:Real; assume domain(1/x)')
        self.assertIs(other.query('x!=0'), T)
        self.assertEqual(other.execute('simplify(x/x)').output, ('1',))

    def test_zero_assumption_prevents_cancellation(self):
        session = Session()
        session.execute('x:Real; assume x==0')
        self.assertIs(session.query('domain(1/x)'), F)
        self.assertIs(session.query('1/x==1/x'), U)
        self.assertEqual(session.execute('simplify(x/x)').output, ('x/x',))

    def test_query_and_assumption_limits(self):
        session = Session(limits=Limits(max_terms=1))
        session.execute('x:Real; y:Real; assume x>0')
        with self.assertRaisesRegex(DefinitionError, 'Assumption count'):
            session.execute('assume y>0')
        self.assertEqual(len(session.context.assumptions.predicates), 1)
        factory = TermFactory()
        predicate = factory.truth(U)
        for _ in range(20):
            predicate = factory.logical('not', predicate)
        with self.assertRaises(ValueError):
            PredicateQuery(factory, limits=Limits(max_steps=10)).query(predicate)


class PredicateIntegrationTests(unittest.TestCase):
    def test_predicate_type_is_not_parameterized(self):
        with self.assertRaises(DefinitionError):
            Session().execute('p:Predicate<Real>')

    def test_predicate_ir_round_trip_and_forged_data_rejection(self):
        session = Session()
        session.execute('module conditions; x:Real; p=x>0 and not x==1; valid=domain(1/x); truth=Unknown')
        module = loads_ir(dumps_ir(session.export_module()))
        self.assertIsInstance(module.member('p'), Logical)
        self.assertIsInstance(module.member('valid'), Defined)
        self.assertIs(module.member('truth').value, U)
        bad = json.loads(dumps_ir(session['p']))
        next(n for n in bad['nodes'] if n['tag'] == 'Comparison')['fields']['op'] = 'arbitrary'
        with self.assertRaises(SerializationError):
            loads_ir(json.dumps(bad))
        bad = json.loads(dumps_ir(session['truth']))
        bad['nodes'][-1]['fields']['value'] = {'truth': 'Maybe'}
        with self.assertRaises(SerializationError):
            loads_ir(json.dumps(bad))
        old = json.loads(dumps_ir(session['x']))
        old['version'] = 2
        self.assertEqual(loads_ir(json.dumps(old)), session['x'])

    def test_loaded_predicates_query_using_current_symbol_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'conditions.mathir'
            source = Session()
            source.execute('module conditions; x:Real; p=x>0')
            source.save_module(path)
            session = Session()
            session.load_module(path)
            self.assertIs(session.query('conditions.p'), U)
            session.execute('assume conditions.x>0')
            self.assertIs(session.query('conditions.p'), T)

    def test_cli_and_repl_predicates_and_recovery(self):
        project = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-m', 'mathlang', '--repl'],
            input='x:Real\n:query x>0\nassume x>0\n:assumptions\n:query x>=0\nassume x<0\n:query x>0\n:quit\n',
            text=True, encoding='utf-8', capture_output=True, cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'Unknown\nx > 0\nTrue\nTrue\n')
        self.assertIn('contradicts', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_ide_analysis_isolated_and_assumptions_visible_after_execution(self):
        from mathlang.ide.language_service import LanguageService
        service = LanguageService()
        source = 'x:Real; assume x>=0; simplify(sqrt(x^2)); x>=0'
        self.assertEqual(service.semantic_diagnostics(source), [])
        self.assertEqual(service.assumptions(), ())
        self.assertEqual([i.text for i in service.execute(source)], ['x', 'True'])
        self.assertEqual(service.assumptions(), ('x >= 0',))
        self.assertIn('assuming', service.completions('assum'))
        self.assertIn('Predicate', service.inspect_expression('x>=0'))


if __name__ == '__main__':
    unittest.main()
