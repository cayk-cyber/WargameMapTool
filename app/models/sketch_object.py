"""Sketch object data class - geometric shapes for administrative overlays."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPainterPathStroker, QPolygonF, QTransform


@dataclass
class SketchObject:
    """Represents a sketch shape in world space.

    Geometry interpretation depends on shape_type:
      - "line": points = [start, end]
      - "rect": points = [corner1, corner2] (axis-aligned before rotation)
      - "polygon": points = [center], uses radius + num_sides
      - "ellipse": points = [center], uses rx + ry
      - "freehand": points = [all collected points]
    """

    shape_type: str = "rect"

    # Geometry
    points: list[tuple[float, float]] = field(default_factory=list)

    # Shape-specific
    radius: float = 30.0
    num_sides: int = 6
    rx: float = 40.0
    ry: float = 30.0
    closed: bool = False

    # Visual
    stroke_color: str = "#000000"
    stroke_width: float = 2.0
    stroke_type: str = "solid"   # "solid" | "dashed" | "dotted"
    dash_length: float = 8.0
    gap_length: float = 4.0
    stroke_cap: str = "round"    # "round" | "flat" | "square"
    fill_enabled: bool = False
    fill_color: str = "#ffff00"
    fill_opacity: float = 0.3
    fill_type: str = "color"       # "color" | "texture"
    fill_texture_id: str = ""
    fill_texture_zoom: float = 1.0
    fill_texture_rotation: float = 0.0
    rotation: float = 0.0

    # Drop shadow
    shadow_enabled: bool = False
    shadow_type: str = "outer"  # "outer" or "inner"
    shadow_color: str = "#000000"
    shadow_opacity: float = 0.5
    shadow_angle: float = 120.0
    shadow_distance: float = 5.0
    shadow_spread: float = 0.0
    shadow_size: float = 5.0

    # Render order
    draw_over_grid: bool = False

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    # Cached QPainterPath — invalidated when geometry fields change.
    _path_cache: QPainterPath | None = field(default=None, repr=False, compare=False)
    _path_cache_key: tuple | None = field(default=None, repr=False, compare=False)

    def _geometry_key(self) -> tuple:
        """Key encoding all fields that affect build_path() output."""
        return (
            self.shape_type,
            tuple(self.points),
            self.radius,
            self.num_sides,
            self.rx,
            self.ry,
            self.closed,
        )

    def center(self) -> tuple[float, float]:
        """Geometric center of the shape."""
        if self.shape_type in ("polygon", "ellipse"):
            if self.points:
                return self.points[0]
            return (0.0, 0.0)
        if not self.points:
            return (0.0, 0.0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def bounding_rect(self) -> QRectF:
        """World-space bounding rectangle accounting for rotation and stroke."""
        path = self.build_path()
        cx, cy = self.center()

        if self.rotation != 0.0:
            xf = QTransform()
            xf.translate(cx, cy)
            xf.rotate(self.rotation)
            xf.translate(-cx, -cy)
            path = xf.map(path)

        rect = path.boundingRect()
        margin = self.stroke_width / 2.0 + 2.0
        return rect.adjusted(-margin, -margin, margin, margin)

    def build_path(self) -> QPainterPath:
        """Construct QPainterPath in world space (un-rotated, centered at shape center).

        Results are cached and only recomputed when geometry fields change.
        """
        key = self._geometry_key()
        if self._path_cache is not None and self._path_cache_key == key:
            return self._path_cache

        path = QPainterPath()
        st = self.shape_type

        if st == "line":
            if len(self.points) < 2:
                return path
            path.moveTo(QPointF(*self.points[0]))
            path.lineTo(QPointF(*self.points[1]))

        elif st == "rect":
            if len(self.points) < 2:
                return path
            x1, y1 = self.points[0]
            x2, y2 = self.points[1]
            path.addRect(QRectF(
                QPointF(min(x1, x2), min(y1, y2)),
                QPointF(max(x1, x2), max(y1, y2)),
            ))

        elif st == "polygon":
            if not self.points:
                return path
            cx, cy = self.points[0]
            n = max(self.num_sides, 3)
            polygon = QPolygonF()
            for i in range(n):
                angle = 2.0 * math.pi * i / n - math.pi / 2.0
                px = cx + self.radius * math.cos(angle)
                py = cy + self.radius * math.sin(angle)
                polygon.append(QPointF(px, py))
            polygon.append(polygon[0])  # close
            path.addPolygon(polygon)

        elif st == "ellipse":
            if not self.points:
                return path
            cx, cy = self.points[0]
            path.addEllipse(QPointF(cx, cy), self.rx, self.ry)

        elif st == "freehand":
            if len(self.points) < 2:
                return path
            path = _catmull_rom_path(self.points)
            if self.closed and len(self.points) >= 3:
                path.closeSubpath()

        self._path_cache = path
        self._path_cache_key = key
        return path

    def contains_point(self, world_x: float, world_y: float,
                       threshold: float = 8.0) -> bool:
        """Hit test: does the shape contain or is near the given world point."""
        cx, cy = self.center()
        px, py = world_x, world_y

        # Inverse-rotate the test point around shape center
        if self.rotation != 0.0:
            rad = -math.radians(self.rotation)
            dx, dy = px - cx, py - cy
            px = cx + dx * math.cos(rad) - dy * math.sin(rad)
            py = cy + dx * math.sin(rad) + dy * math.cos(rad)

        path = self.build_path()
        if path.isEmpty():
            return False

        point = QPointF(px, py)

        # For filled shapes, check if point is inside
        has_fill = (self.fill_enabled and
                    self.shape_type not in ("line",))
        if has_fill and path.contains(point):
            return True

        # For stroke, use QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.stroke_width, threshold * 2))
        stroked = stroker.createStroke(path)
        return stroked.contains(point)

    # --- Serialization ---

    def serialize(self) -> dict:
        data: dict = {
            "id": self.id,
            "shape_type": self.shape_type,
            "points": [[round(x, 2), round(y, 2)] for x, y in self.points],
        }
        # Shape-specific (only when relevant)
        if self.shape_type == "polygon":
            data["radius"] = round(self.radius, 2)
            data["num_sides"] = self.num_sides
        if self.shape_type == "ellipse":
            data["rx"] = round(self.rx, 2)
            data["ry"] = round(self.ry, 2)
        if self.shape_type == "freehand" and self.closed:
            data["closed"] = True

        # Visual
        data["stroke_color"] = self.stroke_color
        data["stroke_width"] = round(self.stroke_width, 2)
        if self.stroke_type != "solid":
            data["stroke_type"] = self.stroke_type
            data["dash_length"] = round(self.dash_length, 1)
            data["gap_length"] = round(self.gap_length, 1)
        if self.stroke_cap != "round":
            data["stroke_cap"] = self.stroke_cap
        if self.fill_enabled:
            data["fill_enabled"] = True
            data["fill_color"] = self.fill_color
            data["fill_opacity"] = round(self.fill_opacity, 2)
            if self.fill_type != "color":
                data["fill_type"] = self.fill_type
            if self.fill_type == "texture" and self.fill_texture_id:
                data["fill_texture_id"] = self.fill_texture_id
                data["fill_texture_zoom"] = round(self.fill_texture_zoom, 3)
                data["fill_texture_rotation"] = round(self.fill_texture_rotation, 1)
        if self.rotation != 0.0:
            data["rotation"] = round(self.rotation, 2)

        # Render order
        if self.draw_over_grid:
            data["draw_over_grid"] = True

        return data

    @classmethod
    def deserialize(cls, data: dict) -> SketchObject:
        raw_points = data.get("points", [])
        points = [(p[0], p[1]) for p in raw_points if len(p) >= 2]  # M17: guard against corrupt point data

        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            shape_type=data.get("shape_type", "rect"),
            points=points,
            radius=data.get("radius", 30.0),
            num_sides=data.get("num_sides", 6),
            rx=data.get("rx", 40.0),
            ry=data.get("ry", 30.0),
            closed=data.get("closed", False),
            stroke_color=data.get("stroke_color", "#000000"),
            stroke_width=data.get("stroke_width", 2.0),
            stroke_type=data.get("stroke_type", "solid"),
            dash_length=data.get("dash_length", 8.0),
            gap_length=data.get("gap_length", 4.0),
            stroke_cap=data.get("stroke_cap", "round"),
            fill_enabled=data.get("fill_enabled", False),
            fill_color=data.get("fill_color", "#ffff00"),
            fill_opacity=data.get("fill_opacity", 0.3),
            fill_type=data.get("fill_type", "color"),
            fill_texture_id=data.get("fill_texture_id", ""),
            fill_texture_zoom=data.get("fill_texture_zoom", 1.0),
            fill_texture_rotation=data.get("fill_texture_rotation", 0.0),
            rotation=data.get("rotation", 0.0),
            shadow_enabled=data.get("shadow_enabled", False),
            shadow_type=data.get("shadow_type", "outer"),
            shadow_color=data.get("shadow_color", "#000000"),
            shadow_opacity=data.get("shadow_opacity", 0.5),
            shadow_angle=data.get("shadow_angle", 120.0),
            shadow_distance=data.get("shadow_distance", 5.0),
            shadow_spread=data.get("shadow_spread", 0.0),
            shadow_size=data.get("shadow_size", data.get("shadow_blur_radius", 5.0)),
            draw_over_grid=data.get("draw_over_grid", False),
        )


def _catmull_rom_path(points: list[tuple[float, float]]) -> QPainterPath:
    """Build a smooth QPainterPath through points using Catmull-Rom interpolation."""
    path = QPainterPath()
    if len(points) < 2:
        return path

    if len(points) == 2:
        path.moveTo(QPointF(points[0][0], points[0][1]))
        path.lineTo(QPointF(points[1][0], points[1][1]))
        return path

    path.moveTo(QPointF(points[0][0], points[0][1]))

    pts = [points[0]] + list(points) + [points[-1]]
    for i in range(1, len(pts) - 2):
        p0 = pts[i - 1]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2]

        cp1x = p1[0] + (p2[0] - p0[0]) / 6.0
        cp1y = p1[1] + (p2[1] - p0[1]) / 6.0
        cp2x = p2[0] - (p3[0] - p1[0]) / 6.0
        cp2y = p2[1] - (p3[1] - p1[1]) / 6.0

        path.cubicTo(
            QPointF(cp1x, cp1y),
            QPointF(cp2x, cp2y),
            QPointF(p2[0], p2[1]),
        )

    return path
