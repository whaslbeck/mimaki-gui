from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QVBoxLayout, QLabel,
)

from app.config import SerialConfig


class SerialSettingsDialog(QDialog):
    def __init__(self, config: SerialConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Serial Port Settings")
        self._config = config
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._port = QLineEdit(self._config.port)
        form.addRow("Port (e.g. /dev/ttyUSB0)", self._port)

        self._baud = QComboBox()
        for b in [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]:
            self._baud.addItem(str(b), b)
        idx = self._baud.findData(self._config.baud)
        if idx >= 0:
            self._baud.setCurrentIndex(idx)
        form.addRow("Baud rate", self._baud)

        self._bytesize = QComboBox()
        for b in [5, 6, 7, 8]:
            self._bytesize.addItem(str(b), b)
        idx = self._bytesize.findData(self._config.bytesize)
        if idx >= 0:
            self._bytesize.setCurrentIndex(idx)
        form.addRow("Data bits", self._bytesize)

        self._parity = QComboBox()
        for p in [("None", "N"), ("Even", "E"), ("Odd", "O")]:
            self._parity.addItem(p[0], p[1])
        idx = self._parity.findData(self._config.parity)
        if idx >= 0:
            self._parity.setCurrentIndex(idx)
        form.addRow("Parity", self._parity)

        self._stopbits = QComboBox()
        for s in [(1, 1), (2, 2)]:
            self._stopbits.addItem(str(s[0]), s[1])
        idx = self._stopbits.findData(self._config.stopbits)
        if idx >= 0:
            self._stopbits.setCurrentIndex(idx)
        form.addRow("Stop bits", self._stopbits)

        self._rtscts = QCheckBox("Hardware flow control (RTS/CTS)")
        self._rtscts.setChecked(self._config.rtscts)
        self._rtscts.setToolTip(
            "Enable if the cable has RTS/CTS wired and the machine supports it.\n"
            "The machine asserts CTS when its buffer is full — the most reliable\n"
            "flow-control method, requiring no software workarounds."
        )
        form.addRow("", self._rtscts)

        # ── Synchronisation ──
        form.addRow(QLabel(""))   # spacer

        self._sync_mode = QComboBox()
        self._sync_mode.addItem(
            "Time-based throttle  (no machine feedback)", "throttle"
        )
        self._sync_mode.addItem(
            "OS; query  (experimental — waits for machine response)", "os_query"
        )
        idx = self._sync_mode.findData(self._config.sync_mode)
        if idx >= 0:
            self._sync_mode.setCurrentIndex(idx)
        self._sync_mode.setToolTip(
            "Throttle: waits estimated move duration × factor — blind, no machine feedback.\n\n"
            "OS; query: inserts OS; into the HPGL stream every N commands and blocks\n"
            "until the machine responds. OS; is queued sequentially, so the response\n"
            "arrives only after all preceding commands have been executed.\n"
            "With N=1 the machine buffer is always empty when the PC waits,\n"
            "giving near-real-time pause/stop accuracy and exact resume position."
        )
        self._sync_mode.currentIndexChanged.connect(self._on_sync_changed)
        form.addRow("Sync mode:", self._sync_mode)

        self._throttle = QDoubleSpinBox()
        self._throttle.setRange(0.1, 2.0)
        self._throttle.setSingleStep(0.05)
        self._throttle.setDecimals(2)
        self._throttle.setValue(self._config.throttle_factor)
        self._throttle.setToolTip(
            "Multiplier applied to the estimated move duration.\n"
            "< 1.0 = faster (risk of buffer overflow)\n"
            "> 1.0 = slower (safer margin)"
        )
        form.addRow("Throttle factor:", self._throttle)

        self._os_interval = QSpinBox()
        self._os_interval.setRange(1, 500)
        self._os_interval.setValue(self._config.os_sync_interval)
        self._os_interval.setToolTip(
            "N=1 (recommended): after every single HPGL command.\n"
            "  → Machine buffer is always empty when PC waits.\n"
            "  → Pause/Stop take effect within one move's execution time.\n"
            "  → Last confirmed position is exact (useful after tool break).\n"
            "  → Round-trip overhead ≈ 10–20 ms — negligible at cutting speeds.\n\n"
            "N>1: reduce OS; queries for very fast machines or high move counts.\n"
            "  Machine can be up to N commands ahead of the PC."
        )
        form.addRow("Look-ahead (moves):", self._os_interval)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_sync_changed()

    def _on_sync_changed(self):
        mode = self._sync_mode.currentData()
        self._throttle.setEnabled(mode == "throttle")
        self._os_interval.setEnabled(mode == "os_query")

    def get_config(self) -> SerialConfig:
        return SerialConfig(
            port=self._port.text().strip(),
            baud=self._baud.currentData(),
            bytesize=self._bytesize.currentData(),
            parity=self._parity.currentData(),
            stopbits=self._stopbits.currentData(),
            rtscts=self._rtscts.isChecked(),
            sync_mode=self._sync_mode.currentData(),
            throttle_factor=self._throttle.value(),
            os_sync_interval=self._os_interval.value(),
        )
