"""Path layer - lines drawn between adjacent hex centers (roads, trails, etc.)."""

from __future__ import annotations

import math
import random as _random

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

from app.hex.hex_math import (
    HEX_DIRECTIONS,
    Hex,
    Layout,
    hex_edge_key,
    hex_to_pixel,
)
from app.layers.base_layer import Layer
from app.models.path_object import PathObject


_CAP_MAP = {
    "flat": Qt.PenCapStyle.FlatCap,
    "round": Qt.PenCapStyle.RoundCap,
    "square": Qt.PenCapStyle.SquareCap,
}


def _stable_hex_hash(q: int, r: int) -> int:
    """Deterministic hash for hex coordinates, independent of Python hash seed."""
    return ((q * 73856093) ^ (r * 19349663)) & 0x7FFFFFFF


def hex_endpoint_offset(
    q: int, r: int, amplitude: float,
) -> tuple[float, float]:
    """Return deterministic (dx, dy) world-space displacement for a hex center.

    The offset depends only on the hex coordinate, so all paths meeting at
    the same hex center will share the same displaced position, preserving
    connectivity.  Uses a stable hash (not Python's session-random hash).
    """
    if amplitude <= 0:
        return (0.0, 0.0)
    rng = _random.Random(_stable_hex_hash(q, r))
    angle = rng.uniform(0, 2 * math.pi)
    raw_mag = rng.gauss(0, 0.6)
    raw_mag = max(-1.5, min(1.5, raw_mag))
    radius = raw_mag * amplitude
    return (radius * math.cos(angle), radius * math.sin(angle))


