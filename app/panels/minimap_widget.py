"""Minimap widget showing a scaled-down overview of the map with viewport indicator."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from app.canvas.canvas_widget import CanvasWidget
from app.hex.hex_math import hex_corners, hex_neighbor
from app.layers.fill_layer import FillLayer
from app.layers.hexside_layer import HexsideLayer
from app.models.project import Project

# Minimum interval between content re-renders (ms)
_RENDER_THROTTLE_MS = 2000


class MinimapWidget(QWidget):
    """Small overview map with viewport rectangle and click-to-navigate."""

    # Emitted when the user clicks/drags to navigate: (world_center_x, world_center_y)
    navigate_requested = Signal(float, float)

    MINIMAP_HEIGHT = 160

    def __init__(self, project: Project, canvas: CanvasWidget, parent=None):
        super().__init__(parent)
        self._project = project
        self._canvas = canvas
        self.setFixedHeight(self.MINIMAP_HEIGHT)
        self.setMinimumWidth(100)
        self._is_dragging = False

        # Cached minimap image
        self._cache_pixmap: QPixmap | None = None
        self._cache_dirty = True
        self._cache_map_bounds: QRectF = QRectF()

        # Throttle timer for content re-renders
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(_RENDER_THROTTLE_MS)
        self._render_timer.timeout.connect(self._on_render_timer)

        # Connect to layer changes to invalidate cache (throttled)
        project.layer_stack.layers_changed.connect(self._schedule_render)

    def set_project(self, project: Project):
        """Update project reference (after new/open)."""
        # M13: disconnect old signal to prevent duplicate connections and stale callbacks
        try:
            self._project.layer_stack.layers_changed.disconnect(self._schedule_render)
        except RuntimeError:
            pass
        self._project = project
        project.layer_stack.layers_changed.connect(self._schedule_render)
        self._mark_dirty()

    def _schedule_render(self):
        """Schedule a throttled content re-render."""
        self._cache_dirty = True
        if not self._render_timer.isActive():
            self._render_timer.start()
        # Always repaint viewport rect immediately (cheap)
        self.update()

    def _on_render_timer(self):
        """Timer fired - trigger actual repaint with content rebuild."""
        self.update()

    def _mark_dirty(self):
        """Invalidate the cached minimap image (immediate, no throttle)."""
        self._cache_dirty = True
        self.update()

    def _get_map_bounds(self) -> QRectF:
        """Get the effective map bounds in world coordinates."""
        return self._project.grid_config.get_effective_bounds()

    def _map_to_widget(self, map_bounds: QRectF) -> tuple[float, float, float]:
        """Compute scale and offset to fit map_bounds into widget.

        Returns (scale, offset_x, offset_y).
        """
        if map_bounds.isEmpty():
            return 1.0, 0.0, 0.0

        w = self.width()
        h = self.height()
        margin = 4

        available_w = w - margin * 2
        available_h = h - margin * 2

        if available_w <= 0 or available_h <= 0:
            return 1.0, 0.0, 0.0

        scale_x = available_w / map_bounds.width()
        scale_y = available_h / map_bounds.height()
        scale = min(scale_x, scale_y)

        # Center the map in the widget
        rendered_w = map_bounds.width() * scale
        rendered_h = map_bounds.height() * scale
        offset_x = (w - rendered_w) / 2
        offset_y = (h - rendered_h) / 2

        return scale, offset_x, offset_y

    def _widget_to_world(self, widget_pos: QPointF) -> QPointF:
        """Convert widget coordinates to world coordinates."""
        map_bounds = self._get_map_bounds()
        scale, offset_x, offset_y = self._map_to_widget(map_bounds)

        world_x = (widget_pos.x() - offset_x) / scale + map_bounds.x()
        world_y = (widget_pos.y() - offset_y) / scale + map_bounds.y()
        return QPointF(world_x, world_y)

    def _render_minimap(self, map_bounds: QRectF) -> QPixmap:
        """Render the map content into a pixmap for the minimap."""
        if self.width() <= 0 or self.height() <= 0:
            return QPixmap()

        scale, offset_x, offset_y = self._map_to_widget(map_bounds)

        pixmap = QPixmap(self.width(), self.height())
        pixmap.fill(QColor("#3c3c3c"))

        if map_bounds.isEmpty():
            return pixmap

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Transform to map space
        painter.translate(offset_x, offset_y)
        painter.scale(scale, scale)
        painter.translate(-map_bounds.x(), -map_bounds.y())

        layout = self._project.grid_config.create_layout()
        config = self._project.grid_config

        # Clip to map bounds
        if config.half_hexes:
            painter.setClipRect(config.get_half_hex_bounds())

        # Border fill
        self._project.grid_renderer.paint_border_fill(painter, layout, config)

        # Collect fill data for hexside auto-shift and texture matching
        fill_colors: dict[tuple[int, int], str] = {}
        fill_textures: dict[tuple[int, int], object] = {}
        for layer in self._project.layer_stack:
            if layer.visible and isinstance(layer, FillLayer):
                for h, color in layer.fills.items():
                    fill_colors[(h.q, h.r)] = color.name()
                for h, tex in layer.textures.items():
                    fill_textures[(h.q, h.r)] = tex
        for layer in self._project.layer_stack:
            if isinstance(layer, HexsideLayer):
                layer.set_fill_context(fill_colors, fill_textures)

        # Grid clip path for layers that clip to the hex boundary (e.g. FillLayer).
        # Mirrors canvas_widget logic: clip_to_grid layers get the hex-union path;
        # other layers may render freely over map_bounds (border area included).
        # When half_hexes is active the whole painter is already clipped to the
        # rectangular half-hex bounds above, so no extra per-layer clip is needed.
        grid_clip = config.get_grid_clip_path() if not config.half_hexes else None

        # Layers (all visible - fills, assets, backgrounds, etc.)
        for layer in self._project.layer_stack:
            if not layer.visible:
                continue
            painter.save()
            painter.setOpacity(layer.opacity)
            if grid_clip is not None and layer.clip_to_grid:
                painter.setClipPath(grid_clip)
            layer.paint(painter, map_bounds, layout)
            painter.restore()

        # Outer boundary: draw only the edges of hexes that have no grid neighbour.
        # This gives a clean map outline without rendering the full grid.
        grid_set = set(config.get_all_hexes())
        is_flat = config.orientation == "flat"
        pen = QPen(config.edge_color, config.line_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for h in grid_set:
            corners = hex_corners(layout, h)
            for direction in range(6):
                if hex_neighbor(h, direction) not in grid_set:
                    ci = (-direction) % 6 if is_flat else (direction - 1) % 6
                    p1 = corners[ci]
                    p2 = corners[(ci + 1) % 6]
                    painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        painter.end()
        return pixmap

    def paintEvent(self, event: QPaintEvent):
        if not self.isVisible():
            return

        map_bounds = self._get_map_bounds()

        # Rebuild cache if dirty and timer has fired (or first paint)
        if self._cache_dirty and not self._render_timer.isActive():
            self._cache_pixmap = self._render_minimap(map_bounds)
            self._cache_map_bounds = QRectF(map_bounds)
            self._cache_dirty = False
        elif self._cache_pixmap is None:
            self._cache_pixmap = self._render_minimap(map_bounds)
            self._cache_map_bounds = QRectF(map_bounds)
            self._cache_dirty = False

        painter = QPainter(self)

        # Draw cached minimap
        painter.drawPixmap(0, 0, self._cache_pixmap)

        # Draw viewport indicator
        if not map_bounds.isEmpty():
            viewport = self._canvas.get_visible_world_rect()
            scale, offset_x, offset_y = self._map_to_widget(map_bounds)

            # Convert world viewport to widget coordinates
            vx = (viewport.x() - map_bounds.x()) * scale + offset_x
            vy = (viewport.y() - map_bounds.y()) * scale + offset_y
            vw = viewport.width() * scale
            vh = viewport.height() * scale

            view_rect = QRectF(vx, vy, vw, vh)

            pen = QPen(QColor(255, 60, 60, 220), 1.5)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 60, 60, 30))
            painter.drawRect(view_rect)

        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._navigate_to(event.position())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging:
            self._navigate_to(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False

    def _navigate_to(self, widget_pos: QPointF):
        """Navigate the main canvas so the clicked point is centered."""
        world_pos = self._widget_to_world(widget_pos)
        self.navigate_requested.emit(world_pos.x(), world_pos.y())
