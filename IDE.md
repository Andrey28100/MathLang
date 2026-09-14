# MathLang IDE

The repository now contains an optional desktop IDE in `mathlang.ide`. It is a
thin presentation layer over the existing parser, resolver, evaluator and
renderer; it does not implement a second language frontend.

## Install and run

```bash
python -m pip install -e ".[ide]"
mathlang-ide
```

The base `mathlang` package still has no third-party runtime dependencies. The
`ide` extra installs PySide6 and matplotlib only for the desktop application.

## Included in the MVP

- dark desktop UI with project tree and tabbed `.math` editor;
- line numbers and MathLang-oriented syntax highlighting;
- multiline block comments and Unicode-aware highlighting and diagnostic ranges;
- name completion with `Ctrl+Space` (also offered after two characters);
- a **Types** pane for pre-evaluation Typed IR, including explicit embeddings;
- an **Assumptions** pane showing active runtime conditions, with logic keyword completion/highlighting;
- immediate syntax diagnostics and delayed semantic diagnostics;
- source-range wave underlines plus a Problems panel;
- debounced semantic analysis after editing pauses; the current pass runs on the
  Qt thread because the existing examples complete in milliseconds and this avoids
  unsafe short-lived Qt worker lifetimes; a future heavy analyser should move to a
  persistent isolated subprocess;
- deterministic **Run file** and persistent REPL / **Run selection**;
- structured `OutputItem` values with a LaTeX renderer for mathematical terms;
- `ApproxNumber` results from `expr |> numeric(digits)` are rendered with `\approx`,
  so an approximation is visually distinct from an exact decimal literal;
- mathematical preview rendered locally through matplotlib MathText;
- real LaTeX-to-PDF compilation through Tectonic (`--untrusted`) and an embedded Qt PDF preview;
- an IDE-neutral `PlotSpec` and scalar plot sampler for expressions such as
  `sin(x)`, `x^2`, `exp(-x^2)`, etc.;
- an embedded matplotlib plot window;
- a standalone `LanguageService` with no Qt dependency, suitable for reuse by a
  future Tauri/CodeMirror or LSP frontend.

## Architecture

```text
PySide6 UI
  ├─ editor / project tree / Problems / Output / REPL
  ├─ LaTeX preview
  └─ Plot viewer
           │
           ▼
mathlang.ide.LanguageService
  ├─ syntax_diagnostics() -> parser
  ├─ semantic_diagnostics() -> disposable Session
  ├─ execute()/execute_repl() -> Session
  ├─ inspect_expression() -> Session.typed_ir()
  ├─ completions() -> syntax declarations / runtime names
  ├─ assumptions() -> current Session context
  ├─ format_latex() -> immutable Term DAG
  └─ plot() -> PlotSpec
           │
           ▼
existing mathlang frontend + kernel
```

`semantic_diagnostics()` always uses a disposable session, so merely editing a
file cannot mutate REPL/runtime state. Analysis is delayed until the user pauses
editing. It is currently synchronous at the GUI boundary to avoid the intermittent
Qt lifetime race that existed in the first MVP; the language service itself remains
UI-independent.


## Stability fixes after the first MVP

- Removed the short-lived `QRunnable`/`QObject` semantic-analysis workers that could
  race with tab destruction and crash Qt intermittently while examples were opened.
- Semantic-analysis exceptions are converted to diagnostics at the IDE boundary.
- Mathematical preview now uses `matplotlib.mathtext.math_to_image()` directly and
  never switches Matplotlib's global GUI backend.
- Proof reports and other non-`Term` values are no longer wrapped in unsupported
  `\texttt{...}` math; raw LaTeX is never displayed as a preview fallback.

## Plotting contract

The GUI consumes `PlotSpec` rather than depending on a future `plot` syntax.
When plotting becomes a first-class MathLang feature, the language runtime can
emit the same frontend-neutral structure and the UI will not need to be
redesigned.

## Deliberate MVP limitations

- the current parser stops at the first syntax/semantic error, so the Problems
  panel currently reports one frontend error per analysis pass;
- completion lists keywords, types, mathematical aliases and preceding top-level
  buffer declarations, including declared namespace members; local function scopes,
  members of imports that have not been resolved, hover and go-to-definition are future work;
- LaTeX preview supports the central mathematical `Term` classes; non-mathematical
  runtime values such as proof reports stay in the textual Output panel instead of
  being misclassified as LaTeX;
- numeric plots intentionally support only safe scalar IR operations and common
  one-argument elementary builtins; they never call Python `eval`;
- plots check builtin identity, require other parameters to be substituted first,
  and mark real-domain holes as missing samples; they accept 2–10,000 points and
  expressions of at most 10,000 distinct DAG nodes;
