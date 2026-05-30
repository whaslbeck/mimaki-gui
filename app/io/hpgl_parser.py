from __future__ import annotations
import re

from app.model.types import Pos, Move
from app.io.gcode_parser import ParseResult, ParseWarning

XY_FACTOR = 100.0   # HPGL units (0.01 mm) → mm
Z_FACTOR  = 100.0

# Matches optional ! prefix, then 1-3 uppercase letters as command name
_CMD_RE  = re.compile(r'(!?[A-Za-z]+)\s*(.*)', re.DOTALL)
_NUM_RE  = re.compile(r'[+-]?\d+(?:\.\d+)?')


def parse_hpgl(text: str) -> ParseResult:
    """Parse HPGL text (IN / PU / PD / !PZ only) into a ParseResult."""
    result = ParseResult()

    last   = Pos()
    z_pd   = 0.0    # cutting Z in mm (negative)
    z_pu   = 0.0    # travel Z in mm

    for line_nr, chunk in enumerate(text.split(';'), 1):
        chunk = chunk.strip()
        if not chunk:
            continue

        m = _CMD_RE.match(chunk)
        if not m:
            continue

        cmd      = m.group(1).upper()
        args_str = m.group(2).strip()
        nums     = [float(x) for x in _NUM_RE.findall(args_str)]

        if cmd == 'IN':
            last = Pos()
            z_pd = 0.0
            z_pu = 0.0

        elif cmd in ('PU', 'PD'):
            pen = (cmd == 'PD')
            z_now = z_pd if pen else z_pu

            # If no coords: only emit a Z/pen-state move if Z actually changed
            if not nums:
                if z_now != last.z:
                    new_pos = Pos(last.x, last.y, z_now)
                    result.moves.append(Move(
                        line_nr=line_nr,
                        source=chunk + ';',
                        from_pos=Pos(last.x, last.y, last.z),
                        to_pos=new_pos,
                        xy_move=False,
                        z_move=True,
                        pen_down=pen,
                        comment='',
                    ))
                    last = new_pos
                continue

            # Walk through coordinate pairs
            for i in range(0, len(nums) - 1, 2):
                nx = nums[i]     / XY_FACTOR
                ny = nums[i + 1] / XY_FACTOR
                new_pos  = Pos(nx, ny, z_now)
                xy_move  = (new_pos.x != last.x or new_pos.y != last.y)
                z_move   = (new_pos.z != last.z)
                if xy_move or z_move:
                    result.moves.append(Move(
                        line_nr=line_nr,
                        source=chunk + ';',
                        from_pos=Pos(last.x, last.y, last.z),
                        to_pos=new_pos,
                        xy_move=xy_move,
                        z_move=z_move,
                        pen_down=pen,
                        comment='',
                    ))
                last = new_pos

        elif cmd == '!PZ':
            if len(nums) >= 1:
                z_pd = nums[0] / Z_FACTOR
            if len(nums) >= 2:
                z_pu = nums[1] / Z_FACTOR
            else:
                z_pu = 0.0

        # All other commands (SP, VS, …) are silently ignored

    # Populate bounding-box stats
    if result.moves:
        xs = [m.to_pos.x for m in result.moves] + [m.from_pos.x for m in result.moves]
        ys = [m.to_pos.y for m in result.moves] + [m.from_pos.y for m in result.moves]
        result.min_pos = Pos(min(xs), min(ys))
        result.max_pos = Pos(max(xs), max(ys))
        pd_z = [m.to_pos.z for m in result.moves if m.pen_down]
        if pd_z:
            result.min_z = min(pd_z)
            result.max_z = max(pd_z)
            result.distinct_z_depths = sorted(set(round(z, 6) for z in pd_z))

    return result
