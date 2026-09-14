"""LaTeX rendering for the mathematical IR.

This renderer is deliberately presentation-only: it never changes or evaluates
terms. Unsupported term classes fall back to an escaped plain representation.
"""

from __future__ import annotations

from fractions import Fraction

from ..renderer import format_term
from ..terms import (
    Comparison, Logical, Defined, ForAll, Truth,
    Approach,
    Binary,
    CalculusOperator,
    CalculusRequest,
    Function,
    FunctionCall,
    ApproxNumber,
    Number,
    Substitution,
    Symbol,
    SymbolKind,
    TaylorSeries,
    Term, TermFactory,
    Unary,
)


_BUILTIN_NAMES = {
    "sin": r"\sin",
    "cos": r"\cos",
    "tan": r"\tan",
    "log": r"\log",
    "exp": r"\exp",
}

def _escape_text(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "_": r"\_",
        "%": r"\%",
        "&": r"\&",
        "#": r"\#",
        "$": r"\$",
    }
    return "".join(replacements.get(ch, ch) for ch in value)


def _symbol(name: str) -> str:
    if len(name) == 1:
        return name
    return r"\mathrm{" + _escape_text(name) + "}"


def _fraction(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return rf"\frac{{{value.numerator}}}{{{value.denominator}}}"


def _precedence(term: Term) -> int:
    if isinstance(term, ForAll):
        return 0
    if isinstance(term, Logical):
        return {'or': 1, 'and': 2, 'not': 3}[term.op]
    if isinstance(term, Comparison):
        return 4
    if isinstance(term, Number) and term.value < 0:
        return 30
    if isinstance(term, Binary):
        return {"+": 10, "-": 10, "*": 20, "/": 20, "^": 40}.get(term.op, 5)
    if isinstance(term, Unary):
        return 30
    return 50


def format_latex(term: Term, *, max_length: int = 100_000) -> str:
    """Render a mathematical :class:`Term` to display-math LaTeX.

    Non-term runtime values (for example ``ProofResult``) are intentionally not
    converted to fake ``\\texttt{...}`` math.  They belong in the textual output
    panel; treating them as LaTeX made the preview fall back to displaying source
    code instead of a rendered formula.
    """
    if not isinstance(term, Term):
        raise TypeError(f"LaTeX rendering requires Term, got {type(term).__name__}")
    memo: dict[Term, str] = {}

    def grouped(node: Term, minimum: int) -> str:
        text = memo[node]
        return rf"\left({text}\right)" if _precedence(node) < minimum else text

    def render(node: Term) -> str:
        match node:
            case Truth(value=value):
                return r'\mathrm{'+value.value+'}'
            case Comparison(op=op, left=left, right=right):
                operator = {'==': '=', '===': r'\mathrm{===}', '!=': r'\ne', '<': '<', '<=': r'\leq', '>': '>', '>=': r'\geq'}[op]
                return grouped(left, 5)+' '+operator+' '+grouped(right, 5)
            case Logical(op='not', operands=(operand,)):
                return r'\neg '+grouped(operand, 3)
            case Logical(op=op, operands=operands):
                operator = r' \wedge ' if op == 'and' else r' \vee '
                return operator.join(grouped(p, _precedence(node)+1) for p in operands)
            case Defined(expression=expression):
                return r'\operatorname{domain}\left('+memo[expression]+r'\right)'
            case ForAll(parameters=parameters, body=body):
                names = r',\ '.join(_symbol(p.name)+r'\!:\!'+_symbol(str(p.annotation)) for p in parameters)
                return r'\forall '+names+r'\quad '+memo[body]
            case Number(value=value):
                return _fraction(value)
            case ApproxNumber(text=text):
                return r"\approx " + _escape_text(text)
            case Symbol(name=name):
                return _symbol(name)
            case Unary(op="-", operand=operand):
                return "-" + grouped(operand, 30)
            case Unary(op=op, operand=operand):
                return rf"\operatorname{{{_escape_text(op)}}}\left({memo[operand]}\right)"
            case Binary(op="+", left=left, right=right):
                return grouped(left, 10) + " + " + grouped(right, 11)
            case Binary(op="-", left=left, right=right):
                return grouped(left, 10) + " - " + grouped(right, 11)
            case Binary(op="*", left=left, right=right):
                numeric = isinstance(right, Number) or (isinstance(right, Unary) and isinstance(right.operand, Number))
                separator = r"\cdot " if numeric else r"\,"
                negative = (isinstance(right, Unary) and right.op == '-') or (isinstance(right, Number) and right.value < 0)
                return grouped(left, 20) + separator + grouped(right, 31 if negative else 21)
            case Binary(op="/", left=left, right=right):
                return rf"\frac{{{memo[left]}}}{{{memo[right]}}}"
            case Binary(op="^", left=left, right=right):
                return "{" + grouped(left, 41) + "}^{" + memo[right] + "}"
            case FunctionCall(callee=Symbol(kind=SymbolKind.BUILTIN, name="sqrt"), arguments=(argument,)):
                return rf"\sqrt{{{memo[argument]}}}"
            case FunctionCall(callee=Symbol(kind=SymbolKind.BUILTIN, name='factorial'), arguments=(argument,)):
                return grouped(argument, 50)+'!'
            case FunctionCall(callee=Symbol(kind=SymbolKind.BUILTIN, name=name), arguments=(Function(parameters=(index,), body=body), lower, upper)) if name in ('sum', 'product', 'all', 'any'):
                operator = {'sum': r'\sum', 'product': r'\prod', 'all': r'\bigwedge', 'any': r'\bigvee'}[name]
                return operator+'_{'+_symbol(index.name)+'='+memo[lower]+'}^{'+memo[upper]+'} '+grouped(body, 21)
            case FunctionCall(callee=Symbol(kind=SymbolKind.BUILTIN, name="abs"), arguments=(argument,)):
                return rf"\left|{memo[argument]}\right|"
            case FunctionCall(callee=Symbol(kind=SymbolKind.BUILTIN, name=name), arguments=arguments) if name in _BUILTIN_NAMES:
                args = ", ".join(memo[arg] for arg in arguments)
                return _BUILTIN_NAMES[name] + rf"\left({args}\right)"
            case FunctionCall(callee=callee, arguments=arguments):
                args = ", ".join(memo[arg] for arg in arguments)
                return memo[callee] + rf"\left({args}\right)"
            case Function(parameters=parameters, body=body):
                params = ", ".join(_symbol(p.name) for p in parameters)
                return rf"\left({params}\right)\mapsto {memo[body]}"
            case Substitution(expression=expression, replacements=replacements):
                binds = ", ".join(_symbol(symbol.name) + "=" + memo[value]
                                  for symbol, value in replacements)
                return memo[expression] + rf"\big|_{{{binds}}}"
            case Approach(variable=variable, point=point):
                return memo[variable] + r"\to " + memo[point]
            case CalculusOperator(operation="derivative", variable=variable, order=order):
                return rf"\frac{{d^{{{memo[order]}}}}}{{d {memo[variable]}^{{{memo[order]}}}}}"
            case CalculusOperator(operation="antiderivative", variable=variable):
                return rf"\int \! \cdot \, d{memo[variable]}"
            case CalculusOperator(operation='integrate', variable=variable, point=lower, upper=upper):
                return rf'\int_{{{memo[lower]}}}^{{{memo[upper]}}} \! \cdot \, d{memo[variable]}'
            case CalculusOperator(operation=operation, variable=variable):
                return rf"\operatorname{{{_escape_text(operation)}}}_{{{memo[variable]}}}"
            case CalculusRequest(operator=operator, expression=expression):
                if operator.operation == "derivative":
                    return memo[operator] + r"\," + memo[expression]
                if operator.operation == "antiderivative":
                    return rf"\int {memo[expression]}\,d{memo[operator.variable]}"
                if operator.operation == 'integrate':
                    return rf'\int_{{{memo[operator.point]}}}^{{{memo[operator.upper]}}} {memo[expression]}\,d{memo[operator.variable]}'
                return memo[operator] + rf"\left({memo[expression]}\right)"
            case TaylorSeries():
                polynomial = node.polynomial(TermFactory())
                base = format_latex(polynomial, max_length=max_length)
                variable = memo[node.variable]
                point = memo[node.point]
                delta = variable if isinstance(node.point, Number) and node.point.value == 0 else rf"\left({variable}-{point}\right)"
                return base + rf" + O\left({delta}^{{{node.order}}}\right)"
            case _:
                raise TypeError(f"Unsupported LaTeX term: {type(node).__name__}")

    stack: list[tuple[Term, bool]] = [(term, False)]
    while stack:
        node, ready = stack.pop()
        if node in memo:
            continue
        if not ready:
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node.children))
            continue
        text = render(node)
        if len(text) > max_length:
            raise ValueError(f"LaTeX output exceeds {max_length} characters")
        memo[node] = text
    return memo[term]
