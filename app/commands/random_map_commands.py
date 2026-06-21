"""Command for applying a random map generation result (single undo step)."""

from __future__ import annotations

import copy

from PySide6.QtGui import QColor

from app.commands.command import Command
from app.hex.hex_math import Hex, hex_edge_key
from app.io.hexside_preset_manager import HexsidePreset
from app.layers.fill_layer import FillLayer, HexTexture
from app.layers.hexside_layer import HexsideLayer
from app.layers.layer_stack import LayerStack
from app.models.hexside_object import HexsideObject


class RandomMapCommand(Command):
    """Applies random map fills and creates layers for textures/edges/rivers.

    On execute: replaces all fills on the fill layer, creates separate
    FillLayers for each textured terrain role, and creates HexsideLayers
    for fill edges and rivers.
    On undo: restores original fills and removes all created layers.
    """

    def __init__(
        self,
        fill_layer: FillLayer,
        layer_stack: LayerStack,
        new_fills: dict[Hex, QColor],
        river_edges: list[tuple[Hex, Hex]],
        river_preset: HexsidePreset | None,
        edge_borders: list[tuple[Hex, Hex, QColor, str | None]] | None = None,
        texture_layers: list[tuple[str, dict[Hex, HexTexture]]] | None = None,
        texture_zoom: float = 1.0,
    ):
        self._fill_layer = fill_layer
        self._layer_stack = layer_stack
        self._new_fills = {h: QColor(c) for h, c in new_fills.items()}
        self._river_edges = list(river_edges)
        self._river_preset = river_preset
        self._edge_borders = list(edge_borders) if edge_borders else []
        self._texture_layers = list(texture_layers) if texture_layers else []
        self._texture_zoom = texture_zoom

        # Snapshots (populated on first execute)
        self._old_fills: dict[Hex, QColor] = {}
        self._old_textures: dict = {}
        self._created_layers: list = []  # FillLayer or HexsideLayer
        self._removed_fill_layer = False
        self._fill_layer_index: int = -1

    def execute(self) -> None:
        # Snapshot current fill state
        self._old_fills = {h: QColor(c) for h, c in self._fill_layer.fills.items()}
        self._old_textures = dict(self._fill_layer.textures)

        # Apply color fills to the base fill layer
        self._fill_layer.fills.clear()
        self._fill_layer.textures.clear()
        for h, color in self._new_fills.items():
            self._fill_layer.fills[h] = color
        self._fill_layer.mark_dirty()

        # Remove the base fill layer if it ended up empty
        self._removed_fill_layer = False
        if not self._new_fills:
            for i, l in enumerate(self._layer_stack):
                if l is self._fill_layer:
                    self._fill_layer_index = i
                    self._layer_stack.remove_layer(i)
                    self._removed_fill_layer = True
                    break

        self._created_layers.clear()

        # Create separate FillLayers for each textured terrain role
        for layer_name, tex_fills in self._texture_layers:
            tex_layer = FillLayer(layer_name)
            for h, tex in tex_fills.items():
                tex_layer.textures[h] = tex
            tex_layer.mark_dirty()
            self._layer_stack.add_layer(tex_layer)
            self._created_layers.append(tex_layer)

        # Create fill-edges layer (above texture layers)
        if self._edge_borders:
            edge_layer = HexsideLayer("Edges")
            for hex_a, hex_b, color, tex_id in self._edge_borders:
                obj = self._make_edge_hexside(hex_a, hex_b, color, tex_id)
                edge_layer.hexsides[obj.edge_key()] = obj
            edge_layer.mark_dirty()
            self._layer_stack.add_layer(edge_layer)
            self._created_layers.append(edge_layer)

        # Create river layer (added last = on top)
        if self._river_edges:
            river_layer = HexsideLayer("Rivers")
            for hex_a, hex_b in self._river_edges:
                obj = self._make_river_hexside(hex_a, hex_b)
                river_layer.hexsides[obj.edge_key()] = obj
            river_layer.mark_dirty()
            self._layer_stack.add_layer(river_layer)
            self._created_layers.append(river_layer)

    def undo(self) -> None:
        # Remove created layers (reverse order to keep indices valid)
        for layer in reversed(self._created_layers):
            for i, l in enumerate(self._layer_stack):
                if l is layer:
                    self._layer_stack.remove_layer(i)
                    break
        self._created_layers.clear()

        # Re-add the base fill layer if it was removed
        if self._removed_fill_layer:
            self._layer_stack.add_layer(self._fill_layer, self._fill_layer_index)
            self._removed_fill_layer = False

        # Restore original fills
        self._fill_layer.fills.clear()
        self._fill_layer.textures.clear()
        for h, c in self._old_fills.items():
            self._fill_layer.fills[h] = c
        for h, t in self._old_textures.items():
            self._fill_layer.textures[h] = t
        self._fill_layer.mark_dirty()

    def _make_edge_hexside(
        self, hex_a: Hex, hex_b: Hex, color: QColor,
        texture_id: str | None = None,
    ) -> HexsideObject:
        """Create a fill-edge HexsideObject in the lower terrain's color/texture."""
        key = hex_edge_key(hex_a, hex_b)
        a_q, a_r = key[0]
        b_q, b_r = key[1]
        return HexsideObject(
            hex_a_q=a_q, hex_a_r=a_r,
            hex_b_q=b_q, hex_b_r=b_r,
            color=color.name(),
            width=16.0,
            random=True,
            random_amplitude=0.7,
            random_distance=0.2,
            random_offset=4.0,
            random_endpoint=6.4,
            texture_id=texture_id,
            texture_zoom=self._texture_zoom if texture_id else 1.0,
        )

    def _make_river_hexside(self, hex_a: Hex, hex_b: Hex) -> HexsideObject:
        """Create a HexsideObject from a river edge using the preset."""
        key = hex_edge_key(hex_a, hex_b)
        a_q, a_r = key[0]
        b_q, b_r = key[1]

        p = self._river_preset
        if p is not None:
            return HexsideObject(
                hex_a_q=a_q, hex_a_r=a_r,
                hex_b_q=b_q, hex_b_r=b_r,
                color=p.color,
                width=p.width,
                outline=p.outline,
                outline_color=p.outline_color,
                outline_width=p.outline_width,
                outline_texture_id=p.outline_texture_id,
                outline_texture_zoom=p.outline_texture_zoom,
                outline_texture_rotation=p.outline_texture_rotation,
                shift=p.shift,
                random=p.random,
                random_amplitude=p.random_amplitude,
                random_distance=p.random_distance,
                random_endpoint=p.random_endpoint,
                random_jitter=p.random_jitter,
                random_offset=p.random_offset,
                taper=p.taper,
                taper_length=p.taper_length,
                texture_id=p.texture_id,
                texture_zoom=p.texture_zoom,
                texture_rotation=p.texture_rotation,
                opacity=p.opacity,
                outline_opacity=p.outline_opacity,
                falloff_width=p.falloff_width,
                falloff_amount=p.falloff_amount,
                falloff_random=p.falloff_random,
            )
        else:
            # Default blue river style
            return HexsideObject(
                hex_a_q=a_q, hex_a_r=a_r,
                hex_b_q=b_q, hex_b_r=b_r,
                color="#4488ff",
                width=2.5,
                outline=True,
                outline_color="#003388",
                outline_width=0.8,
                random=True,
                random_amplitude=1.5,
                random_distance=0.4,
                random_offset=0.3,
            )

    @property
    def description(self) -> str:
        return "Create random map"
