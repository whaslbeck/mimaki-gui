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
