"""Freeform path object data class - a freehand-drawn path in world space."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class FreeformPathObject:
    """Represents a freeform path drawn by mouse input."""

    # Path geometry: list of world-space points
    points: list[tuple[float, float]] = field(default_factory=list)

    # Smoothness used when creating (stored for reference)
    smoothness: float = 0.5

    # Foreground path
    color: str = "#000000"
    width: float = 3.0
    line_type: str = "solid"  # "solid", "dashed", "dotted"
    dash_length: float = 6.0
    gap_length: float = 4.0
    dash_cap: str = "flat"  # "flat", "round", "square"

    # Foreground texture (overrides color when non-empty)
    texture_id: str = ""  # Empty = solid color, non-empty = use texture
    texture_zoom: float = 1.0
    texture_rotation: float = 0.0

    # Background path (drawn underneath as wider second layer)
    bg_enabled: bool = False
    bg_color: str = "#000000"
    bg_width: float = 6.0
    bg_line_type: str = "solid"
    bg_dash_length: float = 6.0
    bg_gap_length: float = 4.0
    bg_dash_cap: str = "flat"  # "flat", "round", "square"

    # Background texture (overrides bg_color when non-empty)
    bg_texture_id: str = ""
    bg_texture_zoom: float = 1.0
    bg_texture_rotation: float = 0.0

    # Opacity (0.0 = transparent, 1.0 = opaque)
    opacity: float = 1.0      # foreground / main path
    bg_opacity: float = 1.0   # background path

    # Straight-line mode: True = lineTo segments, False = Catmull-Rom splines
    straight: bool = False

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def __post_init__(self) -> None:
        # Version counter incremented on every points mutation so the layer
        # cache can use (id, _points_version) instead of tuple(points) to
        # avoid allocating a large tuple every frame.
        self._points_version: int = 0

    def increment_points_version(self) -> None:
        """Increment the points version counter to invalidate the path cache."""
        self._points_version += 1

    def serialize(self) -> dict:
        data = {
            "id": self.id,
            "points": [[round(x, 2), round(y, 2)] for x, y in self.points],
            "color": self.color,
            "width": self.width,
        }
        if self.smoothness != 0.5:
            data["smoothness"] = self.smoothness
        if self.line_type != "solid":
            data["line_type"] = self.line_type
            if self.line_type == "dashed":
                data["dash_length"] = self.dash_length
            data["gap_length"] = self.gap_length
            if self.dash_cap != "flat":
                data["dash_cap"] = self.dash_cap
        if self.texture_id:
            data["texture_id"] = self.texture_id
            if self.texture_zoom != 1.0:
                data["texture_zoom"] = self.texture_zoom
            if self.texture_rotation != 0.0:
                data["texture_rotation"] = self.texture_rotation
        if self.bg_enabled:
            data["bg_enabled"] = True
            data["bg_color"] = self.bg_color
            data["bg_width"] = self.bg_width
            if self.bg_line_type != "solid":
                data["bg_line_type"] = self.bg_line_type
                if self.bg_line_type == "dashed":
                    data["bg_dash_length"] = self.bg_dash_length
                data["bg_gap_length"] = self.bg_gap_length
                if self.bg_dash_cap != "flat":
                    data["bg_dash_cap"] = self.bg_dash_cap
            if self.bg_texture_id:
                data["bg_texture_id"] = self.bg_texture_id
                if self.bg_texture_zoom != 1.0:
                    data["bg_texture_zoom"] = self.bg_texture_zoom
                if self.bg_texture_rotation != 0.0:
                    data["bg_texture_rotation"] = self.bg_texture_rotation
        if self.opacity != 1.0:
            data["opacity"] = self.opacity
        if self.bg_opacity != 1.0:
            data["bg_opacity"] = self.bg_opacity
        if self.straight:
            data["straight"] = True
        return data

    @classmethod
    def deserialize(cls, data: dict) -> FreeformPathObject:
        raw_points = data.get("points", [])
        points = [(p[0], p[1]) for p in raw_points if len(p) >= 2]  # M17: guard against corrupt point data

        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            points=points,
            smoothness=data.get("smoothness", 0.5),
            color=data.get("color", "#000000"),
            width=data.get("width", 3.0),
            line_type=data.get("line_type", "solid"),
            dash_length=data.get("dash_length", 6.0),
            gap_length=data.get("gap_length", 4.0),
            dash_cap=data.get("dash_cap", "flat"),
            texture_id=data.get("texture_id", ""),
            texture_zoom=data.get("texture_zoom", 1.0),
            texture_rotation=data.get("texture_rotation", 0.0),
            bg_enabled=data.get("bg_enabled", False),
            bg_color=data.get("bg_color", "#000000"),
            bg_width=data.get("bg_width", 6.0),
            bg_line_type=data.get("bg_line_type", "solid"),
            bg_dash_length=data.get("bg_dash_length", 6.0),
            bg_gap_length=data.get("bg_gap_length", 4.0),
            bg_dash_cap=data.get("bg_dash_cap", "flat"),
            bg_texture_id=data.get("bg_texture_id", ""),
            bg_texture_zoom=data.get("bg_texture_zoom", 1.0),
            bg_texture_rotation=data.get("bg_texture_rotation", 0.0),
            opacity=data.get("opacity", 1.0),
            bg_opacity=data.get("bg_opacity", 1.0),
            straight=data.get("straight", False),
        )
