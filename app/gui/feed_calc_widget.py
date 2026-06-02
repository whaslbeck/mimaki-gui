"""Milling parameter calculator — chipload-based table.

For each spindle speed step the widget shows conservative / good /
aggressive feed rates and a per-row Apply button that writes the
selected feed directly into the project.

Formula:  feed [mm/s] = RPM × flutes × chipload [mm/tooth] × cutter_factor / 60
"""
from __future__ import annotations
from dataclasses import dataclass

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QDoubleSpinBox, QSpinBox, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QSizePolicy, QFrame,
)

from app.config import AppConfig

# ── Machine constants ──────────────────────────────────────────────────────────
_RPM_STEPS = [4000, 6000, 8000, 10000, 12000, 14000, 16000, 18000, 20000, 22000, 25000]
_FEED_STEPS_MMS = [0.5, 1, 2, 3, 5, 8, 10, 20, 30, 40, 50]


# ── Data classes ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Material:
    chip_conservative: float   # mm/tooth
    chip_good: float
    chip_aggressive: float
    max_feed_mms: float        # hard ceiling in mm/s
    notes: str


@dataclass(frozen=True)
class _CutterType:
    factor: float
    notes: str


_MATERIALS: dict[str, _Material] = {
    "Soft Wood": _Material(
        chip_conservative=0.030, chip_good=0.045, chip_aggressive=0.060,
        max_feed_mms=50,
        notes="Soft wood needs real chips, not dust. Too slow → heat / burn marks.",
    ),
    "Hard Wood": _Material(
        chip_conservative=0.020, chip_good=0.035, chip_aggressive=0.050,
        max_feed_mms=40,
        notes="Harder wood: be more conservative; watch for tearout and vibration.",
    ),
    "PVC": _Material(
        chip_conservative=0.020, chip_good=0.040, chip_aggressive=0.060,
        max_feed_mms=40,
        notes="PVC can smear. Prefer good chip evacuation; avoid excessive spindle speed.",
    ),
    "Aluminum": _Material(
        chip_conservative=0.008, chip_good=0.015, chip_aggressive=0.025,
        max_feed_mms=20,
        notes="Requires suitable end mill, rigid setup, lubrication/air blast, shallow DOC.",
    ),
    "Plexiglas (Acrylic)": _Material(
        chip_conservative=0.015, chip_good=0.030, chip_aggressive=0.045,
        max_feed_mms=30,
        notes="Acrylic melts from friction. Use sharp tool, make chips not dust, cool/blow.",
    ),
}

