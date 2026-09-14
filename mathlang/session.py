"""Resolve parsed definitions into an environment and a shared expression DAG."""

from dataclasses import dataclass, replace

from . import ast
from .environment import Definition, Environment, builtin_environment
from .kernel import Kernel
from .normalization import Limits
from .rule_compiler import RuleCompiler
from .parser import parse_expression, parse_program
from .renderer import RenderError, format_term
from .source import DefinitionError, SourceSpan
from .terms import Approach, Function, FunctionCall, RuleSet, Symbol, SymbolKind, Term, TermFactory, Type
from .terms import Comparison, Defined, ForAll, Logical, Predicate, TruthValue
from .logic import PredicateQuery, LogicError
from .iteration import ITERATION_NAMES
from .analysis import calculus_call
from .algebra import AlgebraDefinition, Relation, algebra_symbols, compile_algebra
from .proof import ProofSearch
from .elaboration import Elaborator, ElaborationError, validate_type
from .symbols import valid_qualified_name
from .modules import Namespace, ModuleLoader, bind_import, bind_module, namespace_definition


@dataclass(frozen=True, slots=True)
class _StatementGroup:
    results: tuple


class _Resolver:
    def __init__(self, source: str, environment: Environment, factory: TermFactory,
                 kernel: Kernel, *, defer: bool = False, preserve_calls: bool = False,
                 module_loader: ModuleLoader | None = None) -> None:
        self.source = source
        self.environment = environment
        self.factory = factory
        self.kernel = kernel
        self.defer = defer
        self.preserve_calls = preserve_calls
        self.module_loader = module_loader
        self.type_parameters = {}
        self.operations = {}

    def error(self, message: str, node: ast.Node) -> DefinitionError:
        return DefinitionError(message, self.source, node.span or SourceSpan(0, 0, 1, 1))

    def annotation(self, node: ast.TypeRef) -> Type:
        if node.name in self.type_parameters:
            if node.arguments:
                raise self.error('A theory type parameter does not take arguments', node)
            return self.type_parameters[node.name]
        definition = self.environment.get(node.name)
        if definition is not None and isinstance(definition.term, AlgebraDefinition) and not node.arguments:
            return definition.term.type
        arguments = []
        for argument in node.arguments:
            if isinstance(argument, ast.NumberLiteral):
                arguments.append(int(argument.text))
            else:
                binding = self.environment.get(argument.name)
                from .terms import Number
                if (binding is not None and isinstance(binding.term, Number)
                        and binding.term.value.denominator == 1 and not argument.arguments):
                    arguments.append(int(binding.term.value))
                else:
                    arguments.append(self.annotation(argument))
        result = Type(node.name, tuple(arguments))
        validate_type(result)
        return result

    def expression(self, node: ast.Expr) -> Term:
        try:
            result = self._expression(node)
            Elaborator(self.kernel.limits, self.kernel.algebras).infer(result)
            return result
        except ElaborationError as error:
            raise self.error(str(error), node) from None

    def _expression(self, node: ast.Expr) -> Term:
        match node:
            case ast.ForAllExpr(parameters=parameters, body=body):
                local = self.environment.child()
                symbols = tuple(Symbol(p.name, SymbolKind.VARIABLE, self.annotation(p.annotation)) for p in parameters)
                for symbol in symbols:
                    local.define(Definition(symbol))
                resolver = _Resolver(self.source, local, self.factory, self.kernel, defer=True)
                resolver.type_parameters, resolver.operations = self.type_parameters, self.operations
                return self.factory._intern(ForAll, symbols, resolver.expression(body))
            case ast.TruthLiteral(value=value):
                return self.factory.truth(TruthValue(value))
            case ast.ComparisonExpr(op=op, left=left, right=right):
                return self.factory.comparison(op, self.expression(left), self.expression(right))
            case ast.LogicalExpr(op=op, operands=operands):
                return self.factory.logical(op, *(self.expression(p) for p in operands))
            case ast.NumberLiteral(text=text):
                try:
                    return self.factory.number(text)
                except ValueError:
                    raise self.error("Number literal is too large to convert", node) from None
            case ast.ApproachExpr(variable=variable, point=point):
                return self.factory._intern(Approach, self.expression(variable), self.expression(point))
            case ast.LambdaExpr(parameters=parameters, body=body):
                return self.function(parameters, body)
            case ast.Identifier(name=name):
                definition = self.environment.get(name)
                if definition is None and "." in name:
                    namespace, member = name.split(".", 1)
                    owner = self.environment.get(namespace)
                    if owner is not None and isinstance(owner.term, AlgebraDefinition):
                        value = owner.term.member(member)
                        if value is not None:
                            return value
                if definition is None:
                    raise self.error(f"Undefined name {name!r}; declare it before use", node)
                if definition.symbol.kind == SymbolKind.BUILTIN and name == "print":
                    raise self.error("print can only be used as a statement", node)
                return definition.term
            case ast.UnaryExpr(op=op, operand=operand):
                if self.operations:
                    operation = self.operations.get((op, 1))
                    if operation is None:
                        raise self.error(f'Theory does not declare unary ({op})', node)
                    return self.factory.call(operation, (self.expression(operand),))
                return self.factory.unary(op, self.expression(operand))
            case ast.BinaryExpr(op=op, left=left, right=right):
                if self.operations:
                    operation = self.operations.get((op, 2))
                    if operation is None:
                        raise self.error(f'Theory does not declare binary ({op})', node)
                    return self.factory.call(operation, (self.expression(left), self.expression(right)))
                result = self.factory.binary(op, self.expression(left), self.expression(right))
                try:
                    if not self.defer:
                        self.kernel.validate_algebra_operands(result)
                except ValueError as error:
                    raise self.error(str(error), node) from None
                return result
            case ast.CallExpr(callee=callee, arguments=arguments):
                function = self.expression(callee)
                if (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                        and function.name in ITERATION_NAMES and len(arguments) == 4):
                    # Expression form: sum(k^2, k, 1, 10). Only the function body
                    # binds k; bounds and the enclosing environment keep k free.
                    binder = self.expression(arguments[1])
                    if not isinstance(binder, Symbol) or binder.kind not in (SymbolKind.VARIABLE, SymbolKind.PARAMETER, SymbolKind.UNKNOWN):
                        raise self.error('Iteration binder must be a declared variable or parameter', arguments[1])
                    deferred = _Resolver(self.source, self.environment, self.factory, self.kernel,
                                         defer=True, preserve_calls=self.preserve_calls)
                    body = deferred.expression(arguments[0])
                    values = (self.factory.function((binder,), body),
                              *(self.expression(a) for a in arguments[2:]))
                    return self.call(function, values, node.keywords, node)
                values = tuple(self.expression(argument) for argument in arguments)
                return self.call(function, values, node.keywords, node)
            case ast.SubstitutionExpr(expression=expression, replacements=replacements):
                return self.substitution(self.expression(expression), replacements, node)
            case ast.PipelineExpr(value=value, target=target):
                argument = self.expression(value)
                if isinstance(target, ast.CallExpr):
                    function = self.expression(target.callee)
                    arguments = (argument, *(self.expression(a) for a in target.arguments))
                    return self.call(function, arguments, target.keywords, node)
                return self.call(self.expression(target), (argument,), (), node)
            case ast.RewriteExpr(expression=expression, rules=rules, strategy=strategy, repeat=repeat):
                selected = self.environment.visible_rules() if rules is None else self.expression(rules)
                if not self.defer and not isinstance(selected, RuleSet):
                    raise self.error("'using' expects a declared rule or rule set", node)
                return self.finish(self.factory.rewrite(self.expression(expression), selected,
                                                        strategy, repeat), node)
            case _:
                raise TypeError(f"Unsupported expression: {type(node).__name__}")

    def finish(self, term: Term, node: ast.Node) -> Term:
        if self.defer:
            return term
        try:
            return self.kernel.evaluate(term, context=self.environment.context)
        except ValueError as error:
            raise self.error(str(error), node) from None

    def call(self, function: Term, arguments: tuple[Term, ...],
             keywords: tuple[ast.KeywordArgument, ...], node: ast.Node) -> Term:
        if (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                and function.name in ("derivative", "antiderivative", "integrate", "series", "limit")):
            order = None
            binding = None
            for keyword in keywords:
                if keyword.name == "order" and function.name in ("derivative", "series"):
                    order = self.expression(keyword.value)
                elif function.name in ("series", "limit") and keyword.name != "order" and binding is None:
                    definition = self.environment.get(keyword.name)
                    if definition is None or not isinstance(definition.term, Symbol):
                        raise self.error("An expansion/limit binding must name a declared variable", keyword)
                    binding = self.factory._intern(Approach, definition.term, self.expression(keyword.value))
                else:
                    raise self.error(f"Unsupported or duplicate {function.name} option {keyword.name!r}", keyword)
            try:
                result = calculus_call(self.factory, function.name, arguments, order=order, binding=binding)
            except ValueError as error:
                raise self.error(str(error), node) from None
            return self.finish(result, node)
        if (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                and function.name == "rewrite"):
            if not 1 <= len(arguments) <= 2:
                raise self.error("rewrite expects an expression and an optional rule set", node)
            selected = arguments[1] if len(arguments) == 2 else self.environment.visible_rules()
            if not self.defer and not isinstance(selected, RuleSet):
                raise self.error("rewrite expects a rule set as its second argument", node)
            strategy, repeat = "bottom_up", False
            for keyword in keywords:
                value = keyword.value
                if keyword.name == "strategy" and isinstance(value, ast.Identifier):
                    if value.name not in ("once", "bottom_up", "top_down", "recursively"):
                        raise self.error("Unknown rewrite strategy", keyword)
                    strategy = value.name if value.name != "recursively" else "bottom_up"
                    repeat = value.name == "recursively"
                else:
                    raise self.error("rewrite accepts only strategy=once/bottom_up/top_down/recursively", keyword)
            return self.finish(self.factory.rewrite(arguments[0], selected, strategy, repeat), node)
        if (isinstance(function, Symbol) and function.kind == SymbolKind.BUILTIN
                and function.name == "substitute"):
            if len(arguments) != 1 or not keywords:
                raise self.error("substitute expects one expression and named replacements", node)
            return self.substitution(arguments[0], keywords, node)
        if keywords:
            raise self.error("Named arguments are supported only by transformations with declared options", node)
        try:
            if self.defer and self.preserve_calls and isinstance(function, Function):
                Elaborator(self.kernel.limits, self.kernel.algebras).check_call(function, arguments)
                result = self.factory._intern(FunctionCall, function, arguments)
            else:
                result = self.factory.call(function, arguments, checker=Elaborator(self.kernel.limits, self.kernel.algebras))
        except ValueError as error:
            raise self.error(str(error), node) from None
        return self.finish(result, node)

    def substitution(self, expression: Term, replacements: tuple[ast.KeywordArgument, ...],
                     node: ast.Node) -> Term:
        bindings: dict[Symbol, Term] = {}
        for replacement in replacements:
            definition = self.environment.get(replacement.name)
            symbol = None if definition is None else definition.term
            if not isinstance(symbol, Symbol) or symbol.kind == SymbolKind.BUILTIN:
                raise self.error(f"Substitution target {replacement.name!r} must be a declared symbol",
                                 replacement)
            if symbol in bindings:
                raise self.error("Substitution targets must be distinct symbols", replacement)
            bindings[symbol] = self.expression(replacement.value)
        return self.finish(self.factory.substitution(expression, tuple(bindings.items())), node)

    def statement(self, node: ast.Statement) -> Term | tuple[Term, ...] | _StatementGroup | None:
        match node:
            case ast.TheoryDeclaration() | ast.ImplementationDeclaration():
                from .theories import compile_theory, compile_implementation
                try:
                    value = (compile_theory(node, self) if isinstance(node, ast.TheoryDeclaration)
                             else compile_implementation(node, self))
                    kind = SymbolKind.THEORY if isinstance(node, ast.TheoryDeclaration) else SymbolKind.IMPLEMENTATION
                    self.define(Definition(Symbol(node.name, kind), value), node)
                except DefinitionError:
                    raise
                except ValueError as error:
                    raise self.error(str(error), node) from None
            case ast.AssumeStatement(condition=condition):
                self.assume(condition)
            case ast.AssumingStatement(conditions=conditions, body=body):
                local = self.environment.child()
                resolver = _Resolver(self.source, local, self.factory, self.kernel, module_loader=self.module_loader)
                for condition in conditions:
                    resolver.assume(condition)
                return _StatementGroup(tuple(resolver.statement(s) for s in body.statements))
            case ast.ReturnStatement():
                raise self.error('return is allowed only at the end of a function body', node)
            case ast.TypedFunctionDefinition(name=name, parameters=parameters, return_type=return_type, body=body):
                if not body.statements or not isinstance(body.statements[-1], ast.ReturnStatement):
                    raise self.error('A function body must end with return', node)
                function = self.function(parameters, body.statements[-1].expression, return_type, body.statements[:-1])
                self.define(Definition(Symbol(name, SymbolKind.FUNCTION), function), node, replace=True)
            case ast.ModuleDeclaration():
                return None
            case ast.ImportStatement(module=module, alias=alias, names=names):
                try:
                    if self.module_loader is None:
                        raise ValueError("Module loading is unavailable in this context")
                    namespace = self.module_loader.load(module, self.kernel)
                    self.environment.imported_modules[module] = namespace
                    if names:
                        for item in names:
                            definition = namespace.definition(item.name)
                            if definition is None:
                                raise ValueError(f"Module {module!r} has no member {item.name!r}")
                            bind_import(self.environment, item.alias or item.name, definition)
                    else:
                        bind_module(self.environment, alias or module, namespace)
                except ValueError as error:
                    raise self.error(str(error), node) from None
            case ast.NamespaceDeclaration(name=name, body=body):
                local = self.environment.child()
                resolver = _Resolver(self.source, local, self.factory, self.kernel,
                                     module_loader=self.module_loader)
                results = tuple(resolver.statement(s) for s in body.statements)
                if local.context != self.environment.context:
                    raise self.error('Namespace assumptions cannot be exported; use an assuming block for local work', node)
                namespace = Namespace(name, tuple(local.definitions.values()), local.local_rule_sets,
                                      dependencies=tuple(local.imported_modules.values()))
                self.define(namespace_definition(name, namespace), node)
                return _StatementGroup(results)
            case ast.AlgebraDeclaration():
                try:
                    domain = self.annotation(node.scalar_domain)
                    type_, generators = algebra_symbols(node.name, tuple(g.name for g in node.generators))
                    local = self.environment.child()
                    for generator in generators:
                        local.define(Definition(generator))
                    # The declaration is elaborated before its normalizer exists.
                    resolver = _Resolver(self.source, local, self.factory, self.kernel, defer=True)
                    relations = tuple(Relation(resolver.expression(r.left), resolver.expression(r.right))
                                      for r in node.relations)
                    basis = None if node.basis is None else tuple(resolver.expression(b) for b in node.basis)
                    algebra = compile_algebra(node.name, domain, type_, generators, relations, basis,
                                              derive_basis=node.derive_basis, bilinear=node.bilinear,
                                              limits=self.kernel.limits)
                    self.kernel.algebras[type_.identity] = algebra
                    local.active_algebra = algebra
                    resolver.defer = False
                    results, properties = [], []
                    for request in node.proofs:
                        result = resolver.statement(request)
                        results.append(result)
                        if request.property_name is not None and result.status == "proved":
                            key = {"associative": "associativity_proof", "commutative": "commutativity_proof"}[request.property_name]
                            properties.append((key, result))
                    algebra = replace(algebra, properties=tuple(properties))
                    self.kernel.algebras[type_.identity] = algebra
                    self.define(Definition(Symbol(node.name, SymbolKind.ALGEBRA, Type("Algebra")), algebra), node)
                    return _StatementGroup(tuple(results))
                except DefinitionError:
                    raise
                except ValueError as error:
                    raise self.error(str(error), node) from None
            case ast.WithStatement(algebra=algebra, body=body):
                selected = self.select_algebra(algebra)
                local = self.environment.child()
                if isinstance(selected, Namespace):
                    local.active_namespace = selected
                else:
                    local.active_algebra = selected
                resolver = _Resolver(self.source, local, self.factory, self.kernel,
                                     module_loader=self.module_loader)
                return _StatementGroup(tuple(resolver.statement(s) for s in body.statements))
            case ast.UseStatement(algebra=algebra):
                selected = self.select_algebra(algebra)
                self.environment.active_algebra = selected if isinstance(selected, AlgebraDefinition) else None
                self.environment.active_namespace = selected if isinstance(selected, Namespace) else None
            case ast.ProveStatement(goals=goals, property_name=property):
                if self.environment.context.assumptions.predicates:
                    raise self.error('Portable prove certificates require an assumption-free context; use query for conditional predicates', node)
                search = ProofSearch(self.factory, self.kernel.limits)
                if property is not None:
                    scope = self.environment
                    while scope is not None and scope.active_algebra is None:
                        scope = scope.parent
                    if scope is None:
                        raise self.error("A multiplication proof requires an active algebra (with or use)", node)
                    return search.property(scope.active_algebra, property)
                results = []
                for goal in goals:
                    left, right = self.expression(goal.left), self.expression(goal.right)
                    try:
                        algebra = self.kernel.algebra_for(left, right)
                    except ValueError as error:
                        raise self.error(str(error), goal) from None
                    results.append(search.equality(left, right, algebra))
                return _StatementGroup(tuple(results))
            case ast.RuleDeclaration():
                group = RuleCompiler(self.environment, self.factory, self.source).compile(node)
                if node.name is None:
                    self.environment.add_anonymous_rules(group)
                else:
                    self.define(Definition(Symbol(node.name, SymbolKind.RULE), group), node)
            case ast.Declaration(kind=kind, name=name, annotation=annotation, value=value):
                try:
                    type_ = None if annotation is None else self.annotation(annotation)
                except ValueError as error:
                    raise self.error(str(error), node) from None
                symbol = Symbol(name, SymbolKind(kind), type_)
                term = None if value is None else self.expression(value)
                if type_ is not None and term is not None:
                    try:
                        Elaborator(self.kernel.limits, self.kernel.algebras).require(term, type_, f'Constant {name!r}')
                    except ElaborationError as error:
                        raise self.error(str(error), node) from None
                self.define(Definition(symbol, term), node)
            case ast.Assignment(name=name, value=value):
                self.define(Definition(Symbol(name, SymbolKind.EXPRESSION),
                                       self.expression(value)), node, replace=True)
            case ast.FunctionDefinition(name=name, parameters=parameters, body=body):
                function = self.function(tuple(ast.FunctionParameter(p.name, span=p.span) for p in parameters), body)
                self.define(Definition(Symbol(name, SymbolKind.FUNCTION), function),
                            node, replace=True)
            case ast.ExpressionStatement(expression=expression):
                if (isinstance(expression, ast.CallExpr)
                        and isinstance(expression.callee, ast.Identifier)
                        and expression.callee.name == "print"):
                    definition = self.environment.get("print")
                    if definition is not None and definition.symbol.kind == SymbolKind.BUILTIN:
                        if expression.keywords:
                            raise self.error("print accepts only positional arguments", expression)
                        return tuple(self.display(self.expression(arg), arg) for arg in expression.arguments)
                return self.display(self.expression(expression), expression)
            case _:
                raise TypeError(f"Unsupported statement: {type(node).__name__}")
        return None

    def query_engine(self):
        return PredicateQuery(self.factory, context=self.environment.context,
                              limits=self.kernel.limits, algebras=self.kernel.algebras)

    def assume(self, condition):
        predicate = self.expression(condition)
        try:
            self.environment.context = self.query_engine().assuming(predicate)
        except ValueError as error:
            raise self.error(str(error), condition) from None

    def display(self, value, node):
        if Elaborator(self.kernel.limits, self.kernel.algebras).infer(value) == Type('Predicate'):
            try:
                return self.factory.truth(self.query_engine().query(value))
            except ValueError as error:
                raise self.error(str(error), node) from None
        return value

    def function(self, parameters, body, return_type=None, statements=()):
        local = self.environment.child()
        symbols = []
        for parameter in parameters:
            outer = self.environment.get(parameter.name)
            try:
                annotation = (self.annotation(parameter.annotation) if parameter.annotation is not None
                              else None if outer is None else outer.symbol.annotation)
            except ValueError as error:
                raise self.error(str(error), parameter) from None
            symbol = Symbol(parameter.name, SymbolKind.VARIABLE, annotation)
            local.define(Definition(symbol))
            symbols.append(symbol)
        resolver = _Resolver(self.source, local, self.factory, self.kernel, defer=True)
        allowed = (ast.Declaration, ast.Assignment, ast.FunctionDefinition, ast.TypedFunctionDefinition, ast.RuleDeclaration)
        for statement in statements:
            if not isinstance(statement, allowed):
                raise self.error('Function bodies support local definitions followed by one return', statement)
            resolver.statement(statement)
        expression = resolver.expression(body)
        try:
            type_ = None if return_type is None else self.annotation(return_type)
            function = self.factory.function(tuple(symbols), expression, type_)
            Elaborator(self.kernel.limits, self.kernel.algebras).infer(function)
            return function
        except ElaborationError as error:
            raise self.error(str(error), body) from None

    def select_algebra(self, node: ast.Identifier) -> AlgebraDefinition | Namespace:
        term = self.expression(node)
        if not isinstance(term, (AlgebraDefinition, Namespace)):
            raise self.error(f"{node.name!r} is not an algebra or namespace", node)
        return term

    def define(self, definition: Definition, node: ast.Node, *, replace: bool = False) -> None:
        try:
            self.environment.define(definition, replace=replace)
        except ValueError as error:
            raise self.error(str(error), node) from None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    values: tuple[Term, ...]
    output: tuple[str, ...]
    # One tuple per textual output line.  A multi-argument print keeps all
    # values in the same group while preserving the traditional console line.
    # IDE clients can therefore render every mathematical value without
    # guessing a correspondence from ``zip(values, output)``.
    output_groups: tuple[tuple[Term, ...], ...] = ()


