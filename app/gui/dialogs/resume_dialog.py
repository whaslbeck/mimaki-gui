from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGroupBox, QRadioButton, QSpinBox, QLabel,
)

from app.model.types import Move


def _find_z_layer_start(moves: list[Move], confirmed_idx: int) -> int:
    """Return the index of the first move of the current Z-depth pass.

    Scans backwards from *confirmed_idx* to find the !PZ plunge that
    initiated the current cutting depth.  Returns 0 if none is found.
    """
    if confirmed_idx < 0 or confirmed_idx >= len(moves):
        return 0

    # Find the active cutting depth at confirmed_idx
    current_z: float | None = None
    for i in range(confirmed_idx, -1, -1):
        m = moves[i]
        if m.pen_down and m.to_pos.z < 0:
            current_z = m.to_pos.z
            break
    if current_z is None:
        return 0

    # Find the plunge move (!PZ) that set this depth
    for i in range(confirmed_idx, -1, -1):
        m = moves[i]
        if m.z_move and m.pen_down and abs(m.to_pos.z - current_z) < 0.01:
            return i   # start of layer = the plunge move itself
    return 0


class ResumeDialog(QDialog):
    """Ask the user where to resume after a pause-with-retract.

    Three options:
      1. Continue from the current confirmed position (default)
      2. Go back N moves (1–20, configurable)
      3. Restart from the beginning of the current Z-depth pass
    """

    def __init__(
        self,
        moves: list[Move],
        confirmed_index: int,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Resume — choose start position")
        self._moves = moves
        self._confirmed = confirmed_index           # last fully executed move
        self._next = min(confirmed_index + 1, len(moves) - 1)
        self._z_start = _find_z_layer_start(moves, confirmed_index)
        self._total = len(moves)
        self._setup_ui()

    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            f"Cutter was retracted. Choose where to resume "
            f"(last confirmed move: {self._confirmed + 1} / {self._total}):"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        grp = QGroupBox("Resume position")
        vl = QVBoxLayout(grp)

        # Option 1 — current position
        self._rb_current = QRadioButton(
            f"Continue from current position  (move {self._next + 1})"
        )
        self._rb_current.setChecked(True)
        vl.addWidget(self._rb_current)

        # Option 2 — N moves back
        back_row = QHBoxLayout()
        self._rb_back = QRadioButton("Go back")
        self._spin_n = QSpinBox()
        self._spin_n.setRange(1, min(20, self._confirmed + 1))
        self._spin_n.setValue(min(5, self._confirmed + 1))
        self._spin_n.setSuffix(" moves")
        self._lbl_back = QLabel()
        self._spin_n.valueChanged.connect(self._update_back_label)
        self._rb_back.toggled.connect(lambda _: self._update_back_label())
        back_row.addWidget(self._rb_back)
        back_row.addWidget(self._spin_n)
        back_row.addWidget(self._lbl_back)
        back_row.addStretch()
        vl.addLayout(back_row)

        # Option 3 — Z-layer start
        self._rb_zlayer = QRadioButton(
            f"Restart current Z-layer  (from move {self._z_start + 1})"
        )
        if self._z_start == 0 and self._confirmed == 0:
            self._rb_zlayer.setEnabled(False)
        vl.addWidget(self._rb_zlayer)

        layout.addWidget(grp)

        self._update_back_label()

        # Disable spinbox when other options are selected
        self._rb_current.toggled.connect(
            lambda c: self._spin_n.setEnabled(not c and self._rb_back.isChecked())
        )
        self._rb_zlayer.toggled.connect(
            lambda c: self._spin_n.setEnabled(not c and self._rb_back.isChecked())
        )
        self._rb_back.toggled.connect(self._spin_n.setEnabled)
        self._spin_n.setEnabled(False)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _update_back_label(self):
        n = self._spin_n.value()
        idx = max(0, self._next - n)
        self._lbl_back.setText(f"→ from move {idx + 1}")

    # ------------------------------------------------------------------

    def get_resume_index(self) -> int:
        """Return the 0-based move index to resume from."""
        if self._rb_back.isChecked():
            n = self._spin_n.value()
            return max(0, self._next - n)
        if self._rb_zlayer.isChecked():
            return self._z_start
        return self._next   # default: current position
