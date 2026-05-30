from __future__ import annotations
import math
from dataclasses import dataclass, field


@dataclass
class Pos:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class Move:
    line_nr: int = 0
    source: str = ""
    from_pos: Pos = field(default_factory=Pos)
    to_pos: Pos = field(default_factory=Pos)
    xy_move: bool = False
    z_move: bool = False
    pen_down: bool = False
    comment: str = ""


@dataclass
class Transform:
    offset_x: float = 0.0
    offset_y: float = 0.0
    scale: float = 1.0
    rotation_deg: float = 0.0
    pivot_x: float = 0.0
    pivot_y: float = 0.0

    def apply_pos(self, p: Pos) -> Pos:
        x = p.x * self.scale
        y = p.y * self.scale
        x += self.offset_x
        y += self.offset_y
        if self.rotation_deg != 0.0:
            rad = math.radians(self.rotation_deg)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            dx = x - self.pivot_x
            dy = y - self.pivot_y
            x = cos_a * dx - sin_a * dy + self.pivot_x
            y = sin_a * dx + cos_a * dy + self.pivot_y
        return Pos(x, y, p.z)

    def copy(self) -> Transform:
        return Transform(
            self.offset_x, self.offset_y, self.scale,
            self.rotation_deg, self.pivot_x, self.pivot_y,
        )

    def to_dict(self) -> dict:
        return {
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "scale": self.scale,
            "rotation_deg": self.rotation_deg,
            "pivot_x": self.pivot_x,
            "pivot_y": self.pivot_y,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Transform:
        return cls(
            offset_x=d.get("offset_x", 0.0),
            offset_y=d.get("offset_y", 0.0),
            scale=d.get("scale", 1.0),
            rotation_deg=d.get("rotation_deg", 0.0),
            pivot_x=d.get("pivot_x", 0.0),
            pivot_y=d.get("pivot_y", 0.0),
        )


@dataclass
class SpeedSettings:
    xy_travel_mm_min: float = 5000.0
    xy_machining_mm_min: float = 1000.0
    z_travel_mm_min: float = 1000.0
    z_machining_mm_min: float = 500.0

    def to_dict(self) -> dict:
        return {
            "xy_travel_mm_min": self.xy_travel_mm_min,
            "xy_machining_mm_min": self.xy_machining_mm_min,
            "z_travel_mm_min": self.z_travel_mm_min,
            "z_machining_mm_min": self.z_machining_mm_min,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SpeedSettings:
        return cls(
            xy_travel_mm_min=d.get("xy_travel_mm_min", 5000.0),
            xy_machining_mm_min=d.get("xy_machining_mm_min", 1000.0),
            z_travel_mm_min=d.get("z_travel_mm_min", 1000.0),
            z_machining_mm_min=d.get("z_machining_mm_min", 500.0),
        )


@dataclass
class GridSettings:
    visible: bool = True
    spacing_mm: float = 10.0
    origin_x: float = 0.0
    origin_y: float = 0.0

    def to_dict(self) -> dict:
        return {
            "visible": self.visible,
            "spacing_mm": self.spacing_mm,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GridSettings:
        return cls(
            visible=d.get("visible", True),
            spacing_mm=d.get("spacing_mm", 10.0),
            origin_x=d.get("origin_x", 0.0),
            origin_y=d.get("origin_y", 0.0),
        )
