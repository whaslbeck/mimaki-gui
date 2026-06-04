from __future__ import annotations
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QRadioButton, QDoubleSpinBox, QComboBox, QLabel, QPushButton,
)

from app.config import AppConfig
from app.model.types import Move


class ShapeWizardDialog(QDialog):
    """Generates simple milling toolpaths without external CAD/CAM."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Shape…")
        self._config = config
        self._result_moves: list[Move] = []
        self._setup_ui()
        self._on_tool_changed()
        self._update_visibility()
        self._update_preview()

    # ------------------------------------------------------------------
    # UI

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ---- Shape ----
        shape_box = QGroupBox("Shape")
        shape_row = QHBoxLayout(shape_box)
        self._rb_rect   = QRadioButton("Rectangle")
        self._rb_circle = QRadioButton("Circle")
        self._rb_rect.setChecked(True)
        shape_row.addWidget(self._rb_rect)
        shape_row.addWidget(self._rb_circle)
        shape_row.addStretch()
        layout.addWidget(shape_box)

        # ---- Operation ----
        op_box = QGroupBox("Operation")
        op_layout = QVBoxLayout(op_box)
        self._rb_cont_out = QRadioButton("Contour — outside")
        self._rb_cont_in  = QRadioButton("Contour — inside (cutout)")
        self._rb_pocket   = QRadioButton("Pocket / Facing")
        self._rb_cont_out.setChecked(True)
        op_layout.addWidget(self._rb_cont_out)
        op_layout.addWidget(self._rb_cont_in)
        op_layout.addWidget(self._rb_pocket)
        layout.addWidget(op_box)

        # ---- Rectangle dimensions ----
        self._rect_box = QGroupBox("Dimensions")
        rect_form = QFormLayout(self._rect_box)
        self._spin_w = self._mm_spin(1, 500, 50.0)
        rect_form.addRow("Width:", self._spin_w)
        self._spin_h = self._mm_spin(1, 500, 50.0)
        rect_form.addRow("Height:", self._spin_h)
        layout.addWidget(self._rect_box)

        # ---- Circle dimensions ----
        self._circ_box = QGroupBox("Dimensions")
        circ_form = QFormLayout(self._circ_box)
        self._spin_r = self._mm_spin(0.5, 250, 25.0)
        circ_form.addRow("Radius:", self._spin_r)
        layout.addWidget(self._circ_box)

        # ---- Tool ----
        tool_box = QGroupBox("Tool")
        tool_form = QFormLayout(tool_box)
        self._cmb_tool = QComboBox()
        self._cmb_tool.addItem("Manual…", None)
        for tp in self._config.tool_presets:
            self._cmb_tool.addItem(f"{tp.name}  (⌀ {tp.tool_diameter_mm:.3f} mm)", tp)
        tool_form.addRow("Preset:", self._cmb_tool)
        self._spin_diam = self._mm_spin(0.001, 50, 2.0)
        self._spin_diam.setDecimals(3)
        tool_form.addRow("Diameter:", self._spin_diam)
        layout.addWidget(tool_box)

        # ---- Z parameters ----
        z_box = QGroupBox("Z Parameters")
        z_form = QFormLayout(z_box)
        self._spin_z_total = self._mm_spin(0.01, 200, 3.0)
        self._spin_z_total.setToolTip("Total cutting depth (positive = downward into material)")
        z_form.addRow("Total depth:", self._spin_z_total)
        self._spin_z_step = self._mm_spin(0.01, 50, 1.0)
        self._spin_z_step.setToolTip("Maximum Z step-down per pass")
        z_form.addRow("Step per pass:", self._spin_z_step)
        layout.addWidget(z_box)

        # ---- Pocket settings ----
        self._pocket_box = QGroupBox("Pocket Settings")
        pocket_form = QFormLayout(self._pocket_box)
        self._spin_overlap = QDoubleSpinBox()
        self._spin_overlap.setRange(5, 95)
        self._spin_overlap.setDecimals(0)
        self._spin_overlap.setSuffix(" %")
        self._spin_overlap.setValue(50)
        self._spin_overlap.setToolTip(
            "Tool-path overlap. 50 % = each pass overlaps the previous by half the tool diameter."
        )
        pocket_form.addRow("Overlap:", self._spin_overlap)
        layout.addWidget(self._pocket_box)

        # ---- Info ----
        self._lbl_info = QLabel()
        self._lbl_info.setStyleSheet("color: #555555; font-size: 11px;")
        layout.addWidget(self._lbl_info)

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # ---- Connections ----
        self._rb_rect.toggled.connect(self._update_visibility)
        self._rb_circle.toggled.connect(self._update_visibility)
        self._rb_pocket.toggled.connect(self._update_visibility)
        self._rb_cont_in.toggled.connect(self._update_visibility)
        self._cmb_tool.currentIndexChanged.connect(self._on_tool_changed)
        for w in (self._spin_w, self._spin_h, self._spin_r, self._spin_diam,
                  self._spin_z_total, self._spin_z_step, self._spin_overlap):
            w.valueChanged.connect(self._update_preview)
        for rb in (self._rb_rect, self._rb_circle, self._rb_cont_out,
                   self._rb_cont_in, self._rb_pocket):
            rb.toggled.connect(self._update_preview)

    @staticmethod
    def _mm_spin(lo: float, hi: float, val: float) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(1)
        s.setSuffix(" mm")
        s.setValue(val)
        s.setKeyboardTracking(False)
        return s

    # ------------------------------------------------------------------
    # Slots

    def _on_tool_changed(self):
        tp = self._cmb_tool.currentData()
        if tp is not None:
            self._spin_diam.setValue(tp.tool_diameter_mm)
            self._spin_diam.setEnabled(False)
        else:
            self._spin_diam.setEnabled(True)
        self._update_preview()

    def _update_visibility(self):
        is_rect   = self._rb_rect.isChecked()
        is_pocket = self._rb_pocket.isChecked()

        self._rect_box.setVisible(is_rect)
        self._circ_box.setVisible(not is_rect)
        self._pocket_box.setVisible(is_pocket)

        # Inside contour doesn't apply to pocket
        self._rb_cont_in.setEnabled(not is_pocket)
        if is_pocket and self._rb_cont_in.isChecked():
            self._rb_cont_out.setChecked(True)

        self._update_preview()

    def _update_preview(self):
        moves = self._generate()
        if moves:
            n_cut = sum(1 for m in moves if m.pen_down and m.xy_move)
            n_pass = len([m for m in moves if m.z_move and m.pen_down])
            self._lbl_info.setText(
                f"{len(moves)} moves  |  {n_cut} cutting segments  |  {n_pass} Z-plunges"
            )
            self._btn_ok.setEnabled(True)
        else:
            self._lbl_info.setText("⚠  Tool too large for the selected dimensions — no toolpath possible.")
            self._btn_ok.setEnabled(False)
        self._result_moves = moves

    # ------------------------------------------------------------------
    # Toolpath generation

    def _generate(self) -> list[Move]:
        from app.cam.simple_cam import (
            rectangle_contour, circle_contour,
            rectangle_pocket, circle_pocket,
        )
        tool_r  = self._spin_diam.value() / 2.0
        z_total = -abs(self._spin_z_total.value())
        z_step  = self._spin_z_step.value()
        overlap = self._spin_overlap.value() / 100.0
        is_rect = self._rb_rect.isChecked()

        if self._rb_pocket.isChecked():
            if is_rect:
                return rectangle_pocket(
                    self._spin_w.value(), self._spin_h.value(),
                    tool_r, overlap, z_total, z_step,
                )
            else:
                return circle_pocket(self._spin_r.value(), tool_r, overlap, z_total, z_step)
        else:
            side = "outside" if self._rb_cont_out.isChecked() else "inside"
            if is_rect:
                return rectangle_contour(
                    self._spin_w.value(), self._spin_h.value(),
                    tool_r, side, z_total, z_step,
                )
            else:
                return circle_contour(self._spin_r.value(), tool_r, side, z_total, z_step)

    def _on_accept(self):
        if self._result_moves:
            self.accept()

    # ------------------------------------------------------------------
    # Public

    def get_moves(self) -> list[Move]:
        return self._result_moves

    def get_label(self) -> str:
        shape = "Rect" if self._rb_rect.isChecked() else "Circle"
        if self._rb_pocket.isChecked():
            op = "Pocket"
        elif self._rb_cont_out.isChecked():
            op = "Contour-Out"
        else:
            op = "Contour-In"
        diam = self._spin_diam.value()
        depth = self._spin_z_total.value()
        return f"{shape} {op} ⌀{diam:.3g} z{depth:.2g}"
