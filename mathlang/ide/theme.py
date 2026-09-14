"""Centralized Qt stylesheet for the bundled IDE."""

DARK_STYLESHEET = r"""
QMainWindow, QWidget {
    background: #0d1117;
    color: #dce3ec;
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMenuBar {
    background: #0d1117;
    color: #cbd3df;
    border-bottom: 1px solid #202833;
    padding: 2px 4px;
}
QMenuBar::item { padding: 5px 8px; border-radius: 4px; }
QMenuBar::item:selected { background: #1b2430; color: #ffffff; }
QMenu {
    background: #151b23;
    color: #dce3ec;
    border: 1px solid #2a3442;
    padding: 5px;
}
QMenu::item { padding: 6px 28px 6px 10px; border-radius: 4px; }
QMenu::item:selected { background: #223044; color: #ffffff; }
QToolBar {
    background: #10151c;
    border: 0;
    border-bottom: 1px solid #202833;
    spacing: 6px;
    padding: 6px 8px;
}
QToolButton, QPushButton {
    background: #18212c;
    color: #dce3ec;
    border: 1px solid #2a3544;
    border-radius: 6px;
    padding: 5px 10px;
}
QToolButton:hover, QPushButton:hover { background: #223044; border-color: #3b4b60; }
QToolButton:pressed, QPushButton:pressed { background: #2b3b50; }
QPlainTextEdit, QTextEdit, QLineEdit, QListWidget, QTreeView {
    background: #0b0f14;
    color: #dce3ec;
    border: 0;
    selection-background-color: #264f78;
    selection-color: #ffffff;
}
QPlainTextEdit, QTextEdit {
    font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
    font-size: 13px;
}
QLineEdit {
    background: #111821;
    border: 1px solid #293443;
    border-radius: 6px;
    padding: 7px 9px;
}
QLineEdit:focus { border-color: #4d8dd8; }
QTreeView#ProjectTree {
    background: #0f141b;
    border-right: 1px solid #202833;
    padding: 7px 3px;
    outline: 0;
}
QTreeView#ProjectTree::item { padding: 4px 5px; border-radius: 4px; }
QTreeView#ProjectTree::item:hover { background: #171f29; }
QTreeView#ProjectTree::item:selected { background: #203147; color: #ffffff; }
QTabWidget::pane { border: 0; background: #0b0f14; }
QTabBar { background: #10151c; }
QTabBar::tab {
    background: #11171f;
    color: #8f9baa;
    padding: 8px 14px;
    border: 0;
    border-right: 1px solid #202833;
    border-bottom: 1px solid #202833;
}
QTabBar::tab:hover { background: #171f29; color: #cbd3df; }
QTabBar::tab:selected {
    background: #0b0f14;
    color: #ffffff;
    border-bottom: 2px solid #5a9be7;
}
QTabBar::close-button { margin-left: 5px; }
QSplitter::handle { background: #202833; }
QListWidget { padding: 4px; }
QListWidget::item { padding: 5px 7px; border-radius: 4px; }
QListWidget::item:selected { background: #203147; }
QHeaderView::section { background: #121820; color: #aab4c2; border: 0; padding: 5px; }
QStatusBar {
    background: #10151c;
    color: #8995a5;
    border-top: 1px solid #202833;
}
QStatusBar::item { border: 0; }
QWidget#MathPreviewPane {
    background: #10151c;
    border-left: 1px solid #202833;
}
QWidget#PreviewHeader { background: transparent; }
QLabel#PaneTitle {
    color: #f1f5f9;
    font-size: 14px;
    font-weight: 600;
}
QLabel#PaneHint { color: #748093; font-size: 11px; }
QGraphicsView#PreviewCanvas {
    background: #0b0f14;
    border: 1px solid #202833;
    border-radius: 8px;
}
QPushButton#PreviewControl {
    min-width: 28px;
    max-width: 28px;
    min-height: 26px;
    padding: 0;
    font-size: 16px;
}
QPushButton#PreviewZoom {
    min-width: 52px;
    max-width: 58px;
    min-height: 26px;
    padding: 0 5px;
    color: #aeb9c7;
}
QPushButton#PreviewFit {
    min-height: 26px;
    padding: 0 8px;
    color: #aeb9c7;
}
QScrollBar:vertical {
    background: #0d1218;
    width: 11px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #303b49;
    min-height: 28px;
    border-radius: 5px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { background: #425064; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #0d1218;
    height: 11px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #303b49;
    min-width: 28px;
    border-radius: 5px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: #425064; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QToolTip {
    background: #1b2430;
    color: #e8edf4;
    border: 1px solid #334155;
    padding: 4px;
}
"""
