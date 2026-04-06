"""Commands for background image editing."""

from __future__ import annotations

from PySide6.QtGui import QImage

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
        self._new_layer.clip_to_grid = self._source.clip_to_grid
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
