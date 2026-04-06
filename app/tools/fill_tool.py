"""Fill tool - click or drag to fill hexes with color or texture."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QMouseEvent, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF, QTransform,
)
from PySide6.QtWidgets import QWidget

from app.commands.command import CompoundCommand
from app.commands.command_stack import CommandStack
from app.commands.fill_commands import (
    ClearCoordColorCommand,
    ClearDotColorCommand,
    ClearHexEdgeCommand,
    ClearHexFillCommand,
    ClearHexTextureCommand,
    SetCoordColorCommand,
    SetDotColorCommand,
    SetHexEdgeCommand,
    SetHexFillCommand,
    SetHexTextureCommand,
)
from app.hex.hex_math import Hex, Layout, axial_to_offset, hex_corners, hex_distance, hex_to_pixel
from app.io import texture_cache
from app.layers.fill_layer import FillLayer, HexEdgeFill, HexTexture, _compute_inset_polygon
from app.models.project import Project
from app.tools.base_tool import Tool


class FillTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack
        self.current_color: QColor = QColor("#c3d89b")
        self.fill_radius: int = 0
        self.paint_mode: str = "hex_fill"  # "hex_fill", "dot_color", "coord_color", "texture", or "hex_edge"
        self.edge_width: float = 2.0  # Edge fill width in world units (mm)
        self.edge_outline: bool = False  # Whether to draw inner outline
        self.edge_outline_color: QColor = QColor("#000000")
        self.edge_outline_width: float = 0.5  # Outline width in mm
        # Texture state
        self.current_texture_id: str | None = None
        self.texture_zoom: float = 1.0
        self.texture_offset_x: float = 0.0
        self.texture_offset_y: float = 0.0
        self.texture_rotation: float = 0.0
        self._is_dragging = False
        self._drag_command: CompoundCommand | None = None
        self._filled_hexes_in_drag: set[Hex] = set()

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.current_color = QColor("#c3d89b")
        self.fill_radius = 0
        self.paint_mode = "hex_fill"
        self.edge_width = 2.0
        self.edge_outline = False
        self.edge_outline_color = QColor("#000000")
        self.edge_outline_width = 0.5
        self.current_texture_id = None
        self.texture_zoom = 1.0
        self.texture_offset_x = 0.0
        self.texture_offset_y = 0.0
        self.texture_rotation = 0.0
        self._is_dragging = False
        self._drag_command = None
        self._filled_hexes_in_drag = set()

    @property
    def name(self) -> str:
        return "Fill"

    @property
    def cursor(self) -> Qt.CursorShape:
        return Qt.CursorShape.CrossCursor

    def _get_active_fill_layer(self) -> FillLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, FillLayer):
            return layer
        return None

    def _is_valid(self, hex_coord: Hex) -> bool:
        return self._project.grid_config.is_valid_hex(hex_coord)

    def _get_hexes_in_radius(self, center: Hex, radius: int) -> list[Hex]:
        """Return all valid hexes within the given radius of center."""
        if radius <= 0:
            if self._is_valid(center):
                return [center]
            return []
        results = []
        for q in range(center.q - radius, center.q + radius + 1):
            for r in range(center.r - radius, center.r + radius + 1):
                h = Hex(q, r)
                if hex_distance(center, h) <= radius and self._is_valid(h):
                    results.append(h)
        return results

    def mouse_press(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        layer = self._get_active_fill_layer()
        if layer is None:
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_command = CompoundCommand("Fill hexes")
            self._filled_hexes_in_drag = set()
            for h in self._get_hexes_in_radius(hex_coord, self.fill_radius):
                self._fill_hex(layer, h)
        elif event.button() == Qt.MouseButton.RightButton:
            for h in self._get_hexes_in_radius(hex_coord, self.fill_radius):
                if self.paint_mode == "hex_edge":
                    cmd = ClearHexEdgeCommand(layer, h)
                elif self.paint_mode == "texture":
                    cmd = ClearHexTextureCommand(layer, h)
                elif self.paint_mode == "dot_color":
                    cmd = ClearDotColorCommand(layer, h)
                elif self.paint_mode == "coord_color":
                    cmd = ClearCoordColorCommand(layer, h)
                else:
                    cmd = ClearHexFillCommand(layer, h)
                self._command_stack.execute(cmd)

    def mouse_move(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> bool:
        if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            layer = self._get_active_fill_layer()
            if layer is not None:
                for h in self._get_hexes_in_radius(hex_coord, self.fill_radius):
                    self._fill_hex(layer, h)
            return True
        # Hover only: hex highlight is handled by canvas hover_changed check.
        return False

    def mouse_release(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            if self._drag_command and not self._drag_command.is_empty:
                self._command_stack._undo_stack.append(self._drag_command)
                self._command_stack._redo_stack.clear()
                if len(self._command_stack._undo_stack) > self._command_stack._max_size:
                    self._command_stack._undo_stack.pop(0)
                self._command_stack.stack_changed.emit()
            self._drag_command = None
            self._filled_hexes_in_drag.clear()

    def _fill_hex(self, layer: FillLayer, hex_coord: Hex) -> None:
        if hex_coord in self._filled_hexes_in_drag:
            return
        self._filled_hexes_in_drag.add(hex_coord)

        if self.paint_mode == "hex_edge":
            edge = HexEdgeFill(
                color=self.current_color.name(),
                width=self.edge_width,
                outline=self.edge_outline,
                outline_color=self.edge_outline_color.name(),
                outline_width=self.edge_outline_width,
            )
            cmd = SetHexEdgeCommand(layer, hex_coord, edge)
        elif self.paint_mode == "texture":
            if self.current_texture_id is None:
                return
            tex = HexTexture(
                texture_id=self.current_texture_id,
                zoom=self.texture_zoom,
                offset_x=self.texture_offset_x,
                offset_y=self.texture_offset_y,
                rotation=self.texture_rotation,
            )
            cmd = SetHexTextureCommand(layer, hex_coord, tex)
        elif self.paint_mode == "dot_color":
            cmd = SetDotColorCommand(layer, hex_coord, self.current_color)
        elif self.paint_mode == "coord_color":
            cmd = SetCoordColorCommand(layer, hex_coord, self.current_color)
        else:
            cmd = SetHexFillCommand(layer, hex_coord, self.current_color)
        cmd.execute()
        if self._drag_command:
            self._drag_command._commands.append(cmd)

    def paint_overlay(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        hover_hex: Hex | None,
    ) -> None:
        if hover_hex is None:
            return

        hexes = self._get_hexes_in_radius(hover_hex, self.fill_radius)
        if not hexes:
            return

        if self.paint_mode == "hex_edge":
            preview_color = QColor(self.current_color)
            preview_color.setAlpha(128)
            for h in hexes:
                corners = hex_corners(layout, h)
                polygon = QPolygonF([QPointF(x, y) for x, y in corners])
                clip_path = QPainterPath()
                clip_path.addPolygon(polygon)
                clip_path.closeSubpath()
                painter.save()
                painter.setClipPath(clip_path)
                pen = QPen(preview_color, self.edge_width * 2)
                pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(polygon)
                # Preview outline on inset boundary
                if self.edge_outline:
                    cx, cy = hex_to_pixel(layout, h)
                    inset = _compute_inset_polygon(
                        cx, cy, corners, self.edge_width
                    )
                    if inset is not None:
                        ol_color = QColor(self.edge_outline_color)
                        ol_color.setAlpha(180)
                        ol_pen = QPen(ol_color, self.edge_outline_width)
                        ol_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                        painter.setPen(ol_pen)
                        painter.drawPolygon(inset)
                painter.restore()
        elif self.paint_mode == "dot_color":
            # Show colored dots at hex centers
            dot_size = self._project.grid_config.center_dot_size + 2
            pen = QPen(self.current_color, dot_size)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for h in hexes:
                cx, cy = hex_to_pixel(layout, h)
                painter.drawPoint(QPointF(cx, cy))
        elif self.paint_mode == "coord_color":
            # Show colored coordinate text at hex centers
            config = self._project.grid_config
            font = QFont("Arial", 8)
            font.setPixelSize(max(6, int(config.hex_size * config.coord_font_scale / 100.0)))
            painter.setFont(font)
            painter.setPen(QPen(self.current_color))
            y_offset = config.coord_offset_y * config.hex_size
            for h in hexes:
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
                    cx - config.hex_size * 0.5, text_y,
                    config.hex_size, config.hex_size * 0.3,
                )
                painter.drawText(text_rect, int(alignment), label)
        elif self.paint_mode == "texture" and self.current_texture_id:
            image = texture_cache.get_texture_image(self.current_texture_id)
            if image and not image.isNull():
                pixmap = QPixmap.fromImage(image)
                brush = QBrush(pixmap)
                brush_xf = QTransform()
                if self.texture_offset_x != 0.0 or self.texture_offset_y != 0.0:
                    brush_xf.translate(self.texture_offset_x, self.texture_offset_y)
                if self.texture_rotation != 0.0:
                    brush_xf.rotate(self.texture_rotation)
                if self.texture_zoom != 1.0:
                    brush_xf.scale(self.texture_zoom, self.texture_zoom)
                brush.setTransform(brush_xf)

                painter.save()
                painter.setOpacity(0.5)
                painter.setBrush(brush)
                painter.setPen(Qt.PenStyle.NoPen)
                for h in hexes:
                    corners = hex_corners(layout, h)
                    polygon = QPolygonF([QPointF(x, y) for x, y in corners])
                    clip_path = QPainterPath()
                    clip_path.addPolygon(polygon)
                    clip_path.closeSubpath()
                    painter.drawPath(clip_path)
                painter.restore()
            else:
                # No image available - show dashed outline
                highlight = QColor(128, 128, 128, 80)
                painter.setBrush(highlight)
                pen = QPen(QColor(128, 128, 128), 2)
                pen.setCosmetic(True)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                for h in hexes:
                    corners = hex_corners(layout, h)
                    polygon = QPolygonF([QPointF(x, y) for x, y in corners])
                    painter.drawPolygon(polygon)
        else:
            highlight_color = QColor(self.current_color)
            highlight_color.setAlpha(80)
            painter.setBrush(highlight_color)

            pen = QPen(self.current_color, 2)
            pen.setCosmetic(True)
            painter.setPen(pen)

            for h in hexes:
                corners = hex_corners(layout, h)
                polygon = QPolygonF([QPointF(x, y) for x, y in corners])
                painter.drawPolygon(polygon)
