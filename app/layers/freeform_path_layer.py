"""Freeform path layer - freehand-drawn paths in world space."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QTransform,
    Qt,
)

from app.io.texture_cache import get_texture_image

from app.layers.base_layer import Layer
from app.models.freeform_path_object import FreeformPathObject


_CAP_MAP = {
    "flat": Qt.PenCapStyle.FlatCap,
    "round": Qt.PenCapStyle.RoundCap,
    "square": Qt.PenCapStyle.SquareCap,
}


class FreeformPathLayer(Layer):
    clip_to_grid = True

    def __init__(self, name: str = "Path (Freeform)"):
        super().__init__(name)
        # Dict keyed by UUID string
        self.paths: dict[str, FreeformPathObject] = {}
        # QPainterPath cache: obj.id -> (points_tuple, QPainterPath)
        # Self-validating: recomputed only when the points list changes.
        self._path_cache: dict = {}
        # Keys hidden during interactive drag (set by tool, cleared on release)
        self._drag_hidden_keys: set = set()

        # Layer-level drop shadow
        self.shadow_enabled: bool = False
        self.shadow_type: str = "outer"  # "outer" or "inner"
        self.shadow_color: str = "#000000"
        self.shadow_opacity: float = 0.5
        self.shadow_angle: float = 120.0
        self.shadow_distance: float = 5.0
        self.shadow_spread: float = 0.0
        self.shadow_size: float = 5.0

    def add_path(self, obj: FreeformPathObject) -> None:
        self.paths[obj.id] = obj
        self.mark_dirty()

    def remove_path(self, obj: FreeformPathObject) -> None:
        self.paths.pop(obj.id, None)
        self._path_cache.pop(obj.id, None)
        self.mark_dirty()

    def get_path_by_id(self, path_id: str) -> FreeformPathObject | None:
        return self.paths.get(path_id)

    def hit_test(
        self, world_x: float, world_y: float, threshold: float = 8.0,
    ) -> FreeformPathObject | None:
        """Find the nearest freeform path to a world point within threshold."""
        point = QPointF(world_x, world_y)
        for obj in self.paths.values():
            if len(obj.points) < 2:
                continue
            path = self._get_cached_freeform_path(obj)
            if path.isEmpty():
                continue
            stroker = QPainterPathStroker()
            stroker.setWidth(max(obj.width, threshold * 2))
            stroked = stroker.createStroke(path)
            if stroked.contains(point):
                return obj
        return None

    # --- Rendering ---

    def paint(self, painter: QPainter, viewport_rect: QRectF, layout) -> None:
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

    def _paint_content(self, painter: QPainter, viewport_rect: QRectF, layout) -> None:
        margin = 50  # Fixed margin in world pixels
        expanded = viewport_rect.adjusted(-margin, -margin, margin, margin)

        # Collect visible paths and pre-compute QPainterPaths
        hidden = self._drag_hidden_keys
        visible: list[tuple[FreeformPathObject, QPainterPath]] = []
        for obj in self.paths.values():
            if hidden and obj.id in hidden:
                continue
            if len(obj.points) < 2:
                continue
            # Viewport culling via bounding box of points
            bbox = self._bounding_box(obj.points)
            if not expanded.intersects(bbox):
                continue
            path = self._get_cached_freeform_path(obj)
            if not path.isEmpty():
                visible.append((obj, path))

        # Two-pass rendering: all background paths first, then all foreground paths.
        # This prevents one path's background from covering another's foreground.

        # Pass 1: All background paths
        for obj, path in visible:
            if not obj.bg_enabled:
                continue
            painter.save()
            if obj.bg_opacity < 1.0:
                painter.setOpacity(obj.bg_opacity)
            pen = self._make_pen(
                obj.bg_color, obj.bg_width, obj.bg_line_type,
                obj.bg_dash_length, obj.bg_gap_length,
                obj.bg_texture_id, obj.bg_texture_zoom, obj.bg_texture_rotation,
                obj.bg_dash_cap,
            )
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()

        # Pass 2: All foreground paths (on top of all backgrounds)
        for obj, path in visible:
            painter.save()
            if obj.opacity < 1.0:
                painter.setOpacity(obj.opacity)
            pen = self._make_pen(
                obj.color, obj.width, obj.line_type,
                obj.dash_length, obj.gap_length,
                obj.texture_id, obj.texture_zoom, obj.texture_rotation,
                obj.dash_cap,
            )
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()

    @staticmethod
    def _bounding_box(points: list[tuple[float, float]]) -> QRectF:
        """Compute the bounding box of a list of points."""
        if not points:
            return QRectF()
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    @staticmethod
    def _make_pen(
        color: str, width: float, line_type: str,
        dash_length: float, gap_length: float,
        texture_id: str = "", texture_zoom: float = 1.0,
        texture_rotation: float = 0.0,
        dash_cap: str = "flat",
    ) -> QPen:
        """Create a QPen with the specified line type and optional texture."""
        # Build brush: textured or solid color
        if texture_id:
            img = get_texture_image(texture_id)
            if img is not None:
                brush = QBrush(QPixmap.fromImage(img))
                brush_xf = QTransform()
                if texture_rotation != 0.0:
                    brush_xf.rotate(texture_rotation)
                if texture_zoom != 1.0:
                    brush_xf.scale(texture_zoom, texture_zoom)
                brush.setTransform(brush_xf)
                pen = QPen(brush, width)
            else:
                pen = QPen(QColor(color), width)
        else:
            pen = QPen(QColor(color), width)

        cap = _CAP_MAP.get(dash_cap, Qt.PenCapStyle.FlatCap)
        pen.setCapStyle(cap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        if line_type == "dashed":
            pw = max(width, 0.5)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([dash_length / pw, gap_length / pw])
        elif line_type == "dotted":
            pw = max(width, 0.5)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([0.1, gap_length / pw])

        return pen

    def _get_cached_freeform_path(self, obj: FreeformPathObject) -> QPainterPath:
        """Return a cached QPainterPath, recomputing only when the points list changes.

        The cache is self-validating via (obj.id, obj._points_version).
        This avoids allocating a new tuple over the full points list every frame;
        only a two-element tuple is created, which is O(1) regardless of path length.
        During waypoint drag only the selected path is recomputed; all others
        keep their cached paths unchanged.
        """
        cache_key = (obj.id, obj._points_version)
        entry = self._path_cache.get(obj.id)
        if entry is not None and entry[0] == cache_key:
            return entry[1]
        path = self._compute_path(obj)
        self._path_cache[obj.id] = (cache_key, path)
        return path

    def _compute_path(self, obj: FreeformPathObject) -> QPainterPath:
        """Compute the full QPainterPath for a freeform path."""
        if len(obj.points) < 2:
            return QPainterPath()

        if obj.straight:
            return self._straight_path(list(obj.points))
        return self._catmull_rom_path(list(obj.points))

    @staticmethod
    def _straight_path(points: list[tuple[float, float]]) -> QPainterPath:
        """Build a QPainterPath with straight line segments (no spline)."""
        path = QPainterPath()
        path.moveTo(QPointF(points[0][0], points[0][1]))
        for x, y in points[1:]:
            path.lineTo(QPointF(x, y))
        return path

    @staticmethod
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

        # Add phantom points at start and end
        pts = [points[0]] + list(points) + [points[-1]]

        for i in range(1, len(pts) - 2):
            p0 = pts[i - 1]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[i + 2]

            # Catmull-Rom to cubic bezier conversion
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

    # --- Serialization ---

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "freeform_path"
        data["paths"] = [obj.serialize() for obj in self.paths.values()]
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
    def deserialize(cls, data: dict) -> FreeformPathLayer:
        layer = cls(data.get("name", "Path (Freeform)"))
        layer._base_deserialize(data)
        layer.shadow_enabled = data.get("shadow_enabled", False)
        layer.shadow_type = data.get("shadow_type", "outer")
        layer.shadow_color = data.get("shadow_color", "#000000")
        layer.shadow_opacity = data.get("shadow_opacity", 0.5)
        layer.shadow_angle = data.get("shadow_angle", 120.0)
        layer.shadow_distance = data.get("shadow_distance", 5.0)
        layer.shadow_spread = data.get("shadow_spread", 0.0)
        layer.shadow_size = data.get("shadow_size", data.get("shadow_blur_radius", 5.0))
        for obj_data in data.get("paths", []):
            obj = FreeformPathObject.deserialize(obj_data)
            layer.paths[obj.id] = obj
        return layer
