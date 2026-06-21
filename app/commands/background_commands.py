"""Commands for background image editing."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter

from app.commands.command import Command
from app.layers.background_layer import BackgroundImageLayer


class EditImageCommand(Command):
    """Replace the background layer's QImage (Posterize, Delete Selection, Outline)."""

    def __init__(self, layer: BackgroundImageLayer, new_image: QImage, description: str = "Edit Image"):
        self._layer = layer
        self._new_image = new_image.copy()
        self._old_image: QImage | None = None
        self._desc = description

    def execute(self) -> None:
        old = self._layer.get_qimage()
        self._old_image = old.copy() if (old and not old.isNull()) else None
        self._layer.set_qimage(self._new_image.copy())

    def undo(self) -> None:
        if self._old_image and not self._old_image.isNull():
            self._layer.set_qimage(self._old_image.copy())
        else:
            self._layer.set_qimage(QImage())

    @property
    def description(self) -> str:
        return self._desc


class ApplyToNewLayerCommand(Command):
    """Create a new image layer from an edited image, positioned like the source."""

    def __init__(
        self,
        layer_stack,
        source_layer: BackgroundImageLayer,
        new_image: QImage,
    ):
        self._layer_stack = layer_stack
        self._source = source_layer
        self._new_image = new_image.copy()
        self._new_layer: BackgroundImageLayer | None = None
        self._insert_index: int = -1

    def execute(self) -> None:
        # Find source position in stack
        src_idx = -1
        for i, lyr in enumerate(self._layer_stack):
            if lyr is self._source:
                src_idx = i
                break
        self._insert_index = src_idx + 1 if src_idx >= 0 else len(self._layer_stack)

        self._new_layer = BackgroundImageLayer(f"{self._source.name} (edited)")
        self._new_layer.set_qimage(self._new_image.copy())
        self._new_layer.offset_x = self._source.offset_x
        self._new_layer.offset_y = self._source.offset_y
        self._new_layer.scale = self._source.scale
        self._new_layer.clip_to_grid = True
        self._layer_stack.add_layer(self._new_layer, self._insert_index)

    def undo(self) -> None:
        if self._new_layer is None:
            return
        for i, lyr in enumerate(self._layer_stack):
            if lyr is self._new_layer:
                self._layer_stack.remove_layer(i)
                break

    @property
    def description(self) -> str:
        return "Apply to New Layer"


class MergeDownCommand(Command):
    """Merge the active image layer down onto the image layer directly below."""

    def __init__(self, layer_stack, upper: BackgroundImageLayer, lower: BackgroundImageLayer):
        self._layer_stack = layer_stack
        self._upper = upper
        self._lower = lower
        # Undo snapshots
        self._old_lower_image: QImage | None = None
        self._old_lower_offset_x: float = 0.0
        self._old_lower_offset_y: float = 0.0
        self._old_lower_has_edits: bool = False
        self._old_clip_to_grid: bool = False
        self._upper_index: int = -1

    def execute(self) -> None:
        # Snapshot lower layer for undo
        lower_img = self._lower.get_qimage()
        self._old_lower_image = lower_img.copy() if lower_img and not lower_img.isNull() else None
        self._old_lower_offset_x = self._lower.offset_x
        self._old_lower_offset_y = self._lower.offset_y
        self._old_lower_has_edits = self._lower._has_edits

        # Find upper layer index before removal
        for i, lyr in enumerate(self._layer_stack):
            if lyr is self._upper:
                self._upper_index = i
                break

        # Compute world-space bounding boxes
        lw = self._lower.image_width() * self._lower.scale
        lh = self._lower.image_height() * self._lower.scale
        l_x0, l_y0 = self._lower.offset_x, self._lower.offset_y

        uw = self._upper.image_width() * self._upper.scale
        uh = self._upper.image_height() * self._upper.scale
        u_x0, u_y0 = self._upper.offset_x, self._upper.offset_y

        # Union bounding box in world space
        min_x = min(l_x0, u_x0)
        min_y = min(l_y0, u_y0)
        max_x = max(l_x0 + lw, u_x0 + uw)
        max_y = max(l_y0 + lh, u_y0 + uh)

        # New canvas in lower layer's pixel scale
        if self._lower.scale <= 0:
            return
        new_w = max(1, int(round((max_x - min_x) / self._lower.scale)))
        new_h = max(1, int(round((max_y - min_y) / self._lower.scale)))

        merged = QImage(new_w, new_h, QImage.Format.Format_ARGB32_Premultiplied)
        merged.fill(Qt.GlobalColor.transparent)

        p = QPainter(merged)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Paint lower image at full opacity
        lower_qimg = self._lower.get_qimage()
        if lower_qimg and not lower_qimg.isNull():
            lx = (l_x0 - min_x) / self._lower.scale
            ly = (l_y0 - min_y) / self._lower.scale
            p.drawImage(QPointF(lx, ly), lower_qimg)

        # Paint upper image with its opacity
        upper_qimg = self._upper.get_qimage()
        if upper_qimg and not upper_qimg.isNull():
            p.setOpacity(self._upper.opacity)
            ux = (u_x0 - min_x) / self._lower.scale
            uy = (u_y0 - min_y) / self._lower.scale
            scale_ratio = self._upper.scale / self._lower.scale
            p.translate(ux, uy)
            p.scale(scale_ratio, scale_ratio)
            p.drawImage(QPointF(0, 0), upper_qimg)

        p.end()

        # Convert to standard ARGB32 format
        merged = merged.convertToFormat(QImage.Format.Format_ARGB32)

        # Update lower layer
        self._lower.set_qimage(merged)
        self._lower.offset_x = min_x
        self._lower.offset_y = min_y
        self._old_clip_to_grid = self._lower.clip_to_grid
        self._lower.clip_to_grid = True

        # Remove upper layer from stack
        if self._upper_index >= 0:
            self._layer_stack.remove_layer(self._upper_index)

    def undo(self) -> None:
        # Restore lower layer image and position
        if self._old_lower_image and not self._old_lower_image.isNull():
            self._lower.set_qimage(self._old_lower_image.copy())
        else:
            self._lower.set_qimage(QImage())
        self._lower.offset_x = self._old_lower_offset_x
        self._lower.offset_y = self._old_lower_offset_y
        self._lower._has_edits = self._old_lower_has_edits
        self._lower.clip_to_grid = self._old_clip_to_grid
        self._lower.mark_dirty()

        # Re-insert upper layer at original position
        if self._upper_index >= 0:
            self._layer_stack.add_layer(self._upper, self._upper_index)

    @property
    def description(self) -> str:
        return "Merge Down"


class PaintBrushCommand(Command):
    """Capture before/after for a paint brush stroke on the background image."""

    def __init__(self, layer: BackgroundImageLayer):
        self._layer = layer
        self._old_image: QImage | None = None
        self._new_image: QImage | None = None

    def begin(self) -> None:
        """Call before starting a paint stroke to capture initial state."""
        old = self._layer.get_qimage()
        self._old_image = old.copy() if (old and not old.isNull()) else None

    def commit(self) -> None:
        """Call after finishing a stroke to capture the result."""
        current = self._layer.get_qimage()
        self._new_image = current.copy() if (current and not current.isNull()) else None

    def execute(self) -> None:
        if self._new_image and not self._new_image.isNull():
            self._layer.set_qimage(self._new_image.copy())

    def undo(self) -> None:
        if self._old_image and not self._old_image.isNull():
            self._layer.set_qimage(self._old_image.copy())
        else:
            self._layer.set_qimage(QImage())

    @property
    def description(self) -> str:
        return "Paint on image"
