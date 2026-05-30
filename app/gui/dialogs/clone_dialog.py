from __future__ import annotations
import math

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox,
    QDoubleSpinBox, QVBoxLayout, QLabel, QMessageBox,
)

from app.model.gcode_object import GcodeObject
from app.model.project import Project, MACHINE_W, MACHINE_H


class CloneDialog(QDialog):
    def __init__(self, source: GcodeObject, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clone Object")
        self._source = source
        self._project = project
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._spin_count = QSpinBox()
        self._spin_count.setRange(1, 200)
        self._spin_count.setValue(1)
        form.addRow("Number of clones", self._spin_count)

        self._spin_gap = QDoubleSpinBox()
        self._spin_gap.setRange(0, 100)
        self._spin_gap.setSingleStep(1)
        self._spin_gap.setDecimals(2)
        self._spin_gap.setValue(2.0)
        form.addRow("Gap between objects [mm]", self._spin_gap)

        layout.addLayout(form)
        layout.addWidget(QLabel(
            "Clones will be placed automatically,\n"
            "avoiding existing objects and forbidden zones."
        ))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        count = self._spin_count.value()
        gap = self._spin_gap.value()

        bb = self._source.bounding_box
        w = bb.width
        h = bb.height
        step_x = w + gap
        step_y = h + gap

        placed = 0
        failed = 0
        angle = math.radians(self._source.transform.rotation_deg)

        for _ in range(count):
            clone = self._source.clone()
            found = False
            y = gap
            while y + h <= MACHINE_H:
                x = gap
                while x + w <= MACHINE_W:
                    if not self._project.bbox_collides(x, y, w, h):
                        # Move clone so its bounding box min lands at (x, y).
                        # apply_pos adds offset BEFORE rotation, so we need the
                        # inverse-rotated displacement to get a world-space shift.
                        dx_world = x - bb.min_x
                        dy_world = y - bb.min_y
                        cos_a = math.cos(-angle)
                        sin_a = math.sin(-angle)
                        clone.transform.offset_x += cos_a * dx_world - sin_a * dy_world
                        clone.transform.offset_y += sin_a * dx_world + cos_a * dy_world
                        clone._invalidate()
                        new_bb = clone.bounding_box
                        clone.transform.pivot_x = new_bb.center_x
                        clone.transform.pivot_y = new_bb.center_y
                        clone._invalidate()
                        self._project.add_object(clone)
                        placed += 1
                        found = True
                        break
                    x += step_x
                if found:
                    break
                y += step_y
            if not found:
                failed += 1
                # Add at increasing offset from original so clones don't stack
                clone.transform.offset_x += bb.width * (placed + failed) + gap * (placed + failed)
                clone._invalidate()
                new_bb = clone.bounding_box
                clone.transform.pivot_x = new_bb.center_x
                clone.transform.pivot_y = new_bb.center_y
                clone.placement_warning = True
                clone._invalidate()
                self._project.add_object(clone)

        if failed > 0:
            QMessageBox.warning(
                self,
                "Clone",
                f"Placed {placed} of {count} clones automatically.\n"
                f"{failed} clone(s) could not be placed (insufficient space) "
                f"and were added with an offset — please reposition manually.",
            )
        self.accept()
