import math
import unittest
from pathlib import Path
import tempfile

from mathlang.ide.language_service import LanguageService
from mathlang.ide.latex import format_latex
from mathlang.ide.plotting import evaluate_numeric
from mathlang.session import Session


class LanguageServiceTests(unittest.TestCase):
    def test_syntax_diagnostic_has_source_range(self):
        service = LanguageService()
        diagnostics = service.syntax_diagnostics("const x = (")
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].phase, "syntax")
        self.assertGreaterEqual(diagnostics[0].end, diagnostics[0].start)

    def test_semantic_diagnostic_is_non_mutating(self):
        service = LanguageService()
        diagnostics = service.semantic_diagnostics("x + 1")
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("Undefined name", diagnostics[0].message)
        # A subsequent real execution remains independent from analysis.
        service.execute_repl("const x = 2")
        self.assertEqual(service.execute_repl("normalize(x + 1)")[0].text, "3")


    def test_multi_argument_print_produces_one_preview_item_per_value(self):
        service = LanguageService()
        items = service.execute("print(1, 2, 3)")
        self.assertEqual([item.text for item in items], ["1", "2", "3"])
        self.assertTrue(all(item.kind == "math" for item in items))
        self.assertTrue(all(item.latex is not None for item in items))
        # The text console keeps print's original single-line behaviour.
        self.assertEqual(items[0].console_text, "1 2 3")
        self.assertTrue(items[0].show_in_console)
        self.assertTrue(all(not item.show_in_console for item in items[1:]))

    def test_latex_renderer(self):
        session = Session()
        term = session.resolve("sin(x^2) / 3") if False else None
        session.execute("variable x:Real")
        term = session.resolve("sin(x^2) / 3")
        rendered = format_latex(term)
        self.assertIn(r"\frac", rendered)
        self.assertIn(r"\sin", rendered)

    def test_numeric_evaluation_and_plot(self):
        service = LanguageService()
        service.execute_repl("variable x:Real")
        term = service.resolve_expression("sin(x)")
        self.assertAlmostEqual(evaluate_numeric(term, {"x": math.pi / 2}), 1.0, places=10)
        spec = service.plot("sin(x)", "x", -1, 1, points=11)
        self.assertEqual(len(spec.series[0].x), 11)
        self.assertEqual(len(spec.series[0].y), 11)


if __name__ == "__main__":
    unittest.main()

class LatexCompilerTests(unittest.TestCase):
    def test_missing_tectonic_is_reported_cleanly(self):
        from unittest.mock import patch
        from mathlang.ide.latex_compile import LatexCompilerUnavailable, find_tectonic
        with patch("mathlang.ide.latex_compile.shutil.which", return_value=None), \
             patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(LatexCompilerUnavailable):
                find_tectonic()

