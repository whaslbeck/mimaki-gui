"""
Simple CAM toolpath generation for basic shapes.
All coordinates in mm. Z=0 = top surface, negative Z = into material.
Generates lists of Move objects that become GcodeObjects in the project.
"""
from __future__ import annotations
import math
from app.model.types import Move, Pos

CIRCLE_SEGS = 72   # 5° per segment for standard circles


# ---------------------------------------------------------------------------
# Internal builder

class _Builder:
    """Accumulates Move objects while tracking current tool position."""

    def __init__(self):
        self.moves: list[Move] = []
        self.pos = Pos(0.0, 0.0, 0.0)

    def rapid(self, x: float, y: float):
        """Pen-up move to (x, y); retracts first if at depth."""
        if self.pos.z < 0.0:
            self._append(Pos(self.pos.x, self.pos.y, 0.0), z_move=True)
        self._append(Pos(x, y, 0.0), xy_move=True)

    def plunge(self, z: float):
        """Move Z to cutting depth (z must be < 0)."""
        self._append(Pos(self.pos.x, self.pos.y, z), z_move=True)

    def cut(self, x: float, y: float):
        """Pen-down move to (x, y) at current Z depth."""
        self._append(Pos(x, y, self.pos.z), xy_move=True)

    def retract(self):
        """Lift Z to 0 if currently at depth."""
        if self.pos.z < 0.0:
            self._append(Pos(self.pos.x, self.pos.y, 0.0), z_move=True)

    def _append(self, to: Pos, xy_move: bool = False, z_move: bool = False):
        self.moves.append(Move(
            from_pos=self.pos,
            to_pos=to,
            xy_move=xy_move,
            z_move=z_move,
            pen_down=(to.z < 0.0),
        ))
        self.pos = to


# ---------------------------------------------------------------------------
# Z-pass helper

def _z_passes(z_total: float, z_step: float) -> list[float]:
    """Return list of Z depths (all ≤ 0) for each cutting pass.

    z_total must be negative (e.g. -5.0), z_step positive (e.g. 1.5).
    Last pass is always exactly z_total.
    """
    if z_step <= 0 or z_total >= 0:
        return [z_total] if z_total < 0 else []
    passes: list[float] = []
    depth = 0.0
    while depth > z_total + 1e-9:
        depth = max(depth - z_step, z_total)
        passes.append(depth)
    return passes or [z_total]


# ---------------------------------------------------------------------------
# Shape generators

def rectangle_contour(
    width: float,
    height: float,
    tool_r: float,
    side: str,       # "outside" or "inside"
    z_total: float,
    z_step: float,
) -> list[Move]:
    """Rectangle contour from (0,0) to (width, height).

    Returns [] if tool is too large for inside contour.
    """
    if side == "outside":
        rx, ry = -tool_r, -tool_r
        rw, rh = width + 2 * tool_r, height + 2 * tool_r
    else:
        rx, ry = tool_r, tool_r
        rw, rh = width - 2 * tool_r, height - 2 * tool_r
        if rw <= 0 or rh <= 0:
            return []

    passes = _z_passes(z_total, z_step)
    b = _Builder()
    b.rapid(rx, ry)
    for z in passes:
        b.plunge(z)
        b.cut(rx + rw, ry)
        b.cut(rx + rw, ry + rh)
        b.cut(rx,       ry + rh)
        b.cut(rx,       ry)          # close loop
    b.retract()
    return b.moves


def circle_contour(
    radius: float,
    tool_r: float,
    side: str,       # "outside" or "inside"
    z_total: float,
    z_step: float,
) -> list[Move]:
    """Circle contour centred at origin.

    Returns [] if tool is too large for inside contour.
    """
    cr = radius + tool_r if side == "outside" else radius - tool_r
    if cr <= 0:
        return []

    pts = [
        (cr * math.cos(2 * math.pi * i / CIRCLE_SEGS),
         cr * math.sin(2 * math.pi * i / CIRCLE_SEGS))
        for i in range(CIRCLE_SEGS)
    ]

    passes = _z_passes(z_total, z_step)
    b = _Builder()
    b.rapid(pts[0][0], pts[0][1])
    for z in passes:
        b.plunge(z)
        for px, py in pts[1:]:
            b.cut(px, py)
        b.cut(pts[0][0], pts[0][1])  # close
    b.retract()
    return b.moves


def rectangle_pocket(
    width: float,
    height: float,
    tool_r: float,
    overlap_frac: float,  # 0.0–0.95
    z_total: float,
    z_step: float,
) -> list[Move]:
    """Fill rectangle (0,0)–(width,height) with boustrophedon lines.

    Covers both pocket milling and surface facing.
    Returns [] if tool diameter exceeds pocket dimensions.
    """
    px, py = tool_r, tool_r
    pw, ph = width - 2 * tool_r, height - 2 * tool_r
    if pw <= 0 or ph <= 0:
        return []

    line_step = max(tool_r * 2 * (1.0 - overlap_frac), 1e-3)

    # Build row Y positions
    ys: list[float] = []
    cy = py
    while cy < py + ph + 1e-9:
        ys.append(min(cy, py + ph))
        if abs(cy - (py + ph)) < 1e-9:
            break
        cy += line_step
    if not ys:
        return []

    passes = _z_passes(z_total, z_step)
    b = _Builder()

    for z in passes:
        b.rapid(px, ys[0])
        b.plunge(z)
        for i, row_y in enumerate(ys):
            if i % 2 == 0:                # left → right
                b.cut(px + pw, row_y)
                if i + 1 < len(ys):
                    b.cut(px + pw, ys[i + 1])   # vertical connector at right edge
            else:                          # right → left
                b.cut(px, row_y)
                if i + 1 < len(ys):
                    b.cut(px, ys[i + 1])         # vertical connector at left edge

    b.retract()
    return b.moves


def circle_pocket(
    radius: float,
    tool_r: float,
    overlap_frac: float,
    z_total: float,
    z_step: float,
) -> list[Move]:
    """Fill circle (centred at origin) with concentric rings inward.

    Returns [] if tool is larger than circle.
    """
    if radius <= tool_r:
        return []

    line_step = max(tool_r * 2 * (1.0 - overlap_frac), 1e-3)
    passes = _z_passes(z_total, z_step)
    b = _Builder()

    for z in passes:
        cr = radius - tool_r
        while cr > 1e-9:
            segs = max(12, int(2 * math.pi * cr / 0.3))   # ≈0.3 mm chord
            pts = [
                (cr * math.cos(2 * math.pi * i / segs),
                 cr * math.sin(2 * math.pi * i / segs))
                for i in range(segs)
            ]
            b.rapid(pts[0][0], pts[0][1])
            b.plunge(z)
            for px, py in pts[1:]:
                b.cut(px, py)
            b.cut(pts[0][0], pts[0][1])   # close ring
            cr -= line_step

    b.retract()
    return b.moves
