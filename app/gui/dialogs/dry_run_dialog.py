from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QProgressBar,
)
from PyQt6.QtCore import Qt

from app.model.types import Move


_SPEEDS = [
    ("1× (real time estimate)", 1),
    ("5×  fast", 5),
    ("20×  faster", 20),
    ("100×  very fast", 100),
    ("500×  max", 500),
]


class DryRunDialog(QDialog):
    """Non-modal dialog controlling the dry-run animation on the canvas."""

    def __init__(self, canvas, moves: list[Move], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dry-run Animation")
        self.setModal(False)
        self._canvas = canvas
        self._moves = moves
        self._setup_ui()
        canvas.animation_finished.connect(self._on_finished)
        self._start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self._lbl_info = QLabel(f"Total moves: {len(self._moves)}")
        layout.addWidget(self._lbl_info)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        self._cmb_speed = QComboBox()
        for label, val in _SPEEDS:
            self._cmb_speed.addItem(label, val)
        self._cmb_speed.setCurrentIndex(2)
        self._cmb_speed.currentIndexChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self._cmb_speed)
        layout.addLayout(speed_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, max(1, len(self._moves)))
        layout.addWidget(self._progress)

        self._lbl_z = QLabel("Z:  0.000 mm")
        self._lbl_z.setStyleSheet("font-family: monospace; font-size: 13px;")
        layout.addWidget(self._lbl_z)

        self._lbl_status = QLabel("Running…")
        layout.addWidget(self._lbl_status)

        btn_row = QHBoxLayout()
        self._btn_restart = QPushButton("Restart")
        self._btn_restart.clicked.connect(self._start)
        btn_row.addWidget(self._btn_restart)
        btn_close = QPushButton("Stop && Close")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._canvas.animation_finished.connect(self._update_progress)
        self._canvas._anim_timer.timeout.connect(self._update_progress)

    def _start(self):
        speed = self._cmb_speed.currentData()
        self._canvas.start_animation(self._moves, speed)
        self._lbl_status.setText("Running…")

    def _on_speed_changed(self):
        if self._canvas.is_animating():
            self._canvas._anim_speed = self._cmb_speed.currentData()

    def _update_progress(self):
        idx = self._canvas._anim_index
        self._progress.setValue(idx + 1)
        if self._moves and idx < len(self._moves):
            z = self._moves[idx].to_pos.z
            cutting = self._moves[idx].pen_down
            color = "#CC0000" if cutting else "#333333"
            label = f"Z:  {z:+.3f} mm"
            if cutting:
                label += "  (cutting)"
            self._lbl_z.setText(label)
            self._lbl_z.setStyleSheet(
                f"font-family: monospace; font-size: 13px; color: {color};"
            )

    def _on_finished(self):
        self._lbl_status.setText("Finished.")

    def closeEvent(self, event):
        self._canvas.stop_animation()
        super().closeEvent(event)
