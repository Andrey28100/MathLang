from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from mathlang import (AssumptionSet, Context, DefinitionError, ForAll, FunctionCall,
                      Implementation, Limits, ParseError, PredicateQuery, PropertyResult,
                      SerializationError, Session, Symbol, SymbolKind, TermFactory,
                      Theory, TruthValue, Type, dumps_ir, format_term, format_tree,
                      free_symbols, loads_ir, parse_expression, parse_program)
from mathlang.ide.language_service import LanguageService
from mathlang.ide.latex import format_latex
from mathlang.theories import validate_implementation

ROOT = Path(__file__).resolve().parents[1]
SEMIGROUP = '''theory Semigroup<T> {
    operation (*) : T x T -> T
    axiom associative {forall a,b,c:T: (a*b)*c = a*(b*c)}
}'''


class QuantifierTests(unittest.TestCase):
    def test_typed_binders_are_local_and_distinct_from_outer_names(self):
        session = Session()
        session.execute('x:Real; P=forall x:Real: x^2>=0')
        predicate = session['P']
        self.assertIsInstance(predicate, ForAll)
        self.assertNotEqual(predicate.parameters[0], session['x'])
        self.assertNotIn(predicate.parameters[0], free_symbols(predicate))
        self.assertEqual(session.query('P'), TruthValue.TRUE)
        self.assertEqual(session.typed_ir('P').type, Type('Predicate'))
        self.assertIsNone(session.environment.get('y'))

    def test_common_mixed_and_nested_parameter_types_parse(self):
        for source in ('forall x,y:Real: x+y==y+x',
                       'forall x:Real,y:Real: x+y==y+x',
                       'forall x:Nat,y:Real: x+y==y+x',
                       'forall x:Real: forall y:Real: x+y==y+x'):
            with self.subTest(source=source):
                self.assertEqual(Session().query(source), TruthValue.TRUE)
                term = Session().resolve(source)
                self.assertEqual(Session().query(format_term(term)), TruthValue.TRUE)
                self.assertIn('ForAllExpr', format_tree(parse_expression(source)))

    def test_universal_truth_is_not_inferred_from_successful_samples(self):
        session = Session()
        self.assertEqual(session.query('forall x:Real: x>0'), TruthValue.FALSE)
        # Vanishes at every built-in real witness, but not at x=3.
        self.assertEqual(session.query('forall x:Real: x*(x-1)*(x+1)*(x-2)==0'), TruthValue.UNKNOWN)
        self.assertEqual(session.query('forall x:Real: x/x==1'), TruthValue.UNKNOWN)
        self.assertEqual(session.query('forall x:Abstract: True'), TruthValue.UNKNOWN)
        limited = Session(limits=Limits(max_quantifier_checks=1))
        self.assertEqual(limited.query('forall x:Real: x<=0'), TruthValue.UNKNOWN)

    def test_substitution_avoids_capture_and_preserves_bound_coordinates(self):
        session = Session()
        session.execute('x:Real; y:Real; P=forall x:Real: x>y')
        q = session['P']
        binder = q.parameters[0]
        mapped = session.factory.substitute(q, {session['y']: binder})
        self.assertNotEqual(mapped.parameters[0], binder)
        self.assertIn(binder, free_symbols(mapped))
        self.assertEqual(session.factory.substitute(q, {binder: session.factory.number(0)}), q)
        self.assertEqual(loads_ir(dumps_ir(mapped)), mapped)

    def test_low_level_binder_masks_matching_context_facts(self):
        factory = TermFactory()
        x = Symbol('x', SymbolKind.VARIABLE, Type('Real'))
        positive = factory.comparison('>', x, factory.number(0))
        context = Context(AssumptionSet((positive,)))
        q = ForAll((x,), positive)
        self.assertEqual(PredicateQuery(factory, context=context).query(q), TruthValue.FALSE)

    def test_bad_binders_and_non_predicates_fail_with_diagnostics(self):
        for source in ('forall x,x:Real: True', 'forall x: True', 'forall :Real: True',
                       'forall x:Real:'):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_expression(source)
        with self.assertRaises(DefinitionError):
            Session().execute('P=forall x:Real: x+1')


class TheoryTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute(SEMIGROUP)

    def implementation(self, name, operation, type_='Real', assumptions=''):
        self.session.execute(f'implementation {name} implements Semigroup<{type_}> {{operation (*) = {operation}; {assumptions}}}')
        return self.session[name]

    def test_generic_theory_has_its_own_typed_ir_and_no_kernel_axioms(self):
        theory = self.session['Semigroup']
        self.assertIsInstance(theory, Theory)
        parameter = theory.parameters[0]
        self.assertIsNotNone(parameter.identity)
        self.assertEqual(theory.operations[0].symbol.annotation, Type('Function',(parameter,parameter,parameter)))
        self.assertIsInstance(theory.axioms[0].statement.body.left, FunctionCall)
        self.assertEqual(self.session.context.assumptions.predicates, ())
        self.assertEqual(self.session.query('Semigroup.associative'), TruthValue.UNKNOWN)
        self.assertIsNone(self.session.environment.get('T'))
        self.assertIsNone(self.session.environment.get('multiply'))
        self.assertEqual(loads_ir(dumps_ir(theory)), theory)

    def test_named_operations_and_unicode_signature_product(self):
        self.session.execute('''theory Commutative<T> {
            operation combine : T × T -> T
            axiom symmetric {forall a,b:T: combine(a,b) = combine(b,a)}
        }
        implementation Add implements Commutative<Real> {operation combine=(a:Real,b:Real)=>a+b}
        ''')
        self.assertEqual(self.session['Add'].valid, TruthValue.TRUE)
        self.assertEqual(self.session.execute('Add.combine(2,3) |> simplify').output, ('5',))

    def test_polynomial_identity_and_concrete_counterexample(self):
        good = self.implementation('Good', '(a:Real,b:Real)=>a+b')
        bad = self.implementation('Bad', '(a:Real,b:Real)=>a-b')
        self.assertEqual(good.valid, TruthValue.TRUE)
        self.assertEqual(bad.valid, TruthValue.FALSE)
        result = bad.member('associative')
        a,b,c = (v.value for v in result.counterexample)
        self.assertNotEqual((a-b)-c, a-(b-c))
        self.assertTrue(good.member('associative').proofs)
        self.assertEqual(self.session.execute('Good.associative.proved; Bad.associative.disproved').output, ('True','True'))

    def test_totality_is_checked_even_without_axioms(self):
        self.session.execute('''theory Operation<T> {operation f:T -> T}
            implementation Partial implements Operation<Real> {operation f=(x:Real)=>1/x}
        ''')
        value=self.session['Partial']
        self.assertEqual(value.valid, TruthValue.FALSE)
        self.assertEqual(value.member('_total_f').counterexample[0].value, 0)

    def test_totality_does_not_trust_cancellation_or_constant_zero(self):
        for operation in ('(a:Real,b:Real)=>a/b','(a:Real,b:Real)=>0*(a/b)',
                          '(a:Real,b:Real)=>a/a', '(a:Real,b:Real)=>a^0'):
            with self.subTest(operation=operation):
                value=self.implementation('Case'+str(len(self.session.environment.definitions)),operation)
                self.assertEqual(value.valid, TruthValue.FALSE)
                self.assertEqual(value.member('_total_multiply').status, 'disproved')

    def test_assumed_and_unknown_are_not_proved(self):
        self.session.execute('combine:Function<Real,Real,Real>')
        unknown=self.implementation('UnknownCase','combine')
        assumed=self.implementation('AssumedCase','combine',assumptions='assume associative')
        self.assertEqual(unknown.member('associative').status,'unknown')
        self.assertEqual(assumed.member('associative').status,'assumed')
        self.assertEqual(assumed.valid, TruthValue.UNKNOWN)
        self.assertEqual(self.session.execute('AssumedCase.associative.proved').output,('False',))
        self.assertEqual(self.session.context.assumptions.predicates,())
        self.assertEqual(loads_ir(dumps_ir(assumed)),assumed)

    def test_false_and_unknown_assumption_names_are_rejected_atomically(self):
        for assumptions, operation in (('assume associative','(a:Real,b:Real)=>a-b'),
                                       ('assume missing','(a:Real,b:Real)=>a+b'),
                                       ('assume associative; assume associative','(a:Real,b:Real)=>a+b')):
            with self.subTest(assumptions=assumptions), self.assertRaises(DefinitionError):
                self.implementation('Rejected',operation,assumptions=assumptions)
            self.assertIsNone(self.session.environment.get('Rejected'))

    def test_signatures_check_arity_closure_and_exact_member_set(self):
        for body in ('', 'operation (*)=(a:Real)=>a',
                     'operation (*)=(a:Real,b:Real)=>a>b',
                     'operation (*)=(a:Nat,b:Nat)=>a+b',
                     'operation (*)=(a:Real,b:Real)=>a+b; const extra=0',
                     'operation (*)=(a:Real,b:Real)=>a+b; operation (*)=(a:Real,b:Real)=>a*b'):
            with self.subTest(body=body), self.assertRaises(DefinitionError):
                self.session.execute(f'implementation Invalid implements Semigroup<Real> {{{body}}}')
        for type_ in ('Semigroup', 'Semigroup<Real,Real>', 'Semigroup<3>', 'Missing<Real>'):
            with self.subTest(type_=type_), self.assertRaises(DefinitionError):
                self.session.execute(f'implementation Invalid implements {type_} {{operation (*)=(a:Real,b:Real)=>a+b}}')

    def test_generic_types_and_lexical_scopes_do_not_leak(self):
        self.session.execute('''namespace Other {
            theory Semigroup<T> {operation (*) : T x T -> T; axiom reflexive {forall a:T: a=a}}
        }''')
        outer=self.session['Semigroup'].parameters[0]
        inner=self.session.resolve('Other.Semigroup').parameters[0]
        self.assertNotEqual(outer,inner)
        good=self.implementation('Addition','(a,b)=>a+b')
        self.assertEqual(good.valid,TruthValue.TRUE)

    def test_multitype_parameters_and_nested_forall(self):
        self.session.execute('''theory PairAction<T,K> {
            operation act:T x K -> T
            const identity:K
            axiom unit {forall a:T: act(a,identity)=a}
        }
        implementation Scale implements PairAction<Real,Nat> {
            operation act=(x:Real,k:Nat)=>x*k
            const identity=1
        }''')
        self.assertEqual(self.session['Scale'].valid,TruthValue.TRUE)
        self.assertEqual(loads_ir(dumps_ir(self.session['Scale'])),self.session['Scale'])

    def test_bad_theory_definitions_are_rejected(self):
        sources = (
            'theory Bad<T,T> {operation f:T -> T}',
            'theory Bad<Real> {operation f:Real -> Real}',
            'theory Bad<T> {const zero:T=0}',
            'theory Bad<T> {operation f:T -> T; operation f:T -> T}',
            'theory Bad<T> {operation (*) : T -> T}',
            'theory Bad<T> {operation f:Undeclared -> Undeclared}',
            'theory Bad<T> {const valid:T}',
            'theory Bad<T> {axiom absent}',
            'theory Bad<T> {axiom invalid {forall a:T: a}}',
            'theory Bad<T> {operation f:T -> T; axiom invalid {forall a:T: a*a=a}}',
        )
        for source in sources:
            with self.subTest(source=source), self.assertRaises((ParseError,DefinitionError)):
                self.session.execute(source)
            self.assertIsNone(self.session.environment.get('Bad'))

    def test_axioms_cannot_capture_unrelated_symbolic_facts(self):
        self.session.execute('x:Real')
        with self.assertRaises(DefinitionError):
            self.session.execute('theory Bad<T> {axiom outside {x>0}}')
        with self.assertRaises(DefinitionError):
            self.session.execute('assuming {x>0} {implementation Conditional implements Semigroup<Real> {operation (*)=(a:Real,b:Real)=>a+b}}')

    def test_library_groups_and_rings_use_general_contracts(self):
        self.session.execute('''import std.theories {Monoid,Group,Ring,Field}
            implementation Additive implements Group<Real> {
                operation (*)=(a:Real,b:Real)=>a+b
                operation inverse=(a:Real)=>-a
                const identity=0
            }
            implementation Numbers implements Ring<Real> {
                operation (+)=(a:Real,b:Real)=>a+b
                operation (*)=(a:Real,b:Real)=>a*b
                operation (-)=(a:Real)=>-a
                const zero=0
                const one=1
            }''')
        self.assertEqual(self.session['Additive'].valid,TruthValue.TRUE)
        self.assertEqual(self.session['Numbers'].valid,TruthValue.TRUE)
        self.assertIsInstance(self.session['Field'],Theory)

    def test_verified_basis_coordinates_certify_quaternion_ring(self):
        self.session=Session()
        self.session.execute_file(ROOT/'examples'/'theories.math')
        ring=self.session['QuaternionRing']
        self.assertEqual(ring.valid,TruthValue.TRUE)
        self.assertTrue(ring.member('distributive').proofs)
        self.assertEqual(loads_ir(dumps_ir(ring)),ring)
        self.assertEqual(self.session.execute('QuaternionRing.multiply(0,Quaternion.i) |> normalize').output,('0',))

    def test_algebra_counterexamples_keep_their_presentation(self):
        self.session.execute('''import std.quaternion {Quaternion}
            theory Commutative<T> {operation (*) : T x T -> T; axiom commutative {forall a,b:T:a*b=b*a}}
            implementation Quaternions implements Commutative<Quaternion> {operation (*)=(a:Quaternion,b:Quaternion)=>a*b}
        ''')
        result=self.session['Quaternions']
        self.assertEqual(result.valid,TruthValue.FALSE)
        self.assertEqual(loads_ir(dumps_ir(result)),result)
        property_ = result.member('commutative')
        self.assertEqual(loads_ir(dumps_ir(property_)),property_)

    def test_limits_fail_without_partial_definitions(self):
        limited=Session(limits=Limits(max_nodes=4))
        with self.assertRaises(DefinitionError):
            limited.execute(SEMIGROUP)
        self.assertIsNone(limited.environment.get('Semigroup'))


class TheoryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.session=Session()
        self.session.execute(SEMIGROUP+'''
            implementation Good implements Semigroup<Real> {operation (*)=(a:Real,b:Real)=>a+b}
            implementation Bad implements Semigroup<Real> {operation (*)=(a:Real,b:Real)=>a-b}
        ''')

    def reject(self, value):
        with self.assertRaises(SerializationError):
            loads_ir(dumps_ir(value))

    def test_reader_checks_certificates_without_calling_search(self):
        good=self.session['Good']
        with patch('mathlang.theories.ProofSearch.equality', side_effect=AssertionError('search must not run')):
            restored=loads_ir(dumps_ir(good))
        self.assertEqual(restored,good)

    def test_forged_proved_status_missing_proof_and_wrong_goal_are_rejected(self):
        bad=self.session['Bad'].member('associative')
        good=self.session['Good'].member('associative')
        self.reject(replace(bad,status='proved',method='polynomial',counterexample=()))
        self.reject(replace(good,proofs=()))
        self.reject(replace(bad,status='proved',method='polynomial',proofs=good.proofs,counterexample=()))
        self.reject(replace(good,method='domain',proofs=()))
        self.reject(replace(bad,status='assumed',method='assumption',counterexample=()))

    def test_changed_bindings_removed_obligations_and_counterexamples_are_rejected(self):
        good,bad=self.session['Good'],self.session['Bad']
        self.reject(replace(good,bindings=bad.bindings))
        self.reject(replace(good,properties=good.properties[:-1]))
        result=bad.member('associative')
        self.reject(replace(result,counterexample=tuple(self.session.factory.number(0) for _ in range(3))))
        self.reject(replace(result,counterexample=(self.session.resolve('1/2'),)))

    def test_saved_modules_keep_imported_contracts_and_callable_operations(self):
        self.session=Session()
        self.session.execute_file(ROOT/'examples'/'theories.math')
        module=loads_ir(dumps_ir(self.session.export_module()))
        fresh=Session()
        result=fresh.kernel.evaluate(fresh.factory.call(module.member('Addition').member('multiply'),
                                                      (fresh.factory.number(3),fresh.factory.number(4))))
        self.assertEqual(format_term(fresh.kernel.transform('simplify',result)),'7')
        self.assertEqual(json.loads(dumps_ir(module))['version'],7)

    def test_version_four_calculus_still_loads(self):
        self.session.execute('x:Real')
        value=self.session.resolve('integrate(x,0,1)')
        data=json.loads(dumps_ir(value))
        data['version']=4
        self.assertEqual(loads_ir(json.dumps(data)),value)
        data=json.loads(dumps_ir(self.session['Good']))
        data['version']=4
        with self.assertRaises(SerializationError):
            loads_ir(json.dumps(data))


