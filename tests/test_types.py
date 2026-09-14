from dataclasses import replace
import json
import unittest

from mathlang import (Session, Type, Function, DefinitionError, ParseError, SerializationError,
                      Elaborator, Limits, ElaborationError, TermFactory, dumps_ir, loads_ir,
                      format_definition, format_tree, parse_program, format_term, compatible)


class TypeAndFunctionTests(unittest.TestCase):
    def test_scalar_inference_and_safe_embeddings_preserve_expression(self):
        session = Session()
        session.execute('n:Nat; z:Integer; q:Rational; x:Real; c:Complex')
        for source, expected in (('2','Nat'), ('-2','Integer'), ('1/2','Rational'),
                                 ('n+z','Integer'), ('z/q','Rational'), ('x+q','Real'),
                                 ('x+c','Complex'), ('n^n','Nat'), ('n-z','Integer'), ('n^z','Rational')):
            with self.subTest(source=source):
                self.assertEqual(session.type_of(source), Type(expected))
        session.execute('const a:Real=2+3; const b:Nat=4/2')
        self.assertEqual(format_term(session['a']), '2 + 3')
        for source in ('const a:Nat=-1', 'const a:Integer=1/2', 'const a:Real=c', 'const a:Custom=2'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                Session(session.environment.child()).execute(source)

    def test_matrix_and_vector_signatures_and_dimension_errors(self):
        session = Session()
        session.execute('A:Matrix<Real,3,2>; B:Matrix<Rational,2,4>; C:Matrix<Real,4,4>; v:Vector<Real,2>')
        self.assertEqual(str(session.type_of('A*B')), 'Matrix<Real, 3, 4>')
        self.assertEqual(str(session.type_of('A*v')), 'Vector<Real, 3>')
        self.assertEqual(str(session.type_of('2*A')), 'Matrix<Real, 3, 2>')
        self.assertEqual(str(session.type_of('v/2')), 'Vector<Real, 2>')
        self.assertEqual(str(session.type_of('C^2')), 'Matrix<Real, 4, 4>')
        for source in ('A*C', 'A+B', 'A+1', 'v*v', 'A^2', 'C*v'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                session.execute('temporary=2; '+source)
            self.assertIsNone(session.environment.get('temporary'))
        with self.assertRaisesRegex(DefinitionError, '2 != 4'):
            session.execute('normalize(A*C)')

    def test_annotation_dimensions_and_symbolic_function_arity(self):
        session = Session()
        session.execute('const size=3; A:Matrix<Real,size,size>; h:Function<Real,Real,Real>')
        self.assertEqual(str(session['A'].annotation), 'Matrix<Real, 3, 3>')
        self.assertEqual(session.execute('normalize(h(2,3))').output, ('h(2, 3)',))
        for source in ('v:Vector<Real,0>', 'A:Matrix<Real,3>', 'x:Real<3>', 'f:Function<3,Real>', 'h(2)', 'h(A,2)'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                session.execute(source)

    def test_full_function_local_definitions_and_annotations(self):
        session = Session()
        source = '''function norm(x:Real,y:Real):Real {
            const xx:Real=x*x
            yy=y*y
            return xx+yy
        }'''
        session.execute(source)
        self.assertEqual(session.execute('normalize(norm(3,4))').output, ('25',))
        self.assertEqual(session.type_of('norm'), Type('Function',(Type('Real'),Type('Real'),Type('Real'))))
        self.assertIsNone(session.environment.get('xx'))
        self.assertIn('FunctionParameter(x)', format_tree(parse_program(source)))
        self.assertIn('function norm(x : Real, y : Real) : Real', format_definition(session.environment['norm']))

    def test_invalid_function_returns_locals_and_argument_types(self):
        for source in ('return 2', 'function f(x:Real):Real {}',
                       'function f(x:Real):Nat {return x}',
                       'function f(x:Real):Real {return x; const y=2}',
                       'function f(x:Real):Real {print(x); return x}',
                       'function f(x:Real):Real {import std.core; return x}',
                       'function f(x:Real):Real {const y:Nat=x; return y}'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                Session().execute(source)
        session = Session()
        session.execute('function positive(n:Nat):Nat {return n+1}; m:Matrix<Real,2,2>; c:Complex')
        for source in ('positive(-1)', 'positive(1/2)', 'positive(m)', 'positive(c)', 'positive()'):
            with self.subTest(source=source), self.assertRaises(DefinitionError):
                session.execute(source)
        self.assertEqual(session.execute('positive(2)').output, ('2 + 1',))

    def test_multi_parameter_lambda_empty_lambda_and_nested_closure(self):
        session = Session()
        result = session.execute('''pair=(x:Real,y:Real)=>x+y
        empty=()=>3
        function shift(a:Real):Function<Real,Real> {
            function add(x:Real):Real {return a+x}
            return add
        }
        add2=shift(2)
        pair(3,4); empty(); add2(5)
        ''')
        self.assertEqual(result.output, ('3 + 4','3','2 + 5'))
        self.assertIsNone(session.environment.get('add'))
        with self.assertRaises(DefinitionError):
            session.execute('pair(1)')
        for source in ('(x,x)=>x', 'function f(x:Real,x:Real){return x}', '(x:)=>x'):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_program(source)

    def test_generic_functions_and_higher_order_contracts(self):
        session = Session()
        session.execute('''square(t)=t*t
        function apply(f:Function<Real,Real>,x:Real):Real {return f(x)}
        A:Matrix<Real,2,3>
        ''')
        self.assertEqual(session.execute('normalize(apply(square,3)); simplify(apply(sin,0))').output, ('9','0'))
        with self.assertRaisesRegex(DefinitionError, 'left.columns'):
            session.execute('square(A)')
        self.assertTrue(compatible(Type('Function',(Type('Real'),Type('Nat'))), Type('Function',(Type('Nat'),Type('Real')))))
        self.assertFalse(compatible(Type('Function',(Type('Nat'),Type('Real'))), Type('Function',(Type('Real'),Type('Nat')))))

    def test_typed_functions_in_algebras_and_calculus(self):
        session = Session()
        session.execute('''import std.complex {Complex}
        function sq(z:Complex):Complex {return z*z}
        variable x:Real
        function f(t:Real):Real {const a:Real=t^3; return a+sin(t)}
        df=derivative(f,x)
        ''')
        self.assertEqual(session.execute('normalize(sq(Complex.i)); simplify(df(0))').output, ('-1','1'))
        self.assertEqual(session.execute('normalize(sq(2))').output, ('4',))
        session.execute('import std.dual {Dual}')
        with self.assertRaises(DefinitionError):
            session.execute('sq(Dual.ε)')

    def test_ir_types_return_contracts_and_version_one_compatibility(self):
        session = Session()
        session.execute('module m; function f(x:Real):Real {return x^2}; x:Real; h(t)=t^2; dh=derivative(h,x)')
        restored = loads_ir(dumps_ir(session.export_module()))
        self.assertEqual(restored.member('f').return_type, Type('Real'))
        forged = replace(session['f'], return_type=Type('Nat'))
        with self.assertRaises(SerializationError):
            loads_ir(dumps_ir(forged))
        old = json.loads(dumps_ir(session['h']))
        old['version'] = 1
        for node in old['nodes']:
            if node['tag'] == 'Function':
                node['fields'].pop('return_type')
        loaded = loads_ir(json.dumps(old))
        self.assertIsInstance(loaded, Function)
        self.assertIsNone(loaded.return_type)

    def test_bounded_type_inference_on_shared_graph(self):
        factory = TermFactory()
        term = factory.number(1)
        for _ in range(200):
            term = factory.binary('+', term, term)
        self.assertEqual(Elaborator().infer(term), Type('Nat'))
        with self.assertRaises(ElaborationError):
            Elaborator(Limits(max_steps=5)).infer(term)


if __name__ == '__main__':
    unittest.main()


class TypedIRTests(unittest.TestCase):
    def test_scalar_embeddings_are_explicit_in_typed_ir(self):
        from mathlang import Embed, TypedTerm, format_typed_ir
        session = Session()
        session.execute('x:Real; c:Complex')

        real_ir = session.typed_ir('1+x')
        self.assertEqual(real_ir.type, Type('Real'))
        self.assertIsInstance(real_ir.children[0], Embed)
        self.assertEqual(real_ir.children[0].source_type, Type('Nat'))
        self.assertEqual(real_ir.children[0].target_type, Type('Real'))

        complex_ir = session.typed_ir('x+c')
        self.assertEqual(complex_ir.type, Type('Complex'))
        self.assertIsInstance(complex_ir.children[0], Embed)
        self.assertEqual(complex_ir.children[0].source_type, Type('Real'))
        self.assertEqual(complex_ir.children[0].target_type, Type('Complex'))
        self.assertIn('Embed<Real, Complex>', format_typed_ir(complex_ir))

    def test_function_arguments_get_explicit_embeddings(self):
        from mathlang import Embed
        session = Session()
        session.execute('function f(x:Real):Real {return x+1}')
        ir = session.typed_ir('f(2)')
        self.assertEqual(ir.type, Type('Real'))
        self.assertIsInstance(ir.children[1], Embed)
        self.assertEqual(ir.children[1].source_type, Type('Nat'))
        self.assertEqual(ir.children[1].target_type, Type('Real'))

    def test_matrix_element_embedding_is_explicit(self):
        from mathlang import Embed
        session = Session()
        session.execute('A:Matrix<Real,2,2>')
        ir = session.typed_ir('2*A')
        self.assertEqual(ir.type, Type('Matrix', (Type('Real'), 2, 2)))
        self.assertIsInstance(ir.children[0], Embed)
        self.assertEqual(ir.children[0].target_type, Type('Real'))

    def test_typed_ir_preserves_early_dimension_error(self):
        session = Session()
        session.execute('A:Matrix<Real,3,2>; B:Matrix<Real,4,4>')
        with self.assertRaisesRegex(DefinitionError, '2 != 4'):
            session.typed_ir('A*B')
