from __future__ import annotations
import json

from app.model.gcode_object import GcodeObject
from app.model.project import Project
from app.model.types import SpeedSettings, GridSettings, Move, Pos
from app.model.zone import ForbiddenZone
from app.model.ref_point import RefPoint
from app.io.gcode_parser import parse_gcode
from app.io.hpgl_parser import parse_hpgl


def save_project(project: Project, filepath: str):
    with open(filepath, "w") as f:
        json.dump(project.to_dict(), f, indent=2)
    project.filepath = filepath
    project.modified = False


def load_project(filepath: str) -> tuple[Project, list[tuple[str, dict]]]:
    """Return (project, [(missing_src_path, obj_dict), ...])."""
    with open(filepath) as f:
        data = json.load(f)

    project = Project()
    missing: list[tuple[str, dict]] = []

    for obj_data in data.get("objects", []):
        src = obj_data["source_file"]
        src_type = obj_data.get("source_type", "gcode")

        if src_type == "generated":
            raw = obj_data.get("generated_moves", [])
            moves = [
                Move(
                    from_pos=Pos(*m["from_pos"]),
                    to_pos=Pos(*m["to_pos"]),
                    xy_move=m.get("xy_move", False),
                    z_move=m.get("z_move", False),
                    pen_down=m.get("pen_down", False),
                )
                for m in raw
            ]
            obj = GcodeObject.from_dict(obj_data, moves)
            project.objects.append(obj)
            continue

        try:
            with open(src, errors="replace") as f:
                text = f.read()
            result = parse_hpgl(text) if src_type == "hpgl" else parse_gcode(text)
            obj = GcodeObject.from_dict(obj_data, result.moves)
            project.objects.append(obj)
        except FileNotFoundError:
            missing.append((src, obj_data))

    for zd in data.get("forbidden_zones", []):
        project.forbidden_zones.append(ForbiddenZone.from_dict(zd))

    for rd in data.get("ref_points", []):
        project.ref_points.append(RefPoint.from_dict(rd))

    project.speeds = SpeedSettings.from_dict(data.get("speeds", {}))
    project.grid = GridSettings.from_dict(data.get("grid", {}))
    project.work_offset_x = data.get("work_offset_x", 0.0)
    project.work_offset_y = data.get("work_offset_y", 0.0)
    project.filepath = filepath
    project.modified = False
    return project, missing
