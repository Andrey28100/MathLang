"""Interactive symbolic session with multiline groups and explicit continuation."""

import sys
from typing import TextIO

from .renderer import RenderError, format_definition, format_rule_set, format_term
from .session import Session
from .source import LanguageError
from .lexer import TokenKind, tokenize


def _open_group(source: str) -> bool:
    try:
        tokens = tokenize(source)
    except LanguageError as error:
        return "Unterminated block comment" in error.message
    stack = []
    pairs = {TokenKind.RPAREN: TokenKind.LPAREN, TokenKind.RBRACE: TokenKind.LBRACE}
    for token in tokens:
        if token.kind in (TokenKind.LPAREN, TokenKind.LBRACE):
            stack.append(token.kind)
        elif token.kind in pairs:
            if not stack or stack.pop() != pairs[token.kind]:
                return False
    return bool(stack)


def run_repl(*, session: Session | None = None, stdin: TextIO | None = None,
             stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    session = Session() if session is None else session
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    interactive = stdin.isatty()
    pending: list[str] = []
    if interactive:
        print("mathlang — :help for commands, :quit to exit", file=stdout)
    while True:
        try:
            if interactive:
                print("... " if pending else ">>> ", end="", file=stdout, flush=True)
            line = stdin.readline()
        except KeyboardInterrupt:
            pending.clear()
            print(file=stdout)
            continue
        if not line:
            if pending:
                print("Incomplete input: unclosed group, comment or line continuation", file=stderr)
                return 1
            return 0
        line = line.rstrip("\r\n")
        if line.strip() == ":cancel":
            pending.clear()
            continue
        if not pending and line.strip().startswith(":"):
            command = line.strip()
            if command == ":quit":
                return 0
            if command == ":help":
                print(":memory — show definitions\n:quit — exit\n"
                      ":modules — show loaded modules\n"
                      ":type EXPR — show the inferred mathematical type\n"
                      ":assumptions — show active assumptions\n"
                      ":query PREDICATE — report True, False or Unknown\n"
                      ":save PATH — save the declared module as portable IR\n"
                      ":load PATH — import a compiled module\n"
                      ":cancel — discard unfinished input\n"
                      "Open parentheses, braces and block comments continue automatically.\n"
                      "End a line with \\ to continue input on the next line.", file=stdout)
            elif command == ":memory":
                definitions = session.environment.definitions.values()
                for definition in definitions:
                    try:
                        print(format_definition(definition), file=stdout)
                    except RenderError as error:
                        print(f"{definition.symbol.name}: {error}", file=stderr)
                anonymous = [group for group in session.environment.local_rule_sets if group.name is None]
                for group in anonymous:
                    try:
                        print(format_rule_set(group), file=stdout)
                    except RenderError as error:
                        print(error, file=stderr)
                if not definitions and not anonymous:
                    print("Memory is empty.", file=stdout)
            elif command == ":modules":
                print("\n".join(session.modules.cache) or "No modules loaded.", file=stdout)
            elif command == ':assumptions':
                print('\n'.join(format_term(p) for p in session.context.assumptions.predicates)
                      or 'No assumptions.', file=stdout)
            elif command.startswith(':query '):
                try:
                    print(session.query(command[7:].strip()).value, file=stdout)
                except ValueError as error:
                    print(error, file=stderr)
            elif command.startswith(':type '):
                try:
                    print(session.type_of(command[6:].strip()) or 'Unknown', file=stdout)
                except (ValueError, RecursionError) as error:
                    print(error, file=stderr)
            elif command.startswith(":save ") or command.startswith(":load "):
                action, _, path = command.partition(' ')
                try:
                    if action == ':save':
                        session.save_module(path.strip())
                        print(f"Saved module {session.module_name}.", file=stdout)
                    else:
                        module = session.load_module(path.strip())
                        print(f"Loaded module {module.name}.", file=stdout)
                except (ValueError, OSError, UnicodeError) as error:
                    print(error, file=stderr)
            else:
                print(f"Unknown command {command!r}; use :help", file=stderr)
            continue
        if line.rstrip().endswith("\\"):
            pending.append(line.rstrip()[:-1])
            continue
        pending.append(line)
        source = "\n".join(pending)
        if _open_group(source):
            continue
        pending.clear()
        try:
            result = session.execute(source)
            for output in result.output:
                print(output, file=stdout)
        except LanguageError as error:
            print(error, file=stderr)
        except KeyboardInterrupt:
            print(file=stdout)
