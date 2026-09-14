"""Optional headless Qt regressions; the core package has no GUI dependency."""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from mathlang.ide.editor import CodeEditor
except ImportError:
    QApplication = None

from mathlang.ide.language_service import LanguageService
from mathlang.ide.text_positions import qt_position, source_position


class TextPositionTests(unittest.TestCase):
    def test_unicode_offsets_round_trip(self):
        source = '𝑥 + α\n😀 undefined'
        for offset in range(len(source)+1):
            self.assertEqual(source_position(source, qt_position(source, offset)), offset)
        self.assertEqual(qt_position(source, -1), 0)
        self.assertEqual(source_position(source, -1), 0)


@unittest.skipIf(QApplication is None, 'PySide6 is not installed')
class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = CodeEditor()
        service = LanguageService()
        self.editor.completion_provider = lambda prefix, source: service.completions(prefix, source=source)

    def tearDown(self):
        self.editor.close()
        self.editor.deleteLater()
        self.app.processEvents()

    def test_diagnostic_selection_after_astral_symbol(self):
        source = 'variable 𝑥:Real\n𝑥 + missing'
        self.editor.setPlainText(source)
        self.editor.set_diagnostics(LanguageService().semantic_diagnostics(source))
        selections = self.editor.extraSelections()
        self.assertEqual(selections[-1].cursor.selectedText(), 'missing')

    def test_multiline_comments_and_utf16_highlight_offsets(self):
        self.editor.setPlainText('/* comment\nfunction sin 42\n*/ 𝑥 + sin(0) // const\nconst y=1')
        self.editor.highlighter.rehighlight()
        block = self.editor.document().firstBlock()
        self.assertEqual(block.userState(), 1)
        block = block.next()
        self.assertEqual(block.userState(), 1)
        formats = block.layout().formats()
        self.assertEqual(formats[0].format.foreground().color().name(), '#637777')
        block = block.next()
        self.assertEqual(block.userState(), 0)
        start = qt_position(block.text(), block.text().index('sin'))
        self.assertTrue(any(f.start == start and f.format.foreground().color().name() == '#82aaff'
                            for f in block.layout().formats()))

    def test_completion_replaces_whole_unicode_token_and_keeps_following_text(self):
        source = '𝑥 + normXYZ + 1'
        self.editor.setPlainText(source)
        cursor = self.editor.textCursor()
        cursor.setPosition(qt_position(source, source.index('XYZ')))
        self.editor.setTextCursor(cursor)
        self.editor.insert_completion('normalize')
        self.assertEqual(self.editor.toPlainText(), '𝑥 + normalize + 1')

    def test_control_space_and_enter_complete_without_inserting_newline(self):
        self.editor.setPlainText('norm')
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self.editor.show()
        QTest.keyClick(self.editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertIn('normalize', self.editor.completion_model.stringList())
        QTest.keyClick(self.editor.completer.popup(), Qt.Key.Key_Return)
        self.assertEqual(self.editor.toPlainText(), 'normalize')

    def test_main_window_type_inspection_uses_unsaved_buffer(self):
        from mathlang.ide.app import MainWindow
        window = MainWindow()
        try:
            editor = window.current_tab().editor
            editor.setPlainText('x:Real\n1+x')
            editor.moveCursor(QTextCursor.MoveOperation.End)
            window.inspect_types()
            self.assertIn('Embed<Nat, Real>', window.type_inspector.toPlainText())
            self.assertIsNone(window.service.runtime.environment.get('x'))
        finally:
            window.analysis_timer.stop()
            window.close()
            window.deleteLater()

    def test_assumption_panel_tracks_runtime_rollback_and_reset(self):
        from pathlib import Path
        from mathlang.ide.app import MainWindow
        window = MainWindow()
        try:
            window.repl_input.setText('x:Real; assume x>0')
            window.run_repl()
            self.assertEqual(window.assumption_inspector.toPlainText(), 'x > 0')
            window.repl_input.setText('assume x<0')
            window.run_repl()
            self.assertEqual(window.assumption_inspector.toPlainText(), 'x > 0')
            window.current_tab().editor.setPlainText('y:Real; assuming {y>0} {y>0}; y>0')
            window._run_semantic_analysis()
            self.assertEqual(window.assumption_inspector.toPlainText(), 'x > 0')
            window.run_file()
            self.assertEqual(window.service.assumptions(), ())
            self.assertEqual(window.output.toPlainText(), 'True\nUnknown')
            self.assertEqual(window.assumption_inspector.toPlainText(), 'No active assumptions.')
            window.repl_input.setText('assume y>0')
            window.run_repl()
            self.assertEqual(window.assumption_inspector.toPlainText(), 'y > 0')
            window._set_project(Path(__file__).resolve().parents[1])
            self.assertEqual(window.assumption_inspector.toPlainText(), 'No active assumptions.')
        finally:
            window.analysis_timer.stop()
            window.close()
            window.deleteLater()

    def test_property_panel_tracks_proofs_failures_and_project_reset(self):
        from pathlib import Path
        from mathlang.ide.app import MainWindow
        window = MainWindow()
        try:
            source = '''import std.theories {Semigroup}
                implementation Add implements Semigroup<Real> {operation (*)=(a:Real,b:Real)=>a+b}
                implementation Sub implements Semigroup<Real> {operation (*)=(a:Real,b:Real)=>a-b}
            '''
            window.current_tab().editor.setPlainText(source)
            window.run_file()
            inspector = window.property_inspector
            self.assertEqual(inspector.topLevelItemCount(), 2)
            add, sub = inspector.topLevelItem(0), inspector.topLevelItem(1)
            self.assertEqual((add.text(0),add.text(1)),('Add','True'))
            self.assertEqual((sub.text(0),sub.text(1)),('Sub','False'))
            self.assertEqual(sub.child(1).text(1),'disproved')
            self.assertIn('Counterexample',sub.child(1).toolTip(0))
            window.repl_input.setText('temporary=1; missing_name')
            window.run_repl()
            self.assertEqual(inspector.topLevelItemCount(),2)
            window.current_tab().editor.setPlainText('1')
            window._run_semantic_analysis()
            self.assertEqual(inspector.topLevelItemCount(),2)
            window._set_project(Path(__file__).resolve().parents[1])
            self.assertEqual(inspector.topLevelItemCount(),0)
        finally:
            window.analysis_timer.stop()
            window.close()
            window.deleteLater()

    def test_property_panel_shows_inherited_origins_and_parent_contract(self):
        from pathlib import Path
        from mathlang.ide.app import MainWindow
        path = Path(__file__).resolve().parents[1]/'examples'/'theory_inheritance.math'
        window = MainWindow()
        try:
            window.open_file(path)
            window.run_file()
            inspector = window.property_inspector
            self.assertEqual(inspector.columnCount(), 4)
            self.assertEqual(inspector.headerItem().text(3), 'Declared in')
            roots = {inspector.topLevelItem(i).text(0): inspector.topLevelItem(i)
                     for i in range(inspector.topLevelItemCount())}
            addition = roots['Addition']
            self.assertIn('extends Monoid<T>, Commutative<T>', addition.toolTip(0))
            properties = {addition.child(i).text(0): addition.child(i)
                          for i in range(addition.childCount())}
            self.assertEqual(properties['associative'].text(3), 'Semigroup')
            self.assertEqual(properties['identity_rule'].text(3), 'Monoid')
            self.assertEqual(properties['commutative'].text(3), 'Commutative')
            self.assertIn('Declared in: Semigroup', properties['associative'].toolTip(0))
            window.repl_input.setText('theory Bad<T> extends Missing<T> {}')
            window.run_repl()
            self.assertEqual(inspector.topLevelItemCount(), 4)
            window._set_project(path.parent)
            self.assertEqual(inspector.topLevelItemCount(), 0)
        finally:
            window.analysis_timer.stop()
            window.close()
            window.deleteLater()
