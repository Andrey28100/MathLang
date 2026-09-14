"""Recursive descent parsers for expressions and definition programs."""

from dataclasses import replace

from .ast import (
    ForAllExpr, TheoryDeclaration, OperationDeclaration, AxiomDeclaration,
    ImplementationDeclaration, ImplementationBinding,
    TruthLiteral, ComparisonExpr, LogicalExpr, AssumeStatement, AssumingStatement,
    FunctionParameter, TypedFunctionDefinition, ReturnStatement,
    ModuleDeclaration, ImportStatement, ImportName, NamespaceDeclaration,
    ApproachExpr, LambdaExpr,
    AlgebraDeclaration, RelationDeclaration, ProveStatement, WithStatement, UseStatement,
    Assignment, BinaryExpr, CallExpr, Declaration, Expr, ExpressionStatement,
    FunctionDefinition, Identifier, KeywordArgument, NumberLiteral, PipelineExpr,
    Program, RewriteExpr, RuleClause, RuleConditionExpr, RuleDeclaration,
    Statement, SubstitutionExpr, TypeRef, UnaryExpr,
)
from .lexer import Token, TokenKind, tokenize
from .source import ParseError
from .symbols import canonical_name


_DECLARATIONS = {"const", "parameter", "variable", "unknown"}
_RESERVED = _DECLARATIONS | {"where", "rule", "using", "when", "algebra", "over",
                           "generator", "generators", "relation", "relations", "basis", "derive",
                           "assert", "with", "use", "prove", "module", "import", "namespace", "as", "function", "return"}
_STRATEGIES = {"once", "bottom_up", "top_down", "recursively"}
_RESERVED |= {'assume', 'assuming', 'and', 'or', 'not', 'True', 'False', 'Unknown'}
_RESERVED |= {'theory', 'operation', 'axiom', 'implementation', 'implements', 'extends', 'forall'}
_COMPARISONS = {TokenKind.EQUAL, TokenKind.EQEQ, TokenKind.STRUCTURAL,
                TokenKind.NOTEQUAL, TokenKind.LESS, TokenKind.LESSEQUAL,
                TokenKind.GREATER, TokenKind.GREATEREQUAL}


