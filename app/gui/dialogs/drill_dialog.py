from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QComboBox, QDoubleSpinBox, QSpinBox, QLabel,
    QRadioButton, QWidget, QStackedWidget,
)

from app.model.types import Move

_PATTERNS = [
    "Single hole",
    "Rectangular grid",
    "Rectangular grid — staggered",
    "Holes on circle",
    "Circle area — grid",
    "Circle area — staggered grid",
    "Circle area — Fibonacci",
]

_PATTERN_SHORT = [
    "Single",
    "Grid",
    "Grid staggered",
    "Circle line",
    "Circle area grid",
    "Circle area staggered",
    "Fibonacci",
]


class DrillDialog(QDialog):
    """Generates drilling toolpaths for various hole patterns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Drilling Pattern…")
        self._result_moves: list[Move] = []
        self._last_n_holes: int = 0
        self._setup_ui()
        self._update_preview()

    # ------------------------------------------------------------------
    # Spin-box factories

    def _mm(self, lo: float, hi: float, val: float, dec: int = 1) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSuffix(" mm")
        s.setValue(val)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(self._update_preview)
        return s

    def _ispin(self, lo: int, hi: int, val: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(self._update_preview)
        return s

    # ------------------------------------------------------------------
    # UI construction

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Pattern selector
        self._cmb = QComboBox()
        self._cmb.addItems(_PATTERNS)
        self._cmb.currentIndexChanged.connect(self._on_pattern_changed)
        layout.addWidget(self._cmb)

        # Per-pattern parameter pages
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_single())
        self._stack.addWidget(self._page_grid(stagger=False))
        self._stack.addWidget(self._page_grid(stagger=True))
        self._stack.addWidget(self._page_circle_line())
        self._stack.addWidget(self._page_circle_area(stagger=False))
        self._stack.addWidget(self._page_circle_area(stagger=True))
        self._stack.addWidget(self._page_fibonacci())
        layout.addWidget(self._stack)

        # Shared Z parameters
        z_box = QGroupBox("Z Parameters")
        z_form = QFormLayout(z_box)
        self._z_depth = self._mm(0.01, 300, 3.0, dec=2)
        self._z_depth.setToolTip("Total drilling depth (positive input → negative Z)")
        z_form.addRow("Depth:", self._z_depth)
        self._z_step = self._mm(0.01, 100, 1.0, dec=2)
        self._z_step.setToolTip("Maximum Z step-down per peck")
        z_form.addRow("Step per peck:", self._z_step)
        layout.addWidget(z_box)

        # Info line
        self._lbl = QLabel()
        self._lbl.setStyleSheet("color:#555;font-size:11px;")
        layout.addWidget(self._lbl)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_ok = btns.button(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    # Page builders

    def _page_single(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self._p0_x = self._mm(-500, 500, 25.0, dec=2)
        self._p0_y = self._mm(-500, 500, 25.0, dec=2)
        f.addRow("X:", self._p0_x)
        f.addRow("Y:", self._p0_y)
        return w

    def _page_grid(self, stagger: bool) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        if not stagger:
            self._p1_ox   = self._mm(-500, 500, 0.0,  dec=2)
            self._p1_oy   = self._mm(-500, 500, 0.0,  dec=2)
            self._p1_cols = self._ispin(1, 500, 3)
            self._p1_rows = self._ispin(1, 500, 3)
            self._p1_dx   = self._mm(0.1, 500, 10.0)
            self._p1_dy   = self._mm(0.1, 500, 10.0)
            f.addRow("Origin X:", self._p1_ox)
            f.addRow("Origin Y:", self._p1_oy)
            f.addRow("Columns:", self._p1_cols)
            f.addRow("Rows:", self._p1_rows)
            f.addRow("Spacing X:", self._p1_dx)
            f.addRow("Spacing Y:", self._p1_dy)
        else:
            self._p2_ox   = self._mm(-500, 500, 0.0,  dec=2)
            self._p2_oy   = self._mm(-500, 500, 0.0,  dec=2)
            self._p2_cols = self._ispin(1, 500, 4)
            self._p2_rows = self._ispin(1, 500, 4)
            self._p2_dx   = self._mm(0.1, 500, 10.0)
            self._p2_dy   = self._mm(0.1, 500, 10.0)
            f.addRow("Origin X:", self._p2_ox)
            f.addRow("Origin Y:", self._p2_oy)
            f.addRow("Columns:", self._p2_cols)
            f.addRow("Rows:", self._p2_rows)
            f.addRow("Spacing X:", self._p2_dx)
            f.addRow("Spacing Y:", self._p2_dy)
            row = QHBoxLayout()
            self._p2_rb_rows = QRadioButton("Rows (X offset)")
            self._p2_rb_cols = QRadioButton("Columns (Y offset)")
            self._p2_rb_rows.setChecked(True)
            self._p2_rb_rows.toggled.connect(self._update_preview)
            row.addWidget(self._p2_rb_rows)
            row.addWidget(self._p2_rb_cols)
            f.addRow("Stagger:", row)
        return w

    def _page_circle_line(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self._p3_cx = self._mm(-500, 500, 50.0, dec=2)
        self._p3_cy = self._mm(-500, 500, 50.0, dec=2)
        self._p3_r  = self._mm(0.1, 500, 20.0)
        self._p3_n  = self._ispin(2, 360, 6)
        f.addRow("Center X:", self._p3_cx)
        f.addRow("Center Y:", self._p3_cy)
        f.addRow("Radius:", self._p3_r)
        f.addRow("Count:", self._p3_n)
        return w

    def _page_circle_area(self, stagger: bool) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        if not stagger:
            self._p4_cx = self._mm(-500, 500, 50.0, dec=2)
            self._p4_cy = self._mm(-500, 500, 50.0, dec=2)
            self._p4_r  = self._mm(0.1, 500, 30.0)
            self._p4_dx = self._mm(0.1, 500, 10.0)
            self._p4_dy = self._mm(0.1, 500, 10.0)
            f.addRow("Center X:", self._p4_cx)
            f.addRow("Center Y:", self._p4_cy)
            f.addRow("Radius:", self._p4_r)
            f.addRow("Spacing X:", self._p4_dx)
            f.addRow("Spacing Y:", self._p4_dy)
        else:
            self._p5_cx = self._mm(-500, 500, 50.0, dec=2)
            self._p5_cy = self._mm(-500, 500, 50.0, dec=2)
            self._p5_r  = self._mm(0.1, 500, 30.0)
            self._p5_dx = self._mm(0.1, 500, 10.0)
            self._p5_dy = self._mm(0.1, 500, 10.0)
            f.addRow("Center X:", self._p5_cx)
            f.addRow("Center Y:", self._p5_cy)
            f.addRow("Radius:", self._p5_r)
            f.addRow("Spacing X:", self._p5_dx)
            f.addRow("Spacing Y:", self._p5_dy)
            row = QHBoxLayout()
            self._p5_rb_rows = QRadioButton("Rows (X offset)")
            self._p5_rb_cols = QRadioButton("Columns (Y offset)")
            self._p5_rb_rows.setChecked(True)
            self._p5_rb_rows.toggled.connect(self._update_preview)
            row.addWidget(self._p5_rb_rows)
            row.addWidget(self._p5_rb_cols)
            f.addRow("Stagger:", row)
        return w

    def _page_fibonacci(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self._p6_cx = self._mm(-500, 500, 50.0, dec=2)
        self._p6_cy = self._mm(-500, 500, 50.0, dec=2)
        self._p6_r  = self._mm(0.1, 500, 30.0)
        self._p6_n  = self._ispin(1, 5000, 37)
        f.addRow("Center X:", self._p6_cx)
        f.addRow("Center Y:", self._p6_cy)
        f.addRow("Radius:", self._p6_r)
        f.addRow("Count:", self._p6_n)
        return w

    # ------------------------------------------------------------------
    # Pattern computation

    def _get_points(self) -> list[tuple[float, float]]:
        from app.cam.drill_cam import (
            single, rect_grid, circle_line, circle_area_grid, circle_fibonacci,
        )
        idx = self._cmb.currentIndex()

        if idx == 0:
            return single(self._p0_x.value(), self._p0_y.value())

        if idx == 1:
            return rect_grid(
                self._p1_ox.value(), self._p1_oy.value(),
                self._p1_cols.value(), self._p1_rows.value(),
                self._p1_dx.value(), self._p1_dy.value(),
            )

        if idx == 2:
            stagger = "rows" if self._p2_rb_rows.isChecked() else "cols"
            return rect_grid(
                self._p2_ox.value(), self._p2_oy.value(),
                self._p2_cols.value(), self._p2_rows.value(),
                self._p2_dx.value(), self._p2_dy.value(),
                stagger=stagger,
            )

        if idx == 3:
            return circle_line(
                self._p3_cx.value(), self._p3_cy.value(),
                self._p3_r.value(), self._p3_n.value(),
            )

        if idx == 4:
            return circle_area_grid(
                self._p4_cx.value(), self._p4_cy.value(),
                self._p4_r.value(),
                self._p4_dx.value(), self._p4_dy.value(),
            )

        if idx == 5:
            stagger = "rows" if self._p5_rb_rows.isChecked() else "cols"
            return circle_area_grid(
                self._p5_cx.value(), self._p5_cy.value(),
                self._p5_r.value(),
                self._p5_dx.value(), self._p5_dy.value(),
                stagger=stagger,
            )

        # idx == 6
        return circle_fibonacci(
            self._p6_cx.value(), self._p6_cy.value(),
            self._p6_r.value(), self._p6_n.value(),
        )

    def _generate(self) -> list[Move]:
        from app.cam.drill_cam import drill_moves
        pts = self._get_points()
        self._last_n_holes = len(pts)
        if not pts:
            return []
        z_depth = -abs(self._z_depth.value())
        z_step  = self._z_step.value()
        return drill_moves(pts, z_depth, z_step)

    # ------------------------------------------------------------------
    # Slots

    def _on_pattern_changed(self, idx: int):
        self._stack.setCurrentIndex(idx)
        self._update_preview()

    def _update_preview(self):
        moves = self._generate()
        n = self._last_n_holes
        n_plunges = sum(1 for m in moves if m.z_move and m.pen_down)
        self._lbl.setText(
            f"{n} hole{'s' if n != 1 else ''}  |  "
            f"{len(moves)} moves  |  {n_plunges} Z-plunges"
        )
        self._btn_ok.setEnabled(n > 0)
        self._result_moves = moves

    def _on_accept(self):
        if self._result_moves:
            self.accept()

    # ------------------------------------------------------------------
    # Public

    def get_moves(self) -> list[Move]:
        return self._result_moves

    def get_label(self) -> str:
        n = self._last_n_holes
        return f"Drill {n}× – {_PATTERN_SHORT[self._cmb.currentIndex()]}"
