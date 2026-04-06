"""Text tool - place, move, rotate, scale text objects."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QKeyEvent, QMouseEvent, QPainter, QPen, QPolygonF,
)
from PySide6.QtWidgets import QApplication, QInputDialog

from app.commands.command_stack import CommandStack
from app.commands.text_commands import (
    EditTextCommand,
    MoveTextCommand,
    PlaceTextCommand,
    RemoveTextCommand,
)
from app.hex.hex_math import Hex, Layout
from app.layers.text_layer import TextLayer
from app.models.project import Project
from app.models.text_object import TextObject
from app.tools.base_tool import Tool

# Handle size in screen pixels (constant regardless of zoom)
_HANDLE_SCREEN_PX = 6.0
# Distance of rotation handle above text (in screen pixels)
_ROT_HANDLE_OFFSET_PX = 25.0
# Hit radius for handle detection (screen pixels)
_HANDLE_HIT_RADIUS_PX = 10.0


class TextTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack
        self.mode: str = "place"  # "place" or "select"

        # Text placement settings (used when creating new text objects)
        self.pending_text: str = "Text"
        self.font_family: str = "Arial"
        self.font_size: float = 12.0
        self.bold: bool = False
        self.italic: bool = False
        self.underline: bool = False
        self.color: str = "#000000"
        self.alignment: str = "left"  # "left", "center", "right"
        self.opacity: float = 1.0
        self.rotation: float = 0.0
        self.outline: bool = False
        self.outline_color: str = "#ffffff"
        self.outline_width: float = 1.0
        self.over_grid: bool = False

        # Selection change callback
        self.on_selection_changed = None

        # Selection state
        self._selected: TextObject | None = None
        self._interaction: str | None = None  # "move", "scale", "rotate"
        self._last_world_pos: QPointF = QPointF(0, 0)
        self._cached_inv_scale: float = 1.0

        # Move drag state
        self._drag_start_x: float = 0.0
        self._drag_start_y: float = 0.0
        self._drag_obj_start_x: float = 0.0
        self._drag_obj_start_y: float = 0.0

        # Scale drag state (scales font_size proportionally)
        self._scale_initial_size: float = 12.0
        self._scale_initial_dist: float = 1.0

        # Rotate drag state
        self._rotate_initial: float = 0.0
        self._rotate_initial_angle: float = 0.0

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.mode = "place"
        self.pending_text = "Text"
        self.font_family = "Arial"
        self.font_size = 12.0
        self.bold = False
        self.italic = False
        self.underline = False
        self.color = "#000000"
        self.alignment = "left"
        self.opacity = 1.0
        self.rotation = 0.0
        self.outline = False
        self.outline_color = "#ffffff"
        self.outline_width = 1.0
        self.over_grid = False
        self._selected = None
        self._interaction = None

    @property
    def name(self) -> str:
        return "Text"

    @property
    def cursor(self) -> Qt.CursorShape:
        if self.mode == "place":
            return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.ArrowCursor

    @property
    def selected_text(self) -> TextObject | None:
        return self._selected

    def _get_active_text_layer(self) -> TextLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, TextLayer):
            return layer
        return None

    def _notify_selection(self) -> None:
        """Notify listener that the selected object changed."""
        if self.on_selection_changed:
            self.on_selection_changed(self._selected)

    def _make_preview_object(self, x: float, y: float) -> TextObject:
        """Create a temporary TextObject from current settings for preview."""
        return TextObject(
            text=self.pending_text,
            x=x,
            y=y,
            font_family=self.font_family,
            font_size=self.font_size,
            bold=self.bold,
            italic=self.italic,
            underline=self.underline,
            color=self.color,
            alignment=self.alignment,
            opacity=self.opacity,
            rotation=self.rotation,
            outline=self.outline,
            outline_color=self.outline_color,
            outline_width=self.outline_width,
            over_grid=self.over_grid,
        )

    # --- Handle geometry ---

    def _get_text_corners(self, obj: TextObject) -> list[tuple[float, float]]:
        """Get the 4 rotated corners of the text bounding rect in world coordinates."""
        local = obj._local_text_rect()
        if obj.outline:
            ow = obj.outline_width
            local = local.adjusted(-ow, -ow, ow, ow)

        corners_local = [
            (local.left(), local.top()),
            (local.right(), local.top()),
            (local.right(), local.bottom()),
            (local.left(), local.bottom()),
        ]

        angle_rad = math.radians(obj.rotation)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        return [
            (lx * cos_a - ly * sin_a + obj.x, lx * sin_a + ly * cos_a + obj.y)
            for lx, ly in corners_local
        ]

    def _get_rotation_handle_pos(
        self, obj: TextObject, inv_scale: float
    ) -> tuple[float, float]:
        """Get the rotation handle position above the text."""
        local = obj._local_text_rect()
        top_y = local.top()
        if obj.outline:
            top_y -= obj.outline_width

        offset = abs(top_y) + _ROT_HANDLE_OFFSET_PX * inv_scale
        angle_rad = math.radians(obj.rotation)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        # Local position: (0, -offset) rotated
        rx = -(-offset) * sin_a + obj.x
        ry = (-offset) * cos_a + obj.y
        return (rx, ry)

    def _hit_handle(
        self, wx: float, wy: float, hx: float, hy: float, inv_scale: float
    ) -> bool:
        hit_r = _HANDLE_HIT_RADIUS_PX * inv_scale
        return (wx - hx) ** 2 + (wy - hy) ** 2 <= hit_r ** 2

    def _try_handle_interaction(self, wx: float, wy: float) -> bool:
        """Try to start a handle interaction. Returns True if handled."""
        if not self._selected:
            return False

        inv_scale = self._cached_inv_scale
        obj = self._selected

        # Check rotation handle
        rot_pos = self._get_rotation_handle_pos(obj, inv_scale)
        if self._hit_handle(wx, wy, rot_pos[0], rot_pos[1], inv_scale):
            self._interaction = "rotate"
            self._rotate_initial = obj.rotation
            self._rotate_initial_angle = math.degrees(
                math.atan2(wx - obj.x, -(wy - obj.y))
            )
            return True

        # Check corner handles (scale via font_size)
        corners = self._get_text_corners(obj)
        for cx, cy in corners:
            if self._hit_handle(wx, wy, cx, cy, inv_scale):
                self._interaction = "scale"
                self._scale_initial_size = obj.font_size
                self._scale_initial_dist = math.hypot(wx - obj.x, wy - obj.y)
                if self._scale_initial_dist < 1.0:
                    self._scale_initial_dist = 1.0
                return True

        # Check text body (move)
        if obj.contains_point(wx, wy):
            self._interaction = "move"
            self._drag_start_x = wx
            self._drag_start_y = wy
            self._drag_obj_start_x = obj.x
            self._drag_obj_start_y = obj.y
            return True

        return False

    def _edit_text_dialog(self) -> None:
        """Open input dialog to edit selected text content."""
        if not self._selected:
            return
        parent = QApplication.activeWindow()
        new_text, ok = QInputDialog.getText(
            parent, "Edit Text", "Text:", text=self._selected.text
        )
        if ok and new_text != self._selected.text:
            layer = self._get_active_text_layer()
            if layer:
                cmd = EditTextCommand(layer, self._selected, text=new_text)
                self._command_stack.execute(cmd)

    # --- Mouse handling ---

    def mouse_press(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex
    ) -> None:
        layer = self._get_active_text_layer()
        if layer is None:
            return

        wx, wy = world_pos.x(), world_pos.y()

        if self.mode == "place":
            if event.button() == Qt.MouseButton.LeftButton:
                if not self._project.grid_config.is_within_placement_area(
                    world_pos, hex_coord, allow_border_zone=True
                ):
                    return
                if not self.pending_text:
                    return
                obj = self._make_preview_object(wx, wy)
                cmd = PlaceTextCommand(layer, obj)
                self._command_stack.execute(cmd)
            elif event.button() == Qt.MouseButton.RightButton:
                hit = layer.hit_test(wx, wy)
                if hit:
                    cmd = RemoveTextCommand(layer, hit)
                    self._command_stack.execute(cmd)
        else:
            # Select mode
            if event.button() == Qt.MouseButton.RightButton:
                return
            if event.button() != Qt.MouseButton.LeftButton:
                return

            # Try handle interaction first
            if self._try_handle_interaction(wx, wy):
                return

            # Try selecting a new text object
            hit = layer.hit_test(wx, wy)
            if hit:
                self._selected = hit
                self._interaction = "move"
                self._drag_start_x = wx
                self._drag_start_y = wy
                self._drag_obj_start_x = hit.x
                self._drag_obj_start_y = hit.y
                self._notify_selection()
            else:
                self._selected = None
                self._notify_selection()

    def mouse_double_click(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex
    ) -> None:
        """Handle double-click to edit text content."""
        if self.mode != "select":
            return
        layer = self._get_active_text_layer()
        if layer is None:
            return

        wx, wy = world_pos.x(), world_pos.y()
        hit = layer.hit_test(wx, wy)
        if hit:
            self._selected = hit
            self._notify_selection()
            self._edit_text_dialog()

    def mouse_move(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex
    ) -> bool:
        self._last_world_pos = world_pos

        if not self._selected or not self._interaction:
            # In place mode with pending text, repaint so the ghost preview follows the cursor.
            if self.mode == "place" and self.pending_text:
                return None  # trigger repaint
            return False

        wx, wy = world_pos.x(), world_pos.y()
        obj = self._selected

        if self._interaction == "move":
            dx = wx - self._drag_start_x
            dy = wy - self._drag_start_y
            obj.x = self._drag_obj_start_x + dx
            obj.y = self._drag_obj_start_y + dy

        elif self._interaction == "scale":
            dist = math.hypot(wx - obj.x, wy - obj.y)
            ratio = dist / self._scale_initial_dist
            new_size = max(1.0, self._scale_initial_size * ratio)
            obj.font_size = round(new_size, 1)

        elif self._interaction == "rotate":
            current_angle = math.degrees(
                math.atan2(wx - obj.x, -(wy - obj.y))
            )
            delta = current_angle - self._rotate_initial_angle
            obj.rotation = self._rotate_initial + delta

    def mouse_release(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex
    ) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._interaction:
            return

        if not self._selected:
            self._interaction = None
            return

        layer = self._get_active_text_layer()
        obj = self._selected

        if self._interaction == "move":
            new_x, new_y = obj.x, obj.y
            # Reset to start position for undo support
            obj.x = self._drag_obj_start_x
            obj.y = self._drag_obj_start_y
            if new_x != self._drag_obj_start_x or new_y != self._drag_obj_start_y:
                if layer:
                    cmd = MoveTextCommand(layer, obj, new_x, new_y)
                    self._command_stack.execute(cmd)

        elif self._interaction == "scale":
            new_size = obj.font_size
            obj.font_size = self._scale_initial_size
            if new_size != self._scale_initial_size and layer:
                cmd = EditTextCommand(layer, obj, font_size=new_size)
                self._command_stack.execute(cmd)

        elif self._interaction == "rotate":
            new_rotation = obj.rotation
            obj.rotation = self._rotate_initial
            if new_rotation != self._rotate_initial and layer:
                cmd = EditTextCommand(layer, obj, rotation=new_rotation)
                self._command_stack.execute(cmd)

        self._interaction = None

    def key_press(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete and self._selected:
            layer = self._get_active_text_layer()
            if layer:
                cmd = RemoveTextCommand(layer, self._selected)
                self._command_stack.execute(cmd)
                self._selected = None
                self._notify_selection()
        elif event.key() == Qt.Key.Key_F4 and self._selected:
            self._edit_text_dialog()
        elif event.key() == Qt.Key.Key_Escape:
            self._selected = None
            self._notify_selection()

    def paint_overlay(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        hover_hex: Hex | None,
    ) -> None:
        # Cache inverse scale from painter's world transform
        transform = painter.worldTransform()
        zoom_scale = transform.m11() if transform.m11() > 0 else 1.0
        inv_scale = 1.0 / zoom_scale
        self._cached_inv_scale = inv_scale

        # Draw selection handles on selected text
        if self._selected and self.mode == "select":
            obj = self._selected
            corners = self._get_text_corners(obj)

            # Selection rectangle (dashed blue)
            pen = QPen(QColor(0, 120, 255), 2)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 0, 0, 0))

            poly = QPolygonF([QPointF(x, y) for x, y in corners])
            painter.drawPolygon(poly)

            # Corner scale handles (white squares with blue border)
            handle_size = _HANDLE_SCREEN_PX * inv_scale
            pen_solid = QPen(QColor(0, 120, 255), 1.5)
            pen_solid.setCosmetic(True)
            painter.setPen(pen_solid)
            painter.setBrush(QColor(255, 255, 255))

            for cx, cy in corners:
                painter.drawRect(
                    QRectF(
                        cx - handle_size,
                        cy - handle_size,
                        handle_size * 2,
                        handle_size * 2,
                    )
                )

            # Rotation handle (green circle above text)
            rot_pos = self._get_rotation_handle_pos(obj, inv_scale)
            rot_x, rot_y = rot_pos

            # Line from top center to rotation handle
            top_mid_x = (corners[0][0] + corners[1][0]) / 2
            top_mid_y = (corners[0][1] + corners[1][1]) / 2

            pen_line = QPen(QColor(0, 120, 255), 1)
            pen_line.setCosmetic(True)
            painter.setPen(pen_line)
            painter.drawLine(
                QPointF(top_mid_x, top_mid_y), QPointF(rot_x, rot_y)
            )

            painter.setPen(pen_solid)
            painter.setBrush(QColor(0, 200, 0))
            rot_radius = _HANDLE_SCREEN_PX * inv_scale
            painter.drawEllipse(
                QPointF(rot_x, rot_y), rot_radius, rot_radius
            )

        # Ghost preview in place mode
        if self.mode == "place" and self.pending_text:
            px, py = self._last_world_pos.x(), self._last_world_pos.y()
            preview = self._make_preview_object(px, py)
            preview.opacity = 0.5
            preview.paint(painter)
