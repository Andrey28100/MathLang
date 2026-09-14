import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class SymbolsAndTypesCliTests(unittest.TestCase):
    def run_cli(self, *args, source=None):
        return subprocess.run([sys.executable, '-m', 'mathlang', *map(str,args)],
                              input=source, capture_output=True, text=True, encoding='utf-8', cwd=PROJECT)

    def test_example_with_dollar_symbols_and_typed_functions(self):
        result = self.run_cli('--file', PROJECT/'examples/symbols_and_types.math')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('sin(α*θ)', result.stdout)
        self.assertIn('4*ε + 1', result.stdout)
        self.assertIn('25\n5\nA*B\n', result.stdout)

    def test_type_errors_roll_back_prints_and_repl_recovers(self):
        result = self.run_cli('--run','print(1); function f(n:Nat):Nat {return n+1}; f(-2)')
        self.assertEqual(result.returncode,1)
        self.assertEqual(result.stdout,'')
        self.assertIn('requires Nat',result.stderr)
        self.assertNotIn('Traceback',result.stderr)
        result = self.run_cli('--repl',source='variable $alpha:Real\n:type $alpha\nf=(x:Real,y:Real)=>x+y\nf(1)\nf(2,3) |> normalize\n:quit\n')
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout,'Real\n5\n')
        self.assertIn('Expected 2 arguments',result.stderr)

    def test_compiled_typed_contracts_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'typed.mathir'
            source=Path(directory)/'typed.math'
            source.write_text('module typed; function f($alpha:Nat):Nat {return $alpha^2}',encoding='utf-8')
            result=self.run_cli('--compile',source,'-o',target)
            self.assertEqual(result.returncode,0,result.stderr)
            result=self.run_cli('--load',target,'--run','normalize(typed.f(3))')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'9\n')
            result=self.run_cli('--load',target,'--run','typed.f(-3)')
            self.assertEqual(result.returncode,1)
            self.assertIn('requires Nat',result.stderr)


if __name__ == '__main__':
    unittest.main()
