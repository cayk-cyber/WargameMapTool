"""Draw channel data class - mask-based painting channel."""

from __future__ import annotations

import base64
import math
import uuid

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PySide6.QtGui import QColor, QImage

# Maximum mask dimension in pixels.
# 0 = no limit (mask matches world size 1:1 for pixel-perfect strokes).
_MAX_MASK_DIM = 0


class DrawChannel:
    """A single paint channel with its own color/texture and accumulation mask.

    Multiple channels in one DrawLayer allow different colors/textures to be
    painted on the same layer.  The mask is a world-space QImage whose alpha
    channel controls where the channel content is visible:
      alpha = 0   → not yet painted (transparent)
      alpha = 255 → fully painted (opaque)

    The mask is created lazily via ensure_mask() the first time the user
    paints on this channel.
    """

    def __init__(
        self,
        ch_id: str | None = None,
        name: str = "Channel",
        color: str = "#000000",
        texture_id: str = "",
        texture_zoom: float = 1.0,
        texture_rotation: float = 0.0,
        opacity: float = 1.0,
        visible: bool = True,
    ) -> None:
        self.id: str = ch_id or uuid.uuid4().hex[:8]
        self.name: str = name
        self.color: str = color
        self.texture_id: str = texture_id
        self.texture_zoom: float = texture_zoom
        self.texture_rotation: float = texture_rotation
        self.opacity: float = opacity
        self.visible: bool = visible

        # Mask (ARGB32_Premultiplied, white pixels = painted, transparent = empty).
        # Initialized lazily via ensure_mask().
        self.mask_image: QImage | None = None
        self._mask_world_offset: tuple[float, float] = (0.0, 0.0)
        self._mask_world_scale: float = 1.0  # mask_px = world_unit * scale

    # -------------------------------------------------------------------------
    # Mask management
    # -------------------------------------------------------------------------

    def ensure_mask(self, world_rect: QRectF) -> None:
        """Create mask_image if it does not exist yet (idempotent).

        The mask covers world_rect at 1:1 world-pixel resolution (no downsampling)
        unless _MAX_MASK_DIM is set, in which case it caps each dimension.
        """
        if self.mask_image is not None:
            return

        w_raw = max(1, math.ceil(world_rect.width()))
        h_raw = max(1, math.ceil(world_rect.height()))
        scale = 1.0
        if _MAX_MASK_DIM > 0 and (w_raw > _MAX_MASK_DIM or h_raw > _MAX_MASK_DIM):
            scale = min(_MAX_MASK_DIM / w_raw, _MAX_MASK_DIM / h_raw)
        w = max(1, int(w_raw * scale))
        h = max(1, int(h_raw * scale))

        self._mask_world_offset = (world_rect.x(), world_rect.y())
        self._mask_world_scale = scale
        self.mask_image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        self.mask_image.fill(QColor(0, 0, 0, 0))  # fully transparent = nothing painted

    def get_mask_snapshot(self) -> QImage | None:
        """Return a deep copy of the current mask for undo purposes."""
        return self.mask_image.copy() if self.mask_image is not None else None

    def restore_mask(self, snapshot: QImage | None) -> None:
        """Restore the mask from a snapshot (called during undo/redo)."""
        self.mask_image = snapshot.copy() if snapshot is not None else None

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def serialize(self) -> dict:
        data: dict = {"id": self.id, "name": self.name}
        if self.texture_id:
            data["texture_id"] = self.texture_id
            if self.texture_zoom != 1.0:
                data["texture_zoom"] = round(self.texture_zoom, 2)
            if self.texture_rotation != 0.0:
                data["texture_rotation"] = round(self.texture_rotation, 2)
        else:
            data["color"] = self.color
        if self.opacity != 1.0:
            data["opacity"] = round(self.opacity, 2)
        if not self.visible:
            data["visible"] = False
        if self.mask_image is not None:
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            self.mask_image.save(buf, "PNG")
            buf.close()
            data["mask_image"] = base64.b64encode(ba.data()).decode("ascii")
            data["mask_world_offset_x"] = round(self._mask_world_offset[0], 4)
            data["mask_world_offset_y"] = round(self._mask_world_offset[1], 4)
            data["mask_world_scale"] = round(self._mask_world_scale, 6)
        return data

    @classmethod
    def deserialize(cls, data: dict) -> DrawChannel:
        ch = cls(
            ch_id=data.get("id"),
            name=data.get("name", "Channel"),
            color=data.get("color", "#000000"),
            texture_id=data.get("texture_id", ""),
            texture_zoom=data.get("texture_zoom", 1.0),
            texture_rotation=data.get("texture_rotation", 0.0),
            opacity=data.get("opacity", 1.0),
            visible=data.get("visible", True),
        )
        if "mask_image" in data:
            try:
                raw = base64.b64decode(data["mask_image"])  # M16: guard against corrupt base64
            except Exception:
                raw = None
            if raw:
                img = QImage()
                img.loadFromData(raw, "PNG")
                if not img.isNull():
                    ch.mask_image = img.convertToFormat(
                        QImage.Format.Format_ARGB32_Premultiplied
                    )
                    ch._mask_world_offset = (
                        data.get("mask_world_offset_x", 0.0),
                        data.get("mask_world_offset_y", 0.0),
                    )
                    ch._mask_world_scale = data.get("mask_world_scale", 1.0)
        return ch
