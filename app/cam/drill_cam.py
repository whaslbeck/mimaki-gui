"""Point-generation functions for drilling patterns.

Every function returns a list[(x, y)] in mm.  The caller converts them
to Move objects via drill_moves().
"""
from __future__ import annotations
import math

from app.model.types import Move, Pos


# ── Move generator ────────────────────────────────────────────────────────────

def drill_moves(
    points: list[tuple[float, float]],
    z_depth: float,
    z_step: float,
) -> list[Move]:
    """Full peck-drilling move list for *points*.

    z_depth  — negative mm (e.g. -3.0)
    z_step   — positive mm per peck (e.g. 1.0)
    """
    moves: list[Move] = []
    cur = Pos(0.0, 0.0, 0.0)
    for x, y in points:
        dest = Pos(x, y, 0.0)
        # Rapid to XY
        moves.append(Move(
            from_pos=cur, to_pos=dest,
            xy_move=True, z_move=False, pen_down=False,
        ))
        # Peck down in steps
        z = 0.0
        while z > z_depth + 1e-9:
            nz = max(z_depth, z - z_step)
            moves.append(Move(
                from_pos=Pos(x, y, z), to_pos=Pos(x, y, nz),
                xy_move=False, z_move=True, pen_down=True,
            ))
            z = nz
        # Retract to surface
        moves.append(Move(
            from_pos=Pos(x, y, z_depth), to_pos=Pos(x, y, 0.0),
            xy_move=False, z_move=True, pen_down=False,
        ))
        cur = Pos(x, y, 0.0)
    return moves


# ── Pattern generators ────────────────────────────────────────────────────────

def single(x: float, y: float) -> list[tuple[float, float]]:
    return [(x, y)]


def rect_grid(
    ox: float, oy: float,
    cols: int, rows: int,
    dx: float, dy: float,
    stagger: str = "",          # "" | "rows" | "cols"
) -> list[tuple[float, float]]:
    """Rectangular grid, optionally staggered.

    stagger="rows"  → every odd row is shifted +dx/2 in X
    stagger="cols"  → every odd column is shifted +dy/2 in Y
    """
    pts: list[tuple[float, float]] = []
    for r in range(rows):
        for c in range(cols):
            x = ox + c * dx + (dx / 2 if stagger == "rows" and r % 2 else 0.0)
            y = oy + r * dy + (dy / 2 if stagger == "cols" and c % 2 else 0.0)
            pts.append((x, y))
    return pts


def circle_line(
    cx: float, cy: float,
    radius: float,
    count: int,
) -> list[tuple[float, float]]:
    """Evenly spaced holes on a circle, starting at 3 o'clock."""
    step = 2 * math.pi / max(1, count)
    return [
        (cx + radius * math.cos(i * step),
         cy + radius * math.sin(i * step))
        for i in range(count)
    ]


def circle_area_grid(
    cx: float, cy: float,
    radius: float,
    dx: float, dy: float,
    stagger: str = "",          # "" | "rows" | "cols"
) -> list[tuple[float, float]]:
    """Grid clipped to a circle, optionally staggered."""
    nx = int(radius / dx) + 1
    ny = int(radius / dy) + 1
    pts: list[tuple[float, float]] = []
    for r in range(-ny, ny + 1):
        for c in range(-nx, nx + 1):
            x = cx + c * dx + (dx / 2 if stagger == "rows" and r % 2 else 0.0)
            y = cy + r * dy + (dy / 2 if stagger == "cols" and c % 2 else 0.0)
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 + 1e-9:
                pts.append((x, y))
    return pts


def circle_fibonacci(
    cx: float, cy: float,
    radius: float,
    count: int,
) -> list[tuple[float, float]]:
    """Sunflower / Fibonacci spiral filling a circle.

    Uses the golden angle (≈ 137.508°) and uniform radial spacing via
    sqrt so that hole density is roughly constant across the area.
    The +0.5 offset avoids a degenerate point at the exact centre.
    """
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    return [
        (
            cx + radius * math.sqrt((i + 0.5) / count) * math.cos(i * golden_angle),
            cy + radius * math.sqrt((i + 0.5) / count) * math.sin(i * golden_angle),
        )
        for i in range(count)
    ]
