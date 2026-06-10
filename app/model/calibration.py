from __future__ import annotations
import base64
import math
import uuid
from dataclasses import dataclass, field
from typing import Optional


# ----------------------------------------------------------------------
# Data model

@dataclass
class CalibrationPoint:
    """Maps one image pixel position to a machine coordinate (mm)."""
    px: float = 0.0          # image pixel x
    py: float = 0.0          # image pixel y
    x: float = 0.0           # machine mm x
    y: float = 0.0           # machine mm y
    label: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {"id": self.id, "px": self.px, "py": self.py,
                "x": self.x, "y": self.y, "label": self.label}

    @classmethod
    def from_dict(cls, d: dict) -> CalibrationPoint:
        return cls(
            px=d.get("px", 0.0), py=d.get("py", 0.0),
            x=d.get("x", 0.0), y=d.get("y", 0.0),
            label=d.get("label", ""),
            id=d.get("id", str(uuid.uuid4())),
        )


DISPLAY_MODES = ("original", "gray", "faded", "hidden")


@dataclass
class BackgroundImage:
    """A calibrated photo of the real machine bed, shown under the work area.

    The image is stored as a base64 JPEG so the project file stays a single
    portable document. Calibration points map image pixels to machine mm; a
    transform (similarity / affine / homography depending on point count) maps
    the whole image into machine coordinate space.
    """
    image_b64: str = ""
    img_w: int = 0
    img_h: int = 0
    points: list[CalibrationPoint] = field(default_factory=list)
    display_mode: str = "original"   # one of DISPLAY_MODES
    opacity: float = 1.0             # 0..1
    points_visible: bool = True

    def to_dict(self) -> dict:
        return {
            "image_b64": self.image_b64,
            "img_w": self.img_w,
            "img_h": self.img_h,
            "points": [p.to_dict() for p in self.points],
            "display_mode": self.display_mode,
            "opacity": self.opacity,
            "points_visible": self.points_visible,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BackgroundImage:
        mode = d.get("display_mode", "original")
        if mode not in DISPLAY_MODES:
            mode = "original"
        return cls(
            image_b64=d.get("image_b64", ""),
            img_w=d.get("img_w", 0),
            img_h=d.get("img_h", 0),
            points=[CalibrationPoint.from_dict(p) for p in d.get("points", [])],
            display_mode=mode,
            opacity=float(d.get("opacity", 1.0)),
            points_visible=d.get("points_visible", True),
        )


# ----------------------------------------------------------------------
# Image (de)coding — base64 JPEG, downscaled on import

def encode_image(image, max_edge: int = 2000, quality: int = 85):
    """Downscale a QImage to max_edge and return (base64_jpeg, w, h)."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt

    if image.width() > max_edge or image.height() > max_edge:
        image = image.scaled(
            max_edge, max_edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "JPG", quality)
    buf.close()
    b64 = base64.b64encode(bytes(ba)).decode("ascii")
    return b64, image.width(), image.height()


def decode_image(image_b64: str):
    """Decode a base64 JPEG into a QImage (or a null QImage on failure)."""
    from PyQt6.QtGui import QImage
    img = QImage()
    if image_b64:
        img.loadFromData(base64.b64decode(image_b64), "JPG")
    return img


# ----------------------------------------------------------------------
# Calibration transform (image pixel -> machine mm)

def compute_transform(points: list[CalibrationPoint]):
    """Return (QTransform pixel->mm, rms_error_mm) or (None, 0.0).

    Model is chosen by point count:
      2  -> similarity (translation + rotation + uniform scale)
      3  -> affine (adds shear / non-uniform scale)
      >=4 -> homography (full perspective, least-squares for >4)
    """
    from PyQt6.QtGui import QTransform
    from PyQt6.QtCore import QPointF

    n = len(points)
    if n < 2:
        return None, 0.0

    src = [(p.px, p.py) for p in points]
    dst = [(p.x, p.y) for p in points]

    if n == 2:
        t = _similarity(src, dst)
    elif n == 3:
        t = _affine(src, dst)
    else:
        t = _homography(src, dst)
    if t is None:
        return None, 0.0

    sq = 0.0
    for (px, py), (X, Y) in zip(src, dst):
        m = t.map(QPointF(px, py))
        sq += (m.x() - X) ** 2 + (m.y() - Y) ** 2
    rms = math.sqrt(sq / n)
    return t, rms


def _similarity(src, dst):
    import numpy as np
    from PyQt6.QtGui import QTransform
    # x = a*px - b*py + tx ;  y = b*px + a*py + ty
    rows, rhs = [], []
    for (px, py), (X, Y) in zip(src, dst):
        rows.append([px, -py, 1, 0]); rhs.append(X)
        rows.append([py, px, 0, 1]);  rhs.append(Y)
    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    a, b, tx, ty = sol
    return QTransform(a, b, 0.0, -b, a, 0.0, tx, ty, 1.0)


def _affine(src, dst):
    import numpy as np
    from PyQt6.QtGui import QTransform
    # x = a*px + b*py + c ;  y = d*px + e*py + f
    rows, rhs = [], []
    for (px, py), (X, Y) in zip(src, dst):
        rows.append([px, py, 1, 0, 0, 0]); rhs.append(X)
        rows.append([0, 0, 0, px, py, 1]); rhs.append(Y)
    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    a, b, c, d, e, f = sol
    return QTransform(a, d, 0.0, b, e, 0.0, c, f, 1.0)


def _homography(src, dst):
    import numpy as np
    from PyQt6.QtGui import QTransform
    # Direct linear transform: solve A h = 0 (h is 9-vector, 3x3 homography)
    A = []
    for (px, py), (X, Y) in zip(src, dst):
        A.append([-px, -py, -1, 0, 0, 0, X * px, X * py, X])
        A.append([0, 0, 0, -px, -py, -1, Y * px, Y * py, Y])
    A = np.array(A, dtype=float)
    try:
        _, _, vt = np.linalg.svd(A)
    except np.linalg.LinAlgError:
        return None
    h = vt[-1]
    if abs(h[8]) < 1e-12:
        return None
    h = h / h[8]
    h11, h12, h13, h21, h22, h23, h31, h32, h33 = h
    # Qt maps point*matrix; see module notes for the index mapping.
    return QTransform(h11, h21, h31, h12, h22, h32, h13, h23, h33)