class PathLayer(Layer):
    clip_to_grid = True

    def __init__(self, name: str = "Path (Center)"):
        super().__init__(name)
        # Dict keyed by canonical edge key: ((q_a, r_a), (q_b, r_b))
        self.paths: dict[tuple[tuple[int, int], tuple[int, int]], PathObject] = {}
        # QPainterPath cache: edge_key -> (params_tuple, QPainterPath)
        # Self-validating: only recomputed when path-relevant parameters change.
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

    def add_path(self, obj: PathObject) -> None:
        self.paths[obj.edge_key()] = obj
        self.mark_dirty()

    def remove_path(self, obj: PathObject) -> None:
        key = obj.edge_key()
        self.paths.pop(key, None)
        self._path_cache.pop(key, None)
        self.mark_dirty()

    def get_path_at_edge(self, hex_a: Hex, hex_b: Hex) -> PathObject | None:
        key = hex_edge_key(hex_a, hex_b)
        return self.paths.get(key)

    def hit_test(
        self, world_x: float, world_y: float, layout: Layout, threshold: float = 8.0,
    ) -> PathObject | None:
        """Find the nearest path to a world point within threshold."""
        point = QPointF(world_x, world_y)
        for obj in self.paths.values():
            path = self._get_cached_path(layout, obj)
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

        # Collect visible paths and pre-compute QPainterPaths
        hidden = self._drag_hidden_keys
        visible: list[tuple[PathObject, QPainterPath]] = []
        for obj in self.paths.values():
            if hidden and obj.edge_key() in hidden:
                continue
            cx_a, cy_a = hex_to_pixel(layout, obj.hex_a())
            cx_b, cy_b = hex_to_pixel(layout, obj.hex_b())
            mid_x = (cx_a + cx_b) / 2
            mid_y = (cy_a + cy_b) / 2
            if not expanded.contains(QPointF(mid_x, mid_y)):
                continue
            path = self._get_cached_path(layout, obj)
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
            if obj.random and obj.random_jitter > 0:
                # Mirror the foreground jitter rendering so bg and fg vary together.
                self._draw_path_with_jitter(
                    painter, path, obj.bg_width, QColor(obj.bg_color),
                    obj.random_jitter, obj.random_seed,
                )
            else:
                pen = self._make_pen(
                    obj.bg_color, obj.bg_width, obj.bg_line_type,
                    obj.bg_dash_length, obj.bg_gap_length,
                    obj.bg_texture_id, obj.bg_texture_zoom, obj.bg_texture_rotation,
                    obj.bg_dash_cap,
                )
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
                # For solid backgrounds with round cap, paint a filled disk at both
                # endpoints so that adjacent path segments connect cleanly at any angle.
                # Round caps alone only extend a *semicircle* in the travel direction,
                # leaving an angular notch when two segments meet at a non-straight
                # junction.  A full disk (radius = half pen width) eliminates the notch.
                # With flat/square caps the user explicitly wants a clean endpoint, so
                # we skip the disk.
                if obj.bg_line_type == "solid" and obj.bg_dash_cap == "round" and not obj.bg_texture_id:
                    r = obj.bg_width / 2.0
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(obj.bg_color))
                    painter.drawEllipse(path.pointAtPercent(0.0), r, r)
                    painter.drawEllipse(path.pointAtPercent(1.0), r, r)
            painter.restore()

        # Pass 2: All foreground paths (on top of all backgrounds)
        for obj, path in visible:
            painter.save()
            if obj.opacity < 1.0:
                painter.setOpacity(obj.opacity)
            if obj.random and obj.random_jitter > 0:
                if obj.texture_id:
                    img = get_texture_image(obj.texture_id)
                    if img is not None:
                        brush = QBrush(QPixmap.fromImage(img))
                        brush_xf = QTransform()
                        if obj.texture_rotation != 0.0:
                            brush_xf.rotate(obj.texture_rotation)
                        if obj.texture_zoom != 1.0:
                            brush_xf.scale(obj.texture_zoom, obj.texture_zoom)
                        brush.setTransform(brush_xf)
                        self._draw_textured_path_with_jitter(
                            painter, path, obj.width, brush,
                            obj.random_jitter, obj.random_seed,
                        )
                    else:
                        self._draw_path_with_jitter(
                            painter, path, obj.width, QColor(obj.color),
                            obj.random_jitter, obj.random_seed,
                        )
                else:
                    self._draw_path_with_jitter(
                        painter, path, obj.width, QColor(obj.color),
                        obj.random_jitter, obj.random_seed,
                    )
            else:
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

    @staticmethod
    def _draw_path_with_jitter(
        painter: QPainter, path: QPainterPath,
        base_width: float, color: QColor, jitter: float, seed: int,
        width_offset: float = 0.0, num_segments: int = 30,
    ) -> None:
        """Draw a path with varying width (jitter modulates line thickness).

        Args:
            num_segments: Ignored; computed adaptively from path length.
        """
        if path.isEmpty() or path.length() == 0:
            return

        # Adaptive segment count: 1 segment per 10 world pixels, clamped to [5, 30]
        path_len = path.length()
        num_segments = max(5, min(30, int(path_len / 10)))

        rng = _random.Random(seed + 77777)

        raw = []
        for _ in range(num_segments + 1):
            noise = rng.gauss(0, jitter)
            w = base_width + noise
            raw.append(w)

        min_w = base_width * 0.15
        raw = [max(min_w, w) for w in raw]

        widths = list(raw)
        for i in range(1, len(widths) - 1):
            widths[i] = (raw[i - 1] + raw[i] + raw[i + 1]) / 3.0

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

    @staticmethod
    def _draw_textured_path_with_jitter(
        painter: QPainter, path: QPainterPath,
        base_width: float, brush: QBrush, jitter: float, seed: int,
        width_offset: float = 0.0, num_segments: int = 30,
    ) -> None:
        """Draw a textured path with varying width (jitter modulates thickness).

        Args:
            num_segments: Ignored; computed adaptively from path length.
        """
        if path.isEmpty() or path.length() == 0:
            return

        # Adaptive segment count: 1 segment per 10 world pixels, clamped to [5, 30]
        path_len = path.length()
        num_segments = max(5, min(30, int(path_len / 10)))

        rng = _random.Random(seed + 77777)

        raw = []
        for _ in range(num_segments + 1):
            raw.append(base_width + rng.gauss(0, jitter))
        min_w = base_width * 0.15
        raw = [max(min_w, w) for w in raw]
        widths = list(raw)
        for i in range(1, len(widths) - 1):
            widths[i] = (raw[i - 1] + raw[i] + raw[i + 1]) / 3.0

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

    def _find_direction(self, obj: PathObject) -> int | None:
        """Find the direction index from hex_a to hex_b."""
        dq = obj.hex_b_q - obj.hex_a_q
        dr = obj.hex_b_r - obj.hex_a_r
        for d in range(6):
            if HEX_DIRECTIONS[d].q == dq and HEX_DIRECTIONS[d].r == dr:
                return d
        return None

    def _get_cached_path(self, layout: Layout, obj: PathObject) -> QPainterPath:
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
        )
        obj_key = obj.edge_key()
        entry = self._path_cache.get(obj_key)
        if entry is not None and entry[0] == cache_key:
            return entry[1]
        path = self._compute_path(layout, obj)
        self._path_cache[obj_key] = (cache_key, path)
        return path

    def _compute_path(self, layout: Layout, obj: PathObject) -> QPainterPath:
        """Compute the full QPainterPath for a path segment between two hex centers."""
        direction = self._find_direction(obj)
        if direction is None:
            return QPainterPath()

        # Get hex center pixel positions
        c1x, c1y = hex_to_pixel(layout, obj.hex_a())
        c2x, c2y = hex_to_pixel(layout, obj.hex_b())

        # Direction vector and perpendicular
        dx = c2x - c1x
        dy = c2y - c1y
        seg_len = math.hypot(dx, dy)
        if seg_len == 0:
            return QPainterPath()

        # Unit tangent and perpendicular
        tx, ty = dx / seg_len, dy / seg_len
        perp_x, perp_y = -ty, tx

        # Start and end points (may be displaced by random endpoint)
        # Uses hex-coordinate-based displacement so adjacent paths connect
        start_x, start_y = c1x, c1y
        end_x, end_y = c2x, c2y

        if obj.random and obj.random_endpoint > 0:
            s_dx, s_dy = hex_endpoint_offset(
                obj.hex_a_q, obj.hex_a_r, obj.random_endpoint,
            )
            e_dx, e_dy = hex_endpoint_offset(
                obj.hex_b_q, obj.hex_b_r, obj.random_endpoint,
            )
            start_x += s_dx
            start_y += s_dy
            end_x += e_dx
            end_y += e_dy

        # Recompute direction from (possibly displaced) endpoints
        ex = end_x - start_x
        ey = end_y - start_y

        # Build point list from control points
        # t-positions may be randomized by distance parameter
        t_positions = obj.cp_t_positions()
        points: list[tuple[float, float]] = []
        num_cp = len(obj.control_points)
        for i in range(num_cp):
            if i == 0:
                # Endpoint A: 2D free offset (ep_a) from start base
                points.append((start_x + obj.ep_a[0], start_y + obj.ep_a[1]))
            elif i == num_cp - 1:
                # Endpoint B: 2D free offset (ep_b) from end base
                points.append((end_x + obj.ep_b[0], end_y + obj.ep_b[1]))
            else:
                t = t_positions[i]
                base_x = start_x + ex * t
                base_y = start_y + ey * t
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

        # Add random waviness if enabled
        if obj.random and obj.random_amplitude > 0:
            points = self._add_random_waviness(
                points, obj.random_seed, obj.random_amplitude,
                perp_x, perp_y,
            )

        # Force endpoint tangents along the straight hex-center direction so that
        # paths always depart from / arrive at the hex center in a predictable direction.
        # This prevents jagged kinks where two paths meet at a shared hex center.
        return self._catmull_rom_path(points, entry_tangent=(tx, ty), exit_tangent=(tx, ty))

    @staticmethod
    def _add_random_waviness(
        base_points: list[tuple[float, float]],
        seed: int,
        amplitude: float,
        perp_x: float,
        perp_y: float,
    ) -> list[tuple[float, float]]:
        """Add road-style random waviness between base points.

        Uses a smoothed random walk to produce broad, organic S-curves
        suitable for roads — distinct from the more jagged meandering
        used for rivers in hexside layers.  A gentle fade-out envelope
        near the start and end ensures smooth connections at hex centers.
        """
        rng = _random.Random(seed)
        n_segments = len(base_points) - 1
        if n_segments < 1:
            return list(base_points)

        pts_per_seg = 5
        total_pts = n_segments * pts_per_seg

        # Random walk with gentle mean reversion for pronounced curves
        amp_offsets: list[float] = []
        current = 0.0
        for _ in range(total_pts):
            current += rng.gauss(0, amplitude * 1.2)
            current *= 0.7  # Gentle mean reversion — allows bigger excursions
            current = max(-amplitude * 3.5, min(amplitude * 3.5, current))
            amp_offsets.append(current)

        # Single smoothing pass — removes micro-jitter but preserves broad shape
        smoothed = list(amp_offsets)
        for j in range(1, len(amp_offsets) - 1):
            smoothed[j] = (amp_offsets[j - 1] + amp_offsets[j] + amp_offsets[j + 1]) / 3
        amp_offsets = smoothed

        # Build interpolated result with gentle fade-out at endpoints
        result: list[tuple[float, float]] = []
        idx = 0
        total_interp = n_segments * pts_per_seg
        for i in range(n_segments):
            x1, y1 = base_points[i]
            x2, y2 = base_points[i + 1]
            result.append((x1, y1))

            for j in range(pts_per_seg):
                t = (j + 1) / (pts_per_seg + 1)
                mx = x1 + (x2 - x1) * t
                my = y1 + (y2 - y1) * t

                # Gentle fade: ramp from 0 at endpoints to 1 quickly
                # Only the first/last ~10% are faded (not 25% like before)
                global_t = (idx + 0.5) / total_interp
                fade = min(global_t * 8.0, (1.0 - global_t) * 8.0, 1.0)
                fade = fade * fade * (3.0 - 2.0 * fade)  # cubic ease

                off = amp_offsets[idx] * fade
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
        """Build a road-like smooth path through all control points with no S-curves.

        Uses local angle-bisector tangents: the direction at each interior point
        is the bisector of the incoming and outgoing segment unit vectors.  Handles
        are scaled by TENSION * segment_length so they stay within the segment's
        bounds.  Both handles are clamped to the forward half-plane, which
        mathematically prevents S-curves (direction reversals between any two
        consecutive control points).  C1 continuity is preserved because the same
        bisector direction is computed from both adjacent segments.

        ``entry_tangent`` / ``exit_tangent``: optional forced unit tangent vectors at
        the first / last point.  When supplied they override the default "along first/
        last segment" fallback.  Pass the straight hex-center direction to ensure
        paths always depart/arrive along the spine regardless of random waviness,
        preventing jagged kinks at hex junctions.
        """
        path = QPainterPath()
        if len(points) < 2:
            return path

        if len(points) == 2:
            path.moveTo(QPointF(points[0][0], points[0][1]))
            path.lineTo(QPointF(points[1][0], points[1][1]))
            return path

        path.moveTo(QPointF(points[0][0], points[0][1]))
        n = len(points)
        TENSION = 0.35  # handle = TENSION * segment_length (0 = straight, ~0.5 = very smooth)

        for i in range(n - 1):
            p1 = points[i]
            p2 = points[i + 1]

            seg_dx = p2[0] - p1[0]
            seg_dy = p2[1] - p1[1]
            seg_len = math.hypot(seg_dx, seg_dy)

            if seg_len < 1e-6:
                path.lineTo(QPointF(p2[0], p2[1]))
                continue

            seg_ux = seg_dx / seg_len
            seg_uy = seg_dy / seg_len
            handle = seg_len * TENSION

            # Outgoing tangent direction at p1 (bisector, or straight for first point)
            if i > 0:
                prev_dx = p1[0] - points[i - 1][0]
                prev_dy = p1[1] - points[i - 1][1]
                prev_len = math.hypot(prev_dx, prev_dy)
                if prev_len > 1e-6:
                    bx = prev_dx / prev_len + seg_ux
                    by = prev_dy / prev_len + seg_uy
                    blen = math.hypot(bx, by)
                    if blen > 1e-6 and (bx * seg_ux + by * seg_uy) > 0:
                        out_ux, out_uy = bx / blen, by / blen
                    else:
                        out_ux, out_uy = seg_ux, seg_uy  # fallback: straight
                else:
                    out_ux, out_uy = seg_ux, seg_uy
            else:
                # First point: use forced tangent if provided, else along first segment
                out_ux, out_uy = entry_tangent if entry_tangent else (seg_ux, seg_uy)

            # Incoming tangent direction at p2 (bisector, or straight for last point)
            if i < n - 2:
                next_dx = points[i + 2][0] - p2[0]
                next_dy = points[i + 2][1] - p2[1]
                next_len = math.hypot(next_dx, next_dy)
                if next_len > 1e-6:
                    bx = seg_ux + next_dx / next_len
                    by = seg_uy + next_dy / next_len
                    blen = math.hypot(bx, by)
                    if blen > 1e-6 and (bx * seg_ux + by * seg_uy) > 0:
                        in_ux, in_uy = bx / blen, by / blen
                    else:
                        in_ux, in_uy = seg_ux, seg_uy
                else:
                    in_ux, in_uy = seg_ux, seg_uy
            else:
                # Last point: use forced tangent if provided, else along last segment
                in_ux, in_uy = exit_tangent if exit_tangent else (seg_ux, seg_uy)

            cp1 = (p1[0] + out_ux * handle, p1[1] + out_uy * handle)
            cp2 = (p2[0] - in_ux * handle, p2[1] - in_uy * handle)

            path.cubicTo(
                QPointF(cp1[0], cp1[1]),
                QPointF(cp2[0], cp2[1]),
                QPointF(p2[0], p2[1]),
            )

        return path

    # --- Serialization ---

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "path"
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
    def deserialize(cls, data: dict) -> PathLayer:
        layer = cls(data.get("name", "Path (Center)"))
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
            obj = PathObject.deserialize(obj_data)
            layer.paths[obj.edge_key()] = obj
        return layer
