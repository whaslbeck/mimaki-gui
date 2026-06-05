from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QProgressBar,
    QLabel, QPlainTextEdit, QGroupBox, QCheckBox, QSlider, QSizePolicy,
)

from app.config import AppConfig

_JOG_STEPS = [0.1, 1.0, 10.0]   # mm


class SendPanel(QWidget):
    connect_requested      = pyqtSignal()
    disconnect_requested   = pyqtSignal()
    send_requested         = pyqtSignal()
    send_from_requested    = pyqtSignal()
    send_selected_requested = pyqtSignal()
    pause_requested        = pyqtSignal()
    resume_requested       = pyqtSignal()
    stop_requested         = pyqtSignal()
    jog_requested          = pyqtSignal(float, float)   # dx_mm, dy_mm
    jog_home_requested     = pyqtSignal()
    feed_override_changed  = pyqtSignal(float)          # factor (1.0 = 100%)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected = False
        self._sending = False
        self._jog_step = 1.0
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)

        # --- Left: controls ---
        ctrl = QVBoxLayout()
        ctrl.setSpacing(4)

        # Connection row
        conn_row = QHBoxLayout()
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setCheckable(True)
        self._btn_connect.clicked.connect(self._on_connect_toggle)
        conn_row.addWidget(self._btn_connect)
        self._lbl_status = QLabel("Disconnected")
        self._lbl_status.setStyleSheet("color: #CC0000;")
        conn_row.addWidget(self._lbl_status)
        conn_row.addStretch()
        ctrl.addLayout(conn_row)

        # Send buttons + Dry Run
        send_row = QHBoxLayout()
        self._btn_send = QPushButton("Send (F5)")
        self._btn_send.clicked.connect(self.send_requested)
        send_row.addWidget(self._btn_send)
        self._btn_send_from = QPushButton("From… (⇧F5)")
        self._btn_send_from.clicked.connect(self.send_from_requested)
        send_row.addWidget(self._btn_send_from)
        self._btn_send_sel = QPushButton("Send Selected (^F5)")
        self._btn_send_sel.clicked.connect(self.send_selected_requested)
        send_row.addWidget(self._btn_send_sel)
        self._chk_dry_run = QCheckBox("Dry run")
        self._chk_dry_run.setToolTip(
            "Simulate toolpath without cutting:\n"
            "all moves sent as travel (PU), Z never engages."
        )
        send_row.addWidget(self._chk_dry_run)
        ctrl.addLayout(send_row)

        # Pause / Stop row
        ps_row = QHBoxLayout()
        self._btn_pause = QPushButton("Pause (F6)")
        self._btn_pause.setEnabled(False)
        self._btn_pause.setCheckable(True)
        self._btn_pause.clicked.connect(self._on_pause_toggle)
        ps_row.addWidget(self._btn_pause)
        self._btn_stop = QPushButton("Stop (F7)")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self.stop_requested)
        ps_row.addWidget(self._btn_stop)
        ctrl.addLayout(ps_row)

        # Feed override (visible only during send)
        self._feed_row = QWidget()
        feed_layout = QHBoxLayout(self._feed_row)
        feed_layout.setContentsMargins(0, 0, 0, 0)
        feed_layout.addWidget(QLabel("Feed:"))
        self._feed_slider = QSlider(Qt.Orientation.Horizontal)
        self._feed_slider.setRange(25, 200)
        self._feed_slider.setValue(100)
        self._feed_slider.setTickInterval(25)
        self._feed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._feed_slider.setToolTip("Feed rate override (25%–200%)")
        self._feed_slider.valueChanged.connect(self._on_feed_slider)
        feed_layout.addWidget(self._feed_slider, 1)
        self._lbl_feed = QLabel("100%")
        self._lbl_feed.setMinimumWidth(38)
        feed_layout.addWidget(self._lbl_feed)
        btn_feed_reset = QPushButton("×1")
        btn_feed_reset.setFixedWidth(32)
        btn_feed_reset.setToolTip("Reset to 100%")
        btn_feed_reset.clicked.connect(lambda: self._feed_slider.setValue(100))
        feed_layout.addWidget(btn_feed_reset)
        self._feed_row.setVisible(False)
        ctrl.addWidget(self._feed_row)

        # Progress + time
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%v / %m moves")
        ctrl.addWidget(self._progress)

        self._lbl_remaining = QLabel("Remaining: --:--:--")
        ctrl.addWidget(self._lbl_remaining)

        self._lbl_confirmed = QLabel()
        self._lbl_confirmed.setStyleSheet("color:#555; font-size:10px;")
        ctrl.addWidget(self._lbl_confirmed)

        # ── Jog group (hidden during send / disconnect) ──────────────
        self._jog_group = QGroupBox("Jog")
        jog_vl = QVBoxLayout(self._jog_group)
        jog_vl.setSpacing(4)
        jog_vl.setContentsMargins(6, 4, 6, 4)

        # Step size row
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Step:"))
        self._step_btns: list[QPushButton] = []
        for mm in _JOG_STEPS:
            lbl = f"{mm:g} mm"
            b = QPushButton(lbl)
            b.setCheckable(True)
            b.setFixedWidth(52)
            b.clicked.connect(lambda _chk, s=mm: self._set_jog_step(s))
            step_row.addWidget(b)
            self._step_btns.append(b)
        self._step_btns[1].setChecked(True)   # default: 1 mm
        step_row.addStretch()
        btn_home = QPushButton("⌂ 0,0")
        btn_home.setToolTip("Move to machine origin (PU 0,0)")
        btn_home.clicked.connect(self.jog_home_requested)
        step_row.addWidget(btn_home)
        jog_vl.addLayout(step_row)

        # D-pad
        dpad = QHBoxLayout()
        dpad.addStretch()
        grid_widget = QWidget()
        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout(grid_widget)
        grid.setSpacing(2)
        grid.setContentsMargins(0, 0, 0, 0)

        def _jog_btn(label: str, dx: float, dy: float) -> QPushButton:
            b = QPushButton(label)
            b.setFixedSize(38, 32)
            b.clicked.connect(lambda: self.jog_requested.emit(dx, dy))
            return b

        grid.addWidget(_jog_btn("Y+", 0, 1), 0, 1)
        grid.addWidget(_jog_btn("X−", -1, 0), 1, 0)
        # centre marker
        lbl_c = QLabel("·")
        lbl_c.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(lbl_c, 1, 1)
        grid.addWidget(_jog_btn("X+", 1, 0), 1, 2)
        grid.addWidget(_jog_btn("Y−", 0, -1), 2, 1)
        dpad.addWidget(grid_widget)
        dpad.addStretch()
        jog_vl.addLayout(dpad)

        self._jog_group.setVisible(False)
        ctrl.addWidget(self._jog_group)

        ctrl.addStretch()
        top.addLayout(ctrl, 1)

        # --- Right: log ---
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setFixedHeight(160)
        top.addWidget(self._log, 2)

        root.addLayout(top)

    # ------------------------------------------------------------------
    # Private

    def _set_jog_step(self, step_mm: float):
        self._jog_step = step_mm
        for i, b in enumerate(self._step_btns):
            b.setChecked(_JOG_STEPS[i] == step_mm)

    def _on_feed_slider(self, val: int):
        self._lbl_feed.setText(f"{val}%")
        self.feed_override_changed.emit(val / 100.0)

    def _update_jog_visibility(self):
        self._jog_group.setVisible(self._connected and not self._sending)

    # ------------------------------------------------------------------
    # Public API

    def set_connected(self, connected: bool):
        self._connected = connected
        if connected:
            self._btn_connect.setText("Disconnect")
            self._btn_connect.setChecked(True)
            self._lbl_status.setText("Connected")
            self._lbl_status.setStyleSheet("color: #008800;")
        else:
            self._btn_connect.setText("Connect")
            self._btn_connect.setChecked(False)
            self._lbl_status.setText("Disconnected")
            self._lbl_status.setStyleSheet("color: #CC0000;")
        self._update_jog_visibility()

    def set_sending(self, active: bool):
        self._sending = active
        self._btn_send.setEnabled(not active)
        self._btn_send_from.setEnabled(not active)
        self._btn_send_sel.setEnabled(not active)
        self._chk_dry_run.setEnabled(not active)
        self._btn_pause.setEnabled(active)
        self._btn_stop.setEnabled(active)
        self._feed_row.setVisible(active)
        if not active:
            self._btn_pause.setChecked(False)
            self._lbl_confirmed.clear()
            self._feed_slider.setValue(100)
        self._update_jog_visibility()

    def is_dry_run(self) -> bool:
        return self._chk_dry_run.isChecked()

    def set_confirmed(self, index: int):
        self._lbl_confirmed.setText(f"Confirmed executed: move {index + 1}")

    def set_progress(self, sent: int, total: int):
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(sent)
        self._progress.setFormat(f"{sent} / {total} moves")

    def set_remaining(self, seconds: float):
        if seconds < 0:
            self._lbl_remaining.setText("Remaining: --:--:--")
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            self._lbl_remaining.setText(f"Remaining: {h:02d}:{m:02d}:{s:02d}")

    def append_log(self, text: str):
        self._log.appendPlainText(text)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def clear_log(self):
        self._log.clear()

    def set_log_max_lines(self, n: int):
        self._log.setMaximumBlockCount(max(10, n))

    def jog_step(self) -> float:
        return self._jog_step

    # ------------------------------------------------------------------

    def _on_connect_toggle(self, checked: bool):
        if checked:
            self.connect_requested.emit()
        else:
            self.disconnect_requested.emit()

    def _on_pause_toggle(self, checked: bool):
        if checked:
            self.pause_requested.emit()
        else:
            self.resume_requested.emit()