class IdeRegressionTests(unittest.TestCase):
    def test_unsaved_buffer_imports_use_file_location_for_analysis_and_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root/'nested'
            nested.mkdir()
            (nested/'helper.math').write_text('module helper; const value=7', encoding='utf-8')
            path = nested/'main.math'
            path.write_text('invalid disk content', encoding='utf-8')
            service = LanguageService(root)
            source = 'import helper; helper.value'
            self.assertEqual(service.semantic_diagnostics(source, path=path), [])
            self.assertIsNone(service.runtime.environment.get('helper'))
            self.assertEqual(service.execute(source, path=path)[0].text, '7')
            self.assertEqual(service.runtime.modules.paths, (root.resolve(),))
            self.assertEqual(path.read_text(encoding='utf-8'), 'invalid disk content')

    def test_qualified_module_buffer_uses_package_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root/'pack'
            package.mkdir()
            (package/'helper.math').write_text('module pack.helper; const value=9', encoding='utf-8')
            service = LanguageService(package)
            source = 'module pack.main; import pack.helper; pack.helper.value'
            self.assertEqual(service.execute(source, path=package/'main.math')[0].text, '9')

    def test_buffer_completions_do_not_execute_or_leak_other_file_names(self):
        service = LanguageService()
        service.execute_repl('const runtime_only=2')
        source = '''const unsaved=3
namespace N {const visible=1}
function f(x:Real):Real {const local=2; return x}
import std.dual {Dual as D}
const incomplete = (
'''
        names = service.completions(source=source)
        self.assertIn('unsaved', names)
        self.assertIn('N.visible', names)
        self.assertIn('D', names)
        self.assertIn('$alpha', names)
        self.assertNotIn('runtime_only', names)
        self.assertNotIn('local', names)
        self.assertNotIn('x', names)
        self.assertEqual(service.runtime.modules.cache, {})
        self.assertIsNone(service.runtime.environment.get('unsaved'))
        self.assertIn('runtime_only', service.completions('runtime'))

    def test_runtime_namespace_and_algebra_member_completion(self):
        service = LanguageService()
        service.execute_repl('import std.dual {Dual}; namespace N {const value=2}')
        self.assertIn('Dual.ε', service.completions('Dual.'))
        self.assertEqual(service.completions('N.v'), ('N.value',))

    def test_inspection_uses_buffer_prefix_without_changing_runtime(self):
        service = LanguageService()
        service.execute_repl('const preserved=5')
        result = service.inspect_expression('f(2)', source='function f(x:Real):Real {return x+1}')
        self.assertIn('FunctionCall : Real', result)
        self.assertIn('Embed<Nat, Real>', result)
        self.assertIsNone(service.runtime.environment.get('f'))
        self.assertEqual(service.execute_repl('preserved')[0].text, '5')

    def test_plots_respect_builtin_identity_and_reject_unknown_parameters(self):
        service = LanguageService()
        service.execute_repl('sin:Function<Real,Real>; x:Real; a:Real')
        with self.assertRaisesRegex(ValueError, 'not numerically plottable'):
            service.plot('sin(x)', 'x', -1, 1)
        with self.assertRaisesRegex(ValueError, 'parameters'):
            service.plot('a*x', 'x', -1, 1)

    def test_plot_domain_holes_and_extreme_ranges(self):
        service = LanguageService()
        plot = service.plot('x^(1/2)', 'x', -1, 1, points=3)
        self.assertTrue(math.isnan(plot.series[0].y[0]))
        self.assertEqual(plot.series[0].y[1:], (0, 1))
        plot = service.plot('x', 'x', -1e308, 1e308, points=3)
        self.assertEqual(plot.series[0].x, (-1e308, 0, 1e308))
        for points in (True, 1, 2.5, 10_001):
            with self.assertRaisesRegex(ValueError, 'points'):
                service.plot('x', 'x', 0, 1, points=points)
        self.assertEqual(service.plot('$alpha', '$alpha', 0, 1, points=2).series[0].y, (0, 1))

    def test_plot_shared_dag_and_zero_to_zero(self):
        from mathlang import TermFactory
        from mathlang.ide.plotting import evaluate_numeric
        factory = TermFactory()
        term = factory.number(1)
        for _ in range(200):
            term = factory.binary('+', term, term)
        self.assertEqual(evaluate_numeric(term, {}), float(2**200))
        with self.assertRaises(ValueError):
            evaluate_numeric(factory.binary('^', factory.number(0), factory.number(0)), {})

    def test_latex_preserves_distinct_names_and_user_function_identity(self):
        session = Session()
        session.execute('alpha:Real; $alpha:Real; name:Real; $name:Real; sqrt:Function<Real,Real>')
        self.assertNotEqual(format_latex(session['alpha']), format_latex(session['$alpha']))
        self.assertNotEqual(format_latex(session['name']), format_latex(session['$name']))
        self.assertNotIn(r'\sqrt', format_latex(session.resolve('sqrt(2)')))

    def test_latex_numeric_products_and_negative_power_bases(self):
        session = Session()
        for expression in ('2*2', '2*(-3)', '2*normalize(-3)'):
            self.assertIn(r'\cdot', format_latex(session.resolve(expression)))
        for expression in ('2*(-3)', '2*normalize(-3)', 'normalize(-2)^2'):
            self.assertIn(r'\left(', format_latex(session.resolve(expression)))

    def test_proof_results_are_text_not_fake_latex(self):
        service = LanguageService()
        source = """
algebra Dual over Real {
    generators {e}
    relations {e^2 = 0}
    basis {1, e}
    multiplication bilinear
}
with Dual {
    prove e^2 = 0
}
"""
        items = service.execute(source)
        proof_items = [item for item in items if "ProofResult" in item.text]
        self.assertTrue(proof_items)
        self.assertTrue(all(item.kind == "text" for item in proof_items))
        self.assertTrue(all(item.latex is None for item in proof_items))

    def test_all_examples_are_safe_for_ide_analysis_and_math_preview(self):
        from pathlib import Path
        try:
            from matplotlib.mathtext import MathTextParser
        except ImportError:
            self.skipTest("matplotlib is not installed")

        parser = MathTextParser("agg")
        root = Path(__file__).resolve().parents[1]
        for path in sorted((root / "examples").rglob("*.math")):
            source = path.read_text(encoding="utf-8")
            with self.subTest(example=path.name):
                service = LanguageService(root)
                self.assertEqual(service.semantic_diagnostics(source, path=path), [])
                for item in service.execute(source, path=path):
                    if item.latex:
                        parser.parse("$" + item.latex + "$", dpi=100)

    def test_predicate_latex_preserves_grouping_and_renders_in_mathtext(self):
        session = Session()
        session.execute('x:Real; y:Real')
        sources = ('x<=0 or x>1 and not y==0', 'not (x==0 or y!=1)',
                   '(x>0)==(y>=0)', 'x+x===2*x', 'domain(1/x)',
                   'True', 'False', 'Unknown')
        rendered = [format_latex(session.resolve(source)) for source in sources]
        self.assertIn(r'\neg \left(', rendered[1])
        self.assertIn(r'\left(', rendered[2])
        self.assertIn(r'\mathrm{===}', rendered[3])
        try:
            from matplotlib.mathtext import MathTextParser
        except ImportError:
            self.skipTest('matplotlib is not installed')
        parser = MathTextParser('agg')
        for source, latex in zip(sources, rendered):
            with self.subTest(source=source):
                parser.parse('$'+latex+'$', dpi=100)
