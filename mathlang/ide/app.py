"""Bundled mathlang desktop IDE (PySide6)."""

from __future__ import annotations

import io
from pathlib import Path
import re
import sys
import traceback
import tempfile

try:
    from PySide6.QtCore import QDir, QTimer, Qt, Signal
    from PySide6.QtGui import (
        QAction, QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QPixmap,
    )
    from PySide6.QtWidgets import (
        QApplication, QDialog, QDialogButtonBox, QFileDialog, QFileSystemModel,
        QFormLayout, QGraphicsScene, QGraphicsTextItem, QGraphicsView, QHBoxLayout,
        QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
        QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QToolBar, QTreeView,
        QVBoxLayout, QWidget, QTreeWidget, QTreeWidgetItem,
    )
except ImportError as error:  # pragma: no cover - exercised only without GUI extras
    raise SystemExit('MathLang IDE requires: pip install -e ".[ide]"') from error

from .editor import CodeEditor
from .language_service import Diagnostic, LanguageService, OutputItem
from .text_positions import qt_position, source_position
from .latex_compile import LatexCompileError, LatexCompilerUnavailable, compile_latex
from .theme import DARK_STYLESHEET


class PreviewView(QGraphicsView):
    """Scrollable preview canvas with mouse-centric zoom and hand panning."""

    zoomChanged = Signal(int)

    def __init__(self, scene: QGraphicsScene, parent=None) -> None:
        super().__init__(scene, parent)
        self._zoom = 1.0
        self.setObjectName("PreviewCanvas")
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    @property
    def zoom_percent(self) -> int:
        return round(self._zoom * 100)

    def set_zoom(self, value: float) -> None:
        value = min(4.0, max(0.25, value))
        self.resetTransform()
        self.scale(value, value)
        self._zoom = value
        self.zoomChanged.emit(self.zoom_percent)

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self._zoom * factor)

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    def fit_content(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            self.reset_zoom()
            return
        rect = rect.adjusted(-28, -28, 28, 28)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        fitted = self.transform().m11()
        if fitted < 0.25 or fitted > 4.0:
            self.set_zoom(fitted)
        else:
            self._zoom = fitted
            self.zoomChanged.emit(self.zoom_percent)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.14 if event.angleDelta().y() > 0 else 1 / 1.14)
            event.accept()
            return
        super().wheelEvent(event)


