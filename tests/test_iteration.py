"""Finite iteration contracts and independent exact Mandelbrot checks."""

from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import unittest

from mathlang import (DefinitionError, Embed, FunctionCall, Limits, Session, Type,
                      SerializationError, TruthValue, dumps_ir, loads_ir, format_term)
from mathlang.ide.language_service import LanguageService
from mathlang.ide.latex import format_latex

ROOT = Path(__file__).resolve().parents[1]


class IterationTests(unittest.TestCase):
    def test_recurrences_match_independent_exact_arithmetic(self):
        for count in range(7):
            expected = Fraction(2, 3)
            for _ in range(count):
                expected = expected/2+1
            actual = Session().resolve(f'iterate(x=>x/2+1, 2/3, {count})')
            # Count zero preserves the original arithmetic DAG.
            actual = Session().kernel.normalizer.simplify(actual)
            self.assertEqual(actual.value, expected)

    def test_zero_steps_do_not_evaluate_body_or_change_initial_expression(self):
        self.assertEqual(Session().execute('iterate(x=>simplify(1/0), 1+2, 0)').output, ('1 + 2',))

    def test_indexed_sums_and_products_match_independent_formulas(self):
        import math
        for n in range(8):
            session = Session()
            self.assertEqual(session.resolve(f'sum(k=>k^2,1,{n})').value, n*(n+1)*(2*n+1)//6)
            self.assertEqual(session.resolve(f'product(k=>k,1,{n})').value, math.factorial(n))
        self.assertEqual(Session().execute('sum(k=>1/k,1,3); sum(k=>k^2,-2,2)').output, ('11/6', '10'))

    def test_empty_ranges_are_identities_without_evaluation(self):
        session = Session()
        self.assertEqual(session.execute('sum(k=>simplify(1/0),3,2); product(k=>simplify(1/0),3,2)').output, ('0', '1'))
        self.assertEqual(session.execute('all(k=>query(simplify(1/0)==0),3,2); any(k=>query(simplify(1/0)==0),3,2)').output, ('True', 'False'))

    def test_bound_expressions_and_negative_indices(self):
        self.assertEqual(Session().execute('sum(k=>k, -2-1, 6/2); product(k=>k, -3, -1)').output, ('0', '-6'))

    def test_expression_binders_are_scoped_and_preserve_free_values(self):
        session = Session()
        self.assertEqual(session.execute('x:Real; k:Integer; a:Real; iterate(x+a,x,x,2); sum(k^2,k,-2,2); k').output,
                         ('2*a + x', '10', 'k'))
        self.assertEqual(format_term(session['x']), 'x')
        self.assertEqual(session.execute('sum(simplify(1/k),k,1,3)').output, ('11/6',))
        self.assertEqual(session.execute('sum(simplify(1/k),k,2,1)').output, ('0',))

    def test_nested_lambdas_and_captured_outer_indices(self):
        session = Session()
        self.assertEqual(session.execute('sum(k=>sum(j=>j*k,1,3),1,2)').output, ('18',))
        self.assertEqual(session.execute('sum(k=>sum(k=>k,1,2)+k,1,2)').output, ('9',))

    def test_aliases_and_user_shadowing(self):
        session = Session()
        self.assertEqual(session.execute('S=sum; k:Integer; S(k^2,k,1,3); sum(x,y,z)=x+y+z; sum(1,2,3)').output, ('14','1 + 2 + 3'))

    def test_function_arguments_defer_iteration_until_invocation(self):
        session = Session()
        session.execute('function factorial(n:Nat):Nat {return product(k=>k,1,n)}')
        self.assertEqual(session.execute('factorial(0); factorial(6)').output, ('1','720'))

    def test_symbolic_and_predicate_states(self):
        session = Session()
        session.execute('f:Function<Real,Real>; x:Real')
        self.assertEqual(session.execute('iterate(f,x,3)').output, ('f(f(f(x)))',))
        self.assertEqual(session.execute('iterate((p:Predicate)=>not p, True, 3)').output, ('False',))
        self.assertEqual(session.execute('iterate(sin,0,3)').output, ('0',))

    def test_noncommutative_product_preserves_increasing_index_order(self):
        session = Session()
        session.execute('import std.quaternion {Quaternion}; i=Quaternion.i; j=Quaternion.j')
        self.assertIs(session.query('product(n=>i+(j-i)*(n-1),1,2) == Quaternion.k'), TruthValue.TRUE)

    def test_all_any_short_circuit_and_keep_unknown(self):
        session = Session()
        self.assertEqual(session.execute('all(k=>k<0,1,3); any(k=>k>0,1,3)').output, ('False','True'))
        self.assertEqual(session.execute('all(k=>Unknown,1,3); any(k=>Unknown,1,3)').output, ('Unknown','Unknown'))
        # At index 2 the explicit simplification would divide by zero.
        self.assertEqual(session.execute('all(k=>simplify(1/(2-k))==0,1,2)').output, ('False',))
        self.assertEqual(session.execute('any(k=>simplify(1/(2-k))==1,1,2)').output, ('True',))

    def test_context_is_used_without_leaking_conditions(self):
        session = Session()
        result = session.execute('x:Real; assuming {x>=0} {sum(k=>sqrt(x^2),1,2); all(k=>x>=0,1,2)}; x>=0')
        self.assertEqual(result.output, ('2*x','True','Unknown'))

    def test_bad_signatures_counts_bounds_and_binders_are_diagnosed(self):
        sources = ('iterate(x=>x,0,-1)', 'iterate(x=>x,0,1/2)', 'iterate(x=>x,0)',
                   'iterate(2,0,3)', 'iterate((x,y,z)=>x+y+z,0,3)', 'iterate((x:Nat)=>x-1,1,3)',
                   'iterate(x=>(y=>x+y),0,3)', 'sum(k=>k,1/2,3)', 'sum(k=>k,1,2/3)',
                   'sum(k=>True,1,3)', 'product(k=>True,1,3)', 'all(k=>1,1,3)',
                   'any(k=>1,1,3)', 'sum((k:Nat)=>k,-1,3)', 'sum(1,2,3,4)',
                   'x=2; sum(x,x,1,3)', 'sum(k=>k,1,3,4,5)')
        for source in sources:
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                Session().execute(source)

    def test_iteration_limit_and_nested_shared_budget(self):
        with self.assertRaisesRegex(DefinitionError, 'Iteration count'):
            Session(limits=Limits(max_iterations=3)).execute('iterate(x=>x+1,0,4)')
        with self.assertRaisesRegex(DefinitionError, 'Iteration count'):
            Session(limits=Limits(max_iterations=5)).execute('sum(k=>sum(j=>j,1,2),1,2)')
        self.assertEqual(Session(limits=Limits(max_iterations=6)).execute('sum(k=>sum(j=>j,1,2),1,2)').output, ('6',))
        with self.assertRaises(ValueError):
            Limits(max_iterations=0)

    def test_symbolic_bounds_remain_ir_and_evaluate_after_substitution(self):
        session = Session()
        session.execute('n:Nat; S=sum(k=>k^2,1,n); P=product(k=>k,1,n); I=iterate(x=>x/2,1,n)')
        for name in ('S','P','I'):
            self.assertIsInstance(session[name], FunctionCall)
            self.assertEqual(loads_ir(dumps_ir(session[name])), session[name])
        self.assertEqual(session.execute('substitute(S,n=3); substitute(P,n=4); substitute(I,n=2)').output,
                         ('14','24','1/4'))
        self.assertEqual(format_latex(session['S']), r'\sum_{k=1}^{n} {k}^{2}')
        self.assertEqual(session.execute('query(all(k=>k>0,1,n))').output, ('Unknown',))

    def test_number_growth_is_limited_and_failures_roll_back(self):
        session = Session(limits=Limits(max_integer_bits=16))
        with self.assertRaises(DefinitionError):
            session.execute('temporary=1; iterate(x=>x^2,2,8)')
        self.assertIsNone(session.environment.get('temporary'))
        self.assertEqual(session.execute('iterate(x=>x+1,0,2)').output, ('2',))
        with self.assertRaises(DefinitionError):
            Session().execute('product(k=>1/(k-2),1,3)')

    def test_typed_ir_preserves_loop_and_contextual_function_types(self):
        session = Session()
        ir = session.typed_ir('iterate(x=>x/2,1,3)')
        self.assertIsInstance(ir.term, FunctionCall)
        self.assertEqual(ir.type, Type('Rational'))
        self.assertIsInstance(ir.children[2], Embed)
        self.assertEqual(ir.children[1].type, Type('Function', (Type('Rational'),Type('Rational'))))
        ir = session.typed_ir('sum(k=>k^2,1,10)')
        self.assertEqual(ir.type, Type('Nat'))
        self.assertEqual(ir.children[1].type, Type('Function', (Type('Nat'),Type('Nat'))))

    def test_saved_iteration_functions_work_after_loading(self):
        session = Session()
        session.execute('module loops; factorial(n)=product(k=>k,1,n)')
        restored = loads_ir(dumps_ir(session.export_module()))
        fresh = Session()
        self.assertEqual(format_term(fresh.kernel.evaluate(fresh.factory.call(restored.member('factorial'), (fresh.factory.number(5),)))), '120')
        data = json.loads(dumps_ir(session['factorial']))
        next(n for n in data['nodes'] if n['tag']=='FunctionCall')['fields']['arguments'] = {'tuple': []}
        with self.assertRaises(SerializationError):
            loads_ir(json.dumps(data))

    def test_cli_and_ide_examples(self):
        for name in ('iteration','mandelbrot'):
            path = ROOT/'examples'/f'{name}.math'
            completed = subprocess.run([sys.executable,'-m','mathlang','--file',str(path)], cwd=ROOT, text=True, encoding='utf-8',capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            service = LanguageService(ROOT)
            self.assertEqual(service.semantic_diagnostics(path.read_text(encoding='utf-8'),path=path), [])
        self.assertIn('iterate', LanguageService().completions('iter'))

    def test_indexed_latex_renders_actual_sum_product_and_quantifiers(self):
        session = Session()
        rendered = []
        for name, body, operator in (('sum','k^2',r'\sum'), ('product','k',r'\prod'),
                                      ('all','k>0',r'\bigwedge'), ('any','k<0',r'\bigvee')):
            term = session.typed_ir(f'{name}(k=>{body},1,3)').term
            latex = format_latex(term)
            self.assertIn(operator+'_{k=1}^{3}', latex)
            rendered.append(latex)
        try:
            from matplotlib.mathtext import MathTextParser
        except ImportError:
            self.skipTest('matplotlib is not installed')
        parser = MathTextParser('agg')
        for latex in rendered:
            parser.parse('$'+latex+'$',dpi=100)


class MandelbrotTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute_file(ROOT/'examples'/'mandelbrot.math')

    def test_orbit_matches_independent_complex_coordinate_recurrence(self):
        for cr, ci in ((Fraction(1),Fraction(1)), (Fraction(-3,4),Fraction(1,10))):
            x, y = Fraction(0), Fraction(0)
            for count in range(5):
                self.session.execute(f'z=orbit({cr},{ci},{count})')
                self.assertEqual(self.session.resolve('simplify(z(0))').value, x)
                self.assertEqual(self.session.resolve('simplify(z(1))').value, y)
                x, y = x*x-y*y+cr, 2*x*y+ci

    def test_membership_is_not_invented_from_a_finite_non_escape(self):
        for args, expected in (('0,0,4','True'), ('-1,0,4','True'), ('1,0,2','Unknown'),
                               ('1,0,3','False'), ('1,1,4','False'), ('-2,0,4','Unknown'),
                               ('-3/4,1/10,3','Unknown'), ('1,0,0','Unknown')):
            self.assertEqual(self.session.execute(f'mandelbrot({args})').output, (expected,))

    def test_radius_two_is_not_an_escape(self):
        self.assertEqual(self.session.execute('bounded_through(-2,0,4); bounded_through(2,0,1); bounded_through(2,0,2)').output,
                         ('True','True','False'))
