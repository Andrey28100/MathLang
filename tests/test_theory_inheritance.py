from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from mathlang import (DefinitionError, Limits, ParseError, SerializationError,
                      Session, TheoryError, TheoryParent, TruthValue, Type,
                      dumps_ir, format_term, format_tree, free_symbols, loads_ir, parse_program)
from mathlang.ide.language_service import LanguageService
from mathlang.theories import Axiom, validate_theory

ROOT = Path(__file__).resolve().parents[1]
BASE = '''theory Semigroup<T> {
    operation (*) : T x T -> T
    axiom associative { forall a,b,c:T: (a*b)*c = a*(b*c) }
}
theory Monoid<T> extends Semigroup<T> {
    const identity:T
    axiom unit { forall a:T: a*identity = a and identity*a = a }
}'''
DIAMOND = BASE + '''
theory Commutative<T> extends Semigroup<T> {
    axiom commutative { forall a,b:T: a*b = b*a }
}
theory Diamond<T> extends Monoid<T>, Commutative<T> {}
implementation Addition implements Diamond<Real> {
    operation (*) = (a:Real,b:Real)=>a+b
    const identity = 0
}'''


class TheoryInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute(BASE)

    def reject(self, source):
        with self.assertRaises((DefinitionError, ParseError)):
            self.session.execute(source)
        self.assertIsNone(self.session.environment.get('Bad'))

    def test_inherited_operators_and_constants_are_available_to_local_axioms(self):
        self.session.execute('''theory Pointed<T> extends Monoid<T> {
            axiom fixed { identity*identity = identity }
        }
        implementation Add implements Pointed<Real> {
            operation (*)=(a:Real,b:Real)=>a+b; const identity=0
        }''')
        theory, implementation = self.session['Pointed'], self.session['Add']
        self.assertEqual([a.name for a in theory.axioms], ['associative', 'unit', 'fixed'])
        self.assertEqual(implementation.valid, TruthValue.TRUE)
        self.assertEqual(len(implementation.properties), 5)
        for axiom in theory.axioms:
            self.assertLessEqual(free_symbols(axiom.statement),
                                 {theory.operations[0].symbol, theory.constants[0]})
        self.assertIn('extends Monoid<T>', format_term(theory))

    def test_diamond_merges_requirements_once_and_keeps_origins(self):
        self.session = Session()
        self.session.execute(DIAMOND)
        theory = self.session['Diamond']
        self.assertEqual(len(theory.operations), 1)
        self.assertEqual(len(theory.constants), 1)
        self.assertEqual([a.name for a in theory.axioms], ['associative', 'unit', 'commutative'])
        self.assertEqual(len(self.session['Addition'].properties), 5)
        self.assertEqual(theory.origins('associative'), ('Semigroup',))
        self.assertEqual(theory.origins('_total_multiply'), ('Semigroup',))
        self.assertEqual(theory.origins('_total_identity'), ('Monoid',))
        self.assertEqual(theory.origins('commutative'), ('Commutative',))
        self.assertEqual(theory.origins('absent'), ())

    def test_independent_parents_merge_alpha_equivalent_axioms_and_signatures(self):
        self.session.execute('''theory Left<T> {
            operation f:T -> T
            axiom reflexive {forall a:T: f(a)=a}
        }
        theory Right<U> {
            operation f:U -> U
            axiom reflexive {forall other:U: f(other)=other}
        }
        theory Both<V> extends Left<V>, Right<V> {}
        implementation Identity implements Both<Real> {operation f=(x:Real)=>x}
        ''')
        theory = self.session['Both']
        self.assertEqual(len(theory.operations), 1)
        self.assertEqual(len(theory.axioms), 1)
        self.assertEqual(theory.origins('reflexive'), ('Left', 'Right'))
        self.assertEqual(self.session['Identity'].valid, TruthValue.TRUE)

    def test_reordered_and_fixed_parent_arguments_specialize_binders_and_signatures(self):
        self.session.execute('''theory Action<T,K> {
            operation act:T x K -> T; const identity:K
            axiom unit {forall a:T: act(a,identity)=a}
        }
        theory Reordered<K,T> extends Action<T,K> {}
        theory Natural<T> extends Reordered<Nat,T> {}
        implementation Scale implements Natural<Real> {
            operation act=(x:Real,k:Nat)=>x*k; const identity=1
        }''')
        natural = self.session['Natural']
        t = natural.parameters[0]
        self.assertEqual(natural.operations[0].symbol.annotation, Type('Function', (t, Type('Nat'), t)))
        self.assertEqual(natural.axioms[0].statement.parameters[0].annotation, t)
        self.assertEqual(natural.constants[0].annotation, Type('Nat'))
        self.assertEqual(self.session['Scale'].valid, TruthValue.TRUE)

    def test_nested_type_arguments_and_unused_parameters_are_preserved(self):
        self.session.execute('''theory Mapping<T> {
            operation apply:Function<T,T> x T -> T
            axiom same {forall f:Function<T,T>,a:T: apply(f,a)=apply(f,a)}
        }
        theory Vectors<T,K> extends Mapping<Vector<T,2>> {}''')
        theory = self.session['Vectors']
        vector = Type('Vector', (theory.parameters[0], 2))
        self.assertEqual(theory.operations[0].symbol.annotation,
                         Type('Function', (Type('Function', (vector, vector)), vector, vector)))
        self.assertEqual(loads_ir(dumps_ir(theory)), theory)

    def test_parent_contract_and_lexical_type_identities_are_not_mutated(self):
        original = self.session['Monoid']
        self.session.execute('''namespace Nested {
            theory Child<U> extends Monoid<U> {}
        }
        theory Sibling<T> extends Monoid<T> {}''')
        child = self.session.resolve('Nested.Child')
        self.assertIs(self.session['Monoid'], original)
        self.assertIs(child.parents[0].theory, original)
        self.assertNotEqual(child.parameters, original.parameters)
        self.assertNotEqual(child.operations[0].symbol, original.operations[0].symbol)
        self.assertNotEqual(child.operations[0].symbol, self.session['Sibling'].operations[0].symbol)
        self.assertIsNone(self.session.environment.get('U'))

    def test_conflicting_inherited_signatures_constants_and_operator_spellings_fail(self):
        sources = (
            'theory A<T>{operation f:T -> T}; theory B<T>{operation f:T -> Real}',
            'theory A<T>{const unit:T}; theory B<T>{const unit:Real}',
            'theory A<T>{operation (*) : T x T -> T}; theory B<T>{operation multiply:T x T -> T}',
            'theory A<T>{operation f:T -> T}; theory B<T>{const f:T}',
        )
        for source in sources:
            with self.subTest(source=source):
                self.reject(source + '; theory Bad<T> extends A<T>, B<T> {}')
                self.assertIsNone(self.session.environment.get('A'))

    def test_same_axiom_name_with_different_law_fails(self):
        self.reject('''theory A<T>{operation f:T -> T; axiom law{forall x:T: f(x)=x}}
            theory B<T>{operation f:T -> T; axiom law{forall x:T: f(x)=f(f(x))}}
            theory Bad<T> extends A<T>,B<T>{}''')

    def test_member_axiom_collisions_and_local_overrides_fail(self):
        for body in ('operation (*) : T x T -> T', 'const identity:T',
                     'axiom associative {forall a:T: a=a}', 'const associative:T',
                     'axiom identity {forall a:T: a=a}'):
            with self.subTest(body=body):
                self.reject('theory Bad<T> extends Monoid<T> {' + body + '}')
        self.reject('''theory A<T>{const law:T}
            theory B<T>{axiom law{forall a:T:a=a}}
            theory Bad<T> extends A<T>,B<T>{}''')

    def test_missing_non_theory_repeated_and_invalid_parent_arguments_fail(self):
        for parent in ('Missing<T>', 'Bad<T>', 'Semigroup', 'Semigroup<T,T>',
                       'Semigroup<2>', 'Semigroup<Missing>', 'Semigroup<T>,Semigroup<T>',
                       'Semigroup<T>,Semigroup<Real>', 'sin<T>'):
            with self.subTest(parent=parent):
                self.reject('theory Bad<T> extends ' + parent + ' {}')
        self.reject('''import std.quaternion {Quaternion}
            theory Bad<T> extends Semigroup<Quaternion> {}''')
        self.reject('theory Bad<T> extends Future<T> {}; theory Future<T> {}')

    def test_same_parent_under_different_arguments_can_compose_without_conflicts(self):
        self.session.execute('''theory Empty<T> {}
            theory Pair<T,U> extends Empty<T>,Empty<U> {}''')
        self.assertEqual(len(self.session['Pair'].parents), 2)

    def test_inherited_requirements_cannot_be_omitted_from_implementation(self):
        self.reject('''implementation Bad implements Monoid<Real> {
            operation (*)=(a:Real,b:Real)=>a+b
        }''')

    def test_assumptions_and_counterexamples_apply_to_inherited_axioms(self):
        self.session.execute('''combine:Function<Real,Real,Real>
            theory Child<T> extends Semigroup<T> {}
            implementation Unresolved implements Child<Real> {
                operation (*)=combine; assume associative
            }
            implementation Sub implements Child<Real> {operation (*)=(a:Real,b:Real)=>a-b}
        ''')
        unknown = self.session['Unresolved']
        self.assertEqual(unknown.valid, TruthValue.UNKNOWN)
        self.assertEqual(unknown.member('associative').status, 'assumed')
        self.assertEqual(unknown.member('_total_multiply').status, 'unknown')
        self.assertEqual(self.session['Sub'].member('associative').status, 'disproved')
        self.reject('''implementation Bad implements Child<Real> {
            operation (*)=(a:Real,b:Real)=>a-b; assume associative
        }''')
        self.assertEqual(self.session.environment.context.assumptions.predicates, ())

    def test_depth_budget_and_shared_ancestors_use_longest_path(self):
        session = Session(limits=Limits(max_theory_depth=2))
        session.execute(BASE)
        with self.assertRaisesRegex(DefinitionError, 'depth limit'):
            session.execute('theory Bad<T> extends Semigroup<T>,Monoid<T> {}')
        self.assertIsNone(session.environment.get('Bad'))
        self.assertIsNotNone(session.environment.get('Monoid'))
        with self.assertRaises(ValueError):
            Limits(max_theory_depth=0)

    def test_hierarchy_budget_and_low_level_cycle_are_checked(self):
        with self.assertRaisesRegex(TheoryError, 'size limit'):
            validate_theory(self.session['Monoid'], Limits(max_nodes=7))
        theory = replace(self.session['Semigroup'], operations=(), axioms=())
        # Only a low-level mutation can form a cycle; parsed and serialized graphs cannot.
        object.__setattr__(theory, 'parents', (TheoryParent(theory, theory.parameters),))
        with self.assertRaisesRegex(TheoryError, 'Cyclic'):
            validate_theory(theory)

    def test_multiline_parent_list_and_ast_children(self):
        source = '''theory Child<T>
            extends Monoid<T>,
                Semigroup<T>
            {;}'''
        self.session.execute(source)
        ast = parse_program(source).statements[0]
        self.assertEqual([p.name for p in ast.parents], ['Monoid', 'Semigroup'])
        self.assertEqual(ast.children[:2], ast.parents)
        self.assertIn('Monoid', format_tree(ast))


class TheoryInheritancePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute(DIAMOND)

    def reject(self, value):
        with self.assertRaises(SerializationError):
            loads_ir(dumps_ir(value))

    def test_roundtrip_keeps_shared_ancestors_and_checks_without_proof_search(self):
        value = self.session['Addition']
        with patch('mathlang.theories.ProofSearch.equality', side_effect=AssertionError('unexpected proof search')):
            restored = loads_ir(dumps_ir(value))
        self.assertEqual(restored, value)
        left, right = restored.theory.parents
        self.assertIs(left.theory.parents[0].theory, right.theory.parents[0].theory)
        self.assertEqual(restored.theory.origins('associative'), ('Semigroup',))

    def test_removed_or_changed_inherited_axioms_are_rejected(self):
        theory = self.session['Diamond']
        self.reject(replace(theory, axioms=theory.axioms[1:]))
        false_axiom = Axiom('associative', self.session.resolve('forall a:Real: a=a'))
        self.reject(replace(theory, axioms=(false_axiom, *theory.axioms[1:])))
        self.reject(replace(theory, axioms=tuple(reversed(theory.axioms))))
        self.reject(replace(theory, operations=()))
        self.reject(replace(theory, constants=()))

    def test_changed_parent_specialization_or_duplicate_parent_is_rejected(self):
        theory = self.session['Diamond']
        parent = replace(theory.parents[0], arguments=(Type('Real'),))
        self.reject(replace(theory, parents=(parent, theory.parents[1])))
        self.reject(replace(theory, parents=(*theory.parents, theory.parents[0])))
        foreign = self.session['Monoid'].parameters[0]
        self.reject(replace(theory, parents=(replace(theory.parents[0], arguments=(foreign,)),)))

    def test_removed_inherited_obligations_are_rejected(self):
        implementation = self.session['Addition']
        self.reject(replace(implementation, properties=implementation.properties[:2]))

    def test_version_five_contracts_migrate_to_parentless_theories(self):
        theory = self.session['Semigroup']
        document = json.loads(dumps_ir(theory))
        document['version'] = 5
        for record in document['nodes']:
            if record['tag'] == 'Theory':
                del record['fields']['parents']
        restored = loads_ir(json.dumps(document))
        self.assertEqual(restored, theory)
        self.assertEqual(restored.parents, ())
        self.assertEqual(json.loads(dumps_ir(restored))['version'], 7)

    def test_old_version_cannot_smuggle_inheritance_and_new_requires_parents(self):
        document = json.loads(dumps_ir(self.session['Diamond']))
        document['version'] = 5
        with self.assertRaises(SerializationError):
            loads_ir(json.dumps(document))
        document = json.loads(dumps_ir(self.session['Semigroup']))
        del document['nodes'][-1]['fields']['parents']
        with self.assertRaises(SerializationError):
            loads_ir(json.dumps(document))

    def test_loaded_module_theory_can_be_extended_in_another_session(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            self.session.save_module(Path(folder) / 'contracts.mathir', name='contracts')
            fresh = Session(module_paths=[folder])
            fresh.execute('''import contracts {Diamond}
                theory Derived<T> extends Diamond<T> {}
                implementation Add implements Derived<Real> {
                    operation (*)=(a:Real,b:Real)=>a+b; const identity=0
                }''')
            self.assertEqual(fresh['Add'].valid, TruthValue.TRUE)


class TheoryInheritanceIDETests(unittest.TestCase):
    def test_example_diagnostics_completion_and_reset(self):
        path = ROOT/'examples'/'theory_inheritance.math'
        source = path.read_text(encoding='utf-8')
        service = LanguageService(ROOT)
        self.assertEqual(service.semantic_diagnostics(source, path=path), [])
        self.assertIn('extends', service.completions('ext'))
        self.assertIn('CommutativeMonoid', service.completions('Commutative', source=source))
        service.execute(source, path=path)
        self.assertIn('Addition.associative', service.completions('Addition.'))
        self.assertIn('CommutativeMonoid.multiply', service.completions('CommutativeMonoid.'))
        properties = dict(service.properties())
        self.assertEqual(properties['AdditiveGroup'].valid, TruthValue.TRUE)
        self.assertEqual(properties['QuaternionProduct'].valid, TruthValue.FALSE)
        service.execute_repl('theory Bad<T> extends Missing<T> {}')
        self.assertEqual(dict(service.properties()), properties)
        service.execute('1')
        self.assertEqual(service.properties(), ())
