from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QDoubleSpinBox,
    QVBoxLayout, QCheckBox,
)

from app.model.types import GridSettings


class GridSettingsDialog(QDialog):
    def __init__(self, grid: GridSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grid Settings")
        self._setup_ui(grid)

    def _setup_ui(self, grid: GridSettings):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._chk_visible = QCheckBox()
        self._chk_visible.setChecked(grid.visible)
        form.addRow("Show grid", self._chk_visible)

        self._spin_spacing = QDoubleSpinBox()
        self._spin_spacing.setRange(0.1, 100)
        self._spin_spacing.setSingleStep(1)
        self._spin_spacing.setDecimals(2)
        self._spin_spacing.setValue(grid.spacing_mm)
        form.addRow("Spacing [mm]", self._spin_spacing)

        self._spin_ox = QDoubleSpinBox()
        self._spin_ox.setRange(-999, 999)
        self._spin_ox.setSingleStep(1)
        self._spin_ox.setDecimals(2)
        self._spin_ox.setValue(grid.origin_x)
        form.addRow("Origin X [mm]", self._spin_ox)

        self._spin_oy = QDoubleSpinBox()
        self._spin_oy.setRange(-999, 999)
        self._spin_oy.setSingleStep(1)
        self._spin_oy.setDecimals(2)
        self._spin_oy.setValue(grid.origin_y)
        form.addRow("Origin Y [mm]", self._spin_oy)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_settings(self) -> GridSettings:
        return GridSettings(
            visible=self._chk_visible.isChecked(),
            spacing_mm=self._spin_spacing.value(),
            origin_x=self._spin_ox.value(),
            origin_y=self._spin_oy.value(),
        )
