from pathlib import Path
import tempfile
import unittest

from mathlang import DefinitionError, Limits, ParseError, Session, check_proof, format_term, parse_program
from mathlang.modules import Namespace


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.session = Session(module_paths=(self.root,))

    def source(self, name, source):
        path = self.root.joinpath(*name.split('.')).with_suffix('.math')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')

    def test_plain_aliased_selective_and_repeated_import(self):
        self.source('geometry', 'module geometry; const a=3; square(x)=a*x^2; parameter t:Real')
        result = self.session.execute('import geometry; import geometry as g; import geometry {square as sq, t,}; import geometry; normalize(sq(2))')
        self.assertEqual(result.output, ('12',))
        self.assertIs(self.session['geometry'], self.session['g'])
        self.assertIs(self.session['t'], self.session.resolve('g.t'))
        self.assertIsNone(self.session.environment.get('a'))
        self.assertEqual(len(self.session.modules.cache), 1)

    def test_dotted_modules_nested_namespaces_and_qualified_annotations(self):
        self.source('lib.one', 'module lib.one; namespace inner {const v=2}')
        self.source('lib.two', 'module lib.two; algebra C over Real {generators {i}; relations {i^2=-1}}')
        result = self.session.execute('''import lib.one
        import lib.two
        with lib.one.inner {v}
        with lib.two.C {normalize(i^2)}
        variable z:lib.two.C
        ''')
        self.assertEqual(result.output, ('2', '-1'))
        self.assertEqual(self.session['z'].annotation, self.session.resolve('lib.two.C').type)
        self.assertIsNone(self.session.environment.get('i'))

    def test_module_isolation_and_closed_function_capture(self):
        self.source('good', 'const a=2; f(x)=a*x')
        self.source('bad', 'f(x)=secret*x')
        self.session.execute('const a=99; const secret=5; import good')
        self.assertEqual(format_term(self.session.resolve('normalize(good.f(3))')), '6')
        with self.assertRaisesRegex(DefinitionError, 'secret'):
            self.session.execute('import bad')
        self.assertNotIn('bad', self.session.modules.cache)

    def test_cycle_missing_member_conflict_and_rollback(self):
        self.source('a', 'import b')
        self.source('b', 'import a')
        with self.assertRaisesRegex(DefinitionError, 'Cyclic import: a -> b -> a'):
            self.session.execute('const temp=1; import a')
        self.assertFalse(self.session.modules.cache)
        self.assertEqual(self.session.modules.loading, [])
        self.assertIsNone(self.session.environment.get('temp'))
        self.source('good', 'algebra C over Real {generators {i}; relations {i^2=-1}}; const n=3')
        for source in ('import good {C, absent}', 'const good=1; import good', 'import good; unknown_name'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.session.execute(source)
            self.assertFalse(self.session.kernel.algebras)
            self.assertFalse(self.session.modules.cache)
            self.assertIsNone(self.session.environment.get('good'))

    def test_declared_name_and_errors_in_import_include_file(self):
        self.source('wrong', 'module another; const n=2')
        with self.assertRaisesRegex(DefinitionError, "Expected module 'wrong'"):
            self.session.execute('import wrong')
        self.source('broken', 'const x = )')
        with self.assertRaisesRegex(DefinitionError, 'broken.math'):
            self.session.execute('import broken')

    def test_with_use_rules_and_namespace_capture(self):
        self.session.execute('''const factor=2
        namespace N {
            f(x)=factor*x
            rule double { t+t -> 2*t }
            namespace Inner {const n=5}
        }
        x:Real
        ''')
        result = self.session.execute('with N {normalize(f(3)); rewrite(x+x); Inner.n}; x+x')
        self.assertEqual(result.output, ('6', '2*x', '5', 'x + x'))
        self.assertIsNone(self.session.environment.get('f'))
        self.session.execute('use N')
        self.assertEqual(self.session.execute('normalize(f(4))').output, ('8',))
        with self.assertRaises(DefinitionError):
            self.session.execute('namespace Bad {const x=1; missing}')
        self.assertIsNone(self.session.environment.get('Bad'))

    def test_selective_rule_alias_is_active_and_shadowing_respected(self):
        self.source('rules', 'rule double {t+t -> 2*t}')
        result = self.session.execute('import rules {double as twice}; x:Real; rewrite(x+x)')
        self.assertEqual(result.output, ('2*x',))
        self.assertEqual(self.session.execute('rewrite(x+x) using twice').output, ('2*x',))

    def test_limits_and_invalid_module_syntax(self):
        self.source('a', 'import b')
        self.source('b', 'const a=2')
        for limits in (Limits(max_modules=1), Limits(max_import_depth=1), Limits(max_module_bytes=2)):
            with self.subTest(limits=limits), self.assertRaises(DefinitionError):
                Session(module_paths=(self.root,), limits=limits).execute('import a')
        for source in ('import a {}', 'import a {x,x}', 'import a as b {x}',
                       'const a=1; module b', 'namespace A {module b}', 'module a..b',
                       'N.x=2', 'N.f(x)=x'):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_program(source)

    def test_standard_library_is_language_data_and_preserves_identities(self):
        result = self.session.execute('''import std.algebra {Complex, Dual, Quaternion}
        import std.complex as c
        import std.quaternion as q
        import std.analysis as a
        with Complex {normalize((1+i)^4)}
        with Dual {normalize((1+ε)^4)}
        normalize(q.Quaternion.i*q.Quaternion.j)
        variable x:Real
        a.limit(sin(x)/x,x -> 0)
        ''')
        self.assertEqual(result.output, ('-4', '4*ε + 1', 'k', '1'))
        self.assertIs(self.session['Complex'], self.session.resolve('c.Complex'))
        self.assertTrue(check_proof(self.session['Quaternion'].member('associativity_proof').proof))

    def test_package_and_module_import_order(self):
        self.source('pkg', 'module pkg; const x=1')
        self.source('pkg.child', 'module pkg.child; const y=2')
        for order in ('import pkg; import pkg.child; import pkg',
                      'import pkg.child; import pkg; import pkg.child'):
            with self.subTest(order=order):
                result = Session(module_paths=(self.root,)).execute(order+'; pkg.x; pkg.child.y')
                self.assertEqual(result.output, ('1', '2'))

    def test_qualified_rule_literals_and_failed_use_roll_back(self):
        self.session.execute('namespace N {const one=1}; x:Real; rule r {t+N.one -> t}')
        self.assertEqual(self.session.execute('rewrite(x+1)').output, ('x',))
        with self.assertRaises(DefinitionError):
            self.session.execute('use N; missing')
        self.assertIsNone(self.session.environment.active_namespace)

    def test_entry_file_finds_sibling_and_package_root(self):
        self.source('package.helpers', 'module package.helpers; const n=7')
        self.source('package.main', 'module package.main; import package.helpers; package.helpers.n')
        session = Session(module_paths=(self.root / 'unrelated',))
        result = session.execute_file(self.root / 'package' / 'main.math')
        self.assertEqual(result.output, ('7',))


if __name__ == '__main__':
    unittest.main()
