"""Qt code editor with line numbers, syntax highlighting and diagnostics."""

from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt, QStringListModel
from PySide6.QtGui import (
    QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat,
)
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QWidget, QTextEdit

from .language_service import Diagnostic
from .text_positions import qt_position, source_position


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.editor.paint_line_numbers(event)


class MathlangHighlighter(QSyntaxHighlighter):
    KEYWORDS = {
        'theory', 'operation', 'axiom', 'implementation', 'implements', 'extends', 'forall',
        'assume', 'assuming', 'and', 'or', 'not', 'True', 'False', 'Unknown',
        "algebra", "as", "assert", "basis", "const", "derive", "function",
        "generator", "generators", "import", "module", "namespace", "over",
        "parameter", "prove", "relation", "relations", "return", "rule",
        "unknown", "use", "using", "variable", "when", "where", "with",
    }
    BUILTINS = {
        'iterate', 'sum', 'product', 'all', 'any', 'factorial', 'antiderivative',
        'query', 'domain',
        "sin", "cos", "tan", "exp", "log", "sqrt", "abs", "print",
        "normalize", "simplify", "substitute", "rewrite", "derivative",
        "integrate", "series", "limit", "polynomial", "numeric",
    }

    def __init__(self, document) -> None:
        super().__init__(document)
        self.keyword_format = self._format("#c792ea", bold=True)
        self.builtin_format = self._format("#82aaff")
        self.number_format = self._format("#f78c6c")
        self.comment_format = self._format("#637777", italic=True)
        self.type_format = self._format("#ffcb6b")
        self.operator_format = self._format("#89ddff")
        self.string_format = self._format("#c3e88d")

    @staticmethod
    def _format(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.DemiBold)
        fmt.setFontItalic(italic)
        return fmt

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        def paint(start, end, format_):
            offset = qt_position(text, start)
            self.setFormat(offset, qt_position(text, end)-offset, format_)

        def code(start, end):
            for match in re.finditer(r"\b\d+(?:\.\d+)?\b|[+\-*/^=<>|]+|\$?(?:[^\W\d]|[∞∂])(?:\w|[\u0300-\u036f])*", text[start:end]):
                word = match.group()
                format_ = (self.keyword_format if word in self.KEYWORDS else
                           self.builtin_format if word in self.BUILTINS else
                           self.number_format if word[0].isdigit() else
                           self.operator_format if word[0] in '+-*/^=<>|' else
                           self.type_format if word[0].isupper() else None)
                if format_ is not None:
                    paint(start+match.start(), start+match.end(), format_)

        offset = 0
        in_comment = self.previousBlockState() == 1
        while offset < len(text):
            if in_comment:
                end = text.find('*/', offset)
                if end < 0:
                    paint(offset, len(text), self.comment_format)
                    break
                paint(offset, end+2, self.comment_format)
                offset, in_comment = end+2, False
            else:
                comment = re.search(r'//|/\*', text[offset:])
                if comment is None:
                    code(offset, len(text))
                    break
                start = offset+comment.start()
                code(offset, start)
                if comment.group() == '//':
                    paint(start, len(text), self.comment_format)
                    break
                paint(start, start+2, self.comment_format)
                offset, in_comment = start+2, True
        self.setCurrentBlockState(1 if in_comment else 0)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.line_numbers = LineNumberArea(self)
        self.highlighter = MathlangHighlighter(self.document())
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width()
        self.highlight_current_line()
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.completion_provider = None
        self.completion_model = QStringListModel(self)
        self.completer = QCompleter(self.completion_model, self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.activated[str].connect(self.insert_completion)

    @staticmethod
    def _name_char(char: str) -> bool:
        return ('a'+char).isidentifier() or char in '$.∞∂'

    def completion_range(self) -> tuple[str, int, int]:
        source = self.toPlainText()
        end = source_position(source, self.textCursor().position())
        start = end
        while start > 0 and self._name_char(source[start-1]):
            start -= 1
        return source, start, end

    def insert_completion(self, name: str) -> None:
        source, start, end = self.completion_range()
        while end < len(source) and self._name_char(source[end]):
            end += 1
        cursor = self.textCursor()
        cursor.setPosition(qt_position(source, start))
        cursor.setPosition(qt_position(source, end), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(name)
        self.setTextCursor(cursor)
        self.completer.popup().hide()

    def show_completions(self, *, explicit: bool = False) -> None:
        if self.completion_provider is None:
            return
        source, start, end = self.completion_range()
        prefix = source[start:end]
        if not explicit and len(prefix) < 2:
            self.completer.popup().hide()
            return
        choices = self.completion_provider(prefix, source[:start])
        self.completion_model.setStringList(list(choices))
        self.completer.setCompletionPrefix(prefix)
        if not choices:
            self.completer.popup().hide()
            return
        self.completer.popup().setCurrentIndex(self.completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(max(240, self.completer.popup().sizeHintForColumn(0)+24))
        self.completer.complete(rect)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if (event.key() == Qt.Key.Key_Space
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self.show_completions(explicit=True)
            return
        if self.completer.popup().isVisible() and event.key() in (
                Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape,
                Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            event.ignore()
            return
        super().keyPressEvent(event)
        if event.text() or event.key() == Qt.Key.Key_Backspace:
            self.show_completions()
        else:
            self.completer.popup().hide()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, *_args) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_numbers.scroll(0, dy)
        else:
            self.line_numbers.update(0, rect.y(), self.line_numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_numbers.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self.line_numbers)
        painter.fillRect(event.rect(), QColor("#111418"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                current = number == self.textCursor().blockNumber()
                painter.setPen(QColor("#a9c7ee" if current else "#5f6978"))
                font = painter.font()
                font.setBold(current)
                painter.setFont(font)
                painter.drawText(0, top, self.line_numbers.width() - 7,
                                 self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight,
                                 str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#121a24"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self._line_selection = selection
        self.set_diagnostics(getattr(self, "_diagnostics", []))

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoomIn(1)
            else:
                self.zoomOut(1)
            event.accept()
            return
        super().wheelEvent(event)

    def set_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        self._diagnostics = diagnostics
        selections = [self._line_selection] if hasattr(self, "_line_selection") else []
        source = self.toPlainText()
        document_len = len(source)
        for diagnostic in diagnostics:
            selection = QTextEdit.ExtraSelection()
            cursor = self.textCursor()
            start = min(max(diagnostic.start, 0), document_len)
            end = min(max(diagnostic.end, start + 1), document_len)
            cursor.setPosition(qt_position(source, start))
            cursor.setPosition(qt_position(source, end), QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            selection.format.setUnderlineColor(QColor("#ff5370"))
            selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            selection.format.setToolTip(diagnostic.message)
            selections.append(selection)
        self.setExtraSelections(selections)
