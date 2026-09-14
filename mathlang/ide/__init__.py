"""Desktop IDE support for mathlang.

The language-service modules intentionally do not depend on Qt, so they can be
reused by a future Tauri/LSP frontend as well as the bundled PySide6 desktop UI.
"""

from .language_service import Diagnostic, LanguageService, OutputItem

__all__ = ["Diagnostic", "LanguageService", "OutputItem"]
