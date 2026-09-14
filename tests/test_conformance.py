"""Regression cases from the 0.7 specification/implementation audit."""

import unittest

from mathlang import (DefinitionError, Embed, FunctionCall, Session, Type,
                      format_typed_ir)


class TypedIRConformanceTests(unittest.TestCase):
    def test_transformation_contracts_are_checked_before_evaluation(self):
        for expression in ('simplify()', 'normalize(1,2)', 'polynomial()', 'polynomial(2)'):
            with self.subTest(expression=expression), self.assertRaises(DefinitionError):
                Session().typed_ir(expression)

    def test_arithmetic_inspection_matches_inference_across_exact_constants(self):
        session = Session()
        for left in ('0', '2', '-3', '1/2', '-1/2'):
            for right in ('0', '2', '-3', '1/2', '-1/2'):
                for op in ('+', '-', '*', '/', '^'):
                    expression = f'({left}){op}({right})'
                    with self.subTest(expression=expression):
                        self.assertEqual(session.typed_ir(expression).type, session.type_of(expression))

    def test_constant_result_refinement_does_not_narrow_operands(self):
        session = Session()
        for source in ('-2+3', '(1/2)*2', '(-1)^2', '4/2', '2-1'):
            with self.subTest(source=source):
                ir = session.typed_ir(source)
                self.assertEqual(ir.type, Type('Nat'))
                self.assertTrue(format_typed_ir(ir))
        ir = session.typed_ir('-2+3')
        self.assertEqual(ir.children[1].type, Type('Integer'))
        ir = session.typed_ir('(1/2)*2')
        self.assertEqual(ir.children[1].type, Type('Rational'))

    def test_elementary_builtin_overloads_have_consistent_call_signatures(self):
        session = Session()
        session.execute('c:Complex; q:Rational')
        for name in ('sin', 'cos', 'tan', 'exp', 'log', 'sqrt', 'abs'):
            with self.subTest(name=name):
                ir = session.typed_ir(f'{name}(c)')
                result = Type('Real' if name == 'abs' else 'Complex')
                self.assertEqual(ir.type, result)
                self.assertEqual(ir.children[0].type, Type('Function', (Type('Complex'), result)))
                self.assertEqual(ir.children[1].type, Type('Complex'))
        self.assertEqual(session.typed_ir('sin(q)').children[1].type, Type('Real'))

    def test_rectangular_matrix_and_vector_embeddings_preserve_operand_shapes(self):
        session = Session()
        session.execute('A:Matrix<Rational,3,2>; B:Matrix<Real,2,4>; v:Vector<Real,2>')
        for expression, result in (('A*B', 'Matrix<Real, 3, 4>'), ('A*v', 'Vector<Real, 3>')):
            with self.subTest(expression=expression):
                ir = session.typed_ir(expression)
                self.assertEqual(str(ir.type), result)
                self.assertIsInstance(ir.children[0], Embed)
                self.assertEqual(str(ir.children[0].type), 'Matrix<Real, 3, 2>')

    def test_contextual_function_types_preserve_calls_and_reject_invalid_shapes(self):
        session = Session()
        session.execute('square(t)=t*t; A:Matrix<Real,2,3>; B:Matrix<Real,2,2>')
        for expression, expected in (('square(3)', 'Nat'), ('square(B)', 'Matrix<Real, 2, 2>')):
            ir = session.typed_ir(expression)
            self.assertIsInstance(ir.term, FunctionCall)
            self.assertEqual(str(ir.type), expected)
            self.assertEqual(ir.children[0].type.arguments[-1], ir.type)
        with self.assertRaisesRegex(DefinitionError, 'left.columns'):
            session.typed_ir('square(A)')
        self.assertIsNone(session['square'].parameters[0].annotation)

    def test_higher_order_generic_argument_is_elaborated_in_context(self):
        session = Session()
        session.execute('square(t)=t*t; function apply(f:Function<Real,Real>,x:Real):Real {return f(x)}')
        ir = session.typed_ir('apply(square,3)')
        self.assertEqual(ir.type, Type('Real'))
        self.assertEqual(ir.children[1].type, Type('Function', (Type('Real'), Type('Real'))))
        self.assertIsNone(session['square'].parameters[0].annotation)
        self.assertEqual(session.execute('normalize(apply(square,3))').output, ('9',))

    def test_nominal_algebra_operation_embeddings_are_explicit(self):
        session = Session()
        session.execute('import std.dual {Dual}; r:Real')
        for expression in ('r+Dual.ε', 'Dual.ε*r'):
            ir = session.typed_ir(expression)
            embedded = next(child for child in ir.children if isinstance(child, Embed))
            self.assertEqual(embedded.target_type, session['Dual'].type)
        # Scalar embeddings now also apply at typed call boundaries. Distinct
        # nominal algebras are still never interchangeable.
        session.execute('function f(x:Dual):Dual {return x}')
        ir = session.typed_ir('f(2)')
        self.assertIsInstance(ir.children[1], Embed)
        self.assertEqual(ir.children[1].target_type, session['Dual'].type)
        session.execute('import std.complex {Complex}')
        with self.assertRaises(DefinitionError):
            session.typed_ir('f(Complex.i)')

    def test_matrix_inverse_is_not_assumed_to_exist(self):
        session = Session()
        session.execute('A:Matrix<Nat,2,2>; n:Nat; z:Integer')
        self.assertEqual(session.type_of('A^n'), session['A'].annotation)
        for expression in ('A^-1', 'A^z'):
            with self.assertRaisesRegex(DefinitionError, 'invertibility'):
                session.execute('temporary=2; '+expression)
            self.assertIsNone(session.environment.get('temporary'))

    def test_display_budget_counts_newlines(self):
        ir = Session().typed_ir('1+2')
        text = format_typed_ir(ir)
        self.assertEqual(format_typed_ir(ir, max_length=len(text)), text)
        with self.assertRaises(ValueError):
            format_typed_ir(ir, max_length=len(text)-1)
