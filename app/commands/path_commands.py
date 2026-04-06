"""Commands for the path layer."""

from __future__ import annotations

import copy

from app.commands.command import Command
from app.layers.path_layer import PathLayer
from app.models.path_object import PathObject


class PlacePathCommand(Command):
    def __init__(self, layer: PathLayer, obj: PathObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.add_path(self._obj)

    def undo(self) -> None:
        self._layer.remove_path(self._obj)

    @property
    def description(self) -> str:
        return "Place path"


class RemovePathCommand(Command):
    def __init__(self, layer: PathLayer, obj: PathObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.remove_path(self._obj)

    def undo(self) -> None:
        self._layer.add_path(self._obj)

    @property
    def description(self) -> str:
        return "Remove path"


class EditPathCommand(Command):
    """Generic command for editing any PathObject property."""

    def __init__(self, layer: PathLayer, obj: PathObject, **changes: object):
        self._layer = layer
        self._obj = obj
        # M04: deep-copy mutable values (e.g. control_points list) to prevent aliasing
        self._new_values = {k: copy.deepcopy(v) for k, v in changes.items()}
        self._old_values = {k: copy.deepcopy(getattr(obj, k)) for k in changes}

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
        return "Edit path"


class MoveControlPointCommand(Command):
    """Move a single control point offset (used during drag in select mode)."""

    def __init__(
        self,
        layer: PathLayer,
        obj: PathObject,
        point_index: int,
        old_offset: float,
        new_offset: float,
    ):
        self._layer = layer
        self._obj = obj
        self._index = point_index
        self._old = old_offset
        self._new = new_offset

    def execute(self) -> None:
        self._obj.control_points[self._index] = self._new
        self._layer.mark_dirty()

    def undo(self) -> None:
        self._obj.control_points[self._index] = self._old
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Move control point"


class MoveEndpointCommand(Command):
    """Move an endpoint (ep_a or ep_b) of a PathObject in 2D."""

    def __init__(
        self,
        layer: PathLayer,
        obj: PathObject,
        endpoint: str,  # "a" or "b"
        old_ep: list[float],
        new_ep: list[float],
    ):
        self._layer = layer
        self._obj = obj
        self._endpoint = endpoint
        self._old = list(old_ep)
        self._new = list(new_ep)

    def execute(self) -> None:
        setattr(self._obj, f"ep_{self._endpoint}", list(self._new))
        self._layer.mark_dirty()

    def undo(self) -> None:
        setattr(self._obj, f"ep_{self._endpoint}", list(self._old))
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Move path endpoint"


class MoveSyncedEndpointsCommand(Command):
    """Move multiple path endpoints together in one undo step.

    Used when dragging a shared endpoint that belongs to multiple paths
    meeting at the same hex center.
    """

    def __init__(
        self,
        layer: PathLayer,
        moves: list[tuple[PathObject, str, list[float], list[float]]],
        # each entry: (obj, "a" or "b", old_ep, new_ep)
    ):
        self._layer = layer
        self._moves = [(obj, ep, list(old), list(new)) for obj, ep, old, new in moves]

    def execute(self) -> None:
        for obj, ep, _old, new in self._moves:
            setattr(obj, f"ep_{ep}", list(new))
        self._layer.mark_dirty()

    def undo(self) -> None:
        for obj, ep, old, _new in self._moves:
            setattr(obj, f"ep_{ep}", list(old))
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Move path endpoints"


class EditPathLayerEffectsCommand(Command):
    """Edit layer-level effects (shadow)."""

    def __init__(self, layer: PathLayer, **changes: object):
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
        return "Edit path layer effects"
