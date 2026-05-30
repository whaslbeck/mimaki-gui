from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton,
)
from PyQt6.QtCore import Qt

from app.model.gcode_object import GcodeObject


class CommentsDialog(QDialog):
    """Read-only list of all G-code comments embedded in the object's moves."""

    def __init__(self, obj: GcodeObject, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Kommentare — {obj.label}")
        self.resize(540, 380)
        self._setup_ui(obj)

    def _setup_ui(self, obj: GcodeObject):
        layout = QVBoxLayout(self)

        comments = [
            (m.line_nr, m.comment)
            for m in obj.original_moves
            if m.comment
        ]

        layout.addWidget(QLabel(f"{len(comments)} Kommentare in {obj.label}:"))

        lst = QListWidget()
        lst.setFont(__import__("PyQt6.QtGui", fromlist=["QFont"]).QFont("Monospace", 9))
        for line_nr, text in comments:
            item = QListWidgetItem(f"Z.{line_nr:>6}  {text}")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            lst.addItem(item)
        layout.addWidget(lst, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
