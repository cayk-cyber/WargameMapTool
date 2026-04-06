"""Commands for the asset layer."""

from __future__ import annotations

from PySide6.QtGui import QImage

from app.commands.command import Command
from app.layers.asset_layer import AssetLayer
from app.models.asset_object import AssetObject


class PlaceAssetCommand(Command):
    def __init__(self, layer: AssetLayer, asset: AssetObject):
        self._layer = layer
        self._asset = asset

    def execute(self) -> None:
        self._layer.add_asset(self._asset)

    def undo(self) -> None:
        self._layer.remove_asset(self._asset)

    @property
    def description(self) -> str:
        return "Place asset"


class RemoveAssetCommand(Command):
    def __init__(self, layer: AssetLayer, asset: AssetObject):
        self._layer = layer
        self._asset = asset
        self._index: int = 0

    def execute(self) -> None:
        for i, obj in enumerate(self._layer.objects):
            if obj.id == self._asset.id:
                self._index = i
                break
        self._layer.remove_asset(self._asset)

    def undo(self) -> None:
        self._layer.objects.insert(self._index, self._asset)
        self._layer._spatial.insert(self._asset)  # M06: keep spatial index in sync
        self._layer._composite_cache = None  # clear composite cache for correct render
        # Spatial index already updated above — skip expensive rebuild.
        self._layer._mark_visual_dirty()

    @property
    def description(self) -> str:
        return "Remove asset"


class MoveAssetCommand(Command):
    def __init__(self, layer: AssetLayer, asset: AssetObject, new_x: float, new_y: float):
        self._layer = layer
        self._asset = asset
        self._new_x = new_x
        self._new_y = new_y
        self._old_x = asset.x
        self._old_y = asset.y

    def execute(self) -> None:
        self._asset.x = self._new_x
        self._asset.y = self._new_y
        self._layer.mark_dirty()

    def undo(self) -> None:
        self._asset.x = self._old_x
        self._asset.y = self._old_y
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Move asset"


class TransformAssetCommand(Command):
    def __init__(
        self,
        layer: AssetLayer,
        asset: AssetObject,
        new_scale: float | None = None,
        new_rotation: float | None = None,
    ):
        self._layer = layer
        self._asset = asset
        self._new_scale = new_scale if new_scale is not None else asset.scale
        self._new_rotation = new_rotation if new_rotation is not None else asset.rotation
        self._old_scale = asset.scale
        self._old_rotation = asset.rotation

    def execute(self) -> None:
        self._asset.scale = self._new_scale
        self._asset.rotation = self._new_rotation
        self._layer.mark_dirty()

    def undo(self) -> None:
        self._asset.scale = self._old_scale
        self._asset.rotation = self._old_rotation
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Transform asset"


class PaintMaskCommand(Command):
    """Records one erase stroke for undo/redo.

    The stroke is applied directly during the drag; this command only stores
    pre/post snapshots so the operation can be undone and redone.
    """

    def __init__(self, layer: AssetLayer, pre_image: QImage | None, post_image: QImage | None):
        self._layer = layer
        self._pre = pre_image
        self._post = post_image

    def execute(self) -> None:
        # Redo: restore post-stroke state
        self._layer.restore_mask(self._post)

    def undo(self) -> None:
        self._layer.restore_mask(self._pre)

    @property
    def description(self) -> str:
        return "Erase assets"


class EditAssetLayerEffectsCommand(Command):
    """Edit layer-level effects (shadow)."""

    def __init__(self, layer: AssetLayer, **changes: object):
        self._layer = layer
        self._new_values = changes
        self._old_values = {k: getattr(layer, k) for k in changes}

    def execute(self) -> None:
        for k, v in self._new_values.items():
            setattr(self._layer, k, v)
        # Shadow/effect properties only — no geometry change, skip spatial rebuild.
        self._layer._mark_visual_dirty()

    def undo(self) -> None:
        for k, v in self._old_values.items():
            setattr(self._layer, k, v)
        self._layer._mark_visual_dirty()

    @property
    def description(self) -> str:
        return "Edit asset layer effects"


