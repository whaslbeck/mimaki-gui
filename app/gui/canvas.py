from __future__ import annotations
import math
from typing import Optional

from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QRectF, QPoint, QTimer
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QPen, QFont, QMouseEvent, QWheelEvent,
    QContextMenuEvent, QAction, QTransform,
)
from PyQt6.QtWidgets import QWidget, QToolTip, QMenu

from app.config import UIConfig
from app.model.project import Project, MACHINE_W, MACHINE_H
from app.model.gcode_object import GcodeObject
from app.model.types import Move, Transform
from app.model.zone import ForbiddenZone

MODE_SELECT = "select"
MODE_DRAW_ZONE = "draw_zone"

_ROT_HANDLE_OFFSET_MM = 8.0   # how far above bbox top the rotation handle sits
_ROT_HANDLE_PX = 7             # pixel radius for hit testing


class WorkCanvas(QWidget):
    object_selected = pyqtSignal(str)              # id (empty = deselect)
    drag_committed = pyqtSignal(str, object, object)  # id, old_t, new_t
    object_moved = pyqtSignal(str, float, float)   # id, new_offset_x, new_offset_y
    cursor_moved = pyqtSignal(float, float)
    zone_added = pyqtSignal(str)                   # zone id
    zone_delete_requested = pyqtSignal(str)        # zone id
    zone_rename_requested = pyqtSignal(str)        # zone id
    zone_edit_requested = pyqtSignal(str)          # zone id
    zone_changed = pyqtSignal(str, object, object) # zone_id, old_state_dict, new_state_dict
    context_action = pyqtSignal(str, str)          # action_name, obj_id
    animation_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: Optional[Project] = None
        self._ui: UIConfig = UIConfig()
        self._zoom: float = 1.0
        self._origin = QPointF(30, 30)
        self._selected_id: str = ""
        self._mode: str = MODE_SELECT

        # pan
        self._pan_last: Optional[QPointF] = None

        # object drag
        self._drag_obj_id: str = ""
        self._drag_world_start: Optional[tuple[float, float]] = None
        self._drag_offset_start: Optional[tuple[float, float]] = None
        self._drag_old_transform: Optional[Transform] = None

        # rotation drag
        self._rot_dragging: bool = False
        self._rot_start_angle: float = 0.0
        self._rot_orig_deg: float = 0.0

        # zone draw
        self._zone_start: Optional[tuple[float, float]] = None
        self._zone_current: Optional[tuple[float, float]] = None

        # zone selection + drag
        self._selected_zone_id: str = ""
        self._zone_drag_mode: str = ""  # "move", "resize_bl/br/tl/tr"
        self._zone_drag_id: str = ""
        self._zone_drag_start_world: Optional[tuple[float, float]] = None
        self._zone_drag_orig: Optional[dict] = None

        # pivot drag
        self._pivot_dragging: bool = False

        # send-from preview marker (animated)
        self._preview_pos: Optional[tuple[float, float]] = None
        self._preview_phase: int = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(420)
        self._preview_timer.timeout.connect(self._on_preview_tick)

        # QPainterPath render cache: (obj_id, cache_version) → (travel_path, {z: cut_path})
        self._render_cache: dict = {}

        # depth coloring
        self._depth_color_mode: bool = False

        # Z-layer filter: frozenset of allowed depths (round to 2dp); None = show all
        self._z_filter_set: Optional[frozenset] = None

        # live machining position overlay (x, y, z) in world mm; None = hidden
        self._machining_pos: Optional[tuple[float, float, float]] = None

        # live jog position overlay (x, y) in machine mm; None = hidden
        self._jog_pos: Optional[tuple[float, float]] = None

        # dry-run animation
        self._anim_moves: list[Move] = []
        self._anim_index: int = 0
        self._anim_speed: int = 1
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(30)
        self._anim_timer.timeout.connect(self._on_anim_tick)

        self.setMouseTracking(True)
        self.setMinimumSize(400, 300)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # ------------------------------------------------------------------
    # Public API

    def set_project(self, project: Project):
        self._project = project
        self._render_cache.clear()
        self.fit_view()

    def set_ui_config(self, ui: UIConfig):
        self._ui = ui
        self.update()

    def set_selected(self, obj_id: str):
        self._selected_id = obj_id
        self._selected_zone_id = ""
        self.update()

    def set_mode(self, mode: str):
        self._mode = mode
        self.setCursor(
            Qt.CursorShape.CrossCursor if mode == MODE_DRAW_ZONE
            else Qt.CursorShape.ArrowCursor
        )
        self._zone_start = None
        self._zone_current = None
        self._selected_zone_id = ""
        self._zone_drag_mode = ""

    def fit_view(self):
        margin = 40
        aw = max(1, self.width() - 2 * margin)
        ah = max(1, self.height() - 2 * margin)
        self._zoom = min(aw / MACHINE_W, ah / MACHINE_H)
        cw = MACHINE_W * self._zoom
        ch = MACHINE_H * self._zoom
        self._origin = QPointF(
            (self.width() - cw) / 2,
            (self.height() + ch) / 2,
        )
        self.update()

    def zoom_step(self, factor: float):
        cx, cy = self.width() / 2, self.height() / 2
        wx, wy = self._s2w(cx, cy)
        self._zoom *= factor
        self._origin = QPointF(cx - wx * self._zoom, cy + wy * self._zoom)
        self.update()

    def set_preview_pos(self, wx: float, wy: float):
        self._preview_pos = (wx, wy)
        if not self._preview_timer.isActive():
            self._preview_timer.start()
        self.update()

    def clear_preview_pos(self):
        self._preview_pos = None
        self._preview_phase = 0
        self._preview_timer.stop()
        self.update()

    def _on_preview_tick(self):
        self._preview_phase = (self._preview_phase + 1) % 2
        self.update()

    def set_depth_color_mode(self, enabled: bool):
        self._depth_color_mode = enabled
        self.update()

    def set_z_filter(self, depths: Optional[frozenset]):
        """Show only cutting moves whose rounded depth is in depths. None = show all."""
        self._z_filter_set = depths
        self.update()

    @property
    def z_filter(self) -> Optional[frozenset]:
        """Current Z-layer filter (None = all depths allowed)."""
        return self._z_filter_set

    def set_machining_pos(self, pos: Optional[tuple[float, float, float]]):
        """Set live machining position (x, y, z) in world mm. None clears overlay."""
        self._machining_pos = pos
        self.update()

    def set_jog_pos(self, pos: Optional[tuple[float, float]]):
        """Set live jog position (x, y) in machine mm. None clears overlay."""
        self._jog_pos = pos
        self.update()

    def start_animation(self, moves: list[Move], speed: int = 1):
        self.stop_animation()
        self._anim_moves = list(moves)
        self._anim_index = 0
        self._anim_speed = max(1, speed)
        self._anim_timer.start()
        self.update()

    def stop_animation(self):
        self._anim_timer.stop()
        self._anim_moves = []
        self._anim_index = 0
        self.update()

    def is_animating(self) -> bool:
        return self._anim_timer.isActive()

    def _on_anim_tick(self):
        if not self._anim_moves:
            self._anim_timer.stop()
            return
        self._anim_index = min(self._anim_index + self._anim_speed, len(self._anim_moves) - 1)
        if self._anim_index >= len(self._anim_moves) - 1:
            self._anim_timer.stop()
            self.animation_finished.emit()
        self.update()

    # ------------------------------------------------------------------
    # Coordinate helpers

    def _w2s(self, wx: float, wy: float) -> QPointF:
        return QPointF(
            self._origin.x() + wx * self._zoom,
            self._origin.y() - wy * self._zoom,
        )

    def _s2w(self, sx: float, sy: float) -> tuple[float, float]:
        return (
            (sx - self._origin.x()) / self._zoom,
            (self._origin.y() - sy) / self._zoom,
        )

    def _snap(self, wx: float, wy: float, force_free: bool = False) -> tuple[float, float]:
        if force_free or self._project is None or not self._project.grid.visible:
            return wx, wy
        g = self._project.grid
        if g.spacing_mm <= 0:
            return wx, wy
        sx = round((wx - g.origin_x) / g.spacing_mm) * g.spacing_mm + g.origin_x
        sy = round((wy - g.origin_y) / g.spacing_mm) * g.spacing_mm + g.origin_y
        return sx, sy

    # ------------------------------------------------------------------
    # Rotation handle helpers

    def _rot_handle_world(self, obj: GcodeObject) -> tuple[float, float]:
        bb = obj.bounding_box
        return bb.center_x, bb.max_y + _ROT_HANDLE_OFFSET_MM

    def _rot_handle_screen(self, obj: GcodeObject) -> QPointF:
        hx, hy = self._rot_handle_world(obj)
        return self._w2s(hx, hy)

    def _rot_handle_hit(self, obj: GcodeObject, sx: float, sy: float) -> bool:
        sp = self._rot_handle_screen(obj)
        return math.hypot(sx - sp.x(), sy - sp.y()) <= _ROT_HANDLE_PX + 2

    # ------------------------------------------------------------------
    # Paint

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self._ui.canvas_bg_color))

        if self._project is None:
            return

        self._draw_work_area(painter)
        self._draw_grid(painter)
        self._draw_wcs_marker(painter)
        self._draw_ref_points(painter)
        self._draw_zones(painter)

        for obj in self._project.visible_objects():
            self._draw_object(painter, obj)

        self._draw_saved_points(painter)
        self._draw_preview_marker(painter)
        if self._anim_moves:
            self._draw_animation_cursor(painter)
        self._draw_jog_cursor(painter)
        self._draw_machining_cursor(painter)

        # Zone preview while drawing
        if self._zone_start and self._zone_current:
            x0, y0 = self._zone_start
            x1, y1 = self._zone_current
            tl = self._w2s(min(x0, x1), max(y0, y1))
            br = self._w2s(max(x0, x1), min(y0, y1))
            rect = QRectF(tl, br)
            c = QColor(self._ui.zone_color)
            c.setAlpha(60)
            painter.setBrush(c)
            painter.setPen(QPen(QColor(self._ui.zone_color), 1, Qt.PenStyle.DashLine))
            painter.drawRect(rect)

    def _draw_preview_marker(self, painter: QPainter):
        if self._preview_pos is None:
            return
        sp = self._w2s(self._preview_pos[0], self._preview_pos[1])
        outer_r = 14 if self._preview_phase == 0 else 9
        painter.setPen(QPen(QColor("#00CC44"), 2))
        painter.setBrush(QColor(0, 204, 68, 60))
        painter.drawEllipse(sp, outer_r, outer_r)
        painter.setBrush(QColor("#00CC44"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(sp, 4, 4)

    def _draw_work_area(self, painter: QPainter):
        tl = self._w2s(0, MACHINE_H)
        br = self._w2s(MACHINE_W, 0)
        rect = QRectF(tl, br)
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#444444"), 2))
        painter.drawRect(rect)

    def _draw_wcs_marker(self, painter: QPainter):
        if self._project is None:
            return
        ox = self._project.work_offset_x
        oy = self._project.work_offset_y
        sp = self._w2s(0, 0)
        arm = 10
        painter.setPen(QPen(QColor("#FF8800"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(sp.x() - arm, sp.y()), QPointF(sp.x() + arm, sp.y()))
        painter.drawLine(QPointF(sp.x(), sp.y() - arm), QPointF(sp.x(), sp.y() + arm))
        if ox != 0.0 or oy != 0.0:
            painter.setFont(QFont("Sans", 7))
            painter.setPen(QPen(QColor("#FF8800"), 1))
            painter.drawText(
                QPointF(sp.x() + arm + 2, sp.y() - 3),
                f"WCS +{ox:.2f} / +{oy:.2f}",
            )

    def _draw_ref_points(self, painter: QPainter):
        if self._project is None or not self._project.ref_points:
            return
        pts = self._project.ref_points
        col = QColor("#AA00CC")

        # Working-area rectangle when exactly 2 points are defined
        if len(pts) == 2:
            x1, y1 = pts[0].x, pts[0].y
            x2, y2 = pts[1].x, pts[1].y
            tl = self._w2s(min(x1, x2), max(y1, y2))
            br = self._w2s(max(x1, x2), min(y1, y2))
            rect = QRectF(tl, br)
            fill = QColor(160, 160, 160, 45)
            painter.setBrush(fill)
            border = QColor("#AA00CC")
            border.setAlpha(140)
            pen = QPen(border, 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(rect)
            painter.setPen(QPen(col, 1))
            painter.setFont(QFont("Sans", 8))
            painter.drawText(tl + QPointF(4, 12), "Working area")

        # Individual markers
        painter.setFont(QFont("Sans", 8, QFont.Weight.Bold))
        r = 5
        arm = 9
        for i, rp in enumerate(pts):
            sp = self._w2s(rp.x, rp.y)
            # Cross
            painter.setPen(QPen(col, 1.5))
            painter.drawLine(QPointF(sp.x() - arm, sp.y()), QPointF(sp.x() + arm, sp.y()))
            painter.drawLine(QPointF(sp.x(), sp.y() - arm), QPointF(sp.x(), sp.y() + arm))
            # Circle
            painter.setBrush(QColor(170, 0, 204, 200))
            painter.drawEllipse(sp, r, r)
            # Label
            painter.setPen(QPen(col, 1))
            tag = f"P{i+1}" + (f" {rp.label}" if rp.label else "")
            coord = f"({rp.x:.1f} / {rp.y:.1f})"
            painter.drawText(sp + QPointF(arm + 3, -3), tag)
            painter.setPen(QPen(QColor("#888888"), 1))
            painter.setFont(QFont("Sans", 7))
            painter.drawText(sp + QPointF(arm + 3, 9), coord)
            painter.setFont(QFont("Sans", 8, QFont.Weight.Bold))

    def _draw_grid(self, painter: QPainter):
        if self._project is None or not self._project.grid.visible:
            return
        g = self._project.grid
        if g.spacing_mm <= 0:
            return
        painter.setPen(QPen(QColor("#BBBBBB"), 1))
        x = g.origin_x
        while x <= MACHINE_W + 0.001:
            painter.drawLine(self._w2s(x, 0), self._w2s(x, MACHINE_H))
            x += g.spacing_mm
        y = g.origin_y
        while y <= MACHINE_H + 0.001:
            painter.drawLine(self._w2s(0, y), self._w2s(MACHINE_W, y))
            y += g.spacing_mm

    def _draw_zones(self, painter: QPainter):
        if self._project is None:
            return
        for zone in self._project.forbidden_zones:
            tl = self._w2s(zone.x, zone.y + zone.height)
            br = self._w2s(zone.x + zone.width, zone.y)
            rect = QRectF(tl, br)
            is_sel_zone = zone.id == self._selected_zone_id
            c = QColor(self._ui.zone_color)
            c.setAlpha(80)
            painter.setBrush(c)
            pen_w = 2 if is_sel_zone else 1
            painter.setPen(QPen(QColor(self._ui.zone_color), pen_w))
            painter.drawRect(rect)
            if is_sel_zone:
                painter.setPen(QPen(QColor("#FFCC00"), 2))
                painter.setBrush(QColor("#FFCC00"))
                for pt in [tl, QPointF(br.x(), tl.y()), br, QPointF(tl.x(), br.y())]:
                    painter.drawEllipse(pt, 4, 4)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            if zone.label:
                painter.setPen(QPen(QColor(self._ui.zone_color), 1))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, zone.label)

    def _depth_to_color(self, z: float, z_min: float) -> QColor:
        if z >= 0 or z_min >= 0:
            return QColor(self._ui.machining_color)
        t = z / z_min  # 0=surface, 1=deepest
        if t < 0.5:
            t2 = t * 2
            r = round(t2 * 0xFF)
            g = round(0xCC + t2 * (0xFF - 0xCC))
            b = round(0xFF - t2 * 0xFF)
        else:
            t2 = (t - 0.5) * 2
            r = 0xFF
            g = round(0xFF - t2 * 0xFF)
            b = 0
        return QColor(r, g, b)

    def _draw_animation_cursor(self, painter: QPainter):
        if not self._anim_moves or self._anim_index >= len(self._anim_moves):
            return
        move = self._anim_moves[self._anim_index]
        sp = self._w2s(move.to_pos.x, move.to_pos.y)
        is_cutting = move.pen_down
        color = QColor("#DD0000") if is_cutting else QColor("#0055DD")
        painter.setPen(QPen(color, 2))
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 140))
        r = 7
        painter.drawEllipse(sp, r, r)
        painter.setPen(QPen(color, 1))
        painter.drawLine(QPointF(sp.x() - r - 3, sp.y()), QPointF(sp.x() + r + 3, sp.y()))
        painter.drawLine(QPointF(sp.x(), sp.y() - r - 3), QPointF(sp.x(), sp.y() + r + 3))

    def _draw_machining_cursor(self, painter: QPainter):
        if self._machining_pos is None:
            return
        x, y, z = self._machining_pos
        sp = self._w2s(x, y)

        arm = 24          # crosshair arm length in screen pixels
        gap = 5           # gap around center dot
        color = QColor("#FFD700")   # gold — distinct from animation cursor colours

        # Crosshair lines (with gap around centre)
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(sp.x() - arm, sp.y()), QPointF(sp.x() - gap, sp.y()))
        painter.drawLine(QPointF(sp.x() + gap, sp.y()), QPointF(sp.x() + arm, sp.y()))
        painter.drawLine(QPointF(sp.x(), sp.y() - arm), QPointF(sp.x(), sp.y() - gap))
        painter.drawLine(QPointF(sp.x(), sp.y() + gap), QPointF(sp.x(), sp.y() + arm))

        # Centre circle
        painter.drawEllipse(sp, gap, gap)

        # Coordinate label
        label = f"X {x:+.2f}  Y {y:+.2f}  Z {z:+.2f}"
        font = QFont("Monospace", 9)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label)
        th = fm.height()
        pad = 4

        # Default: right of crosshair; flip left if near right edge
        tx = sp.x() + arm + pad
        if tx + tw + pad > self.width():
            tx = sp.x() - arm - pad - tw
        ty = sp.y() + fm.ascent() / 2

        # Semi-transparent background pill
        bg = QRectF(tx - pad, ty - fm.ascent() - 1, tw + 2 * pad, th + 2)
        painter.setBrush(QColor(0, 0, 0, 175))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bg, 3, 3)

        # Text
        painter.setPen(color)
        painter.drawText(QPointF(tx, ty), label)

    def _draw_jog_cursor(self, painter: QPainter):
        if self._jog_pos is None:
            return
        x, y = self._jog_pos
        sp = self._w2s(x, y)

        arm = 20
        gap = 4
        color = QColor("#00BFFF")   # deep-sky-blue — distinct from machining gold

        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(sp.x() - arm, sp.y()), QPointF(sp.x() - gap, sp.y()))
        painter.drawLine(QPointF(sp.x() + gap, sp.y()), QPointF(sp.x() + arm, sp.y()))
        painter.drawLine(QPointF(sp.x(), sp.y() - arm), QPointF(sp.x(), sp.y() - gap))
        painter.drawLine(QPointF(sp.x(), sp.y() + gap), QPointF(sp.x(), sp.y() + arm))
        painter.drawEllipse(sp, gap, gap)

        label = f"X {x:+.2f}  Y {y:+.2f}"
        font = QFont("Monospace", 9)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label)
        th = fm.height()
        pad = 4
        tx = sp.x() + arm + pad
        if tx + tw + pad > self.width():
            tx = sp.x() - arm - pad - tw
        ty = sp.y() + fm.ascent() / 2
        bg = QRectF(tx - pad, ty - fm.ascent() - 1, tw + 2 * pad, th + 2)
        painter.setBrush(QColor(0, 0, 0, 175))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bg, 3, 3)
        painter.setPen(color)
        painter.drawText(QPointF(tx, ty), label)

    def _draw_saved_points(self, painter: QPainter):
        if self._project is None or not self._project.saved_points:
            return
        col = QColor("#0077CC")
        r = 5
        painter.setFont(QFont("Sans", 8, QFont.Weight.Bold))
        for i, pt in enumerate(self._project.saved_points):
            sp = self._w2s(pt.x, pt.y)
            # Pin: filled circle with a short stem
            painter.setPen(QPen(col, 1.5))
            painter.setBrush(QColor(0, 119, 204, 200))
            painter.drawEllipse(sp, r, r)
            # Index label inside circle
            painter.setPen(QPen(QColor("white"), 1))
            painter.drawText(
                QRectF(sp.x() - r, sp.y() - r, r * 2, r * 2),
                int(Qt.AlignmentFlag.AlignCenter),
                str(i + 1),
            )
            # Coordinate caption
            painter.setPen(QPen(col, 1))
            painter.setFont(QFont("Sans", 7))
            cap = (pt.label + "  " if pt.label else "") + f"({pt.x:.1f} / {pt.y:.1f})"
            painter.drawText(sp + QPointF(r + 3, 3), cap)
            painter.setFont(QFont("Sans", 8, QFont.Weight.Bold))

    def _get_obj_paths(
        self, obj: GcodeObject
    ) -> tuple[QPainterPath, dict[float, QPainterPath], list[tuple[float, float]]]:
        """World-coordinate QPainterPaths cached by (obj_id, cache_version).

        Returns (travel_path, {rounded_z: cut_path}, comment_midpoints).
        Callers apply the world-to-screen QTransform and cosmetic pens so
        pan/zoom redraws cost only one drawPath() each.
        """
        key = (obj.id, obj._cache_version)
        cached = self._render_cache.get(key)
        if cached is not None:
            return cached

        travel: QPainterPath = QPainterPath()
        by_z: dict[float, QPainterPath] = {}
        comment_pts: list[tuple[float, float]] = []

        for move in obj.computed_moves:
            if not move.xy_move:
                continue
            x0, y0 = move.from_pos.x, move.from_pos.y
            x1, y1 = move.to_pos.x, move.to_pos.y
            if move.pen_down:
                z = round(move.to_pos.z, 2)
                if z not in by_z:
                    by_z[z] = QPainterPath()
                p = by_z[z]
                p.moveTo(x0, y0)
                p.lineTo(x1, y1)
            else:
                travel.moveTo(x0, y0)
                travel.lineTo(x1, y1)
            if move.comment:
                comment_pts.append(((x0 + x1) / 2, (y0 + y1) / 2))

        result = (travel, by_z, comment_pts)
        self._render_cache[key] = result
        return result

    def _draw_object(self, painter: QPainter, obj: GcodeObject):
        is_sel = obj.id == self._selected_id

        # World-to-screen transform: sx = ox + x*zoom;  sy = oy - y*zoom
        wts = QTransform()
        wts.translate(self._origin.x(), self._origin.y())
        wts.scale(self._zoom, -self._zoom)

        travel_path, z_paths, comment_pts = self._get_obj_paths(obj)

        z_min = min(z_paths.keys()) if (self._depth_color_mode and z_paths) else 0.0

        painter.save()
        painter.setTransform(wts, combine=False)

        # Cutting paths — one drawPath() per distinct Z depth
        for z, path in z_paths.items():
            if self._z_filter_set is not None and z not in self._z_filter_set:
                continue
            color = (
                self._depth_to_color(z, z_min)
                if self._depth_color_mode
                else QColor(self._ui.machining_color)
            )
            pen = QPen(color, 1.5)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPath(path)

        # Travel path
        tpen = QPen(QColor(self._ui.travel_color), 1)
        tpen.setCosmetic(True)
        painter.setPen(tpen)
        painter.drawPath(travel_path)

        painter.restore()

        # Comment markers — small "i" badge at each commented move's midpoint
        if comment_pts:
            painter.setFont(QFont("Sans", 7, QFont.Weight.Bold))
            r = 5
            for wx, wy in comment_pts:
                sp = self._w2s(wx, wy)
                painter.setPen(QPen(QColor("#2255BB"), 1))
                painter.setBrush(QColor(34, 85, 187, 210))
                painter.drawEllipse(sp, r, r)
                painter.setPen(QPen(QColor("white"), 1))
                painter.drawText(
                    QRectF(sp.x() - r, sp.y() - r, r * 2, r * 2),
                    int(Qt.AlignmentFlag.AlignCenter),
                    "i",
                )

        # Bounding box
        bb = obj.bounding_box
        tl = self._w2s(bb.min_x, bb.max_y)
        br = self._w2s(bb.max_x, bb.min_y)
        rect = QRectF(tl, br)

        out_of_bounds = (
            bb.min_x < 0 or bb.min_y < 0 or
            bb.max_x > MACHINE_W or bb.max_y > MACHINE_H
        )
        collides = any(
            z.overlaps_rect(bb.min_x, bb.min_y, bb.width, bb.height)
            for z in self._project.forbidden_zones  # type: ignore[union-attr]
        )

        # Semi-transparent red fill when outside work area (visible regardless of selection)
        if out_of_bounds:
            painter.setBrush(QColor(220, 0, 0, 35))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(rect)

        if is_sel:
            bbox_pen = QPen(QColor("#FFCC00"), 2, Qt.PenStyle.DashLine)
        elif out_of_bounds:
            bbox_pen = QPen(QColor("#DD0000"), 2, Qt.PenStyle.DashLine)
        elif collides:
            bbox_pen = QPen(QColor("#FF6600"), 2, Qt.PenStyle.DashLine)
        else:
            bbox_pen = QPen(QColor(self._ui.bbox_color), 1, Qt.PenStyle.DashLine)
        painter.setPen(bbox_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Label
        if obj.label:
            painter.setPen(QPen(QColor("#333333"), 1))
            painter.setFont(QFont("Sans", 8))
            painter.drawText(tl + QPointF(3, 12), obj.label)

        # Out-of-bounds warning text
        if out_of_bounds:
            painter.setFont(QFont("Sans", 8, QFont.Weight.Bold))
            painter.setPen(QPen(QColor("#DD0000"), 1))
            painter.drawText(tl + QPointF(3, 26), "⚠ outside work area")

        # Placement warning indicator
        if obj.placement_warning:
            painter.setFont(QFont("Sans", 10, QFont.Weight.Bold))
            painter.setPen(QPen(QColor("#FF4400"), 1))
            painter.drawText(tl + QPointF(3, 40 if out_of_bounds else 26), "⚠ could not be placed")

        # Pivot cross — world pos of pivot = pivot_local + offset
        pv = self._w2s(
            obj.transform.pivot_x + obj.transform.offset_x,
            obj.transform.pivot_y + obj.transform.offset_y,
        )
        sz = 6
        painter.setPen(QPen(QColor(self._ui.pivot_color), 2))
        painter.drawLine(QPointF(pv.x()-sz, pv.y()), QPointF(pv.x()+sz, pv.y()))
        painter.drawLine(QPointF(pv.x(), pv.y()-sz), QPointF(pv.x(), pv.y()+sz))

        # Rotation handle (only for selected object)
        if is_sel:
            hp = self._rot_handle_screen(obj)
            painter.setPen(QPen(QColor("#FF8800"), 1))
            painter.setBrush(QColor("#FF8800"))
            painter.drawEllipse(hp, _ROT_HANDLE_PX, _ROT_HANDLE_PX)
            # Line from bbox top-center to handle
            top_center = self._w2s(bb.center_x, bb.max_y)
            painter.setPen(QPen(QColor("#FF8800"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(top_center, hp)

    # ------------------------------------------------------------------
    # Mouse / wheel

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_view()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.12 if delta > 0 else 1 / 1.12
        mx, my = event.position().x(), event.position().y()
        wx, wy = self._s2w(mx, my)
        self._zoom *= factor
        self._origin = QPointF(mx - wx * self._zoom, my + wy * self._zoom)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()
        sx, sy = pos.x(), pos.y()
        wx, wy = self._s2w(sx, sy)
        free = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = pos

        elif event.button() == Qt.MouseButton.LeftButton:
            if self._mode == MODE_DRAW_ZONE:
                swx, swy = self._snap(wx, wy, force_free=free)
                self._zone_start = (swx, swy)
                self._zone_current = (swx, swy)

            else:
                # Check rotation handle first (only for selected object)
                if self._selected_id and self._project:
                    sel = self._project.object_by_id(self._selected_id)
                    if sel and self._rot_handle_hit(sel, sx, sy):
                        self._rot_dragging = True
                        pv = (sel.transform.pivot_x + sel.transform.offset_x,
                              sel.transform.pivot_y + sel.transform.offset_y)
                        self._rot_start_angle = math.atan2(wy - pv[1], wx - pv[0])
                        self._rot_orig_deg = sel.transform.rotation_deg
                        self._drag_old_transform = sel.transform.copy()
                        return

                    # Check pivot handle (only for selected object)
                    if sel:
                        pv_sp = self._w2s(
                            sel.transform.pivot_x + sel.transform.offset_x,
                            sel.transform.pivot_y + sel.transform.offset_y,
                        )
                        if math.hypot(sx - pv_sp.x(), sy - pv_sp.y()) <= 8:
                            self._pivot_dragging = True
                            self._drag_old_transform = sel.transform.copy()
                            return

                hit = self._hit_test(wx, wy)
                if hit:
                    self._selected_id = hit.id
                    self._selected_zone_id = ""
                    self._zone_drag_mode = ""
                    swx, swy = self._snap(wx, wy, force_free=free)
                    self._drag_obj_id = hit.id
                    self._drag_world_start = (swx, swy)
                    self._drag_offset_start = (
                        hit.transform.offset_x,
                        hit.transform.offset_y,
                    )
                    self._drag_old_transform = hit.transform.copy()
                    self.object_selected.emit(hit.id)
                else:
                    self._selected_id = ""
                    self._drag_obj_id = ""
                    self.object_selected.emit("")

                    # Check zone corner resize (only for already-selected zone)
                    if self._selected_zone_id and self._project:
                        sel_zone = next(
                            (z for z in self._project.forbidden_zones
                             if z.id == self._selected_zone_id), None
                        )
                        if sel_zone:
                            corner = self._zone_corner_hit(sel_zone, sx, sy)
                            if corner:
                                self._zone_drag_mode = f"resize_{corner}"
                                self._zone_drag_id = self._selected_zone_id
                                swx, swy = self._snap(wx, wy, force_free=free)
                                self._zone_drag_start_world = (swx, swy)
                                self._zone_drag_orig = {
                                    "x": sel_zone.x, "y": sel_zone.y,
                                    "width": sel_zone.width, "height": sel_zone.height,
                                }
                                return

                    # Check zone body (start move drag)
                    zone = self._zone_hit_test(wx, wy)
                    if zone:
                        self._selected_zone_id = zone.id
                        self._zone_drag_mode = "move"
                        self._zone_drag_id = zone.id
                        swx, swy = self._snap(wx, wy, force_free=free)
                        self._zone_drag_start_world = (swx, swy)
                        self._zone_drag_orig = {
                            "x": zone.x, "y": zone.y,
                            "width": zone.width, "height": zone.height,
                        }
                    else:
                        self._selected_zone_id = ""
                        self._zone_drag_mode = ""
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        sx, sy = pos.x(), pos.y()
        wx, wy = self._s2w(sx, sy)
        free = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self.cursor_moved.emit(wx, wy)

        self._update_tooltip(sx, sy)

        if self._pan_last is not None:
            dx = sx - self._pan_last.x()
            dy = sy - self._pan_last.y()
            self._origin += QPointF(dx, dy)
            self._pan_last = pos
            self.update()

        elif self._rot_dragging and self._selected_id and self._project:
            obj = self._project.object_by_id(self._selected_id)
            if obj:
                pv = (obj.transform.pivot_x + obj.transform.offset_x,
                      obj.transform.pivot_y + obj.transform.offset_y)
                cur_angle = math.atan2(wy - pv[1], wx - pv[0])
                delta_deg = math.degrees(cur_angle - self._rot_start_angle)
                new_deg = self._rot_orig_deg + delta_deg
                if not free:   # Ctrl = free; no Ctrl = snap 45°
                    new_deg = round(new_deg / 45.0) * 45.0
                obj.set_rotation(new_deg)
                self.object_moved.emit(obj.id, obj.transform.offset_x, obj.transform.offset_y)
                self.update()

        elif self._pivot_dragging and self._selected_id and self._project:
            obj = self._project.object_by_id(self._selected_id)
            if obj:
                swx, swy = self._snap(wx, wy, force_free=free)
                obj.set_pivot(swx - obj.transform.offset_x,
                              swy - obj.transform.offset_y)
                self.object_moved.emit(obj.id, obj.transform.offset_x, obj.transform.offset_y)
                self.update()

        elif self._zone_drag_mode and self._zone_drag_id and self._zone_drag_start_world:
            zone = next(
                (z for z in self._project.forbidden_zones if z.id == self._zone_drag_id), None
            ) if self._project else None
            if zone and self._zone_drag_orig:
                swx, swy = self._snap(wx, wy, force_free=free)
                dx = swx - self._zone_drag_start_world[0]
                dy = swy - self._zone_drag_start_world[1]
                ox = self._zone_drag_orig["x"]
                oy = self._zone_drag_orig["y"]
                ow = self._zone_drag_orig["width"]
                oh = self._zone_drag_orig["height"]
                if self._zone_drag_mode == "move":
                    zone.x = ox + dx
                    zone.y = oy + dy
                elif self._zone_drag_mode == "resize_bl":
                    nw = max(1.0, ow - dx)
                    nh = max(1.0, oh - dy)
                    if nw > 1.0: zone.x = ox + dx
                    if nh > 1.0: zone.y = oy + dy
                    zone.width = nw
                    zone.height = nh
                elif self._zone_drag_mode == "resize_br":
                    nh = max(1.0, oh - dy)
                    if nh > 1.0: zone.y = oy + dy
                    zone.width = max(1.0, ow + dx)
                    zone.height = nh
                elif self._zone_drag_mode == "resize_tl":
                    nw = max(1.0, ow - dx)
                    if nw > 1.0: zone.x = ox + dx
                    zone.width = nw
                    zone.height = max(1.0, oh + dy)
                elif self._zone_drag_mode == "resize_tr":
                    zone.width = max(1.0, ow + dx)
                    zone.height = max(1.0, oh + dy)
                self.update()

        elif self._mode == MODE_DRAW_ZONE and self._zone_start:
            swx, swy = self._snap(wx, wy, force_free=free)
            self._zone_current = (swx, swy)
            self.update()

        elif self._drag_obj_id and self._drag_world_start:
            if self._project is None:
                return
            obj = self._project.object_by_id(self._drag_obj_id)
            if obj is None:
                return
            swx, swy = self._snap(wx, wy, force_free=free)
            start_wx, start_wy = self._drag_world_start
            ox0, oy0 = self._drag_offset_start  # type: ignore[misc]
            obj.set_offset(ox0 + (swx - start_wx), oy0 + (swy - start_wy))
            self.object_moved.emit(
                obj.id,
                obj.transform.offset_x,
                obj.transform.offset_y,
            )
            self.update()

        else:
            # Update cursor based on hover (no drag in progress)
            if self._mode != MODE_DRAW_ZONE:
                cursor = Qt.CursorShape.ArrowCursor
                if self._selected_zone_id and self._project:
                    sel_zone = next(
                        (z for z in self._project.forbidden_zones
                         if z.id == self._selected_zone_id), None
                    )
                    if sel_zone:
                        corner = self._zone_corner_hit(sel_zone, sx, sy)
                        if corner in ("tl", "br"):
                            cursor = Qt.CursorShape.SizeFDiagCursor
                        elif corner in ("tr", "bl"):
                            cursor = Qt.CursorShape.SizeBDiagCursor
                        elif (sel_zone.x <= wx <= sel_zone.x + sel_zone.width
                              and sel_zone.y <= wy <= sel_zone.y + sel_zone.height):
                            cursor = Qt.CursorShape.SizeAllCursor
                self.setCursor(cursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = None

        elif event.button() == Qt.MouseButton.LeftButton:
            if self._rot_dragging and self._selected_id and self._project:
                self._rot_dragging = False
                obj = self._project.object_by_id(self._selected_id)
                if obj and self._drag_old_transform:
                    self.drag_committed.emit(
                        obj.id,
                        self._drag_old_transform,
                        obj.transform.copy(),
                    )
                self._drag_old_transform = None

            elif self._pivot_dragging and self._selected_id and self._project:
                self._pivot_dragging = False
                obj = self._project.object_by_id(self._selected_id)
                if obj and self._drag_old_transform:
                    self.drag_committed.emit(
                        obj.id,
                        self._drag_old_transform,
                        obj.transform.copy(),
                    )
                self._drag_old_transform = None

            elif self._zone_drag_mode and self._zone_drag_id:
                zone = next(
                    (z for z in self._project.forbidden_zones if z.id == self._zone_drag_id), None
                ) if self._project else None
                if zone and self._zone_drag_orig:
                    new_state = {
                        "x": zone.x, "y": zone.y,
                        "width": zone.width, "height": zone.height,
                    }
                    if new_state != self._zone_drag_orig:
                        self.zone_changed.emit(
                            self._zone_drag_id,
                            dict(self._zone_drag_orig),
                            new_state,
                        )
                self._zone_drag_mode = ""
                self._zone_drag_id = ""
                self._zone_drag_start_world = None
                self._zone_drag_orig = None

            elif self._mode == MODE_DRAW_ZONE and self._zone_start and self._zone_current:
                x0, y0 = self._zone_start
                x1, y1 = self._zone_current
                zx, zy = min(x0, x1), min(y0, y1)
                zw, zh = abs(x1 - x0), abs(y1 - y0)
                if zw > 0.5 and zh > 0.5 and self._project:
                    zone = ForbiddenZone(x=zx, y=zy, width=zw, height=zh)
                    self._project.add_zone(zone)
                    self.zone_added.emit(zone.id)
                self._zone_start = None
                self._zone_current = None
                self.set_mode(MODE_SELECT)
                self.update()

            elif self._drag_obj_id:
                if self._project:
                    obj = self._project.object_by_id(self._drag_obj_id)
                    if obj and self._drag_old_transform:
                        self.drag_committed.emit(
                            obj.id,
                            self._drag_old_transform,
                            obj.transform.copy(),
                        )
                self._drag_obj_id = ""
                self._drag_world_start = None
                self._drag_offset_start = None
                self._drag_old_transform = None

    # ------------------------------------------------------------------
    # Hit testing

    def _hit_test(self, wx: float, wy: float) -> Optional[GcodeObject]:
        if self._project is None:
            return None
        for obj in reversed(self._project.visible_objects()):
            bb = obj.bounding_box
            if bb.min_x <= wx <= bb.max_x and bb.min_y <= wy <= bb.max_y:
                return obj
        return None

    def _zone_hit_test(self, wx: float, wy: float) -> Optional[ForbiddenZone]:
        if self._project is None:
            return None
        for zone in reversed(self._project.forbidden_zones):
            if zone.x <= wx <= zone.x + zone.width and zone.y <= wy <= zone.y + zone.height:
                return zone
        return None

    _ZONE_CORNER_PX = 10

    def _zone_corner_hit(self, zone: ForbiddenZone, sx: float, sy: float) -> str:
        corners = {
            "bl": self._w2s(zone.x, zone.y),
            "br": self._w2s(zone.x + zone.width, zone.y),
            "tl": self._w2s(zone.x, zone.y + zone.height),
            "tr": self._w2s(zone.x + zone.width, zone.y + zone.height),
        }
        for name, pt in corners.items():
            if math.hypot(sx - pt.x(), sy - pt.y()) <= self._ZONE_CORNER_PX:
                return name
        return ""

    # ------------------------------------------------------------------
    # Keyboard

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self._mode != MODE_SELECT:
                self.set_mode(MODE_SELECT)
            else:
                self._selected_id = ""
                self._selected_zone_id = ""
                self._zone_drag_mode = ""
                self._pivot_dragging = False
                self.object_selected.emit("")
                self.update()
            event.accept()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Comment tooltips

    _TOOLTIP_PX = 12   # pixel radius to trigger a comment tooltip

    def _update_tooltip(self, sx: float, sy: float):
        if self._project is None:
            QToolTip.hideText()
            return
        for obj in self._project.visible_objects():
            if not obj.has_comments:
                continue
            for move in obj.computed_moves:
                if not move.comment or not move.xy_move:
                    continue
                mx = (move.from_pos.x + move.to_pos.x) / 2
                my = (move.from_pos.y + move.to_pos.y) / 2
                sp = self._w2s(mx, my)
                if math.hypot(sx - sp.x(), sy - sp.y()) <= self._TOOLTIP_PX:
                    QToolTip.showText(
                        self.mapToGlobal(QPoint(int(sx), int(sy) - 20)),
                        move.comment,
                        self,
                    )
                    return
        QToolTip.hideText()

    # ------------------------------------------------------------------
    # Context menu

    def contextMenuEvent(self, event: QContextMenuEvent):
        wx, wy = self._s2w(event.pos().x(), event.pos().y())
        obj = self._hit_test(wx, wy)

        if obj is None:
            zone = self._zone_hit_test(wx, wy)
            if zone is None:
                return
            self._selected_zone_id = zone.id
            self._selected_id = ""
            self.update()
            menu = QMenu(self)
            act_rename = menu.addAction("Rename Zone…")
            act_edit   = menu.addAction("Edit coordinates…")
            menu.addSeparator()
            act_del = menu.addAction("Delete Zone")
            chosen = menu.exec(event.globalPos())
            if chosen == act_rename:
                self.zone_rename_requested.emit(zone.id)
            elif chosen == act_edit:
                self.zone_edit_requested.emit(zone.id)
            elif chosen == act_del:
                self.zone_delete_requested.emit(zone.id)
            return

        # Select the object so the user sees what the menu refers to
        if obj.id != self._selected_id:
            self._selected_id = obj.id
            self._selected_zone_id = ""
            self.object_selected.emit(obj.id)
            self.update()

        menu = QMenu(self)
        act_clone = menu.addAction("Clone…")
        act_del = menu.addAction("Delete")
        menu.addSeparator()
        act_mirror_h = menu.addAction("Mirror Horizontal")
        act_mirror_v = menu.addAction("Mirror Vertical")
        menu.addSeparator()
        act_reset_t = menu.addAction("Reset Transform")
        act_reset_pv = menu.addAction("Reset Pivot")

        chosen = menu.exec(event.globalPos())
        if chosen == act_clone:
            self.context_action.emit("clone", obj.id)
        elif chosen == act_del:
            self.context_action.emit("delete", obj.id)
        elif chosen == act_mirror_h:
            self.context_action.emit("mirror_h", obj.id)
        elif chosen == act_mirror_v:
            self.context_action.emit("mirror_v", obj.id)
        elif chosen == act_reset_t:
            self.context_action.emit("reset_transform", obj.id)
        elif chosen == act_reset_pv:
            self.context_action.emit("reset_pivot", obj.id)
