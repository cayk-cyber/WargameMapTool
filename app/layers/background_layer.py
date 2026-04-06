"""Background image layer for reference/tracing."""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainter, QPixmap, QImage

from app.hex.hex_math import Layout
from app.layers.base_layer import Layer


class BackgroundImageLayer(Layer):
    def __init__(self, name: str = "Background"):
        super().__init__(name)
        self.image_path: str | None = None
        self.edited_image_path: str | None = None  # relative path to saved edit PNG
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0
        self.scale: float = 1.0
        self._qimage: QImage | None = None       # source of truth for pixels
        self._pixmap: QPixmap | None = None      # render cache, rebuilt from _qimage
        self._has_edits: bool = False            # True once any edit operation has been applied
        # Set by project_io before serialize() so we can save the edit PNG there
        self.project_dir: str | None = None

    # ------------------------------------------------------------------
    # Image access
    # ------------------------------------------------------------------

    def get_qimage(self) -> QImage | None:
        return self._qimage

    def set_qimage(self, img: QImage) -> None:
        """Replace the working image, invalidate pixmap cache, mark layer dirty."""
        self._qimage = img if (img is not None and not img.isNull()) else None  # L01: explicit None check
        self._pixmap = None
        self._has_edits = True
        self.mark_dirty()

    @property
    def has_edits(self) -> bool:
        """True once any paint/edit operation has been applied to this layer. L22"""
        return self._has_edits

    def has_image(self) -> bool:
        return self._qimage is not None and not self._qimage.isNull()

    def image_width(self) -> int:
        return self._qimage.width() if self.has_image() else 0

    def image_height(self) -> int:
        return self._qimage.height() if self.has_image() else 0

    # ------------------------------------------------------------------
    # Coordinate mapping
    # ------------------------------------------------------------------

    def world_to_pixel(self, wx: float, wy: float) -> tuple[int, int]:
        """Convert world coordinates to image pixel coordinates."""
        if self.scale == 0:
            return (0, 0)
        ix = int((wx - self.offset_x) / self.scale)
        iy = int((wy - self.offset_y) / self.scale)
        return (ix, iy)

    def pixel_to_world(self, px: int, py: int) -> tuple[float, float]:
        """Convert image pixel coordinates to world coordinates."""
        wx = px * self.scale + self.offset_x
        wy = py * self.scale + self.offset_y
        return (wx, wy)

    def pixel_in_bounds(self, px: int, py: int) -> bool:
        if not self.has_image():
            return False
        return 0 <= px < self._qimage.width() and 0 <= py < self._qimage.height()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_image(self, path: str) -> bool:
        img = QImage(path)
        if img.isNull():
            return False
        self._qimage = img.convertToFormat(QImage.Format.Format_ARGB32)
        self._pixmap = None
        self.image_path = path
        self._has_edits = False
        self.mark_dirty()
        return True

    # ------------------------------------------------------------------
    # Pixmap cache
    # ------------------------------------------------------------------

    def _get_pixmap(self) -> QPixmap | None:
        if self._qimage is None or self._qimage.isNull():
            return None
        if self._pixmap is None:
            self._pixmap = QPixmap.fromImage(self._qimage)
        return self._pixmap

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paint(self, painter: QPainter, viewport_rect: QRectF, layout: Layout) -> None:
        pm = self._get_pixmap()
        if pm is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.offset_x, self.offset_y)
        painter.scale(self.scale, self.scale)
        painter.drawPixmap(QPointF(0, 0), pm)
        painter.restore()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "background"
        data["image_path"] = self.image_path or ""
        data["offset_x"] = self.offset_x
        data["offset_y"] = self.offset_y
        data["scale"] = self.scale
        data["clip_to_grid"] = self.clip_to_grid

        # Save edited image if present
        if self._has_edits and self._qimage and not self._qimage.isNull():
            if self.project_dir:
                edit_filename = f"{self.id}_bg_edit.png"
                edit_path = os.path.join(self.project_dir, edit_filename)
                self._qimage.save(edit_path, "PNG")
                data["edited_image_path"] = edit_filename
            elif self.edited_image_path:
                data["edited_image_path"] = self.edited_image_path

        return data

    @classmethod
    def deserialize(cls, data: dict) -> BackgroundImageLayer:
        layer = cls(data.get("name", "Background"))
        layer._base_deserialize(data)
        layer.offset_x = data.get("offset_x", 0.0)
        layer.offset_y = data.get("offset_y", 0.0)
        layer.scale = data.get("scale", 1.0)
        layer.clip_to_grid = data.get("clip_to_grid", False)

        # Load edited image first (takes priority), then original
        edited_path = data.get("edited_image_path", "")
        if edited_path and os.path.isfile(edited_path):
            img = QImage(edited_path)
            if not img.isNull():
                layer._qimage = img.convertToFormat(QImage.Format.Format_ARGB32)
                layer._has_edits = True
                layer.edited_image_path = os.path.basename(edited_path)
                layer.image_path = data.get("image_path", "") or None
                return layer

        image_path = data.get("image_path", "")
        if image_path:
            layer.load_image(image_path)
            layer._has_edits = False  # reset: this is the original
        return layer
