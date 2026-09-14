"""Plain mathematical output that preserves operator grouping."""

from .environment import Definition
from .algebra import AlgebraDefinition
from .proof import EqualityGoal, ProofResult
from .modules import Namespace
from .rewriting import BinaryPattern, CallPattern, LiteralPattern, Pattern, UnaryPattern, Wildcard
from .terms import (
    Comparison, Defined, ForAll, Logical, Truth,
    Approach, CalculusOperator, CalculusRequest, TaylorSeries, TermFactory,
    ApproxNumber, Binary, Function, FunctionCall, Number, RewriteRequest, RuleSet, Substitution,
    Symbol, SymbolKind, Term, Unary,
)


class RenderError(ValueError):
    """An expression's expanded text exceeds the display budget."""


def _precedence(term: Term) -> int:
    match term:
        case Logical(op=op):
            return {'or': 1, 'and': 2, 'not': 3}[op]
        case Comparison():
            return 4
        case Function() | CalculusRequest() | ForAll():
            return 0
        case TaylorSeries():
            return 10
        case Binary(op=op):
            return {"+": 10, "-": 10, "*": 20, "/": 20, "^": 40}[op]
        case Unary():
            return 30
        case Number(value=value) if value.denominator != 1:
            return 20
        case Number(value=value) if value < 0:
            return 30
        case _:
            return 50


def format_term(term: Term, *, max_length: int = 100_000) -> str:
    from .theories import Theory, Implementation, PropertyResult
    if max_length < 1:
        raise ValueError("max_length must be positive")
    rendered: dict[Term, str] = {}

    def grouped(node: Term, minimum: int) -> str:
        result = rendered[node]
        return f"({result})" if _precedence(node) < minimum else result

    def render(node: Term) -> str:
        match node:
            case Truth(value=value):
                return value.value
            case Comparison(op=op, left=left, right=right):
                return f'{grouped(left, 5)} {op} {grouped(right, 5)}'
            case Logical(op='not', operands=(operand,)):
                return 'not '+grouped(operand, 3)
            case Logical(op=op, operands=operands):
                return f' {op} '.join(grouped(p, _precedence(node)+1) for p in operands)
            case Defined(expression=expression):
                return f'domain({rendered[expression]})'
            case ForAll(parameters=parameters, body=body):
                return 'forall '+', '.join(p.name+f' : {p.annotation}' for p in parameters)+': '+rendered[body]
            case Number(value=value):
                return str(value)
            case ApproxNumber(text=text):
                return "≈" + text
            case Symbol(name=name):
                return name
            case Unary(op=op, operand=operand):
                return op + grouped(operand, 30)
            case Binary(op=op, left=left, right=right):
                precedence = _precedence(node)
                # Preserve trees such as a+(b+c), a/(b/c), and (a^b)^c.
                lhs = grouped(left, precedence + (op == "^"))
                rhs = grouped(right, 30 if op == "^" else precedence + 1)
                separator = f" {op} " if op in ("+", "-") else op
                return lhs + separator + rhs
            case FunctionCall(callee=callee, arguments=arguments):
                return grouped(callee, 50) + "(" + ", ".join(rendered[a] for a in arguments) + ")"
            case Function(parameters=parameters, body=body):
                return "(" + ", ".join(p.name + (f" : {p.annotation}" if p.annotation is not None else '') for p in parameters) + ") => " + rendered[body]
            case Substitution(expression=expression, replacements=replacements):
                bindings = ", ".join(f"{symbol.name} = {rendered[value]}" for symbol, value in replacements)
                return f"substitute({rendered[expression]}, {bindings})"
            case RuleSet():
                return format_rule_set(node)
            case Approach(variable=variable, point=point):
                return f"{rendered[variable]} -> {rendered[point]}"
            case CalculusOperator(operation=operation, variable=variable, order=order, point=point):
                if operation == 'integrate':
                    return f'integrate({rendered[variable]}, {rendered[point]}, {rendered[node.upper]})'
                coordinate = rendered[variable] if point is None else f"{rendered[variable]} = {rendered[point]}"
                option = f", order = {rendered[order]}" if operation in ("derivative", "series") else ""
                return f"{operation}({coordinate}{option})"
            case CalculusRequest(operator=operator, expression=expression):
                return f"{grouped(expression, 1)} |> {rendered[operator]}"
            case TaylorSeries(variable=variable, point=point):
                polynomial = format_term(node.polynomial(TermFactory()), max_length=max_length)
                delta = rendered[variable] if isinstance(point, Number) and point.value == 0 else f"({rendered[variable]} - {rendered[point]})"
                remainder = "1" if node.order == 0 else delta if node.order == 1 else f"{delta}^{node.order}"
                return ("" if polynomial == "0" else polynomial + " + ") + f"O({remainder})"
            case AlgebraDefinition(name=name, scalar_domain=domain):
                dimension = "unknown" if node.basis is None else str(len(node.basis))
                return f"algebra {name} over {domain} (dimension: {dimension}, confluence: {node.confluence})"
            case Namespace(name=name, definitions=definitions):
                return f"namespace {name} {{" + ", ".join(d.symbol.name for d in definitions) + "}"
            case Theory(name=name):
                signature = ', '.join(str(p) for p in node.parameters)
                members = [f'  operation {o.spelling} : {o.symbol.annotation}' for o in node.operations]
                members += [f'  const {c.name} : {c.annotation}' for c in node.constants]
                members += [f'  axiom {a.name}: '+format_term(a.statement, max_length=max_length) for a in node.axioms]
                parents = ' extends ' + ', '.join(map(str, node.parents)) if node.parents else ''
                return '\n'.join([f'theory {name}<{signature}>' + parents, *members])
            case Implementation(name=name):
                signature = ', '.join(str(p) for p in node.arguments)
                return '\n'.join([f'implementation {name} implements {node.theory.name}<{signature}>',
                                  f'  Valid: {node.valid.value}',
                                  *[f'  {p.name}: {p.status}' for p in node.properties]])
            case PropertyResult(name=name, status=status, method=method):
                lines = [f'Property {name}: {status}', f'  Method: {method}',
                         '  Statement: '+format_term(node.statement, max_length=max_length)]
                if status == 'disproved':
                    lines.append('  Counterexample: '+', '.join(format_term(v, max_length=max_length) for v in node.counterexample))
                return '\n'.join(lines)
            case ProofResult(status=status, method=method):
                goal = node.goal
                statement = (f"{format_term(goal.left, max_length=max_length)} = {format_term(goal.right, max_length=max_length)}"
                             if isinstance(goal, EqualityGoal) else f"multiplication {goal.property}")
                lines = [f"ProofResult: {status}", f"  Goal: {statement}", f"  Method: {method}"]
                if node.checks:
                    lines.append(f"  Basis checks: {node.checks}")
                if node.left_normal is not None:
                    lines.append(f"  Left normal form: {format_term(node.left_normal, max_length=max_length)}")
                    lines.append(f"  Right normal form: {format_term(node.right_normal, max_length=max_length)}")
                if node.counterexample:
                    lines.append("  Counterexample: " + ", ".join(format_term(t, max_length=max_length) for t in node.counterexample))
                if node.reason:
                    lines.append(f"  Reason: {node.reason}")
                return "\n".join(lines)
            case RewriteRequest(expression=expression, rules=rules, strategy=strategy, repeat=repeat):
                selected = ((rules.name or f"<{len(rules.rules)} captured rules>")
                            if isinstance(rules, RuleSet) else rendered[rules])
                mode = "recursively" if repeat and strategy == "bottom_up" else strategy
                return f"rewrite({rendered[expression]}, {selected}, strategy={mode})"
            case _:
                raise TypeError(f"Unsupported term: {type(node).__name__}")

    # Iterative traversal handles deep stored expressions. A compact shared DAG
    # can expand into enormous text, so rendering has a separate size bound.
    stack = [(term, False)]
    while stack:
        node, ready = stack.pop()
        if node in rendered:
            continue
        if not ready:
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node.children))
            continue
        result = render(node)
        if len(result) > max_length:
            raise RenderError(f"Expression is too large to display (limit {max_length} characters)")
        rendered[node] = result
    return rendered[term]


