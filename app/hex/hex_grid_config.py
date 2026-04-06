"""Hex grid configuration dataclass."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPolygonF

from app.hex.hex_math import (
    FLAT_TOP,
    POINTY_TOP,
    Hex,
    Layout,
    axial_to_offset,
    hex_corners,
    hex_to_pixel,
    offset_to_axial,
)

# 96 DPI: 1mm = 3.7795 pixels
MM_TO_PX = 96.0 / 25.4


@dataclass
class HexGridConfig:
    hex_size: float = 72.0          # Internal: radius (center to corner) in pixels
    width: int = 20                  # Columns
    height: int = 20                 # Rows
    orientation: str = "flat"         # "pointy" or "flat"
    line_width: float = 1.0
    edge_color: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    show_center_dots: bool = False
    show_coordinates: bool = False
    first_row_offset: str = "even"   # "even" or "odd"

    # Extended settings
    hex_size_mm: float = 19.0        # Flat-to-flat distance in mm (user-facing)
    center_dot_size: float = 3.0     # Dot radius in cosmetic pixels
    center_dot_color: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    coord_position: str = "top"      # "top" or "bottom"
    coord_format: str = "numeric_dot"  # "numeric", "numeric_dot", "letter", "plain"
    show_border: bool = False
    border_color: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    coord_offset_y: float = 0.0      # Y-offset for coord labels (fraction of hex_size, + = down)
    coord_font_scale: int = 18       # Font size as percentage of hex_size (5-50)
    coord_start_one: bool = False    # Start coordinates at 1 instead of 0
    border_margin: float = 2.0       # Distance from hexes to border in mm
    border_fill: bool = False         # Fill area between border and hexes
    border_fill_color: QColor = field(default_factory=lambda: QColor(255, 255, 255))
    half_hexes: bool = False          # Clip edge hexes for tileable maps
    grid_style: str = "lines"        # "lines" (full hex outlines) or "crossings" (vertex marks only)
    center_dot_outline: bool = False
    center_dot_outline_width: float = 1.0
    center_dot_outline_color: QColor = field(default_factory=lambda: QColor(255, 255, 255))

    # Megahex overlay
    megahex_enabled: bool = False
    megahex_radius: int = 1             # 1-10 hex rings per megahex
    megahex_mode: str = "hex_edges"     # "hex_edges" or "geometric"
    megahex_color: QColor = field(default_factory=lambda: QColor(100, 100, 100))
    megahex_width: float = 3.0          # Line width in cosmetic pixels
    megahex_offset_q: int = 0           # Pattern shift in axial q
    megahex_offset_r: int = 0           # Pattern shift in axial r

    # Canvas
    canvas_bg_color: QColor = field(default_factory=lambda: QColor("#2b2b2b"))
    show_grid: bool = True

    # Global lighting tint (overlay over hex area, under grid)
    global_lighting_enabled: bool = False
    global_lighting_color: QColor = field(default_factory=lambda: QColor("#ffdc64"))
    global_lighting_opacity: int = 0  # 0–255

    # Default fill color stored in grid presets (empty = no default; ignored at runtime)
    default_fill_color: str = ""

    # Bounds cache (self-validating via dimension key)
    _bounds_cache_key: tuple | None = field(default=None, repr=False, compare=False)
    _cached_map_bounds: QRectF | None = field(default=None, repr=False, compare=False)
    _cached_half_hex_bounds: QRectF | None = field(default=None, repr=False, compare=False)

    # Grid clip path cache (includes half_hexes in key)
    _clip_path_cache_key: tuple | None = field(default=None, repr=False, compare=False)
    _cached_grid_clip_path: object = field(default=None, repr=False, compare=False)

    def _bounds_key(self) -> tuple:
        """Cache key for bounds — changes when grid dimensions change."""
        return (self.hex_size, self.width, self.height, self.orientation, self.first_row_offset)

    @staticmethod
    def mm_to_pixel_size(mm: float) -> float:
        """Convert flat-to-flat mm to internal hex radius (pixels).

        Flat-to-flat = sqrt(3) * radius, so radius = flat_to_flat / sqrt(3).
        """
        flat_to_flat_px = mm * MM_TO_PX
        return flat_to_flat_px / math.sqrt(3.0)

    def apply_mm_size(self) -> None:
        """Update hex_size from hex_size_mm."""
        self.hex_size = self.mm_to_pixel_size(self.hex_size_mm)

    def get_orientation(self):
        return POINTY_TOP if self.orientation == "pointy" else FLAT_TOP

    def create_layout(self) -> Layout:
        return Layout(
            orientation=self.get_orientation(),
            size_x=self.hex_size,
            size_y=self.hex_size,
            origin_x=self.hex_size * 2,
            origin_y=self.hex_size * 2,
        )

    def is_valid_hex(self, h: Hex) -> bool:
        """Check if a hex coordinate is within the grid bounds."""
        col, row = axial_to_offset(h, self.first_row_offset, self.orientation)
        return 0 <= col < self.width and 0 <= row < self.height

    def is_within_placement_area(
        self, world_pos: QPointF, hex_coord: Hex, allow_border_zone: bool = False,
    ) -> bool:
        """Check if a world position is valid for placement.

        allow_border_zone=False: only valid hexes (Hexside, Border, Path tools).
        allow_border_zone=True: valid hex OR inside the border zone when
                                show_border=True (Asset, Text, Sketch, Freeform).
        """
        if not allow_border_zone or not self.show_border:
            return self.is_valid_hex(hex_coord)
        return self.get_effective_bounds().contains(world_pos)

    def get_all_hexes(self) -> list[Hex]:
        """Return all hex coordinates in the grid."""
        hexes = []
        for row in range(self.height):
            for col in range(self.width):
                hexes.append(offset_to_axial(col, row, self.first_row_offset, self.orientation))
        return hexes

    def get_map_pixel_bounds(self) -> QRectF:
        """Calculate the bounding rectangle of the entire map in pixels (cached)."""
        key = self._bounds_key()
        if self._bounds_cache_key == key and self._cached_map_bounds is not None:
            return self._cached_map_bounds

        layout = self.create_layout()
        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')

        for h in self.get_all_hexes():
            px, py = hex_to_pixel(layout, h)
            min_x = min(min_x, px - self.hex_size)
            min_y = min(min_y, py - self.hex_size)
            max_x = max(max_x, px + self.hex_size)
            max_y = max(max_y, py + self.hex_size)

        if min_x == float('inf'):
            result = QRectF(0, 0, 0, 0)
        else:
            result = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

        self._bounds_cache_key = key
        self._cached_map_bounds = result
        self._cached_half_hex_bounds = None  # Invalidate half-hex cache too
        return result

    def get_half_hex_bounds(self) -> QRectF:
        """Clip bounds for half-hex mode (cached)."""
        key = self._bounds_key()
        if self._bounds_cache_key == key and self._cached_half_hex_bounds is not None:
            return self._cached_half_hex_bounds

        layout = self.create_layout()
        all_hexes = self.get_all_hexes()
        if not all_hexes:
            result = QRectF(0, 0, 0, 0)
        else:
            centers = [hex_to_pixel(layout, h) for h in all_hexes]
            min_cx = min(c[0] for c in centers)
            max_cx = max(c[0] for c in centers)
            min_cy = min(c[1] for c in centers)
            max_cy = max(c[1] for c in centers)
            result = QRectF(min_cx, min_cy, max_cx - min_cx, max_cy - min_cy)

        self._bounds_cache_key = key
        self._cached_half_hex_bounds = result
        return result

    def get_effective_bounds(self) -> QRectF:
        """Return map bounds considering half_hexes or border margin."""
        if self.half_hexes:
            return self.get_half_hex_bounds()
        bounds = self.get_map_pixel_bounds()
        if self.show_border:
            m = self.border_margin * MM_TO_PX
            bounds = bounds.adjusted(-m, -m, m, m)
        return bounds

    def _clip_path_key(self) -> tuple:
        """Cache key for grid clip path — includes half_hexes flag."""
        return (*self._bounds_key(), self.half_hexes)

    def get_grid_clip_path(self) -> QPainterPath:
        """Return a QPainterPath clipping to the hex grid boundary (cached).

        half_hexes=True  -> rectangular path (center-to-center of edge hexes)
        half_hexes=False -> union of all hex polygons with WindingFill
        """
        key = self._clip_path_key()
        if self._clip_path_cache_key == key and self._cached_grid_clip_path is not None:
            return self._cached_grid_clip_path  # type: ignore[return-value]

        path = QPainterPath()
        if self.half_hexes:
            path.addRect(self.get_half_hex_bounds())
        else:
            layout = self.create_layout()
            path.setFillRule(Qt.FillRule.WindingFill)
            for h in self.get_all_hexes():
                corners = hex_corners(layout, h)
                polygon = QPolygonF([QPointF(x, y) for x, y in corners])
                path.addPolygon(polygon)

        self._clip_path_cache_key = key
        self._cached_grid_clip_path = path
        return path

    def format_coordinate(self, col: int, row: int) -> str:
        """Format a coordinate label based on coord_format setting."""
        offset = 1 if self.coord_start_one else 0
        if self.coord_format == "numeric":
            return f"{col + offset:02d}{row + offset:02d}"
        elif self.coord_format == "numeric_dot":
            return f"{col + offset:02d}.{row + offset:02d}"
        elif self.coord_format == "letter":
            # Letter column stays 0-based (A=0), only row gets offset
            if col < 26:
                letter = chr(65 + col)
            else:
                letter = chr(64 + col // 26) + chr(65 + col % 26)
            return f"{letter}{row + offset}"
        else:  # "plain"
            return f"{col + offset},{row + offset}"

    def serialize(self) -> dict:
        return {
            "hex_size": self.hex_size,
            "hex_size_mm": self.hex_size_mm,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "line_width": self.line_width,
            "edge_color": self.edge_color.name(),
            "show_center_dots": self.show_center_dots,
            "show_coordinates": self.show_coordinates,
            "first_row_offset": self.first_row_offset,
            "center_dot_size": self.center_dot_size,
            "center_dot_color": self.center_dot_color.name(),
            "coord_position": self.coord_position,
            "coord_format": self.coord_format,
            "show_border": self.show_border,
            "border_color": self.border_color.name(),
            "coord_offset_y": self.coord_offset_y,
            "coord_font_scale": self.coord_font_scale,
            "coord_start_one": self.coord_start_one,
            "border_margin": self.border_margin,
            "border_fill": self.border_fill,
            "border_fill_color": self.border_fill_color.name(),
            "half_hexes": self.half_hexes,
            "grid_style": self.grid_style,
            "center_dot_outline": self.center_dot_outline,
            "center_dot_outline_width": self.center_dot_outline_width,
            "center_dot_outline_color": self.center_dot_outline_color.name(),
            "megahex_enabled": self.megahex_enabled,
            "megahex_radius": self.megahex_radius,
            "megahex_mode": self.megahex_mode,
            "megahex_color": self.megahex_color.name(),
            "megahex_width": self.megahex_width,
            "megahex_offset_q": self.megahex_offset_q,
            "megahex_offset_r": self.megahex_offset_r,
            "canvas_bg_color": self.canvas_bg_color.name(),
            "show_grid": self.show_grid,
            "global_lighting_enabled": self.global_lighting_enabled,
            "global_lighting_color": self.global_lighting_color.name(),
            "global_lighting_opacity": self.global_lighting_opacity,
            **({"default_fill_color": self.default_fill_color} if self.default_fill_color else {}),
        }

    @classmethod
    def deserialize(cls, data: dict) -> HexGridConfig:
        return cls(
            hex_size=data.get("hex_size", 72.0),
            hex_size_mm=data.get("hex_size_mm", 19.0),
            width=data.get("width", 20),
            height=data.get("height", 20),
            orientation=data.get("orientation", "flat"),
            line_width=data.get("line_width", 1.0),
            edge_color=QColor(data.get("edge_color", "#000000")),
            show_center_dots=data.get("show_center_dots", False),
            show_coordinates=data.get("show_coordinates", False),
            first_row_offset=data.get("first_row_offset", "even"),
            center_dot_size=data.get("center_dot_size", 3.0),
            center_dot_color=QColor(data.get("center_dot_color", "#000000")),
            coord_position=data.get("coord_position", "top"),
            coord_format=data.get("coord_format", "numeric_dot"),
            show_border=data.get("show_border", False),
            border_color=QColor(data.get("border_color", "#000000")),
            coord_offset_y=data.get("coord_offset_y", 0.0),
            coord_font_scale=data.get("coord_font_scale", 18),
            coord_start_one=data.get("coord_start_one", False),
            border_margin=data.get("border_margin", 2.0),
            border_fill=data.get("border_fill", False),
            border_fill_color=QColor(data.get("border_fill_color", "#ffffff")),
            half_hexes=data.get("half_hexes", False),
            grid_style=data.get("grid_style", "lines"),
            center_dot_outline=data.get("center_dot_outline", False),
            center_dot_outline_width=data.get("center_dot_outline_width", 1.0),
            center_dot_outline_color=QColor(data.get("center_dot_outline_color", "#ffffff")),
            megahex_enabled=data.get("megahex_enabled", False),
            megahex_radius=data.get("megahex_radius", 1),
            megahex_mode=data.get("megahex_mode", "hex_edges"),
            megahex_color=QColor(data.get("megahex_color", "#646464")),
            megahex_width=data.get("megahex_width", 3.0),
            megahex_offset_q=data.get("megahex_offset_q", 0),
            megahex_offset_r=data.get("megahex_offset_r", 0),
            canvas_bg_color=QColor(data.get("canvas_bg_color", "#2b2b2b")),
            show_grid=data.get("show_grid", True),
            global_lighting_enabled=data.get("global_lighting_enabled", False),
            global_lighting_color=QColor(data.get("global_lighting_color", "#ffdc64")),
            global_lighting_opacity=data.get("global_lighting_opacity", 0),
            default_fill_color=data.get("default_fill_color", ""),
        )
