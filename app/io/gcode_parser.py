from __future__ import annotations
import re
from dataclasses import dataclass, field

from app.model.types import Pos, Move


@dataclass
class ParseWarning:
    line_nr: int
    input_text: str
    message: str


@dataclass
class ParseResult:
    moves: list[Move] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)
    min_pos: Pos = field(default_factory=Pos)
    max_pos: Pos = field(default_factory=Pos)
    min_z: float = 0.0
    max_z: float = 0.0
    distinct_z_depths: list[float] = field(default_factory=list)


_AXIS_RE = re.compile(r'([XYZ])([+-]?[0-9]*\.?[0-9]+)', re.IGNORECASE)
_COMMENT_RE = re.compile(r'\(([^)]*)\)')


def parse_gcode(text: str) -> ParseResult:
    result = ParseResult()
    current = Pos()
    last = Pos()
    first = True
    min_p = Pos()
    max_p = Pos()
    min_z = max_z = 0.0
    z_depths: set[float] = set()
    pending_comment = ""

    for line_nr, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()

        # Capture inline comments
        comment_matches = _COMMENT_RE.findall(line)
        if comment_matches:
            pending_comment = " | ".join(comment_matches)
        line_clean = _COMMENT_RE.sub("", line).strip()

        if not line_clean:
            continue

        parts = _AXIS_RE.findall(line_clean)
        if not parts:
            continue

        coord_found = False
        nx, ny, nz = current.x, current.y, current.z

        for axis, val_str in parts:
            try:
                val = float(val_str)
            except ValueError:
                result.warnings.append(
                    ParseWarning(line_nr, val_str, f"Cannot parse: {val_str!r}")
                )
                continue
            coord_found = True
            a = axis.upper()
            if a == "X":
                nx = val
            elif a == "Y":
                ny = val
            elif a == "Z":
                nz = val

        if not coord_found:
            continue

        current = Pos(nx, ny, nz)

        if first:
            min_p = Pos(current.x, current.y, current.z)
            max_p = Pos(current.x, current.y, current.z)
            min_z = max_z = current.z
            first = False
        else:
            if current.x < min_p.x:
                min_p.x = current.x
            if current.y < min_p.y:
                min_p.y = current.y
            if current.x > max_p.x:
                max_p.x = current.x
            if current.y > max_p.y:
                max_p.y = current.y
            if current.z < min_z:
                min_z = current.z
            if current.z > max_z:
                max_z = current.z

        xy_move = current.x != last.x or current.y != last.y
        z_move = current.z != last.z

        if xy_move or z_move:
            pen_down = current.z < 0.0
            if pen_down:
                z_depths.add(round(current.z, 6))
            result.moves.append(Move(
                line_nr=line_nr,
                source=raw,
                from_pos=Pos(last.x, last.y, last.z),
                to_pos=Pos(current.x, current.y, current.z),
                xy_move=xy_move,
                z_move=z_move,
                pen_down=pen_down,
                comment=pending_comment,
            ))
            pending_comment = ""

        last = current

    result.min_pos = min_p
    result.max_pos = max_p
    result.min_z = min_z
    result.max_z = max_z
    result.distinct_z_depths = sorted(z_depths)
    return result
