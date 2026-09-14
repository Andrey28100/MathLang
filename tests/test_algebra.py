from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import random
import unittest

from mathlang import (
    AlgebraDeclaration, AlgebraDefinition, AlgebraNormalizer, DefinitionError,
    Limits, ParseError, Session, check_proof, format_term, format_tree, parse_program,
)


COMPLEX = """algebra C over Real {
    generator i
    relation i^2 = -1
    basis {1,i}
    multiplication bilinear
}"""
QUATERNIONS = Path(__file__).resolve().parents[1].joinpath("examples/quaternions.math").read_text(encoding="utf-8").split("with H")[0]


class AlgebraSyntaxTests(unittest.TestCase):
    def test_braced_declarations_match_legacy_ast(self):
        source = COMPLEX.replace("generator i", "generators {i}").replace(
            "relation i^2 = -1", "relations {i^2 = -1,}")
        self.assertEqual(parse_program(source), parse_program(COMPLEX))
        algebra = parse_program(source).statements[0]
        self.assertEqual(algebra.generators[0].span.line, 2)
        self.assertEqual(algebra.relations[0].span.line, 3)

    def test_braced_lists_accept_multiline_and_trailing_separators(self):
        for separator in (", ", ",\n", "\n", ";\n"):
            with self.subTest(separator=separator):
                tree = parse_program("algebra A over Rational {\n generators\n {\n"
                                     + separator.join(("x0", "x1", "x2"))
                                     + separator + "}\n relations\n {\n"
                                     + separator.join(("x0^2=0", "x1^2=0", "x2^2=0"))
                                     + separator + "}\n}")
                self.assertEqual(tuple(g.name for g in tree.statements[0].generators),
                                 ("x0", "x1", "x2"))
                self.assertEqual(len(tree.statements[0].relations), 3)

    def test_invalid_braced_lists(self):
        for body in (
            "generators {}", "generators {,x}", "generators {x,,y}",
            "generators {x y}", "generators {x", "relations x^2=0",
            "generators {x}; relations {}", "generators {x}; relations {,x^2=0}",
            "generators {x}; relations {x^2=0,,x^3=0}",
            "generators {x}; relations {x^2=0 x^3=0}",
            "generators {x}; relations {x^2=0",
        ):
            with self.subTest(body=body), self.assertRaises(ParseError):
                parse_program("algebra A over Real { " + body + " }")

    def test_ast_is_separate_and_includes_source_positions(self):
        tree = parse_program(COMPLEX)
        algebra = tree.statements[0]
        self.assertIsInstance(algebra, AlgebraDeclaration)
        self.assertEqual(algebra.generators[0].name, "i")
        self.assertEqual(algebra.relations[0].left.op, "^")
        self.assertEqual(algebra.span.start, 0)
        self.assertIn("RelationDeclaration", format_tree(tree))
        self.assertIn("WithStatement", format_tree(parse_program("with C { prove i^2 = -1 }")))

    def test_invalid_declarations_and_blocks(self):
        for source in (
            "algebra A { generator i }", "algebra A over Real { generator }",
            "algebra A over Real { generator i; relation {} }",
            "algebra A over Real { generator i; basis {1}; derive basis }",
            "algebra A over Real { generator i; mystery i }",
            "algebra A over Real {", "with C {", "prove {}",
            "prove multiplication distributive", "with C {} garbage",
        ):
            with self.subTest(source=source), self.assertRaises(ParseError):
                parse_program(source)

    def test_multiline_equalities_and_nested_blocks(self):
        session = Session()
        result = session.execute("""algebra C over Real {
            generator i
            relation { i^2
                 =
                 -1 }
            assert basis {1, i,}
        }
        with C {
            with C { print(normalize((1+i)^2)) }
            prove { (1+i)^2 =
                      2*i }
        }""")
        self.assertEqual(result.output[0], "2*i")
        self.assertEqual(result.values[-1].status, "proved")


class AlgebraTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.session.execute(COMPLEX)

    def run_expr(self, source):
        return self.session.execute("with C { " + source + " }")

    def test_functions_in_comma_separated_relations(self):
        result = self.session.execute("""
        f0(u, v) = u*u
        f1(u, v) = v*v
        f2(u, v) = u*v + v*u
        algebra Cl over Rational {
            generators {x0, x1,}
            relations {f0(x0, x1) = 1, f1(x0, x1) = -1, f2(x0, x1) = 0,}
            basis {1, x0, x1, x0*x1}
            multiplication bilinear
        }
        with Cl {
            normalize((x0+x1)^2)
            prove {x1*x0 = -x0*x1, (x0*x1)^2 = 1,}
        }
        """)
        self.assertEqual(result.output[0], "0")
        self.assertEqual([proof.status for proof in result.values[1:]], ["proved", "proved"])
        self.assertTrue(all(check_proof(proof.proof) for proof in result.values[1:]))

    def test_braced_lists_keep_semantic_validation_and_atomicity(self):
        for body in ("generators {x, x}", "generators {x}; relations {x = missing}",
                     "generators {x}; relations {sin(x) = 0}"):
            with self.subTest(body=body), self.assertRaises(DefinitionError):
                self.session.execute("const temporary=3; algebra A over Real {" + body + "}")
            self.assertIsNone(self.session.environment.get("A"))
            self.assertIsNone(self.session.environment.get("temporary"))

    def test_complex_storage_normalization_and_qualified_dispatch(self):
        result = self.run_expr("z = (1+i)^2; print(z); print(normalize(z)); normalize((1+i)^4)")
        self.assertEqual(result.output, ("(1 + i)^2", "2*i", "-4"))
        self.assertEqual(format_term(self.session.resolve("normalize(C.i*C.i)")), "-1")
        self.assertEqual(format_term(self.session.resolve("C.i")), "i")
        self.assertIsNone(self.session.environment.get("z"))
        self.assertIsNone(self.session.environment.get("i"))
        algebra = self.session["C"]
        self.assertIsInstance(algebra, AlgebraDefinition)
        self.assertEqual(algebra.termination, "known")
        self.assertEqual(algebra.confluence, "known")
        with self.assertRaises(FrozenInstanceError):
            algebra.name = "Other"

    def test_reverse_and_polynomial_relations(self):
        result = self.session.execute("""algebra W over Rational {
            generators x, y
            relation x*y-y*x = 1
        }
        with W { normalize(y*x^3); prove y*x^3 = x^3*y - 3*x^2 }
        algebra D over Real { generator e; relation 0 = e^2; derive basis }
        with D { normalize((1+e)^8) }
        """)
        self.assertEqual(result.output[0], "x^3*y - 3*x^2")
        self.assertEqual(result.values[1].status, "proved")
        self.assertTrue(check_proof(result.values[1].proof))
        self.assertEqual(result.output[2], "8*e + 1")
        self.assertEqual(self.session["D"].basis, ((), (0,)))

    def test_quaternion_order_and_exact_independent_products(self):
        self.session.execute(QUATERNIONS)
        self.session.execute("use H")
        self.assertEqual(self.session.execute("normalize(i*j); normalize(j*i)").output, ("k", "-k"))
        rng = random.Random(49)
        for _ in range(15):
            a, b = (tuple(rng.randint(-3, 3) for _ in range(4)) for _ in range(2))
            w, x, y, z = a
            t, u, v, s = b
            expected = (w*t-x*u-y*v-z*s, w*u+x*t+y*s-z*v,
                        w*v-x*s+y*t+z*u, w*s+x*v-y*u+z*t)
            text = lambda q: f"({q[0]}+({q[1]})*i+({q[2]})*j+({q[3]})*k)"
            actual = self.session.resolve(f"normalize({text(a)}*{text(b)})")
            reference = self.session.resolve(f"normalize({text(expected)})")
            self.assertEqual(actual, reference)

    def test_symbolic_scalar_coefficients(self):
        self.session.execute("parameter a : Real; variable x : Real")
        result = self.run_expr("prove (a+x*i)*(a-x*i) = a^2+x^2; normalize((1/2+i/3)^2)")
        self.assertEqual(result.values[0].status, "proved")
        self.assertTrue(check_proof(result.values[0].proof))
        self.assertEqual(result.output[1], "1/3*i + 5/36")

    def test_with_use_scopes_identity_and_rollback(self):
        self.session.execute("use C")
        old = self.session.resolve("i")
        self.session.execute("algebra D over Real { generator i; relation i^2=0; basis {1,i} }")
        result = self.session.execute("with D { normalize(i^2); with C { normalize(i^2) }; normalize(i^2) }; normalize(i^2)")
        self.assertEqual(result.output, ("0", "-1", "0", "-1"))
        with self.assertRaises(DefinitionError):
            self.session.execute("use D; const a=3; missing")
        self.assertIs(self.session.resolve("i"), old)
        self.assertIsNone(self.session.environment.get("a"))
        registry = dict(self.session.kernel.algebras)
        with self.assertRaises(DefinitionError):
            self.session.execute("algebra E over Real { generator e }; missing")
        self.assertEqual(self.session.kernel.algebras, registry)
        self.assertIsNone(self.session.environment.get("E"))
        with self.assertRaisesRegex(DefinitionError, "different algebras"):
            self.session.resolve("C.i + D.i")

    def test_invalid_basis_relations_and_domains(self):
        bodies = (
            "generators i, i", "relation 1=0", "generator i; relation i^2=-1; basis {1}",
            "generator i; relation i^2=-1; basis {1,i,i}",
            "generator i; relation i^2=-1; basis {1,i^2}",
            "generator i; relation i^2=-1; basis {1,2*i}",
            "generator i; relation i=missing", "generator i; relation i^(-1)=0",
            "generator i; relation i/0=0",
        )
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(DefinitionError):
                self.session.execute("algebra A over Real { " + body + " }")
        with self.assertRaises(DefinitionError):
            self.session.execute("algebra A over Integer { generator i }")
        self.session.execute("v : Matrix<Real,2,2>; c : Complex")
        for expr in ("v*C.i", "c*C.i", "C.i/0", "C.i^0.5", "abs(C.i)", "(0*C.i)^0", "0*(1/0)*C.i"):
            with self.subTest(expr=expr), self.assertRaises(DefinitionError):
                self.session.resolve("normalize(" + expr + ")")

    def test_confluence_checks_inclusion_overlaps_and_competing_rules(self):
        for relations in ("a*b=a; b*c=b", "a=0; a*b=1", "a=0; a=1"):
            with self.subTest(relations=relations):
                session = Session()
                session.execute("algebra A over Real { generators a,b,c; relation {" + relations + "} }")
                self.assertEqual(session["A"].confluence, "unknown")
                with self.assertRaisesRegex(DefinitionError, "Conflicting reductions"):
                    session.resolve("normalize(A.a*A.b*A.c)")
                result = session.execute("with A { prove a=0 }")
                self.assertEqual(result.values[0].status, "unknown")

    def test_derive_basis_and_computation_limits_are_bounded(self):
        for source in (
            "algebra A over Real { generator a; derive basis }",
            "algebra A over Real { generator a; relation a^20=0 }",
        ):
            with self.assertRaises(DefinitionError):
                Session(limits=Limits(max_terms=8, max_power=10)).execute(source)
        session = Session(limits=Limits(max_power=10))
        session.execute(COMPLEX)
        with self.assertRaisesRegex(DefinitionError, "bounded"):
            session.resolve("normalize(C.i^100)")

    def test_function_capture_substitution_and_independent_python_api(self):
        self.session.execute("f(t) = normalize((t+C.i)^2)")
        self.assertEqual(format_term(self.session.resolve("f(1)")), "2*i")
        self.session.execute("parameter a : Real; z = a*C.i")
        self.assertEqual(format_term(self.session.resolve("z |> substitute(a=2) |> normalize")), "2*i")
        algebra = self.session["C"]
        term = self.session.resolve("(1+C.i)^2")
        self.assertEqual(format_term(AlgebraNormalizer(algebra, self.session.factory).normalize(term)), "2*i")
        second = Session(self.session.environment)
        self.assertEqual(format_term(second.resolve("normalize(C.i^2)")), "-1")

    def test_basis_words_clifford_and_matrix_presentations(self):
        result = self.session.execute("""algebra Cl over Real {
            generators x,y
            relation {x^2=1; y^2=-1; y*x=-x*y}
            basis {1,x,y,x*y}
            multiplication bilinear
            prove multiplication associative
        }
        with Cl { prove (x*y)^2=1 }
        algebra M over Rational {
            generators a,b,c
            relation {
                a^2=a; b^2=0; c^2=0
                a*b=b; b*a=0; a*c=0; c*a=c
                b*c=a; c*b=1-a
            }
            derive basis
            multiplication bilinear
            prove multiplication associative
        }
        with M { prove (a+b+c)^2 = 1+a+b+c }
        """)
        self.assertEqual(len(self.session["M"].basis), 4)
        self.assertEqual([value.status for value in result.values], ["proved"]*4)
        self.assertTrue(all(check_proof(value.proof) for value in result.values))

    def test_redundant_relations_and_normalization_idempotence(self):
        self.session.execute("algebra D over Real {generator e; relation {e^2=-1; e^3=-e}; derive basis}")
        for expression in ("(1+D.e)^7", "-3*D.e/7", "(D.e^2+1)*D.e", "D.e^(2+2)"):
            term = self.session.resolve("normalize("+expression+")")
            again = self.session.kernel.transform("normalize", term)
            self.assertEqual(term, again)

    def test_scalar_api_does_not_commute_generators_named_complex(self):
        from mathlang import normalize, NormalizationError
        self.session.execute("algebra Complex over Real {generators a,b}")
        term = self.session.resolve("Complex.b*Complex.a")
        with self.assertRaises(NormalizationError):
            normalize(term, self.session.factory)
        self.assertEqual(format_term(self.session.kernel.transform("normalize", term)), "b*a")

    def test_negative_coefficients_and_undefined_scalar_subexpressions(self):
        self.assertEqual(self.run_expr("normalize(-i/2-i/3)").output, ("-(5/6*i)",))
        self.assertEqual(self.run_expr("normalize(sin(0)*i)").output, ("0",))
        self.assertEqual(self.run_expr("normalize(cos(0)*i)").output, ("i",))
        for expression in ("sin(0)^0+i", "0*(1/0)*i", "(i-i)^0", "i/(2-2)"):
            with self.subTest(expression=expression), self.assertRaises(DefinitionError):
                self.run_expr("normalize("+expression+")")

    def test_type_errors_and_nested_definition_positions(self):
        self.session.execute("variable v : Matrix<Real,2,2>")
        with self.assertRaisesRegex(DefinitionError, "no scalar embedding"):
            self.session.resolve("v+C.i")
        with self.assertRaises(DefinitionError) as error:
            self.session.execute("algebra D over Real {\n generator e\n relation e=missing\n}")
        self.assertEqual(error.exception.span.line, 3)
        self.assertEqual(str(error.exception).count("line 3"), 1)

    def test_all_declared_basis_checks_are_bounded(self):
        from mathlang import ProofSearch
        self.session.execute(QUATERNIONS)
        search = ProofSearch(self.session.factory, Limits(max_steps=63))
        result = search.property(self.session["H"], "associative")
        self.assertEqual(result.status, "unknown")
        self.assertIn("limit", result.reason)


