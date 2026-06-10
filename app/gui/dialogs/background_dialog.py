from __future__ import annotations
import math
from typing import Optional

from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QImage, QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QGroupBox, QFormLayout, QDoubleSpinBox,
    QLineEdit, QComboBox, QDialogButtonBox, QFileDialog, QMessageBox,
    QSlider, QCheckBox,
)

from app.model.calibration import (
    BackgroundImage, CalibrationPoint, compute_transform,
    encode_image, decode_image, DISPLAY_MODES,
)


class _ImageView(QWidget):
    """Shows a QImage with zoom/pan and lets the user place/select markers."""
    point_added = pyqtSignal(float, float)   # image px, py
    point_clicked = pyqtSignal(int)          # marker index, -1 = none
    zoom_changed = pyqtSignal(float)         # screen px per image px

    LOUPE_SIZE = 150
    LOUPE_ZOOM = 4.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img: Optional[QImage] = None
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._pan_last: Optional[QPointF] = None
        self._cursor_pos: Optional[QPointF] = None
        self._user_adjusted = False   # once True, stop auto-fitting on resize
        self.add_mode = False
        self.loupe_on = True
        self.points: list[CalibrationPoint] = []
        self.selected = -1
        self.setMinimumSize(400, 400)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def set_image(self, img: Optional[QImage]):
        self._img = img
        self._user_adjusted = False
        self.fit()

    def fit(self):
        self._user_adjusted = False
        if self._img is None or self._img.isNull():
            self.update()
            return
        iw, ih = self._img.width(), self._img.height()
        s = min(self.width() / iw, self.height() / ih) * 0.96
        self._scale = s
        self._offset = QPointF(
            (self.width() - iw * s) / 2, (self.height() - ih * s) / 2
        )
        self.zoom_changed.emit(self._scale)
        self.update()

    def zoom_by(self, factor: float):
        """Zoom around the widget centre."""
        if self._img is None or self._img.isNull():
            return
        cx, cy = self.width() / 2, self.height() / 2
        ipx, ipy = self._widget_to_img(cx, cy)
        self._scale = max(0.02, min(40.0, self._scale * factor))
        self._offset = QPointF(cx - ipx * self._scale, cy - ipy * self._scale)
        self._user_adjusted = True
        self.zoom_changed.emit(self._scale)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._user_adjusted:
            self.fit()

    # coordinate mapping ------------------------------------------------
    def _img_to_widget(self, px: float, py: float) -> QPointF:
        return QPointF(self._offset.x() + px * self._scale,
                       self._offset.y() + py * self._scale)

    def _widget_to_img(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self._offset.x()) / self._scale,
                (y - self._offset.y()) / self._scale)

    # paint -------------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#202020"))
        if self._img is None or self._img.isNull():
            p.setPen(QColor("#AAAAAA"))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                       "No image loaded")
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.save()
        p.translate(self._offset)
        p.scale(self._scale, self._scale)
        p.drawImage(0, 0, self._img)
        p.restore()

        p.setFont(QFont("Sans", 9, QFont.Weight.Bold))
        for i, pt in enumerate(self.points):
            sp = self._img_to_widget(pt.px, pt.py)
            sel = (i == self.selected)
            col = QColor("#FFD000") if sel else QColor("#E000E0")
            arm = 11 if sel else 8
            p.setPen(QPen(col, 2 if sel else 1.5))
            p.drawLine(QPointF(sp.x() - arm, sp.y()), QPointF(sp.x() + arm, sp.y()))
            p.drawLine(QPointF(sp.x(), sp.y() - arm), QPointF(sp.x(), sp.y() + arm))
            p.setBrush(col)
            p.drawEllipse(sp, 3, 3)
            p.setPen(QPen(col, 1))
            p.drawText(sp + QPointF(arm + 2, -2), pt.label or f"C{i + 1}")

        self._draw_loupe(p)

    def _draw_loupe(self, p: QPainter):
        if not (self.loupe_on and self._cursor_pos is not None
                and self._img is not None and not self._img.isNull()):
            return
        mx, my = self._cursor_pos.x(), self._cursor_pos.y()
        ipx, ipy = self._widget_to_img(mx, my)
        if not (0 <= ipx <= self._img.width() and 0 <= ipy <= self._img.height()):
            return
        size = self.LOUPE_SIZE
        half = size / (2 * self.LOUPE_ZOOM)        # source half-extent (image px)
        src = QRectF(ipx - half, ipy - half, 2 * half, 2 * half)
        margin = 10
        lx = margin if mx > self.width() / 2 else self.width() - size - margin
        ly = margin if my > self.height() / 2 else self.height() - size - margin
        dst = QRectF(lx, ly, size, size)

        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(dst, QColor("#000000"))
        p.drawImage(dst, self._img, src)
        # centre crosshair = exact click point
        cx, cy = dst.center().x(), dst.center().y()
        p.setPen(QPen(QColor("#FFD000"), 1))
        p.drawLine(QPointF(cx - 12, cy), QPointF(cx + 12, cy))
        p.drawLine(QPointF(cx, cy - 12), QPointF(cx, cy + 12))
        p.setPen(QPen(QColor("#FFD000"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(dst)
        p.restore()

    # interaction -------------------------------------------------------
    def wheelEvent(self, e: QWheelEvent):
        if self._img is None:
            return
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        mx, my = e.position().x(), e.position().y()
        ipx, ipy = self._widget_to_img(mx, my)
        self._scale = max(0.02, min(40.0, self._scale * factor))
        self._offset = QPointF(mx - ipx * self._scale, my - ipy * self._scale)
        self._user_adjusted = True
        self.zoom_changed.emit(self._scale)
        self.update()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = e.position()
            return
        if e.button() != Qt.MouseButton.LeftButton or self._img is None:
            return
        mx, my = e.position().x(), e.position().y()
        if self.add_mode:
            px, py = self._widget_to_img(mx, my)
            px = max(0.0, min(self._img.width(), px))
            py = max(0.0, min(self._img.height(), py))
            self.point_added.emit(px, py)
            return
        # select nearest marker within 14 px
        best, bestd = -1, 14.0
        for i, pt in enumerate(self.points):
            sp = self._img_to_widget(pt.px, pt.py)
            d = math.hypot(mx - sp.x(), my - sp.y())
            if d < bestd:
                best, bestd = i, d
        self.point_clicked.emit(best)

    def mouseMoveEvent(self, e: QMouseEvent):
        self._cursor_pos = e.position()
        if self._pan_last is not None:
            d = e.position() - self._pan_last
            self._offset += d
            self._pan_last = e.position()
            self._user_adjusted = True
        if self.loupe_on or self._pan_last is not None:
            self.update()

    def leaveEvent(self, e):
        self._cursor_pos = None
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = None


class BackgroundDialog(QDialog):
    """Load and calibrate a photo of the machine bed as a background image."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Background Image & Calibration")
        self.resize(1100, 700)
        self._project = project

        existing = project.background
        self._img: Optional[QImage] = (
            decode_image(existing.image_b64) if existing else None
        )
        self._image_b64 = existing.image_b64 if existing else ""
        self._points: list[CalibrationPoint] = (
            [CalibrationPoint(**{k: getattr(p, k)
                                 for k in ("px", "py", "x", "y", "label")})
             for p in existing.points] if existing else []
        )
        self._mode = existing.display_mode if existing else "original"
        self._opacity = existing.opacity if existing else 1.0
        self._points_visible = existing.points_visible if existing else True

        self._build_ui()
        self._view.set_image(self._img)
        self._view.points = self._points
        self._refresh_list()
        self._refresh_rms()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QHBoxLayout(self)

        # Image column: zoom toolbar + view
        img_col = QVBoxLayout()
        img_col.setSpacing(2)
        zoom_row = QHBoxLayout()
        btn_zin = QPushButton("Zoom +")
        btn_zin.clicked.connect(lambda: self._view.zoom_by(1.25))
        zoom_row.addWidget(btn_zin)
        btn_zout = QPushButton("Zoom −")
        btn_zout.clicked.connect(lambda: self._view.zoom_by(1 / 1.25))
        zoom_row.addWidget(btn_zout)
        btn_fit = QPushButton("Fit")
        btn_fit.clicked.connect(lambda: self._view.fit())
        zoom_row.addWidget(btn_fit)
        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setMinimumWidth(48)
        zoom_row.addWidget(self._lbl_zoom)
        self._chk_loupe = QCheckBox("Magnifier")
        self._chk_loupe.setChecked(True)
        self._chk_loupe.toggled.connect(self._on_loupe_toggled)
        zoom_row.addWidget(self._chk_loupe)
        zoom_row.addStretch()
        zoom_row.addWidget(QLabel("Wheel = zoom · middle-drag = pan"))
        img_col.addLayout(zoom_row)

        self._view = _ImageView()
        self._view.point_added.connect(self._on_point_added)
        self._view.point_clicked.connect(self._on_point_clicked)
        self._view.zoom_changed.connect(self._on_zoom_changed)
        img_col.addWidget(self._view, 1)
        root.addLayout(img_col, 3)

        side = QVBoxLayout()
        root.addLayout(side, 1)

        btn_load = QPushButton("Load image…")
        btn_load.clicked.connect(self._on_load)
        side.addWidget(btn_load)
        self._lbl_info = QLabel("No image")
        self._lbl_info.setStyleSheet("color:#666; font-size:10px;")
        side.addWidget(self._lbl_info)

        # Hint
        hint = QLabel(
            "Mark ≥4 points spread across the bed (corners too) for a "
            "perspective fit. Zoom in and use the magnifier to hit each "
            "marker precisely."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:10px;")
        side.addWidget(hint)

        # Point list + add/delete
        side.addWidget(QLabel("Calibration points:"))
        self._list = QListWidget()
        self._list.setMaximumHeight(150)
        self._list.currentRowChanged.connect(self._on_row_changed)
        side.addWidget(self._list)

        row = QHBoxLayout()
        self._btn_add = QPushButton("+ Add point")
        self._btn_add.setCheckable(True)
        self._btn_add.toggled.connect(self._on_add_toggled)
        row.addWidget(self._btn_add)
        btn_del = QPushButton("Delete")
        btn_del.clicked.connect(self._on_delete)
        row.addWidget(btn_del)
        side.addLayout(row)

        # Editor for selected point
        self._editor = QGroupBox("Selected point — machine coordinates")
        ef = QFormLayout(self._editor)
        self._ed_label = QLineEdit()
        self._ed_label.editingFinished.connect(self._on_editor_changed)
        ef.addRow("Label:", self._ed_label)
        self._ed_x = QDoubleSpinBox()
        self._ed_x.setRange(-200, 700); self._ed_x.setDecimals(2)
        self._ed_x.setSuffix(" mm"); self._ed_x.setKeyboardTracking(False)
        self._ed_x.valueChanged.connect(self._on_editor_changed)
        ef.addRow("X:", self._ed_x)
        self._ed_y = QDoubleSpinBox()
        self._ed_y.setRange(-200, 500); self._ed_y.setDecimals(2)
        self._ed_y.setSuffix(" mm"); self._ed_y.setKeyboardTracking(False)
        self._ed_y.valueChanged.connect(self._on_editor_changed)
        ef.addRow("Y:", self._ed_y)
        self._cmb_saved = QComboBox()
        self._cmb_saved.addItem("— from saved point —", None)
        for sp in self._project.saved_points:
            self._cmb_saved.addItem(
                f"{sp.label or 'point'}  ({sp.x:.1f} / {sp.y:.1f})", (sp.x, sp.y)
            )
        self._cmb_saved.activated.connect(self._on_pick_saved)
        ef.addRow("Assign:", self._cmb_saved)
        self._editor.setEnabled(False)
        side.addWidget(self._editor)

        self._lbl_rms = QLabel("Fit: —")
        self._lbl_rms.setStyleSheet("font-weight:bold;")
        side.addWidget(self._lbl_rms)

        # Display options
        disp = QGroupBox("Display")
        df = QFormLayout(disp)
        self._cmb_mode = QComboBox()
        for m in DISPLAY_MODES:
            self._cmb_mode.addItem(m.capitalize(), m)
        self._cmb_mode.setCurrentIndex(DISPLAY_MODES.index(self._mode))
        df.addRow("Mode:", self._cmb_mode)
        self._sld_op = QSlider(Qt.Orientation.Horizontal)
        self._sld_op.setRange(10, 100)
        self._sld_op.setValue(int(self._opacity * 100))
        df.addRow("Opacity:", self._sld_op)
        self._chk_pts = QCheckBox("Show calibration points")
        self._chk_pts.setChecked(self._points_visible)
        df.addRow("", self._chk_pts)
        side.addWidget(disp)

        side.addStretch()

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        side.addWidget(bb)

    # ------------------------------------------------------------------
    def _on_load(self):
        import os
        path, _ = QFileDialog.getOpenFileName(
            self, "Load background image", os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)",
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Load image", "Could not load image.")
            return
        b64, w, h = encode_image(img)
        self._image_b64 = b64
        self._img = decode_image(b64)
        self._view.set_image(self._img)
        self._lbl_info.setText(f"{w} × {h} px")
        self.update()

    def _on_zoom_changed(self, scale: float):
        self._lbl_zoom.setText(f"{scale * 100:.0f}%")

    def _on_loupe_toggled(self, on: bool):
        self._view.loupe_on = on
        self._view.update()

    def _on_add_toggled(self, on: bool):
        self._view.add_mode = on
        self._btn_add.setText("Click image…" if on else "+ Add point")

    def _on_point_added(self, px: float, py: float):
        n = len(self._points) + 1
        self._points.append(CalibrationPoint(px=px, py=py, label=f"C{n}"))
        self._btn_add.setChecked(False)
        self._refresh_list()
        self._list.setCurrentRow(len(self._points) - 1)
        self._refresh_rms()
        self._view.update()

    def _on_point_clicked(self, index: int):
        if index >= 0:
            self._list.setCurrentRow(index)

    def _on_row_changed(self, row: int):
        self._view.selected = row
        self._view.update()
        if 0 <= row < len(self._points):
            p = self._points[row]
            self._editor.setEnabled(True)
            for w in (self._ed_x, self._ed_y, self._ed_label):
                w.blockSignals(True)
            self._ed_label.setText(p.label)
            self._ed_x.setValue(p.x)
            self._ed_y.setValue(p.y)
            for w in (self._ed_x, self._ed_y, self._ed_label):
                w.blockSignals(False)
            self._cmb_saved.setCurrentIndex(0)
        else:
            self._editor.setEnabled(False)

    def _on_editor_changed(self):
        row = self._list.currentRow()
        if not (0 <= row < len(self._points)):
            return
        p = self._points[row]
        p.label = self._ed_label.text()
        p.x = self._ed_x.value()
        p.y = self._ed_y.value()
        self._refresh_list_text(row)
        self._refresh_rms()
        self._view.update()

    def _on_pick_saved(self, idx: int):
        data = self._cmb_saved.itemData(idx)
        if data is None:
            return
        x, y = data
        self._ed_x.setValue(x)
        self._ed_y.setValue(y)   # triggers _on_editor_changed

    def _on_delete(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._points):
            del self._points[row]
            self._refresh_list()
            self._refresh_rms()
            self._view.update()

    # ------------------------------------------------------------------
    def _refresh_list(self):
        self._list.clear()
        for i, p in enumerate(self._points):
            self._list.addItem(QListWidgetItem(self._row_text(i, p)))

    def _row_text(self, i: int, p: CalibrationPoint) -> str:
        return (f"{p.label or 'C'+str(i+1)}:  px({p.px:.0f},{p.py:.0f}) "
                f"→ ({p.x:.1f} / {p.y:.1f})")

    def _refresh_list_text(self, row: int):
        if 0 <= row < self._list.count():
            self._list.item(row).setText(self._row_text(row, self._points[row]))

    def _refresh_rms(self):
        t, rms = compute_transform(self._points)
        n = len(self._points)
        if t is None:
            self._lbl_rms.setText(f"Fit: need ≥2 points ({n} set)")
            self._lbl_rms.setStyleSheet("color:#CC6600; font-weight:bold;")
            return
        model = {2: "similarity", 3: "affine"}.get(n, "perspective")
        color = "#008800" if rms < 1.0 else ("#AA8800" if rms < 3.0 else "#CC0000")
        self._lbl_rms.setText(f"Fit: {model}, RMS {rms:.2f} mm ({n} pts)")
        self._lbl_rms.setStyleSheet(f"color:{color}; font-weight:bold;")

    # ------------------------------------------------------------------
    def _on_accept(self):
        if not self._image_b64:
            QMessageBox.information(self, "Background", "No image loaded.")
            return
        if 0 < len(self._points) < 2:
            QMessageBox.information(
                self, "Background",
                "Need at least 2 calibration points (or none).")
            return
        self.accept()

    def get_background(self) -> Optional[BackgroundImage]:
        if not self._image_b64:
            return None
        img = self._img
        return BackgroundImage(
            image_b64=self._image_b64,
            img_w=img.width() if img else 0,
            img_h=img.height() if img else 0,
            points=self._points,
            display_mode=self._cmb_mode.currentData(),
            opacity=self._sld_op.value() / 100.0,
            points_visible=self._chk_pts.isChecked(),
        )
