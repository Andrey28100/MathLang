"""Reusable IDE-facing API over the existing mathlang frontend and runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..parser import parse_program
from ..renderer import format_term
from ..session import Session
from ..source import LanguageError, SourceSpan
from ..terms import Term
from .. import ast
from ..symbols import MATH_ALIASES, canonical_name, valid_name
from ..typed_ir import format_typed_ir
from .latex import format_latex
from .plotting import PlotSpec, sample_expression


Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    message: str
    start: int
    end: int
    line: int
    column: int
    severity: Severity = "error"
    phase: str = "syntax"

    @classmethod
    def from_error(cls, error: LanguageError, *, phase: str) -> "Diagnostic":
        span = error.span
        return cls(error.message, span.start, max(span.end, span.start + 1),
                   span.line, span.column, "error", phase)


@dataclass(frozen=True, slots=True)
class OutputItem:
    kind: Literal["math", "text", "error"]
    text: str
    latex: str | None = None
    # Preview and console have slightly different needs.  ``text`` is the
    # value represented by this preview item; ``console_text`` preserves the
    # original runtime output line (for example ``print(a, b, c)``).
    console_text: str | None = None
    show_in_console: bool = True


_KEYWORDS = (
    'theory', 'operation', 'axiom', 'implementation', 'implements', 'extends', 'forall',
    'assume', 'assuming', 'and', 'or', 'not', 'True', 'False', 'Unknown',
    "algebra", "as", "assert", "basis", "const", "derive", "function",
    "generator", "generators", "import", "module", "namespace", "over",
    "parameter", "prove", "relation", "relations", "return", "rule",
    "unknown", "use", "using", "variable", "when", "where", "with",
)


class LanguageService:
    """Small stable boundary between editor UI and the language implementation.

    Analysis creates disposable sessions and therefore never mutates the user's
    runtime. Explicit execution uses a fresh session by default so repeated Run
    commands are deterministic and do not collide with previous definitions.
    """

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None
        self.runtime = self._new_session()

    def _module_paths(self) -> tuple[Path, ...]:
        return () if self.project_root is None else (self.project_root,)

    def _new_session(self) -> Session:
        return Session(module_paths=self._module_paths())

    @staticmethod
    def _unexpected(error: BaseException, source: str, phase: str) -> Diagnostic:
        return Diagnostic(str(error) or type(error).__name__, 0, min(1, len(source)),
                          1, 1, "error", phase)

    def syntax_diagnostics(self, source: str) -> list[Diagnostic]:
        try:
            parse_program(source)
            return []
        except LanguageError as error:
            return [Diagnostic.from_error(error, phase="syntax")]
        except BaseException as error:
            return [self._unexpected(error, source, "syntax")]

    def semantic_diagnostics(self, source: str, *, path: str | Path | None = None) -> list[Diagnostic]:
        # Parsing separately prevents semantic execution after an incomplete edit.
        syntax = self.syntax_diagnostics(source)
        if syntax:
            return syntax
        try:
            self._new_session().execute_source(source, path=path)
            return []
        except LanguageError as error:
            return [Diagnostic.from_error(error, phase="semantic")]
        except Exception as error:
            # The IDE analysis boundary must be total: an unexpected backend
            # exception is reported as a diagnostic rather than escaping into Qt.
            return [self._unexpected(error, source, "semantic")]

    def execute(self, source: str, *, reset: bool = True,
                path: str | Path | None = None) -> tuple[OutputItem, ...]:
        if reset:
            self.runtime = self._new_session()
        try:
            result = self.runtime.execute_source(source, path=path)
        except LanguageError as error:
            return (OutputItem("error", str(error)),)
        except (ValueError, ArithmeticError) as error:
            return (OutputItem("error", str(error)),)

        items: list[OutputItem] = []

        # Session output is grouped by statement.  In particular,
        # ``print(a, b, c)`` has one console line but three mathematical values.
        # Render every value as its own preview item while only the first item in
        # a group owns the corresponding console line.
        if result.output_groups and len(result.output_groups) == len(result.output):
            for group, console_line in zip(result.output_groups, result.output):
                if not group:
                    # ``print()`` still emits its (empty) console line but has no
                    # mathematical object to render.
                    items.append(OutputItem("text", console_line, None, console_line, True))
                    continue
                for index, value in enumerate(group):
                    text = format_term(value)
                    latex = None
                    try:
                        latex = format_latex(value)
                    except Exception:
                        # Presentation failures must never turn successful execution into
                        # an IDE failure. Unsupported values remain ordinary text output.
                        pass
                    items.append(OutputItem(
                        "math" if latex else "text",
                        text,
                        latex,
                        console_line if index == 0 else None,
                        index == 0,
                    ))
            return tuple(items)

        # Compatibility fallback for ExecutionResult instances created by older
        # clients or serialized fixtures that do not provide output_groups.
        for value, text in zip(result.values, result.output):
            latex = None
            try:
                latex = format_latex(value)
            except Exception:
                pass
            items.append(OutputItem("math" if latex else "text", text, latex, text, True))
        if len(result.output) > len(items):
            items.extend(OutputItem("text", text, None, text, True)
                         for text in result.output[len(items):])
        return tuple(items)

    def execute_repl(self, source: str) -> tuple[OutputItem, ...]:
        return self.execute(source, reset=False)

    def resolve_expression(self, expression: str) -> Term:
        return self.runtime.resolve(expression)

    def assumptions(self) -> tuple[str, ...]:
        return tuple(format_term(p) for p in self.runtime.context.assumptions.predicates)

    def properties(self):
        """Current immutable contracts for a read-only IDE inspector."""
        from ..theories import Implementation
        from ..modules import Namespace
        results, seen = [], set()
        stack = [(name, d.term) for name, d in self.runtime.environment.definitions.items()]
        while stack:
            name, value = stack.pop()
            if id(value) in seen:
                continue
            seen.add(id(value))
            if isinstance(value, Implementation):
                results.append((name, value))
            elif isinstance(value, Namespace):
                stack.extend((name+'.'+d.symbol.name, d.term) for d in value.definitions)
        return tuple(sorted(results, key=lambda pair: pair[0]))

    def inspect_expression(self, expression: str, *, source: str | None = None,
                           path: str | Path | None = None) -> str:
        """Inspect a call before evaluation, optionally after an editor buffer prefix."""
        session = self.runtime
        if source is not None:
            session = self._new_session()
            session.execute_source(source, path=path)
        return format_typed_ir(session.typed_ir(expression))

    def plot(self, expression: str, variable: str, start: float, end: float,
             *, points: int = 600) -> PlotSpec:
        if not valid_name(variable):
            raise ValueError("Plot variable must be an identifier")
        variable = canonical_name(variable)
        try:
            term = self.runtime.resolve(expression)
        except LanguageError as first_error:
            # A standalone plotting expression should work before the file has
            # been executed. In that case introduce only the requested real
            # coordinate in a disposable session. Other missing names still
            # surface as genuine language errors.
            scratch = self._new_session()
            scratch.execute(f"variable {variable}:Real")
            try:
                term = scratch.resolve(expression)
            except LanguageError:
                raise first_error
        return sample_expression(term, variable, start, end, points=points,
                                 label=format_term(term, max_length=200))

    def completions(self, prefix: str = "", *, source: str | None = None) -> tuple[str, ...]:
        """Complete top-level names without evaluating incomplete editor input.

        With source supplied, runtime names from other files are excluded. Local
        function scopes and unresolved imported members await a scope-aware service.
        """
        names = set(_KEYWORDS) | set(MATH_ALIASES)
        names.update(('Nat', 'Integer', 'Rational', 'Real', 'Complex', 'Function', 'Vector', 'Matrix', 'Predicate'))
        scope = self.runtime.environment if source is None else self._new_session().environment
        while scope is not None:
            names.update(scope.definitions)
            names.update(scope.imported_modules)
            if source is None and '.' in prefix:
                owner, _, _ = prefix.rpartition('.')
                definition = self.runtime.environment.get(owner)
                if definition is not None:
                    value = definition.term
                    members = getattr(value, 'definitions', ())
                    names.update(owner+'.'+d.symbol.name for d in members)
                    names.update(owner+'.'+g.name for g in getattr(value, 'generators', ()))
            scope = scope.parent
        if source is not None:
            # Recover preceding complete lines while a declaration is being typed.
            for _ in range(8):
                try:
                    program = parse_program(source)
                    break
                except LanguageError:
                    source, separator, _ = source.rpartition('\n')
                    if not separator:
                        program = ast.Program(())
                        break
            else:
                program = ast.Program(())
            stack = [(program, '')]
            while stack:
                program, owner = stack.pop()
                for statement in program.statements:
                    if isinstance(statement, ast.ImportStatement):
                        names.update(owner+(n.alias or n.name) for n in statement.names)
                        if not statement.names:
                            names.add(owner+(statement.alias or statement.module.split('.')[0]))
                    elif isinstance(statement, (ast.Declaration, ast.Assignment, ast.FunctionDefinition,
                                                ast.TheoryDeclaration, ast.ImplementationDeclaration,
                                                ast.TypedFunctionDefinition, ast.NamespaceDeclaration,
                                                ast.AlgebraDeclaration, ast.RuleDeclaration)):
                        if statement.name is not None:
                            name = owner+statement.name
                            names.add(name)
                            if isinstance(statement, ast.NamespaceDeclaration):
                                stack.append((statement.body, name+'.'))
                            elif isinstance(statement, ast.AlgebraDeclaration):
                                names.update(name+'.'+g.name for g in statement.generators)
        return tuple(sorted(name for name in names if not prefix or name.startswith(prefix)))
