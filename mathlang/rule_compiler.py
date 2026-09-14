"""Elaborate syntax templates into patterns with local wildcard bindings."""

from . import ast
from .environment import Environment
from .rewriting import (
    BinaryPattern, CallPattern, LiteralPattern, Pattern, RewriteRule, RuleCondition,
    UnaryPattern, Wildcard,
)
from .source import DefinitionError, SourceSpan
from .terms import Function, RuleSet, Symbol, SymbolKind, TermFactory


class RuleCompiler:
    def __init__(self, environment: Environment, factory: TermFactory, source: str) -> None:
        self.environment = environment
        self.factory = factory
        self.source = source

    def error(self, message: str, node: ast.Node) -> DefinitionError:
        return DefinitionError(message, self.source, node.span or SourceSpan(0, 0, 1, 1))

    def compile(self, declaration: ast.RuleDeclaration) -> RuleSet:
        rules: list[RewriteRule] = []
        for clause in declaration.clauses:
            wildcards: dict[str, Wildcard] = {}
            pattern = self.template(clause.pattern, wildcards, left=True)
            replacement = self.template(clause.replacement, wildcards)
            condition = None
            if clause.condition is not None:
                condition = RuleCondition(
                    self.template(clause.condition.left, wildcards), clause.condition.op,
                    self.template(clause.condition.right, wildcards),
                )
            rules.append(RewriteRule(pattern, replacement, condition))
        return RuleSet(declaration.name, tuple(rules))

    def template(self, node: ast.Expr, wildcards: dict[str, Wildcard], *,
                 left: bool = False, callee: bool = False) -> Pattern:
        match node:
            case ast.NumberLiteral(text=text):
                try:
                    return LiteralPattern(self.factory.number(text))
                except ValueError:
                    raise self.error("Number literal is too large to convert", node) from None
            case ast.Identifier(name=name):
                if name in wildcards:
                    return wildcards[name]
                definition = self.environment.get(name)
                symbolic = (definition is None or (not callee and definition.symbol.kind in (
                    SymbolKind.VARIABLE, SymbolKind.PARAMETER, SymbolKind.UNKNOWN,
                )))
                if left and symbolic:
                    wildcard = Wildcard(name)
                    wildcards[name] = wildcard
                    return wildcard
                if definition is None:
                    raise self.error(f"Unbound name {name!r} in rule replacement or condition", node)
                value = definition.term
                if callee:
                    if isinstance(value, Symbol) and value.kind == SymbolKind.BUILTIN:
                        if value.name in ("normalize", "simplify", "substitute", "rewrite", "print",
                                         "derivative", "integrate", "series", "limit", "polynomial", "query", "domain",
                                         "iterate", "sum", "product", "all", "any", "factorial", "antiderivative"):
                            raise self.error("Rule templates cannot execute transformations; apply them after rewriting", node)
                    elif isinstance(value, Function):
                        raise self.error("Rule calls require a symbolic Function declaration; defined functions expand before matching", node)
                    elif not isinstance(value, Symbol) or (value.annotation is not None
                                                          and value.annotation.name != "Function"):
                        raise self.error("A rule call requires a symbolic function", node)
                return LiteralPattern(value)
            case ast.UnaryExpr(op=op, operand=operand):
                return UnaryPattern(op, self.template(operand, wildcards, left=left))
            case ast.BinaryExpr(op=op, left=lhs, right=rhs):
                return BinaryPattern(op, self.template(lhs, wildcards, left=left),
                                     self.template(rhs, wildcards, left=left))
            case ast.CallExpr(callee=function, arguments=arguments, keywords=keywords):
                if keywords:
                    raise self.error("Rule patterns support only positional calls", node)
                return CallPattern(self.template(function, wildcards, left=left, callee=True), tuple(
                    self.template(argument, wildcards, left=left) for argument in arguments
                ))
            case _:
                raise self.error("Rule templates support arithmetic and symbolic function calls", node)
