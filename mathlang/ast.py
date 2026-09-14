"""Syntax nodes only: no name resolution, evaluation or simplification."""

from dataclasses import dataclass, field

from .source import SourceSpan


@dataclass(frozen=True, slots=True)
class Node:
    # Location metadata does not affect structural equality or hashing.
    span: SourceSpan | None = field(default=None, kw_only=True, compare=False)

    @property
    def children(self) -> tuple["Node", ...]:
        return ()


@dataclass(frozen=True, slots=True)
class Expr(Node):
    pass


@dataclass(frozen=True, slots=True)
class ForAllExpr(Expr):
    parameters: tuple['FunctionParameter', ...]
    body: Expr

    @property
    def children(self):
        return (*self.parameters, self.body)


@dataclass(frozen=True, slots=True)
class NumberLiteral(Expr):
    # Preserve the spelling; conversion to mathematical numbers belongs to IR.
    text: str


@dataclass(frozen=True, slots=True)
class Identifier(Expr):
    name: str


@dataclass(frozen=True, slots=True)
class TruthLiteral(Expr):
    value: str


@dataclass(frozen=True, slots=True)
class ComparisonExpr(Expr):
    op: str
    left: Expr
    right: Expr

    @property
    def children(self):
        return (self.left, self.right)


@dataclass(frozen=True, slots=True)
class LogicalExpr(Expr):
    op: str
    operands: tuple[Expr, ...]

    @property
    def children(self):
        return self.operands


@dataclass(frozen=True, slots=True)
class UnaryExpr(Expr):
    op: str
    operand: Expr

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, slots=True)
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, slots=True)
class CallExpr(Expr):
    callee: Expr
    arguments: tuple[Expr, ...]
    keywords: tuple["KeywordArgument", ...] = ()

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.callee, *self.arguments, *self.keywords)


@dataclass(frozen=True, slots=True)
class KeywordArgument(Node):
    name: str
    value: Expr

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.value,)


@dataclass(frozen=True, slots=True)
class SubstitutionExpr(Expr):
    expression: Expr
    replacements: tuple[KeywordArgument, ...]

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.expression, *self.replacements)


@dataclass(frozen=True, slots=True)
class PipelineExpr(Expr):
    value: Expr
    target: Expr

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.value, self.target)


@dataclass(frozen=True, slots=True)
class ApproachExpr(Expr):
    variable: Expr
    point: Expr

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.variable, self.point)


@dataclass(frozen=True, slots=True)
class LambdaExpr(Expr):
    parameters: tuple["FunctionParameter", ...]
    body: Expr

    @property
    def children(self) -> tuple[Expr, ...]:
        return (*self.parameters, self.body)


@dataclass(frozen=True, slots=True)
class RewriteExpr(Expr):
    expression: Expr
    rules: Identifier | None = None
    strategy: str = "bottom_up"
    repeat: bool = False

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.expression,) if self.rules is None else (self.expression, self.rules)


@dataclass(frozen=True, slots=True)
class RuleConditionExpr(Node):
    left: Expr
    op: str
    right: Expr

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, slots=True)
class RuleClause(Node):
    pattern: Expr
    replacement: Expr
    condition: RuleConditionExpr | None = None

    @property
    def children(self) -> tuple[Node, ...]:
        return ((self.pattern, self.replacement) if self.condition is None
                else (self.pattern, self.replacement, self.condition))


@dataclass(frozen=True, slots=True)
class TypeRef(Node):
    name: str
    arguments: tuple["TypeRef | NumberLiteral", ...] = ()

    @property
    def children(self) -> tuple[Node, ...]:
        return self.arguments


@dataclass(frozen=True, slots=True)
class Statement(Node):
    pass


@dataclass(frozen=True, slots=True)
class OperationDeclaration(Node):
    name: str
    inputs: tuple[TypeRef, ...]
    output: TypeRef

    @property
    def children(self):
        return (*self.inputs, self.output)


@dataclass(frozen=True, slots=True)
class AxiomDeclaration(Node):
    name: str
    predicate: Expr

    @property
    def children(self):
        return (self.predicate,)


