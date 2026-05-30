from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QFormLayout,
    QSpinBox, QDoubleSpinBox, QLabel,
)

from app.model.gcode_object import GcodeObject


class ArrayDialog(QDialog):
    """Create an N×M grid of copies of an object."""

    def __init__(self, obj: GcodeObject, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Array / Grid…")
        self._obj = obj
        self._setup_ui()
        self._update_info()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._spin_cols = QSpinBox()
        self._spin_cols.setRange(1, 50)
        self._spin_cols.setValue(3)
        self._spin_cols.setSuffix("  columns")
        form.addRow("Columns:", self._spin_cols)

        self._spin_rows = QSpinBox()
        self._spin_rows.setRange(1, 50)
        self._spin_rows.setValue(2)
        self._spin_rows.setSuffix("  rows")
        form.addRow("Rows:", self._spin_rows)

        self._spin_gap_x = QDoubleSpinBox()
        self._spin_gap_x.setRange(0, 500)
        self._spin_gap_x.setDecimals(1)
        self._spin_gap_x.setSuffix(" mm")
        self._spin_gap_x.setValue(5.0)
        form.addRow("Gap X (edge–edge):", self._spin_gap_x)

        self._spin_gap_y = QDoubleSpinBox()
        self._spin_gap_y.setRange(0, 500)
        self._spin_gap_y.setDecimals(1)
        self._spin_gap_y.setSuffix(" mm")
        self._spin_gap_y.setValue(5.0)
        form.addRow("Gap Y (edge–edge):", self._spin_gap_y)

        layout.addLayout(form)

        self._lbl_info = QLabel()
        layout.addWidget(self._lbl_info)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for w in (self._spin_cols, self._spin_rows, self._spin_gap_x, self._spin_gap_y):
            w.valueChanged.connect(self._update_info)

    def _update_info(self):
        cols = self._spin_cols.value()
        rows = self._spin_rows.value()
        total = cols * rows
        bb = self._obj.bounding_box
        total_w = cols * bb.width + (cols - 1) * self._spin_gap_x.value()
        total_h = rows * bb.height + (rows - 1) * self._spin_gap_y.value()
        self._lbl_info.setText(
            f"{cols} × {rows} = {total} objects total  |  "
            f"Grid size: {total_w:.1f} × {total_h:.1f} mm"
        )

    def get_params(self) -> tuple[int, int, float, float]:
        """Returns (rows, cols, gap_x, gap_y)."""
        return (
            self._spin_rows.value(),
            self._spin_cols.value(),
            self._spin_gap_x.value(),
            self._spin_gap_y.value(),
        )
