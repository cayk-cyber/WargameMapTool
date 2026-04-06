"""Text layer - places editable text labels on the map."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from app.hex.hex_math import Layout
from app.layers.base_layer import Layer
from app.models.text_object import TextObject


class TextLayer(Layer):
    def __init__(self, name: str = "Text"):
        super().__init__(name)
        self.objects: list[TextObject] = []
        self._over_grid_count: int = 0
        # Layer-level drop shadow
        self.shadow_enabled: bool = False
        self.shadow_type: str = "outer"  # "outer" or "inner"
        self.shadow_color: str = "#000000"
        self.shadow_opacity: float = 0.5
        self.shadow_angle: float = 120.0
        self.shadow_distance: float = 5.0
        self.shadow_spread: float = 0.0
        self.shadow_size: float = 5.0

    def _recount_over_grid(self) -> None:
        self._over_grid_count = sum(1 for o in self.objects if o.over_grid)

    def add_text(self, obj: TextObject) -> None:
        self.objects.append(obj)
        if getattr(obj, 'over_grid', False):
            self._over_grid_count += 1
        self.mark_dirty()

    def remove_text(self, obj: TextObject) -> None:
        self.objects = [o for o in self.objects if o.id != obj.id]
        self._recount_over_grid()
        self.mark_dirty()

    def hit_test(self, world_x: float, world_y: float) -> TextObject | None:
        """Find the topmost text object at the given world position."""
        for obj in reversed(self.objects):
            if obj.contains_point(world_x, world_y):
                return obj
        return None

    @property
    def has_over_grid_objects(self) -> bool:
        return self._over_grid_count > 0

    def notify_over_grid_changed(self) -> None:
        """Call when an object's over_grid flag has been toggled."""
        self._recount_over_grid()

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
        for obj in self.objects:
            if not viewport_rect.intersects(obj.bounding_rect()):
                continue
            obj.paint(painter)

    def paint_filtered(
        self, painter: QPainter, viewport_rect: QRectF, layout: Layout,
        over_grid: bool = False,
    ) -> None:
        if not (self._gfx_effects_enabled and self.shadow_enabled):
            self._paint_content_filtered(painter, viewport_rect, layout, over_grid)
            return
        composite, screen_tl, device_scale = self._build_shadow_composite(
            painter, viewport_rect, layout,
            lambda p, vr, l: self._paint_content_filtered(p, vr, l, over_grid),
        )
        if composite is None:
            self._paint_content_filtered(painter, viewport_rect, layout, over_grid)
            return
        painter.save()
        painter.resetTransform()
        if self.shadow_type == "outer":
            self._paint_outer_shadow(painter, composite, screen_tl, device_scale)
        painter.drawImage(screen_tl, composite)
        if self.shadow_type == "inner":
            self._paint_inner_shadow(painter, composite, screen_tl, device_scale)
        painter.restore()

    def _paint_content_filtered(
        self, painter: QPainter, viewport_rect: QRectF, layout: Layout,
        over_grid: bool = False,
    ) -> None:
        """Paint only objects with matching over_grid flag (for split-grid rendering)."""
        for obj in self.objects:
            if obj.over_grid != over_grid:
                continue
            if not viewport_rect.intersects(obj.bounding_rect()):
                continue
            obj.paint(painter)

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "text"
        data["objects"] = [obj.serialize() for obj in self.objects]
        # Always save shadow fields so disabled settings survive round-trip
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
    def deserialize(cls, data: dict) -> TextLayer:
        layer = cls(data.get("name", "Text"))
        layer._base_deserialize(data)
        layer.shadow_enabled = data.get("shadow_enabled", False)
        layer.shadow_type = data.get("shadow_type", "outer")
        layer.shadow_color = data.get("shadow_color", "#000000")
        layer.shadow_opacity = data.get("shadow_opacity", 0.5)
        layer.shadow_angle = data.get("shadow_angle", 120.0)
        layer.shadow_distance = data.get("shadow_distance", 5.0)
        layer.shadow_spread = data.get("shadow_spread", 0.0)
        layer.shadow_size = data.get("shadow_size", data.get("shadow_blur_radius", 5.0))
        for obj_data in data.get("objects", []):
            layer.objects.append(TextObject.deserialize(obj_data))
        layer._recount_over_grid()
        return layer
