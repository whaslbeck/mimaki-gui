from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QLineEdit, QMessageBox,
)
from PyQt6.QtGui import QFont, QTextCursor, QTextDocument
from PyQt6.QtCore import Qt

from app.model.gcode_object import GcodeObject

_MAX_LINES = 200_000


class SourcePreviewDialog(QDialog):
    """Read-only viewer for the G-code source file of an object."""

    def __init__(self, obj: GcodeObject, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Quellcode — {obj.label}")
        self.resize(760, 560)
        self._setup_ui(obj)

    def _setup_ui(self, obj: GcodeObject):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Header
        layout.addWidget(QLabel(f"Datei: {obj.source_file}"))

        # Search bar
        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Suchen…")
        self._search.returnPressed.connect(self._find_next)
        search_row.addWidget(self._search, 1)
        btn_find = QPushButton("Weiter")
        btn_find.clicked.connect(self._find_next)
        search_row.addWidget(btn_find)
        layout.addLayout(search_row)

        # Text view
        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setFont(QFont("Monospace", 9))
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._editor, 1)

        # Load content
        try:
            with open(obj.source_file, errors="replace") as f:
                lines = f.readlines()
            truncated = len(lines) > _MAX_LINES
            text = "".join(lines[:_MAX_LINES])
            self._editor.setPlainText(text)
            if truncated:
                self._editor.appendPlainText(
                    f"\n… (Datei gekürzt — nur erste {_MAX_LINES:,} Zeilen angezeigt)"
                )
        except OSError as e:
            self._editor.setPlainText(f"Fehler beim Öffnen:\n{e}")

        # Buttons
        btn_row = QHBoxLayout()
        self._lbl_info = QLabel(f"{len(lines):,} Zeilen")
        btn_row.addWidget(self._lbl_info)
        btn_row.addStretch()
        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _find_next(self):
        term = self._search.text()
        if not term:
            return
        found = self._editor.find(term)
        if not found:
            # Wrap around
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)
            self._editor.find(term)