- Tectonic is intentionally not bundled; install it separately or point `MATHLANG_TECTONIC` at the executable.

These boundaries keep the editor independent from unimplemented language
features and preserve the existing proof/evaluation trust boundary.

## Types and editing buffers

Select an expression, then press **Ctrl+Alt+T** (View → Inspect expression types).
Without a selection, the current line is treated as an expression. The **Types**
pane displays the result type, preserved function calls and explicit `Embed`
nodes. Definitions before the selection/line are read from the unsaved buffer
in a disposable session; REPL state stays unchanged. Inspection inside an
unfinished function/block is not supported. Try `examples/ide_types.math`.

Both semantic diagnostics and **Run file** receive the document path. Imports
therefore use the same file/package search roots as CLI execution, even if the
file is nested below the selected project or its buffer differs from disk.
The reusable API is `Session.execute_source(source, path=...)`.

The optional GUI tests run with Qt's offscreen platform:

```powershell
python -m unittest tests.test_ide_editor tests.test_ide_service -v
```

## Predicates and assumptions (0.8)

The **Assumptions** pane lists explicitly active runtime predicates. **Run file**
starts a fresh session; **Run selection** and **REPL** keep that session's conditions.
Changing the project clears the session and the pane. An unsuccessful input rolls
back its assumptions along with definitions. Syntax/semantic analysis never changes
this pane or the runtime context.

`assuming {x>0} { ... }` keeps both assumptions and definitions inside the block.
After the block, the pane again reflects the enclosing context. Derived conditions
are not listed separately. There is no assumption editor or selective removal yet.

`Predicate`, comparisons, logical operations and `domain(...)` have LaTeX renderers;
evaluated predicates display `True`, `False` or `Unknown`. A saved predicate is
queried again in the current context when printed. Try `examples/logic.math` and
see [docs/LOGIC.md](docs/LOGIC.md) for the supported inference fragment.

## Preview workspace

Version 0.8.1 adds completion/highlighting for `iterate`, `sum`, `product`,
`all` and `any`. Symbolic indexed calls render with ∑, ∏, ⋀ and ⋁, including
bounds and their bound variable. **Types** preserves the call and shows the
specialized function signature before execution. Try `examples/iteration.math`
and `examples/mandelbrot.math`; the latter tests individual complex points with
exact arithmetic and an explicit finite iteration budget.

Version 0.8.2 adds typed state/index blocks such as
`iterate(1,6) {(value:Nat,index:Nat)=>value*index}`, the built-in `factorial`,
and separate `antiderivative(expr,x)` / `integrate(expr,x,a,b)` operations.
Completion and highlighting include these names; the preview renders factorials
and bounded integrals. Series derivatives and primitives preserve `Series<Real>`
in **Types**. Try [examples/series_calculus.math](examples/series_calculus.math)
for series limits, explicit polynomial approximations and termwise indexed sums.
See [docs/CALCULUS.md](docs/CALCULUS.md) for supported cases and migration.

Version 0.9.0 adds **Properties** (View → Inspect properties, Ctrl+Alt+P).
It lists concrete implementations, their validity, every totality/axiom obligation,
and the proof method. Statuses are explicit: proved, disproved, unknown and assumed.
Hover a property to read its statement and any exact counterexample. The inspector
updates after execution and REPL, survives a failed input's rollback, and clears
when switching projects. Semantic checks of an editor buffer do not change it.
Theory declarations and forall have highlighting/completion; quantified predicates
render with ∀. Try [examples/theories.math](examples/theories.math) and see
[docs/THEORIES.md](docs/THEORIES.md) for the supported proof fragment.

Version 0.9.1 adds `extends` highlighting/completion and a **Declared in** column
in Properties. Inherited requirements name their original declaring theory;
shared diamond ancestors appear once. Hover the implementation to inspect its
parent contracts and complete requirements. The runnable example
[examples/theory_inheritance.math](examples/theory_inheritance.math) compares
addition with quaternion multiplication and demonstrates type specialization.

The mathematical preview is now a scrollable canvas rather than a single
last-result label.

- **Run file** replaces the canvas with every output from the run.
- **Run selection** and **REPL** append their outputs to the current canvas.
- Every value with a MathLang LaTeX representation is rendered as typeset math;
  textual/proof/error outputs remain readable text cards instead of raw LaTeX.
- Use **Ctrl + mouse wheel** or the **− / +** buttons to zoom from 25% to 400%.
- Drag directly on the preview to pan, use the ordinary wheel to scroll, click
  **100%** to reset the scale, and **Fit** to frame all current results.
- Formula images are rendered with transparent backgrounds for strong contrast in
  the dark theme.

The editor also supports **Ctrl + mouse wheel** font zoom, and the project tree,
editor tabs, result panel, scrollbars, and status area share the same revised dark
visual system.
