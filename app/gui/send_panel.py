from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QProgressBar,
    QLabel, QPlainTextEdit, QGroupBox, QFormLayout, QLineEdit,
)

from app.config import AppConfig


class SendPanel(QWidget):
    connect_requested = pyqtSignal()
    disconnect_requested = pyqtSignal()
    send_requested = pyqtSignal()
    send_from_requested = pyqtSignal()
    send_selected_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # --- Left: controls ---
        ctrl = QVBoxLayout()

        conn_row = QHBoxLayout()
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setCheckable(True)
        self._btn_connect.clicked.connect(self._on_connect_toggle)
        conn_row.addWidget(self._btn_connect)
        self._lbl_status = QLabel("Disconnected")
        self._lbl_status.setStyleSheet("color: #CC0000;")
        conn_row.addWidget(self._lbl_status)
        conn_row.addStretch()
        ctrl.addLayout(conn_row)

        send_row = QHBoxLayout()
        self._btn_send = QPushButton("Send (F5)")
        self._btn_send.clicked.connect(self.send_requested)
        send_row.addWidget(self._btn_send)
        self._btn_send_from = QPushButton("From… (⇧F5)")
        self._btn_send_from.clicked.connect(self.send_from_requested)
        send_row.addWidget(self._btn_send_from)
        self._btn_send_sel = QPushButton("Send Selected (^F5)")
        self._btn_send_sel.clicked.connect(self.send_selected_requested)
        send_row.addWidget(self._btn_send_sel)
        ctrl.addLayout(send_row)

        ps_row = QHBoxLayout()
        self._btn_pause = QPushButton("Pause (F6)")
        self._btn_pause.setEnabled(False)
        self._btn_pause.setCheckable(True)
        self._btn_pause.clicked.connect(self._on_pause_toggle)
        ps_row.addWidget(self._btn_pause)
        self._btn_stop = QPushButton("Stop (F7)")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self.stop_requested)
        ps_row.addWidget(self._btn_stop)
        ctrl.addLayout(ps_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%v / %m moves")
        ctrl.addWidget(self._progress)

        self._lbl_remaining = QLabel("Remaining: --:--:--")
        ctrl.addWidget(self._lbl_remaining)

        self._lbl_confirmed = QLabel()
        self._lbl_confirmed.setStyleSheet("color:#555; font-size:10px;")
        ctrl.addWidget(self._lbl_confirmed)

        ctrl.addStretch()
        layout.addLayout(ctrl, 1)

        # --- Right: log ---
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setFixedHeight(120)
        layout.addWidget(self._log, 2)

    # ------------------------------------------------------------------
    # Public API

    def set_connected(self, connected: bool):
        if connected:
            self._btn_connect.setText("Disconnect")
            self._btn_connect.setChecked(True)
            self._lbl_status.setText("Connected")
            self._lbl_status.setStyleSheet("color: #008800;")
        else:
            self._btn_connect.setText("Connect")
            self._btn_connect.setChecked(False)
            self._lbl_status.setText("Disconnected")
            self._lbl_status.setStyleSheet("color: #CC0000;")

    def set_sending(self, active: bool):
        self._btn_send.setEnabled(not active)
        self._btn_send_from.setEnabled(not active)
        self._btn_send_sel.setEnabled(not active)
        self._btn_pause.setEnabled(active)
        self._btn_stop.setEnabled(active)
        if not active:
            self._btn_pause.setChecked(False)
            self._lbl_confirmed.clear()

    def set_confirmed(self, index: int):
        """Show the last OS;-confirmed move index (0-based)."""
        self._lbl_confirmed.setText(f"Confirmed executed: move {index + 1}")

    def set_progress(self, sent: int, total: int):
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(sent)
        self._progress.setFormat(f"{sent} / {total} moves")

    def set_remaining(self, seconds: float):
        if seconds < 0:
            self._lbl_remaining.setText("Remaining: --:--:--")
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            self._lbl_remaining.setText(f"Remaining: {h:02d}:{m:02d}:{s:02d}")

    def append_log(self, text: str):
        self._log.appendPlainText(text)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def clear_log(self):
        self._log.clear()

    def set_log_max_lines(self, n: int):
        self._log.setMaximumBlockCount(max(10, n))

    # ------------------------------------------------------------------

    def _on_connect_toggle(self, checked: bool):
        if checked:
            self.connect_requested.emit()
        else:
            self.disconnect_requested.emit()

    def _on_pause_toggle(self, checked: bool):
        if checked:
            self.pause_requested.emit()
        else:
            self.resume_requested.emit()
