"""Mathematical syntax, symbolic definitions and persistent in-process sessions."""

from .ast import (
    ForAllExpr, TheoryDeclaration, ImplementationDeclaration,
    ComparisonExpr, LogicalExpr, TruthLiteral, AssumeStatement, AssumingStatement,
    FunctionParameter, TypedFunctionDefinition, ReturnStatement,
    ModuleDeclaration, ImportStatement, ImportName, NamespaceDeclaration,
    ApproachExpr, LambdaExpr,
    AlgebraDeclaration, RelationDeclaration, ProveStatement, WithStatement, UseStatement,
    Assignment, BinaryExpr, CallExpr, Declaration, Expr, ExpressionStatement,
    FunctionDefinition, Identifier, KeywordArgument, NumberLiteral, PipelineExpr,
    Program, RewriteExpr, RuleClause, RuleConditionExpr, RuleDeclaration,
    SubstitutionExpr, TypeRef, UnaryExpr, format_tree,
)
from .environment import Definition, Environment
from .kernel import Kernel
from .normalization import Limits, NormalizationError, ScalarNormalizer, normalize, simplify
from .parser import parse_expression, parse_program
from .renderer import RenderError, format_definition, format_pattern, format_rule_set, format_term
from .rewriting import (
    BinaryPattern, CallPattern, LiteralPattern, Matcher, Pattern, RewriteError, RewriteResult,
    RewriteRule, RewriteStrategy, Rewriter, RuleCondition, UnaryPattern, Wildcard, rewrite,
)
from .session import ExecutionResult, Session
from .source import DefinitionError, LanguageError, ParseError, SourceSpan
from .terms import (
    Predicate, Comparison, Logical, Defined, ForAll, Truth, TruthValue,
    Approach, CalculusOperator, CalculusRequest, TaylorSeries, builtin_symbol,
    ApproxNumber, Binary, Function, FunctionCall, Number, RewriteRequest, RuleSet, Substitution,
    Symbol, SymbolKind, Term, TermFactory, Type, Unary,
    free_symbols,
)
from .algebra import AlgebraDefinition, AlgebraError, AlgebraNormalizer, Relation, WordReduction, compile_algebra, algebra_symbols
from .proof import EqualityGoal, PropertyGoal, Proof, ProofResult, ProofSearch, ProofChecker, check_proof
from .analysis import AnalysisError, Calculus, derivative, antiderivative, integrate, series, limit
from .modules import ModuleError, ModuleLoader, Namespace
from .serialization import SerializationError, dumps_ir, loads_ir, save_ir, load_ir
from .elaboration import Elaborator, ElaborationError, compatible, validate_type
from .typed_ir import Embed, TypedTerm, TypedValue, format_typed_ir
from .symbols import MATH_ALIASES, canonical_name
from .logic import AssumptionSet, Context, PredicateQuery, LogicError
from .iteration import IterationError
from .theories import Theory, TheoryParent, TheoryOperation, Axiom, Implementation, PropertyResult, TheoryError
from .numeric import NumericError, evaluate_numeric

__all__ = [
    'ForAll', 'ForAllExpr', 'TheoryDeclaration', 'ImplementationDeclaration',
    'Theory', 'TheoryParent', 'TheoryOperation', 'Axiom', 'Implementation', 'PropertyResult', 'TheoryError',
    'IterationError',
    'Predicate', 'Comparison', 'Logical', 'Defined', 'Truth', 'TruthValue',
    'AssumptionSet', 'Context', 'PredicateQuery', 'LogicError',
    'ComparisonExpr', 'LogicalExpr', 'TruthLiteral', 'AssumeStatement', 'AssumingStatement',
    "FunctionParameter", "TypedFunctionDefinition", "ReturnStatement", "Elaborator", "ElaborationError", "compatible", "validate_type", "Embed", "TypedTerm", "TypedValue", "format_typed_ir",
    "MATH_ALIASES", "canonical_name",
    "ModuleDeclaration", "ImportStatement", "ImportName", "NamespaceDeclaration",
    "ModuleError", "ModuleLoader", "Namespace", "SerializationError", "dumps_ir", "loads_ir", "save_ir", "load_ir",
    "ApproachExpr", "LambdaExpr", "Approach", "CalculusOperator", "CalculusRequest", "TaylorSeries", "builtin_symbol",
    "AnalysisError", "Calculus", "derivative", "antiderivative", "integrate", "series", "limit",
    "AlgebraDeclaration", "RelationDeclaration", "ProveStatement", "WithStatement", "UseStatement",
    "AlgebraDefinition", "AlgebraError", "AlgebraNormalizer", "Relation", "WordReduction", "compile_algebra", "algebra_symbols",
    "EqualityGoal", "PropertyGoal", "Proof", "ProofResult", "ProofSearch", "ProofChecker", "check_proof",
    "BinaryExpr", "CallExpr", "Expr", "Identifier", "NumberLiteral", "UnaryExpr",
    "Assignment", "Declaration", "ExpressionStatement", "FunctionDefinition", "Program",
    "TypeRef", "DefinitionError", "LanguageError", "ParseError", "SourceSpan",
    "format_tree", "parse_expression", "parse_program", "Definition", "Environment",
    "ExecutionResult", "Session", "RenderError", "format_definition", "format_term", "Binary", "Function",
    "FunctionCall", "Number", "ApproxNumber", "Symbol", "SymbolKind", "Term", "TermFactory", "Type", "Unary",
    "KeywordArgument", "PipelineExpr", "SubstitutionExpr", "Substitution", "Kernel", "Limits",
    "NormalizationError", "ScalarNormalizer", "normalize", "simplify",
    "free_symbols",
    "RewriteExpr", "RuleClause", "RuleConditionExpr", "RuleDeclaration", "RewriteRequest", "RuleSet",
    "BinaryPattern", "CallPattern", "LiteralPattern", "Matcher", "Pattern", "RewriteError", "RewriteResult",
    "RewriteRule", "RewriteStrategy", "Rewriter", "RuleCondition", "UnaryPattern", "Wildcard", "rewrite",
    "format_pattern", "format_rule_set",
    "NumericError", "evaluate_numeric",
]
