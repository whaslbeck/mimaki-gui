from __future__ import annotations
import copy
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QGroupBox, QFormLayout,
    QDoubleSpinBox, QComboBox, QLineEdit, QPushButton, QLabel,
)

from app.config import AppConfig, ToolPreset
from app.model.project import Project

_XY_MACHINING_MMS = [0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 50]
_Z_MACHINING_MMS  = [0.5, 1, 2, 3, 5, 8, 10]
_XY_TRAVEL_MMS    = [20, 40, 60, 80]
_Z_TRAVEL_MMS     = [5, 10, 15, 20, 25, 30]


def _make_speed_combo(speeds_mms: list) -> QComboBox:
    c = QComboBox()
    for mms in speeds_mms:
        c.addItem(f"{mms:g} mm/s  ({mms * 6:.0f} cm/min)", mms * 60)
    return c


def _select_speed(combo: QComboBox, value_mm_min: float):
    best = min(range(combo.count()),
               key=lambda i: abs(combo.itemData(i) - value_mm_min))
    combo.setCurrentIndex(best)


class ToolLibraryDialog(QDialog):
    def __init__(self, config: AppConfig, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tool / Material Library")
        self.resize(580, 380)
        self._presets: list[ToolPreset] = copy.deepcopy(config.tool_presets)
        self._project = project
        self._applied: Optional[ToolPreset] = None
        self._loading = False
        self._setup_ui()
        self._refresh_list()

    # ------------------------------------------------------------------

    def _setup_ui(self):
        outer = QVBoxLayout(self)

        layout = QHBoxLayout()

        # Left: preset list + add/delete
        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(QLabel("Presets:"))
        left.addWidget(self._list, 1)
        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("Add")
        self._btn_add.clicked.connect(self._on_add)
        self._btn_del = QPushButton("Delete")
        self._btn_del.clicked.connect(self._on_delete)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_del)
        left.addLayout(btn_row)
        layout.addLayout(left)

        # Right: edit form
        right = QVBoxLayout()
        box = QGroupBox("Preset properties")
        form = QFormLayout(box)
        form.setSpacing(5)

        self._edit_name = QLineEdit()
        self._edit_name.textEdited.connect(self._on_field_changed)
        form.addRow("Name:", self._edit_name)

        self._spin_diam = QDoubleSpinBox()
        self._spin_diam.setRange(0.001, 50.0)
        self._spin_diam.setDecimals(3)
        self._spin_diam.setSuffix(" mm")
        self._spin_diam.setKeyboardTracking(False)
        self._spin_diam.valueChanged.connect(self._on_field_changed)
        form.addRow("Tool diameter:", self._spin_diam)

        self._cmb_xy_tr = _make_speed_combo(_XY_TRAVEL_MMS)
        self._cmb_xy_tr.currentIndexChanged.connect(self._on_field_changed)
        form.addRow("XY travel (PU):", self._cmb_xy_tr)

        self._cmb_xy_mc = _make_speed_combo(_XY_MACHINING_MMS)
        self._cmb_xy_mc.currentIndexChanged.connect(self._on_field_changed)
        form.addRow("XY machining (PD):", self._cmb_xy_mc)

        self._cmb_z_tr = _make_speed_combo(_Z_TRAVEL_MMS)
        self._cmb_z_tr.currentIndexChanged.connect(self._on_field_changed)
        form.addRow("Z travel (PU):", self._cmb_z_tr)

        self._cmb_z_mc = _make_speed_combo(_Z_MACHINING_MMS)
        self._cmb_z_mc.currentIndexChanged.connect(self._on_field_changed)
        form.addRow("Z machining (PD):", self._cmb_z_mc)

        right.addWidget(box)
        right.addStretch()

        self._btn_apply = QPushButton("Apply to Project")
        self._btn_apply.setToolTip(
            "Apply this preset's speeds to the current project and close."
        )
        self._btn_apply.clicked.connect(self._on_apply)
        right.addWidget(self._btn_apply)

        layout.addLayout(right)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        outer.addLayout(layout)
        outer.addWidget(buttons)

        self._set_form_enabled(False)

    # ------------------------------------------------------------------

    def _refresh_list(self):
        self._list.clear()
        for tp in self._presets:
            self._list.addItem(QListWidgetItem(tp.name))
        if self._presets:
            self._list.setCurrentRow(0)
        else:
            self._set_form_enabled(False)

    def _set_form_enabled(self, enabled: bool):
        for w in (self._edit_name, self._spin_diam,
                  self._cmb_xy_tr, self._cmb_xy_mc,
                  self._cmb_z_tr, self._cmb_z_mc,
                  self._btn_apply, self._btn_del):
            w.setEnabled(enabled)

    def _on_row_changed(self, row: int):
        if row < 0 or row >= len(self._presets):
            self._set_form_enabled(False)
            return
        self._set_form_enabled(True)
        tp = self._presets[row]
        self._loading = True
        self._edit_name.setText(tp.name)
        self._spin_diam.setValue(tp.tool_diameter_mm)
        _select_speed(self._cmb_xy_tr, tp.xy_travel_mm_min)
        _select_speed(self._cmb_xy_mc, tp.xy_machining_mm_min)
        _select_speed(self._cmb_z_tr, tp.z_travel_mm_min)
        _select_speed(self._cmb_z_mc, tp.z_machining_mm_min)
        self._loading = False

    def _on_field_changed(self):
        if self._loading:
            return
        row = self._list.currentRow()
        if row < 0 or row >= len(self._presets):
            return
        tp = self._presets[row]
        tp.name = self._edit_name.text() or "Preset"
        tp.tool_diameter_mm = self._spin_diam.value()
        tp.xy_travel_mm_min = self._cmb_xy_tr.currentData()
        tp.xy_machining_mm_min = self._cmb_xy_mc.currentData()
        tp.z_travel_mm_min = self._cmb_z_tr.currentData()
        tp.z_machining_mm_min = self._cmb_z_mc.currentData()
        self._list.currentItem().setText(tp.name)

    def _on_add(self):
        tp = ToolPreset(name=f"Preset {len(self._presets) + 1}")
        self._presets.append(tp)
        self._list.addItem(QListWidgetItem(tp.name))
        self._list.setCurrentRow(len(self._presets) - 1)

    def _on_delete(self):
        row = self._list.currentRow()
        if row < 0:
            return
        self._presets.pop(row)
        self._list.takeItem(row)
        if self._presets:
            self._list.setCurrentRow(min(row, len(self._presets) - 1))
        else:
            self._set_form_enabled(False)

    def _on_apply(self):
        self._on_field_changed()
        self._applied = self._presets[self._list.currentRow()]
        self.accept()

    # ------------------------------------------------------------------
    # Public

    def get_presets(self) -> list[ToolPreset]:
        return self._presets

    def get_applied_preset(self) -> Optional[ToolPreset]:
        return self._applied