@dataclass(frozen=True, slots=True)
class TheoryDeclaration(Statement):
    name: str
    parameters: tuple[str, ...]
    operations: tuple[OperationDeclaration, ...]
    constants: tuple['Declaration', ...]
    axioms: tuple[AxiomDeclaration, ...]
    parents: tuple[TypeRef, ...] = ()

    @property
    def children(self):
        return (*self.parents, *self.operations, *self.constants, *self.axioms)


@dataclass(frozen=True, slots=True)
class ImplementationBinding(Node):
    name: str
    value: Expr
    operation: bool

    @property
    def children(self):
        return (self.value,)


@dataclass(frozen=True, slots=True)
class ImplementationDeclaration(Statement):
    name: str
    theory: TypeRef
    bindings: tuple[ImplementationBinding, ...]
    assumptions: tuple[str, ...]

    @property
    def children(self):
        return (self.theory, *self.bindings)


@dataclass(frozen=True, slots=True)
class AssumeStatement(Statement):
    condition: Expr

    @property
    def children(self):
        return (self.condition,)


@dataclass(frozen=True, slots=True)
class AssumingStatement(Statement):
    conditions: tuple[Expr, ...]
    body: 'Program'

    @property
    def children(self):
        return (*self.conditions, self.body)


@dataclass(frozen=True, slots=True)
class FunctionParameter(Node):
    name: str
    annotation: TypeRef | None = None

    @property
    def children(self) -> tuple[Node, ...]:
        return () if self.annotation is None else (self.annotation,)


@dataclass(frozen=True, slots=True)
class TypedFunctionDefinition(Statement):
    name: str
    parameters: tuple[FunctionParameter, ...]
    return_type: TypeRef | None
    body: "Program"

    @property
    def children(self) -> tuple[Node, ...]:
        return (*self.parameters, *((self.return_type,) if self.return_type is not None else ()), self.body)


@dataclass(frozen=True, slots=True)
class ReturnStatement(Statement):
    expression: Expr

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.expression,)


@dataclass(frozen=True, slots=True)
class ModuleDeclaration(Statement):
    name: str


@dataclass(frozen=True, slots=True)
class ImportName(Node):
    name: str
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class ImportStatement(Statement):
    module: str
    alias: str | None = None
    names: tuple[ImportName, ...] = ()

    @property
    def children(self) -> tuple[Node, ...]:
        return self.names


@dataclass(frozen=True, slots=True)
class NamespaceDeclaration(Statement):
    name: str
    body: "Program"

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.body,)


@dataclass(frozen=True, slots=True)
class RelationDeclaration(Node):
    left: Expr
    right: Expr

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, slots=True)
class ProveStatement(Statement):
    goals: tuple[RelationDeclaration, ...] = ()
    property_name: str | None = None

    @property
    def children(self) -> tuple[Node, ...]:
        return self.goals


@dataclass(frozen=True, slots=True)
class AlgebraDeclaration(Statement):
    name: str
    scalar_domain: TypeRef
    generators: tuple[Identifier, ...]
    relations: tuple[RelationDeclaration, ...]
    basis: tuple[Expr, ...] | None = None
    derive_basis: bool = False
    bilinear: bool = False
    proofs: tuple[ProveStatement, ...] = ()

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.scalar_domain, *self.generators, *self.relations,
                *(self.basis or ()), *self.proofs)


@dataclass(frozen=True, slots=True)
class WithStatement(Statement):
    algebra: Identifier
    body: "Program"

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.algebra, self.body)


@dataclass(frozen=True, slots=True)
class UseStatement(Statement):
    algebra: Identifier

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.algebra,)


@dataclass(frozen=True, slots=True)
class RuleDeclaration(Statement):
    name: str | None
    clauses: tuple[RuleClause, ...]

    @property
    def children(self) -> tuple[Node, ...]:
        return self.clauses


@dataclass(frozen=True, slots=True)
class Declaration(Statement):
    kind: str
    name: str
    annotation: TypeRef | None = None
    value: Expr | None = None

    @property
    def children(self) -> tuple[Node, ...]:
        return tuple(node for node in (self.annotation, self.value) if node is not None)


@dataclass(frozen=True, slots=True)
class Assignment(Statement):
    name: str
    value: Expr

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.value,)


