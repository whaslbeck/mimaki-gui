from __future__ import annotations
import os
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QGroupBox, QFormLayout, QLineEdit, QCheckBox, QPushButton,
    QDoubleSpinBox, QLabel, QMenu, QSizePolicy,
)

from app.model.gcode_object import GcodeObject
from app.model.project import Project, MACHINE_W, MACHINE_H
from app.model.types import Transform


class ObjectPanel(QWidget):
    object_selected = pyqtSignal(str)
    # id + copy of transform BEFORE the change (for undo)
    transform_changed = pyqtSignal(str, object)
    visibility_changed = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)   # obj id
    send_requested = pyqtSignal(str)        # obj id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: Optional[Project] = None
        self._current_id: str = ""
        self._updating = False
        self._pre_change: Optional[Transform] = None   # snapshot before edit
        self._orig_w: float = 1.0   # bounding box width at scale=1
        self._orig_h: float = 1.0   # bounding box height at scale=1
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # --- Object list ---
        layout.addWidget(QLabel("<b>Objects</b>"))
        self._list = QListWidget()
        self._list.setMaximumHeight(180)
        self._list.currentRowChanged.connect(self._on_list_row_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        layout.addWidget(self._list)

        list_btns = QHBoxLayout()
        self._btn_duplicate = QPushButton("Duplicate")
        self._btn_duplicate.clicked.connect(self._on_duplicate)
        list_btns.addWidget(self._btn_duplicate)
        self._btn_delete = QPushButton("Delete")
        self._btn_delete.clicked.connect(self._on_delete)
        list_btns.addWidget(self._btn_delete)
        self._btn_up = QPushButton("▲")
        self._btn_up.setFixedWidth(28)
        self._btn_up.clicked.connect(self._on_move_up)
        list_btns.addWidget(self._btn_up)
        self._btn_down = QPushButton("▼")
        self._btn_down.setFixedWidth(28)
        self._btn_down.clicked.connect(self._on_move_down)
        list_btns.addWidget(self._btn_down)
        layout.addLayout(list_btns)

        # --- Properties ---
        prop_box = QGroupBox("Properties")
        form = QFormLayout(prop_box)
        form.setSpacing(4)

        self._chk_visible = QCheckBox()
        self._chk_visible.stateChanged.connect(self._on_visible_changed)
        form.addRow("Visible", self._chk_visible)

        self._edit_label = QLineEdit()
        self._edit_label.editingFinished.connect(self._on_label_changed)
        form.addRow("Label", self._edit_label)

        self._spin_ox = self._make_spin(-9999, 9999, 0.1)
        self._spin_ox.valueChanged.connect(self._on_offset_changed)
        form.addRow("Offset X [mm]", self._spin_ox)

        self._spin_oy = self._make_spin(-9999, 9999, 0.1)
        self._spin_oy.valueChanged.connect(self._on_offset_changed)
        form.addRow("Offset Y [mm]", self._spin_oy)

        self._spin_scale = self._make_spin(0.001, 100, 0.01, decimals=4)
        self._spin_scale.valueChanged.connect(self._on_scale_changed)
        form.addRow("Scale", self._spin_scale)

        self._spin_width = self._make_spin(0.001, 99999, 0.1, decimals=3)
        self._spin_width.valueChanged.connect(self._on_width_changed)
        form.addRow("Width [mm]", self._spin_width)

        self._spin_height = self._make_spin(0.001, 99999, 0.1, decimals=3)
        self._spin_height.valueChanged.connect(self._on_height_changed)
        form.addRow("Height [mm]", self._spin_height)

        self._chk_lock_aspect = QCheckBox()
        self._chk_lock_aspect.setChecked(True)
        self._chk_lock_aspect.setToolTip("Lock aspect ratio (only uniform scale supported)")
        form.addRow("Lock aspect", self._chk_lock_aspect)

        self._spin_rot = self._make_spin(-360, 360, 1.0, decimals=2)
        self._spin_rot.valueChanged.connect(self._on_rotation_changed)
        form.addRow("Rotation [°]", self._spin_rot)

        self._spin_pvx = self._make_spin(-9999, 9999, 0.1)
        self._spin_pvx.valueChanged.connect(self._on_pivot_changed)
        form.addRow("Pivot X [mm]", self._spin_pvx)

        self._spin_pvy = self._make_spin(-9999, 9999, 0.1)
        self._spin_pvy.valueChanged.connect(self._on_pivot_changed)
        form.addRow("Pivot Y [mm]", self._spin_pvy)

        reset_row = QHBoxLayout()
        btn_reset_pivot = QPushButton("Reset Pivot")
        btn_reset_pivot.clicked.connect(self._on_reset_pivot)
        reset_row.addWidget(btn_reset_pivot)
        btn_reset_all = QPushButton("Reset Transform")
        btn_reset_all.clicked.connect(self._on_reset_transform)
        reset_row.addWidget(btn_reset_all)
        form.addRow("", reset_row)

        layout.addWidget(prop_box)

        # --- Snap to work-area edge ---
        snap_box = QGroupBox("Snap to work area edge")
        snap_layout = QVBoxLayout(snap_box)
        snap_layout.setSpacing(3)

        row_x = QHBoxLayout()
        self._btn_xmin = QPushButton("X min = 0")
        self._btn_xmin.setToolTip("Move object so left edge is at X = 0")
        self._btn_xmin.clicked.connect(lambda: self._snap_edge("xmin"))
        row_x.addWidget(self._btn_xmin)
        self._btn_xmax = QPushButton(f"X max = {MACHINE_W:.0f} mm")
        self._btn_xmax.setToolTip(f"Move object so right edge is at X = {MACHINE_W} mm")
        self._btn_xmax.clicked.connect(lambda: self._snap_edge("xmax"))
        row_x.addWidget(self._btn_xmax)
        snap_layout.addLayout(row_x)

        row_y = QHBoxLayout()
        self._btn_ymin = QPushButton("Y min = 0")
        self._btn_ymin.setToolTip("Move object so bottom edge is at Y = 0")
        self._btn_ymin.clicked.connect(lambda: self._snap_edge("ymin"))
        row_y.addWidget(self._btn_ymin)
        self._btn_ymax = QPushButton(f"Y max = {MACHINE_H:.0f} mm")
        self._btn_ymax.setToolTip(f"Move object so top edge is at Y = {MACHINE_H} mm")
        self._btn_ymax.clicked.connect(lambda: self._snap_edge("ymax"))
        row_y.addWidget(self._btn_ymax)
        snap_layout.addLayout(row_y)

        layout.addWidget(snap_box)

        # --- Metadaten ---
        meta_box = QGroupBox("Metadaten")
        meta_form = QFormLayout(meta_box)
        meta_form.setSpacing(3)

        self._lbl_source = QLabel("—")
        self._lbl_source.setWordWrap(True)
        meta_form.addRow("Quelle:", self._lbl_source)

        self._lbl_move_count = QLabel("—")
        meta_form.addRow("Pfade:", self._lbl_move_count)

        self._lbl_z_range = QLabel("—")
        meta_form.addRow("Z-Bereich:", self._lbl_z_range)

        meta_btn_row = QHBoxLayout()
        self._btn_comments = QPushButton("Kommentare")
        self._btn_comments.setEnabled(False)
        self._btn_comments.clicked.connect(self._on_show_comments)
        meta_btn_row.addWidget(self._btn_comments)
        self._btn_source = QPushButton("Quellcode…")
        self._btn_source.setEnabled(False)
        self._btn_source.clicked.connect(self._on_show_source)
        meta_btn_row.addWidget(self._btn_source)
        meta_form.addRow("", meta_btn_row)

        layout.addWidget(meta_box)
        layout.addStretch()

        self._set_props_enabled(False)

    @staticmethod
    def _make_spin(
        lo: float, hi: float, step: float = 1.0, decimals: int = 3
    ) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(decimals)
        s.setKeyboardTracking(False)
        return s

    def _set_props_enabled(self, on: bool):
        for w in (
            self._chk_visible, self._edit_label,
            self._spin_ox, self._spin_oy,
            self._spin_scale, self._spin_width, self._spin_height,
            self._spin_rot, self._spin_pvx, self._spin_pvy,
            self._btn_xmin, self._btn_xmax,
            self._btn_ymin, self._btn_ymax,
        ):
            w.setEnabled(on)
        if not on and hasattr(self, "_lbl_source"):
            self._lbl_source.setText("—")
            self._lbl_source.setToolTip("")
            self._lbl_move_count.setText("—")
            self._lbl_z_range.setText("—")
            self._btn_comments.setText("Kommentare")
            self._btn_comments.setEnabled(False)
            self._btn_source.setEnabled(False)

    # ------------------------------------------------------------------
    # Public API

    def set_project(self, project: Project):
        self._project = project
        self.refresh_list()

    def refresh_list(self):
        self._updating = True
        current_id = self._current_id
        self._list.clear()
        if self._project:
            for obj in self._project.objects:
                item = QListWidgetItem(obj.label)
                item.setData(Qt.ItemDataRole.UserRole, obj.id)
                self._list.addItem(item)
        # restore selection
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == current_id:
                self._list.setCurrentRow(i)
                break
        self._updating = False

    def select_object(self, obj_id: str):
        self._current_id = obj_id
        self._updating = True
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == obj_id:
                self._list.setCurrentRow(i)
                break
        self._updating = False
        self._populate_props()

    def refresh_props(self):
        self._populate_props()

    # ------------------------------------------------------------------
    # Prop population

    def _populate_props(self):
        if not self._project or not self._current_id:
            self._set_props_enabled(False)
            return
        obj = self._project.object_by_id(self._current_id)
        if not obj:
            self._set_props_enabled(False)
            return
        self._set_props_enabled(True)
        self._updating = True
        t = obj.transform
        self._pre_change = t.copy()       # snapshot for undo
        bb = obj.bounding_box
        self._orig_w = bb.width / t.scale if abs(t.scale) > 1e-9 else bb.width
        self._orig_h = bb.height / t.scale if abs(t.scale) > 1e-9 else bb.height
        self._chk_visible.setChecked(obj.visible)
        self._edit_label.setText(obj.label)
        self._spin_ox.setValue(t.offset_x)
        self._spin_oy.setValue(t.offset_y)
        self._spin_scale.setValue(t.scale)
        self._spin_width.setValue(bb.width)
        self._spin_height.setValue(bb.height)
        self._spin_rot.setValue(t.rotation_deg)
        self._spin_pvx.setValue(t.pivot_x)
        self._spin_pvy.setValue(t.pivot_y)
        self._updating = False

        self._populate_meta(obj)

    # ------------------------------------------------------------------
    # List events

    def _on_list_row_changed(self, row: int):
        if self._updating or row < 0:
            return
        item = self._list.item(row)
        if item:
            obj_id = item.data(Qt.ItemDataRole.UserRole)
            self._current_id = obj_id
            self._populate_props()
            self.object_selected.emit(obj_id)

    def _on_list_context_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        obj_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_send = menu.addAction("Send this object")
        act_dup = menu.addAction("Duplicate")
        menu.addSeparator()
        act_del = menu.addAction("Delete")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen == act_send:
            self.send_requested.emit(obj_id)
        elif chosen == act_dup:
            self.duplicate_requested.emit(obj_id)
        elif chosen == act_del:
            self._current_id = obj_id
            self._on_delete()

    def _on_duplicate(self):
        if not self._current_id:
            return
        self.duplicate_requested.emit(self._current_id)

    def _on_delete(self):
        if not self._project or not self._current_id:
            return
        self._project.remove_object(self._current_id)
        self._current_id = ""
        self._pre_change = None
        self.refresh_list()
        self._set_props_enabled(False)
        self.transform_changed.emit("", None)

    def _on_move_up(self):
        self._move_in_list(-1)

    def _on_move_down(self):
        self._move_in_list(1)

    def _move_in_list(self, direction: int):
        if not self._project or not self._current_id:
            return
        ids = [o.id for o in self._project.objects]
        idx = ids.index(self._current_id) if self._current_id in ids else -1
        if idx < 0:
            return
        new_idx = max(0, min(len(ids) - 1, idx + direction))
        if new_idx == idx:
            return
        self._project.objects[idx], self._project.objects[new_idx] = (
            self._project.objects[new_idx], self._project.objects[idx]
        )
        self._project.modified = True
        self.refresh_list()
        self.transform_changed.emit(self._current_id, None)

    # ------------------------------------------------------------------
    # Property change handlers

    def _current_obj(self) -> Optional[GcodeObject]:
        if not self._project or not self._current_id:
            return None
        return self._project.object_by_id(self._current_id)

    def _capture_old(self) -> Optional[Transform]:
        """Return the saved pre-change snapshot, then advance it."""
        snap = self._pre_change
        return snap

    def _commit(self, obj: GcodeObject, old: Optional[Transform]):
        """Update pre_change to current state, emit transform_changed."""
        self._pre_change = obj.transform.copy()
        self._project.modified = True  # type: ignore[union-attr]
        self.transform_changed.emit(obj.id, old)

    def _on_visible_changed(self):
        if self._updating:
            return
        obj = self._current_obj()
        if obj:
            obj.visible = self._chk_visible.isChecked()
            self._project.modified = True  # type: ignore[union-attr]
            self.visibility_changed.emit(obj.id)

    def _on_label_changed(self):
        if self._updating:
            return
        obj = self._current_obj()
        if obj:
            obj.label = self._edit_label.text()
            self._project.modified = True  # type: ignore[union-attr]
            self.refresh_list()

    def _on_offset_changed(self):
        if self._updating:
            return
        obj = self._current_obj()
        if obj:
            old = self._capture_old()
            obj.set_offset(self._spin_ox.value(), self._spin_oy.value())
            self._commit(obj, old)

    def _on_scale_changed(self):
        if self._updating:
            return
        obj = self._current_obj()
        if obj:
            old = self._capture_old()
            obj.set_scale(self._spin_scale.value())
            self._updating = True
            self._spin_width.setValue(self._orig_w * obj.transform.scale)
            self._spin_height.setValue(self._orig_h * obj.transform.scale)
            self._updating = False
            self._commit(obj, old)

    def _on_width_changed(self):
        if self._updating or self._orig_w < 1e-9:
            return
        obj = self._current_obj()
        if obj:
            old = self._capture_old()
            new_scale = self._spin_width.value() / self._orig_w
            obj.set_scale(new_scale)
            self._updating = True
            self._spin_scale.setValue(new_scale)
            self._spin_height.setValue(self._orig_h * new_scale)
            self._updating = False
            self._commit(obj, old)

    def _on_height_changed(self):
        if self._updating or self._orig_h < 1e-9:
            return
        obj = self._current_obj()
        if obj:
            old = self._capture_old()
            new_scale = self._spin_height.value() / self._orig_h
            obj.set_scale(new_scale)
            self._updating = True
            self._spin_scale.setValue(new_scale)
            self._spin_width.setValue(self._orig_w * new_scale)
            self._updating = False
            self._commit(obj, old)

    def _on_rotation_changed(self):
        if self._updating:
            return
        obj = self._current_obj()
        if obj:
            old = self._capture_old()
            obj.set_rotation(self._spin_rot.value())
            self._commit(obj, old)

    def _on_pivot_changed(self):
        if self._updating:
            return
        obj = self._current_obj()
        if obj:
            old = self._capture_old()
            obj.set_pivot(self._spin_pvx.value(), self._spin_pvy.value())
            self._commit(obj, old)

    def _on_reset_pivot(self):
        obj = self._current_obj()
        if obj:
            old = self._capture_old()
            obj.reset_pivot()
            self._populate_props()   # updates _pre_change to new state
            self.transform_changed.emit(obj.id, old)

    def _on_reset_transform(self):
        obj = self._current_obj()
        if obj:
            old = self._capture_old()
            obj.reset_transform()
            self._populate_props()   # updates _pre_change to new state
            self.transform_changed.emit(obj.id, old)

    def _populate_meta(self, obj: GcodeObject):
        """Fill the Metadaten box — single pass over original_moves."""
        xy_moves = 0
        cut_moves = 0
        n_comments = 0
        z_set: set[float] = set()
        for m in obj.original_moves:
            if m.comment:
                n_comments += 1
            if not m.xy_move:
                continue
            xy_moves += 1
            if m.pen_down:
                cut_moves += 1
                if m.to_pos.z < 0:
                    z_set.add(round(m.to_pos.z, 2))
        travel_moves = xy_moves - cut_moves

        self._lbl_move_count.setText(
            f"{xy_moves} gesamt  ({cut_moves} schneidend, {travel_moves} Eilgang)"
        )

        if z_set:
            z_sorted = sorted(z_set)
            self._lbl_z_range.setText(
                f"{z_sorted[0]:.2f} … {z_sorted[-1]:.2f} mm  ({len(z_set)} Pässe)"
            )
        else:
            self._lbl_z_range.setText("—")

        self._btn_comments.setText(
            f"{n_comments} Kommentar{'e' if n_comments != 1 else ''}"
        )
        self._btn_comments.setEnabled(n_comments > 0)

        src_name = os.path.basename(obj.source_file) if obj.source_file else "—"
        self._lbl_source.setText(src_name)
        self._lbl_source.setToolTip(obj.source_file)

        can_preview = (
            obj.source_type not in ("generated",)
            and bool(obj.source_file)
            and os.path.isfile(obj.source_file)
        )
        self._btn_source.setEnabled(can_preview)

    def _on_show_comments(self):
        obj = self._current_obj()
        if not obj:
            return
        from app.gui.dialogs.comments_dialog import CommentsDialog
        dlg = CommentsDialog(obj, self)
        dlg.exec()

    def _on_show_source(self):
        obj = self._current_obj()
        if not obj:
            return
        from app.gui.dialogs.source_preview_dialog import SourcePreviewDialog
        dlg = SourcePreviewDialog(obj, self)
        dlg.exec()

    def _snap_edge(self, edge: str):
        obj = self._current_obj()
        if not obj:
            return
        bb = obj.bounding_box
        old = self._capture_old()
        if edge == "xmin":
            obj.transform.offset_x -= bb.min_x
        elif edge == "xmax":
            obj.transform.offset_x += MACHINE_W - bb.max_x
        elif edge == "ymin":
            obj.transform.offset_y -= bb.min_y
        elif edge == "ymax":
            obj.transform.offset_y += MACHINE_H - bb.max_y
        obj._invalidate()
        self._populate_props()
        self._commit(obj, old)
