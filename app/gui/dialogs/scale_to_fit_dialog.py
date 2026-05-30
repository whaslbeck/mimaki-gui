from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QFormLayout,
    QDoubleSpinBox, QCheckBox, QPushButton, QLabel, QHBoxLayout,
)
from PyQt6.QtCore import Qt

from app.model.gcode_object import GcodeObject
from app.model.project import MACHINE_W, MACHINE_H


class ScaleToFitDialog(QDialog):
    """Scale the selected object to exact target dimensions."""

    def __init__(self, obj: GcodeObject, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scale to Fit…")
        self._obj = obj
        self._bb = obj.bounding_box
        self._orig_w = self._bb.width
        self._orig_h = self._bb.height
        self._aspect = self._orig_w / self._orig_h if self._orig_h > 0 else 1.0
        self._updating = False
        self._result_scale: float = obj.transform.scale
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self._lbl_current = QLabel(
            f"Current size: {self._orig_w:.2f} × {self._orig_h:.2f} mm"
            f"  (scale {self._obj.transform.scale:.4f}×)"
        )
        layout.addWidget(self._lbl_current)

        form = QFormLayout()

        self._spin_w = QDoubleSpinBox()
        self._spin_w.setRange(0.01, 5000)
        self._spin_w.setDecimals(2)
        self._spin_w.setSuffix(" mm")
        self._spin_w.setKeyboardTracking(False)
        self._spin_w.setValue(self._orig_w)
        form.addRow("Target width:", self._spin_w)

        self._spin_h = QDoubleSpinBox()
        self._spin_h.setRange(0.01, 5000)
        self._spin_h.setDecimals(2)
        self._spin_h.setSuffix(" mm")
        self._spin_h.setKeyboardTracking(False)
        self._spin_h.setValue(self._orig_h)
        form.addRow("Target height:", self._spin_h)

        self._chk_lock = QCheckBox("Lock aspect ratio")
        self._chk_lock.setChecked(True)
        form.addRow("", self._chk_lock)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_work = QPushButton("Fit to work area")
        btn_work.setToolTip(f"Scale to fill {MACHINE_W} × {MACHINE_H} mm (unlocks aspect)")
        btn_work.clicked.connect(self._fit_to_work_area)
        btn_row.addWidget(btn_work)
        btn_orig = QPushButton("Reset to original")
        btn_orig.clicked.connect(self._reset)
        btn_row.addWidget(btn_orig)
        layout.addLayout(btn_row)

        self._lbl_scale = QLabel()
        layout.addWidget(self._lbl_scale)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._spin_w.valueChanged.connect(self._on_w_changed)
        self._spin_h.valueChanged.connect(self._on_h_changed)
        self._update_label()

    def _raw_w(self) -> float:
        raw = self._obj._raw_bbox()
        return raw.width if raw.width > 0 else 1.0

    def _raw_h(self) -> float:
        raw = self._obj._raw_bbox()
        return raw.height if raw.height > 0 else 1.0

    def _on_w_changed(self, val: float):
        if self._updating:
            return
        self._updating = True
        if self._chk_lock.isChecked() and self._aspect > 0:
            self._spin_h.setValue(val / self._aspect)
        self._updating = False
        self._update_label()

    def _on_h_changed(self, val: float):
        if self._updating:
            return
        self._updating = True
        if self._chk_lock.isChecked() and self._aspect > 0:
            self._spin_w.setValue(val * self._aspect)
        self._updating = False
        self._update_label()

    def _fit_to_work_area(self):
        self._chk_lock.setChecked(False)
        self._updating = True
        self._spin_w.setValue(MACHINE_W)
        self._spin_h.setValue(MACHINE_H)
        self._updating = False
        self._update_label()

    def _reset(self):
        self._updating = True
        self._spin_w.setValue(self._orig_w)
        self._spin_h.setValue(self._orig_h)
        self._updating = False
        self._update_label()

    def _update_label(self):
        scale_w = self._spin_w.value() / self._raw_w() if self._raw_w() > 0 else 1.0
        scale_h = self._spin_h.value() / self._raw_h() if self._raw_h() > 0 else 1.0
        if self._chk_lock.isChecked():
            s = scale_w
            self._lbl_scale.setText(f"Scale: {s:.4f}×  ({s*100:.1f} %)")
        else:
            self._lbl_scale.setText(
                f"Scale X: {scale_w:.4f}×  Y: {scale_h:.4f}×  (non-uniform — only W applied)"
            )

    def _on_accept(self):
        raw_w = self._raw_w()
        target_w = self._spin_w.value()
        self._result_scale = target_w / raw_w if raw_w > 0 else self._obj.transform.scale
        self.accept()

    def get_scale(self) -> float:
        return self._result_scale
