from __future__ import annotations
import math
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QLabel, QCheckBox, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QFont, QWheelEvent, QMouseEvent,
)

from app.model.types import Move
from app.model.project import MACHINE_W, MACHINE_H

_BG = "#1A1A2A"


class _View3DWidget(QWidget):
    def __init__(self, moves: list[Move], parent=None):
        super().__init__(parent)
        self._moves = moves
        self._show_travel = False
        self._z_scale = 10.0

        # Default view: slightly from above, from front-left
        self._az = math.radians(225)
        self._el = math.radians(25)
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)

        # Drag state
        self._drag_start: Optional[QPointF] = None
        self._drag_az0 = 0.0
        self._drag_el0 = 0.0
        self._drag_pan0 = QPointF(0.0, 0.0)

        # Bounding box for auto-scale
        xs = [m.from_pos.x for m in moves] + [m.to_pos.x for m in moves]
        ys = [m.from_pos.y for m in moves] + [m.to_pos.y for m in moves]
        if xs and ys:
            self._cx = (min(xs) + max(xs)) / 2
            self._cy = (min(ys) + max(ys)) / 2
            self._extent = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
        else:
            self._cx = MACHINE_W / 2
            self._cy = MACHINE_H / 2
            self._extent = max(MACHINE_W, MACHINE_H)

        # Distinct Z depths for depth planes
        z_vals = [m.to_pos.z for m in moves if m.pen_down and m.to_pos.z < 0]
        self._z_min = min(z_vals) if z_vals else 0.0
        self._distinct_z = sorted(
            {round(z, 3) for z in z_vals}, reverse=True  # shallowest first
        )

        self.setMinimumSize(500, 400)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # ------------------------------------------------------------------
    # Public setters

    def set_show_travel(self, v: bool):
        self._show_travel = v
        self.update()

    def set_z_scale(self, v: float):
        self._z_scale = max(0.1, v)
        self.update()

    def reset_view(self):
        self._az = math.radians(225)
        self._el = math.radians(25)
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    # ------------------------------------------------------------------
    # Projection

    def _project(self, x: float, y: float, z: float) -> QPointF:
        xc = x - self._cx
        yc = y - self._cy
        zs = z * self._z_scale

        # Rotate around Z axis (azimuth)
        xa = xc * math.cos(self._az) - yc * math.sin(self._az)
        ya = xc * math.sin(self._az) + yc * math.cos(self._az)

        # Rotate around X axis (elevation)
        yb = ya * math.cos(self._el) - zs * math.sin(self._el)
        zb = ya * math.sin(self._el) + zs * math.cos(self._el)

        scale = min(self.width(), self.height()) * 0.7 / self._extent * self._zoom
        sx = self.width() / 2 + self._pan.x() + xa * scale
        sy = self.height() / 2 + self._pan.y() - zb * scale
        return QPointF(sx, sy)

    # ------------------------------------------------------------------
    # Color by Z depth

    def _depth_color(self, z: float, alpha: int = 255) -> QColor:
        if self._z_min >= 0 or z >= 0:
            return QColor(80, 200, 80, alpha)
        t = z / self._z_min  # 0 = surface, 1 = deepest
        if t < 0.5:
            t2 = t * 2
            r, g, b = round(t2 * 0xFF), round(0xCC + t2 * 51), round(0xFF * (1 - t2))
        else:
            t2 = (t - 0.5) * 2
            r, g, b = 0xFF, round(0xFF * (1 - t2)), 0
        return QColor(r, g, b, alpha)

    # ------------------------------------------------------------------
    # Paint

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(_BG))

        self._draw_depth_planes(painter)
        self._draw_moves(painter)
        self._draw_z_legend(painter)
        self._draw_hint(painter)

    def _draw_depth_planes(self, painter: QPainter):
        """Work-area outline at Z=0 plus semi-transparent planes at each cut depth."""

        def _rect_at_z(z: float, color: QColor, style=Qt.PenStyle.SolidLine, width=1):
            corners = [
                (0, 0, z), (MACHINE_W, 0, z),
                (MACHINE_W, MACHINE_H, z), (0, MACHINE_H, z),
            ]
            pts = [self._project(x, y, zz) for x, y, zz in corners]
            painter.setPen(QPen(color, width, style))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(4):
                painter.drawLine(pts[i], pts[(i + 1) % 4])

        # Surface plane (Z=0) — dashed white
        _rect_at_z(0.0, QColor(180, 180, 200, 200), Qt.PenStyle.DashLine, 1)

        # Depth planes — colored, semi-transparent
        for z in self._distinct_z:
            col = self._depth_color(z, alpha=160)
            _rect_at_z(z, col, Qt.PenStyle.DashDotLine, 1)

        # Vertical corner edges connecting surface to deepest cut
        if self._distinct_z:
            z_deep = min(self._distinct_z)
            edge_color = QColor(100, 100, 140, 100)
            for cx, cy in [(0, 0), (MACHINE_W, 0), (MACHINE_W, MACHINE_H), (0, MACHINE_H)]:
                painter.setPen(QPen(edge_color, 1))
                painter.drawLine(
                    self._project(cx, cy, 0.0),
                    self._project(cx, cy, z_deep),
                )

    def _draw_moves(self, painter: QPainter):
        travel_pen = QPen(QColor(90, 90, 110, 100), 1)
        for move in self._moves:
            if not move.xy_move:
                continue
            if not move.pen_down:
                if not self._show_travel:
                    continue
                painter.setPen(travel_pen)
            else:
                painter.setPen(QPen(self._depth_color(move.to_pos.z), 1.5))
            painter.drawLine(
                self._project(move.from_pos.x, move.from_pos.y, move.from_pos.z),
                self._project(move.to_pos.x, move.to_pos.y, move.to_pos.z),
            )

    def _draw_z_legend(self, painter: QPainter):
        """Vertical color-bar legend with tick marks at each distinct Z depth."""
        if not self._distinct_z or self._z_min >= 0:
            return

        font = QFont("Monospace", 8)
        painter.setFont(font)

        bar_x, bar_y = 14, 14
        bar_w, bar_h = 14, min(180, self.height() - 60)

        # Gradient bar
        for row in range(bar_h):
            t = row / bar_h
            z = t * self._z_min
            painter.setPen(QPen(self._depth_color(z), 1))
            painter.drawLine(bar_x, bar_y + row, bar_x + bar_w, bar_y + row)

        # Border
        painter.setPen(QPen(QColor(140, 140, 170), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(bar_x, bar_y, bar_w, bar_h)

        # Top label Z=0
        painter.setPen(QPen(QColor(200, 200, 210), 1))
        painter.drawText(QPointF(bar_x + bar_w + 6, bar_y + 4), "0.00 mm")

        # Tick marks at each distinct depth
        for z in self._distinct_z:
            t = z / self._z_min
            ty = bar_y + round(t * bar_h)
            col = self._depth_color(z)
            painter.setPen(QPen(col, 1))
            painter.drawLine(bar_x + bar_w, ty, bar_x + bar_w + 5, ty)
            painter.drawText(QPointF(bar_x + bar_w + 6, ty + 4), f"{z:.3f} mm")

        # Bottom label
        painter.setPen(QPen(QColor(180, 180, 200), 1))
        painter.drawText(
            QPointF(bar_x, bar_y + bar_h + 14),
            f"min: {self._z_min:.3f} mm",
        )

    def _draw_hint(self, painter: QPainter):
        painter.setFont(QFont("Sans", 8))
        painter.setPen(QPen(QColor(100, 100, 120), 1))
        painter.drawText(
            QRectF(0, self.height() - 20, self.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            "Drag: rotate  |  Ctrl+drag: pan  |  Scroll: zoom",
        )

    # ------------------------------------------------------------------
    # Mouse / wheel

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position()
            self._drag_az0 = self._az
            self._drag_el0 = self._el
            self._drag_pan0 = QPointF(self._pan)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start is None:
            return
        dx = event.position().x() - self._drag_start.x()
        dy = event.position().y() - self._drag_start.y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._pan = QPointF(self._drag_pan0.x() + dx, self._drag_pan0.y() + dy)
        else:
            self._az = self._drag_az0 + math.radians(dx * 0.5)
            self._el = max(
                math.radians(-89),
                min(math.radians(89), self._drag_el0 - math.radians(dy * 0.5)),
            )
        self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent):
        self._drag_start = None

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self._zoom = max(0.05, min(30.0, self._zoom * factor))
        self.update()


class Preview3DDialog(QDialog):
    def __init__(self, moves: list[Move], parent=None):
        super().__init__(parent)
        self.setWindowTitle("3D Preview")
        self.resize(860, 640)
        self._setup_ui(moves)

    def _setup_ui(self, moves: list[Move]):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._view = _View3DWidget(moves, self)
        layout.addWidget(self._view, 1)

        ctrl = QHBoxLayout()

        chk_travel = QCheckBox("Show travel moves")
        chk_travel.setChecked(False)
        chk_travel.toggled.connect(self._view.set_show_travel)
        ctrl.addWidget(chk_travel)

        ctrl.addSpacing(16)
        ctrl.addWidget(QLabel("Z-Skalierung:"))
        self._spin_z = QDoubleSpinBox()
        self._spin_z.setRange(1, 100)
        self._spin_z.setDecimals(1)
        self._spin_z.setSuffix("×")
        self._spin_z.setValue(10.0)
        self._spin_z.setToolTip(
            "Vertical exaggeration of Z depth\n"
            "10× → 1 mm depth appears as 10 mm"
        )
        self._spin_z.valueChanged.connect(self._view.set_z_scale)
        ctrl.addWidget(self._spin_z)

        ctrl.addStretch()

        # Preset view buttons
        for label, az, el in [
            ("Top", 225, 89),
            ("Front", 270, 5),
            ("ISO", 225, 25),
        ]:
            btn = QPushButton(label)
            az_r, el_r = math.radians(az), math.radians(el)
            btn.clicked.connect(
                lambda _chk, a=az_r, e=el_r: self._set_view(a, e)
            )
            ctrl.addWidget(btn)

        btn_reset = QPushButton("Reset view")
        btn_reset.clicked.connect(self._view.reset_view)
        ctrl.addWidget(btn_reset)

        layout.addLayout(ctrl)

    def _set_view(self, az: float, el: float):
        self._view._az = az
        self._view._el = el
        self._view._zoom = 1.0
        self._view._pan = QPointF(0, 0)
        self._view.update()
