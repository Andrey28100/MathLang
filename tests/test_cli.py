import subprocess
import sys
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def run_cli(self, *args, source=None):
        return subprocess.run(
            [sys.executable, "-m", "mathlang", *args], input=source,
            capture_output=True, text=True, encoding="utf-8", cwd=Path(__file__).resolve().parents[1],
        )

    def test_argument(self):
        result = self.run_cli("2*x + 3*x")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("BinaryExpr(+)\n"))
        self.assertEqual(result.stdout.count("BinaryExpr(*)"), 2)

    def test_stdin(self):
        result = self.run_cli(source="i * (i + i)")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BinaryExpr(*)", result.stdout)

    def test_leading_minus(self):
        result = self.run_cli("--", "-x^2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("UnaryExpr(-)\n"))

    def test_invalid_expression(self):
        result = self.run_cli("x +")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("line 1, column 4", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_run_program_from_argument_and_stdin(self):
        source = "const c=2; variable x:Real; f=c*x+1; print(f); f^2"
        for result in (self.run_cli("--run", source), self.run_cli("--run", source=source)):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "2*x + 1\n(2*x + 1)^2\n")

    def test_run_program_file(self):
        result = self.run_cli("--file", "examples/memory.math")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("exp(a*2)*sin(2)\n", result.stdout)

    def test_file_errors(self):
        result = self.run_cli("--file", "examples/does-not-exist.math")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_failed_program_does_not_print_partial_output(self):
        result = self.run_cli("--run", "a=2; print(a); b=missing")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Undefined name 'missing'", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_repl_keeps_memory_and_recovers_after_error(self):
        result = self.run_cli("--repl", source="a=2\na\na=3; b=missing\na\n:memory\n:quit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2\n2\na = 2\n")
        self.assertIn("Undefined name 'missing'", result.stderr)

    def test_repl_line_continuation(self):
        result = self.run_cli("--repl", source="f = \\\n2 + \\\n3\nf\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2 + 3\n")

    def test_repl_incomplete_continuation(self):
        result = self.run_cli("--repl", source="f = \\\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Incomplete input", result.stderr)

    def test_expression_engine_example_file(self):
        result = self.run_cli("--file", "examples/expressions.math")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "2*x + 3*x", "5*x", "(x + 1)^3", "x^3 + 3*x^2 + 3*x + 1", "5/6",
            "1", "25", "11", "y - x", "9", "x/x",
        ])

    def test_arithmetic_error_is_diagnosed_without_partial_output(self):
        result = self.run_cli("--run", "x=1; print(x); normalize(1/0)")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Division by zero", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_algebra_examples_and_unicode_redirected_output(self):
        for path, expected in (("examples/algebras.math", "3*a^2*b*ε + a^3"),
                               ("examples/quaternions.math", "Basis checks: 64")):
            with self.subTest(path=path):
                result = self.run_cli("--file", path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertIn(expected, result.stdout)

    def test_repl_multiline_algebra_and_context(self):
        source = """algebra C over Real {
generator i
relation {
i^2=-1
}
basis {1,i}
}
use C
normalize((1+i)^2)
with C {
print(normalize(i^2))
}
:quit
"""
        result = self.run_cli("--repl", source=source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2*i\n-1\n")
        self.assertEqual(result.stderr, "")

    def test_repl_can_cancel_an_unfinished_block(self):
        result = self.run_cli("--repl", source="algebra A over Real {\n:cancel\n2\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2\n")
        self.assertEqual(result.stderr, "")

    def test_repl_unclosed_group_and_mismatched_delimiters(self):
        result = self.run_cli("--repl", source="algebra A over Real {\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Incomplete input", result.stderr)
        result = self.run_cli("--repl", source="(2}\n3\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "3\n")
        self.assertNotIn("Traceback", result.stderr)

    def test_failed_algebra_program_discards_proofs_and_output(self):
        source = "algebra A over Real { generator a; relation a^2=0; basis{1,a}; multiplication bilinear; prove multiplication associative }; print(2); missing"
        result = self.run_cli("--run", source)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)

    def test_analysis_example_file(self):
        result = self.run_cli("--file", "examples/analysis.math")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("60*x^2\n", result.stdout)
        self.assertIn("O(x^6)", result.stdout)
        self.assertIn("O(x^7)", result.stdout)
        self.assertIn("1\n2\n1/2\n", result.stdout)

    def test_calculus_error_discards_output_without_traceback(self):
        result = self.run_cli("--run", "x:Real; print(derivative(x^2,x)); limit(1/x,x -> 0)")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("finite", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_repl_retains_calculus_operators_and_functions(self):
        result = self.run_cli("--repl", source="x:Real\nD=derivative(x)\nf=x=>x^2\ng=D(f)\ng(3) |> simplify\nlimit(sin(x)/x,x -> 0)\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, "6\n1\n")


if __name__ == "__main__":
    unittest.main()
