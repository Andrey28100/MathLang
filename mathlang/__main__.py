"""Inspect expression syntax, execute a program, or start a symbolic session."""

import argparse
import sys
from pathlib import Path

from . import LanguageError, Session, format_tree, parse_expression
from .repl import run_repl
from .serialization import SerializationError, load_ir


def main() -> int:
    # Redirected Windows streams otherwise use a legacy code page, which cannot
    # represent the Unicode identifiers accepted by the language.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Parse expressions or define symbolic objects.")
    parser.add_argument("expression", nargs="?", help="source text; omit to read stdin")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run", action="store_true", help="execute definitions and expressions")
    modes.add_argument("--file", type=Path, help="execute a UTF-8 program file")
    modes.add_argument("--repl", action="store_true", help="start a session with memory")
    modes.add_argument("--compile", type=Path, help="compile a source module to portable IR")
    modes.add_argument("--check-ir", type=Path, help="validate IR and independently check its proof certificates")
    parser.add_argument("-o", "--output", type=Path, help="compiled module output path")
    parser.add_argument("--name", help="module name when compiling a file without a module declaration")
    parser.add_argument("-I", "--module-path", action="append", type=Path, default=[], help="additional module search root")
    parser.add_argument("--load", action="append", type=Path, default=[], help="load a compiled module before execution")
    args = parser.parse_args()
    if args.expression is not None and (args.repl or args.file is not None or args.compile is not None or args.check_ir is not None):
        parser.error("source text cannot be combined with a file, validation, compilation or REPL mode")
    if (args.output is not None or args.name is not None) and args.compile is None:
        parser.error("--output and --name require --compile")
    try:
        session = Session(module_paths=args.module_path)
        for path in args.load:
            session.load_module(path)
        if args.check_ir is not None:
            load_ir(args.check_ir)
            print("IR verified; all included proof certificates checked.")
            return 0
        if args.compile is not None:
            session.execute_file(args.compile)
            name = args.name or session.module_name or args.compile.stem
            if args.name is not None and session.module_name is not None and args.name != session.module_name:
                raise ValueError("--name conflicts with the source module declaration")
            output = args.output or args.compile.with_suffix('.mathir')
            if output.resolve() == args.compile.resolve():
                raise ValueError("Compiled output must be different from the source file")
            session.save_module(output, name=name)
            print(f"Compiled {name} to {output}")
            return 0
        if args.repl or (args.expression is None and args.file is None and sys.stdin.isatty()):
            return run_repl(session=session)
        source = ("" if args.file is not None
                  else args.expression if args.expression is not None else sys.stdin.read())
        if args.run or args.file is not None:
            result = session.execute_file(args.file) if args.file is not None else session.execute(source)
            for output in result.output:
                print(output)
        else:
            print(format_tree(parse_expression(source)))
    except (LanguageError, SerializationError, ValueError, OSError, UnicodeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