@dataclass(frozen=True, slots=True)
class FunctionDefinition(Statement):
    name: str
    parameters: tuple[Identifier, ...]
    body: Expr

    @property
    def children(self) -> tuple[Node, ...]:
        return (*self.parameters, self.body)


@dataclass(frozen=True, slots=True)
class ExpressionStatement(Statement):
    expression: Expr

    @property
    def children(self) -> tuple[Node, ...]:
        return (self.expression,)


@dataclass(frozen=True, slots=True)
class Program(Node):
    statements: tuple[Statement, ...]

    @property
    def children(self) -> tuple[Node, ...]:
        return self.statements


def _label(node: Node) -> str:
    match node:
        case ForAllExpr():
            return 'ForAllExpr'
        case TheoryDeclaration(name=name) | ImplementationDeclaration(name=name) | OperationDeclaration(name=name) | AxiomDeclaration(name=name) | ImplementationBinding(name=name):
            return f'{type(node).__name__}({name})'
        case TruthLiteral(value=value):
            return f'TruthLiteral({value})'
        case ComparisonExpr(op=op) | LogicalExpr(op=op):
            return f'{type(node).__name__}({op})'
        case AssumeStatement() | AssumingStatement():
            return type(node).__name__
        case ModuleDeclaration(name=name):
            return f"ModuleDeclaration({name})"
        case ImportStatement(module=module):
            return f"ImportStatement({module})"
        case ImportName(name=name):
            return f"ImportName({name})"
        case NamespaceDeclaration(name=name):
            return f"NamespaceDeclaration({name})"
        case TypedFunctionDefinition(name=name):
            return f"TypedFunctionDefinition({name})"
        case FunctionParameter(name=name):
            return f"FunctionParameter({name})"
        case ReturnStatement():
            return "ReturnStatement"
        case NumberLiteral(text=text):
            return f"NumberLiteral({text})"
        case Identifier(name=name):
            return f"Identifier({name})"
        case UnaryExpr(op=op):
            return f"UnaryExpr({op})"
        case BinaryExpr(op=op):
            return f"BinaryExpr({op})"
        case CallExpr():
            return "CallExpr"
        case KeywordArgument(name=name):
            return f"KeywordArgument({name})"
        case SubstitutionExpr():
            return "SubstitutionExpr"
        case PipelineExpr():
            return "PipelineExpr"
        case ApproachExpr():
            return "ApproachExpr"
        case LambdaExpr():
            return "LambdaExpr"
        case RewriteExpr(strategy=strategy, repeat=repeat):
            return f"RewriteExpr({strategy}{', recursively' if repeat else ''})"
        case RuleConditionExpr(op=op):
            return f"RuleConditionExpr({op})"
        case RuleClause():
            return "RuleClause"
        case RuleDeclaration(name=name):
            return f"RuleDeclaration({name or 'anonymous'})"
        case TypeRef(name=name):
            return f"TypeRef({name})"
        case Declaration(kind=kind, name=name):
            return f"Declaration({kind} {name})"
        case Assignment(name=name):
            return f"Assignment({name})"
        case FunctionDefinition(name=name):
            return f"FunctionDefinition({name})"
        case ExpressionStatement():
            return "ExpressionStatement"
        case Program():
            return "Program"
        case AlgebraDeclaration(name=name):
            return f"AlgebraDeclaration({name})"
        case RelationDeclaration():
            return "RelationDeclaration"
        case ProveStatement(property_name=property):
            return f"ProveStatement({property or 'equality'})"
        case WithStatement():
            return "WithStatement"
        case UseStatement():
            return "UseStatement"
        case _:
            raise TypeError(f"Unsupported node: {type(node).__name__}")


def format_tree(node: Node) -> str:
    """Render a tree; a call's first child is its callee, then its arguments."""
    lines = [_label(node)]
    children = node.children
    stack = [
        (child, "", i == len(children) - 1)
        for i, child in reversed(list(enumerate(children)))
    ]
    while stack:
        child, prefix, last = stack.pop()
        lines.append(prefix + ("`-- " if last else "|-- ") + _label(child))
        next_prefix = prefix + ("    " if last else "|   ")
        children = child.children
        stack.extend(
            (item, next_prefix, i == len(children) - 1)
            for i, item in reversed(list(enumerate(children)))
        )
    return "\n".join(lines)
