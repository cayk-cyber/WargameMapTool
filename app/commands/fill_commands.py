"""Commands for the fill layer."""

from __future__ import annotations

from PySide6.QtGui import QColor

from app.commands.command import Command
from app.hex.hex_math import Hex
from app.layers.fill_layer import FillLayer, HexEdgeFill, HexTexture


class FillAllCommand(Command):
    """Fill every hex on the map with a single color or texture (undoable)."""

    def __init__(
        self,
        layer: FillLayer,
        all_hexes: list[Hex],
        color: QColor | None,
        texture: HexTexture | None,
    ):
        self._layer = layer
        self._all_hexes = all_hexes
        self._color = QColor(color) if color is not None else None
        self._texture = texture
        # Snapshots for undo (captured in execute)
        self._old_fills: dict = {}
        self._old_textures: dict = {}

    def execute(self) -> None:
        # Snapshot current state
        self._old_fills = {h: QColor(c) for h, c in self._layer.fills.items()}
        self._old_textures = dict(self._layer.textures)
        # Apply to all hexes
        if self._texture is not None:
            for h in self._all_hexes:
                self._layer.set_texture(h, self._texture)
        elif self._color is not None:
            for h in self._all_hexes:
                self._layer.set_fill(h, self._color)

    def undo(self) -> None:
        self._layer.fills.clear()
        self._layer.textures.clear()
        self._layer.fills.update(self._old_fills)
        self._layer.textures.update(self._old_textures)
        self._layer.mark_dirty()

    @property
    def description(self) -> str:
        return "Fill all hexes"


class SetHexFillCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex, color: QColor):
        self._layer = layer
        self._hex = hex_coord
        self._new_color = QColor(color)
        self._old_color: QColor | None = None

    def execute(self) -> None:
        self._old_color = self._layer.get_fill(self._hex)
        if self._old_color is not None:
            self._old_color = QColor(self._old_color)
        self._layer.set_fill(self._hex, self._new_color)

    def undo(self) -> None:
        if self._old_color is None:
            self._layer.clear_fill(self._hex)
        else:
            self._layer.set_fill(self._hex, self._old_color)

    @property
    def description(self) -> str:
        return f"Fill hex ({self._hex.q}, {self._hex.r})"


class ClearHexFillCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex):
        self._layer = layer
        self._hex = hex_coord
        self._old_color: QColor | None = None

    def execute(self) -> None:
        self._old_color = self._layer.clear_fill(self._hex)
        if self._old_color is not None:
            self._old_color = QColor(self._old_color)

    def undo(self) -> None:
        if self._old_color is not None:
            self._layer.set_fill(self._hex, self._old_color)

    @property
    def description(self) -> str:
        return f"Clear hex ({self._hex.q}, {self._hex.r})"


class SetDotColorCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex, color: QColor):
        self._layer = layer
        self._hex = hex_coord
        self._new_color = QColor(color)
        self._old_color: QColor | None = None

    def execute(self) -> None:
        self._old_color = self._layer.get_dot_color(self._hex)
        if self._old_color is not None:
            self._old_color = QColor(self._old_color)
        self._layer.set_dot_color(self._hex, self._new_color)

    def undo(self) -> None:
        if self._old_color is None:
            self._layer.clear_dot_color(self._hex)
        else:
            self._layer.set_dot_color(self._hex, self._old_color)

    @property
    def description(self) -> str:
        return f"Set dot color ({self._hex.q}, {self._hex.r})"


class ClearDotColorCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex):
        self._layer = layer
        self._hex = hex_coord
        self._old_color: QColor | None = None

    def execute(self) -> None:
        self._old_color = self._layer.clear_dot_color(self._hex)
        if self._old_color is not None:
            self._old_color = QColor(self._old_color)

    def undo(self) -> None:
        if self._old_color is not None:
            self._layer.set_dot_color(self._hex, self._old_color)

    @property
    def description(self) -> str:
        return f"Clear dot color ({self._hex.q}, {self._hex.r})"


class SetCoordColorCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex, color: QColor):
        self._layer = layer
        self._hex = hex_coord
        self._new_color = QColor(color)
        self._old_color: QColor | None = None

    def execute(self) -> None:
        self._old_color = self._layer.get_coord_color(self._hex)
        if self._old_color is not None:
            self._old_color = QColor(self._old_color)
        self._layer.set_coord_color(self._hex, self._new_color)

    def undo(self) -> None:
        if self._old_color is None:
            self._layer.clear_coord_color(self._hex)
        else:
            self._layer.set_coord_color(self._hex, self._old_color)

    @property
    def description(self) -> str:
        return f"Set coord color ({self._hex.q}, {self._hex.r})"


class ClearCoordColorCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex):
        self._layer = layer
        self._hex = hex_coord
        self._old_color: QColor | None = None

    def execute(self) -> None:
        self._old_color = self._layer.clear_coord_color(self._hex)
        if self._old_color is not None:
            self._old_color = QColor(self._old_color)

    def undo(self) -> None:
        if self._old_color is not None:
            self._layer.set_coord_color(self._hex, self._old_color)

    @property
    def description(self) -> str:
        return f"Clear coord color ({self._hex.q}, {self._hex.r})"


class SetHexTextureCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex, texture: HexTexture):
        self._layer = layer
        self._hex = hex_coord
        self._new_texture = texture
        self._old_texture: HexTexture | None = None
        self._old_color: QColor | None = None

    def execute(self) -> None:
        # Save both old states (texture and color fill)
        self._old_texture = self._layer.get_texture(self._hex)
        self._old_color = self._layer.get_fill(self._hex)
        if self._old_color is not None:
            self._old_color = QColor(self._old_color)
        # set_texture clears color fill automatically
        self._layer.set_texture(self._hex, self._new_texture)

    def undo(self) -> None:
        self._layer.clear_texture(self._hex)
        if self._old_texture is not None:
            self._layer.set_texture(self._hex, self._old_texture)
        elif self._old_color is not None:
            self._layer.set_fill(self._hex, self._old_color)

    @property
    def description(self) -> str:
        return f"Set texture ({self._hex.q}, {self._hex.r})"


class ClearHexTextureCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex):
        self._layer = layer
        self._hex = hex_coord
        self._old_texture: HexTexture | None = None

    def execute(self) -> None:
        self._old_texture = self._layer.clear_texture(self._hex)

    def undo(self) -> None:
        if self._old_texture is not None:
            self._layer.set_texture(self._hex, self._old_texture)

    @property
    def description(self) -> str:
        return f"Clear texture ({self._hex.q}, {self._hex.r})"


class SetHexEdgeCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex, edge_fill: HexEdgeFill):
        self._layer = layer
        self._hex = hex_coord
        self._new_edge = edge_fill
        self._old_edge: HexEdgeFill | None = None

    def execute(self) -> None:
        self._old_edge = self._layer.get_edge_fill(self._hex)
        self._layer.set_edge_fill(self._hex, self._new_edge)

    def undo(self) -> None:
        if self._old_edge is None:
            self._layer.clear_edge_fill(self._hex)
        else:
            self._layer.set_edge_fill(self._hex, self._old_edge)

    @property
    def description(self) -> str:
        return f"Set edge fill ({self._hex.q}, {self._hex.r})"


class ClearHexEdgeCommand(Command):
    def __init__(self, layer: FillLayer, hex_coord: Hex):
        self._layer = layer
        self._hex = hex_coord
        self._old_edge: HexEdgeFill | None = None

    def execute(self) -> None:
        self._old_edge = self._layer.clear_edge_fill(self._hex)

    def undo(self) -> None:
        if self._old_edge is not None:
            self._layer.set_edge_fill(self._hex, self._old_edge)

    @property
    def description(self) -> str:
        return f"Clear edge fill ({self._hex.q}, {self._hex.r})"
