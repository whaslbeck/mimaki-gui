from __future__ import annotations
from typing import Optional

from app.model.types import Move

XY_FACTOR = 100  # mm → 0.01 mm HPGL units
Z_FACTOR = 100


def moves_to_hpgl(
    moves: list[Move],
    include_init: bool = True,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    xy_speed_mms: Optional[float] = None,
    z_speed_mms: Optional[float] = None,
) -> bytes:
    parts: list[str] = []
    if include_init:
        parts.append("IN;PU;\n")
        if xy_speed_mms is not None:
            parts.append(f"VS{round(max(1, xy_speed_mms))};\n")
        if z_speed_mms is not None:
            parts.append(f"!VZ{max(1, min(10, round(z_speed_mms)))};\n")

    current_z = 0.0
    in_pd = False

    for move in moves:
        t = move.to_pos
        xy_move = move.xy_move
        z_move = move.z_move
        seg = ""

        if z_move:
            if in_pd:
                seg += ";\n"
                in_pd = False
            seg += f"!PZ{round(t.z * Z_FACTOR):.0f};\n"
            if not xy_move:
                seg += "PD;" if t.z < 0.0 else "PU;\n"
            current_z = t.z

        if xy_move:
            hx = round((t.x + offset_x) * XY_FACTOR)
            hy = round((t.y + offset_y) * XY_FACTOR)
            if t.z < 0.0:
                if not in_pd:
                    seg += "PD"
                    in_pd = True
                else:
                    seg += ","
            else:
                if in_pd:
                    seg += ";\n"
                    in_pd = False
                seg += "PU"
            seg += f"{hx},{hy}"
            if not in_pd:
                seg += ";\n"

        parts.append(seg)

    if in_pd:
        parts.append(";\n")

    return "".join(parts).encode()


def limits_to_hpgl(
    min_x: float, min_y: float, max_x: float, max_y: float
) -> bytes:
    x1, y1 = round(min_x * XY_FACTOR), round(min_y * XY_FACTOR)
    x2, y2 = round(max_x * XY_FACTOR), round(max_y * XY_FACTOR)
    return (
        f"IN;PU;!PZ500;PU0,0;"
        f"PU{x1},{y1};"
        f"PD{x2},{y1};"
        f"PD{x2},{y2};"
        f"PD{x1},{y2};"
        f"PD{x1},{y1};"
        f"PU0,0;"
    ).encode()
