"""Tectonic integration used by the desktop IDE.

The compiler is intentionally an external process: the symbolic kernel never
executes TeX and the IDE can put a timeout around document compilation.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True, slots=True)
class LatexCompileResult:
    pdf_path: Path
    log: str


class LatexCompilerUnavailable(RuntimeError):
    pass


class LatexCompileError(RuntimeError):
    pass


def find_tectonic() -> str:
    configured = os.environ.get("MATHLANG_TECTONIC")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path)
        raise LatexCompilerUnavailable(
            f"MATHLANG_TECTONIC points to a missing executable: {path}"
        )
    executable = shutil.which("tectonic")
    if executable:
        return executable
    raise LatexCompilerUnavailable(
        "Tectonic was not found. Install Tectonic or set MATHLANG_TECTONIC to its executable."
    )


def compile_latex(source: str, output_dir: str | Path, *, timeout: float = 30.0,
                  filename: str = "document.tex") -> LatexCompileResult:
    """Compile UTF-8 LaTeX to PDF in *output_dir* using Tectonic.

    `--untrusted` keeps shell escape and other unsafe facilities disabled. The
    caller chooses the output directory so a GUI can keep the PDF alive while a
    preview window is open.
    """
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    tex_path = root / Path(filename).name
    tex_path.write_text(source, encoding="utf-8")
    executable = find_tectonic()
    command = [
        executable,
        "--untrusted",
        "--keep-logs",
        "--keep-intermediates",
        "--outdir", str(root),
        str(tex_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise LatexCompileError(f"LaTeX compilation exceeded {timeout:g} seconds") from error
    log = completed.stdout or ""
    pdf_path = root / (tex_path.stem + ".pdf")
    if completed.returncode != 0 or not pdf_path.is_file():
        tail = "\n".join(log.splitlines()[-30:])
        raise LatexCompileError(tail or f"Tectonic exited with code {completed.returncode}")
    return LatexCompileResult(pdf_path, log)
