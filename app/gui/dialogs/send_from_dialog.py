from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QRadioButton,
    QComboBox, QLabel, QHBoxLayout, QCheckBox,
)

from app.model.project import Project
from app.model.types import Move


class SendFromDialog(QDialog):
    # World position of the first move that will be sent; (-1, -1) = none
    preview_move_changed = pyqtSignal(float, float)

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Send From…")
        self._project = project
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ---- Mode: from beginning ----
        self._rb_begin = QRadioButton("From beginning")
        self._rb_begin.setChecked(True)
        layout.addWidget(self._rb_begin)

        # ---- Mode: from object ----
        obj_row = QHBoxLayout()
        self._rb_object = QRadioButton("From object:")
        obj_row.addWidget(self._rb_object)
        self._cmb_object = QComboBox()
        for obj in self._project.visible_objects():
            self._cmb_object.addItem(obj.label, obj.id)
        self._cmb_object.setEnabled(False)
        obj_row.addWidget(self._cmb_object)
        obj_row.addStretch()
        layout.addLayout(obj_row)

        # Sub-option: also filter by Z (only active when rb_object is checked)
        also_z_row = QHBoxLayout()
        also_z_row.addSpacing(24)
        self._chk_also_z = QCheckBox("also from Z-layer ≤")
        self._chk_also_z.setEnabled(False)
        also_z_row.addWidget(self._chk_also_z)
        self._cmb_also_z = QComboBox()
        self._cmb_also_z.setEditable(True)
        self._cmb_also_z.setEnabled(False)
        also_z_row.addWidget(self._cmb_also_z)
        also_z_row.addWidget(QLabel("mm"))
        also_z_row.addStretch()
        layout.addLayout(also_z_row)

        # ---- Mode: from Z-layer (global) ----
        z_row = QHBoxLayout()
        self._rb_zlayer = QRadioButton("From Z-layer ≤")
        z_row.addWidget(self._rb_zlayer)
        self._cmb_z = QComboBox()
        self._cmb_z.setEditable(True)
        self._cmb_z.setEnabled(False)
        z_row.addWidget(self._cmb_z)
        z_row.addWidget(QLabel("mm"))
        z_row.addStretch()
        layout.addLayout(z_row)

        # Populate Z combos
        all_z: set[float] = set()
        for obj in self._project.visible_objects():
            all_z.update(obj.distinct_z_depths)
        for z in sorted(all_z):
            label = f"{z:.3f}"
            self._cmb_z.addItem(label, z)
            self._cmb_also_z.addItem(label, z)

        # Connections
        self._rb_begin.toggled.connect(self._on_mode_changed)
        self._rb_object.toggled.connect(self._on_mode_changed)
        self._rb_zlayer.toggled.connect(self._on_mode_changed)
        self._cmb_object.currentIndexChanged.connect(self._emit_preview)
        self._cmb_z.currentTextChanged.connect(self._emit_preview)
        self._chk_also_z.toggled.connect(self._on_also_z_toggled)
        self._cmb_also_z.currentTextChanged.connect(self._emit_preview)

        layout.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._emit_preview()

    # ------------------------------------------------------------------
    # Slots

    def _on_mode_changed(self):
        is_obj = self._rb_object.isChecked()
        self._cmb_object.setEnabled(is_obj)
        self._chk_also_z.setEnabled(is_obj)
        self._cmb_also_z.setEnabled(is_obj and self._chk_also_z.isChecked())
        self._cmb_z.setEnabled(self._rb_zlayer.isChecked())
        if not is_obj:
            self._chk_also_z.setChecked(False)
        self._emit_preview()

    def _on_also_z_toggled(self, checked: bool):
        self._cmb_also_z.setEnabled(checked)
        self._emit_preview()

    def _emit_preview(self):
        move = self._find_first_move()
        if move is not None:
            self.preview_move_changed.emit(move.from_pos.x, move.from_pos.y)
        else:
            self.preview_move_changed.emit(-1.0, -1.0)

    # ------------------------------------------------------------------
    # Logic helpers

    def _z_threshold(self, combo: QComboBox) -> Optional[float]:
        try:
            return float(combo.currentText())
        except ValueError:
            return None

    def _find_first_move(self) -> Optional[Move]:
        """Return the first Move object that will be transmitted."""
        if self._rb_begin.isChecked():
            for obj in self._project.visible_objects():
                if obj.computed_moves:
                    return obj.computed_moves[0]
            return None

        if self._rb_object.isChecked():
            sel_id = self._cmb_object.currentData()
            use_z = self._chk_also_z.isChecked()
            threshold = self._z_threshold(self._cmb_also_z) if use_z else None
            for obj in self._project.visible_objects():
                if obj.id == sel_id:
                    if use_z and threshold is not None:
                        for move in obj.computed_moves:
                            if move.pen_down and move.to_pos.z <= threshold:
                                return move
                        return None
                    return obj.computed_moves[0] if obj.computed_moves else None
            return None

        if self._rb_zlayer.isChecked():
            threshold = self._z_threshold(self._cmb_z)
            if threshold is None:
                return None
            for obj in self._project.visible_objects():
                for move in obj.computed_moves:
                    if move.pen_down and move.to_pos.z <= threshold:
                        return move
            return None

        return None

    # ------------------------------------------------------------------
    # Public

    def get_result(self) -> tuple[str, int, str]:
        """Return (scope, start_move_index, selected_object_id)."""
        if self._rb_begin.isChecked():
            return "all", 0, ""

        if self._rb_object.isChecked():
            sel_id = self._cmb_object.currentData()
            use_z  = self._chk_also_z.isChecked()
            threshold = self._z_threshold(self._cmb_also_z) if use_z else None

            offset = 0
            for obj in self._project.visible_objects():
                if obj.id == sel_id:
                    if use_z and threshold is not None:
                        # Find first matching move within selected object
                        for i, move in enumerate(obj.computed_moves):
                            if move.pen_down and move.to_pos.z <= threshold:
                                return "all", offset + i, ""
                        # No match in this object → start at next object
                        return "all", offset + len(obj.computed_moves), ""
                    return "all", offset, ""
                offset += len(obj.computed_moves)
            return "all", 0, ""

        if self._rb_zlayer.isChecked():
            threshold = self._z_threshold(self._cmb_z)
            if threshold is None:
                return "all", 0, ""
            idx = 0
            for obj in self._project.visible_objects():
                for move in obj.computed_moves:
                    if move.pen_down and move.to_pos.z <= threshold:
                        return "all", idx, ""
                    idx += 1
            return "all", 0, ""

        return "all", 0, ""
