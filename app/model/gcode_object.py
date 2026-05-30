from __future__ import annotations
import copy
import uuid
from dataclasses import dataclass
from typing import Optional

from .types import Move, Pos, Transform


@dataclass
class BoundingBox:
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center_x(self) -> float:
        return (self.min_x + self.max_x) / 2

    @property
    def center_y(self) -> float:
        return (self.min_y + self.max_y) / 2


class GcodeObject:
    def __init__(
        self,
        source_file: str,
        original_moves: list[Move],
        label: str = "",
        obj_id: Optional[str] = None,
    ):
        self.id = obj_id or str(uuid.uuid4())
        self.source_file = source_file
        self.source_type: str = "gcode"        # "gcode" or "hpgl"
        self.label = label or source_file.split("/")[-1].split("\\")[-1]
        self.visible = True
        self.placement_warning: bool = False   # set when auto-placement failed
        self.original_moves: list[Move] = original_moves
        self.transform = Transform()
        self._computed_moves: Optional[list[Move]] = None
        self._bbox: Optional[BoundingBox] = None
        self._cache_version: int = 0
        self.has_comments: bool = any(m.comment for m in original_moves)

        raw = self._raw_bbox()
        self.transform.pivot_x = raw.center_x
        self.transform.pivot_y = raw.center_y

    # ------------------------------------------------------------------
    # Private helpers

    def _raw_bbox(self) -> BoundingBox:
        if not self.original_moves:
            return BoundingBox()
        xs: list[float] = []
        ys: list[float] = []
        for m in self.original_moves:
            xs += [m.from_pos.x, m.to_pos.x]
            ys += [m.from_pos.y, m.to_pos.y]
        return BoundingBox(min(xs), min(ys), max(xs), max(ys))

    def _invalidate(self):
        self._computed_moves = None
        self._bbox = None
        self._cache_version += 1

    # ------------------------------------------------------------------
    # Public properties

    @property
    def computed_moves(self) -> list[Move]:
        if self._computed_moves is None:
            t = self.transform
            self._computed_moves = [
                Move(
                    line_nr=m.line_nr,
                    source=m.source,
                    from_pos=t.apply_pos(m.from_pos),
                    to_pos=t.apply_pos(m.to_pos),
                    xy_move=m.xy_move,
                    z_move=m.z_move,
                    pen_down=m.pen_down,
                    comment=m.comment,
                )
                for m in self.original_moves
            ]
        return self._computed_moves

    @property
    def bounding_box(self) -> BoundingBox:
        if self._bbox is None:
            moves = self.computed_moves
            if not moves:
                self._bbox = BoundingBox()
            else:
                xs: list[float] = []
                ys: list[float] = []
                for m in moves:
                    xs += [m.from_pos.x, m.to_pos.x]
                    ys += [m.from_pos.y, m.to_pos.y]
                self._bbox = BoundingBox(min(xs), min(ys), max(xs), max(ys))
        return self._bbox

    @property
    def distinct_z_depths(self) -> list[float]:
        depths = {m.to_pos.z for m in self.original_moves if m.pen_down}
        return sorted(depths)

    # ------------------------------------------------------------------
    # Transform setters (each invalidates the cache)

    def set_offset(self, x: float, y: float):
        self.transform.offset_x = x
        self.transform.offset_y = y
        self._invalidate()

    def set_scale(self, s: float):
        self.transform.scale = max(0.001, s)
        self._invalidate()

    def set_rotation(self, deg: float):
        self.transform.rotation_deg = deg % 360
        self._invalidate()

    def set_pivot(self, x: float, y: float):
        self.transform.pivot_x = x
        self.transform.pivot_y = y
        self._invalidate()

    def reset_pivot(self):
        bbox = self.bounding_box
        self.transform.pivot_x = bbox.center_x
        self.transform.pivot_y = bbox.center_y
        self._invalidate()

    def reset_transform(self):
        raw = self._raw_bbox()
        self.transform = Transform(
            pivot_x=raw.center_x,
            pivot_y=raw.center_y,
        )
        self._invalidate()

    # ------------------------------------------------------------------
    # Clone

    def mirror_h(self):
        """Flip object horizontally (left ↔ right) around its current bbox center."""
        moves = self.computed_moves
        if not moves:
            return
        cx = self.bounding_box.center_x
        self.original_moves = [
            Move(
                line_nr=m.line_nr, source=m.source,
                from_pos=Pos(2*cx - m.from_pos.x, m.from_pos.y, m.from_pos.z),
                to_pos=Pos(2*cx - m.to_pos.x, m.to_pos.y, m.to_pos.z),
                xy_move=m.xy_move, z_move=m.z_move,
                pen_down=m.pen_down, comment=m.comment,
            )
            for m in moves
        ]
        raw = self._raw_bbox()
        self.transform = Transform(pivot_x=raw.center_x, pivot_y=raw.center_y)
        self._invalidate()

    def mirror_v(self):
        """Flip object vertically (top ↔ bottom) around its current bbox center."""
        moves = self.computed_moves
        if not moves:
            return
        cy = self.bounding_box.center_y
        self.original_moves = [
            Move(
                line_nr=m.line_nr, source=m.source,
                from_pos=Pos(m.from_pos.x, 2*cy - m.from_pos.y, m.from_pos.z),
                to_pos=Pos(m.to_pos.x, 2*cy - m.to_pos.y, m.to_pos.z),
                xy_move=m.xy_move, z_move=m.z_move,
                pen_down=m.pen_down, comment=m.comment,
            )
            for m in moves
        ]
        raw = self._raw_bbox()
        self.transform = Transform(pivot_x=raw.center_x, pivot_y=raw.center_y)
        self._invalidate()

    def clone(self) -> GcodeObject:
        obj = GcodeObject(
            source_file=self.source_file,
            original_moves=self.original_moves,
            label=self.label,
        )
        obj.transform = self.transform.copy()
        obj._invalidate()
        return obj

    # ------------------------------------------------------------------
    # Serialisation

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "label": self.label,
            "source_file": self.source_file,
            "source_type": self.source_type,
            "visible": self.visible,
            "transform": self.transform.to_dict(),
        }
        if self.source_type == "generated":
            d["generated_moves"] = [
                {
                    "from_pos": [m.from_pos.x, m.from_pos.y, m.from_pos.z],
                    "to_pos":   [m.to_pos.x,   m.to_pos.y,   m.to_pos.z],
                    "xy_move":  m.xy_move,
                    "z_move":   m.z_move,
                    "pen_down": m.pen_down,
                }
                for m in self.original_moves
            ]
        return d

    @classmethod
    def from_dict(cls, data: dict, original_moves: list[Move]) -> GcodeObject:
        obj = cls(
            source_file=data["source_file"],
            original_moves=original_moves,
            label=data.get("label", ""),
            obj_id=data.get("id"),
        )
        obj.source_type = data.get("source_type", "gcode")
        obj.visible = data.get("visible", True)
        obj.transform = Transform.from_dict(data.get("transform", {}))
        obj._invalidate()
        return obj

    @classmethod
    def from_generated(cls, moves: list[Move], label: str) -> GcodeObject:
        """Create an object from programmatically generated moves (no source file)."""
        obj = cls(source_file="<generated>", original_moves=moves, label=label)
        obj.source_type = "generated"
        return obj
