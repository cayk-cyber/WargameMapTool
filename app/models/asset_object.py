"""Asset object data class."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPixmap, QTransform


@dataclass
class AssetObject:
    image_path: str = ""
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0  # degrees
    snap_to_hex: bool = True
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _pixmap: QPixmap | None = field(default=None, repr=False, compare=False)
    # Bounding rect cache (self-validating key)
    _cached_br: QRectF | None = field(default=None, repr=False, compare=False)
    _br_key: tuple | None = field(default=None, repr=False, compare=False)

    def get_pixmap(self) -> QPixmap:
        if self._pixmap is None or self._pixmap.isNull():
            self._pixmap = QPixmap(self.image_path)
        return self._pixmap

    def bounding_rect(self) -> QRectF:
        key = (self.x, self.y, self.scale, self.rotation, self.image_path)
        if self._cached_br is not None and self._br_key == key:
            return self._cached_br

        pm = self.get_pixmap()
        if pm.isNull():
            result = QRectF(self.x - 16, self.y - 16, 32, 32)
        else:
            w = pm.width() * self.scale
            h = pm.height() * self.scale

            # Account for rotation: compute exact AABB from 4 rotated corners (L10)
            transform = QTransform()
            transform.rotate(self.rotation)
            corners = [
                transform.map(QPointF(-w / 2, -h / 2)),
                transform.map(QPointF( w / 2, -h / 2)),
                transform.map(QPointF(-w / 2,  h / 2)),
                transform.map(QPointF( w / 2,  h / 2)),
            ]
            xs = [p.x() for p in corners]
            ys = [p.y() for p in corners]
            result = QRectF(
                self.x + min(xs),
                self.y + min(ys),
                max(xs) - min(xs),
                max(ys) - min(ys),
            )

        self._cached_br = result
        self._br_key = key
        return result

    def contains_point(self, world_x: float, world_y: float) -> bool:
        return self.bounding_rect().contains(QPointF(world_x, world_y))

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "image": self.image_path,
            "x": self.x,
            "y": self.y,
            "scale": self.scale,
            "rotation": self.rotation,
            "snap_to_hex": self.snap_to_hex,
        }

    @classmethod
    def deserialize(cls, data: dict) -> AssetObject:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            image_path=data.get("image", ""),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            scale=data.get("scale", 1.0),
            rotation=data.get("rotation", 0.0),
            snap_to_hex=data.get("snap_to_hex", True),
        )
