"""Bounded proof search and a separate certificate checker.

The trusted computational base is exact polynomial normalization plus the
verified quotient presentation. User rewrite rules are never proof axioms.
"""

from dataclasses import dataclass
from itertools import product

from .algebra import AlgebraDefinition, AlgebraNormalizer, Relation, compile_algebra, word_term
from .normalization import Limits, NormalizationError, ScalarNormalizer
from .rewriting import structurally_equal
from .terms import Number, SymbolKind, Term, TermFactory, free_symbols


@dataclass(frozen=True, slots=True)
class EqualityGoal:
    left: Term
    right: Term


@dataclass(frozen=True, slots=True)
class PropertyGoal:
    property: str


@dataclass(frozen=True, slots=True)
class Proof:
    goal: EqualityGoal | PropertyGoal
    method: str
    algebra: AlgebraDefinition | None = None
    left_normal: Term | None = None
    right_normal: Term | None = None
    children: tuple["Proof", ...] = ()

    @property
    def relations(self) -> tuple[Relation, ...]:
        return () if self.algebra is None else self.algebra.relations

    @property
    def axioms(self) -> tuple:
        return ()


@dataclass(frozen=True, slots=True)
class ProofResult(Term):
    status: str
    goal: EqualityGoal | PropertyGoal
    method: str
    proof: Proof | None = None
    left_normal: Term | None = None
    right_normal: Term | None = None
    reason: str | None = None
    counterexample: tuple[Term, ...] | None = None
    checks: int = 0
    __hash__ = Term.__hash__


def _goals(algebra: AlgebraDefinition, property: str, factory: TermFactory, limits: Limits):
    if property not in ("associative", "commutative"):
        raise NormalizationError("Unknown multiplication property")
    if not algebra.bilinear or algebra.basis is None:
        raise NormalizationError("A verified finite basis and declared bilinear multiplication are required")
    arity = 3 if property == "associative" else 2
    if len(algebra.basis) ** arity > limits.max_steps:
        raise NormalizationError("Finite-basis proof check limit exceeded")
    basis = tuple(word_term(algebra, word, factory) for word in algebra.basis)
    mul = lambda a, b: factory.binary("*", a, b)
    for elements in product(basis, repeat=arity):
        a, b = elements[:2]
        if arity == 3:
            c = elements[2]
            yield elements, EqualityGoal(mul(mul(a, b), c), mul(a, mul(b, c)))
        else:
            yield elements, EqualityGoal(mul(a, b), mul(b, a))


class ProofSearch:
    def __init__(self, factory: TermFactory, limits: Limits | None = None):
        self.factory, self.limits = factory, Limits() if limits is None else limits

    def equality(self, left: Term, right: Term, algebra: AlgebraDefinition | None = None) -> ProofResult:
        goal = EqualityGoal(left, right)
        normalizer = (ScalarNormalizer(self.factory, self.limits) if algebra is None
                      else AlgebraNormalizer(algebra, self.factory, self.limits))
        try:
            a, b = normalizer.normalize(left), normalizer.normalize(right)
            if structurally_equal(a, b):
                proof = Proof(goal, "normalization", algebra, a, b)
                return ProofResult("proved", goal, "normalization", proof, a, b)
            difference = normalizer.normalize(self.factory.binary("-", a, b))
            fixed = all(s.kind in (SymbolKind.GENERATOR, SymbolKind.BUILTIN) for s in free_symbols(difference))
            # Distinct rational coordinates in a certified word basis refute
            # equality. Symbolic atoms may specialize, so retain Unknown.
            numeric = ScalarNormalizer(self.factory, self.limits).simplify(difference) if algebra is None else difference
            disproved = (isinstance(numeric, Number) and numeric.value != 0)
            if algebra is not None and fixed:
                disproved = disproved or _rational_coordinates(difference)
            return ProofResult("disproved" if disproved else "unknown", goal,
                               "normalization", left_normal=a, right_normal=b,
                               reason=None if disproved else "Normal forms differ, but symbolic values may coincide")
        except NormalizationError as error:
            return ProofResult("unknown", goal, "normalization", reason=str(error))

    def property(self, algebra: AlgebraDefinition, property: str) -> ProofResult:
        goal = PropertyGoal(property)
        children = []
        try:
            for elements, equality in _goals(algebra, property, self.factory, self.limits):
                result = self.equality(equality.left, equality.right, algebra)
                if result.status != "proved":
                    return ProofResult(result.status, goal, "finite_basis", reason=result.reason,
                                       counterexample=elements, checks=len(children)+1,
                                       left_normal=result.left_normal, right_normal=result.right_normal)
                children.append(result.proof)
            proof = Proof(goal, "finite_basis", algebra, children=tuple(children))
            return ProofResult("proved", goal, "finite_basis", proof, checks=len(children))
        except NormalizationError as error:
            return ProofResult("unknown", goal, "finite_basis", reason=str(error))


def _rational_coordinates(term: Term) -> bool:
    from .terms import Binary, Symbol, Unary
    stack = [term]
    while stack:
        node = stack.pop()
        if isinstance(node, Number):
            continue
        if isinstance(node, Symbol) and node.kind == SymbolKind.GENERATOR:
            continue
        if not isinstance(node, (Binary, Unary)):
            return False
        stack.extend(node.children)
    return True


class ProofChecker:
    """Rebuild the presentation; verify certificates without invoking search."""

    def __init__(self, limits: Limits | None = None):
        self.limits = Limits() if limits is None else limits

    def check(self, proof: Proof, expected_goal: EqualityGoal | PropertyGoal | None = None) -> bool:
        if not isinstance(proof, Proof) or (expected_goal is not None and proof.goal != expected_goal):
            return False
        factory = TermFactory()
        algebra = proof.algebra
        try:
            if algebra is not None:
                # Do not trust supplied reductions, basis metadata or confluence.
                basis = (None if algebra.basis is None else
                         tuple(word_term(algebra, w, factory) for w in algebra.basis))
                checked = compile_algebra(algebra.name, algebra.scalar_domain, algebra.type,
                                          algebra.generators, algebra.relations, basis,
                                          bilinear=algebra.bilinear, limits=self.limits)
                if checked.reductions != algebra.reductions or checked.confluence != "known":
                    return False
                algebra = checked
            normalizer = (ScalarNormalizer(factory, self.limits) if algebra is None
                          else AlgebraNormalizer(algebra, factory, self.limits))

            def equality(item: Proof, goal: EqualityGoal) -> bool:
                if (item.method != "normalization" or item.goal != goal or item.children
                        or item.algebra is not proof.algebra
                        or item.left_normal is None or item.right_normal is None):
                    return False
                left, right = normalizer.normalize(goal.left), normalizer.normalize(goal.right)
                return (structurally_equal(left, item.left_normal)
                        and structurally_equal(right, item.right_normal)
                        and structurally_equal(left, right))

            if isinstance(proof.goal, EqualityGoal):
                return equality(proof, proof.goal)
            if proof.method != "finite_basis" or algebra is None or proof.left_normal is not None or proof.right_normal is not None:
                return False
            expected = tuple(_goals(algebra, proof.goal.property, factory, self.limits))
            return (len(expected) == len(proof.children)
                    and all(equality(child, goal) for child, (_, goal) in zip(proof.children, expected)))
        except (ValueError, TypeError, IndexError, RecursionError):
            return False


def check_proof(proof: Proof, expected_goal=None, *, limits: Limits | None = None) -> bool:
    return ProofChecker(limits).check(proof, expected_goal)
