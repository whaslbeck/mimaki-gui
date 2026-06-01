from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QListWidget, QListWidgetItem, QPushButton, QLabel,
    QDoubleSpinBox, QLineEdit,
)
from PyQt6.QtCore import Qt

from app.model.project import Project
from app.model.ref_point import RefPoint


class _PointEditDialog(QDialog):
    """Small dialog for entering / editing a single reference point."""

    def __init__(self, point: RefPoint | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reference Point" if point is None else "Edit Reference Point")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._edit_label = QLineEdit(point.label if point else "")
        form.addRow("Label:", self._edit_label)

        def _spin(val: float) -> QDoubleSpinBox:
            s = QDoubleSpinBox()
            s.setRange(-9999, 9999)
            s.setDecimals(2)
            s.setSuffix(" mm")
            s.setSingleStep(1.0)
            s.setValue(val)
            return s

        self._spin_x = _spin(point.x if point else 0.0)
        self._spin_y = _spin(point.y if point else 0.0)
        form.addRow("X:", self._spin_x)
        form.addRow("Y:", self._spin_y)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_values(self) -> tuple[float, float, str]:
        return self._spin_x.value(), self._spin_y.value(), self._edit_label.text().strip()


class RefPointsDialog(QDialog):
    """Manage reference points and working-area definition for the project."""

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reference Points")
        self.resize(380, 300)
        self._project = project
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            "Enter machine coordinates read from the display.\n"
            "With 2 points the working area is highlighted on the canvas."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#555;font-size:11px;")
        layout.addWidget(info)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemDoubleClicked.connect(self._on_edit)
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._btn_add  = QPushButton("Add…")
        self._btn_edit = QPushButton("Edit…")
        self._btn_del  = QPushButton("Delete")
        self._btn_clr  = QPushButton("Clear All")
        self._btn_add.clicked.connect(self._on_add)
        self._btn_edit.clicked.connect(self._on_edit)
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_clr.clicked.connect(self._on_clear)
        for b in (self._btn_add, self._btn_edit, self._btn_del, self._btn_clr):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------

    def _refresh(self):
        self._list.clear()
        for i, rp in enumerate(self._project.ref_points):
            tag = f"P{i+1}"
            label = f"  {rp.label}" if rp.label else ""
            self._list.addItem(QListWidgetItem(
                f"{tag}{label}   —   X: {rp.x:.2f} mm  /  Y: {rp.y:.2f} mm"
            ))
        self._on_row_changed(self._list.currentRow())

    def _on_row_changed(self, row: int):
        has = row >= 0 and row < len(self._project.ref_points)
        self._btn_edit.setEnabled(has)
        self._btn_del.setEnabled(has)
        self._btn_clr.setEnabled(bool(self._project.ref_points))

    def _on_add(self):
        dlg = _PointEditDialog(parent=self)
        if not dlg.exec():
            return
        x, y, label = dlg.get_values()
        rp = RefPoint(x=x, y=y, label=label)
        self._project.ref_points.append(rp)
        self._project.modified = True
        self._refresh()
        self._list.setCurrentRow(len(self._project.ref_points) - 1)

    def _on_edit(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._project.ref_points):
            return
        rp = self._project.ref_points[row]
        dlg = _PointEditDialog(point=rp, parent=self)
        if not dlg.exec():
            return
        rp.x, rp.y, rp.label = dlg.get_values()
        self._project.modified = True
        self._refresh()
        self._list.setCurrentRow(row)

    def _on_delete(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._project.ref_points):
            return
        self._project.ref_points.pop(row)
        self._project.modified = True
        self._refresh()
        new_row = min(row, len(self._project.ref_points) - 1)
        self._list.setCurrentRow(new_row)

    def _on_clear(self):
        self._project.ref_points.clear()
        self._project.modified = True
        self._refresh()
