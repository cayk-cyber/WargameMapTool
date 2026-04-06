"""Commands for the draw layer (channel-mask system)."""

from __future__ import annotations

from app.commands.command import Command
from app.layers.draw_layer import DrawLayer
from app.models.draw_object import DrawChannel


class DrawMaskCommand(Command):
    """Undo/Redo a brush stroke (saves mask snapshots before and after)."""

    def __init__(
        self,
        layer: DrawLayer,
        channel_id: str,
        before: object,  # QImage | None
        after: object,   # QImage | None
    ):
        self._layer = layer
        self._channel_id = channel_id
        self._before = before
        self._after = after

    def execute(self) -> None:
        ch = self._layer.find_channel(self._channel_id)
        if ch is not None:
            ch.restore_mask(self._after)
        self._layer.mark_channel_dirty(self._channel_id)

    def undo(self) -> None:
        ch = self._layer.find_channel(self._channel_id)
        if ch is not None:
            ch.restore_mask(self._before)
        self._layer.mark_channel_dirty(self._channel_id)

    @property
    def description(self) -> str:
        return "Draw stroke"


class DrawAddChannelCommand(Command):
    """Add a new channel to the draw layer."""

    def __init__(self, layer: DrawLayer, channel: DrawChannel, index: int = -1):
        self._layer = layer
        self._channel = channel
        self._index = index

    def execute(self) -> None:
        if self._index < 0:
            self._layer.add_channel(self._channel)
        else:
            self._layer.insert_channel(self._index, self._channel)

    def undo(self) -> None:
        self._layer.remove_channel(self._channel)

    @property
    def description(self) -> str:
        return "Add draw channel"


class DrawRemoveChannelCommand(Command):
    """Remove a channel from the draw layer."""

    def __init__(self, layer: DrawLayer, channel: DrawChannel):
        self._layer = layer
        self._channel = channel
        self._index: int = -1

    def execute(self) -> None:
        self._index = self._layer.index_of(self._channel)
        self._layer.remove_channel(self._channel)

    def undo(self) -> None:
        if self._index >= 0:
            self._layer.insert_channel(self._index, self._channel)
        else:
            self._layer.add_channel(self._channel)

    @property
    def description(self) -> str:
        return "Remove draw channel"


class DrawMoveChannelCommand(Command):
    """Move a channel up or down in the stack."""

    def __init__(self, layer: DrawLayer, channel: DrawChannel, new_index: int):
        self._layer = layer
        self._channel = channel
        self._new_index = new_index
        self._old_index: int = -1

    def execute(self) -> None:
        self._old_index = self._layer.index_of(self._channel)
        if self._old_index < 0:
            return
        self._layer.remove_channel(self._channel)
        self._layer.insert_channel(self._new_index, self._channel)

    def undo(self) -> None:
        if self._old_index < 0:
            return
        self._layer.remove_channel(self._channel)
        self._layer.insert_channel(self._old_index, self._channel)

    @property
    def description(self) -> str:
        return "Move draw channel"


class DrawEditChannelCommand(Command):
    """Edit channel properties (color, texture, opacity, name, visible)."""

    def __init__(self, layer: DrawLayer, channel: DrawChannel, **changes: object):
        self._layer = layer
        self._channel = channel
        self._new_values = changes
        self._old_values = {k: getattr(channel, k) for k in changes}

    def execute(self) -> None:
        for k, v in self._new_values.items():
            setattr(self._channel, k, v)
        self._layer.mark_channel_dirty(self._channel.id)

    def undo(self) -> None:
        for k, v in self._old_values.items():
            setattr(self._channel, k, v)
        self._layer.mark_channel_dirty(self._channel.id)

    @property
    def description(self) -> str:
        return "Edit draw channel"


class EditDrawLayerEffectsCommand(Command):
    """Edit layer-level effects (outline, shadow)."""

    def __init__(self, layer: DrawLayer, **changes: object):
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
        return "Edit draw effects"