def format_definition(definition: Definition) -> str:
    symbol, value = definition.symbol, definition.value
    if isinstance(value, AlgebraDefinition):
        return format_term(value)
    if symbol.kind == SymbolKind.RULE and isinstance(value, RuleSet):
        return format_rule_set(value)
    if (isinstance(value, Function)
            and symbol.kind in (SymbolKind.FUNCTION, SymbolKind.EXPRESSION)):
        if value.return_type is not None or any(p.annotation is not None for p in value.parameters):
            parameters = ", ".join(p.name + (f" : {p.annotation}" if p.annotation is not None else '') for p in value.parameters)
            result_type = '' if value.return_type is None else f' : {value.return_type}'
            return f"function {symbol.name}({parameters}){result_type} {{ return {format_term(value.body)} }}"
        parameters = ", ".join(p.name for p in value.parameters)
        return f"{symbol.name}({parameters}) = {format_term(value.body)}"
    prefix = "" if symbol.kind.value == "expression" else symbol.kind.value + " "
    annotation = "" if symbol.annotation is None else f" : {symbol.annotation}"
    suffix = "" if value is None else " = " + format_term(value)
    return prefix + symbol.name + annotation + suffix


def format_pattern(pattern: Pattern) -> str:
    memo: dict[int, Term] = {}
    stack = [(pattern, False)]
    while stack:
        node, ready = stack.pop()
        if id(node) in memo:
            continue
        if not ready:
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node.children))
            continue
        match node:
            case Wildcard(name=name):
                term = Symbol(name, SymbolKind.VARIABLE)
            case LiteralPattern(value=value):
                term = value
            case UnaryPattern(op=op, operand=operand):
                term = Unary(op, memo[id(operand)])
            case BinaryPattern(op=op, left=left, right=right):
                term = Binary(op, memo[id(left)], memo[id(right)])
            case CallPattern(callee=callee, arguments=arguments):
                term = FunctionCall(memo[id(callee)], tuple(memo[id(a)] for a in arguments))
            case _:
                raise TypeError(f"Unsupported pattern: {type(node).__name__}")
        memo[id(node)] = term
    return format_term(memo[id(pattern)])


def format_rule_set(rules: RuleSet) -> str:
    lines = ["rule" + (" " + rules.name if rules.name else "") + " {"]
    for rule in rules.rules:
        line = f"    {format_pattern(rule.pattern)} -> {format_pattern(rule.replacement)}"
        if rule.condition is not None:
            condition = rule.condition
            line += f" when {format_pattern(condition.left)} {condition.op} {format_pattern(condition.right)}"
        lines.append(line)
    lines.append("}")
    return "\n".join(lines)
