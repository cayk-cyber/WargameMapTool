"""Renders the hex grid lines, center dots, coordinate labels, and border."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF

from app.hex.hex_grid_config import MM_TO_PX, HexGridConfig
from app.hex.hex_math import (
    Hex,
    Layout,
    axial_to_offset,
    hex_corner_offset,
    hex_corners,
    hex_neighbor,
    hex_to_pixel,
    pixel_to_hex,
)


class HexGridRenderer:
    """Draws the hex grid overlay."""

    def paint_border_fill(
        self,
        painter: QPainter,
        layout: Layout,
        config: HexGridConfig,
    ) -> None:
        """Draw border fill only. Call BEFORE layers so fills aren't covered."""
        if config.show_border and config.border_fill:
            bounds = config.get_map_pixel_bounds()
            if bounds.isEmpty():
                return
            margin = config.border_margin * MM_TO_PX
            border_rect = bounds.adjusted(-margin, -margin, margin, margin)
            painter.fillRect(border_rect, config.border_fill_color)

    def paint(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        config: HexGridConfig,
        dot_overrides: dict | None = None,
        coord_overrides: dict | None = None,
    ) -> None:
        visible_hexes = self._get_visible_hexes(viewport_rect, layout, config)

        # Border outline (fill is drawn earlier via paint_border_fill)
        if config.show_border:
            self._draw_border(painter, layout, config)

        if config.grid_style == "crossings":
            self._draw_hex_crossings(painter, visible_hexes, layout, config)
        else:
            self._draw_hex_outlines(painter, visible_hexes, layout, config)

        if config.megahex_enabled:
            self._draw_megahexes(painter, visible_hexes, layout, config)

        if config.show_center_dots:
            self._draw_center_dots(painter, visible_hexes, layout, config, dot_overrides)

        if config.show_coordinates:
            self._draw_coordinates(painter, visible_hexes, layout, config, coord_overrides)

    def _get_visible_hexes(
        self,
        viewport_rect: QRectF,
        layout: Layout,
        config: HexGridConfig,
    ) -> list[Hex]:
        """Determine which hexes are visible in the viewport."""
        corners = [
            viewport_rect.topLeft(),
            viewport_rect.topRight(),
            viewport_rect.bottomLeft(),
            viewport_rect.bottomRight(),
        ]

        hex_coords = [
            pixel_to_hex(layout, c.x(), c.y()) for c in corners
        ]

        min_q = min(h.q for h in hex_coords) - 2
        max_q = max(h.q for h in hex_coords) + 2
        min_r = min(h.r for h in hex_coords) - 2
        max_r = max(h.r for h in hex_coords) + 2

        # L04: clamp iteration range to grid size to prevent huge loops at low zoom
        _grid_max = config.width + config.height + 4
        min_q = max(min_q, -_grid_max)
        max_q = min(max_q, _grid_max)
        min_r = max(min_r, -_grid_max)
        max_r = min(max_r, _grid_max)

        visible = []
        for r in range(min_r, max_r + 1):
            for q in range(min_q, max_q + 1):
                h = Hex(q, r)
                col, row = axial_to_offset(h, config.first_row_offset, config.orientation)
                if 0 <= col < config.width and 0 <= row < config.height:
                    visible.append(h)

        return visible

    def _draw_hex_outlines(
        self,
        painter: QPainter,
        hexes: list[Hex],
        layout: Layout,
        config: HexGridConfig,
    ) -> None:
        pen = QPen(config.edge_color, config.line_width)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))

        for h in hexes:
            corners = hex_corners(layout, h)
            polygon = QPolygonF([QPointF(x, y) for x, y in corners])
            painter.drawPolygon(polygon)

    def _draw_hex_crossings(
        self,
        painter: QPainter,
        hexes: list[Hex],
        layout: Layout,
        config: HexGridConfig,
    ) -> None:
        """Draw only vertex marks where hexes meet (no full edge lines)."""
        pen = QPen(config.edge_color, config.line_width)
        painter.setPen(pen)

        frac = 0.25  # Draw 25% of each edge from the vertex

        for h in hexes:
            corners = hex_corners(layout, h)
            n = len(corners)
            for i in range(n):
                cx, cy = corners[i]
                # Stub toward next corner
                nx, ny = corners[(i + 1) % n]
                painter.drawLine(
                    QPointF(cx, cy),
                    QPointF(cx + (nx - cx) * frac, cy + (ny - cy) * frac),
                )

    def _draw_center_dots(
        self,
        painter: QPainter,
        hexes: list[Hex],
        layout: Layout,
        config: HexGridConfig,
        dot_overrides: dict | None = None,
    ) -> None:
        # Outline pass (larger dot behind the fill dot)
        if config.center_dot_outline:
            outline_size = config.center_dot_size + config.center_dot_outline_width * 2
            outline_pen = QPen(config.center_dot_outline_color, outline_size)
            outline_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(outline_pen)
            for h in hexes:
                cx, cy = hex_to_pixel(layout, h)
                painter.drawPoint(QPointF(cx, cy))

        # Fill dots - use override color per hex if available
        if dot_overrides:
            default_pen = QPen(config.center_dot_color, config.center_dot_size)
            default_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            for h in hexes:
                override = dot_overrides.get(h)
                if override is not None:
                    pen = QPen(override, config.center_dot_size)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    painter.setPen(pen)
                else:
                    painter.setPen(default_pen)
                cx, cy = hex_to_pixel(layout, h)
                painter.drawPoint(QPointF(cx, cy))
        else:
            pen = QPen(config.center_dot_color, config.center_dot_size)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for h in hexes:
                cx, cy = hex_to_pixel(layout, h)
                painter.drawPoint(QPointF(cx, cy))

    def _draw_coordinates(
        self,
        painter: QPainter,
        hexes: list[Hex],
        layout: Layout,
        config: HexGridConfig,
        coord_overrides: dict | None = None,
    ) -> None:
        font = QFont("Arial", 8)
        font.setPixelSize(max(6, int(config.hex_size * config.coord_font_scale / 100.0)))
        painter.setFont(font)
        default_pen = QPen(config.edge_color)
        painter.setPen(default_pen)

        y_offset = config.coord_offset_y * config.hex_size

        for h in hexes:
            # Per-hex coordinate color override
            if coord_overrides:
                override = coord_overrides.get(h)
                if override is not None:
                    painter.setPen(QPen(override))
                else:
                    painter.setPen(default_pen)

            cx, cy = hex_to_pixel(layout, h)
            col, row = axial_to_offset(h, config.first_row_offset, config.orientation)
            label = config.format_coordinate(col, row)

            if config.coord_position == "bottom":
                text_y = cy + config.hex_size * 0.30 + y_offset
                alignment = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
            else:
                text_y = cy - config.hex_size * 0.55 + y_offset
                alignment = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop

            text_rect = QRectF(
                cx - config.hex_size * 0.5,
                text_y,
                config.hex_size,
                config.hex_size * 0.3,
            )
            painter.drawText(text_rect, int(alignment), label)

    @staticmethod
    def _megahex_center_of(h: Hex, radius: int, offset_q: int, offset_r: int) -> tuple[int, int]:
        """Return the megahex center (q, r) that hex h belongs to.

        Uses the Eisenstein lattice for proper hexagonal tiling.
        Basis vectors: v1 = (R+1, R), v2 = (-R, 2R+1)
        This produces N = 3R^2 + 3R + 1 hexes per cell with uniform,
        non-tilted hexagonal groupings.
        """
        R = radius
        N = 3 * R * R + 3 * R + 1
        hq = h.q - offset_q
        hr = h.r - offset_r

        # Fractional lattice coordinates
        m_f = ((2 * R + 1) * hq + R * hr) / N
        n_f = ((R + 1) * hr - R * hq) / N
        m0 = round(m_f)
        n0 = round(n_f)

        # Check 7 nearest lattice points and pick closest by hex distance
        best_dist = 999999
        best = (0, 0)

        for dm, dn in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)):
            m = m0 + dm
            n = n0 + dn
            cq = m * (R + 1) - n * R + offset_q
            cr = m * R + n * (2 * R + 1) + offset_r
            dq = abs(h.q - cq)
            dr = abs(h.r - cr)
            ds = abs((-h.q - h.r) - (-cq - cr))
            dist = (dq + dr + ds) // 2
            if dist < best_dist or (dist == best_dist and (cq, cr) < best):
                best_dist = dist
                best = (cq, cr)

        return best

    def _draw_megahexes(
        self,
        painter: QPainter,
        hexes: list[Hex],
        layout: Layout,
        config: HexGridConfig,
    ) -> None:
        """Draw megahex overlay (thick borders between clusters or geometric hexagons)."""
        R = config.megahex_radius
        off_q = config.megahex_offset_q
        off_r = config.megahex_offset_r

        # Non-cosmetic pen: width scales with the map so it looks correct
        # in both the main canvas and the minimap.
        pen_width = config.megahex_width * layout.size_x / 50.0
        pen = QPen(config.megahex_color, pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))

        # Clip to the actual hex grid outline so megahex lines (including
        # rounded pen caps) never extend outside the outer edges of the grid.
        # IntersectClip preserves any existing clip (e.g. half-hex rect).
        painter.save()
        painter.setClipPath(
            config.get_grid_clip_path(), Qt.ClipOperation.IntersectClip
        )

        if config.megahex_mode == "geometric":
            step = 2 * R + 1
            self._draw_megahexes_geometric(painter, hexes, layout, config, step, off_q, off_r)
        else:
            self._draw_megahexes_edges(painter, hexes, layout, config, R, off_q, off_r)

        painter.restore()

    def _draw_megahexes_edges(
        self,
        painter: QPainter,
        hexes: list[Hex],
        layout: Layout,
        config: HexGridConfig,
        radius: int,
        off_q: int,
        off_r: int,
    ) -> None:
        """Draw megahex boundaries along hex edges."""
        is_flat = config.orientation == "flat"
        drawn_edges: set[tuple[tuple[float, float], tuple[float, float]]] = set()

        for h in hexes:
            center_h = self._megahex_center_of(h, radius, off_q, off_r)
            corners_h = hex_corners(layout, h)

            for direction in range(6):
                nb = hex_neighbor(h, direction)
                center_nb = self._megahex_center_of(nb, radius, off_q, off_r)

                if center_h == center_nb:
                    continue

                # Map direction to the correct shared edge corners.
                # For flat-top:   corner 0 is at 0°  → ci = (-direction) % 6
                # For pointy-top: corner 0 is at 30° → ci = (5 - direction) % 6
                # (Different from hex_edge_vertices, which uses a self-consistent
                # but geometry-shifted convention shared with nearest_hex_edge.)
                ci = (-direction) % 6 if is_flat else (5 - direction) % 6
                p1 = corners_h[ci]
                p2 = corners_h[(ci + 1) % 6]

                # Deduplicate (round to avoid float comparison issues)
                edge_key = (
                    (round(p1[0], 1), round(p1[1], 1)),
                    (round(p2[0], 1), round(p2[1], 1)),
                )
                rev_key = (edge_key[1], edge_key[0])
                if edge_key in drawn_edges or rev_key in drawn_edges:
                    continue
                drawn_edges.add(edge_key)

                painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

    def _draw_megahexes_geometric(
        self,
        painter: QPainter,
        hexes: list[Hex],
        layout: Layout,
        config: HexGridConfig,
        step: int,
        off_q: int,
        off_r: int,
    ) -> None:
        """Draw perfect hexagons at megahex center positions.

        Uses axial supergrid for center positions. Each mega-hexagon has
        vertex radius = step * hex_size, which makes adjacent mega-hexagons
        share edges and tile the plane perfectly.
        Clipping to the grid boundary is handled by the caller (_draw_megahexes).
        """
        # Collect megahex centers from visible hexes using simple axial grid,
        # then expand to include neighbor centers so that megahexes at the
        # grid edge are drawn fully.
        core_centers: set[tuple[int, int]] = set()
        for h in hexes:
            aq = h.q - off_q
            ar = h.r - off_r
            a0 = round(aq / step)
            b0 = round(ar / step)
            core_centers.add((a0 * step + off_q, b0 * step + off_r))

        centers: set[tuple[int, int]] = set()
        for cq, cr in core_centers:
            for dq, dr in ((0, 0), (step, 0), (-step, 0), (0, step),
                           (0, -step), (step, -step), (-step, step)):
                centers.add((cq + dq, cr + dr))

        for cq, cr in centers:
            center_hex = Hex(cq, cr)
            cx, cy = hex_to_pixel(layout, center_hex)

            # hex_corner_offset returns (size * cos(angle), size * sin(angle)).
            # Multiplying by step gives the correct mega-hex vertex positions
            # so that adjacent mega-hexes touch edge-to-edge.
            points = []
            for i in range(6):
                ox, oy = hex_corner_offset(layout, i)
                points.append(QPointF(cx + ox * step, cy + oy * step))

            polygon = QPolygonF(points)
            painter.drawPolygon(polygon)

    def _draw_border(
        self,
        painter: QPainter,
        layout: Layout,
        config: HexGridConfig,
    ) -> None:
        bounds = config.get_map_pixel_bounds()
        if bounds.isEmpty():
            return

        margin = config.border_margin * MM_TO_PX
        border_rect = bounds.adjusted(-margin, -margin, margin, margin)

        pen = QPen(config.border_color, max(config.line_width, 2.0))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))
        painter.drawRect(border_rect)
