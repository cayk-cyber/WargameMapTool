"""Central project model holding all document state."""

from __future__ import annotations

from app.hex.hex_grid_config import HexGridConfig
from app.hex.hex_grid_renderer import HexGridRenderer
from app.layers.layer_stack import LayerStack


class Project:
    def __init__(self):
        self.grid_config = HexGridConfig()
        self.layer_stack = LayerStack()
        self.grid_renderer = HexGridRenderer()
        self.file_path: str | None = None
        self.dirty: bool = False