_CUTTER_TYPES: dict[str, _CutterType] = {
    "Straight flutes":       _CutterType(0.80, "Straight flutes: less chip evacuation — be conservative."),
    "Spiral upcut":          _CutterType(1.10, "Upcut: good chip evacuation; top edge may fray."),
    "Spiral downcut":        _CutterType(0.85, "Downcut: clean top edge; poorer chip evacuation."),
    "Compression":           _CutterType(1.00, "Compression: good for sheet material; DOC must match geometry."),
    "Single-flute / O-flute":_CutterType(1.15, "Single/O-flute: excellent chip evacuation; good for plastics and aluminium."),
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def _nearest_feed(f: float) -> float:
    return min(_FEED_STEPS_MMS, key=lambda x: abs(x - f))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _calc_feed_mms(rpm: int, flutes: int, chipload: float, factor: float) -> float:
    return rpm * flutes * chipload * factor / 60.0


# ── Widget ─────────────────────────────────────────────────────────────────────
class FeedCalcWidget(QWidget):
    """Chipload-based milling parameter table."""

    # Emits mm/min (internal project unit) when Apply is clicked in a row
    apply_requested = pyqtSignal(float)
    # Emitted when the user closes the window via the title-bar button
    window_closed = pyqtSignal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._loading = False
        self._setup_ui()
        self.refresh_tools()
        self._update_table()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.window_closed.emit()

    # ------------------------------------------------------------------
    # UI construction

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Inputs ────────────────────────────────────────────────────
        grp = QGroupBox("Parameters")
        form = QFormLayout(grp)
        form.setSpacing(4)

        self._cmb_mat = QComboBox()
        self._cmb_mat.addItems(list(_MATERIALS.keys()))
        self._cmb_mat.currentIndexChanged.connect(self._update_table)
        form.addRow("Material:", self._cmb_mat)

        self._cmb_cut = QComboBox()
        self._cmb_cut.addItems(list(_CUTTER_TYPES.keys()))
        self._cmb_cut.setCurrentIndex(1)   # Spiral upcut default
        self._cmb_cut.currentIndexChanged.connect(self._update_table)
        form.addRow("Cutter type:", self._cmb_cut)

        self._cmb_tool = QComboBox()
        self._cmb_tool.addItem("Manual…", None)
        self._cmb_tool.currentIndexChanged.connect(self._on_tool_changed)
        form.addRow("Tool preset:", self._cmb_tool)

        self._spin_diam = QDoubleSpinBox()
        self._spin_diam.setRange(0.001, 50)
        self._spin_diam.setDecimals(3)
        self._spin_diam.setSuffix(" mm")
        self._spin_diam.setSingleStep(0.125)
        self._spin_diam.setValue(3.175)
        self._spin_diam.setKeyboardTracking(False)
        self._spin_diam.valueChanged.connect(self._update_table)
        form.addRow("Diameter:", self._spin_diam)

        self._spin_flutes = QSpinBox()
        self._spin_flutes.setRange(1, 8)
        self._spin_flutes.setValue(2)
        self._spin_flutes.setKeyboardTracking(False)
        self._spin_flutes.valueChanged.connect(self._update_table)
        form.addRow("Flutes:", self._spin_flutes)

        self._spin_max_rpm = QSpinBox()
        self._spin_max_rpm.setRange(4000, 25000)
        self._spin_max_rpm.setSingleStep(1000)
        self._spin_max_rpm.setSuffix(" RPM")
        self._spin_max_rpm.setValue(25000)
        self._spin_max_rpm.setKeyboardTracking(False)
        self._spin_max_rpm.valueChanged.connect(self._update_table)
        form.addRow("Show up to:", self._spin_max_rpm)

        root.addWidget(grp)

        # ── Table ─────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "RPM", "Conservative", "Good", "Aggressive",
            "Chipload (c / g / a)", "⚠", "Apply",
        ])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._table, 1)

        # ── Notes ─────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        self._lbl_notes = QLabel()
        self._lbl_notes.setWordWrap(True)
        self._lbl_notes.setStyleSheet("color:#444; font-size:10px;")
        root.addWidget(self._lbl_notes)

    # ------------------------------------------------------------------
    # Tool preset

    def refresh_tools(self):
        self._loading = True
        prev = self._cmb_tool.currentData()
        self._cmb_tool.clear()
        self._cmb_tool.addItem("Manual…", None)
        for tp in self._config.tool_presets:
            self._cmb_tool.addItem(f"{tp.name}  (⌀ {tp.tool_diameter_mm:.3f} mm)", tp)
        for i in range(self._cmb_tool.count()):
            if self._cmb_tool.itemData(i) is prev:
                self._cmb_tool.setCurrentIndex(i)
                break
        self._loading = False
        self._on_tool_changed()

    def _on_tool_changed(self):
        if self._loading:
            return
        tp = self._cmb_tool.currentData()
        if tp is not None:
            self._spin_diam.setValue(tp.tool_diameter_mm)
            self._spin_diam.setEnabled(False)
        else:
            self._spin_diam.setEnabled(True)
        self._update_table()

    # ------------------------------------------------------------------
    # Table

    def _update_table(self):
        mat    = _MATERIALS.get(self._cmb_mat.currentText())
        cutter = _CUTTER_TYPES.get(self._cmb_cut.currentText())
        if mat is None or cutter is None:
            return

        flutes  = self._spin_flutes.value()
        diam    = self._spin_diam.value()
        max_rpm = self._spin_max_rpm.value()

        # Diameter correction: smaller → more conservative, larger → more generous
        diam_factor = _clamp((diam / 3.125) ** 0.25, 0.75, 1.25)

        chips = {
            "c": mat.chip_conservative * diam_factor,
            "g": mat.chip_good         * diam_factor,
            "a": mat.chip_aggressive   * diam_factor,
        }

        rpms = [r for r in _RPM_STEPS if r <= max_rpm]
        self._table.setRowCount(len(rpms))

        for row, rpm in enumerate(rpms):
            feeds_raw  = {k: _calc_feed_mms(rpm, flutes, chips[k], cutter.factor) for k in chips}
            feeds_clamp= {k: min(v, mat.max_feed_mms) for k, v in feeds_raw.items()}
            feeds_snap = {k: _nearest_feed(v) for k, v in feeds_clamp.items()}

            warnings = []
            if feeds_snap["c"] == feeds_snap["g"] == feeds_snap["a"]:
                warnings.append("grid too coarse")
            if rpm >= 20000 and mat is _MATERIALS.get("PVC"):
                warnings.append("smear risk")
            if rpm >= 20000 and mat is _MATERIALS.get("Plexiglas (Acrylic)"):
                warnings.append("melt risk")
            if mat is _MATERIALS.get("Aluminum") and flutes > 2:
                warnings.append("prefer 1–2 flutes for alu")

            def _cell(text: str, bold: bool = False) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if bold:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                return item

            self._table.setItem(row, 0, _cell(f"{rpm:,}".replace(",", ".") + " RPM"))
            self._table.setItem(row, 1, _cell(f"{feeds_snap['c']:g} mm/s"))
            self._table.setItem(row, 2, _cell(f"{feeds_snap['g']:g} mm/s", bold=True))
            self._table.setItem(row, 3, _cell(f"{feeds_snap['a']:g} mm/s"))
            self._table.setItem(row, 4, _cell(
                f"{chips['c']:.3f} / {chips['g']:.3f} / {chips['a']:.3f} mm/z"
            ))
            self._table.setItem(row, 5, _cell(", ".join(warnings)))

            # Apply button — captures the "good" feed for this row
            feed_good_mms = feeds_snap["g"]
            btn = QPushButton(f"Apply {feed_good_mms:g} mm/s")
            btn.setToolTip(
                f"Set XY machining speed to {feed_good_mms:g} mm/s "
                f"({feed_good_mms * 60:.0f} mm/min) — good feed at {rpm:,} RPM"
            )
            btn.clicked.connect(lambda _checked, f=feed_good_mms: self.apply_requested.emit(f * 60))
            self._table.setCellWidget(row, 6, btn)

        self._table.resizeColumnsToContents()

        self._lbl_notes.setText(
            f"Material: {mat.notes}\n"
            f"Cutter: {cutter.notes}\n"
            f"Machine feed steps: {_FEED_STEPS_MMS} mm/s  ·  "
            f"Diameter factor: {diam_factor:.2f}  ·  "
            f"Formula: RPM × flutes × chipload × cutter_factor / 60"
        )
