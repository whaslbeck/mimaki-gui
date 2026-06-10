from __future__ import annotations
import math
from typing import Optional

from .gcode_object import GcodeObject
from .zone import ForbiddenZone
from .ref_point import RefPoint
from .saved_point import SavedPoint
from .calibration import BackgroundImage
from .types import SpeedSettings, GridSettings

MACHINE_W = 483.0
MACHINE_H = 305.0


class Project:
    def __init__(self):
        self.objects: list[GcodeObject] = []
        self.forbidden_zones: list[ForbiddenZone] = []
        self.ref_points: list[RefPoint] = []
        self.saved_points: list[SavedPoint] = []
        self.background: Optional[BackgroundImage] = None
        self.speeds = SpeedSettings()
        self.grid = GridSettings()
        self.work_offset_x: float = 0.0
        self.work_offset_y: float = 0.0
        self.filepath: str = ""
        self.modified: bool = False

    # ------------------------------------------------------------------
    # Object management

    def add_object(self, obj: GcodeObject):
        self.objects.append(obj)
        self.modified = True

    def remove_object(self, obj_id: str):
        self.objects = [o for o in self.objects if o.id != obj_id]
        self.modified = True

    def object_by_id(self, obj_id: str) -> Optional[GcodeObject]:
        return next((o for o in self.objects if o.id == obj_id), None)

    def visible_objects(self) -> list[GcodeObject]:
        return [o for o in self.objects if o.visible]

    # ------------------------------------------------------------------
    # Zone management

    def add_zone(self, zone: ForbiddenZone):
        self.forbidden_zones.append(zone)
        self.modified = True

    def remove_zone(self, zone_id: str):
        self.forbidden_zones = [z for z in self.forbidden_zones if z.id != zone_id]
        self.modified = True

    # ------------------------------------------------------------------
    # Saved-point management

    def add_saved_point(self, point: SavedPoint):
        self.saved_points.append(point)
        self.modified = True

    def remove_saved_point(self, point_id: str):
        self.saved_points = [p for p in self.saved_points if p.id != point_id]
        self.modified = True

    # ------------------------------------------------------------------
    # Collision helpers

    def bbox_collides(self, x: float, y: float, w: float, h: float,
                      exclude_id: Optional[str] = None) -> bool:
        for zone in self.forbidden_zones:
            if zone.overlaps_rect(x, y, w, h):
                return True
        for obj in self.visible_objects():
            if obj.id == exclude_id:
                continue
            bb = obj.bounding_box
            ox, oy, ow, oh = bb.min_x, bb.min_y, bb.width, bb.height
            if not (x + w <= ox or x >= ox + ow or y + h <= oy or y >= oy + oh):
                return True
        if x < 0 or y < 0 or x + w > MACHINE_W or y + h > MACHINE_H:
            return True
        return False

    # ------------------------------------------------------------------
    # Duration estimate

    def estimate_duration_seconds(self) -> float:
        total = 0.0
        for obj in self.visible_objects():
            for m in obj.computed_moves:
                dx = m.to_pos.x - m.from_pos.x
                dy = m.to_pos.y - m.from_pos.y
                dz = abs(m.to_pos.z - m.from_pos.z)
                xy_dist = math.sqrt(dx * dx + dy * dy)
                if m.pen_down:
                    xy_spd = self.speeds.xy_machining_mm_min
                    z_spd = self.speeds.z_machining_mm_min
                else:
                    xy_spd = self.speeds.xy_travel_mm_min
                    z_spd = self.speeds.z_travel_mm_min
                if xy_dist > 0 and xy_spd > 0:
                    total += (xy_dist / xy_spd) * 60.0
                if dz > 0 and z_spd > 0:
                    total += (dz / z_spd) * 60.0
        return total

    # ------------------------------------------------------------------
    # Serialisation

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "objects": [o.to_dict() for o in self.objects],
            "forbidden_zones": [z.to_dict() for z in self.forbidden_zones],
            "ref_points": [r.to_dict() for r in self.ref_points],
            "saved_points": [p.to_dict() for p in self.saved_points],
            "background": self.background.to_dict() if self.background else None,
            "speeds": self.speeds.to_dict(),
            "grid": self.grid.to_dict(),
            "work_offset_x": self.work_offset_x,
            "work_offset_y": self.work_offset_y,
        }