class ProofTests(unittest.TestCase):
    def test_equality_proofs_are_objects_and_not_booleans(self):
        session = Session()
        result = session.execute("parameter x : Real; prove { (x+1)^2=x^2+2*x+1; x=x+1; x=2 }")
        self.assertEqual([p.status for p in result.values], ["proved", "disproved", "unknown"])
        proof = result.values[0].proof
        self.assertTrue(check_proof(proof))
        self.assertFalse(check_proof(replace(proof, left_normal=session.factory.number(17))))
        self.assertFalse(check_proof(proof, result.values[1].goal))
        self.assertIsNone(result.values[1].proof)

    def test_finite_basis_certificates_and_counterexamples(self):
        session = Session()
        result = session.execute(QUATERNIONS)
        proved = result.values[0]
        self.assertEqual(proved.status, "proved")
        self.assertEqual(proved.checks, 64)
        self.assertEqual(len(proved.proof.children), 64)
        self.assertTrue(check_proof(proved.proof))
        self.assertFalse(check_proof(replace(proved.proof, children=proved.proof.children[:-1])))
        bad_child = replace(proved.proof.children[-1], method="user_rewrite")
        self.assertFalse(check_proof(replace(proved.proof, children=(*proved.proof.children[:-1], bad_child))))
        self.assertTrue(check_proof(session.resolve("H.associativity_proof").proof))
        disproved = session.execute("with H { prove multiplication commutative }").values[0]
        self.assertEqual(disproved.status, "disproved")
        self.assertEqual(tuple(map(format_term, disproved.counterexample)), ("i", "j"))
        self.assertNotIn("commutativity_proof", dict(session["H"].properties))

    def test_checker_recompiles_the_presentation(self):
        session = Session()
        session.execute(COMPLEX)
        proof = session.execute("with C { prove i^2=-1 }").values[0].proof
        forged = replace(proof.algebra, reductions=(), confluence="known")
        self.assertFalse(check_proof(replace(proof, algebra=forged)))

    def test_unproved_properties_and_user_rewrites_do_not_become_axioms(self):
        session = Session()
        session.execute("algebra A over Real { generator a; relation a^2=0; basis {1,a} }")
        result = session.execute("with A { prove multiplication associative }").values[0]
        self.assertEqual(result.status, "unknown")
        self.assertIn("bilinear", result.reason)
        result = session.execute("rule wrong {1 -> 2}; prove 1=2").values[0]
        self.assertEqual(result.status, "disproved")
        result = session.execute("prove 1/0 = 1/0").values[0]
        self.assertEqual(result.status, "unknown")


if __name__ == "__main__":
    unittest.main()
