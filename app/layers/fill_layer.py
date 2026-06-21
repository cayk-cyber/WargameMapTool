"""Fill layer - colors or textures individual hexes."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QPolygonF, QRadialGradient, QTransform,
)

import math
import random as _random

import numpy as np

from app.hex.hex_math import (
    Hex,
    Layout,
    axial_to_offset,
    hex_corners,
    hex_edge_key,
    hex_edge_vertices,
    hex_neighbor,
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


@dataclass
class HexStipple:
    """Per-hex stipple (edge gradient) data.

    Renders a gradient band along the outer edges of a stipple region,
    fading from full color/texture at the edge to transparent.  The outer
    boundary is noise-modulated for an organic, terrain-like transition.

    When *texture_id* is set, the gradient bands are filled with a tiled
    texture instead of a flat color, using mask-based compositing.

    The *priority* field enables nested zones: a higher-priority stipple
    extends its gradient into lower-priority neighbors, but not vice versa.
    Two zones at the same priority never bleed into each other.
    """

    color: str = "#6b8c42"
    spread: float = 6.0         # Gradient width in world units (mm)
    falloff: float = 1.0        # Fraction of spread with alpha fade (0-1)
    jitter: float = 0.4         # Noise amplitude (0-1, fraction of spread)
    priority: int = 0           # Nesting level (higher = inner zone)
    inset: float = 0.0          # How far gradient extends inward into hex (mm)
    inset_falloff: float = 1.0  # Fraction of inset with alpha fade (0-1)
    texture_id: str | None = None   # None = color mode, str = texture mode
    texture_zoom: float = 1.0
    texture_rotation: float = 0.0

    def visual_key(self) -> str | tuple:
        """Hashable key for grouping and same-zone detection."""
        if self.texture_id:
            return ("tex", self.texture_id, self.texture_zoom, self.texture_rotation)
        return self.color

    def serialize(self) -> dict:
        d = {
            "color": self.color,
            "spread": self.spread,
            "falloff": self.falloff,
            "jitter": self.jitter,
            "priority": self.priority,
            "inset": self.inset,
            "inset_falloff": self.inset_falloff,
        }
        if self.texture_id is not None:
            d["texture_id"] = self.texture_id
            d["texture_zoom"] = self.texture_zoom
            d["texture_rotation"] = self.texture_rotation
        return d

    @classmethod
    def deserialize(cls, data: dict) -> HexStipple:
        return cls(
            color=data.get("color", "#6b8c42"),
            spread=data.get("spread", 6.0),
            falloff=min(1.0, max(0.0, data.get("falloff", 1.0))),
            jitter=data.get("jitter", 0.4),
            priority=data.get("priority", 0),
            inset=data.get("inset", 0.0),
            inset_falloff=min(1.0, max(0.0, data.get("inset_falloff", 1.0))),
            texture_id=data.get("texture_id"),
            texture_zoom=data.get("texture_zoom", 1.0),
            texture_rotation=data.get("texture_rotation", 0.0),
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
        self.stipples: dict[Hex, HexStipple] = {}
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

    def set_stipple(self, hex_coord: Hex, stipple: HexStipple) -> None:
        self.stipples[hex_coord] = stipple
        # Only invalidate the layer cache — stipple rendering is done
        # directly in _paint_stipples() and NOT through the color/texture
        # off-screen buffers.  Using _mark_hex_dirty() would add hexes to
        # _dirty_color_hexes, triggering an incremental color-buffer update
        # that creates visible artifacts at hex boundaries (because
        # non-dirty neighbors' expanded fill polygons overlap the cleared
        # dirty area but aren't redrawn).
        self._cache_dirty = True
        self._cache_pixmap = None

    def clear_stipple(self, hex_coord: Hex) -> HexStipple | None:
        result = self.stipples.pop(hex_coord, None)
        if result is not None:
            # Full invalidation to prevent ghost artifacts — the gradient
            # extends beyond the hex boundary so incremental dirty marking
            # is not sufficient for complete cleanup.
            self.mark_dirty()
        return result

    def get_stipple(self, hex_coord: Hex) -> HexStipple | None:
        return self.stipples.get(hex_coord)

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

        # Draw stipple (edge scatter) dots - on top of everything else
        if self.stipples:
            self._paint_stipples(painter, viewport_rect, layout)

    def _paint_stipples(
        self, painter: QPainter, viewport_rect: QRectF, layout: Layout,
    ) -> None:
        """Render stipple gradient bands along outer edges.

        For each stipple hex, find outer edges (where the neighbor has no
        stipple or a different visual identity), then draw a gradient band
        that fades from full color/texture at the edge to transparent.  The
        outer boundary is noise-modulated for an organic, terrain-like
        transition.

        Color stipples render colored gradients directly.  Texture stipples
        use a two-pass mask approach: white+alpha gradients into an alpha
        mask buffer, then composite with tiled texture via DestinationIn.

        Rendering uses a per-group temporary buffer with Lighten composition
        to prevent alpha accumulation at inner corners where bands from
        adjacent hexes overlap.  Corner fans fill the gap at outer vertices
        where two adjacent bands meet.
        """
        if not self.stipples:
            return

        from PySide6.QtGui import QImage
        from app.io.texture_cache import get_texture_image

        max_spread = max(s.spread for s in self.stipples.values())
        margin = layout.size_x + max_spread
        expanded = viewport_rect.adjusted(-margin, -margin, margin, margin)

        _N_SEG = 16          # segments along each edge for noise resolution
        _N_GRAD_STOPS = 8    # gradient color stops for falloff curve
        _N_CORNER_ARC = 8    # arc segments for corner fan

        # --- Determine temp buffer size from painter's transform ---
        xform = painter.transform()
        sx, sy = xform.m11(), xform.m22()
        # If no scale (identity), use 1.0
        if abs(sx) < 0.001:
            sx = 1.0
        if abs(sy) < 0.001:
            sy = 1.0

        dev_l = expanded.left() * sx + xform.dx()
        dev_t = expanded.top() * sy + xform.dy()
        dev_r = expanded.right() * sx + xform.dx()
        dev_b = expanded.bottom() * sy + xform.dy()
        buf_x = int(min(dev_l, dev_r)) - 1
        buf_y = int(min(dev_t, dev_b)) - 1
        buf_w = int(abs(dev_r - dev_l)) + 3
        buf_h = int(abs(dev_b - dev_t)) + 3

        # Cap to prevent huge allocations; fall back to direct render
        _MAX_PIX = 25_000_000
        use_buffer = (buf_w > 0 and buf_h > 0 and buf_w * buf_h <= _MAX_PIX)

        # Group stipples by visual identity for batch rendering
        by_key: dict[str | tuple, list[tuple[Hex, HexStipple]]] = {}
        for hc, st in self.stipples.items():
            cx, cy = hex_to_pixel(layout, hc)
            if expanded.contains(QPointF(cx, cy)):
                by_key.setdefault(st.visual_key(), []).append((hc, st))

        # Cache for hex polygon clip paths (shared across all groups)
        hex_clip_cache: dict = {}

        def _get_hex_clip(hc: Hex) -> QPainterPath:
            if hc not in hex_clip_cache:
                hcx, hcy = hex_to_pixel(layout, hc)
                crn = hex_corners(layout, hc)
                clip = QPainterPath()
                exp = 1.01  # ~1% outward to cover shared edges
                clip.moveTo(QPointF(
                    hcx + (crn[0][0] - hcx) * exp,
                    hcy + (crn[0][1] - hcy) * exp))
                for cxx, cyy in crn[1:]:
                    clip.lineTo(QPointF(
                        hcx + (cxx - hcx) * exp,
                        hcy + (cyy - hcy) * exp))
                clip.closeSubpath()
                hex_clip_cache[hc] = clip
            return hex_clip_cache[hc]

        for vis_key, entries in by_key.items():
            is_texture = isinstance(vis_key, tuple)
            # For color mode: use the actual color; for texture: white mask
            base_color = QColor(255, 255, 255) if is_texture else QColor(vis_key)

            # numpy-max compositing: each primitive drawn into band_img,
            # accumulated via np.maximum to prevent alpha overlap
            # darkening (same proven technique as hexside falloff).
            if use_buffer:
                combined = np.zeros((buf_h, buf_w, 4), dtype=np.uint8)
                band_img = QImage(
                    buf_w, buf_h,
                    QImage.Format.Format_ARGB32_Premultiplied)
            else:
                tp = painter
                tp.save()
                tp.setRenderHint(QPainter.RenderHint.Antialiasing)
                tp.setPen(Qt.PenStyle.NoPen)

            def _draw_prim(path: QPainterPath, brush: QBrush) -> None:
                """Draw a clipped primitive; numpy-max or direct.

                Uses bounding-rect optimisation: only allocates a small
                QImage covering the path's screen-space bounding box
                instead of the full buffer, reducing memory throughput
                by ~500-1000x for typical band sizes.
                """
                if path.isEmpty():
                    return
                if use_buffer:
                    # Compute screen-pixel bounding rect of the path
                    br = path.boundingRect()
                    bx1 = int(br.left() * sx + xform.dx() - buf_x) - 1
                    by1 = int(br.top() * sy + xform.dy() - buf_y) - 1
                    bx2 = int(br.right() * sx + xform.dx() - buf_x) + 2
                    by2 = int(br.bottom() * sy + xform.dy() - buf_y) + 2
                    # Clamp to buffer bounds
                    bx1 = max(0, bx1)
                    by1 = max(0, by1)
                    bx2 = min(buf_w, bx2)
                    by2 = min(buf_h, by2)
                    bw = bx2 - bx1
                    bh = by2 - by1
                    if bw <= 0 or bh <= 0:
                        return
                    # Small QImage covering only this band
                    band_img = QImage(
                        bw, bh,
                        QImage.Format.Format_ARGB32_Premultiplied)
                    band_img.fill(0)
                    bp = QPainter(band_img)
                    bp.setRenderHint(
                        QPainter.RenderHint.Antialiasing, True)
                    bp.setPen(Qt.PenStyle.NoPen)
                    bp.translate(
                        xform.dx() - buf_x - bx1,
                        xform.dy() - buf_y - by1)
                    bp.scale(sx, sy)
                    bp.setBrush(brush)
                    bp.drawPath(path)
                    bp.end()
                    stride = band_img.bytesPerLine()
                    raw = np.frombuffer(
                        band_img.constBits(), dtype=np.uint8)
                    if stride == bw * 4:
                        arr = raw.reshape(bh, bw, 4)
                    else:
                        arr = raw.reshape(
                            bh, stride
                        )[:, :bw * 4].reshape(bh, bw, 4)
                    region = combined[by1:by2, bx1:bx2]
                    np.maximum(region, arr, out=region)
                else:
                    tp.setBrush(brush)
                    tp.drawPath(path)

            # Collect vertex normals across all hexes for corner fans
            vertex_normals: dict[tuple[float, float], list] = {}

            for hex_coord, stipple in entries:
                spread = stipple.spread
                jitter = stipple.jitter
                falloff_frac = max(0.0, min(1.0, stipple.falloff))
                inset_falloff_frac = max(0.0, min(1.0, stipple.inset_falloff))

                # Determine which directions are outer edges.
                priority = stipple.priority
                vis = stipple.visual_key()
                outer_dirs: set[int] = set()
                edge_normals: dict[int, tuple[float, float]] = {}
                for direction in range(6):
                    neighbor = hex_neighbor(hex_coord, direction)
                    nb_stipple = self.stipples.get(neighbor)
                    if nb_stipple is not None:
                        if nb_stipple.visual_key() == vis:
                            continue  # same zone
                        if nb_stipple.priority >= priority:
                            continue  # peer or inner zone
                    outer_dirs.add(direction)

                    v_a, v_b = hex_edge_vertices(layout, hex_coord, direction)
                    ax, ay = v_a
                    bx, by = v_b
                    elen = math.hypot(bx - ax, by - ay)
                    if elen < 0.001:
                        continue
                    nx_r, ny_r = -(by - ay) / elen, (bx - ax) / elen
                    ncx, ncy = hex_to_pixel(layout, neighbor)
                    mid_x = (ax + bx) * 0.5
                    mid_y = (ay + by) * 0.5
                    if (ncx - mid_x) * nx_r + (ncy - mid_y) * ny_r < 0:
                        nx_r, ny_r = -nx_r, -ny_r
                    edge_normals[direction] = (nx_r, ny_r)

                # --- Draw gradient bands along outer edges ---
                inset = stipple.inset
                inner_offset = inset if inset > 0 else 0.3
                total_dist = inner_offset + spread
                t_edge = inner_offset / total_dist if total_dist > 0.001 else 0.0

                # Pre-compute gradient stop positions (even + critical)
                stop_ts: set[float] = set()
                for si in range(_N_GRAD_STOPS + 1):
                    stop_ts.add(si / _N_GRAD_STOPS)
                if inset > 0:
                    stop_ts.add(t_edge)
                    if 0 < inset_falloff_frac < 1:
                        stop_ts.add(t_edge * inset_falloff_frac)
                if 0 < falloff_frac < 1:
                    if inset > 0:
                        stop_ts.add(
                            t_edge + (1.0 - t_edge) * (1.0 - falloff_frac)
                        )
                    else:
                        stop_ts.add(1.0 - falloff_frac)
                sorted_stops = sorted(stop_ts)

                for direction in outer_dirs:
                    if direction not in edge_normals:
                        continue
                    v_a, v_b = hex_edge_vertices(layout, hex_coord, direction)
                    ax, ay = v_a
                    bx, by = v_b
                    ex, ey = bx - ax, by - ay
                    edge_len = math.hypot(ex, ey)
                    if edge_len < 0.001:
                        continue

                    nx_raw, ny_raw = edge_normals[direction]
                    mid_x = (ax + bx) * 0.5
                    mid_y = (ay + by) * 0.5

                    neighbor = hex_neighbor(hex_coord, direction)
                    edge_k = hex_edge_key(hex_coord, neighbor)
                    seed_val = hash(edge_k) & 0x7FFFFFFF
                    rng = _random.Random(seed_val)
                    rng_inner = _random.Random(seed_val ^ 0x1F2E3D4C)

                    inner_pts: list[QPointF] = []
                    outer_pts: list[QPointF] = []

                    for i in range(_N_SEG + 1):
                        t = i / _N_SEG
                        px = ax + t * ex
                        py = ay + t * ey

                        # Outer edge with jitter
                        noise = rng.uniform(-1.0, 1.0) * spread * jitter
                        outer_dist = max(0.0, spread + noise)
                        outer_pts.append(QPointF(
                            px + nx_raw * outer_dist,
                            py + ny_raw * outer_dist,
                        ))

                        # Inner edge with jitter (when inset > 0)
                        if inset > 0:
                            in_noise = (
                                rng_inner.uniform(-1.0, 1.0) * inset * jitter
                            )
                            inner_dist = max(0.0, inner_offset + in_noise)
                        else:
                            inner_dist = inner_offset
                        inner_pts.append(QPointF(
                            px - nx_raw * inner_dist,
                            py - ny_raw * inner_dist,
                        ))

                    poly_points = inner_pts + list(reversed(outer_pts))
                    polygon = QPolygonF(poly_points)

                    # Gradient: percentage-based falloff
                    grad = QLinearGradient(
                        QPointF(mid_x - nx_raw * inner_offset,
                                mid_y - ny_raw * inner_offset),
                        QPointF(mid_x + nx_raw * spread,
                                mid_y + ny_raw * spread),
                    )
                    for t in sorted_stops:
                        if inset > 0 and t <= t_edge:
                            # Inner portion: fade zone then solid
                            lt = t / t_edge if t_edge > 0 else 1.0
                            if inset_falloff_frac > 0 and lt < inset_falloff_frac:
                                alpha = int(255 * lt / inset_falloff_frac)
                            else:
                                alpha = 255
                        else:
                            # Outer portion: solid zone then fade
                            if inset > 0:
                                lt = ((t - t_edge) / (1.0 - t_edge)
                                      if (1.0 - t_edge) > 0 else 1.0)
                            else:
                                lt = t
                            s_end = 1.0 - falloff_frac
                            if lt <= s_end:
                                alpha = 255
                            elif falloff_frac > 0:
                                ft = (lt - s_end) / falloff_frac
                                alpha = int(255 * (1.0 - ft))
                            else:
                                alpha = 255
                        c = QColor(base_color)
                        c.setAlpha(max(0, min(255, alpha)))
                        grad.setColorAt(t, c)

                    # Clip band to neighbor hex boundary to prevent
                    # overflow at outer corners (same fix as falloff).
                    band_path = QPainterPath()
                    band_path.addPolygon(polygon)
                    band_path.closeSubpath()
                    band_path = band_path.intersected(
                        _get_hex_clip(neighbor))
                    _draw_prim(band_path, QBrush(grad))

                    # Collect vertex normals for corner fan generation
                    va_key = (round(ax, 1), round(ay, 1))
                    vb_key = (round(bx, 1), round(by, 1))
                    info = (nx_raw, ny_raw, spread, inner_offset,
                            falloff_frac, inset_falloff_frac, inset,
                            neighbor, hex_coord)
                    vertex_normals.setdefault(va_key, []).append(info)
                    vertex_normals.setdefault(vb_key, []).append(info)

            # --- Corner fans at ALL vertices (same-hex + cross-hex) ---
            for (vx, vy), info_list in vertex_normals.items():
                if len(info_list) < 2:
                    continue
                info_list.sort(key=lambda inf: math.atan2(inf[1], inf[0]))
                n_norms = len(info_list)

                for idx in range(n_norms):
                    ni = info_list[idx]
                    nj = info_list[(idx + 1) % n_norms]
                    n1x, n1y = ni[0], ni[1]
                    n2x, n2y = nj[0], nj[1]

                    # Angular gap (CCW from n1 to n2)
                    a1 = math.atan2(n1y, n1x)
                    a2 = math.atan2(n2y, n2x)
                    gap = a2 - a1
                    if gap < 0:
                        gap += 2 * math.pi
                    if gap > math.pi:
                        continue  # back side, skip

                    fan_spread = min(ni[2], nj[2])
                    fan_inner = min(ni[3], nj[3])
                    fan_fo = max(ni[4], nj[4])
                    fan_ifo = max(ni[5], nj[5])
                    fan_inset = min(ni[6], nj[6])

                    # --- Outer corner fan ---
                    fan_pts = [QPointF(vx, vy)]
                    for k in range(_N_CORNER_ARC + 1):
                        ta = k / _N_CORNER_ARC
                        ix = n1x + ta * (n2x - n1x)
                        iy = n1y + ta * (n2y - n1y)
                        il = math.hypot(ix, iy)
                        if il < 0.001:
                            continue
                        ix /= il
                        iy /= il
                        fan_pts.append(QPointF(
                            vx + ix * fan_spread,
                            vy + iy * fan_spread,
                        ))

                    if len(fan_pts) >= 3:
                        rgrad = QRadialGradient(
                            QPointF(vx, vy), fan_spread
                        )
                        s_end = 1.0 - fan_fo
                        for k in range(_N_GRAD_STOPS + 1):
                            tg = k / _N_GRAD_STOPS
                            if tg <= s_end:
                                a_val = 255
                            elif fan_fo > 0:
                                ft = (tg - s_end) / fan_fo
                                a_val = int(255 * (1.0 - ft))
                            else:
                                a_val = 255
                            c = QColor(base_color)
                            c.setAlpha(max(0, min(255, a_val)))
                            rgrad.setColorAt(tg, c)
                        # Clip outer fan to union of adjacent neighbor
                        # hexes to prevent overflow at outer corners.
                        fan_path = QPainterPath()
                        fan_path.addPolygon(QPolygonF(fan_pts))
                        fan_path.closeSubpath()
                        fan_path = fan_path.intersected(
                            _get_hex_clip(ni[7]).united(
                                _get_hex_clip(nj[7])))
                        _draw_prim(fan_path, QBrush(rgrad))

                    # --- Inner corner fan ---
                    if fan_inset > 0:
                        in_fan_pts = [QPointF(vx, vy)]
                        for k in range(_N_CORNER_ARC + 1):
                            ta = k / _N_CORNER_ARC
                            ix = -n1x + ta * (-n2x + n1x)
                            iy = -n1y + ta * (-n2y + n1y)
                            il = math.hypot(ix, iy)
                            if il < 0.001:
                                continue
                            ix /= il
                            iy /= il
                            in_fan_pts.append(QPointF(
                                vx + ix * fan_inner,
                                vy + iy * fan_inner,
                            ))

                        if len(in_fan_pts) >= 3:
                            irgrad = QRadialGradient(
                                QPointF(vx, vy), fan_inner,
                            )
                            s_end_i = 1.0 - fan_ifo
                            for k in range(_N_GRAD_STOPS + 1):
                                tg = k / _N_GRAD_STOPS
                                if tg <= s_end_i:
                                    a_val = 255
                                elif fan_ifo > 0:
                                    ft = (tg - s_end_i) / fan_ifo
                                    a_val = int(255 * (1.0 - ft))
                                else:
                                    a_val = 255
                                c = QColor(base_color)
                                c.setAlpha(max(0, min(255, a_val)))
                                irgrad.setColorAt(tg, c)
                            # Clip inner fan to union of adjacent source
                            # hexes to prevent overlap accumulation.
                            in_fan_path = QPainterPath()
                            in_fan_path.addPolygon(QPolygonF(in_fan_pts))
                            in_fan_path.closeSubpath()
                            in_fan_path = in_fan_path.intersected(
                                _get_hex_clip(ni[8]).united(
                                    _get_hex_clip(nj[8])))
                            _draw_prim(in_fan_path, QBrush(irgrad))

            # Composite accumulated result onto main painter
            if use_buffer:
                if not combined.any():
                    continue
                result_data = combined.tobytes()
                result_img = QImage(
                    result_data, buf_w, buf_h, buf_w * 4,
                    QImage.Format.Format_ARGB32_Premultiplied)
                if is_texture:
                    tex_id = vis_key[1]  # ("tex", id, zoom, rot)
                    tex_zoom = vis_key[2]
                    tex_rot = vis_key[3]
                    tex_img = get_texture_image(tex_id)
                    if tex_img is not None:
                        tex_buf = QImage(
                            buf_w, buf_h,
                            QImage.Format.Format_ARGB32_Premultiplied,
                        )
                        tex_buf.fill(0)
                        tp2 = QPainter(tex_buf)
                        pix = QPixmap.fromImage(tex_img)
                        brush = QBrush(pix)
                        bxf = QTransform()
                        bxf.translate(
                            xform.dx() - buf_x, xform.dy() - buf_y)
                        bxf.scale(sx, sy)
                        if tex_zoom != 1.0:
                            bxf.scale(tex_zoom, tex_zoom)
                        if tex_rot != 0.0:
                            bxf.rotate(tex_rot)
                        brush.setTransform(bxf)
                        tp2.fillRect(tex_buf.rect(), brush)
                        tp2.setCompositionMode(
                            QPainter.CompositionMode.CompositionMode_DestinationIn
                        )
                        tp2.drawImage(0, 0, result_img)
                        tp2.end()
                        painter.save()
                        painter.resetTransform()
                        painter.drawImage(buf_x, buf_y, tex_buf)
                        painter.restore()
                else:
                    painter.save()
                    painter.resetTransform()
                    painter.drawImage(buf_x, buf_y, result_img)
                    painter.restore()
            else:
                tp.restore()

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
        if self.stipples:
            data["stipples"] = {
                f"{h.q},{h.r}": s.serialize()
                for h, s in self.stipples.items()
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
        for key, s_data in data.get("stipples", {}).items():
            q, r = map(int, key.split(","))
            layer.stipples[Hex(q, r)] = HexStipple.deserialize(s_data)
        return layer
