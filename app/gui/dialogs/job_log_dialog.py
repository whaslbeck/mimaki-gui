from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialogButtonBox, QLabel,
)

from app.io.job_log import load_log, clear_log


class JobLogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Job Log")
        self.resize(760, 420)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Timestamp", "Project file", "Moves", "Duration", "Status", "Error",
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        self._lbl_count = QLabel()
        layout.addWidget(self._lbl_count)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("Clear Log")
        btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

    def _load(self):
        entries = load_log()
        self._table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            dur = f"{e.duration_seconds:.1f} s"
            self._table.setItem(row, 0, QTableWidgetItem(e.timestamp))
            self._table.setItem(row, 1, QTableWidgetItem(e.project_file or "(unsaved)"))
            self._table.setItem(row, 2, QTableWidgetItem(str(e.move_count)))
            self._table.setItem(row, 3, QTableWidgetItem(dur))
            status_item = QTableWidgetItem(e.status)
            if e.status == "finished":
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            elif e.status == "error":
                status_item.setForeground(Qt.GlobalColor.red)
            else:
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            self._table.setItem(row, 4, status_item)
            self._table.setItem(row, 5, QTableWidgetItem(e.error_message))
        self._table.resizeColumnsToContents()
        self._lbl_count.setText(f"{len(entries)} entries")

    def _on_clear(self):
        reply = QMessageBox.question(
            self, "Clear Log",
            "Delete all job log entries?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            clear_log()
            self._load()
