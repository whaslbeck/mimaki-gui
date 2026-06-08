from __future__ import annotations
import uuid
from dataclasses import dataclass, field


@dataclass
class SavedPoint:
    """A machine XY position the operator captured via jog, for re-visiting
    or aligning the workpiece against."""
    x: float = 0.0
    y: float = 0.0
    label: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {"id": self.id, "x": self.x, "y": self.y, "label": self.label}

    @classmethod
    def from_dict(cls, d: dict) -> SavedPoint:
        return cls(
            x=d.get("x", 0.0),
            y=d.get("y", 0.0),
            label=d.get("label", ""),
            id=d.get("id", str(uuid.uuid4())),
        )
