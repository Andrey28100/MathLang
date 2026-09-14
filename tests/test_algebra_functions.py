"""Language, domain and proof checks for generic algebra functions and division."""

from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from mathlang import (AlgebraNormalizer, DefinitionError, Embed, Limits,
                      PredicateQuery, Session, TruthValue, Type, check_proof,
                      dumps_ir, loads_ir)

T, F, U = TruthValue.TRUE, TruthValue.FALSE, TruthValue.UNKNOWN
DUAL = 'algebra D over Real {generators {eps}; relations {eps^2=0}; derive basis}'
COMPLEX = 'algebra C over Real {generators {j}; relations {j^2=-1}; derive basis}'


class AlgebraFunctionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.s.execute(DUAL + ';' + COMPLEX + ';a:Real;b:Real;c:Real;d:Real;x:Real')

    def same(self, left, right):
        self.assertIs(self.s.query(f'({left}) == ({right})'), T)

    def test_numeric_dual_division_against_independent_fraction_formula(self):
        rng = random.Random(92026)
        for _ in range(25):
            a, b, d = (rng.randint(-8, 8) for _ in range(3))
            c = rng.choice([n for n in range(-8, 9) if n])
            with self.subTest(a=a, b=b, c=c, d=d):
                result = self.s.resolve(f'normalize(({a}+({b})*D.eps)/({c}+({d})*D.eps))')
                expected = self.s.resolve(f'normalize(({Fraction(a,c)})+({Fraction(b*c-a*d,c*c)})*D.eps)')
                self.assertEqual(result, expected)

    def test_symbolic_division_derives_formula_only_with_required_guard(self):
        source = '(a+b*D.eps)/(c+d*D.eps)'
        self.assertIs(self.s.query(f'domain({source})'), U)
        with self.assertRaisesRegex(DefinitionError, 'invertibility'):
            self.s.resolve(f'normalize({source})')
        self.s.execute('assume c!=0')
        self.same(f'normalize({source})', 'a/c+(b*c-a*d)/c^2*D.eps')
        self.assertIs(self.s.query(f'domain({source})'), T)

    def test_nonzero_nilpotents_are_not_invertible_but_have_a_zeroth_power(self):
        self.assertIs(self.s.query('D.eps!=0'), T)
        for expression in ('1/D.eps', 'D.eps/D.eps', 'D.eps^-1', '0/D.eps'):
            with self.subTest(expression=expression):
                self.assertIs(self.s.query(f'domain({expression})'), F)
                with self.assertRaises(DefinitionError):
                    self.s.resolve(f'normalize({expression})')
        self.assertIs(self.s.query('domain(D.eps^0)'), T)
        self.assertEqual(self.s.execute('normalize(D.eps^0)').output, ('1',))

    def test_assuming_domain_supplies_the_scalar_invertibility_condition(self):
        self.s.execute('assume domain(1/(c+d*D.eps))')
        self.assertIs(self.s.query('c!=0'), T)
        self.same('normalize((c+d*D.eps)^-1)', '1/c-d/c^2*D.eps')
        with self.assertRaises(DefinitionError):
            self.s.execute('assume c==0')

    def test_singular_specialization_and_local_context_rollback(self):
        self.s.execute('q=(1+D.eps)/(c+d*D.eps)')
        with self.assertRaises(DefinitionError):
            self.s.execute('temporary=42; normalize(substitute(q,c=0,d=1))')
        self.assertIsNone(self.s.environment.get('temporary'))
        self.s.execute('assuming {c!=0} {normalize(q)}')
        self.assertIs(self.s.query('c!=0'), U)
        with self.assertRaisesRegex(DefinitionError, 'invertibility'):
            self.s.resolve('normalize(q)')

    def test_higher_dimension_inverse_is_not_a_dual_special_case(self):
        self.s.execute('algebra J over Rational {generator n; relation n^4=0; derive basis}')
        self.same('(1+J.n+J.n^2)^-1', '1-J.n+J.n^3')
        self.same('(2+J.n)^-2', '1/4-J.n/4+3*J.n^2/16-J.n^3/8')

    def test_noncommutative_right_division_and_both_inverse_products(self):
        self.s.execute('import std.quaternion {Quaternion}; use Quaternion')
        self.same('i/j', '-k')
        self.same('j^-1*i', 'k')
        q = '(1+2*i+3*j+4*k)'
        inverse = '(1-2*i-3*j-4*k)/30'
        self.same(f'{q}^-1', inverse)
        self.same(f'{q}*({inverse})', '1')
        self.same(f'({inverse})*{q}', '1')

    def test_typed_ir_and_annotated_functions_preserve_algebra_signatures(self):
        for source in ('1/(1+D.eps)', 'D.eps/(1+D.eps)', '(1+D.eps)^-1', 'exp(D.eps)'):
            with self.subTest(source=source):
                self.assertEqual(self.s.typed_ir(source).type, self.s['D'].type)
        ir = self.s.typed_ir('1/(1+D.eps)')
        self.assertIsInstance(ir.children[0], Embed)
        ir = self.s.typed_ir('exp(D.eps)')
        self.assertEqual(ir.children[0].type, Type('Function', (self.s['D'].type, self.s['D'].type)))
        self.s.execute('function inv(z:D):D {return z^-1}; function f(z:D):D {return exp(z)}')
        self.same('inv(1+D.eps)', '1-D.eps')
        self.same('f(D.eps)', '1+D.eps')

    def test_dual_builtin_functions_and_composition(self):
        for source, expected in (
            ('exp(a+b*D.eps)', 'exp(a)+b*exp(a)*D.eps'),
            ('sin(a+b*D.eps)', 'sin(a)+b*cos(a)*D.eps'),
            ('cos(a+b*D.eps)', 'cos(a)-b*sin(a)*D.eps'),
            ('exp(sin(D.eps))', '1+D.eps'),
        ):
            with self.subTest(source=source):
                self.same(source, expected)

    def test_euler_identity_and_checked_scale_do_not_depend_on_names(self):
        self.same('exp(C.j*x)', 'cos(x)+sin(x)*C.j')
        self.s.execute('algebra R over Real {generator rotation; relation rotation^2=-2; derive basis}')
        self.same('exp(x*R.rotation)', 'cos(sqrt(2)*x)+sin(sqrt(2)*x)/sqrt(2)*R.rotation')

    def test_regular_log_sqrt_and_inherited_domain_guards(self):
        self.assertIs(self.s.query('domain(log(a+b*D.eps))'), U)
        with self.assertRaises(DefinitionError):
            self.s.resolve('normalize(log(a+b*D.eps))')
        self.s.execute('assume domain(log(a+b*D.eps))')
        self.assertIs(self.s.query('a>0'), T)
        self.same('log(a+b*D.eps)', 'log(a)+(b/a)*D.eps')
        self.same('sqrt(a+b*D.eps)', 'sqrt(a)+b/(2*sqrt(a))*D.eps')
        self.assertIs(self.s.query('domain(sqrt(C.j))'), U)

    def test_complex_scalar_coefficients_for_entire_functions(self):
        self.s.execute('algebra Z over Complex {generator n; relation n^2=0; derive basis}; z:Complex')
        self.same('exp(z+Z.n)', 'exp(z)+exp(z)*Z.n')
        self.same('sin(z+Z.n)', 'sin(z)+cos(z)*Z.n')

    def test_unsupported_values_remain_distinct_from_undefined_ones(self):
        self.s.execute('algebra A over Real {generator t; relation t^3=2; derive basis}')
        self.assertIs(self.s.query('domain(exp(A.t))'), T)
        with self.assertRaisesRegex(DefinitionError, 'No exact algebra reduction'):
            self.s.resolve('normalize(exp(A.t))')
        for source in ('abs(D.eps)', 'tan(D.eps)', 'D.eps/C.j', 'exp(D.eps,C.j)'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.s.resolve(source)

    def test_partial_scalar_coefficients_cannot_disappear_through_relations(self):
        for source in ('0*(1/c)*D.eps', '(D.eps^2)/c', '0/(c+D.eps)',
                       '(1/c)*D.eps-(1/c)*D.eps', 'log(c)*D.eps^2'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.s.resolve(f'normalize({source})')
        self.s.execute('assume c>0')
        self.same('log(c)*D.eps^2', '0')
        self.same('(1/c)*D.eps-(1/c)*D.eps', '0')

    def test_proofs_recheck_without_search_and_reject_changed_analytic_goal(self):
        proof = self.s.execute('prove exp(C.j*x)=cos(x)+sin(x)*C.j').values[0].proof
        with patch('mathlang.proof.ProofSearch.equality', side_effect=AssertionError('search called')):
            self.assertTrue(check_proof(proof))
            self.assertTrue(check_proof(loads_ir(dumps_ir(proof))))
        forged = replace(proof, goal=replace(proof.goal, right=self.s.factory.number(0)))
        self.assertFalse(check_proof(forged))
        result = self.s.execute('prove 1/(c+D.eps)=1/c-D.eps/c^2').values[0]
        self.assertEqual(result.status, 'unknown')

    def test_saved_unconditional_expressions_keep_guards_at_use(self):
        self.s.execute('raw=1/(c+d*D.eps); euler=exp(C.j*x)')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'formulas.mathir'
            self.s.save_module(path, name='formulas')
            restored = Session()
            restored.load_module(path)
            self.assertIs(restored.query('domain(formulas.raw)'), U)
            restored.execute('assuming {formulas.c!=0} {normalize(formulas.raw)}')
            self.assertIs(restored.query('formulas.c!=0'), U)
            self.assertIs(restored.query('formulas.euler==cos(formulas.x)+sin(formulas.x)*formulas.C.j'), T)

    def test_scalar_coefficients_and_functions_keep_existing_exact_values(self):
        self.same('sqrt(2)*D.eps', '(2^(1/2))*D.eps')
        self.same('exp(1)*(1+D.eps)^-1', 'exp(1)-exp(1)*D.eps')

    def test_coordinate_api_and_matrix_resource_limit(self):
        normalizer = AlgebraNormalizer(self.s['D'], self.s.factory)
        coordinates = normalizer.coordinates(self.s.resolve('3+2*D.eps'))
        self.assertEqual(coordinates, {(): self.s.factory.number(3), (0,): self.s.factory.number(2)})
        self.assertEqual(normalizer.normalize(normalizer.from_coordinates(coordinates)),
                         self.s.resolve('normalize(3+2*D.eps)'))
        small = AlgebraNormalizer(self.s['D'], self.s.factory, Limits(max_terms=3))
        with self.assertRaisesRegex(ValueError, 'matrix size limit'):
            small.normalize(self.s.resolve('(1+D.eps)^-1'))


if __name__ == '__main__':
    unittest.main()
