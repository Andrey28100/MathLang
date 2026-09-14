import unittest

from mathlang import ApproxNumber, DefinitionError, Session, dumps_ir, format_term, loads_ir


class NumericPipelineTests(unittest.TestCase):
    def setUp(self):
        self.s = Session()

    def test_pipeline_default_precision(self):
        value = self.s.resolve('sqrt(2) |> numeric')
        self.assertIsInstance(value, ApproxNumber)
        self.assertEqual(value.digits, 20)
        self.assertEqual(format_term(value), '≈1.4142135623730950488')

    def test_pipeline_explicit_precision(self):
        cases = {
            'sqrt(2) |> numeric(30)': '≈1.41421356237309504880168872421',
            'exp(1) |> numeric(30)': '≈2.71828182845904523536028747135',
            'sin(1) |> numeric(20)': '≈0.84147098480789650665',
            'cos(1) |> numeric(20)': '≈0.54030230586813971740',
            'tan(1) |> numeric(20)': '≈1.5574077246549022305',
            '(1/3) |> numeric(12)': '≈0.333333333333',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(format_term(self.s.resolve(source)), expected)

    def test_numeric_after_substitution_and_calculus(self):
        self.s.execute('variable x:Real')
        self.assertEqual(
            self.s.execute('sin(x)+sqrt(2) |> substitute(x=1) |> numeric(24)').output,
            ('≈2.25568454718099155545419',),
        )
        self.assertEqual(
            self.s.execute('integrate(exp(x),x,0,1) |> numeric(24)').output,
            ('≈1.71828182845904523536029',),
        )

    def test_numeric_is_explicitly_inexact_and_serializable(self):
        value = self.s.resolve('log(2) |> numeric(25)')
        self.assertIsInstance(value, ApproxNumber)
        restored = loads_ir(dumps_ir(value))
        self.assertEqual(restored, value)
        self.assertTrue(format_term(restored).startswith('≈'))

    def test_numeric_rejects_open_nonreal_and_bad_precision(self):
        self.s.execute('variable x:Real')
        for source in ('x |> numeric', 'sqrt(-1) |> numeric', 'sqrt(2) |> numeric(0)',
                       'sqrt(2) |> numeric(501)', 'sqrt(2) |> numeric(3/2)'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                self.s.execute(source)

    def test_approximate_values_survive_symbolic_storage(self):
        self.s.execute('a=sqrt(2) |> numeric(15)')
        self.assertEqual(self.s.execute('a').output, ('≈1.41421356237310',))
        self.assertEqual(self.s.execute('a |> simplify').output, ('≈1.41421356237310',))


if __name__ == '__main__':
    unittest.main()
