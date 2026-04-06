"""Commands for the freeform path layer."""

from __future__ import annotations

import copy

from app.commands.command import Command
from app.layers.freeform_path_layer import FreeformPathLayer
from app.models.freeform_path_object import FreeformPathObject


class PlaceFreeformPathCommand(Command):
    def __init__(self, layer: FreeformPathLayer, obj: FreeformPathObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.add_path(self._obj)

    def undo(self) -> None:
        self._layer.remove_path(self._obj)

    @property
    def description(self) -> str:
        return "Place freeform path"


class RemoveFreeformPathCommand(Command):
    def __init__(self, layer: FreeformPathLayer, obj: FreeformPathObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.remove_path(self._obj)

    def undo(self) -> None:
        self._layer.add_path(self._obj)

    @property
    def description(self) -> str:
        return "Remove freeform path"


class EditFreeformPathCommand(Command):
    """Generic command for editing any FreeformPathObject property."""

    def __init__(self, layer: FreeformPathLayer, obj: FreeformPathObject, **changes: object):
        self._layer = layer
        self._obj = obj
        # M04: deep-copy mutable values (e.g. points list) to prevent aliasing
        self._new_values = {k: copy.deepcopy(v) for k, v in changes.items()}
        self._old_values = {k: copy.deepcopy(getattr(obj, k)) for k in changes}

    def execute(self) -> None:
        for k, v in self._new_values.items():
            setattr(self._obj, k, v)
        # Invalidate path cache whenever the points list is replaced
        if "points" in self._new_values:
            self._obj.increment_points_version()
        self._layer.mark_dirty()

    def undo(self) -> None:
        for k, v in self._old_values.items():
            setattr(self._obj, k, v)
        # Invalidate path cache when restoring a previous points list
        if "points" in self._old_values:
            self._obj.increment_points_version()
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Edit freeform path"


class MoveFreeformPointCommand(Command):
    """Move a single waypoint in a freeform path."""

    def __init__(
        self,
        layer: FreeformPathLayer,
        obj: FreeformPathObject,
        point_index: int,
        old_pos: tuple[float, float],
        new_pos: tuple[float, float],
    ):
        self._layer = layer
        self._obj = obj
        self._index = point_index
        self._old = old_pos
        self._new = new_pos

    def execute(self) -> None:
        self._obj.points[self._index] = self._new
        self._obj.increment_points_version()
        self._layer.mark_dirty()

    def undo(self) -> None:
        self._obj.points[self._index] = self._old
        self._obj.increment_points_version()
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Move freeform point"


class EditFreeformPathLayerEffectsCommand(Command):
    """Edit layer-level effects (shadow)."""

    def __init__(self, layer: FreeformPathLayer, **changes: object):
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
        return "Edit freeform path layer effects"
