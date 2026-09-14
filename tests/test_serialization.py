from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from mathlang import (Session, Limits, SerializationError, TermFactory, Symbol, SymbolKind,
                      Type, dumps_ir, loads_ir, save_ir, load_ir, check_proof, format_term)


class SerializationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_exact_dag_sharing_and_deep_graph(self):
        factory = TermFactory()
        x = Symbol('x', SymbolKind.VARIABLE, Type('Real'))
        value = factory.binary('+', x, factory.number('0.125'))
        for _ in range(1100):
            value = factory.binary('*', value, value)
        text = dumps_ir(value)
        self.assertLess(len(text), 200_000)
        restored = loads_ir(text)
        for _ in range(1100):
            self.assertIs(restored.left, restored.right)
            restored = restored.left
        self.assertEqual(restored.right.value.numerator, 1)
        self.assertEqual(restored.right.value.denominator, 8)
        self.assertEqual(restored.left.identity, x.identity)

    def test_function_calculus_series_and_rules_survive_without_source(self):
        session = Session()
        session.execute('''module demo
        parameter x:Real
        const a=3
        f(t)=a*t^2
        slope(t)=derivative(sin(t),t)
        D=derivative(x)
        s=series(exp(x),x=0,order=5)
        rule double {t+t -> 2*t}
        delayed(t)=rewrite(t+t) using double
        ''')
        path = self.root / 'demo.mathir'
        session.save_module(path)
        restored = Session()
        restored.load_module(path)
        result = restored.execute('''with demo {
            normalize(f(2))
            simplify(slope(0))
            simplify(D(x^3))
            s
            normalize(delayed(7))
            rewrite(x+x)
        }''')
        self.assertEqual(result.output[0:3], ('12', '1', '3*x^2'))
        self.assertIn('O(x^5)', result.output[3])
        self.assertEqual(result.output[4:], ('14', '2*x'))
        self.assertIs(restored.resolve('demo.x'), restored.resolve('demo.s').variable)

    def test_algebra_proofs_and_namespace_registration(self):
        session = Session()
        session.execute_file(Path(__file__).resolve().parents[1] / 'examples/quaternions.math')
        module = loads_ir(dumps_ir(session.export_module('quaternions')))
        proof = module.member('H').member('associativity_proof')
        self.assertTrue(check_proof(proof.proof))
        path = self.root / 'quaternions.mathir'
        save_ir(module, path)
        target = Session()
        target.load_module(path, alias='q')
        target.load_module(path, alias='again')
        self.assertIs(target['q'], target['again'])
        self.assertEqual(target.execute('normalize(q.H.i*q.H.j)').output, ('k',))
        second = Session(target.environment)
        self.assertEqual(second.execute('normalize(q.H.j*q.H.i)').output, ('-k',))

    def test_compiled_only_import_and_transitive_identity(self):
        (self.root / 'dep.math').write_text('module dep; algebra C over Real {generators {i}; relations {i^2=-1}}', encoding='utf-8')
        session = Session(module_paths=(self.root,))
        session.execute('module main; import dep {C}; z=C.i')
        session.save_module(self.root / 'main.mathir')
        (self.root / 'dep.math').unlink()
        target = Session(module_paths=(self.root,))
        result = target.execute('import main; import dep; normalize(main.z*dep.C.i)')
        self.assertEqual(result.output, ('-1',))
        self.assertIs(target.resolve('main.z'), target.resolve('dep.C.i'))

    def test_data_corruption_version_fields_tags_types_and_references(self):
        original = json.loads(dumps_ir(TermFactory().number(2)))
        variants = []
        for key, value in (('version', 999), ('version', True), ('format', 'pickle'), ('root', {'ref': 99})):
            item = json.loads(json.dumps(original))
            item[key] = value
            variants.append(item)
        for record in ({'tag': '__import__', 'fields': {}},
                       {'tag': 'Number', 'fields': {'value': 2}},
                       {'tag': 'Number', 'fields': {'value': {'ref': 0}}},
                       {'tag': 'Number', 'fields': {'value': {'rational': ['1','0']}}}):
            item = json.loads(json.dumps(original))
            item['nodes'][0] = record
            variants.append(item)
        for item in variants:
            with self.subTest(item=item), self.assertRaises(SerializationError):
                loads_ir(json.dumps(item))
        for text in ('{"format":1,"format":2}', '[]', '{}', 'NaN', '[1.2]', '{'):
            with self.subTest(text=text), self.assertRaises(SerializationError):
                loads_ir(text)

    def test_tampered_proofs_results_and_algebra_reductions_rejected(self):
        session = Session()
        session.execute('algebra C over Real {generators {i}; relations {i^2=-1}; basis {1,i}; multiplication bilinear}')
        result = session.execute('with C {prove i^2=-1}').values[0]
        self.assertTrue(check_proof(loads_ir(dumps_ir(result.proof))))
        forged = replace(result.proof, left_normal=session.factory.number(17))
        for value in (forged, replace(result, left_normal=session.factory.number(17)),
                      replace(session['C'], reductions=()), replace(result, proof=None)):
            with self.subTest(value=type(value).__name__), self.assertRaises(SerializationError):
                loads_ir(dumps_ir(value))

    def test_ir_limits(self):
        value = TermFactory().binary('+', TermFactory().number(1), TermFactory().number(2))
        text = dumps_ir(value)
        for limits in (Limits(max_ir_bytes=10), Limits(max_nodes=1)):
            with self.subTest(limits=limits), self.assertRaises(SerializationError):
                loads_ir(text, limits=limits)
            with self.subTest(limits=limits), self.assertRaises(SerializationError):
                dumps_ir(value, limits=limits)
        with self.assertRaises(SerializationError):
            loads_ir(dumps_ir(TermFactory().number(1000)), limits=Limits(max_integer_bits=5))

    def test_package_views_and_selective_dependencies_survive_saving(self):
        session = Session()
        session.execute('module demo; import std.analysis; import std.analysis.calculus; import std.algebra {Complex}')
        path = self.root/'demo.mathir'
        session.save_module(path)
        target = Session()
        target.load_module(path)
        result = target.execute('import std.complex; normalize(demo.Complex.i*std.complex.Complex.i)')
        self.assertEqual(result.output, ('-1',))
        inherited = Session(target.environment)
        inherited.execute('import std.complex')
        self.assertIs(inherited.resolve('std.complex.Complex'), target.resolve('demo.Complex'))

    def test_property_certificate_must_certify_the_claimed_algebra_property(self):
        session = Session()
        session.execute('import std.quaternion {Quaternion}')
        algebra = session['Quaternion']
        forged = replace(algebra, properties=(('commutativity_proof', algebra.member('associativity_proof')),))
        with self.assertRaisesRegex(SerializationError, 'matching certificate'):
            loads_ir(dumps_ir(forged))

    def test_failed_load_preserves_existing_session_and_file(self):
        session = Session()
        session.execute('module data; const n=2')
        path = self.root / 'data.mathir'
        session.save_module(path)
        target = Session()
        target.execute('const data=7')
        with self.assertRaises(ValueError):
            target.load_module(path)
        self.assertEqual(target['data'].value, 7)
        self.assertFalse(target.modules.cache)
        self.assertFalse(target.kernel.algebras)
        original = path.read_bytes()
        with self.assertRaises(SerializationError):
            save_ir(object(), path)
        self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
