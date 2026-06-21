"""Draw channel data class - mask-based painting channel."""

from __future__ import annotations

import base64
import math
import uuid

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PySide6.QtGui import QColor, QImage

# Safety cap: maximum mask dimension in pixels per axis.
_MAX_MASK_DIM = 8192

# Draw quality scale: 1.0 = Performance (1× world-res), 2.0 = Quality (2× world-res).
_draw_quality_scale: float = 1.0


def set_draw_quality_mode(quality: bool) -> None:
    """Set draw mask quality scale (True = 2×, False = 1×)."""
    global _draw_quality_scale
    _draw_quality_scale = 2.0 if quality else 1.0


def get_draw_quality_scale() -> float:
    """Return current draw quality scale factor."""
    return _draw_quality_scale


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

        # Edge bleeding effect (per-channel, color mode only).
        self.edge_color: str = ""          # empty = disabled; "#rrggbb" = bleed color
        self.edge_distance: float = 20.0   # transition length in mask pixels
        self.edge_noise: float = 0.3       # 0.0 = smooth gradient, 1.0 = max organic

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

        The mask covers world_rect at _draw_quality_scale × world-pixel
        resolution (1× Performance, 2× Quality).  Capped to _MAX_MASK_DIM
        per axis as safety net.
        """
        if self.mask_image is not None:
            return

        w_raw = max(1, math.ceil(world_rect.width()))
        h_raw = max(1, math.ceil(world_rect.height()))
        scale = _draw_quality_scale
        w_desired = max(1, round(w_raw * scale))
        h_desired = max(1, round(h_raw * scale))
        if _MAX_MASK_DIM > 0 and (w_desired > _MAX_MASK_DIM or h_desired > _MAX_MASK_DIM):
            cap = min(_MAX_MASK_DIM / w_desired, _MAX_MASK_DIM / h_desired)
            scale *= cap
        w = max(1, int(w_raw * scale))
        h = max(1, int(h_raw * scale))

        self._mask_world_offset = (world_rect.x(), world_rect.y())
        self._mask_world_scale = scale
        self.mask_image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        self.mask_image.fill(QColor(0, 0, 0, 0))  # fully transparent = nothing painted

    def rescale_mask(self, new_scale: float) -> None:
        """Rescale an existing mask to a new world scale (e.g. 1.0 → 2.0).

        Preserves painted content via smooth bilinear interpolation.
        No-op if mask is None or the scale is already matching.
        """
        if self.mask_image is None:
            return
        if abs(self._mask_world_scale - new_scale) < 0.001:
            return
        from PySide6.QtCore import Qt as _Qt
        ratio = new_scale / self._mask_world_scale
        new_w = max(1, round(self.mask_image.width() * ratio))
        new_h = max(1, round(self.mask_image.height() * ratio))
        self.mask_image = self.mask_image.scaled(
            new_w, new_h,
            _Qt.AspectRatioMode.IgnoreAspectRatio,
            _Qt.TransformationMode.SmoothTransformation,
        )
        self._mask_world_scale = new_scale

    def resize_mask(self, new_world_rect: QRectF) -> None:
        """Resize mask to cover a new (larger/smaller) world rect, preserving content."""
        if self.mask_image is None:
            return
        old_mask = self.mask_image
        old_offset = self._mask_world_offset
        old_scale = self._mask_world_scale

        # Create new mask at same quality scale
        w_raw = max(1, math.ceil(new_world_rect.width()))
        h_raw = max(1, math.ceil(new_world_rect.height()))
        scale = old_scale  # preserve quality scale
        w_desired = max(1, round(w_raw * scale))
        h_desired = max(1, round(h_raw * scale))
        if _MAX_MASK_DIM > 0 and (w_desired > _MAX_MASK_DIM or h_desired > _MAX_MASK_DIM):
            cap = min(_MAX_MASK_DIM / w_desired, _MAX_MASK_DIM / h_desired)
            scale *= cap
        w = max(1, int(w_raw * scale))
        h = max(1, int(h_raw * scale))

        new_mask = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        new_mask.fill(QColor(0, 0, 0, 0))  # transparent

        # Composite old mask at correct position in new mask
        from PySide6.QtCore import QPointF as _QPointF
        from PySide6.QtGui import QPainter as _P

        p = _P(new_mask)
        ox = (old_offset[0] - new_world_rect.x()) * scale
        oy = (old_offset[1] - new_world_rect.y()) * scale
        sx = scale / old_scale
        p.translate(ox, oy)
        p.scale(sx, sx)
        p.drawImage(_QPointF(0, 0), old_mask)
        p.end()

        self.mask_image = new_mask
        self._mask_world_offset = (new_world_rect.x(), new_world_rect.y())
        self._mask_world_scale = scale

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
        if self.edge_color:
            data["edge_color"] = self.edge_color
            data["edge_distance"] = round(self.edge_distance, 1)
            data["edge_noise"] = round(self.edge_noise, 3)
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
        ch.edge_color = data.get("edge_color", "")
        ch.edge_distance = data.get("edge_distance", 20.0)
        ch.edge_noise = data.get("edge_noise", 0.3)
        return ch
