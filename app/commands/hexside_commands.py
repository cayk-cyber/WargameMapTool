"""Commands for the hexside layer."""

from __future__ import annotations

import copy

from app.commands.command import Command
from app.layers.hexside_layer import HexsideLayer
from app.models.hexside_object import HexsideObject


class PlaceHexsideCommand(Command):
    def __init__(self, layer: HexsideLayer, obj: HexsideObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.add_hexside(self._obj)

    def undo(self) -> None:
        self._layer.remove_hexside(self._obj)

    @property
    def description(self) -> str:
        return "Place hexside"


class RemoveHexsideCommand(Command):
    def __init__(self, layer: HexsideLayer, obj: HexsideObject):
        self._layer = layer
        self._obj = obj

    def execute(self) -> None:
        self._layer.remove_hexside(self._obj)

    def undo(self) -> None:
        self._layer.add_hexside(self._obj)

    @property
    def description(self) -> str:
        return "Remove hexside"


class EditHexsideCommand(Command):
    """Generic command for editing any HexsideObject property."""

    def __init__(self, layer: HexsideLayer, obj: HexsideObject, **changes: object):
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
        return "Edit hexside"


class MoveControlPointCommand(Command):
    """Move a single control point offset (used during drag in select mode)."""

    def __init__(
        self,
        layer: HexsideLayer,
        obj: HexsideObject,
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
    """Move an endpoint (ep_a or ep_b) of a HexsideObject in 2D."""

    def __init__(
        self,
        layer: HexsideLayer,
        obj: HexsideObject,
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
        return "Move hexside endpoint"


class MoveSyncedEndpointsCommand(Command):
    """Move multiple hexside endpoints together in one undo step.

    Used when dragging a shared endpoint that belongs to multiple hexsides
    meeting at the same hex vertex.
    """

    def __init__(
        self,
        layer: HexsideLayer,
        moves: list[tuple[HexsideObject, str, list[float], list[float]]],
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
        return "Move hexside endpoints"


class SyncRandomEndpointCommand(Command):
    """Set random_endpoint on multiple hexsides atomically (for endpoint connectivity).

    Used when the user changes the Endpoints slider for a selected hexside to
    propagate the new amplitude to all hexsides sharing either of its vertices,
    so that hex_vertex_endpoint_offset() produces the same displacement everywhere.
    """

    def __init__(
        self,
        layer: HexsideLayer,
        changes: list[tuple[HexsideObject, float, float]],
    ):
        # changes: list of (obj, old_random_endpoint, new_random_endpoint)
        self._layer = layer
        self._changes = [(obj, float(old), float(new)) for obj, old, new in changes]

    def execute(self) -> None:
        for obj, _old, new in self._changes:
            obj.random_endpoint = new
        self._layer.mark_dirty()

    def undo(self) -> None:
        for obj, old, _new in self._changes:
            obj.random_endpoint = old
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Sync hexside endpoint amplitude"


class EditHexsideLayerEffectsCommand(Command):
    """Edit layer-level effects (shadow)."""

    def __init__(self, layer: HexsideLayer, **changes: object):
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
        return "Edit hexside layer effects"