class MathPreview(QWidget):
    """Multi-result mathematical canvas used by file, selection and REPL runs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MathPreviewPane")
        self.setMinimumWidth(320)
        self._outputs: list[OutputItem] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        header = QWidget(self)
        header.setObjectName("PreviewHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(2, 0, 0, 0)
        header_layout.setSpacing(5)

        title_box = QWidget(header)
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 10, 0)
        title_layout.setSpacing(1)
        self.title = QLabel("Preview")
        self.title.setObjectName("PaneTitle")
        self.hint = QLabel("Ctrl + wheel to zoom · drag to pan")
        self.hint.setObjectName("PaneHint")
        title_layout.addWidget(self.title)
        title_layout.addWidget(self.hint)
        header_layout.addWidget(title_box, 1)

        self.zoom_out_button = QPushButton("−")
        self.zoom_out_button.setToolTip("Zoom out")
        self.zoom_out_button.setObjectName("PreviewControl")
        self.zoom_label = QPushButton("100%")
        self.zoom_label.setToolTip("Reset zoom")
        self.zoom_label.setObjectName("PreviewZoom")
        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip("Zoom in")
        self.zoom_in_button.setObjectName("PreviewControl")
        self.fit_button = QPushButton("Fit")
        self.fit_button.setToolTip("Fit all results")
        self.fit_button.setObjectName("PreviewFit")
        for button in (self.zoom_out_button, self.zoom_label, self.zoom_in_button, self.fit_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            header_layout.addWidget(button)
        root.addWidget(header)

        self.scene = QGraphicsScene(self)
        self.view = PreviewView(self.scene, self)
        root.addWidget(self.view, 1)

        self.zoom_out_button.clicked.connect(lambda: self.view.zoom_by(1 / 1.2))
        self.zoom_in_button.clicked.connect(lambda: self.view.zoom_by(1.2))
        self.zoom_label.clicked.connect(self.view.reset_zoom)
        self.fit_button.clicked.connect(self.view.fit_content)
        self.view.zoomChanged.connect(lambda value: self.zoom_label.setText(f"{value}%"))
        self._rebuild_scene()

    @staticmethod
    def _math_pixmap(latex: str) -> QPixmap:
        # math_to_image uses the standalone MathText parser and therefore does not
        # interfere with the Qt Matplotlib backend used by plot windows.
        from matplotlib import rc_context
        from matplotlib.font_manager import FontProperties
        from matplotlib.mathtext import math_to_image

        buffer = io.BytesIO()
        # MathText normally saves an opaque white figure.  A transparent image
        # keeps formulas crisp and high-contrast on the IDE's dark result cards.
        with rc_context({
            "figure.facecolor": "none",
            "savefig.facecolor": "none",
            "savefig.transparent": True,
        }):
            math_to_image(
                "$" + latex + "$", buffer, dpi=180, format="png",
                color="#f2f5f9", prop=FontProperties(size=18),
            )
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
            raise ValueError("Mathematical preview image could not be decoded")
        return pixmap

    def clear_outputs(self) -> None:
        self._outputs.clear()
        self._rebuild_scene()

    def set_outputs(self, items: tuple[OutputItem, ...], *, append: bool = False) -> None:
        if append:
            self._outputs.extend(items)
        else:
            self._outputs = list(items)
        self._rebuild_scene()

    def _text_item(self, text: str, *, color: str, size: int = 12) -> QGraphicsTextItem:
        item = QGraphicsTextItem(text)
        item.setDefaultTextColor(QColor(color))
        item.setFont(QFont("Segoe UI", size))
        item.setTextWidth(560)
        self.scene.addItem(item)
        return item

    def _rebuild_scene(self) -> None:
        self.scene.clear()
        if not self._outputs:
            empty = self._text_item(
                "Run a file, selection, or REPL expression.\nEvery result will appear here.",
                color="#7f8a9a", size=12,
            )
            empty.setPos(30, 34)
            self.scene.setSceneRect(0, 0, 640, 220)
            return

        y = 24.0
        max_right = 640.0
        for index, output in enumerate(self._outputs, start=1):
            label = self._text_item(f"RESULT {index}", color="#7f8a9a", size=8)
            label.setPos(42, y + 15)

            content_x = 42.0
            content_y = y + 43.0
            content_width = 0.0
            content_height = 0.0
            if output.latex:
                try:
                    pixmap = self._math_pixmap(output.latex)
                    math_item = self.scene.addPixmap(pixmap)
                    math_item.setPos(content_x, content_y)
                    content_width = float(pixmap.width())
                    content_height = float(pixmap.height())
                except Exception:
                    fallback = self._text_item(output.text, color="#e9edf4", size=13)
                    fallback.setPos(content_x, content_y)
                    bounds = fallback.boundingRect()
                    content_width, content_height = bounds.width(), bounds.height()
            else:
                color = "#ff8fa3" if output.kind == "error" else "#d7dde7"
                fallback = self._text_item(output.text, color=color, size=12)
                fallback.setPos(content_x, content_y)
                bounds = fallback.boundingRect()
                content_width, content_height = bounds.width(), bounds.height()

            card_width = max(560.0, content_width + 48.0)
            card_height = max(94.0, content_height + 68.0)
            card = self.scene.addRect(
                24, y, card_width, card_height,
                QPen(QColor("#2b3441")), QBrush(QColor("#151a21")),
            )
            card.setZValue(-1)
            y += card_height + 14.0
            max_right = max(max_right, 24.0 + card_width + 24.0)

        self.scene.setSceneRect(0, 0, max_right, y + 18.0)

    # Compatibility for callers outside the bundled window.
    def show_latex(self, latex: str | None, fallback: str = "") -> None:
        kind = "math" if latex else "text"
        self.set_outputs((OutputItem(kind, fallback or "No mathematical preview available.", latex),))


class PlotDialog(QDialog):
    def __init__(self, expression: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plot expression")
        form = QFormLayout(self)
        self.expression = QLineEdit(expression)
        self.variable = QLineEdit("x")
        self.start = QLineEdit("-10")
        self.end = QLineEdit("10")
        form.addRow("Expression", self.expression)
        form.addRow("Variable", self.variable)
        form.addRow("From", self.start)
        form.addRow("To", self.end)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class DocumentTab(QWidget):
    changed = Signal()

    def __init__(self, path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.dirty = False
        self.version = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.editor = CodeEditor()
        layout.addWidget(self.editor)
        self.editor.textChanged.connect(self._on_changed)
        if path and path.exists():
            self.editor.setPlainText(path.read_text(encoding="utf-8-sig"))
            self.dirty = False

    def _on_changed(self) -> None:
        self.dirty = True
        self.version += 1
        self.changed.emit()

    @property
    def title(self) -> str:
        name = self.path.name if self.path else "Untitled.math"
        return name + (" •" if self.dirty else "")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MathLang IDE")
        self.resize(1500, 930)
        self.project_root: Path | None = None
        self.service = LanguageService()
        self.analysis_timer = QTimer(self)
        self.analysis_timer.setSingleShot(True)
        self.analysis_timer.setInterval(650)
        # Semantic analysis is deliberately run on the GUI thread for now.  The
        # current examples finish in a few milliseconds, while the previous
        # QRunnable implementation could deliver signals after a tab/worker had
        # already been destroyed and caused intermittent native Qt crashes.
        # A future heavy analyser should use an isolated persistent subprocess,
        # not short-lived QObject/QRunnable pairs.
        self.analysis_timer.timeout.connect(self._run_semantic_analysis)

        self._build_ui()
        self._build_actions()
        self.new_file()

    def _build_ui(self) -> None:
        self.file_model = QFileSystemModel(self)
        self.file_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.file_model.setNameFilters(["*.math", "*.tex", "*.md"])
        self.file_model.setNameFilterDisables(False)
        self.tree = QTreeView()
        self.tree.setObjectName("ProjectTree")
        self.tree.setModel(self.file_model)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        self.tree.doubleClicked.connect(self._tree_open)
        for column in range(1, 4):
            self.tree.hideColumn(column)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("EditorTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)

        self.preview = MathPreview()

        center = QSplitter(Qt.Orientation.Horizontal)
        center.addWidget(self.tree)
        center.addWidget(self.tabs)
        center.addWidget(self.preview)
        center.setStretchFactor(0, 0)
        center.setStretchFactor(1, 1)
        center.setStretchFactor(2, 0)
        center.setHandleWidth(1)
        center.setSizes([230, 900, 370])

        self.problems = QListWidget()
        self.problems.itemDoubleClicked.connect(self._jump_to_problem)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.repl_output = QPlainTextEdit()
        self.repl_output.setReadOnly(True)
        self.repl_input = QLineEdit()
        self.repl_input.setPlaceholderText("Enter mathlang expression or statement…")
        self.repl_input.returnPressed.connect(self.run_repl)
        repl = QWidget()
        repl_layout = QVBoxLayout(repl)
        repl_layout.setContentsMargins(0, 0, 0, 0)
        repl_layout.addWidget(self.repl_output)
        repl_layout.addWidget(self.repl_input)

        self.bottom = QTabWidget()
        self.bottom.setObjectName("BottomTabs")
        self.bottom.setDocumentMode(True)
        self.bottom.addTab(self.problems, "Problems")
        self.bottom.addTab(self.output, "Output")
        self.bottom.addTab(repl, "REPL")
        self.type_inspector = QPlainTextEdit()
        self.type_inspector.setReadOnly(True)
        self.bottom.addTab(self.type_inspector, "Types")
        self.assumption_inspector = QPlainTextEdit()
        self.assumption_inspector.setReadOnly(True)
        self.bottom.addTab(self.assumption_inspector, 'Assumptions')
        self.property_inspector = QTreeWidget()
        self.property_inspector.setHeaderLabels(['Implementation / property', 'Status', 'Method', 'Declared in'])
        self.property_inspector.setColumnWidth(0, 320)
        self.property_inspector.setColumnWidth(1, 110)
        self.property_inspector.setColumnWidth(2, 130)
        self.property_inspector.setToolTip('Verified obligations and exact counterexamples. Hover a property for its statement.')
        self.bottom.addTab(self.property_inspector, 'Properties')
        self._refresh_assumptions()

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.addWidget(center)
        vertical.addWidget(self.bottom)
        vertical.setStretchFactor(0, 1)
        vertical.setHandleWidth(1)
        vertical.setSizes([735, 175])
        self.setCentralWidget(vertical)
        self.statusBar().showMessage("Ready")

    def _action(self, text: str, shortcut: str | None, slot) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        return action

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        run_menu = self.menuBar().addMenu("Run")
        view_menu = self.menuBar().addMenu("View")
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        actions = [
            (file_menu, self._action("New", "Ctrl+N", self.new_file)),
            (file_menu, self._action("Open file…", "Ctrl+O", self.open_file_dialog)),
            (file_menu, self._action("Open project…", "Ctrl+Shift+O", self.open_project_dialog)),
            (file_menu, self._action("Save", "Ctrl+S", self.save_file)),
            (run_menu, self._action("Run file", "Ctrl+Enter", self.run_file)),
            (run_menu, self._action("Run selection", "Ctrl+Shift+Enter", self.run_selection)),
            (run_menu, self._action("Plot expression…", "Ctrl+P", self.plot_expression)),
            (run_menu, self._action("Compile LaTeX / PDF", "Ctrl+Alt+L", self.compile_latex_document)),
            (view_menu, self._action("Toggle math preview", None, lambda: self.preview.setVisible(not self.preview.isVisible()))),
            (view_menu, self._action("Inspect expression types", "Ctrl+Alt+T", self.inspect_types)),
            (view_menu, self._action('Inspect properties', 'Ctrl+Alt+P', lambda: self.bottom.setCurrentWidget(self.property_inspector))),
        ]
        for menu, action in actions:
            menu.addAction(action)
        for action in (actions[3][1], actions[4][1], actions[6][1]):
            toolbar.addAction(action)

    def current_tab(self) -> DocumentTab | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, DocumentTab) else None

    def new_file(self) -> None:
        tab = DocumentTab()
        tab.editor.completion_provider = lambda prefix, source: self.service.completions(prefix, source=source)
        tab.changed.connect(lambda tab=tab: self._document_changed(tab))
        index = self.tabs.addTab(tab, tab.title)
        self.tabs.setCurrentIndex(index)
        tab.editor.setFocus()

    def open_file_dialog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open MathLang file",
                                                  str(self.project_root or Path.cwd()),
                                                  "MathLang (*.math);;All files (*)")
        if filename:
            self.open_file(Path(filename))

    def open_file(self, path: Path) -> None:
        path = path.resolve()
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, DocumentTab) and tab.path == path:
                self.tabs.setCurrentIndex(i)
                return
        tab = DocumentTab(path)
        tab.editor.completion_provider = lambda prefix, source: self.service.completions(prefix, source=source)
        tab.changed.connect(lambda tab=tab: self._document_changed(tab))
        index = self.tabs.addTab(tab, tab.title)
        self.tabs.setCurrentIndex(index)
        if self.project_root is None:
            self._set_project(path.parent)
        self._document_changed(tab)

    def open_project_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open MathLang project",
                                                     str(self.project_root or Path.cwd()))
        if directory:
            self._set_project(Path(directory))

    def _set_project(self, root: Path) -> None:
        self.project_root = root.resolve()
        self.service = LanguageService(self.project_root)
        index = self.file_model.setRootPath(str(self.project_root))
        self.tree.setRootIndex(index)
        self._refresh_assumptions()
        self.statusBar().showMessage(f"Project: {self.project_root}")

    def _tree_open(self, index) -> None:
        path = Path(self.file_model.filePath(index))
        if path.is_file():
            self.open_file(path)

    def save_file(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if tab.path is None:
            filename, _ = QFileDialog.getSaveFileName(self, "Save MathLang file",
                                                      str(self.project_root or Path.cwd()),
                                                      "MathLang (*.math)")
            if not filename:
                return
            tab.path = Path(filename).resolve()
            if self.project_root is None:
                self._set_project(tab.path.parent)
        tab.path.write_text(tab.editor.toPlainText(), encoding="utf-8")
        tab.dirty = False
        self._refresh_tab_title(tab)
        self.statusBar().showMessage(f"Saved {tab.path}", 2500)

    def close_tab(self, index: int) -> None:
        tab = self.tabs.widget(index)
        if isinstance(tab, DocumentTab) and tab.dirty:
            answer = QMessageBox.question(self, "Unsaved changes", f"Close {tab.title} without saving?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.tabs.removeTab(index)
        if self.tabs.count() == 0:
            self.new_file()

    def _refresh_tab_title(self, tab: DocumentTab) -> None:
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.setTabText(index, tab.title)

    def _document_changed(self, tab: DocumentTab) -> None:
        self._refresh_tab_title(tab)
        if tab is not self.current_tab():
            return
        source = tab.editor.toPlainText()
        diagnostics = self.service.syntax_diagnostics(source)
        self._apply_diagnostics(tab, diagnostics)
        if not diagnostics:
            self.analysis_timer.start()

    def _run_semantic_analysis(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        version = tab.version
        source = tab.editor.toPlainText()
        try:
            diagnostics = self.service.semantic_diagnostics(source, path=tab.path)
        except Exception as error:  # GUI boundary: diagnostics must never terminate Qt.
            diagnostics = [Diagnostic(
                str(error) or type(error).__name__, 0, min(1, len(source)),
                1, 1, "error", "semantic",
            )]
        if tab is self.current_tab() and tab.version == version:
            self._apply_diagnostics(tab, diagnostics)

    def _apply_diagnostics(self, tab: DocumentTab, diagnostics: list[Diagnostic]) -> None:
        tab.editor.set_diagnostics(diagnostics)
        if tab is not self.current_tab():
            return
        self.problems.clear()
        for diagnostic in diagnostics:
            item = QListWidgetItem(
                f"{diagnostic.phase}: {diagnostic.message}  [{diagnostic.line}:{diagnostic.column}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, diagnostic)
            item.setForeground(QColor("#ff7b93"))
            self.problems.addItem(item)
        count = len(diagnostics)
        self.bottom.setTabText(0, f"Problems ({count})")

    def _jump_to_problem(self, item: QListWidgetItem) -> None:
        diagnostic = item.data(Qt.ItemDataRole.UserRole)
        tab = self.current_tab()
        if tab is None or not isinstance(diagnostic, Diagnostic):
            return
        cursor = tab.editor.textCursor()
        cursor.setPosition(qt_position(tab.editor.toPlainText(), diagnostic.start))
        tab.editor.setTextCursor(cursor)
        tab.editor.setFocus()

    def _tab_changed(self, _index: int) -> None:
        tab = self.current_tab()
        if tab:
            self._document_changed(tab)

    def _append_outputs(self, items: tuple[OutputItem, ...], *, clear: bool = True) -> None:
        self._refresh_assumptions()
        if clear:
            self.output.clear()
        for item in items:
            if not item.show_in_console:
                continue
            prefix = "Error: " if item.kind == "error" else ""
            text = item.text if item.console_text is None else item.console_text
            self.output.appendPlainText(prefix + text)
        self.preview.set_outputs(items, append=not clear)
        self.bottom.setCurrentWidget(self.output)

    def _refresh_assumptions(self) -> None:
        self.assumption_inspector.setPlainText('\n'.join(self.service.assumptions()) or 'No active assumptions.')
        self.property_inspector.clear()
        from ..renderer import format_term
        colors = {'proved': '#98c379', 'disproved': '#e06c75', 'unknown': '#e5c07b', 'assumed': '#c792ea'}
        for name, implementation in self.service.properties():
            theory = implementation.theory
            root = QTreeWidgetItem([name, implementation.valid.value, theory.name, ''])
            root.setToolTip(0, format_term(theory))
            self.property_inspector.addTopLevelItem(root)
            for result in implementation.properties:
                label = ('Defined: '+result.name.removeprefix('_total_') if result.name.startswith('_total_') else result.name)
                origins = ', '.join(theory.origins(result.name))
                child = QTreeWidgetItem([label, result.status, result.method, origins])
                child.setForeground(1, QBrush(QColor(colors[result.status])))
                child.setToolTip(0, format_term(result) + '\nDeclared in: ' + origins)
                child.setToolTip(3, origins)
                root.addChild(child)
            root.setExpanded(True)

    def run_file(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        self.service = LanguageService(self.project_root)
        items = self.service.execute(tab.editor.toPlainText(), reset=True, path=tab.path)
        self._append_outputs(items)
        self.statusBar().showMessage("Execution finished", 2500)

    def inspect_types(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        cursor = tab.editor.textCursor()
        source = tab.editor.toPlainText()
        if cursor.hasSelection():
            start = source_position(source, cursor.selectionStart())
            expression = cursor.selectedText().replace('\u2029', '\n')
        else:
            start = source_position(source, cursor.block().position())
            expression = cursor.block().text()
        try:
            result = self.service.inspect_expression(expression, source=source[:start], path=tab.path)
        except Exception as error:
            result = str(error) or type(error).__name__
        self.type_inspector.setPlainText(result)
        self.bottom.setCurrentWidget(self.type_inspector)

    def run_selection(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        selected = tab.editor.textCursor().selectedText().replace("\u2029", "\n")
        if not selected.strip():
            selected = tab.editor.textCursor().block().text()
        items = self.service.execute_repl(selected)
        self._append_outputs(items, clear=False)

    def run_repl(self) -> None:
        source = self.repl_input.text().strip()
        if not source:
            return
        self.repl_output.appendPlainText(">>> " + source)
        items = self.service.execute_repl(source)
        self._refresh_assumptions()
        for item in items:
            if not item.show_in_console:
                continue
            text = item.text if item.console_text is None else item.console_text
            self.repl_output.appendPlainText(text)
        self.preview.set_outputs(items, append=True)
        self.repl_input.clear()

    def compile_latex_document(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        source = tab.editor.toPlainText()
        work = tempfile.TemporaryDirectory(prefix="mathlang-tex-")
        try:
            filename = tab.path.name if tab.path and tab.path.suffix.lower() == ".tex" else "document.tex"
            result = compile_latex(source, work.name, filename=filename)
        except (LatexCompilerUnavailable, LatexCompileError) as error:
            work.cleanup()
            QMessageBox.critical(self, "LaTeX compilation", str(error))
            return
        self.output.clear()
        self.output.setPlainText(result.log or f"Compiled {result.pdf_path.name}")
        self.bottom.setCurrentWidget(self.output)
        self._show_pdf_preview(result.pdf_path, work)

    def _show_pdf_preview(self, path: Path, work) -> None:
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView
        except ImportError:
            work.cleanup()
            QMessageBox.information(self, "PDF ready", f"Compiled PDF: {path}")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("PDF preview — " + path.name)
        dialog.resize(980, 760)
        layout = QVBoxLayout(dialog)
        document = QPdfDocument(dialog)
        status = document.load(str(path))
        view = QPdfView(dialog)
        view.setDocument(document)
        try:
            view.setPageMode(QPdfView.PageMode.MultiPage)
            view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        except AttributeError:
            pass
        layout.addWidget(view)
        # Keep the temporary compilation directory alive for QPdfDocument.
        dialog._mathlang_tempdir = work
        dialog.finished.connect(lambda _code, d=dialog: d._mathlang_tempdir.cleanup())
        dialog.exec()

    def plot_expression(self) -> None:
        tab = self.current_tab()
        selected = ""
        if tab:
            selected = tab.editor.textCursor().selectedText().replace("\u2029", "\n").strip()
            if not selected:
                selected = tab.editor.textCursor().block().text().strip()
        dialog = PlotDialog(selected, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            spec = self.service.plot(dialog.expression.text(), dialog.variable.text().strip(),
                                     float(dialog.start.text()), float(dialog.end.text()))
            self._show_plot(spec)
        except Exception as error:
            QMessageBox.critical(self, "Plot error", str(error))

    def _show_plot(self, spec) -> None:
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
        except ImportError:
            QMessageBox.critical(self, "Plotting unavailable", "Install the IDE extras with matplotlib.")
            return
        window = QDialog(self)
        window.setWindowTitle("Plot — " + spec.title)
        window.resize(900, 620)
        layout = QVBoxLayout(window)
        figure = Figure(figsize=(8, 5))
        canvas = FigureCanvasQTAgg(figure)
        axes = figure.subplots()
        for series in spec.series:
            axes.plot(series.x, series.y, label=series.label)
        axes.axhline(0, linewidth=0.7)
        axes.axvline(0, linewidth=0.7)
        axes.set_xlabel(spec.x_label)
        axes.set_ylabel(spec.y_label)
        axes.grid(True, alpha=0.25)
        if len(spec.series) > 1:
            axes.legend()
        layout.addWidget(canvas)
        canvas.draw()
        window.exec()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MathLang IDE")
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
