"""Commands for the sketch layer."""

from __future__ import annotations

import copy

from app.commands.command import Command
from app.layers.sketch_layer import SketchLayer
from app.models.sketch_object import SketchObject


class PlaceSketchCommand(Command):
    def __init__(self, layer: SketchLayer, obj: SketchObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.add_object(self._obj)

    def undo(self) -> None:
        self._layer.remove_object(self._obj)

    @property
    def description(self) -> str:
        return "Place sketch"


class RemoveSketchCommand(Command):
    def __init__(self, layer: SketchLayer, obj: SketchObject):
        self._layer = layer
        self._obj = obj
        self._index = -1

    def execute(self) -> None:
        self._index = self._layer.index_of(self._obj)
        self._layer.remove_object(self._obj)

    def undo(self) -> None:
        if self._index >= 0:
            self._layer.insert_object(self._index, self._obj)
        else:
            self._layer.add_object(self._obj)

    @property
    def description(self) -> str:
        return "Remove sketch"


class EditSketchCommand(Command):
    """Generic command for editing any SketchObject property."""

    def __init__(self, layer: SketchLayer, obj: SketchObject, **changes: object):
        self._layer = layer
        self._obj = obj
        # M04: deep-copy mutable values (e.g. points list) to prevent aliasing
        self._new_values = {k: copy.deepcopy(v) for k, v in changes.items()}
        self._old_values = {k: copy.deepcopy(getattr(obj, k)) for k in changes}

    def execute(self) -> None:
        for k, v in self._new_values.items():
            setattr(self._obj, k, v)
        self._layer.mark_dirty()
        if "draw_over_grid" in self._new_values:
            self._layer._recount_over_grid()

    def undo(self) -> None:
        for k, v in self._old_values.items():
            setattr(self._obj, k, v)
        self._layer.mark_dirty()
        if "draw_over_grid" in self._old_values:
            self._layer._recount_over_grid()

    @property
    def description(self) -> str:
        return "Edit sketch"


class MoveSketchCommand(Command):
    """Move a sketch object by translating all points."""

    def __init__(self, layer: SketchLayer, obj: SketchObject,
                 dx: float, dy: float):
        self._layer = layer
        self._obj = obj
        self._dx = dx
        self._dy = dy

    def execute(self) -> None:
        self._obj.points = [
            (p[0] + self._dx, p[1] + self._dy) for p in self._obj.points
        ]
        self._layer.mark_dirty()

    def undo(self) -> None:
        self._obj.points = [
            (p[0] - self._dx, p[1] - self._dy) for p in self._obj.points
        ]
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Move sketch"


class ResizeSketchCommand(Command):
    """Resize a sketch object by storing old and new geometry."""

    def __init__(self, layer: SketchLayer, obj: SketchObject,
                 old_points: list[tuple[float, float]],
                 new_points: list[tuple[float, float]],
                 old_radius: float, new_radius: float,
                 old_rx: float, new_rx: float,
                 old_ry: float, new_ry: float):
        self._layer = layer
        self._obj = obj
        self._old_points = old_points
        self._new_points = new_points
        self._old_radius = old_radius
        self._new_radius = new_radius
        self._old_rx = old_rx
        self._new_rx = new_rx
        self._old_ry = old_ry
        self._new_ry = new_ry

    def execute(self) -> None:
        self._obj.points = list(self._new_points)
        self._obj.radius = self._new_radius
        self._obj.rx = self._new_rx
        self._obj.ry = self._new_ry
        self._layer.mark_dirty()

    def undo(self) -> None:
        self._obj.points = list(self._old_points)
        self._obj.radius = self._old_radius
        self._obj.rx = self._old_rx
        self._obj.ry = self._old_ry
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Resize sketch"


class EditSketchLayerEffectsCommand(Command):
    """Edit layer-level effects (shadow)."""

    def __init__(self, layer: SketchLayer, **changes: object):
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
        return "Edit sketch effects"


class RotateSketchCommand(Command):
    """Rotate a sketch object."""

    def __init__(self, layer: SketchLayer, obj: SketchObject,
                 old_rotation: float, new_rotation: float):
        self._layer = layer
        self._obj = obj
        self._old_rotation = old_rotation
        self._new_rotation = new_rotation

    def execute(self) -> None:
        self._obj.rotation = self._new_rotation
        self._layer.mark_dirty()

    def undo(self) -> None:
        self._obj.rotation = self._old_rotation
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Rotate sketch"
