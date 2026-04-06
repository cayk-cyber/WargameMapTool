"""Fill layer - colors or textures individual hexes."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform

from app.hex.hex_math import (
    Hex,
    Layout,
    axial_to_offset,
    hex_corners,
    hex_to_pixel,
    pixel_to_hex,
)
from app.layers.base_layer import Layer

# Module-level render quality flag.
# False (default) = Performance: world-resolution cache (current behavior).
# True            = Quality: screen-resolution cache (sharp at zoom).
_quality_mode: bool = False


def set_fill_quality_mode(enabled: bool) -> None:
    """Set the fill layer render quality mode (affects all FillLayer instances)."""
    global _quality_mode
    _quality_mode = enabled


@dataclass
class HexTexture:
    """Per-hex texture fill data."""

    texture_id: str
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation: float = 0.0

    def serialize(self) -> dict:
        return {
            "texture_id": self.texture_id,
            "zoom": self.zoom,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "rotation": self.rotation,
        }

    @classmethod
    def deserialize(cls, data: dict) -> HexTexture:
        return cls(
            texture_id=data["texture_id"],
            zoom=data.get("zoom", 1.0),
            offset_x=data.get("offset_x", 0.0),
            offset_y=data.get("offset_y", 0.0),
            rotation=data.get("rotation", 0.0),
        )


@dataclass
class HexEdgeFill:
    """Per-hex edge fill data (inner border with optional outline)."""

    color: str  # Hex color string like "#ff0000"
    width: float = 2.0  # Width in world units (mm)
    outline: bool = False  # Whether to draw inner outline
    outline_color: str = "#000000"  # Outline color
    outline_width: float = 0.5  # Outline width in world units (mm)

    def serialize(self) -> dict:
        data = {"color": self.color, "width": self.width}
        # Always save outline fields so settings survive round-trip
        data["outline"] = self.outline
        data["outline_color"] = self.outline_color
        data["outline_width"] = self.outline_width
        return data

    @classmethod
    def deserialize(cls, data: dict) -> HexEdgeFill:
        return cls(
            color=data["color"],
            width=data.get("width", 2.0),
            outline=data.get("outline", False),
            outline_color=data.get("outline_color", "#000000"),
            outline_width=data.get("outline_width", 0.5),
        )


def _compute_inset_polygon(
    cx: float, cy: float, corners: list[tuple[float, float]], inset: float
) -> QPolygonF | None:
    """Compute a polygon inset from hex corners toward center by *inset* distance.

    Uses the apothem (center-to-edge-midpoint distance) to derive the
    uniform scale factor that shrinks the hex by the requested amount.
    Returns None if the inset is larger than the apothem.
    """
    # Apothem = distance from center to midpoint of first edge
    mx = (corners[0][0] + corners[1][0]) * 0.5
    my = (corners[0][1] + corners[1][1]) * 0.5
    dx, dy = mx - cx, my - cy
    apothem = (dx * dx + dy * dy) ** 0.5
    if apothem <= inset:
        return None
    scale = 1.0 - inset / apothem
    return QPolygonF(
        [QPointF(cx + (x - cx) * scale, cy + (y - cy) * scale) for x, y in corners]
    )


class FillLayer(Layer):
    clip_to_grid = True

    @property
    def cacheable(self) -> bool:
        """Quality mode: screen-res cache (sharp). Performance mode: world-res cache."""
        return not _quality_mode

    def __init__(self, name: str = "Fill"):
        super().__init__(name)
        self.fills: dict[Hex, QColor] = {}
        self.dot_colors: dict[Hex, QColor] = {}
        self.coord_colors: dict[Hex, QColor] = {}
        self.textures: dict[Hex, HexTexture] = {}
        self.edge_fills: dict[Hex, HexEdgeFill] = {}
        # Colour off-screen buffer with dirty-region tracking (mirrors _tex_buffer).
        # Stores all colour-filled hexes pre-rendered into a pixmap so that only
        # the changed hex needs to be repainted on each edit.
        self._color_buffer: QPixmap | None = None
        self._color_buffer_bounds: QRectF | None = None
        self._dirty_color_hexes: set[Hex] | None = None  # None = full repaint

        # Texture off-screen buffer with dirty-region tracking
        self._tex_buffer: QPixmap | None = None
        self._tex_buffer_bounds: QRectF | None = None
        self._dirty_hexes: set[Hex] | None = None  # None = full repaint
        self._texture_pixmap_cache: dict[str, QPixmap] = {}

    # --- Dirty tracking ---

    def mark_dirty(self) -> None:
        """Full invalidation — discard both off-screen buffers."""
        super().mark_dirty()
        self._dirty_hexes = None
        self._dirty_color_hexes = None
        self._tex_buffer = None
        self._color_buffer = None

    def _mark_hex_dirty(self, hex_coord: Hex) -> None:
        """Mark a single hex as needing repaint (incremental)."""
        if self._dirty_hexes is not None:
            self._dirty_hexes.add(hex_coord)
        if self._dirty_color_hexes is not None:
            self._dirty_color_hexes.add(hex_coord)
        # Invalidate canvas-level cache so paintEvent re-calls paint()
        self._cache_dirty = True
        self._cache_pixmap = None

    # --- Mutation methods (use _mark_hex_dirty for incremental updates) ---

    def set_fill(self, hex_coord: Hex, color: QColor) -> None:
        self.fills[hex_coord] = QColor(color)
        # A hex has either color or texture, not both
        self.textures.pop(hex_coord, None)
        self._mark_hex_dirty(hex_coord)

    def clear_fill(self, hex_coord: Hex) -> QColor | None:
        result = self.fills.pop(hex_coord, None)
        self._mark_hex_dirty(hex_coord)
        return result

    def get_fill(self, hex_coord: Hex) -> QColor | None:
        return self.fills.get(hex_coord)

    def set_dot_color(self, hex_coord: Hex, color: QColor) -> None:
        self.dot_colors[hex_coord] = QColor(color)
        self._mark_hex_dirty(hex_coord)

    def clear_dot_color(self, hex_coord: Hex) -> QColor | None:
        result = self.dot_colors.pop(hex_coord, None)
        self._mark_hex_dirty(hex_coord)
        return result

    def get_dot_color(self, hex_coord: Hex) -> QColor | None:
        return self.dot_colors.get(hex_coord)

    def set_coord_color(self, hex_coord: Hex, color: QColor) -> None:
        self.coord_colors[hex_coord] = QColor(color)
        self._mark_hex_dirty(hex_coord)

    def clear_coord_color(self, hex_coord: Hex) -> QColor | None:
        result = self.coord_colors.pop(hex_coord, None)
        self._mark_hex_dirty(hex_coord)
        return result

    def get_coord_color(self, hex_coord: Hex) -> QColor | None:
        return self.coord_colors.get(hex_coord)

    def set_texture(self, hex_coord: Hex, texture: HexTexture) -> None:
        self.textures[hex_coord] = texture
        # A hex has either texture or color, not both
        self.fills.pop(hex_coord, None)
        self._mark_hex_dirty(hex_coord)

    def clear_texture(self, hex_coord: Hex) -> HexTexture | None:
        result = self.textures.pop(hex_coord, None)
        self._mark_hex_dirty(hex_coord)
        return result

    def get_texture(self, hex_coord: Hex) -> HexTexture | None:
        return self.textures.get(hex_coord)

    def set_edge_fill(self, hex_coord: Hex, edge_fill: HexEdgeFill) -> None:
        self.edge_fills[hex_coord] = edge_fill
        self._mark_hex_dirty(hex_coord)

    def clear_edge_fill(self, hex_coord: Hex) -> HexEdgeFill | None:
        result = self.edge_fills.pop(hex_coord, None)
        self._mark_hex_dirty(hex_coord)
        return result

    def get_edge_fill(self, hex_coord: Hex) -> HexEdgeFill | None:
        return self.edge_fills.get(hex_coord)

    # --- Rendering ---

    def paint(self, painter: QPainter, viewport_rect: QRectF, layout: Layout) -> None:
        # Expand viewport by hex_size to catch hexes at edges (used by edge_fills)
        margin = layout.size_x
        expanded = viewport_rect.adjusted(-margin, -margin, margin, margin)

        # Draw colour fills via off-screen buffer (incremental updates)
        if self.fills:
            self._paint_colors(painter, viewport_rect, layout)

        # Draw texture fills via off-screen buffer
        if self.textures:
            self._paint_textures(painter, viewport_rect, layout)

        # Draw edge fills (inner borders) - on top of colour/texture fills
        if self.edge_fills:
            for hex_coord, edge_fill in self.edge_fills.items():
                cx, cy = hex_to_pixel(layout, hex_coord)
                if not expanded.contains(QPointF(cx, cy)):
                    continue
                corners = hex_corners(layout, hex_coord)
                polygon = QPolygonF([QPointF(x, y) for x, y in corners])

                clip_path = QPainterPath()
                clip_path.addPolygon(polygon)
                clip_path.closeSubpath()

                # Clip to hex, draw outline with 2x width so inner half = desired width
                painter.save()
                painter.setClipPath(clip_path)
                pen = QPen(QColor(edge_fill.color), edge_fill.width * 2)
                pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(polygon)
                painter.restore()

                # Draw inner outline along the inset polygon boundary
                if edge_fill.outline:
                    inset = _compute_inset_polygon(
                        cx, cy, corners, edge_fill.width
                    )
                    if inset is not None:
                        painter.save()
                        painter.setClipPath(clip_path)
                        ol_pen = QPen(
                            QColor(edge_fill.outline_color),
                            edge_fill.outline_width,
                        )
                        ol_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                        painter.setPen(ol_pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawPolygon(inset)
                        painter.restore()

    def _paint_colors(
        self, painter: QPainter, viewport_rect: QRectF, layout: Layout,
    ) -> None:
        """Render colour fills using an off-screen buffer with dirty-region updates.

        On first call (or after mark_dirty): builds a full pixmap of all fills.
        On subsequent edits: only the hexes in _dirty_color_hexes are cleared
        and redrawn, leaving the rest of the pixmap untouched.

        When the painter's world transform has a scale > 1 (e.g. during export
        at DPI > 96), the buffer is bypassed and fills are drawn directly so
        that Qt's renderer scales the vector geometry — not a low-res bitmap.
        """
        bounds = viewport_rect
        # Check painter scale: at export DPI > 96 the world transform has scale > 1.
        # Drawing a world-resolution pixmap through that transform produces blurry
        # output, so we skip the buffer and let the painter scale vector ops instead.
        paint_scale = abs(painter.worldTransform().m11())
        use_buffer = paint_scale <= 1.01

        w = max(1, int(bounds.width()))
        h = max(1, int(bounds.height()))
        exp_factor = 1.0 + 0.7 / layout.size_x

        buf_valid = (
            use_buffer
            and self._color_buffer is not None
            and self._color_buffer_bounds is not None
            and self._color_buffer_bounds == bounds
            and self._dirty_color_hexes is not None
        )

        if buf_valid and not self._dirty_color_hexes:
            # Buffer current, nothing dirty — blit only.
            painter.drawPixmap(QPointF(bounds.x(), bounds.y()), self._color_buffer)
            return

        if buf_valid:
            # Incremental update: clear and redraw only the dirty hexes.
            bp = QPainter(self._color_buffer)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bp.translate(-bounds.x(), -bounds.y())

            for hex_coord in self._dirty_color_hexes:
                cx, cy = hex_to_pixel(layout, hex_coord)
                corners = hex_corners(layout, hex_coord)
                exp_poly = QPolygonF([
                    QPointF(cx + (x - cx) * exp_factor, cy + (y - cy) * exp_factor)
                    for x, y in corners
                ])
                clip_path = QPainterPath()
                clip_path.addPolygon(exp_poly)
                clip_path.closeSubpath()

                # Clear old content (transparent) for this hex region.
                bp.save()
                bp.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Clear
                )
                bp.setPen(Qt.PenStyle.NoPen)
                bp.setBrush(QBrush(QColor(0, 0, 0, 0)))
                bp.drawPath(clip_path)
                bp.restore()

                # Redraw if the hex still has a colour fill.
                color = self.fills.get(hex_coord)
                if color is not None:
                    bp.setPen(Qt.PenStyle.NoPen)
                    bp.setBrush(color)
                    bp.drawPolygon(exp_poly)

            bp.end()
            self._dirty_color_hexes.clear()
        else:
            # Full repaint: build a fresh buffer from all fills.
            # When paint_scale > 1 (export) or the viewport is very large, draw
            # directly so the painter's transform handles scaling at full quality.
            # When called from a cache-build context (world-res / screen-res in
            # canvas_widget), viewport_rect == map_bounds which can be hundreds of
            # megapixels.  Allocating a QPixmap that large often fails on low-VRAM
            # systems and always wastes memory since the canvas will cache the result
            # itself.  Draw directly into the supplied painter instead and skip
            # storing a buffer so incremental updates remain available at smaller
            # viewport sizes (interactive direct-render path).
            _MAX_BUF_PX = 100_000_000
            if not use_buffer or w * h > _MAX_BUF_PX:
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(Qt.PenStyle.NoPen)
                margin = layout.size_x
                expanded = bounds.adjusted(-margin, -margin, margin, margin)
                for hex_coord, color in self.fills.items():
                    cx, cy = hex_to_pixel(layout, hex_coord)
                    if not expanded.contains(QPointF(cx, cy)):
                        continue
                    corners = hex_corners(layout, hex_coord)
                    polygon = QPolygonF([
                        QPointF(cx + (x - cx) * exp_factor, cy + (y - cy) * exp_factor)
                        for x, y in corners
                    ])
                    painter.setBrush(color)
                    painter.drawPolygon(polygon)
                painter.restore()
                return

            buf = QPixmap(w, h)
            buf.fill(Qt.GlobalColor.transparent)
            bp = QPainter(buf)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bp.translate(-bounds.x(), -bounds.y())
            bp.setPen(Qt.PenStyle.NoPen)

            margin = layout.size_x
            expanded = bounds.adjusted(-margin, -margin, margin, margin)
            for hex_coord, color in self.fills.items():
                cx, cy = hex_to_pixel(layout, hex_coord)
                if not expanded.contains(QPointF(cx, cy)):
                    continue
                corners = hex_corners(layout, hex_coord)
                polygon = QPolygonF([
                    QPointF(cx + (x - cx) * exp_factor, cy + (y - cy) * exp_factor)
                    for x, y in corners
                ])
                bp.setBrush(color)
                bp.drawPolygon(polygon)

            bp.end()
            self._color_buffer = buf
            self._color_buffer_bounds = QRectF(bounds)
            self._dirty_color_hexes = set()

        painter.drawPixmap(QPointF(bounds.x(), bounds.y()), self._color_buffer)

    def _paint_textures(
        self, painter: QPainter, viewport_rect: QRectF, layout: Layout,
    ) -> None:
        """Render textures using an off-screen buffer with dirty-region updates.

        When the painter's world transform has a scale > 1 (e.g. during export
        at DPI > 96), the buffer is bypassed and textures are drawn directly so
        that the vector clipping path and brush are rendered at full output quality.
        """
        from app.io.texture_cache import get_texture_image

        bounds = viewport_rect
        # Skip buffer for export (paint_scale > 1): same reasoning as _paint_colors.
        paint_scale = abs(painter.worldTransform().m11())
        use_buffer = paint_scale <= 1.01

        w = max(1, int(bounds.width()))
        h = max(1, int(bounds.height()))

        # Check if we can do an incremental update
        buf_valid = (
            use_buffer
            and self._tex_buffer is not None
            and self._tex_buffer_bounds is not None
            and self._tex_buffer_bounds == bounds
            and self._dirty_hexes is not None
        )

        if buf_valid and not self._dirty_hexes:
            # Buffer valid, no dirty hexes — just blit
            painter.drawPixmap(QPointF(bounds.x(), bounds.y()), self._tex_buffer)
            return

        if buf_valid:
            # Incremental update — only re-render dirty hexes
            bp = QPainter(self._tex_buffer)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            bp.translate(-bounds.x(), -bounds.y())

            exp_factor = 1.0 + 0.7 / layout.size_x
            for hex_coord in self._dirty_hexes:
                cx, cy = hex_to_pixel(layout, hex_coord)
                corners = hex_corners(layout, hex_coord)
                # Expand polygon to match _render_tex_hex so clear covers entire rendered area
                exp_poly = QPolygonF([
                    QPointF(cx + (x - cx) * exp_factor, cy + (y - cy) * exp_factor)
                    for x, y in corners
                ])
                clip_path = QPainterPath()
                clip_path.addPolygon(exp_poly)
                clip_path.closeSubpath()

                # Clear the hex region (including expanded border)
                bp.save()
                bp.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Clear
                )
                bp.setPen(Qt.PenStyle.NoPen)
                bp.setBrush(QBrush(QColor(0, 0, 0, 0)))
                bp.drawPath(clip_path)
                bp.restore()

                # Re-render if texture exists at this hex
                hex_tex = self.textures.get(hex_coord)
                if hex_tex:
                    self._render_tex_hex(bp, hex_coord, hex_tex, layout)

            bp.end()
            self._dirty_hexes.clear()
        else:
            # Full repaint — create new buffer and render all textures.
            # Same large-viewport guard as _paint_colors: draw directly if too big or
            # if paint_scale > 1 (export at DPI > 96).
            _MAX_BUF_PX = 100_000_000
            if not use_buffer or w * h > _MAX_BUF_PX:
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                margin = layout.size_x
                expanded = bounds.adjusted(-margin, -margin, margin, margin)
                for hex_coord, hex_tex in self.textures.items():
                    cx, cy = hex_to_pixel(layout, hex_coord)
                    if not expanded.contains(QPointF(cx, cy)):
                        continue
                    self._render_tex_hex(painter, hex_coord, hex_tex, layout)
                painter.restore()
                return

            buf = QPixmap(w, h)
            buf.fill(Qt.GlobalColor.transparent)
            bp = QPainter(buf)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            bp.translate(-bounds.x(), -bounds.y())

            margin = layout.size_x
            expanded = bounds.adjusted(-margin, -margin, margin, margin)

            for hex_coord, hex_tex in self.textures.items():
                cx, cy = hex_to_pixel(layout, hex_coord)
                if not expanded.contains(QPointF(cx, cy)):
                    continue
                self._render_tex_hex(bp, hex_coord, hex_tex, layout)

            bp.end()
            self._tex_buffer = buf
            self._tex_buffer_bounds = QRectF(bounds)
            self._dirty_hexes = set()

        painter.drawPixmap(QPointF(bounds.x(), bounds.y()), self._tex_buffer)

    def _render_tex_hex(
        self, painter: QPainter, hex_coord: Hex,
        hex_tex: HexTexture, layout: Layout,
    ) -> None:
        """Render a single textured hex into the given painter."""
        from app.io.texture_cache import get_texture_image

        # Get or create cached QPixmap for this texture_id
        if hex_tex.texture_id not in self._texture_pixmap_cache:
            image = get_texture_image(hex_tex.texture_id)
            if image is None:
                return
            self._texture_pixmap_cache[hex_tex.texture_id] = (
                QPixmap.fromImage(image)
            )
        pixmap = self._texture_pixmap_cache.get(hex_tex.texture_id)
        if pixmap is None:
            return

        cx, cy = hex_to_pixel(layout, hex_coord)
        corners = hex_corners(layout, hex_coord)
        # Expand polygon slightly to prevent hairline gaps when grid is hidden
        exp_factor = 1.0 + 0.7 / layout.size_x
        polygon = QPolygonF([
            QPointF(cx + (x - cx) * exp_factor, cy + (y - cy) * exp_factor)
            for x, y in corners
        ])

        clip_path = QPainterPath()
        clip_path.addPolygon(polygon)
        clip_path.closeSubpath()

        # Create tiled brush in world space
        brush = QBrush(pixmap)
        brush_xf = QTransform()
        if hex_tex.offset_x != 0.0 or hex_tex.offset_y != 0.0:
            brush_xf.translate(hex_tex.offset_x, hex_tex.offset_y)
        if hex_tex.rotation != 0.0:
            brush_xf.rotate(hex_tex.rotation)
        if hex_tex.zoom != 1.0:
            brush_xf.scale(hex_tex.zoom, hex_tex.zoom)
        brush.setTransform(brush_xf)

        painter.save()
        painter.setBrush(brush)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(clip_path)
        painter.restore()

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "fill"
        data["hexes"] = {
            f"{h.q},{h.r}": color.name() for h, color in self.fills.items()
        }
        data["dot_colors"] = {
            f"{h.q},{h.r}": color.name() for h, color in self.dot_colors.items()
        }
        data["coord_colors"] = {
            f"{h.q},{h.r}": color.name() for h, color in self.coord_colors.items()
        }
        if self.textures:
            data["textures"] = {
                f"{h.q},{h.r}": tex.serialize()
                for h, tex in self.textures.items()
            }
        if self.edge_fills:
            data["edge_fills"] = {
                f"{h.q},{h.r}": ef.serialize()
                for h, ef in self.edge_fills.items()
            }
        return data

    @classmethod
    def deserialize(cls, data: dict) -> FillLayer:
        layer = cls(data.get("name", "Fill"))
        layer._base_deserialize(data)
        for key, color_str in data.get("hexes", {}).items():
            q, r = map(int, key.split(","))
            layer.fills[Hex(q, r)] = QColor(color_str)
        for key, color_str in data.get("dot_colors", {}).items():
            q, r = map(int, key.split(","))
            layer.dot_colors[Hex(q, r)] = QColor(color_str)
        for key, color_str in data.get("coord_colors", {}).items():
            q, r = map(int, key.split(","))
            layer.coord_colors[Hex(q, r)] = QColor(color_str)
        for key, tex_data in data.get("textures", {}).items():
            q, r = map(int, key.split(","))
            layer.textures[Hex(q, r)] = HexTexture.deserialize(tex_data)
        for key, ef_data in data.get("edge_fills", {}).items():
            q, r = map(int, key.split(","))
            layer.edge_fills[Hex(q, r)] = HexEdgeFill.deserialize(ef_data)
        return layer
