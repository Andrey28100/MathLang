from fractions import Fraction
import json
import math
from pathlib import Path
import unittest

from mathlang import (DefinitionError, FunctionCall, Limits, ParseError, Session,
                      SerializationError, TaylorSeries, Type, antiderivative,
                      builtin_symbol, dumps_ir, format_term, integrate, loads_ir, parse_expression)
from mathlang.ide.latex import format_latex


class IndexedIterationTests(unittest.TestCase):
    def test_typed_state_and_index_have_consistent_one_based_semantics(self):
        session = Session()
        for count in range(7):
            self.assertEqual(session.resolve(f'iterate((s:Nat,i:Nat)=>s*i,1,{count})').value, math.factorial(count))
        self.assertEqual(session.execute('iterate((s:Real,i:Integer)=>s+i,0,3)').output, ('6',))
        with self.assertRaises(DefinitionError):
            session.execute('iterate((s:Nat,i:Predicate)=>s,0,3)')

    def test_multiline_iteration_and_reduction_blocks(self):
        session = Session()
        result = session.execute('''iterate(1,5) {
    (value:Nat,index:Nat)=>value*index
}
sum(-2,2) {(index:Integer)=>index^2}
product(1,3) {(index:Nat)=>index}
''')
        self.assertEqual(result.output, ('120','10','6'))
        self.assertIsNone(session.environment.get('index'))
        self.assertEqual(session.execute('f(n)=iterate(1,n) {(s:Nat,i:Nat)=>s*i}; f(4)').output, ('24',))

    def test_block_lowering_and_typed_ir_preserve_signature(self):
        a = parse_expression('iterate(1,4) {(s:Nat,i:Nat)=>s*i}')
        b = parse_expression('iterate((s:Nat,i:Nat)=>s*i,1,4)')
        self.assertEqual(a,b)
        ir = Session().typed_ir('iterate(1,4) {(s:Nat,i:Nat)=>s*i}')
        self.assertEqual(ir.children[1].type, Type('Function',(Type('Nat'),Type('Nat'),Type('Nat'))))
        real = Session().typed_ir('iterate(1,4) {(s:Real,i:Nat)=>s*i}')
        self.assertEqual(real.type, Type('Real'))
        self.assertEqual(real.children[1].type, Type('Function',(Type('Real'),Type('Nat'),Type('Real'))))
        with self.assertRaises(DefinitionError):
            Session().execute('iterate(1,4) {(s:Nat,i:Nat)=>s-i}')
        for source in ('iterate(1,4) {s*i}', 'iterate(1,4) {(s:Nat,i:Nat)=>}', 'iterate(1,4) {'):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_expression(source)

    def test_factorial_is_exact_deferred_and_bounded(self):
        session = Session()
        for n in range(16):
            self.assertEqual(session.resolve(f'factorial({n})').value, math.factorial(n))
        session.execute('n:Nat; f=factorial(n)')
        self.assertIsInstance(session['f'], FunctionCall)
        self.assertEqual(session.execute('substitute(f,n=6)').output, ('720',))
        self.assertEqual(format_latex(session['f']), 'n!')
        for source in ('factorial(-1)','factorial(1/2)','factorial()','factorial(1,2)'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                session.execute(source)
        for limits, source in ((Limits(max_integer_bits=10),'factorial(10)'),
                               (Limits(max_iterations=3),'factorial(4)'),
                               (Limits(max_iterations=5),'sum(k=>factorial(k),1,3)')):
            with self.assertRaises(DefinitionError):
                Session(limits=limits).execute(source)


class DefiniteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute('x:Real; a:Real; b:Real')

    def test_primitives_and_definite_integrals_are_separate(self):
        self.assertEqual(self.session.execute('antiderivative(x^2,x); integrate(x^2,x,0,1)').output, ('1/3*x^3','1/3'))
        with self.assertRaisesRegex(DefinitionError, 'antiderivative'):
            self.session.execute('integrate(x^2,x)')
        primitive = antiderivative(self.session.resolve('x^2'),self.session['x'])
        result = integrate(self.session.resolve('x^2'),self.session['x'],self.session.factory.number(0),self.session.factory.number(1))
        self.assertEqual(format_term(primitive),'1/3*x^3')
        self.assertEqual(result.value,Fraction(1,3))

    def test_polynomial_integrals_match_independent_endpoint_formula(self):
        for power in range(1,7):
            for a,b in ((-2,3),(3,-2),(1,1)):
                actual=self.session.resolve(f'integrate(x^{power},x,{a},{b})')
                self.assertEqual(actual.value,Fraction(b**(power+1)-a**(power+1),power+1))

    def test_functions_operators_pipeline_and_symbolic_bounds(self):
        self.assertEqual(self.session.execute('I=integrate(x,0,1); I(x^2); x^2 |> integrate(x,0,1); integrate((t:Real)=>t^2,x,0,1)').output,
                         ('1/3','1/3','1/3'))
        self.session.execute('area(t)=integrate(x^2,x,0,t)')
        self.assertEqual(self.session.execute('area(3)').output, ('9',))
        self.assertEqual(self.session.execute('integrate(x^2,x,a,b) |> substitute(a=0,b=3) |> simplify').output, ('9',))

    def test_elementary_regular_intervals_and_exact_square_roots(self):
        self.assertEqual(self.session.execute('integrate(sqrt(x),x,0,4); integrate(1/x,x,1,2); integrate(exp(x),x,0,1)').output,
                         ('16/3','log(2)','exp(1) - 1'))
        self.assertEqual(self.session.query('integrate(1/x,x,-2,-1) == -log(2)').value, 'True')

    def test_singularities_inside_or_at_endpoints_are_not_ordinary_integrals(self):
        sources = ('integrate(1/x,x,-1,1)','integrate(1/(x-1),x,0,2)',
                   'integrate(log(x),x,0,1)','integrate(sqrt(x),x,-1,1)',
                   'integrate(1/x,x,0,0)','integrate(0*(1/x),x,-1,1)',
                   'integrate(x/x,x,-1,1)','integrate(tan(x),x,0,2)',
                   'integrate(1/x,x,a,b)','integrate(x,x,x,1)')
        for source in sources:
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.session.execute(source)

    def test_new_ir_preserves_bounds_and_reads_legacy_primitive_operators(self):
        operator=self.session.resolve('integrate(x,0,1)')
        self.assertEqual(loads_ir(dumps_ir(operator)),operator)
        data=json.loads(dumps_ir(self.session.resolve('antiderivative(x)')))
        data['version']=3
        for record in data['nodes']:
            if record['tag']=='CalculusOperator':
                record['fields'].pop('upper')
                record['fields']['operation']='integrate'
        restored=loads_ir(json.dumps(data))
        self.assertEqual(restored.operation,'antiderivative')
        self.assertEqual(format_term(self.session.kernel.evaluate(self.session.factory.call(restored,(self.session.resolve('x^2'),)))),'1/3*x^3')
        old=json.loads(dumps_ir(builtin_symbol('integrate')))
        old['version']=3
        self.assertEqual(loads_ir(json.dumps(old)),builtin_symbol('antiderivative'))
        broken=json.loads(dumps_ir(operator))
        next(n for n in broken['nodes'] if n['tag']=='CalculusOperator')['fields']['upper']=None
        with self.assertRaises(SerializationError):
            loads_ir(json.dumps(broken))


class TaylorAnalysisExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.session=Session()
        self.session.execute('x:Real; S=series(exp(x),x=0,order=5)')

    def test_series_types_are_preserved_through_functions_and_typed_ir(self):
        self.session.execute('function slope(s:Series<Real>):Series<Real> {return derivative(s,x)}')
        self.assertIsInstance(self.session.resolve('slope(S)'),TaylorSeries)
        for operation in ('derivative','antiderivative'):
            self.assertEqual(self.session.typed_ir(f'{operation}(S,x)').type,Type('Series',(Type('Real'),)))

    def test_symbolic_finite_sums_support_deferred_termwise_calculus(self):
        self.session.execute('n:Nat; P=sum(1,n) {(k:Nat)=>x^k/factorial(k)}; d=derivative(P,x); F=antiderivative(P,x); A=integrate(P,x,0,1); L=limit(P,x -> 0)')
        self.assertIsInstance(self.session['d'],FunctionCall)
        self.assertEqual(self.session.execute('substitute(A,n=2); substitute(L,n=2)').output, ('2/3','0'))
        self.assertEqual(self.session.query('substitute(d,n=3) == 1+x+x^2/2').value,'True')
        self.assertEqual(self.session.query('substitute(F,n=2) == x^2/2+x^3/6').value,'True')
        self.assertEqual(self.session.execute('substitute(d,n=0) |> substitute(x=0)').output, ('0',))
        self.session.execute('Q=sum(x,x,1,n); dQ=derivative(Q,x)')
        self.assertEqual(self.session.execute('substitute(dQ,n=3)').output, ('0',))
        self.assertEqual(loads_ir(dumps_ir(self.session['A'])),self.session['A'])

    def test_series_derivative_primitive_and_limit_keep_remainder_contract(self):
        self.assertEqual(self.session.resolve('derivative(S,x)').order,4)
        integrated=self.session.resolve('antiderivative(S,x)')
        self.assertEqual(integrated.order,6)
        self.assertEqual(integrated.coefficients[0].value,0)
        self.assertEqual(self.session.execute('limit(S,x -> 0)').output, ('1',))
        self.session.execute('T=series(x^2,x=2,order=4)')
        self.assertEqual(self.session.execute('limit(T,x -> 2)').output, ('4',))
        for source in ('limit(S,x -> 1)','limit(derivative(S,x,order=5),x -> 0)',
                       'integrate(S,x,0,1)'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.session.execute(source)
        self.assertEqual(self.session.execute('integrate(S,x,0,0)').output, ('0',))
        self.assertEqual(self.session.execute('integrate(polynomial(S),x,0,1)').output, ('103/60',))

    def test_example_executes_and_mathtext_renders_new_operations(self):
        path=Path(__file__).resolve().parents[1]/'examples'/'series_calculus.math'
        session=Session()
        session.execute_file(path)
        try:
            from matplotlib.mathtext import MathTextParser
        except ImportError:
            self.skipTest('matplotlib is not installed')
        parser=MathTextParser('agg')
        for expression in ('integrate(x,0,1)','antiderivative(x)','factorial(6)'):
            term=session.typed_ir(expression).term
            parser.parse('$'+format_latex(term)+'$',dpi=100)
