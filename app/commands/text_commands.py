"""Commands for the text layer."""

from __future__ import annotations

from app.commands.command import Command
from app.layers.text_layer import TextLayer
from app.models.text_object import TextObject


class PlaceTextCommand(Command):
    def __init__(self, layer: TextLayer, obj: TextObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.add_text(self._obj)

    def undo(self) -> None:
        self._layer.remove_text(self._obj)

    @property
    def description(self) -> str:
        return "Place text"


class RemoveTextCommand(Command):
    def __init__(self, layer: TextLayer, obj: TextObject):
        self._layer = layer
        self._obj = obj
        self._index: int = 0

    def execute(self) -> None:
        for i, o in enumerate(self._layer.objects):
            if o.id == self._obj.id:
                self._index = i
                break
        self._layer.remove_text(self._obj)

    def undo(self) -> None:
        self._layer.objects.insert(self._index, self._obj)
        self._layer.mark_dirty()
        self._layer._recount_over_grid()

    @property
    def description(self) -> str:
        return "Remove text"


class MoveTextCommand(Command):
    def __init__(self, layer: TextLayer, obj: TextObject, new_x: float, new_y: float):
        self._layer = layer
        self._obj = obj
        self._new_x = new_x
        self._new_y = new_y
        self._old_x = obj.x
        self._old_y = obj.y

    def execute(self) -> None:
        self._obj.x = self._new_x
        self._obj.y = self._new_y
        self._layer.mark_dirty()

    def undo(self) -> None:
        self._obj.x = self._old_x
        self._obj.y = self._old_y
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Move text"


class EditTextCommand(Command):
    """Generic command for editing any TextObject property."""

    def __init__(self, layer: TextLayer, obj: TextObject, **changes: object):
        self._layer = layer
        self._obj = obj
        self._new_values = changes
        self._old_values = {k: getattr(obj, k) for k in changes}

    def execute(self) -> None:
        for k, v in self._new_values.items():
            setattr(self._obj, k, v)
        self._layer.mark_dirty()
        if "over_grid" in self._new_values:
            self._layer._recount_over_grid()

    def undo(self) -> None:
        for k, v in self._old_values.items():
            setattr(self._obj, k, v)
        self._layer.mark_dirty()
        if "over_grid" in self._old_values:
            self._layer._recount_over_grid()

    @property
    def description(self) -> str:
        return "Edit text"


class EditTextLayerEffectsCommand(Command):
    """Edit layer-level effects (shadow)."""

    def __init__(self, layer: TextLayer, **changes: object):
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
        return "Edit text layer effects"
