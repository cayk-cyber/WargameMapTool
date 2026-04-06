"""Sketch layer - geometric shapes for administrative overlays."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform, Qt

from app.layers.base_layer import Layer
from app.models.sketch_object import SketchObject

_CAP_MAP = {
    "flat": Qt.PenCapStyle.FlatCap,
    "round": Qt.PenCapStyle.RoundCap,
    "square": Qt.PenCapStyle.SquareCap,
}


def _make_stroke_pen(obj: SketchObject, color: QColor | None = None) -> QPen:
    """Build a QPen respecting stroke_type, dash_length, gap_length, stroke_cap."""
    c = color if color is not None else QColor(obj.stroke_color)
    pen = QPen(c, obj.stroke_width)
    cap = _CAP_MAP.get(getattr(obj, "stroke_cap", "round"), Qt.PenCapStyle.RoundCap)
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    stroke_type = getattr(obj, "stroke_type", "solid")
    if stroke_type != "solid":
        pw = max(obj.stroke_width, 0.5)
        dash_len = getattr(obj, "dash_length", 8.0)
        gap_len = getattr(obj, "gap_length", 4.0)
        if stroke_type == "dashed":
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([dash_len / pw, gap_len / pw])
        elif stroke_type == "dotted":
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([0.1, gap_len / pw])
    return pen


class SketchLayer(Layer):
    def __init__(self, name: str = "Sketches"):
        super().__init__(name)
        self.objects: list[SketchObject] = []
        self._over_grid_count: int = 0  # cached count of draw_over_grid objects

        # Layer-level shadow (applies to all objects as a group)
        self.shadow_enabled: bool = False
        self.shadow_type: str = "outer"  # "outer" or "inner"
        self.shadow_color: str = "#000000"
        self.shadow_opacity: float = 0.5
        self.shadow_angle: float = 120.0
        self.shadow_distance: float = 5.0
        self.shadow_spread: float = 0.0
        self.shadow_size: float = 5.0

    def _recount_over_grid(self) -> None:
        self._over_grid_count = sum(1 for o in self.objects if o.draw_over_grid)

    def add_object(self, obj: SketchObject) -> None:
        self.objects.append(obj)
        if obj.draw_over_grid:
            self._over_grid_count += 1
        self.mark_dirty()

    def remove_object(self, obj: SketchObject) -> None:
        self.objects = [o for o in self.objects if o.id != obj.id]
        self._recount_over_grid()
        self.mark_dirty()

    def insert_object(self, index: int, obj: SketchObject) -> None:
        self.objects.insert(index, obj)
        if obj.draw_over_grid:
            self._over_grid_count += 1
        self.mark_dirty()

    def index_of(self, obj: SketchObject) -> int:
        for i, o in enumerate(self.objects):
            if o.id == obj.id:
                return i
        return -1

    def get_by_id(self, obj_id: str) -> SketchObject | None:
        for obj in self.objects:
            if obj.id == obj_id:
                return obj
        return None

    @property
    def has_over_grid_objects(self) -> bool:
        """True if any object has draw_over_grid enabled (O(1) cached)."""
        return self._over_grid_count > 0

    def notify_over_grid_changed(self) -> None:
        """Call when an object's draw_over_grid flag has been toggled."""
        self._recount_over_grid()

    def hit_test(
        self, world_x: float, world_y: float, threshold: float = 8.0,
    ) -> SketchObject | None:
        """Find the topmost sketch object at a world point."""
        for obj in reversed(self.objects):
            if obj.contains_point(world_x, world_y, threshold):
                return obj
        return None

    # --- Rendering ---

    @staticmethod
    def _paint_obj_fill(
        painter: QPainter, obj: SketchObject, path: QPainterPath,
    ) -> None:
        """Paint the fill of a sketch object (color or texture)."""
        fill_type = getattr(obj, "fill_type", "color")
        if fill_type == "texture" and getattr(obj, "fill_texture_id", ""):
            from app.io import texture_cache
            image = texture_cache.get_texture_image(obj.fill_texture_id)
            if image and not image.isNull():
                brush_xf = QTransform()
                if obj.fill_texture_rotation != 0.0:
                    brush_xf.rotate(obj.fill_texture_rotation)
                if obj.fill_texture_zoom != 1.0:
                    brush_xf.scale(obj.fill_texture_zoom, obj.fill_texture_zoom)
                brush = QBrush(QPixmap.fromImage(image))
                brush.setTransform(brush_xf)
                painter.setOpacity(obj.fill_opacity)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(brush)
                painter.drawPath(path)
                painter.setOpacity(1.0)
                return
        # Fallback: solid color fill
        fill_color = QColor(obj.fill_color)
        fill_color.setAlphaF(obj.fill_opacity)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill_color))
        painter.drawPath(path)

    def _paint_objects(
        self, painter: QPainter, viewport_rect: QRectF, layout,
        filter_over_grid: bool | None = None,
    ) -> None:
        """Paint objects without shadow.

        Args:
            filter_over_grid: None = all objects, True/False = only matching.
        """
        margin = 80
        expanded = viewport_rect.adjusted(-margin, -margin, margin, margin)

        for obj in self.objects:
            if filter_over_grid is not None and obj.draw_over_grid != filter_over_grid:
                continue
            bbox = obj.bounding_rect()
            if not expanded.intersects(bbox):
                continue

            path = obj.build_path()
            if path.isEmpty():
                continue

            cx, cy = obj.center()

            painter.save()
            painter.translate(cx, cy)
            painter.rotate(obj.rotation)
            painter.translate(-cx, -cy)

            if obj.fill_enabled and obj.shape_type != "line":
                self._paint_obj_fill(painter, obj, path)

            if obj.stroke_width > 0:
                painter.setPen(_make_stroke_pen(obj))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)

            painter.restore()

    def _paint_layer_shadow(
        self, painter: QPainter, viewport_rect: QRectF, layout,
    ) -> None:
        """Render layer-level shadow using off-screen composite."""
        composite, screen_tl, device_scale = self._build_shadow_composite(
            painter, viewport_rect, layout,
            lambda p, vr, ly: self._paint_objects(p, vr, ly),
        )
        if composite is None:
            return
        painter.save()
        painter.resetTransform()
        if self.shadow_type == "inner":
            self._paint_inner_shadow(painter, composite, screen_tl, device_scale)
        else:
            self._paint_outer_shadow(painter, composite, screen_tl, device_scale)
        painter.restore()

    def paint_filtered(
        self, painter: QPainter, viewport_rect: QRectF, layout,
        over_grid: bool,
    ) -> None:
        """Paint only objects matching the over_grid flag."""
        gfx = self._gfx_effects_enabled
        is_inner = gfx and self.shadow_enabled and self.shadow_type == "inner"

        # Outer shadow before content (only in under-grid pass)
        if not over_grid and gfx and self.shadow_enabled and not is_inner:
            self._paint_layer_shadow(painter, viewport_rect, layout)

        self._paint_objects(painter, viewport_rect, layout, filter_over_grid=over_grid)

        # Inner shadow after content (only in under-grid pass)
        if not over_grid and is_inner:
            self._paint_layer_shadow(painter, viewport_rect, layout)

    def paint(self, painter: QPainter, viewport_rect: QRectF, layout) -> None:
        gfx = self._gfx_effects_enabled
        is_inner = gfx and self.shadow_enabled and self.shadow_type == "inner"

        # Outer shadow before content
        if gfx and self.shadow_enabled and not is_inner:
            self._paint_layer_shadow(painter, viewport_rect, layout)

        self._paint_objects(painter, viewport_rect, layout)

        # Inner shadow after content
        if is_inner:
            self._paint_layer_shadow(painter, viewport_rect, layout)

    # --- Serialization ---

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "sketch"
        data["objects"] = [obj.serialize() for obj in self.objects]
        # Layer-level shadow (always save so disabled settings survive round-trip)
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
    def deserialize(cls, data: dict) -> SketchLayer:
        layer = cls(data.get("name", "Sketches"))
        layer._base_deserialize(data)

        # Layer-level shadow
        layer.shadow_enabled = data.get("shadow_enabled", False)
        layer.shadow_type = data.get("shadow_type", "outer")
        layer.shadow_color = data.get("shadow_color", "#000000")
        layer.shadow_opacity = data.get("shadow_opacity", 0.5)
        layer.shadow_angle = data.get("shadow_angle", 120.0)
        layer.shadow_distance = data.get("shadow_distance", 5.0)
        layer.shadow_spread = data.get("shadow_spread", 0.0)
        layer.shadow_size = data.get("shadow_size", data.get("shadow_blur_radius", 5.0))

        # Backward compat: layer-level draw_over_grid → apply to all objects
        layer_over_grid = data.get("draw_over_grid", False)
        for obj_data in data.get("objects", []):
            if layer_over_grid and "draw_over_grid" not in obj_data:
                obj_data["draw_over_grid"] = True
            obj = SketchObject.deserialize(obj_data)
            layer.objects.append(obj)

        # BUG-2 fix: recount over-grid objects after loading
        layer._recount_over_grid()

        # Backward compat: migrate per-object shadow to layer-level
        if not layer.shadow_enabled:
            for obj in layer.objects:
                if obj.shadow_enabled:
                    layer.shadow_enabled = True
                    layer.shadow_type = obj.shadow_type
                    layer.shadow_color = obj.shadow_color
                    layer.shadow_opacity = obj.shadow_opacity
                    layer.shadow_angle = obj.shadow_angle
                    layer.shadow_distance = obj.shadow_distance
                    layer.shadow_spread = obj.shadow_spread
                    layer.shadow_size = obj.shadow_size
                    break

        return layer
