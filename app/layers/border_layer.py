"""Border layer - styled lines drawn along hex edges (borders, fences, etc.)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, Qt

_CAP_MAP = {
    "flat": Qt.PenCapStyle.FlatCap,
    "round": Qt.PenCapStyle.RoundCap,
    "square": Qt.PenCapStyle.SquareCap,
}

from app.hex.hex_math import (
    Hex,
    Layout,
    hex_edge_key,
    hex_edge_vertices,
    hex_to_pixel,
)
from app.layers.base_layer import Layer
from app.models.border_object import BorderObject


class BorderLayer(Layer):
    clip_to_grid = True

    def __init__(self, name: str = "Border"):
        super().__init__(name)
        # Dict keyed by canonical edge key: ((q_a, r_a), (q_b, r_b))
        self.borders: dict[tuple[tuple[int, int], tuple[int, int]], BorderObject] = {}
        # Layer-level drop shadow
        self.shadow_enabled: bool = False
        self.shadow_type: str = "outer"  # "outer" or "inner"
        self.shadow_color: str = "#000000"
        self.shadow_opacity: float = 0.5
        self.shadow_angle: float = 120.0
        self.shadow_distance: float = 5.0
        self.shadow_spread: float = 0.0
        self.shadow_size: float = 5.0

    def add_border(self, obj: BorderObject) -> None:
        self.borders[obj.edge_key()] = obj
        self.mark_dirty()

    def remove_border(self, obj: BorderObject) -> None:
        self.borders.pop(obj.edge_key(), None)
        self.mark_dirty()

    def get_border_at_edge(self, hex_a: Hex, hex_b: Hex) -> BorderObject | None:
        key = hex_edge_key(hex_a, hex_b)
        return self.borders.get(key)

    def hit_test(
        self, world_x: float, world_y: float, layout: Layout, threshold: float = 8.0,
    ) -> BorderObject | None:
        """Find the nearest border to a world point within threshold."""
        point = QPointF(world_x, world_y)
        for obj in self.borders.values():
            path = self._compute_border_path(layout, obj)
            if path.isEmpty():
                continue
            stroker = QPainterPathStroker()
            effective_width = obj.width
            if obj.line_type == "dotted":
                effective_width = max(obj.width, obj.element_size)
            stroker.setWidth(max(effective_width, threshold * 2))
            stroked = stroker.createStroke(path)
            if stroked.contains(point):
                return obj
        return None

    # --- Rendering ---

    def paint(self, painter: QPainter, viewport_rect: QRectF, layout: Layout) -> None:
        if not (self._gfx_effects_enabled and self.shadow_enabled):
            self._paint_content(painter, viewport_rect, layout)
            return
        composite, screen_tl, device_scale = self._build_shadow_composite(
            painter, viewport_rect, layout, self._paint_content
        )
        if composite is None:
            self._paint_content(painter, viewport_rect, layout)
            return
        painter.save()
        painter.resetTransform()
        if self.shadow_type == "outer":
            self._paint_outer_shadow(painter, composite, screen_tl, device_scale)
        painter.drawImage(screen_tl, composite)
        if self.shadow_type == "inner":
            self._paint_inner_shadow(painter, composite, screen_tl, device_scale)
        painter.restore()

    def _paint_content(self, painter: QPainter, viewport_rect: QRectF, layout: Layout) -> None:
        margin = layout.size_x * 2
        expanded = viewport_rect.adjusted(-margin, -margin, margin, margin)

        # Collect visible borders and pre-compute paths
        visible: list[tuple[BorderObject, QPainterPath]] = []
        for obj in self.borders.values():
            cx_a, cy_a = hex_to_pixel(layout, obj.hex_a())
            cx_b, cy_b = hex_to_pixel(layout, obj.hex_b())
            mid_x = (cx_a + cx_b) / 2
            mid_y = (cy_a + cy_b) / 2
            if not expanded.contains(QPointF(mid_x, mid_y)):
                continue
            path = self._compute_border_path(layout, obj)
            if not path.isEmpty():
                visible.append((obj, path))

        # Two-pass rendering: outlines first, then main lines
        for obj, path in visible:
            if obj.outline:
                self._paint_outline(painter, obj, path)

        for obj, path in visible:
            pen = self._make_pen(
                obj.color, obj.width, obj.line_type,
                obj.element_size, obj.gap_size, obj.dash_cap,
            )
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _paint_outline(
        self, painter: QPainter, obj: BorderObject, path: QPainterPath,
    ) -> None:
        """Draw the outline around each element individually."""
        ol_pen = self._make_outline_pen(
            obj.outline_color, obj.outline_width,
            obj.width, obj.line_type,
            obj.element_size, obj.gap_size, obj.dash_cap,
        )
        painter.setPen(ol_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    @staticmethod
    def _make_outline_pen(
        outline_color: str, outline_width: float,
        main_width: float, line_type: str,
        element_size: float, gap_size: float,
        dash_cap: str = "round",
    ) -> QPen:
        """Create a QPen for the outline behind the main border line."""
        if line_type == "dotted":
            main_pw = max(element_size, 0.5)
            total_pw = main_pw + outline_width * 2
            pen = QPen(QColor(outline_color), total_pw)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([0.1, gap_size / total_pw])
        elif line_type == "dashed":
            total_width = main_width + outline_width * 2
            pen = QPen(QColor(outline_color), total_width)
            cap = _CAP_MAP.get(dash_cap, Qt.PenCapStyle.RoundCap)
            pen.setCapStyle(cap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pw = max(total_width, 0.5)
            pen.setDashPattern([element_size / pw, gap_size / pw])
        else:
            total_width = main_width + outline_width * 2
            pen = QPen(QColor(outline_color), total_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _find_direction(self, obj: BorderObject) -> int | None:
        """Find the direction index from hex_a to hex_b."""
        dq = obj.hex_b_q - obj.hex_a_q
        dr = obj.hex_b_r - obj.hex_a_r
        from app.hex.hex_math import HEX_DIRECTIONS
        for d in range(6):
            if HEX_DIRECTIONS[d].q == dq and HEX_DIRECTIONS[d].r == dr:
                return d
        return None

    def _get_edge_normal(
        self, layout: Layout, hex_a: Hex, hex_b: Hex,
    ) -> tuple[float, float]:
        """Get the unit normal perpendicular to the edge, pointing from hex_a toward hex_b."""
        ca_x, ca_y = hex_to_pixel(layout, hex_a)
        cb_x, cb_y = hex_to_pixel(layout, hex_b)
        dx = cb_x - ca_x
        dy = cb_y - ca_y
        length = math.hypot(dx, dy)
        if length == 0:
            return (0.0, 0.0)
        return (dx / length, dy / length)

    def _compute_border_path(self, layout: Layout, obj: BorderObject) -> QPainterPath:
        """Compute a straight QPainterPath along the hex edge with offset applied."""
        direction = self._find_direction(obj)
        if direction is None:
            return QPainterPath()

        v1, v2 = hex_edge_vertices(layout, obj.hex_a(), direction)

        # Apply offset perpendicular to edge
        if obj.offset != 0.0:
            nx, ny = self._get_edge_normal(layout, obj.hex_a(), obj.hex_b())
            ox, oy = obj.offset * nx, obj.offset * ny
            v1 = (v1[0] + ox, v1[1] + oy)
            v2 = (v2[0] + ox, v2[1] + oy)

        path = QPainterPath()
        path.moveTo(QPointF(v1[0], v1[1]))
        path.lineTo(QPointF(v2[0], v2[1]))
        return path

    @staticmethod
    def _make_pen(
        color: str, width: float, line_type: str,
        element_size: float, gap_size: float,
        dash_cap: str = "round",
    ) -> QPen:
        """Create a QPen for the given border style."""
        if line_type == "dotted":
            # Dot diameter = element_size (pen width controls dot size with RoundCap)
            dot_pw = max(element_size, 0.5)
            pen = QPen(QColor(color), dot_pw)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([0.1, gap_size / dot_pw])
            return pen

        cap = _CAP_MAP.get(dash_cap, Qt.PenCapStyle.RoundCap)
        pen = QPen(QColor(color), width)
        pen.setCapStyle(cap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        if line_type == "dashed":
            pw = max(width, 0.5)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([element_size / pw, gap_size / pw])

        return pen

    # --- Serialization ---

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "border"
        data["borders"] = [obj.serialize() for obj in self.borders.values()]
        # Always save all effect fields so disabled settings survive round-trip
        data["shadow_enabled"] = self.shadow_enabled
        data["shadow_type"] = self.shadow_type
        data["shadow_color"] = self.shadow_color
        data["shadow_opacity"] = round(self.shadow_opacity, 2)
        data["shadow_angle"] = round(self.shadow_angle, 1)
        data["shadow_distance"] = round(self.shadow_distance, 1)
        data["shadow_spread"] = round(self.shadow_spread, 1)
        data["shadow_size"] = round(self.shadow_size, 1)
        return data

    @classmethod
    def deserialize(cls, data: dict) -> BorderLayer:
        layer = cls(data.get("name", "Border"))
        layer._base_deserialize(data)
        layer.shadow_enabled = data.get("shadow_enabled", False)
        layer.shadow_type = data.get("shadow_type", "outer")
        layer.shadow_color = data.get("shadow_color", "#000000")
        layer.shadow_opacity = data.get("shadow_opacity", 0.5)
        layer.shadow_angle = data.get("shadow_angle", 120.0)
        layer.shadow_distance = data.get("shadow_distance", 5.0)
        layer.shadow_spread = data.get("shadow_spread", 0.0)
        layer.shadow_size = data.get("shadow_size", data.get("shadow_blur_radius", 5.0))
        for obj_data in data.get("borders", []):
            obj = BorderObject.deserialize(obj_data)
            layer.borders[obj.edge_key()] = obj
        return layer
