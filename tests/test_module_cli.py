import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class ModuleCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def run_cli(self, *args, source=None):
        return subprocess.run([sys.executable, '-m', 'mathlang', *map(str, args)],
                              input=source, capture_output=True, text=True, encoding='utf-8',
                              cwd=self.root, env=dict(os.environ, PYTHONPATH=str(PROJECT)))

    def test_multifile_example_from_another_directory(self):
        result = self.run_cli('--file', PROJECT/'examples/modules/main.math')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith('25\n-2\n'))
        self.assertIn('ProofResult: proved', result.stdout)
        self.assertIn('O(x^5)', result.stdout)

    def test_compile_check_load_and_compiled_only_import(self):
        source = self.root/'geometry.math'
        source.write_text('module geometry; namespace Plane {norm(x,y)=x^2+y^2}', encoding='utf-8')
        path = self.root/'geometry.mathir'
        result = self.run_cli('--compile', source, '-o', path)
        self.assertEqual(result.returncode, 0, result.stderr)
        source.unlink()
        result = self.run_cli('--check-ir', path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('IR verified', result.stdout)
        result = self.run_cli('--load', path, '--run', 'normalize(geometry.Plane.norm(3,4))')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '25\n')
        result = self.run_cli('-I', self.root, '--run', 'import geometry; normalize(geometry.Plane.norm(5,12))')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '169\n')

    def test_failed_compile_preserves_existing_output_and_reports_import_file(self):
        source = self.root/'broken.math'
        source.write_text('module broken; import absent', encoding='utf-8')
        target = self.root/'keep.mathir'
        target.write_text('existing contents', encoding='utf-8')
        result = self.run_cli('--compile', source, '-o', target)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(target.read_text(encoding='utf-8'), 'existing contents')
        result = self.run_cli('--check-ir', target)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)

    def test_repl_saving_loading_and_recovering(self):
        path = self.root/'saved module.mathir'
        result = self.run_cli('--repl', source=f'module saved\nf(x)=x^2\n:save {path}\n:quit\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(path.exists())
        result = self.run_cli('--repl', source=f':load {path}\n:modules\nnormalize(saved.f(3))\n:load missing.mathir\nnormalize(saved.f(4))\n:quit\n')
        self.assertEqual(result.returncode, 0)
        self.assertIn('9\n', result.stdout)
        self.assertTrue(result.stdout.endswith('16\n'))
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
