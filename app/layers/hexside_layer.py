"""Hexside layer - lines drawn along hex edges (rivers, walls, hedges, etc.)."""

from __future__ import annotations

import math
import random as _random
from collections import defaultdict

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import (
    QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath,
    QPainterPathStroker, QPen, QPixmap, QTransform, Qt,
)

from app.io.texture_cache import get_texture_image

from app.hex.hex_math import (
    HEX_DIRECTIONS,
    Hex,
    Layout,
    hex_corners,
    hex_edge_key,
    hex_edge_vertices,
    hex_to_pixel,
)
from app.layers.base_layer import Layer
from app.layers.fill_layer import HexTexture
from app.models.hexside_object import HexsideObject


def hex_vertex_endpoint_offset(vx: float, vy: float, amplitude: float) -> tuple[float, float]:
    """Deterministic hash-based displacement for a hex vertex position.

    Uses the pixel position (at 0.1-pixel precision) as hash input so that
    all hexsides meeting at the same vertex share the same displacement when
    given the same amplitude, preserving visual connectivity.
    """
    if amplitude <= 0:
        return (0.0, 0.0)
    vxi = round(vx * 10)
    vyi = round(vy * 10)
    hash_val = ((vxi * 73856093) ^ (vyi * 19349663)) & 0x7FFFFFFF
    rng = _random.Random(hash_val)
    angle = rng.uniform(0, 2 * math.pi)
    raw = rng.gauss(0, 0.6)
    raw = max(-1.5, min(1.5, raw))
    return (raw * amplitude * math.cos(angle), raw * amplitude * math.sin(angle))


