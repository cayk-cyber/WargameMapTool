"""Commands for the border layer."""

from __future__ import annotations

from app.commands.command import Command
from app.layers.border_layer import BorderLayer
from app.models.border_object import BorderObject


class PlaceBorderCommand(Command):
    def __init__(self, layer: BorderLayer, obj: BorderObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.add_border(self._obj)

    def undo(self) -> None:
        self._layer.remove_border(self._obj)

    @property
    def description(self) -> str:
        return "Place border"


class RemoveBorderCommand(Command):
    def __init__(self, layer: BorderLayer, obj: BorderObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.remove_border(self._obj)

    def undo(self) -> None:
        self._layer.add_border(self._obj)

    @property
    def description(self) -> str:
        return "Remove border"


class EditBorderCommand(Command):
    """Generic command for editing any BorderObject property."""

    def __init__(self, layer: BorderLayer, obj: BorderObject, **changes: object):
        self._layer = layer
        self._obj = obj
        self._new_values = changes
        self._old_values = {k: getattr(obj, k) for k in changes}

    def execute(self) -> None:
        for k, v in self._new_values.items():
            setattr(self._obj, k, v)
        self._layer.mark_dirty()

    def undo(self) -> None:
        for k, v in self._old_values.items():
            setattr(self._obj, k, v)
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Edit border"


class EditBorderLayerEffectsCommand(Command):
    """Edit layer-level effects (shadow)."""

    def __init__(self, layer: BorderLayer, **changes: object):
        self._layer = layer
        self._new_values = changes
        self._old_values = {k: getattr(layer, k) for k in changes}

    def execute(self) -> None:
        for k, v in self._new_values.items():
            setattr(self._layer, k, v)
        self._layer.mark_dirty()

    def undo(self) -> None:
        for k, v in self._old_values.items():
            setattr(self._layer, k, v)
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Edit border layer effects"
