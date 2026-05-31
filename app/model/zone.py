from __future__ import annotations
import uuid
from dataclasses import dataclass, field


@dataclass
class ForbiddenZone:
    x: float = 0.0
    y: float = 0.0
    width: float = 20.0
    height: float = 20.0
    label: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def overlaps_rect(self, x: float, y: float, w: float, h: float) -> bool:
        return not (
            x + w <= self.x or x >= self.x + self.width or
            y + h <= self.y or y >= self.y + self.height
        )

    def intersects_segment(self, ax: float, ay: float, bx: float, by: float) -> bool:
        """True if the line segment A→B passes through or touches this zone."""
        zx1, zy1 = self.x, self.y
        zx2, zy2 = self.x + self.width, self.y + self.height

        def _inside(px: float, py: float) -> bool:
            return zx1 <= px <= zx2 and zy1 <= py <= zy2

        if _inside(ax, ay) or _inside(bx, by):
            return True

        # Check segment against each of the four rectangle edges.
        def _seg_cross(p1x, p1y, p2x, p2y, p3x, p3y, p4x, p4y) -> bool:
            d1x, d1y = p2x - p1x, p2y - p1y
            d2x, d2y = p4x - p3x, p4y - p3y
            denom = d1x * d2y - d1y * d2x
            if abs(denom) < 1e-12:
                return False  # parallel / collinear
            t = ((p3x - p1x) * d2y - (p3y - p1y) * d2x) / denom
            u = ((p3x - p1x) * d1y - (p3y - p1y) * d1x) / denom
            return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0

        return (
            _seg_cross(ax, ay, bx, by, zx1, zy1, zx2, zy1) or  # bottom
            _seg_cross(ax, ay, bx, by, zx2, zy1, zx2, zy2) or  # right
            _seg_cross(ax, ay, bx, by, zx2, zy2, zx1, zy2) or  # top
            _seg_cross(ax, ay, bx, by, zx1, zy2, zx1, zy1)     # left
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ForbiddenZone:
        return cls(
            x=d["x"],
            y=d["y"],
            width=d["width"],
            height=d["height"],
            label=d.get("label", ""),
            id=d.get("id", str(uuid.uuid4())),
        )