class TheoryIDETests(unittest.TestCase):
    def test_cli_example_and_semantic_diagnostics(self):
        path=ROOT/'examples'/'theories.math'
        result=subprocess.run([sys.executable,'-m','mathlang','--file',str(path)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(LanguageService(ROOT).semantic_diagnostics(path.read_text(encoding='utf-8'),path=path),[])

    def test_completion_property_inspection_and_rollback(self):
        service=LanguageService(ROOT)
        source=SEMIGROUP+'\nimplementation Add implements Semigroup<Real> {operation (*)=(a:Real,b:Real)=>a+b}'
        self.assertIn('theory',service.completions('the'))
        self.assertIn('Add',service.completions('Add',source=source))
        service.execute(source)
        self.assertIn('Add.associative',service.completions('Add.'))
        self.assertEqual(service.properties()[0][0],'Add')
        self.assertEqual(service.properties()[0][1].valid,TruthValue.TRUE)
        service.execute_repl('temporary=1; missing_name')
        self.assertEqual(service.properties()[0][0],'Add')
        service.execute('1')
        self.assertEqual(service.properties(),())

    def test_mathtext_renders_quantifier_and_annotations(self):
        try:
            from matplotlib.mathtext import MathTextParser
        except ImportError:
            self.skipTest('matplotlib is not installed')
        value=Session().resolve('forall x,y:Real: x+y==y+x')
        latex=format_latex(value)
        self.assertIn(r'\forall',latex)
        MathTextParser('agg').parse('$'+latex+'$',dpi=100)
