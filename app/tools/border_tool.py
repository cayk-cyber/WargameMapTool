"""Border tool - place, select, and edit border objects along hex edges."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen

from app.commands.command import CompoundCommand
from app.commands.command_stack import CommandStack
from app.commands.border_commands import (
    PlaceBorderCommand,
    RemoveBorderCommand,
)
from app.hex.hex_math import (
    Hex,
    Layout,
    hex_edge_key,
    hex_edge_vertices,
    hex_neighbor,
    hex_to_pixel,
    nearest_hex_edge,
)
from app.layers.border_layer import BorderLayer
from app.models.border_object import BorderObject
from app.models.project import Project
from app.tools.base_tool import Tool


class BorderTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack
        self.mode: str = "place"  # "place" or "select"

        # Placement settings
        self.color: str = "#000000"
        self.width: float = 3.0
        self.line_type: str = "solid"
        self.element_size: float = 4.0
        self.gap_size: float = 4.0
        self.dash_cap: str = "round"  # "flat", "round", "square"
        self.outline: bool = False
        self.outline_color: str = "#000000"
        self.outline_width: float = 1.0
        self.offset: float = 0.0

        # Hover state
        self._hover_edge: tuple[Hex, int] | None = None  # (hex, direction)
        self._hover_offset_sign: float = 1.0
        self._last_world_pos: QPointF = QPointF(0, 0)

        # Drag state (place mode)
        self._is_dragging: bool = False
        self._drag_command: CompoundCommand | None = None
        self._placed_edges_in_drag: set = set()

        # Select mode state
        self._selected: BorderObject | None = None
        self._interaction = None

        # Selection change callback
        self.on_selection_changed = None

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.mode = "place"
        self.color = "#000000"
        self.width = 3.0
        self.line_type = "solid"
        self.element_size = 4.0
        self.gap_size = 4.0
        self.dash_cap = "round"
        self.outline = False
        self.outline_color = "#000000"
        self.outline_width = 1.0
        self.offset = 0.0
        self._hover_edge = None
        self._selected = None
        self._interaction = None
        self._is_dragging = False
        self._drag_command = None
        self._placed_edges_in_drag = set()

    @property
    def name(self) -> str:
        return "Border"

    @property
    def cursor(self) -> Qt.CursorShape:
        if self.mode == "place":
            return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.ArrowCursor

    def _get_active_border_layer(self) -> BorderLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, BorderLayer):
            return layer
        return None

    def _get_layout(self) -> Layout:
        return self._project.grid_config.create_layout()

    def _notify_selection(self) -> None:
        """Notify listener that the selected object changed."""
        if self.on_selection_changed:
            self.on_selection_changed(self._selected)

    # --- Place mode helpers ---

    def _place_at_hover(self, layer: BorderLayer, layout: Layout) -> None:
        """Place a border at the current hover edge."""
        if self._hover_edge is None:
            return

        hex_c, direction = self._hover_edge
        neighbor = hex_neighbor(hex_c, direction)
        key = hex_edge_key(hex_c, neighbor)

        if key in self._placed_edges_in_drag:
            return
        if layer.get_border_at_edge(hex_c, neighbor) is not None:
            return  # Edge already occupied

        self._placed_edges_in_drag.add(key)

        # Build canonical key
        a = (hex_c.q, hex_c.r)
        b = (neighbor.q, neighbor.r)
        if a > b:
            a, b = b, a

        obj = BorderObject(
            hex_a_q=a[0],
            hex_a_r=a[1],
            hex_b_q=b[0],
            hex_b_r=b[1],
            color=self.color,
            width=self.width,
            line_type=self.line_type,
            element_size=self.element_size,
            gap_size=self.gap_size,
            dash_cap=self.dash_cap,
            outline=self.outline,
            outline_color=self.outline_color,
            outline_width=self.outline_width,
            offset=self.offset * self._hover_offset_sign,
        )

        cmd = PlaceBorderCommand(layer, obj)
        cmd.execute()
        if self._drag_command:
            self._drag_command._commands.append(cmd)

    # --- Mouse events ---

    def mouse_press(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        layer = self._get_active_border_layer()
        if layer is None:
            return

        wx, wy = world_pos.x(), world_pos.y()
        layout = self._get_layout()

        if self.mode == "place":
            if event.button() == Qt.MouseButton.LeftButton:
                self._is_dragging = True
                self._drag_command = CompoundCommand("Place borders")
                self._placed_edges_in_drag = set()
                self._place_at_hover(layer, layout)

            elif event.button() == Qt.MouseButton.RightButton:
                if self._hover_edge:
                    hex_c, direction = self._hover_edge
                    neighbor = hex_neighbor(hex_c, direction)
                    existing = layer.get_border_at_edge(hex_c, neighbor)
                    if existing:
                        cmd = RemoveBorderCommand(layer, existing)
                        self._command_stack.execute(cmd)

        else:  # select mode
            if event.button() != Qt.MouseButton.LeftButton:
                return

            # Try selecting a border
            hit = layer.hit_test(wx, wy, layout)
            if hit:
                self._selected = hit
                self._notify_selection()
            else:
                self._selected = None
                self._notify_selection()

    def mouse_move(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        self._last_world_pos = world_pos
        wx, wy = world_pos.x(), world_pos.y()

        layer = self._get_active_border_layer()
        if layer is None:
            self._hover_edge = None
            return

        layout = self._get_layout()

        if self.mode == "place":
            # Update hover edge — only within valid hexes
            if not self._project.grid_config.is_valid_hex(hex_coord):
                self._hover_edge = None
            else:
                direction, dist = nearest_hex_edge(layout, hex_coord, wx, wy)
                if dist < self._project.grid_config.hex_size * 0.6:
                    self._hover_edge = (hex_coord, direction)
                    # Compute offset sign: positive = toward canonical hex_b, negative = toward hex_a
                    if self.offset != 0.0:
                        neighbor = hex_neighbor(hex_coord, direction)
                        c_ax, c_ay = hex_to_pixel(layout, hex_coord)
                        c_bx, c_by = hex_to_pixel(layout, neighbor)
                        ndx, ndy = c_bx - c_ax, c_by - c_ay
                        nlen = math.hypot(ndx, ndy)
                        if nlen > 0:
                            nx, ny = ndx / nlen, ndy / nlen
                            v1, v2 = hex_edge_vertices(layout, hex_coord, direction)
                            emx = (v1[0] + v2[0]) / 2
                            emy = (v1[1] + v2[1]) / 2
                            dot = (wx - emx) * nx + (wy - emy) * ny
                            raw_sign = 1.0 if dot >= 0 else -1.0
                            # Normal points hex_coord→neighbor; if canonical pair is
                            # (neighbor, hex_coord) the direction is reversed — flip sign.
                            hc_tup = (hex_coord.q, hex_coord.r)
                            nb_tup = (neighbor.q, neighbor.r)
                            if hc_tup > nb_tup:
                                raw_sign = -raw_sign
                            self._hover_offset_sign = raw_sign
                else:
                    self._hover_edge = None

            # Handle drag placement
            if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
                self._place_at_hover(layer, layout)

    def mouse_release(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        if self.mode == "place":
            if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
                self._is_dragging = False
                if self._drag_command and not self._drag_command.is_empty:
                    self._command_stack._undo_stack.append(self._drag_command)
                    self._command_stack._redo_stack.clear()
                    if len(self._command_stack._undo_stack) > self._command_stack._max_size:
                        self._command_stack._undo_stack.pop(0)
                    self._command_stack.stack_changed.emit()
                self._drag_command = None
                self._placed_edges_in_drag.clear()

    def key_press(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete and self._selected:
            layer = self._get_active_border_layer()
            if layer:
                cmd = RemoveBorderCommand(layer, self._selected)
                self._command_stack.execute(cmd)
                self._selected = None
                self._notify_selection()
        elif event.key() == Qt.Key.Key_Escape:
            self._selected = None
            self._notify_selection()

    # --- Overlay rendering ---

    def paint_overlay(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        hover_hex: Hex | None,
    ) -> None:
        # Place mode: highlight hover edge with accurate line style preview
        if self.mode == "place" and self._hover_edge:
            hex_c, direction = self._hover_edge
            v1, v2 = hex_edge_vertices(layout, hex_c, direction)

            # Apply signed offset for preview using canonical hex_a→hex_b direction
            signed_offset = self.offset * self._hover_offset_sign
            if signed_offset != 0.0:
                neighbor = hex_neighbor(hex_c, direction)
                # Canonical pair: (min, max) lexicographically
                hc_tup = (hex_c.q, hex_c.r)
                nb_tup = (neighbor.q, neighbor.r)
                if hc_tup < nb_tup:
                    c_ax, c_ay = hex_to_pixel(layout, hex_c)
                    c_bx, c_by = hex_to_pixel(layout, neighbor)
                else:
                    c_ax, c_ay = hex_to_pixel(layout, neighbor)
                    c_bx, c_by = hex_to_pixel(layout, hex_c)
                ndx, ndy = c_bx - c_ax, c_by - c_ay
                nlen = math.hypot(ndx, ndy)
                if nlen > 0:
                    nx, ny = ndx / nlen, ndy / nlen
                    ox, oy = signed_offset * nx, signed_offset * ny
                    v1 = (v1[0] + ox, v1[1] + oy)
                    v2 = (v2[0] + ox, v2[1] + oy)

            preview_path = QPainterPath()
            preview_path.moveTo(QPointF(v1[0], v1[1]))
            preview_path.lineTo(QPointF(v2[0], v2[1]))

            painter.save()
            painter.setOpacity(0.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # Draw outline preview if enabled
            if self.outline:
                ol_pen = BorderLayer._make_outline_pen(
                    self.outline_color, self.outline_width,
                    self.width, self.line_type,
                    self.element_size, self.gap_size, self.dash_cap,
                )
                painter.setPen(ol_pen)
                painter.drawPath(preview_path)

            # Draw main line preview
            pen = BorderLayer._make_pen(
                self.color, self.width, self.line_type,
                self.element_size, self.gap_size, self.dash_cap,
            )
            painter.setPen(pen)
            painter.drawPath(preview_path)

            painter.restore()

        # Select mode: draw selection highlight
        if self.mode == "select" and self._selected:
            obj = self._selected
            layer = self._get_active_border_layer()
            if layer:
                path = layer._compute_border_path(layout, obj)
                if not path.isEmpty():
                    effective_width = obj.width
                    if obj.line_type == "dotted":
                        effective_width = max(obj.width, obj.element_size)
                    sel_pen = QPen(QColor(0, 120, 255), max(effective_width + 4, 6))
                    sel_pen.setCosmetic(False)
                    sel_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    sel_pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(sel_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