class _Parser:
    def __init__(self, source: str, *, program: bool = False) -> None:
        self.source = source
        self.tokens = tokenize(source, keep_newlines=program)
        self.index = 0
        self.group_depth = 0
        self.allow_equal = True

    def without_equal(self, parse):
        saved = self.allow_equal
        self.allow_equal = False
        try:
            return parse()
        finally:
            self.allow_equal = saved

    @property
    def current(self) -> Token:
        while self.group_depth and self.tokens[self.index].kind == TokenKind.NEWLINE:
            self.index += 1
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def expect(self, kind: TokenKind) -> Token:
        if self.current.kind != kind:
            raise self.error(f"Expected {kind.value!r}")
        return self.advance()

    def error(self, message: str) -> ParseError:
        found = repr(self.current.text) if self.current.text else "end of input"
        return ParseError(f"{message}, found {found}", self.source, self.current.span)

    def parse(self) -> Expr:
        expression = self.pipeline()
        if self.current.kind != TokenKind.EOF:
            raise self.error("Expected an operator or end of input")
        return expression

    def skip_newlines(self) -> None:
        while self.current.kind == TokenKind.NEWLINE:
            self.advance()

    def name(self) -> Token:
        if self.current.text in _RESERVED:
            raise self.error("Expected a name, not a keyword")
        token = self.expect(TokenKind.IDENTIFIER)
        return replace(token, text=canonical_name(token.text))

    def qualified_name(self) -> Identifier:
        token = self.name()
        name, span = token.text, token.span
        while self.current.kind == TokenKind.DOT:
            self.advance()
            member = self.expect(TokenKind.IDENTIFIER)
            name += "." + canonical_name(member.text)
            span = span.through(member.span)
        return Identifier(name, span=span)

    def program(self, *, block: bool = False) -> Program:
        statements: list[Statement] = []
        separators = (TokenKind.NEWLINE, TokenKind.SEMICOLON)
        while self.current.kind in separators:
            self.advance()
        start = self.current.span
        ends = (TokenKind.EOF, TokenKind.RBRACE) if block else (TokenKind.EOF,)
        while self.current.kind not in ends:
            statement = self.statement()
            if isinstance(statement, ModuleDeclaration) and (block or statements):
                raise ParseError("module must be the first statement of a file or input",
                                 self.source, statement.span)
            statements.append(statement)
            if self.current.kind not in (*separators, *ends):
                raise self.error("Expected a newline, ';' or end of input")
            while self.current.kind in separators:
                self.advance()
        return Program(tuple(statements), span=start.through(self.current.span))

    def statement(self) -> Statement:
        if self.current.text == 'theory':
            return self.theory_declaration()
        if self.current.text == 'implementation':
            return self.implementation_declaration()
        if self.current.text == 'assume':
            start = self.advance().span
            condition = self.pipeline()
            return AssumeStatement(condition, span=start.through(condition.span))
        if self.current.text == 'assuming':
            start = self.advance().span
            self.skip_newlines()
            self.expect(TokenKind.LBRACE)
            self.separators()
            conditions = []
            while self.current.kind != TokenKind.RBRACE:
                if self.current.text == 'assume':
                    self.advance()
                conditions.append(self.pipeline())
                if self.current.kind == TokenKind.COMMA:
                    self.advance()
                elif self.current.kind not in (TokenKind.NEWLINE, TokenKind.SEMICOLON, TokenKind.RBRACE):
                    raise self.error('Expected a separator between assumptions')
                self.separators()
            self.advance()
            self.skip_newlines()
            self.expect(TokenKind.LBRACE)
            body = self.program(block=True)
            end = self.expect(TokenKind.RBRACE).span
            return AssumingStatement(tuple(conditions), body, span=start.through(end))
        if self.current.text == "function":
            return self.function_declaration()
        if self.current.text == "return":
            start = self.advance().span
            value = self.pipeline()
            return ReturnStatement(value, span=start.through(value.span))
        if self.current.text == "module":
            start = self.advance().span
            name = self.qualified_name()
            return ModuleDeclaration(name.name, span=start.through(name.span))
        if self.current.text == "namespace":
            start = self.advance().span
            name = self.name()
            self.skip_newlines()
            self.expect(TokenKind.LBRACE)
            body = self.program(block=True)
            end = self.expect(TokenKind.RBRACE).span
            return NamespaceDeclaration(name.text, body, span=start.through(end))
        if self.current.text == "import":
            return self.import_statement()
        if self.current.text == "algebra":
            return self.algebra_declaration()
        if self.current.text == "prove":
            return self.prove_statement()
        if self.current.text in ("with", "use"):
            start = self.advance()
            algebra = self.qualified_name()
            if start.text == "use":
                return UseStatement(algebra, span=start.span.through(algebra.span))
            self.skip_newlines()
            self.expect(TokenKind.LBRACE)
            body = self.program(block=True)
            end = self.expect(TokenKind.RBRACE).span
            return WithStatement(algebra, body, span=start.span.through(end))
        if self.current.text == "rule":
            return self.rule_declaration()
        if self.current.text in _DECLARATIONS:
            return self.declaration()
        if (self.current.kind == TokenKind.IDENTIFIER
                and self.tokens[self.index + 1].kind == TokenKind.COLON):
            return self.declaration(bare=True)
        target = self.without_equal(self.pipeline)
        if self.current.kind != TokenKind.EQUAL:
            return ExpressionStatement(target, span=target.span)
        self.advance()
        if isinstance(target, Identifier):
            if "." in target.name:
                raise ParseError("Define namespace members inside their namespace block", self.source, target.span)
            value = self.without_equal(self.pipeline)
            assert target.span is not None and value.span is not None
            return Assignment(target.name, value, span=target.span.through(value.span))
        if isinstance(target, CallExpr) and isinstance(target.callee, Identifier):
            if "." in target.callee.name:
                raise ParseError("Define namespace functions inside their namespace block", self.source, target.span)
            if target.keywords:
                raise self.error("Function parameters must be names without values")
            parameters: list[Identifier] = []
            names: set[str] = set()
            for argument in target.arguments:
                if not isinstance(argument, Identifier) or argument.name in names:
                    assert argument.span is not None
                    raise ParseError("Function parameters must be distinct names",
                                     self.source, argument.span)
                names.add(argument.name)
                parameters.append(argument)
            body = self.without_equal(self.pipeline)
            assert target.span is not None and body.span is not None
            return FunctionDefinition(target.callee.name, tuple(parameters), body,
                                      span=target.span.through(body.span))
        assert target.span is not None
        raise ParseError('Only a name or function signature can be assigned; use == for equality',
                         self.source, target.span)

    def parameters(self) -> tuple[FunctionParameter, ...]:
        self.expect(TokenKind.LPAREN)
        self.group_depth += 1
        result, names = [], set()
        while self.current.kind != TokenKind.RPAREN:
            token = self.name()
            annotation, end = None, token.span
            if token.text in names:
                raise self.error("Function parameters must be distinct names")
            names.add(token.text)
            if self.current.kind == TokenKind.COLON:
                self.advance()
                annotation = self.type_ref()
                end = annotation.span
            result.append(FunctionParameter(token.text, annotation, span=token.span.through(end)))
            if self.current.kind != TokenKind.COMMA:
                break
            self.advance()
        self.expect(TokenKind.RPAREN)
        self.group_depth -= 1
        return tuple(result)

    def operation_name(self):
        if self.current.kind == TokenKind.LPAREN:
            self.advance()
            if self.current.kind not in (TokenKind.PLUS, TokenKind.MINUS, TokenKind.STAR, TokenKind.SLASH, TokenKind.CARET):
                raise self.error('Expected a supported arithmetic operator')
            name = self.advance().text
            self.expect(TokenKind.RPAREN)
            return name
        return self.name().text

    def member_separator(self):
        if self.current.kind not in (TokenKind.NEWLINE, TokenKind.SEMICOLON, TokenKind.RBRACE):
            raise self.error("Expected a newline, ';' or '}' after a member")
        while self.current.kind in (TokenKind.NEWLINE, TokenKind.SEMICOLON):
            self.advance()

    def theory_declaration(self):
        start = self.advance().span
        name = self.name().text
        self.expect(TokenKind.LESS)
        parameters = [self.name().text]
        while self.current.kind == TokenKind.COMMA:
            self.advance()
            parameters.append(self.name().text)
        self.expect(TokenKind.GREATER)
        self.skip_newlines()
        parents = []
        if self.current.text == 'extends':
            self.advance()
            self.skip_newlines()
            parents.append(self.type_ref())
            while self.current.kind == TokenKind.COMMA:
                self.advance()
                self.skip_newlines()
                parents.append(self.type_ref())
            self.skip_newlines()
        self.expect(TokenKind.LBRACE)
        self.separators()
        operations, constants, axioms = [], [], []
        while self.current.kind != TokenKind.RBRACE:
            member_start = self.current.span
            if self.current.text == 'operation':
                self.advance()
                operation = self.operation_name()
                self.expect(TokenKind.COLON)
                self.skip_newlines()
                inputs = [self.type_ref()]
                while self.current.text in ('x', '×'):
                    self.advance()
                    inputs.append(self.type_ref())
                self.expect(TokenKind.ARROW)
                output = self.type_ref()
                operations.append(OperationDeclaration(operation, tuple(inputs), output, span=member_start.through(output.span)))
            elif self.current.text == 'const':
                declaration = self.declaration()
                if declaration.annotation is None or declaration.value is not None:
                    raise self.error('A theory constant requires a type and no value')
                constants.append(declaration)
            elif self.current.text == 'axiom':
                self.advance()
                axiom = self.name().text
                self.skip_newlines()
                self.expect(TokenKind.LBRACE)
                self.skip_newlines()
                predicate = self.pipeline()
                self.skip_newlines()
                end = self.expect(TokenKind.RBRACE).span
                axioms.append(AxiomDeclaration(axiom, predicate, span=member_start.through(end)))
            else:
                raise self.error('Expected operation, const or an axiom with an explicit body')
            self.member_separator()
        end = self.advance().span
        return TheoryDeclaration(name, tuple(parameters), tuple(operations), tuple(constants), tuple(axioms), tuple(parents), span=start.through(end))

    def implementation_declaration(self):
        start = self.advance().span
        name = self.name().text
        if self.current.text != 'implements':
            raise self.error('Expected implements and a concrete theory type')
        self.advance()
        theory = self.type_ref()
        self.skip_newlines()
        self.expect(TokenKind.LBRACE)
        self.skip_newlines()
        bindings, assumptions = [], []
        while self.current.kind != TokenKind.RBRACE:
            member_start = self.current.span
            if self.current.text == 'assume':
                self.advance()
                assumptions.append(self.name().text)
            elif self.current.text in ('operation', 'const'):
                operation = self.advance().text == 'operation'
                member = self.operation_name() if operation else self.name().text
                self.expect(TokenKind.EQUAL)
                value = self.without_equal(self.pipeline)
                bindings.append(ImplementationBinding(member, value, operation, span=member_start.through(value.span)))
            else:
                raise self.error('Expected an operation binding, constant binding or axiom assumption')
            self.member_separator()
        end = self.advance().span
        return ImplementationDeclaration(name, theory, tuple(bindings), tuple(assumptions), span=start.through(end))

    def function_declaration(self) -> TypedFunctionDefinition:
        start = self.advance().span
        name = self.name()
        parameters = self.parameters()
        self.skip_newlines()
        result_type = None
        if self.current.kind == TokenKind.COLON:
            self.advance()
            result_type = self.type_ref()
        self.skip_newlines()
        self.expect(TokenKind.LBRACE)
        body = self.program(block=True)
        end = self.expect(TokenKind.RBRACE).span
        return TypedFunctionDefinition(name.text, parameters, result_type, body, span=start.through(end))

    def parenthesized_lambda(self) -> bool:
        if self.current.kind != TokenKind.LPAREN:
            return False
        depth, index = 0, self.index
        while index < len(self.tokens):
            kind = self.tokens[index].kind
            if kind == TokenKind.LPAREN:
                depth += 1
            elif kind == TokenKind.RPAREN:
                depth -= 1
                if depth == 0:
                    index += 1
                    while self.tokens[index].kind == TokenKind.NEWLINE:
                        index += 1
                    return self.tokens[index].kind == TokenKind.FATARROW
            elif kind == TokenKind.EOF:
                return False
            index += 1
        return False

    def import_statement(self) -> ImportStatement:
        start = self.advance().span
        module = self.qualified_name()
        alias, names, end = None, [], module.span
        if self.current.text == "as":
            self.advance()
            token = self.name()
            alias, end = token.text, token.span
        index = self.index
        while self.tokens[index].kind == TokenKind.NEWLINE:
            index += 1
        if self.tokens[index].kind == TokenKind.LBRACE:
            if alias is not None:
                raise self.error("Choose a module alias or selective import")
            self.index = index + 1
            self.separators()
            while self.current.kind != TokenKind.RBRACE:
                token = self.name()
                name_alias, end = None, token.span
                if self.current.text == "as":
                    self.advance()
                    renamed = self.name()
                    name_alias, end = renamed.text, renamed.span
                names.append(ImportName(token.text, name_alias, span=token.span.through(end)))
                if self.current.kind == TokenKind.COMMA:
                    self.advance()
                elif self.current.kind not in (TokenKind.NEWLINE, TokenKind.SEMICOLON, TokenKind.RBRACE):
                    raise self.error("Expected a separator between imported names")
                self.separators()
            end = self.advance().span
            if not names:
                raise self.error("A selective import must not be empty")
            targets = [item.alias or item.name for item in names]
            if len(set(targets)) != len(targets):
                raise self.error("Imported names must be distinct")
        return ImportStatement(module.name, alias, tuple(names), span=start.through(end))

    def separators(self) -> None:
        while self.current.kind in (TokenKind.NEWLINE, TokenKind.SEMICOLON):
            self.advance()

    def relation(self) -> RelationDeclaration:
        left = self.without_equal(self.pipeline)
        self.skip_newlines()
        self.expect(TokenKind.EQUAL)
        right = self.pipeline()
        return RelationDeclaration(left, right, span=left.span.through(right.span))

    def relation_block(self) -> tuple[RelationDeclaration, ...]:
        self.skip_newlines()
        if self.current.kind != TokenKind.LBRACE:
            return (self.relation(),)
        self.advance()
        self.separators()
        result = []
        while self.current.kind != TokenKind.RBRACE:
            result.append(self.relation())
            if self.current.kind == TokenKind.COMMA:
                self.advance()
            elif self.current.kind not in (TokenKind.NEWLINE, TokenKind.SEMICOLON, TokenKind.RBRACE):
                raise self.error("Expected a separator after an equality")
            self.separators()
        self.advance()
        if not result:
            raise self.error("An equality block must not be empty")
        return tuple(result)

    def generator_list(self) -> tuple[Identifier, ...]:
        self.skip_newlines()
        block = self.current.kind == TokenKind.LBRACE
        if block:
            self.advance()
            self.separators()
        result = []
        while True:
            token = self.name()
            result.append(Identifier(token.text, span=token.span))
            if self.current.kind == TokenKind.COMMA:
                self.advance()
                self.skip_newlines()
            elif block and self.current.kind in (TokenKind.NEWLINE, TokenKind.SEMICOLON):
                self.separators()
            else:
                break
            if block and self.current.kind == TokenKind.RBRACE:
                break
        if block:
            self.expect(TokenKind.RBRACE)
        return tuple(result)

    def prove_statement(self) -> ProveStatement:
        start = self.advance().span
        self.skip_newlines()
        if self.current.text == "multiplication":
            self.advance()
            property = self.name()
            if property.text not in ("associative", "commutative"):
                raise self.error("Expected associative or commutative")
            return ProveStatement(property_name=property.text, span=start.through(property.span))
        goals = self.relation_block()
        return ProveStatement(goals, span=start.through(goals[-1].span))

    def algebra_declaration(self) -> AlgebraDeclaration:
        start = self.advance().span
        name = self.name().text
        if self.current.text != "over":
            raise self.error("Expected 'over' and a scalar domain")
        self.advance()
        domain = self.type_ref()
        self.skip_newlines()
        self.expect(TokenKind.LBRACE)
        generators, relations, proofs = [], [], []
        basis = None
        derive = bilinear = False
        self.separators()
        while self.current.kind != TokenKind.RBRACE:
            keyword = self.current.text
            if keyword in ("generator", "generators"):
                self.advance()
                generators.extend(self.generator_list())
            elif keyword in ("relation", "relations"):
                self.advance()
                self.skip_newlines()
                if keyword == "relations" and self.current.kind != TokenKind.LBRACE:
                    raise self.error("Expected '{' after 'relations'")
                relations.extend(self.relation_block())
            elif keyword in ("basis", "assert", "derive"):
                self.advance()
                if keyword in ("assert", "derive"):
                    if self.current.text != "basis":
                        raise self.error("Expected 'basis'")
                    self.advance()
                if basis is not None or derive:
                    raise self.error("Basis was already specified")
                if keyword == "derive":
                    derive = True
                else:
                    self.skip_newlines()
                    self.expect(TokenKind.LBRACE)
                    items = []
                    self.separators()
                    while self.current.kind != TokenKind.RBRACE:
                        items.append(self.additive())
                        if self.current.kind == TokenKind.COMMA:
                            self.advance()
                        elif self.current.kind not in (TokenKind.NEWLINE, TokenKind.SEMICOLON, TokenKind.RBRACE):
                            raise self.error("Expected a basis separator")
                        self.separators()
                    self.advance()
                    basis = tuple(items)
            elif keyword == "multiplication":
                self.advance()
                if self.current.text != "bilinear":
                    raise self.error("Expected 'bilinear'")
                self.advance()
                bilinear = True
            elif keyword == "prove":
                proofs.append(self.prove_statement())
            else:
                raise self.error("Expected generators, relations, basis, multiplication or proof declaration")
            if self.current.kind not in (TokenKind.NEWLINE, TokenKind.SEMICOLON, TokenKind.RBRACE):
                raise self.error("Expected a separator in algebra declaration")
            self.separators()
        end = self.advance().span
        return AlgebraDeclaration(name, domain, tuple(generators), tuple(relations), basis,
                                  derive, bilinear, tuple(proofs), span=start.through(end))

    def rule_declaration(self) -> RuleDeclaration:
        start = self.advance().span
        self.skip_newlines()
        name = None if self.current.kind == TokenKind.LBRACE else self.name().text
        self.skip_newlines()
        self.expect(TokenKind.LBRACE)
        clauses: list[RuleClause] = []
        separators = (TokenKind.NEWLINE, TokenKind.SEMICOLON)
        while self.current.kind in separators:
            self.advance()
        while self.current.kind != TokenKind.RBRACE:
            pattern = self.additive()
            self.skip_newlines()
            self.expect(TokenKind.ARROW)
            replacement = self.additive()
            condition = None
            end = replacement.span
            index = self.index
            while self.tokens[index].kind == TokenKind.NEWLINE:
                index += 1
            if self.tokens[index].text == "when":
                self.index = index + 1
                left = self.additive()
                if self.current.kind not in (TokenKind.EQEQ, TokenKind.NOTEQUAL, TokenKind.LESS,
                                             TokenKind.LESSEQUAL, TokenKind.GREATER, TokenKind.GREATEREQUAL):
                    raise self.error("Expected a comparison in the rule condition")
                op = self.advance()
                right = self.additive()
                assert left.span is not None and right.span is not None
                condition = RuleConditionExpr(left, op.text, right, span=left.span.through(right.span))
                end = right.span
            assert pattern.span is not None and end is not None
            clauses.append(RuleClause(pattern, replacement, condition, span=pattern.span.through(end)))
            if self.current.kind not in (*separators, TokenKind.RBRACE):
                raise self.error("Expected a newline, ';' or '}' after a rule")
            while self.current.kind in separators:
                self.advance()
        end = self.advance().span
        if not clauses:
            raise ParseError("A rule block must not be empty", self.source, start.through(end))
        return RuleDeclaration(name, tuple(clauses), span=start.through(end))

    def rewrite_suffix(self, expression: Expr, start) -> RewriteExpr:
        rules = None
        strategy = "bottom_up"
        repeat = False
        selected = False
        end = expression.span
        if self.current.text == "using":
            self.advance()
            name = self.name()
            rules = Identifier(name.text, span=name.span)
            end = name.span
        while self.current.text in _STRATEGIES:
            token = self.advance()
            end = token.span
            if token.text == "recursively":
                if repeat:
                    raise self.error("Duplicate recursive rewrite modifier")
                repeat = True
            else:
                if selected:
                    raise self.error("Select only one rewrite traversal strategy")
                strategy = token.text
                selected = True
        if strategy == "once" and repeat:
            raise self.error("'once' cannot be combined with recursive rewriting")
        assert end is not None
        return RewriteExpr(expression, rules, strategy, repeat, span=start.through(end))

    def declaration(self, *, bare: bool = False) -> Declaration:
        start = self.current.span
        kind = "variable" if bare else self.advance().text
        name = self.name()
        annotation = None
        value = None
        end = name.span
        if self.current.kind == TokenKind.COLON:
            self.advance()
            annotation = self.type_ref()
            assert annotation.span is not None
            end = annotation.span
        elif kind != "const":
            raise self.error("Expected ':' and a type annotation")
        if self.current.kind == TokenKind.EQUAL:
            if kind != "const":
                raise self.error(f"{kind!r} declares a symbolic name without a value")
            self.advance()
            value = self.without_equal(self.pipeline)
            assert value.span is not None
            end = value.span
        elif kind == "const" and annotation is None:
            raise self.error("Expected '=' and a constant expression")
        return Declaration(kind, name.text, annotation, value, span=start.through(end))

    def type_ref(self) -> TypeRef:
        self.skip_newlines()
        name = self.qualified_name()
        arguments: list[TypeRef | NumberLiteral] = []
        end = name.span
        if self.current.kind == TokenKind.LESS:
            self.advance()
            self.group_depth += 1
            while True:
                if (self.current.kind == TokenKind.NUMBER
                        and self.current.text.isdecimal()):
                    number = self.advance()
                    arguments.append(NumberLiteral(number.text, span=number.span))
                else:
                    arguments.append(self.type_ref())
                if self.current.kind != TokenKind.COMMA:
                    break
                self.advance()
            end = self.expect(TokenKind.GREATER).span
            self.group_depth -= 1
        return TypeRef(name.name, tuple(arguments), span=name.span.through(end))

    def additive(self) -> Expr:
        left = self.multiplicative()
        while self.current.kind in (TokenKind.PLUS, TokenKind.MINUS):
            op = self.advance()
            left = self.binary(left, op, self.multiplicative())
        return left

    def pipeline(self) -> Expr:
        self.skip_newlines()
        if self.parenthesized_lambda():
            start = self.current.span
            parameters = self.parameters()
            self.skip_newlines()
            self.expect(TokenKind.FATARROW)
            body = self.pipeline()
            return LambdaExpr(parameters, body, span=start.through(body.span))
        if (self.current.kind == TokenKind.IDENTIFIER
                and self.tokens[self.index+1].kind == TokenKind.FATARROW):
            parameter = self.name()
            self.advance()
            body = self.pipeline()
            return LambdaExpr((FunctionParameter(parameter.text, span=parameter.span),), body,
                              span=parameter.span.through(body.span))
        left = self.logical_or()
        while True:
            # A leading pipeline operator is an unambiguous continuation of a
            # complete expression, including at top level in a multiline file.
            index = self.index
            while self.tokens[index].kind == TokenKind.NEWLINE:
                index += 1
            if self.tokens[index].kind != TokenKind.PIPELINE:
                break
            self.index = index + 1
            self.skip_newlines()
            target = self.call()
            if not isinstance(target, (Identifier, CallExpr)):
                raise self.error("Expected a function after '|>'")
            assert left.span is not None and target.span is not None
            left = PipelineExpr(left, target, span=left.span.through(target.span))
        return left

    def logical_or(self):
        left = self.logical_and()
        while self.current.text == 'or':
            self.advance()
            right = self.logical_and()
            left = LogicalExpr('or', (left, right), span=left.span.through(right.span))
        return left

    def logical_and(self):
        left = self.logical_not()
        while self.current.text == 'and':
            self.advance()
            right = self.logical_not()
            left = LogicalExpr('and', (left, right), span=left.span.through(right.span))
        return left

    def logical_not(self):
        self.skip_newlines()
        if self.current.text == 'not':
            start = self.advance().span
            operand = self.logical_not()
            return LogicalExpr('not', (operand,), span=start.through(operand.span))
        left = self.where()
        comparisons = _COMPARISONS if self.allow_equal else _COMPARISONS - {TokenKind.EQUAL}
        if self.current.kind in comparisons:
            op = self.advance()
            self.skip_newlines()
            right = self.where()
            left = ComparisonExpr(op.text, left, right, span=left.span.through(right.span))
            if self.current.kind in comparisons:
                raise self.error('Use and between comparisons; comparison chains are not supported')
        return left

    def keyword(self) -> KeywordArgument:
        name = self.name()
        self.expect(TokenKind.EQUAL)
        value = self.pipeline()
        assert value.span is not None
        return KeywordArgument(name.text, value, span=name.span.through(value.span))

    def where(self) -> Expr:
        expression = self.additive()
        if self.current.text != "where":
            return expression
        self.advance()
        self.skip_newlines()
        replacements: list[KeywordArgument] = []
        if self.current.kind == TokenKind.LBRACE:
            self.advance()
            # Curly substitution blocks use line separators even inside calls.
            saved_depth = self.group_depth
            self.group_depth = 0
            separators = (TokenKind.NEWLINE, TokenKind.SEMICOLON, TokenKind.COMMA)
            while self.current.kind in separators:
                self.advance()
            while self.current.kind != TokenKind.RBRACE:
                replacements.append(self.keyword())
                if self.current.kind not in (*separators, TokenKind.RBRACE):
                    raise self.error("Expected a substitution separator or '}'")
                while self.current.kind in separators:
                    self.advance()
            end = self.advance().span
            self.group_depth = saved_depth
            if not replacements:
                raise self.error("Expected at least one substitution")
        else:
            # A following pipeline applies to the substituted expression.
            name = self.name()
            self.expect(TokenKind.EQUAL)
            value = self.additive()
            assert value.span is not None
            replacements.append(KeywordArgument(name.text, value, span=name.span.through(value.span)))
            end = value.span
        names = [item.name for item in replacements]
        if len(set(names)) != len(names):
            raise self.error("Substitution targets must be distinct names")
        assert expression.span is not None
        return SubstitutionExpr(expression, tuple(replacements), span=expression.span.through(end))

    def multiplicative(self) -> Expr:
        left = self.unary()
        while self.current.kind in (TokenKind.STAR, TokenKind.SLASH):
            op = self.advance()
            left = self.binary(left, op, self.unary())
        return left

    def unary(self) -> Expr:
        self.skip_newlines()
        if self.current.kind in (TokenKind.PLUS, TokenKind.MINUS):
            op = self.advance()
            operand = self.unary()
            assert operand.span is not None
            return UnaryExpr(op.text, operand, span=op.span.through(operand.span))
        return self.power()

    def power(self) -> Expr:
        left = self.call()
        if self.current.kind == TokenKind.CARET:
            op = self.advance()
            # Right associativity, with signed exponents: 2^3^2 and 2^-3.
            return self.binary(left, op, self.unary())
        return left

    def call(self) -> Expr:
        callee = self.primary()
        while self.current.kind == TokenKind.LPAREN:
            self.advance()
            self.group_depth += 1
            arguments: list[Expr] = []
            keywords: list[KeywordArgument] = []
            names: set[str] = set()
            if self.current.kind != TokenKind.RPAREN:
                while True:
                    token = self.current
                    if (token.kind == TokenKind.IDENTIFIER
                            and self.tokens[self.index + 1].kind == TokenKind.EQUAL):
                        keyword = self.keyword()
                        if keyword.name in names:
                            raise self.error("Named arguments must be distinct")
                        names.add(keyword.name)
                        keywords.append(keyword)
                    else:
                        if keywords:
                            raise self.error("Positional arguments must precede named arguments")
                        argument = self.pipeline()
                        if self.current.kind == TokenKind.ARROW:
                            self.advance()
                            point = self.pipeline()
                            argument = ApproachExpr(argument, point, span=argument.span.through(point.span))
                        arguments.append(argument)
                    if self.current.kind != TokenKind.COMMA:
                        break
                    self.advance()
            end = self.expect(TokenKind.RPAREN)
            self.group_depth -= 1
            assert callee.span is not None
            callee = CallExpr(
                callee, tuple(arguments), tuple(keywords), span=callee.span.through(end.span),
            )
        if (isinstance(callee, CallExpr) and isinstance(callee.callee, Identifier)
                and callee.callee.name == "rewrite"
                and self.current.text in ({"using"} | _STRATEGIES)):
            if len(callee.arguments) != 1 or callee.keywords:
                raise self.error("Prefix rewrite expects one expression")
            return self.rewrite_suffix(callee.arguments[0], callee.span)
        if isinstance(callee, CallExpr) and self.current.kind == TokenKind.LBRACE:
            # Trailing expression blocks pass their lambda as the first argument.
            # iterate(seed,n) {(state:Real,index:Nat)=>...} is an ordinary call IR.
            start = self.advance().span
            saved_depth = self.group_depth
            self.group_depth = 0
            self.skip_newlines()
            body = self.pipeline()
            self.skip_newlines()
            end = self.expect(TokenKind.RBRACE).span
            self.group_depth = saved_depth
            if not isinstance(body, LambdaExpr):
                raise ParseError('An iteration block requires an explicit lambda, such as (state:Real,index:Nat)=>state+index',
                                 self.source, start.through(end))
            callee = CallExpr(callee.callee, (body, *callee.arguments), callee.keywords,
                              span=callee.span.through(end))
        return callee

    def primary(self) -> Expr:
        if self.current.text == 'forall':
            start = self.advance().span
            parameters = []
            while True:
                names = [self.name()]
                while self.current.kind == TokenKind.COMMA:
                    self.advance()
                    names.append(self.name())
                self.expect(TokenKind.COLON)
                annotation = self.type_ref()
                parameters.extend(FunctionParameter(n.text, annotation, span=n.span.through(annotation.span)) for n in names)
                if self.current.kind != TokenKind.COMMA:
                    break
                self.advance()
            if len({p.name for p in parameters}) != len(parameters):
                raise self.error('Quantified variables must have distinct names')
            self.expect(TokenKind.COLON)
            saved = self.allow_equal
            self.allow_equal = True
            try:
                body = self.pipeline()
            finally:
                self.allow_equal = saved
            return ForAllExpr(tuple(parameters), body, span=start.through(body.span))
        token = self.current
        if token.text == "rewrite" and self.is_rewrite_prefix():
            self.advance()
            expression = self.where()
            return self.rewrite_suffix(expression, token.span)
        if token.text in ('True', 'False', 'Unknown'):
            self.advance()
            return TruthLiteral(token.text, span=token.span)
        if token.kind == TokenKind.NUMBER:
            self.advance()
            return NumberLiteral(token.text, span=token.span)
        if token.kind == TokenKind.IDENTIFIER:
            token = self.name()
            name, span = token.text, token.span
            while self.current.kind == TokenKind.DOT:
                self.advance()
                member = self.expect(TokenKind.IDENTIFIER)
                name += "." + canonical_name(member.text)
                span = span.through(member.span)
            return Identifier(name, span=span)
        if token.kind == TokenKind.LPAREN:
            self.advance()
            self.group_depth += 1
            saved = self.allow_equal
            self.allow_equal = True
            expression = self.pipeline()
            self.allow_equal = saved
            end = self.expect(TokenKind.RPAREN)
            self.group_depth -= 1
            # Grouping affects the tree and span, but needs no separate AST node.
            return replace(expression, span=token.span.through(end.span))
        raise self.error("Expected a number, identifier or '('")

    def is_rewrite_prefix(self) -> bool:
        following = self.tokens[self.index+1].kind
        if following in (TokenKind.IDENTIFIER, TokenKind.NUMBER, TokenKind.PLUS, TokenKind.MINUS):
            return True
        if following != TokenKind.LPAREN:
            return False
        # `rewrite (x+0)+0 using r` is a prefix expression, while
        # `rewrite(x, r)+0` is an ordinary call. Modifiers disambiguate grouping.
        depth = 0
        for token in self.tokens[self.index+1:]:
            if depth == 0:
                if token.text in ({"using"} | _STRATEGIES):
                    return True
                if token.kind in (TokenKind.RPAREN, TokenKind.RBRACE, TokenKind.COMMA,
                                  TokenKind.NEWLINE, TokenKind.SEMICOLON, TokenKind.EQUAL,
                                  TokenKind.PIPELINE, TokenKind.EOF):
                    return False
            if token.kind == TokenKind.LPAREN:
                depth += 1
            elif token.kind == TokenKind.RPAREN:
                depth -= 1
            elif depth == 1 and token.kind in (TokenKind.COMMA, TokenKind.EQUAL):
                return False
        return False

    @staticmethod
    def binary(left: Expr, op: Token, right: Expr) -> BinaryExpr:
        assert left.span is not None and right.span is not None
        return BinaryExpr(op.text, left, right, span=left.span.through(right.span))


def parse_expression(source: str) -> Expr:
    """Parse the entire string into an immutable AST, without evaluating it."""
    parser = _Parser(source)
    try:
        return parser.parse()
    except RecursionError:
        raise parser.error("Expression nesting is too deep") from None


def parse_program(source: str) -> Program:
    """Parse declarations, definitions and expressions separated by newlines or ';'."""
    parser = _Parser(source, program=True)
    try:
        return parser.program()
    except RecursionError:
        raise parser.error("Program nesting is too deep") from None
