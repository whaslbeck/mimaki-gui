from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QVBoxLayout,
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

        self._throttle = QDoubleSpinBox()
        self._throttle.setRange(0.1, 2.0)
        self._throttle.setSingleStep(0.05)
        self._throttle.setDecimals(2)
        self._throttle.setValue(self._config.throttle_factor)
        form.addRow("Throttle factor", self._throttle)

        self._zi_sync = QCheckBox("Use ZI synchronisation (experimental)")
        self._zi_sync.setChecked(self._config.use_zi_sync)
        form.addRow("", self._zi_sync)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_config(self) -> SerialConfig:
        return SerialConfig(
            port=self._port.text().strip(),
            baud=self._baud.currentData(),
            bytesize=self._bytesize.currentData(),
            parity=self._parity.currentData(),
            stopbits=self._stopbits.currentData(),
            throttle_factor=self._throttle.value(),
            use_zi_sync=self._zi_sync.isChecked(),
        )