class HexsideLayer(Layer):
    clip_to_grid = True

    @property
    def cacheable(self) -> bool:
        """Screen-res cache when sharp lines or texture quality is on."""
        from app.layers import fill_layer as _fl
        return not Layer._sharp_lines and not _fl._quality_mode

    def __init__(self, name: str = "Hexside"):
        super().__init__(name)
        # Dict keyed by canonical edge key: ((q_a, r_a), (q_b, r_b))
        self.hexsides: dict[tuple[tuple[int, int], tuple[int, int]], HexsideObject] = {}
        # Fill context for auto-shift and texture matching (set before paint)
        self._fill_colors: dict[tuple[int, int], str] = {}  # (q,r) -> color hex string
        self._fill_textures: dict[tuple[int, int], HexTexture] = {}  # (q,r) -> full HexTexture
        # QPainterPath cache: edge_key -> (params_tuple, QPainterPath)
        # Self-validating: cache entry is used only when params_tuple matches current params.
        # Not cleared on mark_dirty() so undragged objects keep their cached paths during drag.
        self._path_cache: dict = {}
        # Layer-level drop shadow
        self.shadow_enabled: bool = False
        self.shadow_type: str = "outer"  # "outer" or "inner"
        self.shadow_color: str = "#000000"
        self.shadow_opacity: float = 0.5
        self.shadow_angle: float = 120.0
        self.shadow_distance: float = 5.0
        self.shadow_spread: float = 0.0
        self.shadow_size: float = 5.0

        # Layer-level bevel & emboss
        self.bevel_enabled: bool = False
        self.bevel_type: str = "inner"  # "inner" or "outer"
        self.bevel_angle: float = 120.0
        self.bevel_size: float = 3.0
        self.bevel_depth: float = 0.5
        self.bevel_highlight_color: str = "#ffffff"
        self.bevel_highlight_opacity: float = 0.75
        self.bevel_shadow_color: str = "#000000"
        self.bevel_shadow_opacity: float = 0.75

        # Keys hidden during interactive drag (set by tool, cleared on release)
        self._drag_hidden_keys: set = set()

        # Layer-level structure (texture bump)
        self.structure_enabled: bool = False
        self.structure_texture_id: str | None = None
        self.structure_scale: float = 1.0
        self.structure_depth: float = 50.0
        self.structure_invert: bool = False

    def set_fill_context(
        self,
        fill_colors: dict[tuple[int, int], str],
        fill_textures: dict[tuple[int, int], HexTexture],
    ) -> None:
        """Set fill data from visible FillLayers for auto-shift and texture matching."""
        self._fill_colors = fill_colors
        self._fill_textures = fill_textures

    def add_hexside(self, obj: HexsideObject) -> None:
        self.hexsides[obj.edge_key()] = obj
        self.mark_dirty()

    def remove_hexside(self, obj: HexsideObject) -> None:
        key = obj.edge_key()
        self.hexsides.pop(key, None)
        self._path_cache.pop(key, None)
        self.mark_dirty()

    def get_hexside_at_edge(self, hex_a: Hex, hex_b: Hex) -> HexsideObject | None:
        key = hex_edge_key(hex_a, hex_b)
        return self.hexsides.get(key)

    def hit_test(
        self, world_x: float, world_y: float, layout: Layout, threshold: float = 8.0,
    ) -> HexsideObject | None:
        """Find the nearest hexside to a world point within threshold."""
        point = QPointF(world_x, world_y)
        for obj in self.hexsides.values():
            effective_shift = self._compute_effective_shift(obj)
            path = self._get_cached_hexside_path(layout, obj, effective_shift)
            if path.isEmpty():
                continue
            stroker = QPainterPathStroker()
            stroker.setWidth(max(obj.width, threshold * 2))
            stroked = stroker.createStroke(path)
            if stroked.contains(point):
                return obj
        return None

    # --- Rendering ---

    def paint(self, painter: QPainter, viewport_rect: QRectF, layout: Layout) -> None:
        gfx = self._gfx_effects_enabled
        needs_composite = (
            gfx and (self.shadow_enabled or self.bevel_enabled or self.structure_enabled)
        )
        if not needs_composite:
            self._paint_content(painter, viewport_rect, layout)
            return

        composite, screen_tl, device_scale = self._build_shadow_composite(
            painter, viewport_rect, layout, self._paint_content,
        )
        if composite is None:
            self._paint_content(painter, viewport_rect, layout)
            return

        # Apply structure to a copy (must not modify composite in place)
        display = composite
        if self.structure_enabled and self.structure_texture_id:
            display = self._apply_structure_to_composite(composite)

        painter.save()
        painter.resetTransform()
        sx, sy = screen_tl.x(), screen_tl.y()

        # Outer effects (behind composite)
        if self.shadow_enabled and self.shadow_type == "outer":
            self._paint_outer_shadow(painter, composite, screen_tl, device_scale)
        if self.bevel_enabled and self.bevel_type == "outer":
            self._paint_outer_bevel(
                painter, composite, sx, sy, device_scale,
            )

        # Composite (with structure baked in)
        painter.drawImage(screen_tl, display)

        # Inner effects (over composite)
        if self.bevel_enabled and self.bevel_type == "inner":
            self._paint_inner_bevel(
                painter, composite, sx, sy, device_scale,
            )
        if self.shadow_enabled and self.shadow_type == "inner":
            self._paint_inner_shadow(painter, composite, screen_tl, device_scale)

        painter.restore()

    def _paint_content(self, painter: QPainter, viewport_rect: QRectF, layout: Layout) -> None:
        margin = layout.size_x * 2
        expanded = viewport_rect.adjusted(-margin, -margin, margin, margin)

        # Collect visible hexsides and pre-compute paths
        hidden = self._drag_hidden_keys
        visible: list[tuple[HexsideObject, QPainterPath]] = []
        for obj in self.hexsides.values():
            if hidden and obj.edge_key() in hidden:
                continue
            cx_a, cy_a = hex_to_pixel(layout, obj.hex_a())
            cx_b, cy_b = hex_to_pixel(layout, obj.hex_b())
            mid_x = (cx_a + cx_b) / 2
            mid_y = (cy_a + cy_b) / 2
            if not expanded.contains(QPointF(mid_x, mid_y)):
                continue
            effective_shift = self._compute_effective_shift(obj)
            path = self._get_cached_hexside_path(layout, obj, effective_shift)
            if not path.isEmpty():
                visible.append((obj, path))

        # Taper: build vertex connectivity map when any hexside uses taper
        any_taper = any(obj.taper for obj, _ in visible)
        vertex_counts: dict[tuple[int, int], int] = {}
        if any_taper:
            vertex_counts = self._build_vertex_counts(layout)

        # Pre-compute taper info per visible hexside: (taper_start, taper_end, taper_length)
        taper_info: dict = {}
        if any_taper:
            for obj, _ in visible:
                if not obj.taper:
                    continue
                direction = self._find_direction(obj)
                if direction is None:
                    continue
                v1, v2 = hex_edge_vertices(layout, obj.hex_a(), direction)
                k1 = (round(v1[0] * 10), round(v1[1] * 10))
                k2 = (round(v2[0] * 10), round(v2[1] * 10))
                ts = vertex_counts.get(k1, 0) <= 1
                te = vertex_counts.get(k2, 0) <= 1
                taper_info[obj.edge_key()] = (ts, te, obj.taper_length)

        # Three-pass rendering: falloff bands, outlines, main lines.

        # Pass 0: All falloff bands (below outlines and main lines)
        # Group by target hex so overlapping bands don't darken additively.
        self._paint_all_falloffs(painter, layout, visible)

        # Pass 1: All outlines
        for obj, path in visible:
            if not obj.outline:
                continue
            ts, te, tl = taper_info.get(obj.edge_key(), (False, False, 0.5))
            painter.save()
            if obj.outline_opacity < 1.0:
                painter.setOpacity(obj.outline_opacity)
            self._paint_outline(painter, layout, obj, path, ts, te, tl)
            painter.restore()

        # Pass 2: All main lines (on top of all outlines)
        for obj, path in visible:
            ts, te, tl = taper_info.get(obj.edge_key(), (False, False, 0.5))
            painter.save()
            if obj.opacity < 1.0:
                painter.setOpacity(obj.opacity)
            if obj.texture_id:
                self._paint_textured_line(painter, path, obj, ts, te, tl)
            elif obj.random and obj.random_jitter > 0:
                self._draw_path_with_jitter(
                    painter, path, obj.width, QColor(obj.color),
                    obj.random_jitter, obj.random_seed,
                    taper_start=ts, taper_end=te, taper_length=tl,
                )
            elif ts or te:
                # No jitter/texture but taper active: use segment renderer
                self._draw_path_with_jitter(
                    painter, path, obj.width, QColor(obj.color),
                    0.0, 0,
                    taper_start=ts, taper_end=te, taper_length=tl,
                )
            else:
                pen = QPen(QColor(obj.color), obj.width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            painter.restore()

        # Pass 3: All teeth decorators (on top of lines)
        self._paint_all_teeth(painter, layout, visible)

    def _paint_all_teeth(
        self, painter: QPainter, layout: Layout,
        visible: list[tuple],
    ) -> None:
        """Draw triangular teeth decorators along hexside paths."""
        for obj, path in visible:
            if not obj.teeth_side:
                continue

            count = max(1, obj.teeth_count)
            side_len = obj.teeth_size
            half_base = side_len * 0.5        # equilateral: base = side length
            height = side_len * 0.8660254     # sqrt(3)/2 ≈ 0.866

            # Get edge normal (from hex_a toward hex_b)
            nx, ny = self._get_edge_normal(layout, obj.hex_a(), obj.hex_b())

            painter.save()
            if obj.teeth_opacity < 1.0:
                painter.setOpacity(obj.teeth_opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(obj.teeth_color))

            for i in range(count):
                t = (i + 0.5) / count
                pt = path.pointAtPercent(t)

                # Tangent via finite difference
                dt = 0.01
                t1 = max(0.0, t - dt)
                t2 = min(1.0, t + dt)
                p1 = path.pointAtPercent(t1)
                p2 = path.pointAtPercent(t2)
                tang_x = p2.x() - p1.x()
                tang_y = p2.y() - p1.y()
                tang_len = math.hypot(tang_x, tang_y)
                if tang_len < 1e-9:
                    continue
                tang_x /= tang_len
                tang_y /= tang_len

                # Perpendicular: orient toward hex_b by default
                perp_x, perp_y = -tang_y, tang_x
                dot = perp_x * nx + perp_y * ny
                if dot < 0:
                    perp_x, perp_y = -perp_x, -perp_y
                # Flip if teeth point toward hex_a
                if obj.teeth_side == "a":
                    perp_x, perp_y = -perp_x, -perp_y

                # Equilateral triangle vertices
                bx1 = pt.x() - tang_x * half_base
                by1 = pt.y() - tang_y * half_base
                bx2 = pt.x() + tang_x * half_base
                by2 = pt.y() + tang_y * half_base
                ax = pt.x() + perp_x * height
                ay = pt.y() + perp_y * height

                tri = QPainterPath()
                tri.moveTo(bx1, by1)
                tri.lineTo(bx2, by2)
                tri.lineTo(ax, ay)
                tri.closeSubpath()
                painter.drawPath(tri)

            painter.restore()

    def _paint_outline(
        self, painter: QPainter, layout: Layout, obj: HexsideObject, path: QPainterPath,
        taper_start: bool = False, taper_end: bool = False, taper_length: float = 0.5,
    ) -> None:
        """Draw the outline for a single hexside.

        Two-pass rendering (all outlines first, then all main lines) ensures
        that no outline can cover another hexside's main line. RoundCap
        provides natural joining at shared vertices.
        Supports both solid-color and textured outlines.
        """
        total_width = obj.width + obj.outline_width * 2

        # Textured outline
        if obj.outline_texture_id:
            brush = self._make_texture_brush(
                obj.outline_texture_id,
                obj.outline_texture_zoom,
                obj.outline_texture_rotation,
            )
            if brush is not None:
                if obj.random and obj.random_jitter > 0:
                    self._draw_textured_path_with_jitter(
                        painter, path, obj.width, brush,
                        obj.random_jitter, obj.random_seed,
                        width_offset=obj.outline_width * 2,
                        taper_start=taper_start, taper_end=taper_end,
                        taper_length=taper_length,
                    )
                elif taper_start or taper_end:
                    self._draw_textured_path_with_jitter(
                        painter, path, obj.width, brush,
                        0.0, 0,
                        width_offset=obj.outline_width * 2,
                        taper_start=taper_start, taper_end=taper_end,
                        taper_length=taper_length,
                    )
                else:
                    stroker = QPainterPathStroker()
                    stroker.setWidth(total_width)
                    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
                    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    stroked = stroker.createStroke(path)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(brush)
                    painter.drawPath(stroked)
                return

        # Solid-color outline (default)
        if obj.random and obj.random_jitter > 0:
            self._draw_path_with_jitter(
                painter, path, obj.width, QColor(obj.outline_color),
                obj.random_jitter, obj.random_seed,
                width_offset=obj.outline_width * 2,
                taper_start=taper_start, taper_end=taper_end,
                taper_length=taper_length,
            )
        elif taper_start or taper_end:
            self._draw_path_with_jitter(
                painter, path, obj.width, QColor(obj.outline_color),
                0.0, 0,
                width_offset=obj.outline_width * 2,
                taper_start=taper_start, taper_end=taper_end,
                taper_length=taper_length,
            )
        else:
            ol_pen = QPen(QColor(obj.outline_color), total_width)
            ol_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            ol_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(ol_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _find_direction(self, obj: HexsideObject) -> int | None:
        """Find the direction index from hex_a to hex_b."""
        dq = obj.hex_b_q - obj.hex_a_q
        dr = obj.hex_b_r - obj.hex_a_r
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

    def _compute_effective_shift(self, obj: HexsideObject) -> float:
        """Compute the signed shift value with auto-direction detection.

        Positive = toward hex_b, negative = toward hex_a.
        Auto-detects which adjacent hex has a matching fill color/texture
        and shifts AWAY from it.
        """
        if obj.shift == 0.0:
            return 0.0

        ha = (obj.hex_a_q, obj.hex_a_r)
        hb = (obj.hex_b_q, obj.hex_b_r)

        if obj.texture_id:
            # Textured hexside: match by texture_id — shift away from match
            ft_b = self._fill_textures.get(hb)
            if ft_b and ft_b.texture_id == obj.texture_id:
                return -obj.shift  # Away from hex_b
            ft_a = self._fill_textures.get(ha)
            if ft_a and ft_a.texture_id == obj.texture_id:
                return obj.shift  # Away from hex_a
        else:
            # Color hexside: match by color string — shift away from match
            if self._fill_colors.get(hb) == obj.color:
                return -obj.shift  # Away from hex_b
            if self._fill_colors.get(ha) == obj.color:
                return obj.shift  # Away from hex_a

        return 0.0  # No matching neighbor

    def _paint_all_falloffs(
        self, painter: QPainter, layout: Layout,
        visible: list[tuple[HexsideObject, QPainterPath]],
    ) -> None:
        """Render all falloff bands with true per-pixel max alpha.

        Uses a screen-resolution off-screen buffer (like _paint_stipples)
        with an opaque-black background + Lighten mode to compute
        max(grayscale) per pixel.  One numpy pass converts brightness
        to premultiplied ARGB with the fill color.

        This avoids the Porter-Duff alpha accumulation that makes
        overlapping semi-transparent bands darker.
        """
        # Collect bands, grouped by source fill color
        color_groups: dict[str, list[tuple[QPainterPath, QLinearGradient, float]]] = (
            defaultdict(list)
        )
        tex_bands: list[tuple[QPainterPath, QLinearGradient, float, object]] = []
        world_bounds = QRectF()

        for obj, path in visible:
            if not obj.falloff_side or obj.falloff_width <= 0:
                continue

            if obj.falloff_side == "a":
                source_key = (obj.hex_b_q, obj.hex_b_r)
            else:
                source_key = (obj.hex_a_q, obj.hex_a_r)

            fill_color = self._fill_colors.get(source_key)
            fill_tex = self._fill_textures.get(source_key)
            if fill_color is None and fill_tex is None:
                continue

            result = self._build_falloff_shape(layout, obj, path)
            if result is None:
                continue
            strip_path, gradient, solid_end = result

            if fill_tex:
                tex_bands.append((strip_path, gradient, solid_end, fill_tex))
            elif fill_color:
                color_groups[fill_color].append((strip_path, gradient, solid_end))

            if world_bounds.isNull():
                world_bounds = strip_path.boundingRect()
            else:
                world_bounds = world_bounds.united(strip_path.boundingRect())

        if not color_groups and not tex_bands:
            return

        # Compute screen-pixel buffer size from painter's world transform
        wb = world_bounds.adjusted(-4, -4, 4, 4)
        xform = painter.transform()
        sx = xform.m11() if abs(xform.m11()) > 0.001 else 1.0
        sy = xform.m22() if abs(xform.m22()) > 0.001 else 1.0

        dev_l = wb.left() * sx + xform.dx()
        dev_t = wb.top() * sy + xform.dy()
        dev_r = wb.right() * sx + xform.dx()
        dev_b = wb.bottom() * sy + xform.dy()
        buf_x = int(min(dev_l, dev_r)) - 1
        buf_y = int(min(dev_t, dev_b)) - 1
        buf_w = int(abs(dev_r - dev_l)) + 3
        buf_h = int(abs(dev_b - dev_t)) + 3

        if buf_w <= 0 or buf_h <= 0 or buf_w * buf_h > 25_000_000:
            return

        # --- Color bands: per-group opaque-black Lighten + numpy ---
        for fill_color, bands in color_groups.items():
            self._paint_color_falloff_group(
                painter, fill_color, bands,
                xform, sx, sy, buf_x, buf_y, buf_w, buf_h,
            )

        # --- Texture bands: per-band buffer + numpy max ---
        if tex_bands:
            self._paint_texture_falloff_bands(
                painter, tex_bands,
                xform, sx, sy, buf_x, buf_y, buf_w, buf_h,
            )

    def _paint_color_falloff_group(
        self,
        painter: QPainter,
        fill_color: str,
        bands: list[tuple[QPainterPath, QLinearGradient, float]],
        xform: QTransform,
        sx: float,
        sy: float,
        buf_x: int,
        buf_y: int,
        buf_w: int,
        buf_h: int,
    ) -> None:
        """Render same-color falloff bands with true max-alpha compositing.

        Uses bounding-rect optimisation: each band is rendered into a
        small QImage covering only its screen-space bounding box, then
        accumulated via numpy per-pixel maximum.  This reduces memory
        throughput by ~500-1000x compared to full-buffer per band.
        """
        source_color = QColor(fill_color)
        transparent = QColor(source_color)
        transparent.setAlpha(0)

        combined = np.zeros((buf_h, buf_w, 4), dtype=np.uint8)

        for strip_path, gradient, solid_end in bands:
            # Compute screen-pixel bounding rect of this band
            br = strip_path.boundingRect()
            bx1 = int(br.left() * sx + xform.dx() - buf_x) - 1
            by1 = int(br.top() * sy + xform.dy() - buf_y) - 1
            bx2 = int(br.right() * sx + xform.dx() - buf_x) + 2
            by2 = int(br.bottom() * sy + xform.dy() - buf_y) + 2
            bx1 = max(0, bx1)
            by1 = max(0, by1)
            bx2 = min(buf_w, bx2)
            by2 = min(buf_h, by2)
            bw = bx2 - bx1
            bh = by2 - by1
            if bw <= 0 or bh <= 0:
                continue

            band_img = QImage(
                bw, bh, QImage.Format.Format_ARGB32_Premultiplied,
            )
            if band_img.isNull():
                continue
            band_img.fill(Qt.GlobalColor.transparent)

            bp = QPainter(band_img)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            bp.setPen(Qt.PenStyle.NoPen)
            bp.translate(
                xform.dx() - buf_x - bx1,
                xform.dy() - buf_y - by1)
            bp.scale(sx, sy)

            gradient.setColorAt(0.0, source_color)
            if solid_end > 0.01:
                gradient.setColorAt(solid_end, source_color)
            gradient.setColorAt(1.0, transparent)
            bp.setBrush(QBrush(gradient))
            bp.drawPath(strip_path)
            bp.end()

            # Per-pixel max into accumulator at the correct offset
            stride = band_img.bytesPerLine()
            raw = np.frombuffer(band_img.constBits(), dtype=np.uint8)
            if stride == bw * 4:
                arr = raw.reshape(bh, bw, 4)
            else:
                arr = raw.reshape(bh, stride)[:, :bw * 4].reshape(
                    bh, bw, 4,
                )
            region = combined[by1:by2, bx1:bx2]
            np.maximum(region, arr, out=region)

        if not combined.any():
            return

        result_data = combined.tobytes()
        result_img = QImage(
            result_data, buf_w, buf_h, buf_w * 4,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        painter.save()
        painter.resetTransform()
        painter.drawImage(buf_x, buf_y, result_img)
        painter.restore()

    def _paint_texture_falloff_bands(
        self,
        painter: QPainter,
        tex_bands: list[tuple[QPainterPath, QLinearGradient, float, object]],
        xform: QTransform,
        sx: float,
        sy: float,
        buf_x: int,
        buf_y: int,
        buf_w: int,
        buf_h: int,
    ) -> None:
        """Render texture falloff bands with bounding-rect numpy max."""
        combined = np.zeros((buf_h, buf_w, 4), dtype=np.uint8)

        for strip_path, gradient, solid_end, fill_tex in tex_bands:
            # Compute screen-pixel bounding rect of this band
            br = strip_path.boundingRect()
            bx1 = int(br.left() * sx + xform.dx() - buf_x) - 1
            by1 = int(br.top() * sy + xform.dy() - buf_y) - 1
            bx2 = int(br.right() * sx + xform.dx() - buf_x) + 2
            by2 = int(br.bottom() * sy + xform.dy() - buf_y) + 2
            bx1 = max(0, bx1)
            by1 = max(0, by1)
            bx2 = min(buf_w, bx2)
            by2 = min(buf_h, by2)
            bw = bx2 - bx1
            bh = by2 - by1
            if bw <= 0 or bh <= 0:
                continue

            band_img = QImage(
                bw, bh, QImage.Format.Format_ARGB32_Premultiplied,
            )
            if band_img.isNull():
                continue
            band_img.fill(Qt.GlobalColor.transparent)
            bp = QPainter(band_img)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            bp.setPen(Qt.PenStyle.NoPen)
            bp.translate(
                xform.dx() - buf_x - bx1,
                xform.dy() - buf_y - by1)
            bp.scale(sx, sy)

            brush = self._make_texture_brush(
                fill_tex.texture_id, fill_tex.zoom, fill_tex.rotation,
                fill_tex.offset_x, fill_tex.offset_y,
            )
            if brush:
                bp.setBrush(brush)
                bp.drawPath(strip_path)
                bp.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_DestinationIn,
                )
                gradient.setColorAt(0.0, QColor(255, 255, 255, 255))
                if solid_end > 0.01:
                    gradient.setColorAt(solid_end, QColor(255, 255, 255, 255))
                gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
                bp.setBrush(QBrush(gradient))
                bp.drawRect(strip_path.boundingRect().adjusted(-4, -4, 4, 4))
            bp.end()

            # Per-pixel max into combined at the correct offset
            stride = band_img.bytesPerLine()
            raw = np.frombuffer(band_img.constBits(), dtype=np.uint8)
            if stride == bw * 4:
                arr = raw.reshape(bh, bw, 4)
            else:
                arr = raw.reshape(bh, stride)[:, :bw * 4].reshape(
                    bh, bw, 4,
                )
            region = combined[by1:by2, bx1:bx2]
            np.maximum(region, arr, out=region)

        if combined.any():
            result_data = combined.tobytes()
            result_img = QImage(
                result_data, buf_w, buf_h, buf_w * 4,
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            painter.save()
            painter.resetTransform()
            painter.drawImage(buf_x, buf_y, result_img)
            painter.restore()

    def _build_falloff_shape(
        self, layout: Layout,
        obj: HexsideObject, hexside_path: QPainterPath,
    ) -> tuple[QPainterPath, QLinearGradient, float] | None:
        """Build the falloff polygon shape with corner fans and gradient.

        Returns (strip_path, gradient, solid_end) or None.
        """
        ha = (obj.hex_a_q, obj.hex_a_r)
        hb = (obj.hex_b_q, obj.hex_b_r)

        # Source = the hex whose fill extends into falloff_side
        if obj.falloff_side == "a":
            source_key = hb
        else:
            source_key = ha

        fill_color = self._fill_colors.get(source_key)
        fill_tex = self._fill_textures.get(source_key)
        if fill_color is None and fill_tex is None:
            return None

        # Band direction: normal pointing INTO falloff_side hex
        nx, ny = self._get_edge_normal(layout, obj.hex_a(), obj.hex_b())
        if obj.falloff_side == "a":
            band_nx, band_ny = -nx, -ny
        else:
            band_nx, band_ny = nx, ny

        # Sample the hexside path to get inner edge points
        path_len = hexside_path.length()
        if path_len <= 0:
            return None
        n_samples = max(10, min(60, int(path_len / 5)))
        inner_points: list[tuple[float, float]] = []
        for i in range(n_samples + 1):
            t = i / n_samples
            p = hexside_path.pointAtPercent(t)
            inner_points.append((p.x(), p.y()))

        fw = obj.falloff_width

        # Compute outer edge with optional organic width variation
        if obj.falloff_random > 0:
            rng = _random.Random(obj.falloff_random_seed)
            amp = obj.falloff_random
            # Damped random walk — strong steps + moderate damping for organic blobs
            raw: list[float] = []
            current = 0.0
            for _ in range(n_samples + 1):
                current += rng.gauss(0, amp * 0.6)
                current *= 0.7  # moderate mean-reversion
                current = max(-amp * 2.0, min(amp * 2.0, current))
                raw.append(current)
            # Smooth with 3-point moving average
            smoothed = list(raw)
            for i in range(1, len(smoothed) - 1):
                smoothed[i] = (raw[i - 1] + raw[i] + raw[i + 1]) / 3.0
            outer_points: list[tuple[float, float]] = [
                (ix + band_nx * max(fw * 0.1, fw + smoothed[i]),
                 iy + band_ny * max(fw * 0.1, fw + smoothed[i]))
                for i, (ix, iy) in enumerate(inner_points)
            ]
        else:
            outer_points: list[tuple[float, float]] = [
                (ix + band_nx * fw, iy + band_ny * fw)
                for ix, iy in inner_points
            ]

        # --- Corner fans: fill gaps at hex vertices ---
        # At each endpoint, sweep 55 degrees from the band normal toward the
        # outward tangent to cover the ~60 degree gap between adjacent bands.
        n_fan = 4
        fan_sweep = math.radians(55)
        base_angle = math.atan2(band_ny, band_nx)

        # Start vertex fan
        if len(inner_points) >= 2:
            vx, vy = inner_points[0]
            tx = inner_points[0][0] - inner_points[1][0]
            ty = inner_points[0][1] - inner_points[1][1]
            tangent_angle = math.atan2(ty, tx)
            delta = tangent_angle - base_angle
            while delta > math.pi:
                delta -= 2 * math.pi
            while delta < -math.pi:
                delta += 2 * math.pi
            sweep_dir = math.copysign(fan_sweep, delta)

            start_fan = []
            for i in range(n_fan, 0, -1):
                angle = base_angle + sweep_dir * (i / n_fan)
                start_fan.append((
                    vx + math.cos(angle) * fw,
                    vy + math.sin(angle) * fw,
                ))
            outer_points = start_fan + outer_points

        # End vertex fan
        if len(inner_points) >= 2:
            vx, vy = inner_points[-1]
            tx = inner_points[-1][0] - inner_points[-2][0]
            ty = inner_points[-1][1] - inner_points[-2][1]
            tangent_angle = math.atan2(ty, tx)
            delta = tangent_angle - base_angle
            while delta > math.pi:
                delta -= 2 * math.pi
            while delta < -math.pi:
                delta += 2 * math.pi
            sweep_dir = math.copysign(fan_sweep, delta)

            end_fan = []
            for i in range(1, n_fan + 1):
                angle = base_angle + sweep_dir * (i / n_fan)
                end_fan.append((
                    vx + math.cos(angle) * fw,
                    vy + math.sin(angle) * fw,
                ))
            outer_points = outer_points + end_fan

        # Build closed polygon: inner edge forward + outer edge reversed
        strip_path = QPainterPath()
        strip_path.moveTo(QPointF(inner_points[0][0], inner_points[0][1]))
        for px, py in inner_points[1:]:
            strip_path.lineTo(QPointF(px, py))
        for px, py in reversed(outer_points):
            strip_path.lineTo(QPointF(px, py))
        strip_path.closeSubpath()

        # Gradient: from inner edge (opaque) to outer edge (transparent)
        inner_mid_x = sum(p[0] for p in inner_points) / len(inner_points)
        inner_mid_y = sum(p[1] for p in inner_points) / len(inner_points)
        grad_start = QPointF(inner_mid_x, inner_mid_y)
        grad_end = QPointF(
            inner_mid_x + band_nx * fw,
            inner_mid_y + band_ny * fw,
        )

        gradient = QLinearGradient(grad_start, grad_end)
        solid_end = 1.0 - obj.falloff_amount

        # Clip to target hex boundary so bands never overflow into
        # adjacent hexes (prevents overlap darkening at outer corners).
        # Expand the clip polygon by ~0.5 px outward so the shared
        # hexside edge (which sits exactly on the hex boundary) is
        # reliably inside the clip — QPainterPath.intersected() can
        # discard geometry that lies exactly on a shared edge.
        target = obj.hex_a() if obj.falloff_side == "a" else obj.hex_b()
        tcx, tcy = hex_to_pixel(layout, target)
        corners = hex_corners(layout, target)
        hex_clip = QPainterPath()
        expand = 1.01  # ~1 % outward to cover the shared edge
        c0x = tcx + (corners[0][0] - tcx) * expand
        c0y = tcy + (corners[0][1] - tcy) * expand
        hex_clip.moveTo(QPointF(c0x, c0y))
        for cx, cy in corners[1:]:
            hex_clip.lineTo(QPointF(tcx + (cx - tcx) * expand,
                                    tcy + (cy - tcy) * expand))
        hex_clip.closeSubpath()
        strip_path = strip_path.intersected(hex_clip)

        return strip_path, gradient, solid_end

    def _build_vertex_counts(self, layout: Layout) -> dict[tuple[int, int], int]:
        """Count how many hexsides meet at each hex vertex.

        Uses rounded pixel coordinates (×10) as keys for vertex identity,
        matching the precision in hex_vertex_endpoint_offset().
        """
        counts: dict[tuple[int, int], int] = {}
        for obj in self.hexsides.values():
            direction = self._find_direction(obj)
            if direction is None:
                continue
            v1, v2 = hex_edge_vertices(layout, obj.hex_a(), direction)
            for vx, vy in (v1, v2):
                key = (round(vx * 10), round(vy * 10))
                counts[key] = counts.get(key, 0) + 1
        return counts

    def _get_cached_hexside_path(
        self, layout: Layout, obj: HexsideObject, effective_shift: float,
    ) -> QPainterPath:
        """Return a cached QPainterPath, recomputing only when any parameter changes.

        The cache is self-validating: each entry stores a params-tuple alongside the
        path. If params match the current object state the cached path is returned
        directly, so only the one object being dragged is recomputed each frame.
        """
        cache_key = (
            layout.size_x, layout.size_y,
            obj.hex_a_q, obj.hex_a_r, obj.hex_b_q, obj.hex_b_r,
            obj.ep_a[0], obj.ep_a[1], obj.ep_b[0], obj.ep_b[1],
            obj.ip_a[0], obj.ip_a[1], obj.ip_b[0], obj.ip_b[1],
            tuple(obj.control_points),
            obj.random, obj.random_seed,
            obj.random_amplitude, obj.random_distance, obj.random_endpoint, obj.random_offset,
            effective_shift,
        )
        obj_key = obj.edge_key()
        entry = self._path_cache.get(obj_key)
        if entry is not None and entry[0] == cache_key:
            return entry[1]
        path = self._compute_hexside_path(layout, obj, shift_override=effective_shift)
        self._path_cache[obj_key] = (cache_key, path)
        return path

    def _compute_hexside_path(
        self, layout: Layout, obj: HexsideObject,
        shift_override: float | None = None,
    ) -> QPainterPath:
        """Compute the full QPainterPath for a hexside including shift, control points, random."""
        direction = self._find_direction(obj)
        if direction is None:
            return QPainterPath()

        v1, v2 = hex_edge_vertices(layout, obj.hex_a(), direction)
        nx, ny = self._get_edge_normal(layout, obj.hex_a(), obj.hex_b())

        # Apply shift to endpoints
        shift = shift_override if shift_override is not None else obj.shift
        sx, sy = shift * nx, shift * ny

        # Compute base vertex positions (shift applied, optional random_endpoint displacement)
        base_v1 = (v1[0] + sx, v1[1] + sy)
        base_v2 = (v2[0] + sx, v2[1] + sy)

        if obj.random and obj.random_endpoint > 0:
            dv1 = hex_vertex_endpoint_offset(v1[0], v1[1], obj.random_endpoint)
            dv2 = hex_vertex_endpoint_offset(v2[0], v2[1], obj.random_endpoint)
            base_v1 = (base_v1[0] + dv1[0], base_v1[1] + dv1[1])
            base_v2 = (base_v2[0] + dv2[0], base_v2[1] + dv2[1])

        # Recompute edge vector from (possibly displaced) base vertices
        ex = base_v2[0] - base_v1[0]
        ey = base_v2[1] - base_v1[1]
        edge_len = math.hypot(ex, ey)
        if edge_len == 0:
            return QPainterPath()
        tx, ty = ex / edge_len, ey / edge_len
        perp_x, perp_y = -ty, tx
        dot = perp_x * nx + perp_y * ny
        if dot < 0:
            perp_x, perp_y = -perp_x, -perp_y

        # Build point list from all control points (including start/end vertices)
        # t-positions may be randomized by distance parameter
        t_positions = obj.cp_t_positions()
        points: list[tuple[float, float]] = []
        num_cp = len(obj.control_points)
        for i in range(num_cp):
            if i == 0:
                # Endpoint A: 2D free offset (ep_a) from base vertex
                points.append((base_v1[0] + obj.ep_a[0], base_v1[1] + obj.ep_a[1]))
            elif i == num_cp - 1:
                # Endpoint B: 2D free offset (ep_b) from base vertex
                points.append((base_v2[0] + obj.ep_b[0], base_v2[1] + obj.ep_b[1]))
            else:
                t = t_positions[i]
                base_x = base_v1[0] + ex * t
                base_y = base_v1[1] + ey * t
                # Each inner CP gets an independent random perpendicular offset
                # (seed varies per control point index so ip_a and ip_b differ)
                if obj.random_offset != 0.0:
                    rng = _random.Random(obj.random_seed + 11111 * i)
                    off = rng.uniform(-obj.random_offset, obj.random_offset)
                    base_x += perp_x * off
                    base_y += perp_y * off
                # Inner points use free 2D offsets (ip_a at i=1, ip_b at i=2)
                ip = obj.ip_a if i == 1 else obj.ip_b
                points.append((base_x + ip[0], base_y + ip[1]))

        # Add random waviness if enabled (amplitude only — jitter affects width, not path)
        if obj.random and obj.random_amplitude > 0:
            points = self._add_random_waviness(
                points, obj.random_seed, obj.random_amplitude,
                perp_x, perp_y,
            )

        # Build smooth path. Force endpoint tangents along the straight edge direction
        # so hexsides depart/arrive predictably at shared vertices, preventing kinks.
        return self._catmull_rom_path(points, entry_tangent=(tx, ty), exit_tangent=(tx, ty))

    @staticmethod
    def _add_random_waviness(
        base_points: list[tuple[float, float]],
        seed: int,
        amplitude: float,
        perp_x: float,
        perp_y: float,
    ) -> list[tuple[float, float]]:
        """Add random waviness between base points via damped random walk.

        Places knot points per segment producing organic flowing curves
        (like a river). Catmull-Rom smooths them further.
        """
        rng = _random.Random(seed)
        n_segments = len(base_points) - 1
        if n_segments < 1:
            return list(base_points)

        pts_per_seg = 4  # More points = more organic, blob-like curves
        total_pts = n_segments * pts_per_seg

        # Damped random walk: strong step + gentle damping = large, organic deviations
        amp_offsets: list[float] = []
        current = 0.0
        for _ in range(total_pts):
            current += rng.gauss(0, amplitude * 1.8)
            current *= 0.65  # Gentle mean reversion — allows bigger blobs
            current = max(-amplitude * 3.5, min(amplitude * 3.5, current))
            amp_offsets.append(current)

        result: list[tuple[float, float]] = []
        idx = 0
        for i in range(n_segments):
            x1, y1 = base_points[i]
            x2, y2 = base_points[i + 1]
            result.append((x1, y1))

            for j in range(pts_per_seg):
                t = (j + 1) / (pts_per_seg + 1)
                mx = x1 + (x2 - x1) * t
                my = y1 + (y2 - y1) * t
                off = amp_offsets[idx]
                idx += 1
                result.append((mx + perp_x * off, my + perp_y * off))

        result.append(base_points[-1])
        return result

    @staticmethod
    def _catmull_rom_path(
        points: list[tuple[float, float]],
        entry_tangent: tuple[float, float] | None = None,
        exit_tangent: tuple[float, float] | None = None,
    ) -> QPainterPath:
        """Build a smooth QPainterPath through points using Catmull-Rom interpolation.

        ``entry_tangent`` / ``exit_tangent``: optional forced unit tangent vectors at the
        first / last point.  Overrides the default phantom-point boundary condition.
        Pass the straight edge direction to prevent kinks at shared vertices.
        """
        path = QPainterPath()
        if len(points) < 2:
            return path

        if len(points) == 2:
            path.moveTo(QPointF(points[0][0], points[0][1]))
            path.lineTo(QPointF(points[1][0], points[1][1]))
            return path

        path.moveTo(QPointF(points[0][0], points[0][1]))

        # Build phantom points at start and end.
        # If forced tangents are provided, position the phantom so that the
        # Catmull-Rom tangent at the first/last real point aligns with the
        # desired direction (phantom = real - tangent * first_segment_length).
        if entry_tangent is not None:
            seg01 = math.hypot(points[1][0] - points[0][0], points[1][1] - points[0][1])
            phantom_s: tuple[float, float] = (
                points[0][0] - entry_tangent[0] * seg01,
                points[0][1] - entry_tangent[1] * seg01,
            )
        else:
            phantom_s = points[0]

        if exit_tangent is not None:
            seg_last = math.hypot(points[-1][0] - points[-2][0], points[-1][1] - points[-2][1])
            phantom_e: tuple[float, float] = (
                points[-1][0] + exit_tangent[0] * seg_last,
                points[-1][1] + exit_tangent[1] * seg_last,
            )
        else:
            phantom_e = points[-1]

        pts = [phantom_s] + list(points) + [phantom_e]

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

    @staticmethod
    def _draw_path_with_jitter(
        painter: QPainter, path: QPainterPath,
        base_width: float, color: QColor, jitter: float, seed: int,
        width_offset: float = 0.0, num_segments: int = 30,
        taper_start: bool = False, taper_end: bool = False,
        taper_length: float = 0.5,
    ) -> None:
        """Draw a path with varying width (jitter modulates line thickness).

        Args:
            base_width: The nominal line width.
            color: Line color.
            jitter: Strength of width variation (world pixels).
            seed: Random seed for reproducible variation.
            width_offset: Constant addition per side (used for outlines).
            num_segments: Ignored; computed adaptively from path length.
            taper_start: Taper the start of the path to zero width.
            taper_end: Taper the end of the path to zero width.
            taper_length: Fraction of path over which to taper (0.1–1.0).
        """
        if path.isEmpty() or path.length() == 0:
            return

        # Adaptive segment count: 1 segment per 10 world pixels, clamped to [5, 30]
        # Use more segments when taper is active for smoother width transitions
        path_len = path.length()
        has_taper = taper_start or taper_end
        seg_max = 60 if has_taper else 30
        num_segments = max(5, min(seg_max, int(path_len / (5 if has_taper else 10))))

        rng = _random.Random(seed + 77777)  # Offset from amplitude seed

        # Generate raw width variations
        raw = []
        for _ in range(num_segments + 1):
            noise = rng.gauss(0, jitter) if jitter > 0 else 0.0
            w = base_width + noise
            raw.append(w)

        # Clamp to minimum 15% of base width
        min_w = base_width * 0.15
        raw = [max(min_w, w) for w in raw]

        # Smooth with 3-point moving average for natural transitions
        widths = list(raw)
        for i in range(1, len(widths) - 1):
            widths[i] = (raw[i - 1] + raw[i] + raw[i + 1]) / 3.0

        # Apply taper factors using smoothstep (3x²−2x³) for curved transitions
        if has_taper:
            for i in range(num_segments + 1):
                t = i / num_segments
                factor = 1.0
                if taper_start and t < taper_length:
                    x = t / taper_length if taper_length > 0 else 0.0
                    factor *= x * x * (3.0 - 2.0 * x)
                if taper_end and t > (1.0 - taper_length):
                    x = (1.0 - t) / taper_length if taper_length > 0 else 0.0
                    factor *= x * x * (3.0 - 2.0 * x)
                widths[i] *= factor

        # Draw each segment with its local width
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(num_segments):
            t0 = i / num_segments
            t1 = (i + 1) / num_segments
            p0 = path.pointAtPercent(t0)
            p1 = path.pointAtPercent(t1)
            w = (widths[i] + widths[i + 1]) / 2.0 + width_offset
            pen = QPen(color, max(w, 0.5))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(p0, p1)

    # --- Texture rendering ---

    @staticmethod
    def _make_texture_brush(
        texture_id: str, zoom: float, rotation: float,
        offset_x: float = 0.0, offset_y: float = 0.0,
    ) -> QBrush | None:
        """Create a textured QBrush from a texture library ID."""
        image = get_texture_image(texture_id)
        if image is None:
            return None
        brush = QBrush(QPixmap.fromImage(image))
        if offset_x != 0.0 or offset_y != 0.0 or zoom != 1.0 or rotation != 0.0:
            xf = QTransform()
            if offset_x != 0.0 or offset_y != 0.0:
                xf.translate(offset_x, offset_y)
            if rotation != 0.0:
                xf.rotate(rotation)
            if zoom != 1.0:
                xf.scale(zoom, zoom)
            brush.setTransform(xf)
        return brush

    def _find_matching_fill_texture(self, obj: HexsideObject) -> HexTexture | None:
        """Find a fill texture from an adjacent hex that matches this hexside's texture."""
        if not obj.texture_id:
            return None
        ha = (obj.hex_a_q, obj.hex_a_r)
        hb = (obj.hex_b_q, obj.hex_b_r)
        ft = self._fill_textures.get(ha)
        if ft and ft.texture_id == obj.texture_id:
            return ft
        ft = self._fill_textures.get(hb)
        if ft and ft.texture_id == obj.texture_id:
            return ft
        return None

    def _paint_textured_line(
        self, painter: QPainter, path: QPainterPath, obj: HexsideObject,
        taper_start: bool = False, taper_end: bool = False,
        taper_length: float = 0.5,
    ) -> None:
        """Draw a hexside path filled with a texture instead of a solid color.

        If an adjacent hex has the same texture in its fill layer, the brush
        uses that fill's zoom/offset/rotation so the hexside blends seamlessly.
        """
        fill_tex = self._find_matching_fill_texture(obj)
        if fill_tex:
            brush = self._make_texture_brush(
                obj.texture_id, fill_tex.zoom, fill_tex.rotation,
                fill_tex.offset_x, fill_tex.offset_y,
            )
        else:
            brush = self._make_texture_brush(
                obj.texture_id, obj.texture_zoom, obj.texture_rotation,
            )
        if brush is None:
            # Fallback to solid color if texture not found
            pen = QPen(QColor(obj.color), obj.width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            return

        if obj.random and obj.random_jitter > 0:
            self._draw_textured_path_with_jitter(
                painter, path, obj.width, brush,
                obj.random_jitter, obj.random_seed,
                taper_start=taper_start, taper_end=taper_end,
                taper_length=taper_length,
            )
        elif taper_start or taper_end:
            self._draw_textured_path_with_jitter(
                painter, path, obj.width, brush,
                0.0, 0,
                taper_start=taper_start, taper_end=taper_end,
                taper_length=taper_length,
            )
        else:
            stroker = QPainterPathStroker()
            stroker.setWidth(obj.width)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            stroked = stroker.createStroke(path)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(brush)
            painter.drawPath(stroked)

    @staticmethod
    def _draw_textured_path_with_jitter(
        painter: QPainter, path: QPainterPath,
        base_width: float, brush: QBrush, jitter: float, seed: int,
        width_offset: float = 0.0, num_segments: int = 30,
        taper_start: bool = False, taper_end: bool = False,
        taper_length: float = 0.5,
    ) -> None:
        """Draw a textured path with varying width (jitter modulates thickness).

        Args:
            num_segments: Ignored; computed adaptively from path length.
            taper_start: Taper the start of the path to zero width.
            taper_end: Taper the end of the path to zero width.
            taper_length: Fraction of path over which to taper (0.1–1.0).
        """
        if path.isEmpty() or path.length() == 0:
            return

        # Adaptive segment count: 1 segment per 10 world pixels, clamped to [5, 30]
        # Use more segments when taper is active for smoother width transitions
        path_len = path.length()
        has_taper = taper_start or taper_end
        seg_max = 60 if has_taper else 30
        num_segments = max(5, min(seg_max, int(path_len / (5 if has_taper else 10))))

        rng = _random.Random(seed + 77777)

        # Generate smoothed width variations
        raw = []
        for _ in range(num_segments + 1):
            noise = rng.gauss(0, jitter) if jitter > 0 else 0.0
            raw.append(base_width + noise)
        min_w = base_width * 0.15
        raw = [max(min_w, w) for w in raw]
        widths = list(raw)
        for i in range(1, len(widths) - 1):
            widths[i] = (raw[i - 1] + raw[i] + raw[i + 1]) / 3.0

        # Apply taper factors using smoothstep (3x²−2x³) for curved transitions
        if has_taper:
            for i in range(num_segments + 1):
                t = i / num_segments
                factor = 1.0
                if taper_start and t < taper_length:
                    x = t / taper_length if taper_length > 0 else 0.0
                    factor *= x * x * (3.0 - 2.0 * x)
                if taper_end and t > (1.0 - taper_length):
                    x = (1.0 - t) / taper_length if taper_length > 0 else 0.0
                    factor *= x * x * (3.0 - 2.0 * x)
                widths[i] *= factor

        # Draw each segment as a stroked mini-path filled with texture
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(brush)
        stroker = QPainterPathStroker()
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        for i in range(num_segments):
            t0 = i / num_segments
            t1 = (i + 1) / num_segments
            p0 = path.pointAtPercent(t0)
            p1 = path.pointAtPercent(t1)
            w = (widths[i] + widths[i + 1]) / 2.0 + width_offset
            w = max(w, 0.5)

            seg = QPainterPath()
            seg.moveTo(p0)
            seg.lineTo(p1)
            stroker.setWidth(w)
            painter.drawPath(stroker.createStroke(seg))

    # --- Serialization ---

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "hexside"
        data["hexsides"] = [obj.serialize() for obj in self.hexsides.values()]
        # Always save all effect fields so disabled settings survive round-trip
        data["shadow_enabled"] = self.shadow_enabled
        data["shadow_type"] = self.shadow_type
        data["shadow_color"] = self.shadow_color
        data["shadow_opacity"] = round(self.shadow_opacity, 2)
        data["shadow_angle"] = round(self.shadow_angle, 1)
        data["shadow_distance"] = round(self.shadow_distance, 1)
        data["shadow_spread"] = round(self.shadow_spread, 1)
        data["shadow_size"] = round(self.shadow_size, 1)
        data["bevel_enabled"] = self.bevel_enabled
        data["bevel_type"] = self.bevel_type
        data["bevel_angle"] = round(self.bevel_angle, 1)
        data["bevel_size"] = round(self.bevel_size, 2)
        data["bevel_depth"] = round(self.bevel_depth, 3)
        data["bevel_highlight_color"] = self.bevel_highlight_color
        data["bevel_highlight_opacity"] = round(self.bevel_highlight_opacity, 2)
        data["bevel_shadow_color"] = self.bevel_shadow_color
        data["bevel_shadow_opacity"] = round(self.bevel_shadow_opacity, 2)
        data["structure_enabled"] = self.structure_enabled
        if self.structure_texture_id is not None:
            data["structure_texture_id"] = self.structure_texture_id
        data["structure_scale"] = round(self.structure_scale, 3)
        data["structure_depth"] = round(self.structure_depth, 1)
        data["structure_invert"] = self.structure_invert
        return data

    @classmethod
    def deserialize(cls, data: dict) -> HexsideLayer:
        layer = cls(data.get("name", "Hexside"))
        layer._base_deserialize(data)
        layer.shadow_enabled = data.get("shadow_enabled", False)
        layer.shadow_type = data.get("shadow_type", "outer")
        layer.shadow_color = data.get("shadow_color", "#000000")
        layer.shadow_opacity = data.get("shadow_opacity", 0.5)
        layer.shadow_angle = data.get("shadow_angle", 120.0)
        layer.shadow_distance = data.get("shadow_distance", 5.0)
        layer.shadow_spread = data.get("shadow_spread", 0.0)
        layer.shadow_size = data.get("shadow_size", data.get("shadow_blur_radius", 5.0))
        layer.bevel_enabled = data.get("bevel_enabled", False)
        layer.bevel_type = data.get("bevel_type", "inner")
        layer.bevel_angle = data.get("bevel_angle", 120.0)
        layer.bevel_size = data.get("bevel_size", 3.0)
        layer.bevel_depth = data.get("bevel_depth", 0.5)
        layer.bevel_highlight_color = data.get("bevel_highlight_color", "#ffffff")
        layer.bevel_highlight_opacity = data.get("bevel_highlight_opacity", 0.75)
        layer.bevel_shadow_color = data.get("bevel_shadow_color", "#000000")
        layer.bevel_shadow_opacity = data.get("bevel_shadow_opacity", 0.75)
        layer.structure_enabled = data.get("structure_enabled", False)
        layer.structure_texture_id = data.get("structure_texture_id", None)
        layer.structure_scale = data.get("structure_scale", 1.0)
        layer.structure_depth = data.get("structure_depth", 50.0)
        layer.structure_invert = data.get("structure_invert", False)
        for obj_data in data.get("hexsides", []):
            obj = HexsideObject.deserialize(obj_data)
            layer.hexsides[obj.edge_key()] = obj
        return layer