class Session:
    """In-process memory. Each successful execute() commits a complete input.

    Definitions capture current terms; redefining a name cannot mutate previously
    stored expressions. Nothing is automatically simplified or saved to disk.
    """

    def __init__(self, environment: Environment | None = None, *, limits: Limits | None = None,
                 module_paths=(), module_loader: ModuleLoader | None = None, _kernel: Kernel | None = None) -> None:
        self.environment = (builtin_environment().child()
                            if environment is None else environment)
        self.factory = TermFactory() if _kernel is None else _kernel.factory
        self.kernel = Kernel(self.factory, limits) if _kernel is None else _kernel
        self.modules = (ModuleLoader(module_paths, limits=self.kernel.limits)
                        if module_loader is None else module_loader)
        self.module_name: str | None = None
        from .serialization import register_algebras
        scope = self.environment
        while scope is not None:
            for definition in scope.definitions.values():
                register_algebras(definition.term, self.kernel)
                if isinstance(definition.term, Namespace):
                    self.modules.register(definition.term)
            for module in scope.imported_modules.values():
                self.modules.register(module)
            scope = scope.parent

    def __getitem__(self, name: str) -> Term:
        return self.environment[name].term

    def type_of(self, value: str | Term) -> Type | None:
        term = self.resolve(value) if isinstance(value, str) else value
        return Elaborator(self.kernel.limits, self.kernel.algebras).infer(term)

    def typed_ir(self, value: str | Term):
        """Return pre-evaluation Typed IR with explicit implicit embeddings."""
        if isinstance(value, str):
            node = parse_expression(value)
            resolver = _Resolver(value, self.environment, self.factory, self.kernel,
                                 defer=True, preserve_calls=True, module_loader=self.modules)
            try:
                term = resolver.expression(node)
                return Elaborator(self.kernel.limits, self.kernel.algebras).elaborate(term)
            except ElaborationError as error:
                raise resolver.error(str(error), node) from None
            except RecursionError:
                raise resolver.error("Expression nesting is too deep to resolve", node) from None
        return Elaborator(self.kernel.limits, self.kernel.algebras).elaborate(value)

    def export_module(self, name: str | None = None) -> Namespace:
        if self.environment.context.assumptions.predicates:
            raise ValueError('Modules with active assumptions cannot be exported as unconditional definitions')
        name = name or self.module_name
        if name is None or not valid_qualified_name(name):
            raise ValueError("Declare a module or supply a valid module name before saving")
        return Namespace(name, tuple(self.environment.definitions.values()),
                         self.environment.local_rule_sets, is_module=True,
                         dependencies=tuple(self.environment.imported_modules.values()))

    def save_module(self, path, *, name: str | None = None) -> None:
        from .serialization import save_ir
        save_ir(self.export_module(name), path, limits=self.kernel.limits)

    def load_module(self, path, *, alias: str | None = None) -> Namespace:
        from .serialization import load_ir, register_algebras
        module = load_ir(path, limits=self.kernel.limits, factory=self.factory)
        if not isinstance(module, Namespace) or not module.is_module:
            raise ValueError("A module file must contain a namespace")
        snapshot = self.kernel.algebras.copy()
        try:
            with self.environment.transaction(), self.modules.transaction():
                previous = self.modules.cache.get(module.name)
                if previous is not None:
                    if previous != module:
                        raise ValueError(f"Module {module.name!r} is already loaded with different contents")
                    module = previous
                register_algebras(module, self.kernel)
                bind_module(self.environment, alias or module.name, module)
                self.modules.register(module)
                self.environment.imported_modules[module.name] = module
        except BaseException:
            self.kernel.algebras.clear()
            self.kernel.algebras.update(snapshot)
            raise
        return module

    def execute_file(self, path) -> ExecutionResult:
        from pathlib import Path
        path = Path(path).resolve()
        source = path.read_text(encoding='utf-8-sig')
        return self.execute_source(source, path=path)

    def execute_source(self, source: str, *, path=None) -> ExecutionResult:
        """Execute a buffer using its file location for imports, without reading it."""
        if path is None:
            return self.execute(source)
        from pathlib import Path
        path = Path(path).resolve()
        program = parse_program(source)
        roots = [path.parent]
        if program.statements and isinstance(program.statements[0], ast.ModuleDeclaration):
            parts = program.statements[0].name.split('.')
            if list(path.with_suffix('').parts[-len(parts):]) == parts:
                roots.insert(0, path.parents[len(parts)-1])
        previous = self.modules.paths
        self.modules.paths = tuple(dict.fromkeys((*roots, *previous)))
        try:
            return self.execute(source)
        finally:
            self.modules.paths = previous

    def resolve(self, source: str) -> Term:
        """Read an expression using current definitions, without changing memory."""
        node = parse_expression(source)
        resolver = _Resolver(source, self.environment, self.factory, self.kernel, module_loader=self.modules)
        try:
            return resolver.expression(node)
        except RecursionError:
            raise resolver.error("Expression nesting is too deep to resolve", node) from None

    @property
    def context(self):
        return self.environment.context

    def query(self, predicate: str | Term) -> TruthValue:
        value = self.resolve(predicate) if isinstance(predicate, str) else predicate
        return PredicateQuery(self.factory, context=self.context, limits=self.kernel.limits,
                              algebras=self.kernel.algebras).query(value)

    def domain(self, expression: str | Term) -> Defined:
        value = self.resolve(expression) if isinstance(expression, str) else expression
        return self.factory._intern(Defined, value)

    def execute(self, source: str, *, module_name: str | None = None) -> ExecutionResult:
        program = parse_program(source)
        resolver = _Resolver(source, self.environment, self.factory, self.kernel, module_loader=self.modules)
        declared = (program.statements[0] if program.statements
                    and isinstance(program.statements[0], ast.ModuleDeclaration) else None)
        if declared is not None and module_name is not None and declared.name != module_name:
            raise resolver.error(f"Expected module {module_name!r}, found {declared.name!r}", declared)
        if declared is not None and self.module_name is not None and declared.name != self.module_name:
            raise resolver.error("A session cannot change its declared module", declared)
        values: list[Term] = []
        output: list[str] = []
        output_groups: list[tuple[Term, ...]] = []

        def collect(result):
            if isinstance(result, _StatementGroup):
                for item in result.results:
                    collect(item)
            elif isinstance(result, tuple):
                values.extend(result)
                output.append(" ".join(map(format_term, result)))
                output_groups.append(tuple(result))
            elif result is not None:
                values.append(result)
                output.append(format_term(result))
                output_groups.append((result,))

        algebra_snapshot = self.kernel.algebras.copy()
        try:
            with self.environment.transaction(), self.modules.transaction():
                for statement in program.statements:
                    try:
                        collect(resolver.statement(statement))
                    except RecursionError:
                        raise resolver.error("Expression nesting is too deep to resolve",
                                             statement) from None
                    except RenderError as error:
                        raise resolver.error(str(error), statement) from None
        except BaseException:
            self.kernel.algebras.clear()
            self.kernel.algebras.update(algebra_snapshot)
            raise
        self.module_name = declared.name if declared is not None else module_name or self.module_name
        return ExecutionResult(tuple(values), tuple(output), tuple(output_groups))
