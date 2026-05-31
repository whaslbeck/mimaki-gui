from __future__ import annotations
import math
import os
import time
from typing import Optional

import serial
from PyQt6.QtCore import Qt, QSettings, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence, QCloseEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QLabel, QDockWidget, QFileDialog, QInputDialog, QMessageBox, QStatusBar,
    QGroupBox, QFormLayout, QDoubleSpinBox, QFrame, QPushButton, QComboBox,
    QSlider, QTabWidget, QScrollArea,
)

# Machine-supported speeds (mm/s). Stored internally as mm/min.
_XY_MACHINING_MMS = [0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 50]
_Z_MACHINING_MMS  = [0.5, 1, 2, 3, 5, 8, 10]
_XY_TRAVEL_MMS    = [20, 40, 60, 80]
_Z_TRAVEL_MMS     = [5, 10, 15, 20, 25, 30]

from app.config import AppConfig
from app.model.gcode_object import GcodeObject
from app.model.project import Project
from app.model.types import Transform
from app.model.undo import UndoManager
from app.io.gcode_parser import parse_gcode
from app.io.project_io import save_project, load_project
from app.io.serial_sender import SerialSender
from app.gui.canvas import WorkCanvas
from app.gui.object_panel import ObjectPanel
from app.gui.send_panel import SendPanel


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config
        self._project = Project()
        self._serial_port: Optional[serial.Serial] = None
        self._undo = UndoManager()
        self._sender = SerialSender(self)
        self._job_start_time: float = 0.0
        self._job_move_count: int = 0

        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_shortcuts()
        self._connect_signals()

        self._canvas.set_project(self._project)
        self._object_panel.set_project(self._project)
        self._canvas.set_ui_config(config.ui)
        self._send_panel.set_log_max_lines(config.ui.transmission_log_lines)

        self.setWindowTitle("Mimaki ME-500 GUI")
        self.resize(1280, 820)
        self._update_title()

    # ------------------------------------------------------------------
    # UI setup

    def _setup_ui(self):
        # Central splitter: canvas left, right panel
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self._canvas = WorkCanvas()
        splitter.addWidget(self._canvas)

        # Right panel — two tabs so everything fits on FullHD
        right_tabs = QTabWidget()
        right_tabs.setMinimumWidth(300)

        # ── Tab 1: Objekte ──
        obj_scroll = QScrollArea()
        obj_scroll.setWidgetResizable(True)
        obj_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._object_panel = ObjectPanel()
        obj_scroll.setWidget(self._object_panel)
        right_tabs.addTab(obj_scroll, "Objekte")

        # ── Tab 2: Einstellungen ──
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_inner = QWidget()
        settings_layout = QVBoxLayout(settings_inner)
        settings_layout.setContentsMargins(4, 4, 4, 4)
        settings_layout.setSpacing(6)

        # Speed settings
        speed_box = QGroupBox("Speeds")
        speed_form = QFormLayout(speed_box)
        speed_form.setSpacing(3)
        self._cmb_xy_travel = self._make_speed_combo(_XY_TRAVEL_MMS)
        self._select_speed(self._cmb_xy_travel, self._project.speeds.xy_travel_mm_min)
        self._cmb_xy_travel.currentIndexChanged.connect(self._on_speed_changed)
        speed_form.addRow("XY travel (PU):", self._cmb_xy_travel)
        self._cmb_xy_machine = self._make_speed_combo(_XY_MACHINING_MMS)
        self._select_speed(self._cmb_xy_machine, self._project.speeds.xy_machining_mm_min)
        self._cmb_xy_machine.currentIndexChanged.connect(self._on_speed_changed)
        speed_form.addRow("XY machining (PD):", self._cmb_xy_machine)
        self._cmb_z_travel = self._make_speed_combo(_Z_TRAVEL_MMS)
        self._select_speed(self._cmb_z_travel, self._project.speeds.z_travel_mm_min)
        self._cmb_z_travel.currentIndexChanged.connect(self._on_speed_changed)
        speed_form.addRow("Z travel (PU):", self._cmb_z_travel)
        self._cmb_z_machine = self._make_speed_combo(_Z_MACHINING_MMS)
        self._select_speed(self._cmb_z_machine, self._project.speeds.z_machining_mm_min)
        self._cmb_z_machine.currentIndexChanged.connect(self._on_speed_changed)
        speed_form.addRow("Z machining (PD):", self._cmb_z_machine)
        self._lbl_duration = QLabel("Est. duration: --:--:--")
        speed_form.addRow("", self._lbl_duration)
        settings_layout.addWidget(speed_box)

        # WCS offset
        wcs_box = QGroupBox("Work Coordinate Offset")
        wcs_form = QFormLayout(wcs_box)
        wcs_form.setSpacing(3)
        self._spin_wcs_x = QDoubleSpinBox()
        self._spin_wcs_x.setRange(-500, 500)
        self._spin_wcs_x.setDecimals(2)
        self._spin_wcs_x.setSuffix(" mm")
        self._spin_wcs_x.setKeyboardTracking(False)
        self._spin_wcs_x.valueChanged.connect(self._on_wcs_changed)
        wcs_form.addRow("Offset X:", self._spin_wcs_x)
        self._spin_wcs_y = QDoubleSpinBox()
        self._spin_wcs_y.setRange(-500, 500)
        self._spin_wcs_y.setDecimals(2)
        self._spin_wcs_y.setSuffix(" mm")
        self._spin_wcs_y.setKeyboardTracking(False)
        self._spin_wcs_y.valueChanged.connect(self._on_wcs_changed)
        wcs_form.addRow("Offset Y:", self._spin_wcs_y)
        wcs_btn_row = QHBoxLayout()
        btn_wcs_reset = QPushButton("Reset")
        btn_wcs_reset.setToolTip("Set WCS offset to 0 / 0")
        btn_wcs_reset.clicked.connect(self._on_wcs_reset)
        wcs_btn_row.addWidget(btn_wcs_reset)
        btn_wcs_bake = QPushButton("Bake into Objects")
        btn_wcs_bake.setToolTip(
            "Add the WCS offset to every object's position and reset offset to 0"
        )
        btn_wcs_bake.clicked.connect(self._on_wcs_bake)
        wcs_btn_row.addWidget(btn_wcs_bake)
        wcs_form.addRow("", wcs_btn_row)
        settings_layout.addWidget(wcs_box)

        # Z-Layer filter
        self._z_depths: list[float] = []   # shallowest first, round 2dp
        self._z_filter_box = QGroupBox("Z-Ebenen-Filter")
        z_filter_layout = QVBoxLayout(self._z_filter_box)
        z_filter_layout.setSpacing(4)

        z_slider_row = QHBoxLayout()
        z_slider_row.addWidget(QLabel("Schnell:"))
        self._z_slider = QSlider(Qt.Orientation.Horizontal)
        self._z_slider.setMinimum(0)
        self._z_slider.setMaximum(0)
        self._z_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._z_slider.setTickInterval(1)
        self._z_slider.valueChanged.connect(self._on_z_slider_changed)
        z_slider_row.addWidget(self._z_slider, 1)
        self._z_slider_label = QLabel("Alle")
        self._z_slider_label.setMinimumWidth(110)
        z_slider_row.addWidget(self._z_slider_label)
        btn_z_all = QPushButton("Alle")
        btn_z_all.setFixedWidth(40)
        btn_z_all.setToolTip("Alle Z-Ebenen anzeigen")
        btn_z_all.clicked.connect(self._z_filter_reset)
        z_slider_row.addWidget(btn_z_all)
        z_filter_layout.addLayout(z_slider_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        z_filter_layout.addWidget(sep)

        from PyQt6.QtWidgets import QListWidget
        self._z_layer_list = QListWidget()
        self._z_layer_list.setMaximumHeight(110)
        self._z_layer_list.setSpacing(1)
        self._z_layer_list.itemChanged.connect(self._on_z_item_changed)
        z_filter_layout.addWidget(self._z_layer_list)

        self._z_filter_box.setVisible(False)
        settings_layout.addWidget(self._z_filter_box)
        settings_layout.addStretch()

        settings_scroll.setWidget(settings_inner)
        right_tabs.addTab(settings_scroll, "Einstellungen")

        splitter.addWidget(right_tabs)
        splitter.setSizes([900, 340])

        # Transmission dock (bottom)
        self._send_panel = SendPanel()
        send_dock = QDockWidget("Transmission", self)
        send_dock.setObjectName("send_dock")
        send_dock.setWidget(self._send_panel)
        send_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, send_dock)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._coord_label = QLabel("X: 0.000  Y: 0.000")
        self._status_bar.addPermanentWidget(self._coord_label)

    @staticmethod
    def _make_speed_combo(speeds_mms: list) -> QComboBox:
        c = QComboBox()
        for mms in speeds_mms:
            c.addItem(f"{mms:g} mm/s  ({mms * 6:.0f} cm/min)", mms * 60)
        return c

    @staticmethod
    def _select_speed(combo: QComboBox, value_mm_min: float):
        best = min(range(combo.count()),
                   key=lambda i: abs(combo.itemData(i) - value_mm_min))
        combo.setCurrentIndex(best)

    # ------------------------------------------------------------------
    # Menu

    def _setup_menu(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")
        self._act_open_gcode = QAction("&Import G-code…", self)
        self._act_open_gcode.setShortcut(QKeySequence("Ctrl+O"))
        file_menu.addAction(self._act_open_gcode)

        self._act_open_hpgl = QAction("Import &HPGL…", self)
        file_menu.addAction(self._act_open_hpgl)

        self._act_open_project = QAction("Open &Project…", self)
        self._act_open_project.setShortcut(QKeySequence("Ctrl+Shift+O"))
        file_menu.addAction(self._act_open_project)

        self._recent_menu = file_menu.addMenu("Recent &Projects")

        file_menu.addSeparator()
        self._act_save = QAction("&Save Project", self)
        self._act_save.setShortcut(QKeySequence("Ctrl+S"))
        file_menu.addAction(self._act_save)

        self._act_save_as = QAction("Save Project &As…", self)
        self._act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        file_menu.addAction(self._act_save_as)

        file_menu.addSeparator()
        self._act_export_hpgl = QAction("&Export HPGL…", self)
        file_menu.addAction(self._act_export_hpgl)

        file_menu.addSeparator()
        act_quit = QAction("&Quit", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # Edit
        edit_menu = mb.addMenu("&Edit")
        self._act_undo = QAction("&Undo", self)
        self._act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self._act_undo.triggered.connect(self._on_undo)
        edit_menu.addAction(self._act_undo)

        self._act_redo = QAction("&Redo", self)
        self._act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self._act_redo.triggered.connect(self._on_redo)
        edit_menu.addAction(self._act_redo)

        self._act_select_all = QAction("Select &All", self)
        self._act_select_all.setShortcut(QKeySequence("Ctrl+A"))
        edit_menu.addAction(self._act_select_all)

        edit_menu.addSeparator()
        self._act_clone = QAction("&Clone Selected…", self)
        self._act_clone.setShortcut(QKeySequence("Ctrl+D"))
        edit_menu.addAction(self._act_clone)

        edit_menu.addSeparator()
        self._act_insert_shape = QAction("&Insert Shape…", self)
        self._act_insert_shape.setShortcut(QKeySequence("Ctrl+I"))
        edit_menu.addAction(self._act_insert_shape)

        edit_menu.addSeparator()
        self._act_mirror_h = QAction("Mirror &Horizontal", self)
        self._act_mirror_h.setShortcut(QKeySequence("Ctrl+Shift+H"))
        edit_menu.addAction(self._act_mirror_h)

        self._act_mirror_v = QAction("Mirror &Vertical", self)
        self._act_mirror_v.setShortcut(QKeySequence("Ctrl+Shift+V"))
        edit_menu.addAction(self._act_mirror_v)

        edit_menu.addSeparator()
        self._act_array = QAction("&Array / Grid…", self)
        self._act_array.setShortcut(QKeySequence("Ctrl+Shift+A"))
        edit_menu.addAction(self._act_array)

        self._act_scale_to_fit = QAction("&Scale to Fit…", self)
        self._act_scale_to_fit.setShortcut(QKeySequence("Ctrl+Shift+F"))
        edit_menu.addAction(self._act_scale_to_fit)

        edit_menu.addSeparator()
        self._act_optimize_order = QAction("&Optimize Path Order", self)
        self._act_optimize_order.setShortcut(QKeySequence("Ctrl+Shift+O"))
        edit_menu.addAction(self._act_optimize_order)

        # View
        view_menu = mb.addMenu("&View")
        self._act_toggle_grid = QAction("Toggle &Grid", self)
        self._act_toggle_grid.setShortcut(QKeySequence("Ctrl+G"))
        self._act_toggle_grid.setCheckable(True)
        self._act_toggle_grid.setChecked(True)
        view_menu.addAction(self._act_toggle_grid)

        self._act_fit = QAction("&Fit to Window", self)
        self._act_fit.setShortcut(QKeySequence("Ctrl+0"))
        view_menu.addAction(self._act_fit)

        self._act_depth_color = QAction("&Depth Coloring", self)
        self._act_depth_color.setCheckable(True)
        self._act_depth_color.setToolTip(
            "Color cutting moves by Z depth (green = shallow, red = deep)"
        )
        view_menu.addAction(self._act_depth_color)

        self._act_preview_3d = QAction("&3D-Vorschau…", self)
        self._act_preview_3d.setShortcut(QKeySequence("Ctrl+3"))
        view_menu.addAction(self._act_preview_3d)

        view_menu.addSeparator()
        self._act_draw_zone = QAction("Draw &Forbidden Zone", self)
        self._act_draw_zone.setCheckable(True)
        self._act_draw_zone.setShortcut(QKeySequence("Ctrl+F"))
        view_menu.addAction(self._act_draw_zone)

        self._act_clear_zones = QAction("Clear All Forbidden Zones", self)
        view_menu.addAction(self._act_clear_zones)

        view_menu.addSeparator()
        self._act_grid_settings = QAction("Grid &Settings…", self)
        view_menu.addAction(self._act_grid_settings)

        # Machine
        machine_menu = mb.addMenu("&Machine")
        self._act_send = QAction("&Send Job (F5)", self)
        self._act_send.setShortcut(QKeySequence("F5"))
        machine_menu.addAction(self._act_send)

        self._act_send_from = QAction("Send &From… (Shift+F5)", self)
        self._act_send_from.setShortcut(QKeySequence("Shift+F5"))
        machine_menu.addAction(self._act_send_from)

        self._act_send_sel = QAction("Send &Selected Object (Ctrl+F5)", self)
        self._act_send_sel.setShortcut(QKeySequence("Ctrl+F5"))
        machine_menu.addAction(self._act_send_sel)

        machine_menu.addSeparator()
        self._act_simulate = QAction("Si&mulate…", self)
        machine_menu.addAction(self._act_simulate)

        self._act_dry_run = QAction("&Dry-run Animation…", self)
        self._act_dry_run.setShortcut(QKeySequence("F4"))
        machine_menu.addAction(self._act_dry_run)

        self._act_tool_library = QAction("&Tool Library…", self)
        machine_menu.addAction(self._act_tool_library)

        machine_menu.addSeparator()
        self._act_job_log = QAction("&Job Log…", self)
        machine_menu.addAction(self._act_job_log)

        machine_menu.addSeparator()
        self._act_serial_settings = QAction("Serial &Settings…", self)
        machine_menu.addAction(self._act_serial_settings)

        # Help
        help_menu = mb.addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._on_about)
        help_menu.addAction(act_about)

        self._update_recent_menu()

    # ------------------------------------------------------------------
    # Toolbar

    def _setup_toolbar(self):
        from PyQt6.QtWidgets import QToolBar
        from PyQt6.QtCore import QSize
        tb = QToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        tb.addAction(self._act_open_gcode)
        tb.addAction(self._act_open_project)
        tb.addAction(self._act_save)
        tb.addSeparator()
        tb.addAction(self._act_undo)
        tb.addAction(self._act_redo)
        tb.addSeparator()
        tb.addAction(self._act_toggle_grid)
        tb.addAction(self._act_draw_zone)
        tb.addAction(self._act_fit)
        tb.addSeparator()
        tb.addAction(self._act_send)
        tb.addAction(self._act_send_sel)

    # ------------------------------------------------------------------
    # Shortcuts

    def _setup_shortcuts(self):
        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence("F6"), self, self._on_pause)
        QShortcut(QKeySequence("F7"), self, self._on_stop)
        QShortcut(QKeySequence("Delete"), self, self._on_delete_selected)
        QShortcut(QKeySequence("Ctrl+B"), self, self._on_send_bounds)
        QShortcut(QKeySequence("Ctrl+A"), self, self._on_select_all)
        QShortcut(QKeySequence("Ctrl++"), self, lambda: self._canvas.zoom_step(1.2))
        QShortcut(QKeySequence("Ctrl+="), self, lambda: self._canvas.zoom_step(1.2))
        QShortcut(QKeySequence("Ctrl+-"), self, lambda: self._canvas.zoom_step(1 / 1.2))

    # ------------------------------------------------------------------
    # Signal wiring

    def _connect_signals(self):
        self._act_open_gcode.triggered.connect(self._on_open_gcode)
        self._act_open_hpgl.triggered.connect(self._on_open_hpgl)
        self._act_export_hpgl.triggered.connect(self._on_export_hpgl)
        self._act_open_project.triggered.connect(self._on_open_project)
        self._act_save.triggered.connect(self._on_save)
        self._act_save_as.triggered.connect(self._on_save_as)
        self._act_toggle_grid.toggled.connect(self._on_toggle_grid)
        self._act_fit.triggered.connect(self._canvas.fit_view)
        self._act_draw_zone.toggled.connect(self._on_draw_zone_toggle)
        self._act_clear_zones.triggered.connect(self._on_clear_zones)
        self._act_grid_settings.triggered.connect(self._on_grid_settings)
        self._canvas.zone_added.connect(self._on_zone_added)  # now passes zone_id
        self._act_select_all.triggered.connect(self._on_select_all)
        self._act_clone.triggered.connect(self._on_clone)
        self._act_insert_shape.triggered.connect(self._on_insert_shape)
        self._act_mirror_h.triggered.connect(self._on_mirror_h)
        self._act_mirror_v.triggered.connect(self._on_mirror_v)
        self._act_array.triggered.connect(self._on_array)
        self._act_scale_to_fit.triggered.connect(self._on_scale_to_fit)
        self._act_optimize_order.triggered.connect(self._on_optimize_order)
        self._act_depth_color.toggled.connect(self._canvas.set_depth_color_mode)
        self._act_preview_3d.triggered.connect(self._on_preview_3d)
        self._act_simulate.triggered.connect(self._on_simulate)
        self._act_dry_run.triggered.connect(self._on_dry_run)
        self._act_tool_library.triggered.connect(self._on_tool_library)
        self._act_job_log.triggered.connect(self._on_job_log)
        self._act_send.triggered.connect(self._on_send)
        self._act_send_from.triggered.connect(self._on_send_from)
        self._act_send_sel.triggered.connect(self._on_send_selected)
        self._act_serial_settings.triggered.connect(self._on_serial_settings)

        self._canvas.object_selected.connect(self._on_canvas_select)
        self._canvas.object_moved.connect(self._on_canvas_moved)
        self._canvas.drag_committed.connect(self._on_drag_committed)
        self._canvas.cursor_moved.connect(self._on_cursor_moved)
        self._canvas.context_action.connect(self._on_canvas_context_action)
        self._canvas.zone_delete_requested.connect(self._on_zone_delete_requested)
        self._canvas.zone_rename_requested.connect(self._on_zone_rename_requested)
        self._canvas.zone_edit_requested.connect(self._on_zone_edit_requested)
        self._canvas.zone_changed.connect(self._on_zone_changed)

        self._object_panel.object_selected.connect(self._on_panel_select)
        self._object_panel.transform_changed.connect(self._on_panel_transform_changed)
        self._object_panel.duplicate_requested.connect(self._on_duplicate_object)
        self._object_panel.send_requested.connect(
            lambda obj_id: self._start_send(scope="selected", selected_id=obj_id)
        )
        self._object_panel.visibility_changed.connect(
            lambda _: (self._canvas.update(), self._update_duration(),
                       self._rebuild_z_layer_list())
        )

        self._send_panel.connect_requested.connect(self._on_connect)
        self._send_panel.disconnect_requested.connect(self._on_disconnect)
        self._send_panel.send_requested.connect(self._on_send)
        self._send_panel.send_from_requested.connect(self._on_send_from)
        self._send_panel.send_selected_requested.connect(self._on_send_selected)
        self._send_panel.pause_requested.connect(self._on_pause)
        self._send_panel.resume_requested.connect(self._on_resume)
        self._send_panel.stop_requested.connect(self._on_stop)

        self._sender.progress.connect(self._on_send_progress)
        self._sender.line_sent.connect(self._send_panel.append_log)
        self._sender.job_finished.connect(self._on_job_finished)
        self._sender.job_stopped.connect(self._on_job_stopped)
        self._sender.error_occurred.connect(self._on_send_error)

    # ------------------------------------------------------------------
    # File actions

    @pyqtSlot()
    def _on_open_gcode(self):
        start_dir = self._config.last_import_dir or os.path.expanduser("~")
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import G-code files",
            start_dir,
            "G-code files (*.gcode *.nc *.tap *.txt);;All files (*)",
        )
        if not paths:
            return
        self._config.last_import_dir = os.path.dirname(paths[0])
        ids_before = {o.id for o in self._project.objects}
        for path in paths:
            self._import_gcode_file(path)
        new_objs = [o for o in self._project.objects if o.id not in ids_before]
        self._canvas.update()
        self._object_panel.refresh_list()
        self._update_duration()
        self._rebuild_z_layer_list()
        self._update_title()

        if new_objs:
            new_ids = [o.id for o in new_objs]
            label = f"Import {len(new_objs)} file(s)"

            def undo_import():
                for oid in new_ids:
                    self._project.remove_object(oid)
                self._project.modified = True
                self._canvas.set_selected("")
                self._canvas.update()
                self._object_panel.refresh_list()
                self._update_duration()
                self._update_undo_actions()

            def redo_import():
                for obj in new_objs:
                    if not self._project.object_by_id(obj.id):
                        self._project.objects.append(obj)
                self._project.modified = True
                self._canvas.update()
                self._object_panel.refresh_list()
                self._update_duration()
                self._update_undo_actions()

            self._undo.push(undo_import, redo_import, label)
            self._update_undo_actions()

    def _import_gcode_file(self, path: str):
        try:
            with open(path) as f:
                text = f.read()
        except OSError as e:
            QMessageBox.critical(self, "Import error", str(e))
            return
        result = parse_gcode(text)
        if result.warnings:
            msgs = "\n".join(
                f"Line {w.line_nr}: {w.message}" for w in result.warnings[:10]
            )
            QMessageBox.warning(self, "Parse warnings", msgs)
        obj = GcodeObject(source_file=path, original_moves=result.moves)
        self._project.add_object(obj)

    @pyqtSlot()
    def _on_open_hpgl(self):
        start_dir = self._config.last_import_dir or os.path.expanduser("~")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import HPGL files", start_dir,
            "HPGL files (*.hpgl *.plt *.hgl);;All files (*)",
        )
        if not paths:
            return
        self._config.last_import_dir = os.path.dirname(paths[0])
        ids_before = {o.id for o in self._project.objects}
        for path in paths:
            self._import_hpgl_file(path)
        new_objs = [o for o in self._project.objects if o.id not in ids_before]
        self._canvas.update()
        self._object_panel.refresh_list()
        self._update_duration()
        self._update_title()

        if new_objs:
            new_ids = [o.id for o in new_objs]

            def undo_import():
                for oid in new_ids:
                    self._project.remove_object(oid)
                self._project.modified = True
                self._canvas.set_selected("")
                self._canvas.update()
                self._object_panel.refresh_list()
                self._update_duration()
                self._update_undo_actions()

            def redo_import():
                for obj in new_objs:
                    if not self._project.object_by_id(obj.id):
                        self._project.objects.append(obj)
                self._project.modified = True
                self._canvas.update()
                self._object_panel.refresh_list()
                self._update_duration()
                self._update_undo_actions()

            self._undo.push(undo_import, redo_import, f"Import {len(new_objs)} HPGL file(s)")
            self._update_undo_actions()

    def _import_hpgl_file(self, path: str):
        from app.io.hpgl_parser import parse_hpgl
        try:
            with open(path, errors="replace") as f:
                text = f.read()
        except OSError as e:
            QMessageBox.critical(self, "Import error", str(e))
            return
        result = parse_hpgl(text)
        if not result.moves:
            QMessageBox.warning(self, "Import HPGL",
                                f"No moves found in:\n{path}")
            return
        obj = GcodeObject(source_file=path, original_moves=result.moves)
        obj.source_type = "hpgl"
        self._project.add_object(obj)

    @pyqtSlot()
    def _on_export_hpgl(self):
        vis = self._project.visible_objects()
        if not vis:
            QMessageBox.information(self, "Export HPGL", "No visible objects to export.")
            return
        start = (
            self._project.filepath.replace(".mimaki", ".hpgl")
            if self._project.filepath
            else os.path.expanduser("~/output.hpgl")
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export HPGL", start,
            "HPGL files (*.hpgl);;All files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".hpgl"):
            path += ".hpgl"
        from app.io.hpgl_writer import moves_to_hpgl
        moves: list = []
        for obj in vis:
            moves.extend(obj.computed_moves)
        data = moves_to_hpgl(
            moves,
            include_init=True,
            offset_x=self._project.work_offset_x,
            offset_y=self._project.work_offset_y,
            xy_speed_mms=self._project.speeds.xy_machining_mm_min / 60.0,
            z_speed_mms=self._project.speeds.z_machining_mm_min / 60.0,
        )
        try:
            with open(path, "wb") as f:
                f.write(data)
            self._status_bar.showMessage(f"HPGL exported: {path}")
        except OSError as e:
            QMessageBox.critical(self, "Export error", str(e))

    @pyqtSlot()
    def _on_simulate(self):
        vis = self._project.visible_objects()
        if not vis:
            QMessageBox.information(self, "Simulate", "No visible objects to simulate.")
            return
        moves: list = []
        for obj in vis:
            moves.extend(obj.computed_moves)
        from app.gui.dialogs.simulation_dialog import SimulationDialog
        dlg = SimulationDialog(moves, self)
        dlg.exec()

    @pyqtSlot()
    def _on_open_project(self):
        start_dir = self._config.last_project_dir or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", start_dir,
            "Mimaki project (*.mimaki);;All files (*)",
        )
        if not path:
            return
        try:
            project, missing = load_project(path)
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))
            return
        self._relocate_missing(project, missing)
        self._project = project
        self._canvas.set_project(project)
        self._object_panel.set_project(project)
        self._sync_speed_spinboxes()
        self._canvas.update()
        self._update_duration()
        self._rebuild_z_layer_list()
        self._config.last_project_dir = os.path.dirname(path)
        self._config.add_recent_file(path)
        self._config.save()
        self._update_title()
        self._update_recent_menu()

    @pyqtSlot()
    def _on_save(self):
        if not self._project.filepath:
            self._on_save_as()
            return
        self._do_save(self._project.filepath)

    @pyqtSlot()
    def _on_save_as(self):
        start_dir = (
            self._project.filepath or
            self._config.last_project_dir or
            os.path.expanduser("~")
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", start_dir,
            "Mimaki project (*.mimaki);;All files (*)",
        )
        if not path:
            return
        if not path.endswith(".mimaki"):
            path += ".mimaki"
        self._do_save(path)

    def _do_save(self, path: str):
        try:
            save_project(self._project, path)
        except OSError as e:
            QMessageBox.critical(self, "Save error", str(e))
            return
        self._config.last_project_dir = os.path.dirname(path)
        self._config.add_recent_file(path)
        self._config.save()
        self._update_title()
        self._update_recent_menu()

    # ------------------------------------------------------------------
    # View actions

    def _on_toggle_grid(self, checked: bool):
        self._project.grid.visible = checked
        self._canvas.update()

    # ------------------------------------------------------------------
    # View actions (zones)

    def _on_draw_zone_toggle(self, checked: bool):
        from app.gui.canvas import MODE_DRAW_ZONE, MODE_SELECT
        self._canvas.set_mode(MODE_DRAW_ZONE if checked else MODE_SELECT)

    def _on_zone_added(self, zone_id: str):
        self._act_draw_zone.setChecked(False)
        self._project.modified = True
        self._canvas.update()
        self._update_title()

        zone = next((z for z in self._project.forbidden_zones if z.id == zone_id), None)
        if zone:
            def undo_zone_add():
                self._project.remove_zone(zone.id)
                self._canvas._selected_zone_id = ""
                self._project.modified = True
                self._canvas.update()
                self._update_undo_actions()

            def redo_zone_add():
                if not any(z.id == zone.id for z in self._project.forbidden_zones):
                    self._project.forbidden_zones.append(zone)
                self._project.modified = True
                self._canvas.update()
                self._update_undo_actions()

            self._undo.push(undo_zone_add, redo_zone_add, "Draw zone")
            self._update_undo_actions()

    def _on_clear_zones(self):
        self._project.forbidden_zones.clear()
        self._project.modified = True
        self._canvas.update()
        self._update_title()

    def _on_grid_settings(self):
        from app.gui.dialogs.grid_dialog import GridSettingsDialog
        dlg = GridSettingsDialog(self._project.grid, self)
        if dlg.exec():
            new_grid = dlg.get_settings()
            self._project.grid = new_grid
            self._act_toggle_grid.setChecked(new_grid.visible)
            self._canvas.update()

    # ------------------------------------------------------------------
    # Edit actions

    @pyqtSlot()
    def _on_clone(self):
        sel_id = self._canvas._selected_id
        if not sel_id:
            QMessageBox.information(self, "Clone", "Please select an object first.")
            return
        obj = self._project.object_by_id(sel_id)
        if not obj:
            return
        ids_before = {o.id for o in self._project.objects}
        from app.gui.dialogs.clone_dialog import CloneDialog
        dlg = CloneDialog(obj, self._project, self)
        if dlg.exec():
            clones = [o for o in self._project.objects if o.id not in ids_before]
            clone_ids = [c.id for c in clones]

            def undo_clone():
                for cid in clone_ids:
                    self._project.remove_object(cid)
                self._project.modified = True
                self._canvas.update()
                self._object_panel.refresh_list()
                self._update_duration()
                self._update_undo_actions()

            def redo_clone():
                for c in clones:
                    if not self._project.object_by_id(c.id):
                        self._project.objects.append(c)
                self._project.modified = True
                self._canvas.update()
                self._object_panel.refresh_list()
                self._update_duration()
                self._update_undo_actions()

            self._undo.push(undo_clone, redo_clone, "Clone")
            self._update_undo_actions()
            self._canvas.update()
            self._object_panel.refresh_list()
            self._update_duration()
            self._update_title()

    @pyqtSlot(str)
    def _on_duplicate_object(self, obj_id: str):
        obj = self._project.object_by_id(obj_id)
        if not obj:
            return
        dup = obj.clone()
        dup.label = f"{obj.label} copy"
        bb = obj.bounding_box
        dup.transform.offset_x += bb.width + 2.0
        dup._invalidate()
        self._project.objects.append(dup)
        self._project.modified = True
        self._canvas.set_selected(dup.id)
        self._canvas.update()
        self._object_panel.refresh_list()
        self._object_panel.select_object(dup.id)
        self._update_duration()
        self._update_title()

        def undo_dup():
            self._project.remove_object(dup.id)
            self._project.modified = True
            self._canvas.set_selected(obj_id)
            self._canvas.update()
            self._object_panel.refresh_list()
            self._object_panel.select_object(obj_id)
            self._update_duration()
            self._update_undo_actions()

        def redo_dup():
            if not self._project.object_by_id(dup.id):
                self._project.objects.append(dup)
            self._project.modified = True
            self._canvas.set_selected(dup.id)
            self._canvas.update()
            self._object_panel.refresh_list()
            self._object_panel.select_object(dup.id)
            self._update_duration()
            self._update_undo_actions()

        self._undo.push(undo_dup, redo_dup, "Duplicate")
        self._update_undo_actions()

    @pyqtSlot()
    def _on_select_all(self):
        """Deselect zone; clear object selection so scope is 'all objects'."""
        self._canvas.set_selected("")
        self._object_panel.select_object("")
        self._canvas.update()

    @pyqtSlot()
    def _on_delete_selected(self):
        zone_id = self._canvas._selected_zone_id
        if zone_id:
            self._on_zone_delete_requested(zone_id)
            return
        sel_id = self._canvas._selected_id
        if not sel_id:
            return
        obj = self._project.object_by_id(sel_id)
        if not obj:
            return
        obj_index = self._project.objects.index(obj)

        def undo_delete():
            self._project.objects.insert(obj_index, obj)
            self._project.modified = True
            self._canvas.update()
            self._object_panel.refresh_list()
            self._update_duration()
            self._update_undo_actions()

        def redo_delete():
            self._project.remove_object(sel_id)
            self._canvas.set_selected("")
            self._object_panel.refresh_list()
            self._object_panel.select_object("")
            self._canvas.update()
            self._update_duration()
            self._update_undo_actions()

        redo_delete()   # execute immediately
        self._undo.push(undo_delete, redo_delete, "Delete")
        self._update_undo_actions()
        self._update_title()

    # ------------------------------------------------------------------
    # Shape wizard

    @pyqtSlot()
    def _on_insert_shape(self):
        from app.gui.dialogs.shape_wizard_dialog import ShapeWizardDialog
        dlg = ShapeWizardDialog(self._config, self)
        if not dlg.exec():
            return
        moves = dlg.get_moves()
        if not moves:
            return
        label = dlg.get_label()
        obj = GcodeObject.from_generated(moves, label)
        self._project.add_object(obj)
        self._canvas.set_selected(obj.id)
        self._canvas.update()
        self._object_panel.refresh_list()
        self._object_panel.select_object(obj.id)
        self._update_duration()
        self._update_title()

        def undo_insert():
            self._project.remove_object(obj.id)
            self._project.modified = True
            self._canvas.set_selected("")
            self._canvas.update()
            self._object_panel.refresh_list()
            self._update_duration()
            self._update_undo_actions()

        def redo_insert():
            if not self._project.object_by_id(obj.id):
                self._project.objects.append(obj)
            self._project.modified = True
            self._canvas.set_selected(obj.id)
            self._canvas.update()
            self._object_panel.refresh_list()
            self._object_panel.select_object(obj.id)
            self._update_duration()
            self._update_undo_actions()

        self._undo.push(undo_insert, redo_insert, f"Insert {label}")
        self._update_undo_actions()

    # ------------------------------------------------------------------
    # Mirror

    def _mirror_selected(self, axis: str):
        sel_id = self._canvas._selected_id
        if not sel_id:
            QMessageBox.information(self, "Mirror", "Please select an object first.")
            return
        obj = self._project.object_by_id(sel_id)
        if not obj:
            return
        old_moves = list(obj.original_moves)
        old_t = obj.transform.copy()
        if axis == "h":
            obj.mirror_h()
        else:
            obj.mirror_v()
        new_moves = list(obj.original_moves)
        new_t = obj.transform.copy()

        def undo_mirror():
            obj.original_moves = list(old_moves)
            obj.transform = old_t.copy()
            obj._invalidate()
            self._canvas.update()
            self._object_panel.refresh_props()
            self._update_undo_actions()

        def redo_mirror():
            obj.original_moves = list(new_moves)
            obj.transform = new_t.copy()
            obj._invalidate()
            self._canvas.update()
            self._object_panel.refresh_props()
            self._update_undo_actions()

        self._project.modified = True
        self._canvas.update()
        self._object_panel.refresh_props()
        self._update_title()
        self._undo.push(undo_mirror, redo_mirror, f"Mirror {'H' if axis == 'h' else 'V'}")
        self._update_undo_actions()

    @pyqtSlot()
    def _on_mirror_h(self):
        self._mirror_selected("h")

    @pyqtSlot()
    def _on_mirror_v(self):
        self._mirror_selected("v")

    # ------------------------------------------------------------------
    # Array / Grid

    @pyqtSlot()
    def _on_array(self):
        sel_id = self._canvas._selected_id
        if not sel_id:
            QMessageBox.information(self, "Array", "Please select an object first.")
            return
        obj = self._project.object_by_id(sel_id)
        if not obj:
            return
        from app.gui.dialogs.array_dialog import ArrayDialog
        dlg = ArrayDialog(obj, self)
        if not dlg.exec():
            return
        rows, cols, gap_x, gap_y = dlg.get_params()
        if rows * cols <= 1:
            return
        bb = obj.bounding_box
        step_x = bb.width + gap_x
        step_y = bb.height + gap_y
        new_objs: list[GcodeObject] = []
        for row in range(rows):
            for col in range(cols):
                if row == 0 and col == 0:
                    continue
                clone = obj.clone()
                clone.transform.offset_x += col * step_x
                clone.transform.offset_y += row * step_y
                clone._invalidate()
                clone.label = f"{obj.label} [{col + 1},{row + 1}]"
                self._project.objects.append(clone)
                new_objs.append(clone)

        obj.label = f"{obj.label} [1,1]"
        clone_ids = [c.id for c in new_objs]
        self._project.modified = True
        self._canvas.update()
        self._object_panel.refresh_list()
        self._update_duration()
        self._update_title()

        def undo_array():
            for cid in clone_ids:
                self._project.remove_object(cid)
            obj.label = obj.label.replace(" [1,1]", "")
            self._project.modified = True
            self._canvas.update()
            self._object_panel.refresh_list()
            self._update_duration()
            self._update_undo_actions()

        def redo_array():
            for c in new_objs:
                if not self._project.object_by_id(c.id):
                    self._project.objects.append(c)
            obj.label = obj.label if obj.label.endswith("[1,1]") else obj.label + " [1,1]"
            self._project.modified = True
            self._canvas.update()
            self._object_panel.refresh_list()
            self._update_duration()
            self._update_undo_actions()

        self._undo.push(undo_array, redo_array, f"Array {cols}×{rows}")
        self._update_undo_actions()

    # ------------------------------------------------------------------
    # Scale to fit

    @pyqtSlot()
    def _on_scale_to_fit(self):
        sel_id = self._canvas._selected_id
        if not sel_id:
            QMessageBox.information(self, "Scale to Fit", "Please select an object first.")
            return
        obj = self._project.object_by_id(sel_id)
        if not obj:
            return
        from app.gui.dialogs.scale_to_fit_dialog import ScaleToFitDialog
        dlg = ScaleToFitDialog(obj, self)
        if not dlg.exec():
            return
        old_t = obj.transform.copy()
        obj.set_scale(dlg.get_scale())
        self._push_transform_undo(sel_id, old_t, obj.transform.copy(), "Scale to fit")
        self._canvas.update()
        self._object_panel.refresh_props()
        self._update_duration()
        self._project.modified = True
        self._update_title()

    # ------------------------------------------------------------------
    # Dry-run animation

    @pyqtSlot()
    def _on_dry_run(self):
        vis = self._project.visible_objects()
        if not vis:
            QMessageBox.information(self, "Dry-run", "No visible objects to animate.")
            return
        moves: list = []
        for obj in vis:
            moves.extend(obj.computed_moves)
        from app.gui.dialogs.dry_run_dialog import DryRunDialog
        dlg = DryRunDialog(self._canvas, moves, self)
        dlg.show()
        dlg.raise_()

    @pyqtSlot()
    def _on_preview_3d(self):
        vis = self._project.visible_objects()
        if not vis:
            QMessageBox.information(self, "3D-Vorschau", "Keine sichtbaren Objekte.")
            return
        moves: list = []
        for obj in vis:
            moves.extend(obj.computed_moves)
        from app.gui.dialogs.preview_3d_dialog import Preview3DDialog
        dlg = Preview3DDialog(moves, self)
        dlg.show()
        dlg.raise_()

    # ------------------------------------------------------------------
    # Path optimization

    @pyqtSlot()
    def _on_optimize_order(self):
        vis = self._project.visible_objects()
        if len(vis) < 2:
            QMessageBox.information(self, "Optimize Order",
                                    "Need at least 2 visible objects to optimize.")
            return

        old_objects = list(self._project.objects)
        old_travel = self._calc_travel_distance(vis)

        unvisited = list(vis)
        ordered: list = []
        cur_x, cur_y = 0.0, 0.0
        while unvisited:
            best = min(
                unvisited,
                key=lambda o: math.hypot(
                    (o.computed_moves[0].from_pos.x if o.computed_moves else 0) - cur_x,
                    (o.computed_moves[0].from_pos.y if o.computed_moves else 0) - cur_y,
                ),
            )
            ordered.append(best)
            unvisited.remove(best)
            if best.computed_moves:
                last = best.computed_moves[-1]
                cur_x, cur_y = last.to_pos.x, last.to_pos.y

        new_travel = self._calc_travel_distance(ordered)

        vis_ids = {o.id for o in vis}
        vis_iter = iter(ordered)
        new_objects = [
            next(vis_iter) if o.id in vis_ids else o
            for o in self._project.objects
        ]

        saved = old_travel - new_travel
        saved_pct = saved / old_travel * 100 if old_travel > 0 else 0

        def apply_order(objs):
            self._project.objects = list(objs)
            self._project.modified = True
            self._canvas.update()
            self._object_panel.refresh_list()
            self._update_undo_actions()

        apply_order(new_objects)
        self._undo.push(
            lambda: apply_order(old_objects),
            lambda: apply_order(new_objects),
            "Optimize order",
        )
        self._update_undo_actions()
        self._update_title()
        self._status_bar.showMessage(
            f"Path order optimized: travel {old_travel:.1f} → {new_travel:.1f} mm "
            f"(saved {saved:.1f} mm, {saved_pct:.0f}%)"
        )

    @staticmethod
    def _calc_travel_distance(objects) -> float:
        total = 0.0
        cur_x, cur_y = 0.0, 0.0
        for obj in objects:
            if not obj.computed_moves:
                continue
            first = obj.computed_moves[0]
            total += math.hypot(first.from_pos.x - cur_x, first.from_pos.y - cur_y)
            last = obj.computed_moves[-1]
            cur_x, cur_y = last.to_pos.x, last.to_pos.y
        return total

    # ------------------------------------------------------------------
    # Tool library

    @pyqtSlot()
    def _on_tool_library(self):
        from app.gui.dialogs.tool_library_dialog import ToolLibraryDialog
        dlg = ToolLibraryDialog(self._config, self._project, self)
        if dlg.exec():
            self._config.tool_presets = dlg.get_presets()
            self._config.save()
            applied = dlg.get_applied_preset()
            if applied is not None:
                spd = self._project.speeds
                spd.xy_travel_mm_min = applied.xy_travel_mm_min
                spd.xy_machining_mm_min = applied.xy_machining_mm_min
                spd.z_travel_mm_min = applied.z_travel_mm_min
                spd.z_machining_mm_min = applied.z_machining_mm_min
                self._sync_speed_spinboxes()
                self._update_duration()
                self._project.modified = True
                self._update_title()
                self._status_bar.showMessage(
                    f"Applied tool preset: {applied.name}"
                )

    # ------------------------------------------------------------------
    # Job log

    @pyqtSlot()
    def _on_job_log(self):
        from app.gui.dialogs.job_log_dialog import JobLogDialog
        dlg = JobLogDialog(self)
        dlg.exec()

    # ------------------------------------------------------------------
    # WCS offset

    def _on_wcs_changed(self):
        self._project.work_offset_x = self._spin_wcs_x.value()
        self._project.work_offset_y = self._spin_wcs_y.value()
        self._project.modified = True
        self._canvas.update()
        self._update_title()

    def _on_wcs_reset(self):
        self._project.work_offset_x = 0.0
        self._project.work_offset_y = 0.0
        self._sync_wcs_spinboxes()
        self._project.modified = True
        self._canvas.update()
        self._update_title()

    def _on_wcs_bake(self):
        ox = self._project.work_offset_x
        oy = self._project.work_offset_y
        if ox == 0.0 and oy == 0.0:
            return
        old_transforms = {o.id: o.transform.copy() for o in self._project.objects}
        for obj in self._project.objects:
            obj.transform.offset_x += ox
            obj.transform.offset_y += oy
            obj._invalidate()
        new_transforms = {o.id: o.transform.copy() for o in self._project.objects}
        self._project.work_offset_x = 0.0
        self._project.work_offset_y = 0.0
        self._sync_wcs_spinboxes()
        self._project.modified = True
        self._canvas.update()
        self._object_panel.refresh_list()
        self._object_panel.refresh_props()
        self._update_title()

        def undo_bake():
            for obj in self._project.objects:
                if obj.id in old_transforms:
                    obj.transform = old_transforms[obj.id].copy()
                    obj._invalidate()
            self._project.work_offset_x = ox
            self._project.work_offset_y = oy
            self._sync_wcs_spinboxes()
            self._project.modified = True
            self._canvas.update()
            self._object_panel.refresh_list()
            self._object_panel.refresh_props()
            self._update_undo_actions()

        def redo_bake():
            for obj in self._project.objects:
                if obj.id in new_transforms:
                    obj.transform = new_transforms[obj.id].copy()
                    obj._invalidate()
            self._project.work_offset_x = 0.0
            self._project.work_offset_y = 0.0
            self._sync_wcs_spinboxes()
            self._project.modified = True
            self._canvas.update()
            self._object_panel.refresh_list()
            self._object_panel.refresh_props()
            self._update_undo_actions()

        self._undo.push(undo_bake, redo_bake, "Bake WCS offset")
        self._update_undo_actions()

    # ------------------------------------------------------------------
    # Z-Layer filter

    def _rebuild_z_layer_list(self):
        """Rebuild slider + checklist from all visible objects."""
        from PyQt6.QtWidgets import QListWidgetItem
        z_vals: set[float] = set()
        for obj in self._project.visible_objects():
            for m in obj.computed_moves:
                if m.pen_down and m.to_pos.z < 0:
                    z_vals.add(round(m.to_pos.z, 2))
        depths = sorted(z_vals, reverse=True)   # shallowest first
        self._z_depths = depths

        visible = len(depths) > 1
        self._z_filter_box.setVisible(visible)
        self._canvas.set_z_filter(None)
        if not visible:
            return

        n = len(depths)

        # Slider
        self._z_slider.blockSignals(True)
        self._z_slider.setMinimum(0)
        self._z_slider.setMaximum(n - 1)
        self._z_slider.setTickInterval(1)
        self._z_slider.setValue(n - 1)
        self._z_slider.blockSignals(False)
        self._z_slider_label.setText("Alle Ebenen")

        # Checklist
        self._z_layer_list.blockSignals(True)
        self._z_layer_list.clear()
        for i, z in enumerate(depths):
            item = QListWidgetItem(f"Pass {i + 1}  —  {z:.2f} mm")
            item.setData(Qt.ItemDataRole.UserRole, z)
            item.setCheckState(Qt.CheckState.Checked)
            self._z_layer_list.addItem(item)
        self._z_layer_list.blockSignals(False)

    def _on_z_slider_changed(self, idx: int):
        """Slider moved → update checklist and canvas (cumulative: show passes 0..idx)."""
        if not self._z_depths:
            return
        idx = max(0, min(idx, len(self._z_depths) - 1))
        n = len(self._z_depths)
        show = frozenset(self._z_depths[:idx + 1])

        # Sync checklist
        self._z_layer_list.blockSignals(True)
        for i in range(self._z_layer_list.count()):
            item = self._z_layer_list.item(i)
            z = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(
                Qt.CheckState.Checked if z in show else Qt.CheckState.Unchecked
            )
        self._z_layer_list.blockSignals(False)

        # Canvas + label
        if idx == n - 1:
            self._canvas.set_z_filter(None)
            self._z_slider_label.setText("Alle Ebenen")
        else:
            self._canvas.set_z_filter(show)
            self._z_slider_label.setText(
                f"bis {self._z_depths[idx]:.2f} mm  ({idx + 1}/{n})"
            )

    def _on_z_item_changed(self, _item):
        """Checkbox toggled → update canvas; try to sync slider."""
        if not self._z_depths:
            return
        checked: set[float] = set()
        for i in range(self._z_layer_list.count()):
            it = self._z_layer_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                checked.add(it.data(Qt.ItemDataRole.UserRole))

        n = len(self._z_depths)
        if len(checked) == n:
            self._canvas.set_z_filter(None)
            self._z_slider_label.setText("Alle Ebenen")
            self._z_slider.blockSignals(True)
            self._z_slider.setValue(n - 1)
            self._z_slider.blockSignals(False)
            return

        self._canvas.set_z_filter(frozenset(checked) if checked else frozenset())

        # Try to match a slider prefix position
        prefix_idx = -1
        for k in range(n):
            if checked == set(self._z_depths[:k + 1]):
                prefix_idx = k
                break

        if prefix_idx >= 0:
            self._z_slider.blockSignals(True)
            self._z_slider.setValue(prefix_idx)
            self._z_slider.blockSignals(False)
            self._z_slider_label.setText(
                f"bis {self._z_depths[prefix_idx]:.2f} mm  ({prefix_idx + 1}/{n})"
            )
        else:
            # Non-contiguous selection — leave slider, update label
            self._z_slider_label.setText(
                f"{len(checked)} von {n} Pässen"
                + (" (individuell)" if checked else " — keine")
            )

    def _z_filter_reset(self):
        if self._z_depths:
            self._z_slider.setValue(len(self._z_depths) - 1)

    # ------------------------------------------------------------------
    # Machine / serial actions

    @pyqtSlot()
    def _on_connect(self):
        from app.gui.dialogs.serial_dialog import SerialSettingsDialog
        dlg = SerialSettingsDialog(self._config.serial, self)
        if dlg.exec():
            self._config.serial = dlg.get_config()
            self._config.save()
        sc = self._config.serial
        try:
            self._serial_port = serial.Serial(
                port=sc.port,
                baudrate=sc.baud,
                bytesize=sc.bytesize,
                parity=sc.parity,
                stopbits=sc.stopbits,
                timeout=2,
            )
            self._send_panel.set_connected(True)
            self._status_bar.showMessage(f"Connected to {sc.port} — checking machine…")
            self._check_machine_on_connect()
            self._status_bar.showMessage(f"Connected to {sc.port}")
        except Exception as e:
            QMessageBox.critical(self, "Connection error", str(e))
            self._send_panel.set_connected(False)

    def _check_machine_on_connect(self):
        """Send OH and ZI commands and warn if machine replies unexpectedly."""
        import time as _time

        def _read_response(cmd: bytes, timeout: float = 2.0) -> str:
            try:
                self._serial_port.write(cmd)
                deadline = _time.time() + timeout
                buf = b""
                while _time.time() < deadline:
                    waiting = self._serial_port.in_waiting
                    if waiting:
                        buf += self._serial_port.read(waiting)
                    if buf and _time.time() > deadline - timeout + 0.3:
                        break
                    _time.sleep(0.05)
                return buf.decode(errors="replace").strip()
            except Exception:
                return ""

        # OH returns the hard limits: minx,miny,maxx,maxy in plotter units.
        # ME-500 at 0.01 mm (MGL-IIC3): 483 mm × 305 mm → 0,0,48300,30500
        oh_resp = _read_response(b"OH;\n")
        if oh_resp:
            parts = oh_resp.split(",")
            if len(parts) == 4:
                try:
                    maxx, maxy = int(parts[2]), int(parts[3])
                    if maxx != 48300 or maxy != 30500:
                        QMessageBox.warning(
                            self, "Plottereinheit prüfen",
                            "Die Maschine scheint nicht auf 0,01 mm (MGL-IIC3) eingestellt zu sein.\n\n"
                            f"OH-Antwort: {oh_resp!r}\n"
                            "Erwartet für ME-500 bei 0,01 mm: '0,0,48300,30500'\n\n"
                            "Bitte Plottereinheit in den Maschineneinstellungen prüfen.",
                        )
                except ValueError:
                    QMessageBox.warning(
                        self, "Plottereinheit",
                        f"OH-Antwort konnte nicht ausgewertet werden: {oh_resp!r}",
                    )
            else:
                QMessageBox.warning(
                    self, "Plottereinheit",
                    f"OH-Antwort hat unerwartetes Format: {oh_resp!r}\n"
                    "Erwartet: 'minx,miny,maxx,maxy'",
                )

        zi_resp = _read_response(b"ZI;\n")
        if zi_resp and "ME500" not in zi_resp:
            QMessageBox.warning(
                self, "Machine Check",
                f"Unbekannte Maschine — erwartet 'ME500', erhalten: {zi_resp!r}\n\n"
                "Bitte Verbindung und Einstellungen prüfen.",
            )

    @pyqtSlot()
    def _on_disconnect(self):
        if self._serial_port and self._serial_port.is_open:
            self._serial_port.close()
        self._serial_port = None
        self._send_panel.set_connected(False)
        self._status_bar.showMessage("Disconnected")

    @pyqtSlot()
    def _on_send(self):
        self._start_send(scope="all", start_index=0)

    @pyqtSlot()
    def _on_send_from(self):
        from app.gui.dialogs.send_from_dialog import SendFromDialog
        dlg = SendFromDialog(self._project, self)
        dlg.preview_move_changed.connect(self._on_preview_move)
        try:
            accepted = dlg.exec()
        finally:
            self._canvas.clear_preview_pos()
        if accepted:
            scope, start_index, selected_id = dlg.get_result()
            self._start_send(scope=scope, start_index=start_index,
                             selected_id=selected_id)

    @pyqtSlot(float, float)
    def _on_preview_move(self, x: float, y: float):
        if x < 0:
            self._canvas.clear_preview_pos()
        else:
            self._canvas.set_preview_pos(x, y)

    @pyqtSlot()
    def _on_send_selected(self):
        sel_id = self._canvas._selected_id
        if not sel_id:
            QMessageBox.information(self, "Send", "Please select an object first.")
            return
        self._start_send(scope="selected", selected_id=sel_id)

    def _start_send(
        self,
        scope: str = "all",
        start_index: int = 0,
        selected_id: str = "",
    ):
        if not self._serial_port or not self._serial_port.is_open:
            QMessageBox.warning(self, "Send", "Not connected to machine.")
            return

        # Collision check — test actual move segments against forbidden zones,
        # using the bounding box only as a fast pre-filter.
        for obj in self._project.visible_objects():
            bb = obj.bounding_box
            candidate_zones = [
                z for z in self._project.forbidden_zones
                if z.overlaps_rect(bb.min_x, bb.min_y, bb.width, bb.height)
            ]
            if not candidate_zones:
                continue
            for move in obj.computed_moves:
                if not move.xy_move:
                    continue
                ax, ay = move.from_pos.x, move.from_pos.y
                bx, by = move.to_pos.x, move.to_pos.y
                for zone in candidate_zones:
                    if zone.intersects_segment(ax, ay, bx, by):
                        name = zone.label or "Forbidden zone"
                        QMessageBox.critical(
                            self, "Send blocked",
                            f"Object '{obj.label}' enters {name!r}.",
                        )
                        return

        # Pre-send checklist
        reply = QMessageBox.question(
            self, "Vor dem Senden bestätigen",
            "Bitte vor dem Start sicherstellen:\n\n"
            "  •  Z-Achse auf Oberflächen-Nullpunkt kalibriert?\n"
            "  •  X/Y auf Ursprung 0 / 0 eingestellt?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Collect moves
        if scope == "selected" and selected_id:
            obj = self._project.object_by_id(selected_id)
            moves = obj.computed_moves if obj else []
        else:
            moves = []
            for obj in self._project.visible_objects():
                moves.extend(obj.computed_moves)

        moves = moves[start_index:]
        if not moves:
            QMessageBox.information(self, "Send", "No moves to send.")
            return

        self._send_panel.clear_log()
        self._send_panel.set_progress(0, len(moves))
        self._send_panel.set_sending(True)
        self._job_start_time = time.time()
        self._job_move_count = len(moves)

        self._sender.configure(
            port=self._serial_port,
            moves=moves,
            speeds=self._project.speeds,
            throttle_factor=self._config.serial.throttle_factor,
            use_zi_sync=self._config.serial.use_zi_sync,
            offset_x=self._project.work_offset_x,
            offset_y=self._project.work_offset_y,
        )
        self._sender.start()

    @pyqtSlot()
    def _on_send_bounds(self):
        if not self._serial_port or not self._serial_port.is_open:
            QMessageBox.warning(self, "Bounds preview", "Not connected.")
            return
        vis = self._project.visible_objects()
        if not vis:
            return
        from app.io.hpgl_writer import limits_to_hpgl
        min_x = min(o.bounding_box.min_x for o in vis)
        min_y = min(o.bounding_box.min_y for o in vis)
        max_x = max(o.bounding_box.max_x for o in vis)
        max_y = max(o.bounding_box.max_y for o in vis)
        self._serial_port.write(limits_to_hpgl(min_x, min_y, max_x, max_y))

    @pyqtSlot()
    def _on_pause(self):
        self._sender.pause()

    @pyqtSlot()
    def _on_resume(self):
        self._sender.resume()

    @pyqtSlot()
    def _on_stop(self):
        self._sender.stop()

    # ------------------------------------------------------------------
    # Sender callbacks

    @pyqtSlot(int, int)
    def _on_send_progress(self, sent: int, total: int):
        self._send_panel.set_progress(sent, total)
        remaining_moves = total - sent
        if total > 0:
            elapsed_frac = sent / total
            est_total = self._project.estimate_duration_seconds()
            remaining = est_total * (1 - elapsed_frac)
            self._send_panel.set_remaining(remaining)

    @pyqtSlot()
    def _on_job_finished(self):
        self._send_panel.set_sending(False)
        self._status_bar.showMessage("Job finished.")
        self._write_log_entry("finished")

    @pyqtSlot()
    def _on_job_stopped(self):
        self._send_panel.set_sending(False)
        self._status_bar.showMessage("Job stopped.")
        self._write_log_entry("stopped")

    @pyqtSlot(str)
    def _on_send_error(self, msg: str):
        self._send_panel.set_sending(False)
        self._write_log_entry("error", msg)
        QMessageBox.critical(self, "Send error", msg)

    def _write_log_entry(self, status: str, error_msg: str = ""):
        from app.io.job_log import LogEntry, append_entry
        import datetime
        duration = time.time() - self._job_start_time if self._job_start_time > 0 else 0.0
        entry = LogEntry(
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            project_file=self._project.filepath,
            move_count=self._job_move_count,
            duration_seconds=round(duration, 1),
            status=status,
            error_message=error_msg,
        )
        try:
            append_entry(entry)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Canvas ↔ Panel sync

    @pyqtSlot(str)
    def _on_canvas_select(self, obj_id: str):
        self._object_panel.select_object(obj_id)

    @pyqtSlot(str, float, float)
    def _on_canvas_moved(self, obj_id: str, ox: float, oy: float):
        self._object_panel.refresh_props()
        self._update_duration()
        self._project.modified = True
        self._update_title()

    @pyqtSlot(str, object, object)
    def _on_drag_committed(self, obj_id: str, old_t: Transform, new_t: Transform):
        """Canvas drag finished — push undo entry."""
        self._push_transform_undo(obj_id, old_t, new_t, "Move/rotate")

    @pyqtSlot(str, object)
    def _on_panel_transform_changed(self, obj_id: str, old_t):
        """Panel spinbox committed — push undo if old_t provided, refresh canvas."""
        self._canvas.update()
        self._update_duration()
        self._project.modified = True
        self._update_title()
        if old_t is not None and obj_id:
            obj = self._project.object_by_id(obj_id)
            if obj:
                self._push_transform_undo(obj_id, old_t, obj.transform.copy(), "Edit")

    def _push_transform_undo(
        self, obj_id: str, old_t: Transform, new_t: Transform, desc: str
    ):
        def undo():
            obj = self._project.object_by_id(obj_id)
            if obj:
                obj.transform = old_t.copy()
                obj._invalidate()
                self._canvas.update()
                self._object_panel.refresh_props()
                self._update_duration()
                self._update_undo_actions()

        def redo():
            obj = self._project.object_by_id(obj_id)
            if obj:
                obj.transform = new_t.copy()
                obj._invalidate()
                self._canvas.update()
                self._object_panel.refresh_props()
                self._update_duration()
                self._update_undo_actions()

        self._undo.push(undo, redo, desc)
        self._update_undo_actions()

    def _update_undo_actions(self):
        self._act_undo.setEnabled(self._undo.can_undo)
        self._act_undo.setText(
            f"&Undo {self._undo.undo_description}" if self._undo.can_undo else "&Undo"
        )
        self._act_redo.setEnabled(self._undo.can_redo)
        self._act_redo.setText(
            f"&Redo {self._undo.redo_description}" if self._undo.can_redo else "&Redo"
        )

    @pyqtSlot()
    def _on_undo(self):
        self._undo.undo()
        self._update_undo_actions()

    @pyqtSlot()
    def _on_redo(self):
        self._undo.redo()
        self._update_undo_actions()

    @pyqtSlot(str)
    def _on_panel_select(self, obj_id: str):
        self._canvas.set_selected(obj_id)

    @pyqtSlot(str, str)
    def _on_canvas_context_action(self, action: str, obj_id: str):
        self._canvas.set_selected(obj_id)
        self._object_panel.select_object(obj_id)
        if action == "clone":
            self._on_clone()
        elif action == "delete":
            self._on_delete_selected()
        elif action == "mirror_h":
            self._mirror_selected("h")
        elif action == "mirror_v":
            self._mirror_selected("v")
        elif action == "reset_transform":
            obj = self._project.object_by_id(obj_id)
            if obj:
                old_t = obj.transform.copy()
                obj.reset_transform()
                self._push_transform_undo(obj_id, old_t, obj.transform.copy(), "Reset transform")
                self._canvas.update()
                self._object_panel.refresh_props()
        elif action == "reset_pivot":
            obj = self._project.object_by_id(obj_id)
            if obj:
                old_t = obj.transform.copy()
                obj.reset_pivot()
                self._push_transform_undo(obj_id, old_t, obj.transform.copy(), "Reset pivot")
                self._canvas.update()
                self._object_panel.refresh_props()

    @pyqtSlot(float, float)
    def _on_cursor_moved(self, wx: float, wy: float):
        self._coord_label.setText(f"X: {wx:.2f}  Y: {wy:.2f}")

    # ------------------------------------------------------------------
    # Speed combos

    def _sync_speed_spinboxes(self):
        spd = self._project.speeds
        for cmb in (self._cmb_xy_travel, self._cmb_xy_machine,
                    self._cmb_z_travel, self._cmb_z_machine):
            cmb.blockSignals(True)
        self._select_speed(self._cmb_xy_travel, spd.xy_travel_mm_min)
        self._select_speed(self._cmb_xy_machine, spd.xy_machining_mm_min)
        self._select_speed(self._cmb_z_travel, spd.z_travel_mm_min)
        self._select_speed(self._cmb_z_machine, spd.z_machining_mm_min)
        for cmb in (self._cmb_xy_travel, self._cmb_xy_machine,
                    self._cmb_z_travel, self._cmb_z_machine):
            cmb.blockSignals(False)
        self._sync_wcs_spinboxes()

    def _sync_wcs_spinboxes(self):
        self._spin_wcs_x.blockSignals(True)
        self._spin_wcs_y.blockSignals(True)
        self._spin_wcs_x.setValue(self._project.work_offset_x)
        self._spin_wcs_y.setValue(self._project.work_offset_y)
        self._spin_wcs_x.blockSignals(False)
        self._spin_wcs_y.blockSignals(False)

    def _on_speed_changed(self):
        spd = self._project.speeds
        spd.xy_travel_mm_min = self._cmb_xy_travel.currentData()
        spd.xy_machining_mm_min = self._cmb_xy_machine.currentData()
        spd.z_travel_mm_min = self._cmb_z_travel.currentData()
        spd.z_machining_mm_min = self._cmb_z_machine.currentData()
        self._update_duration()

    def _update_duration(self):
        secs = self._project.estimate_duration_seconds()
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = int(secs % 60)
        self._lbl_duration.setText(f"Est. duration: {h:02d}:{m:02d}:{s:02d}")

    # ------------------------------------------------------------------
    # Zone delete (with undo)

    @pyqtSlot(str)
    def _on_zone_delete_requested(self, zone_id: str):
        zone = next((z for z in self._project.forbidden_zones if z.id == zone_id), None)
        if not zone:
            return
        zone_index = self._project.forbidden_zones.index(zone)

        def undo_zone_delete():
            self._project.forbidden_zones.insert(zone_index, zone)
            self._project.modified = True
            self._canvas.update()
            self._update_undo_actions()

        def redo_zone_delete():
            if zone in self._project.forbidden_zones:
                self._project.forbidden_zones.remove(zone)
            self._canvas._selected_zone_id = ""
            self._project.modified = True
            self._canvas.update()
            self._update_undo_actions()

        redo_zone_delete()
        self._undo.push(undo_zone_delete, redo_zone_delete, "Delete zone")
        self._update_undo_actions()
        self._update_title()

    @pyqtSlot(str)
    def _on_zone_rename_requested(self, zone_id: str):
        zone = next((z for z in self._project.forbidden_zones if z.id == zone_id), None)
        if not zone:
            return
        new_label, ok = QInputDialog.getText(
            self, "Rename Zone", "Zone name:", text=zone.label
        )
        if not ok or new_label == zone.label:
            return
        old_label = zone.label
        zone.label = new_label
        self._project.modified = True
        self._canvas.update()
        self._update_title()

        def undo_rename():
            zone.label = old_label
            self._project.modified = True
            self._canvas.update()
            self._update_undo_actions()

        def redo_rename():
            zone.label = new_label
            self._project.modified = True
            self._canvas.update()
            self._update_undo_actions()

        self._undo.push(undo_rename, redo_rename, "Rename zone")
        self._update_undo_actions()

    @pyqtSlot(str)
    def _on_zone_edit_requested(self, zone_id: str):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout
        zone = next((z for z in self._project.forbidden_zones if z.id == zone_id), None)
        if not zone:
            return
        old_state = {"x": zone.x, "y": zone.y, "width": zone.width, "height": zone.height}

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit Zone — {zone.label or zone_id[:8]}")
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        layout.addLayout(form)

        def _spin(lo, hi, val):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(2)
            s.setSuffix(" mm")
            s.setSingleStep(1.0)
            s.setValue(val)
            return s

        sp_x = _spin(-500, 500, zone.x)
        sp_y = _spin(-500, 500, zone.y)
        sp_w = _spin(0.1, 1000, zone.width)
        sp_h = _spin(0.1, 1000, zone.height)
        form.addRow("X (links):", sp_x)
        form.addRow("Y (unten):", sp_y)
        form.addRow("Breite:", sp_w)
        form.addRow("Höhe:", sp_h)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if not dlg.exec():
            return

        new_state = {
            "x": sp_x.value(), "y": sp_y.value(),
            "width": sp_w.value(), "height": sp_h.value(),
        }
        if new_state == old_state:
            return

        zone.x, zone.y = new_state["x"], new_state["y"]
        zone.width, zone.height = new_state["width"], new_state["height"]
        self._project.modified = True
        self._canvas.update()
        self._update_title()

        def apply_state(state: dict):
            zone.x, zone.y = state["x"], state["y"]
            zone.width, zone.height = state["width"], state["height"]
            self._project.modified = True
            self._canvas.update()
            self._update_undo_actions()

        self._undo.push(lambda: apply_state(old_state), lambda: apply_state(new_state),
                        "Edit zone coordinates")
        self._update_undo_actions()

    @pyqtSlot(str, object, object)
    def _on_zone_changed(self, zone_id: str, old_state: dict, new_state: dict):
        zone = next((z for z in self._project.forbidden_zones if z.id == zone_id), None)
        if not zone:
            return

        def apply_state(state: dict):
            zone.x = state["x"]
            zone.y = state["y"]
            zone.width = state["width"]
            zone.height = state["height"]
            self._project.modified = True
            self._canvas.update()
            self._update_undo_actions()

        self._project.modified = True
        self._update_title()
        self._undo.push(lambda: apply_state(old_state), lambda: apply_state(new_state), "Move/resize zone")
        self._update_undo_actions()

    # ------------------------------------------------------------------
    # Missing source file relocation

    def _relocate_missing(self, project, missing: list[tuple[str, dict]]):
        for src_path, obj_data in missing:
            reply = QMessageBox.question(
                self, "Missing source file",
                f"Could not find:\n{src_path}\n\nLocate it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                continue
            new_path, _ = QFileDialog.getOpenFileName(
                self, "Locate G-code file",
                os.path.dirname(src_path),
                "G-code files (*.gcode *.nc *.tap *.txt);;All files (*)",
            )
            if not new_path:
                continue
            try:
                with open(new_path) as f:
                    text = f.read()
                parse_result = parse_gcode(text)
                obj = GcodeObject.from_dict(obj_data, parse_result.moves)
                obj.source_file = new_path
                project.objects.append(obj)
            except Exception as e:
                QMessageBox.warning(self, "Import error", str(e))

    # ------------------------------------------------------------------
    # Recent files

    def _update_recent_menu(self):
        self._recent_menu.clear()
        if not self._config.recent_files:
            act = QAction("(no recent files)", self)
            act.setEnabled(False)
            self._recent_menu.addAction(act)
        else:
            for path in self._config.recent_files[:10]:
                act = QAction(os.path.basename(path), self)
                act.setStatusTip(path)
                act.triggered.connect(lambda checked, p=path: self._open_recent(p))
                self._recent_menu.addAction(act)

    def _open_recent(self, path: str):
        if not os.path.exists(path):
            QMessageBox.warning(self, "Recent file", f"File not found:\n{path}")
            if path in self._config.recent_files:
                self._config.recent_files.remove(path)
                self._config.save()
            self._update_recent_menu()
            return
        try:
            project, missing = load_project(path)
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))
            return
        self._relocate_missing(project, missing)
        self._project = project
        self._canvas.set_project(project)
        self._object_panel.set_project(project)
        self._sync_speed_spinboxes()
        self._canvas.update()
        self._update_duration()
        self._rebuild_z_layer_list()
        self._config.last_project_dir = os.path.dirname(path)
        self._config.add_recent_file(path)
        self._config.save()
        self._update_title()
        self._update_recent_menu()

    # ------------------------------------------------------------------
    # Misc

    def _on_serial_settings(self):
        from app.gui.dialogs.serial_dialog import SerialSettingsDialog
        dlg = SerialSettingsDialog(self._config.serial, self)
        if dlg.exec():
            self._config.serial = dlg.get_config()
            self._config.save()

    def _on_about(self):
        QMessageBox.about(
            self,
            "About Mimaki ME-500 GUI",
            "<b>Mimaki ME-500 GUI</b><br>"
            "G-code to HPGL layout and transmission tool.<br><br>"
            "Machine: Mimaki ME-500 (483 × 305 mm)",
        )

    def _update_title(self):
        name = os.path.basename(self._project.filepath) if self._project.filepath else "Untitled"
        mod = " *" if self._project.modified else ""
        self.setWindowTitle(f"Mimaki ME-500 GUI — {name}{mod}")

    def closeEvent(self, event: QCloseEvent):
        if self._project.modified:
            reply = QMessageBox.question(
                self, "Unsaved changes",
                "Project has unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._on_save()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self._config.save()
        event.accept()
