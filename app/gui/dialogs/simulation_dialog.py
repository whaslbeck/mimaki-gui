from __future__ import annotations
from typing import Optional

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QDoubleSpinBox, QGroupBox, QLabel, QPushButton,
    QScrollArea, QMessageBox, QDialogButtonBox, QFileDialog,
)

from app.model.types import Move
from app.sim.simulator import simulate, depth_to_rgba, export_stl


class SimulationDialog(QDialog):
    def __init__(self, moves: list[Move], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Machining Simulation")
        self.resize(960, 720)
        self._moves = moves
        self._depth_map: Optional[np.ndarray] = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ---- Config row ----
        cfg_row = QHBoxLayout()

        wp_box = QGroupBox("Workpiece")
        wp_form = QFormLayout(wp_box)
        self._spin_wx        = self._dspin(0,    9999, 0.0,   "Origin X [mm]",    wp_form)
        self._spin_wy        = self._dspin(0,    9999, 0.0,   "Origin Y [mm]",    wp_form)
        self._spin_ww        = self._dspin(1,    9999, 483.0, "Width [mm]",        wp_form)
        self._spin_wh        = self._dspin(1,    9999, 305.0, "Height [mm]",       wp_form)
        self._spin_thickness = self._dspin(0.1, 200,  10.0,  "Thickness [mm]",    wp_form)
        cfg_row.addWidget(wp_box)

        tool_box = QGroupBox("Tool / Resolution")
        tool_form = QFormLayout(tool_box)
        self._spin_tool_d = self._dspin(0.1, 50, 3.0,  "Cutter ⌀ [mm]",   tool_form)
        self._spin_res    = self._dspin(0.1,  5, 2.0,  "Resolution [px/mm]", tool_form)
        cfg_row.addWidget(tool_box)

        layout.addLayout(cfg_row)

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        self._btn_run = QPushButton("▶  Run Simulation")
        self._btn_run.setDefault(True)
        self._btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self._btn_run)

        self._btn_stl = QPushButton("Export STL…")
        self._btn_stl.setEnabled(False)
        self._btn_stl.clicked.connect(self._on_export_stl)
        btn_row.addWidget(self._btn_stl)

        self._lbl_status = QLabel("")
        btn_row.addWidget(self._lbl_status)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ---- Result image ----
        self._img_label = QLabel("Run the simulation to see the result.")
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self._img_label)
        scroll.setWidgetResizable(False)
        layout.addWidget(scroll, 1)

        # ---- Close button ----
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _dspin(lo, hi, val, label, form) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setDecimals(2)
        s.setSingleStep(1.0)
        s.setKeyboardTracking(False)
        form.addRow(label, s)
        return s

    # ------------------------------------------------------------------
    # Actions

    def _on_run(self):
        self._btn_run.setEnabled(False)
        self._btn_run.setText("Running…")
        self._lbl_status.setText("")
        try:
            depth = simulate(
                moves=self._moves,
                workpiece_x=self._spin_wx.value(),
                workpiece_y=self._spin_wy.value(),
                workpiece_w=self._spin_ww.value(),
                workpiece_h=self._spin_wh.value(),
                tool_diameter=self._spin_tool_d.value(),
                px_per_mm=self._spin_res.value(),
            )
            self._depth_map = depth
            self._render(depth, self._spin_thickness.value())
            n_cut = int((depth > 0).sum())
            pct   = 100 * n_cut / max(depth.size, 1)
            self._lbl_status.setText(
                f"{depth.shape[1]}×{depth.shape[0]} px  |  "
                f"{pct:.1f}% material removed  |  "
                f"max depth {float(depth.max()):.3f} mm"
            )
            self._btn_stl.setEnabled(True)
        except ImportError:
            QMessageBox.critical(
                self, "Missing dependency",
                "numpy is required for simulation.\n"
                "Install with:  pip install numpy",
            )
        except Exception as e:
            QMessageBox.critical(self, "Simulation error", str(e))
        finally:
            self._btn_run.setEnabled(True)
            self._btn_run.setText("▶  Run Simulation")

    def _render(self, depth: np.ndarray, thickness: float):
        rgba = depth_to_rgba(depth, thickness)
        self._rgba_buf = rgba                   # keep alive for QImage
        h, w = depth.shape
        img = QImage(
            rgba.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888
        )
        self._img_label.setPixmap(QPixmap.fromImage(img))
        self._img_label.resize(w, h)

    def _on_export_stl(self):
        if self._depth_map is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export STL", "", "STL files (*.stl);;All files (*)"
        )
        if not path:
            return
        if not path.lower().endswith(".stl"):
            path += ".stl"
        try:
            export_stl(
                path=path,
                depth=self._depth_map,
                workpiece_x=self._spin_wx.value(),
                workpiece_y=self._spin_wy.value(),
                workpiece_w=self._spin_ww.value(),
                workpiece_h=self._spin_wh.value(),
                thickness=self._spin_thickness.value(),
                px_per_mm=self._spin_res.value(),
            )
            QMessageBox.information(self, "Export STL", f"Saved:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))
