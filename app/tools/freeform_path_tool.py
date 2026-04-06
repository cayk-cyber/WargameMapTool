"""Freeform path tool - draw, select, and edit freeform paths."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen

from app.commands.command_stack import CommandStack
from app.commands.freeform_path_commands import (
    MoveFreeformPointCommand,
    PlaceFreeformPathCommand,
    RemoveFreeformPathCommand,
)
from app.hex.hex_math import Hex, Layout
from app.layers.freeform_path_layer import FreeformPathLayer
from app.models.freeform_path_object import FreeformPathObject
from app.models.project import Project
from app.tools.base_tool import Tool

# Handle size in screen pixels
_HANDLE_SCREEN_PX = 5.0
_HANDLE_HIT_RADIUS_PX = 10.0

# Minimum distance between consecutive raw mouse points (world pixels)
_MIN_POINT_DISTANCE = 2.0

# Maximum Douglas-Peucker epsilon (world pixels) at smoothness=1.0
_MAX_DP_EPSILON = 15.0


def _point_to_line_dist(
    px: float, py: float,
    ax: float, ay: float, bx: float, by: float,
) -> float:
    """Perpendicular distance from point (px, py) to line segment (ax, ay)-(bx, by)."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _douglas_peucker(
    points: list[tuple[float, float]], epsilon: float,
) -> list[tuple[float, float]]:
    """Simplify a polyline using the Douglas-Peucker algorithm."""
    if len(points) <= 2:
        return list(points)

    # Find the point farthest from the line between first and last
    dmax = 0.0
    index = 0
    ax, ay = points[0]
    bx, by = points[-1]
    for i in range(1, len(points) - 1):
        d = _point_to_line_dist(points[i][0], points[i][1], ax, ay, bx, by)
        if d > dmax:
            dmax = d
            index = i

    if dmax > epsilon:
        left = _douglas_peucker(points[: index + 1], epsilon)
        right = _douglas_peucker(points[index:], epsilon)
        return left[:-1] + right
    else:
        return [points[0], points[-1]]


class FreeformPathTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack
        self.mode: str = "draw"  # "draw" or "select"

        # Drawing settings
        self.smoothness: float = 0.5
        self.color: str = "#000000"
        self.width: float = 3.0
        self.line_type: str = "solid"
        self.dash_length: float = 6.0
        self.gap_length: float = 4.0
        self.dash_cap: str = "flat"
        self.texture_id: str = ""
        self.texture_zoom: float = 1.0
        self.texture_rotation: float = 0.0
        self.bg_enabled: bool = False
        self.bg_color: str = "#000000"
        self.bg_width: float = 6.0
        self.bg_line_type: str = "solid"
        self.bg_dash_length: float = 6.0
        self.bg_gap_length: float = 4.0
        self.bg_dash_cap: str = "flat"
        self.bg_texture_id: str = ""
        self.bg_texture_zoom: float = 1.0
        self.bg_texture_rotation: float = 0.0
        self.opacity: float = 1.0
        self.bg_opacity: float = 1.0

        # Draw mode state
        self._is_drawing: bool = False
        self._current_points: list[tuple[float, float]] = []

        # Shift+Click straight-line mode state
        self._shift_points: list[tuple[float, float]] = []
        self._hover_world_pos: tuple[float, float] | None = None

        # Select mode state
        self._selected: FreeformPathObject | None = None
        self._interaction: str | None = None  # "drag_point"
        self._drag_point_index: int = -1
        self._drag_initial_pos: tuple[float, float] = (0.0, 0.0)
        self._wp_dragging: bool = False
        self._cached_inv_scale: float = 1.0

        # Selection change callback
        self.on_selection_changed = None

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.mode = "draw"
        self.smoothness = 0.5
        self.color = "#000000"
        self.width = 3.0
        self.line_type = "solid"
        self.dash_length = 6.0
        self.gap_length = 4.0
        self.dash_cap = "flat"
        self.texture_id = ""
        self.texture_zoom = 1.0
        self.texture_rotation = 0.0
        self.bg_enabled = False
        self.bg_color = "#000000"
        self.bg_width = 6.0
        self.bg_line_type = "solid"
        self.bg_dash_length = 6.0
        self.bg_gap_length = 4.0
        self.bg_dash_cap = "flat"
        self.bg_texture_id = ""
        self.bg_texture_zoom = 1.0
        self.bg_texture_rotation = 0.0
        self.opacity = 1.0
        self.bg_opacity = 1.0
        self._is_drawing = False
        self._current_points = []
        self._shift_points = []
        self._hover_world_pos = None
        self._selected = None
        self._interaction = None
        self._wp_dragging = False

    @property
    def name(self) -> str:
        return "Path (Freeform)"

    @property
    def cursor(self) -> Qt.CursorShape:
        if self.mode == "draw":
            return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.ArrowCursor

    def _notify_selection(self) -> None:
        """Notify listener that the selected object changed."""
        if self.on_selection_changed:
            self.on_selection_changed(self._selected)

    def _get_active_layer(self) -> FreeformPathLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, FreeformPathLayer):
            return layer
        return None

    # --- Mouse events ---

    def mouse_press(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        layer = self._get_active_layer()
        if layer is None:
            return

        wx, wy = world_pos.x(), world_pos.y()

        if self.mode == "draw":
            if event.button() == Qt.MouseButton.LeftButton:
                if not self._project.grid_config.is_within_placement_area(
                    world_pos, hex_coord, allow_border_zone=True
                ):
                    return
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                if shift:
                    # Shift+Click: accumulate straight-line points
                    self._shift_points.append((wx, wy))
                elif self._shift_points:
                    # Click without Shift while polyline pending: add final
                    # point and commit straight-line path.
                    self._shift_points.append((wx, wy))
                    self._commit_shift_path(layer)
                else:
                    # Normal freehand draw
                    self._is_drawing = True
                    self._current_points = [(wx, wy)]

            elif event.button() == Qt.MouseButton.RightButton:
                if self._shift_points:
                    # Cancel pending polyline
                    self._shift_points.clear()
                    return
                hit = layer.hit_test(wx, wy)
                if hit:
                    cmd = RemoveFreeformPathCommand(layer, hit)
                    self._command_stack.execute(cmd)

        else:  # select mode
            if event.button() != Qt.MouseButton.LeftButton:
                return

            # Check if clicking on a waypoint of the selected path
            if self._selected:
                for i, (px, py) in enumerate(self._selected.points):
                    if self._hit_handle(wx, wy, px, py):
                        self._interaction = "drag_point"
                        self._drag_point_index = i
                        self._drag_initial_pos = (px, py)
                        # Hide dragged object from layer cache and rebuild once
                        self._wp_dragging = True
                        layer._drag_hidden_keys = {self._selected.id}
                        layer.mark_dirty()
                        return

            # Try selecting a path
            hit = layer.hit_test(wx, wy)
            if hit:
                self._selected = hit
            else:
                self._selected = None
            self._interaction = None
            self._notify_selection()

    def mouse_move(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> bool | None:
        wx, wy = world_pos.x(), world_pos.y()
        self._hover_world_pos = (wx, wy)

        if self.mode == "draw":
            # Repaint for shift-point hover line
            if self._shift_points:
                return None  # always repaint
            if self._is_drawing and (event.buttons() & Qt.MouseButton.LeftButton):
                # Distance-based sampling to avoid excessive points
                if self._current_points:
                    last_x, last_y = self._current_points[-1]
                    dist = math.hypot(wx - last_x, wy - last_y)
                    if dist < _MIN_POINT_DISTANCE:
                        return
                self._current_points.append((wx, wy))

        elif self.mode == "select":
            if self._interaction == "drag_point" and self._selected:
                layer = self._get_active_layer()
                if layer and 0 <= self._drag_point_index < len(self._selected.points):
                    self._selected.points[self._drag_point_index] = (wx, wy)
                    self._selected.increment_points_version()

    def mouse_release(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        if self.mode == "draw":
            if event.button() == Qt.MouseButton.LeftButton and self._is_drawing:
                self._is_drawing = False

                # Need at least 2 points
                if len(self._current_points) < 2:
                    self._current_points.clear()
                    return

                # Apply Douglas-Peucker simplification
                epsilon = self.smoothness * _MAX_DP_EPSILON
                if epsilon > 0:
                    simplified = _douglas_peucker(self._current_points, epsilon)
                else:
                    simplified = list(self._current_points)

                # Need at least 2 points after simplification
                if len(simplified) < 2:
                    self._current_points.clear()
                    return

                layer = self._get_active_layer()
                if layer is None:
                    self._current_points.clear()
                    return

                obj = FreeformPathObject(
                    points=simplified,
                    smoothness=self.smoothness,
                    color=self.color,
                    width=self.width,
                    line_type=self.line_type,
                    dash_length=self.dash_length,
                    gap_length=self.gap_length,
                    dash_cap=self.dash_cap,
                    texture_id=self.texture_id,
                    texture_zoom=self.texture_zoom,
                    texture_rotation=self.texture_rotation,
                    bg_enabled=self.bg_enabled,
                    bg_color=self.bg_color,
                    bg_width=self.bg_width,
                    bg_line_type=self.bg_line_type,
                    bg_dash_length=self.bg_dash_length,
                    bg_gap_length=self.bg_gap_length,
                    bg_dash_cap=self.bg_dash_cap,
                    bg_texture_id=self.bg_texture_id,
                    bg_texture_zoom=self.bg_texture_zoom,
                    bg_texture_rotation=self.bg_texture_rotation,
                    opacity=self.opacity,
                    bg_opacity=self.bg_opacity,
                )

                cmd = PlaceFreeformPathCommand(layer, obj)
                self._command_stack.execute(cmd)
                self._current_points.clear()

        elif self.mode == "select":
            if event.button() == Qt.MouseButton.LeftButton and self._interaction == "drag_point":
                self._wp_dragging = False
                if self._selected:
                    layer = self._get_active_layer()
                    # Clear drag preview state before command (which calls mark_dirty)
                    if layer:
                        layer._drag_hidden_keys = set()
                    idx = self._drag_point_index
                    if layer and 0 <= idx < len(self._selected.points):
                        new_pos = self._selected.points[idx]
                        # Reset to initial for undo
                        self._selected.points[idx] = self._drag_initial_pos
                        self._selected.increment_points_version()
                        if new_pos != self._drag_initial_pos:
                            cmd = MoveFreeformPointCommand(
                                layer, self._selected, idx,
                                self._drag_initial_pos, new_pos,
                            )
                            self._command_stack.execute(cmd)
                        else:
                            layer.mark_dirty()  # Rebuild cache with all objects visible
                self._interaction = None

    def key_press(self, event: QKeyEvent) -> None:
        # Straight-line polyline: Enter = commit, Escape = cancel
        if self._shift_points:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                layer = self._get_active_layer()
                if layer:
                    self._commit_shift_path(layer)
                return
            if event.key() == Qt.Key.Key_Escape:
                self._shift_points.clear()
                return

        if event.key() == Qt.Key.Key_Delete and self._selected:
            layer = self._get_active_layer()
            if layer:
                cmd = RemoveFreeformPathCommand(layer, self._selected)
                self._command_stack.execute(cmd)
                self._selected = None
                self._notify_selection()
        elif event.key() == Qt.Key.Key_Escape:
            self._selected = None
            self._notify_selection()

    def _commit_shift_path(self, layer: FreeformPathLayer) -> None:
        """Commit the pending Shift+Click points as a straight-line path."""
        pts = self._shift_points
        self._shift_points = []
        if len(pts) < 2:
            return
        obj = FreeformPathObject(
            points=pts,
            smoothness=self.smoothness,
            straight=True,
            color=self.color,
            width=self.width,
            line_type=self.line_type,
            dash_length=self.dash_length,
            gap_length=self.gap_length,
            dash_cap=self.dash_cap,
            texture_id=self.texture_id,
            texture_zoom=self.texture_zoom,
            texture_rotation=self.texture_rotation,
            bg_enabled=self.bg_enabled,
            bg_color=self.bg_color,
            bg_width=self.bg_width,
            bg_line_type=self.bg_line_type,
            bg_dash_length=self.bg_dash_length,
            bg_gap_length=self.bg_gap_length,
            bg_dash_cap=self.bg_dash_cap,
            bg_texture_id=self.bg_texture_id,
            bg_texture_zoom=self.bg_texture_zoom,
            bg_texture_rotation=self.bg_texture_rotation,
            opacity=self.opacity,
            bg_opacity=self.bg_opacity,
        )
        cmd = PlaceFreeformPathCommand(layer, obj)
        self._command_stack.execute(cmd)

    # --- Overlay rendering ---

    def paint_overlay(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        hover_hex: Hex | None,
    ) -> None:
        # Cache inverse scale
        transform = painter.worldTransform()
        zoom_scale = transform.m11() if transform.m11() > 0 else 1.0
        self._cached_inv_scale = 1.0 / zoom_scale

        # Draw mode: render live preview of current stroke
        if self.mode == "draw" and self._is_drawing and len(self._current_points) >= 2:
            preview_color = QColor(self.color)
            preview_color.setAlpha(128)
            pen = QPen(preview_color, max(self.width, 2.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # Draw as polyline for performance during live drawing
            for i in range(len(self._current_points) - 1):
                x1, y1 = self._current_points[i]
                x2, y2 = self._current_points[i + 1]
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Shift+Click straight-line preview
        if self.mode == "draw" and len(self._shift_points) >= 1:
            inv_scale = self._cached_inv_scale
            preview_color = QColor(self.color)
            preview_color.setAlpha(128)
            pen = QPen(preview_color, max(self.width, 2.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            for i in range(len(self._shift_points) - 1):
                x1, y1 = self._shift_points[i]
                x2, y2 = self._shift_points[i + 1]
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            # Draw hover line from last point to mouse position
            if self._hover_world_pos:
                lx, ly = self._shift_points[-1]
                hx, hy = self._hover_world_pos

                # Outer shadow line for readability
                pen_shadow = QPen(QColor(0, 0, 0, 160), 3.0 * inv_scale)
                pen_shadow.setStyle(Qt.PenStyle.DashLine)
                pen_shadow.setCosmetic(True)
                painter.setPen(pen_shadow)
                painter.drawLine(QPointF(lx, ly), QPointF(hx, hy))

                # White dashed line on top
                pen_line = QPen(QColor(255, 255, 255, 220), 1.5 * inv_scale)
                pen_line.setStyle(Qt.PenStyle.DashLine)
                pen_line.setCosmetic(True)
                painter.setPen(pen_line)
                painter.drawLine(QPointF(lx, ly), QPointF(hx, hy))

            # Draw point handles
            handle_r = _HANDLE_SCREEN_PX * inv_scale
            painter.setPen(QPen(QColor(0, 120, 215), 1.5 * inv_scale))
            painter.setBrush(QColor(0, 120, 215, 140))
            for px, py in self._shift_points:
                painter.drawEllipse(QPointF(px, py), handle_r, handle_r)

        # Select mode: draw waypoint handles
        if self.mode == "select" and self._selected:
            obj = self._selected
            inv_scale = self._cached_inv_scale

            # During waypoint drag: render dragged path as overlay preview
            # (layer cache has it hidden via _drag_hidden_keys)
            if self._wp_dragging:
                layer = self._get_active_layer()
                if layer:
                    path = layer._get_cached_freeform_path(obj)
                    if not path.isEmpty():
                        # Background pass
                        if obj.bg_enabled:
                            painter.save()
                            if obj.bg_opacity < 1.0:
                                painter.setOpacity(obj.bg_opacity)
                            bg_pen = FreeformPathLayer._make_pen(
                                obj.bg_color, obj.bg_width, obj.bg_line_type,
                                obj.bg_dash_length, obj.bg_gap_length,
                                obj.bg_texture_id, obj.bg_texture_zoom,
                                obj.bg_texture_rotation, obj.bg_dash_cap,
                            )
                            painter.setPen(bg_pen)
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawPath(path)
                            painter.restore()
                        # Foreground pass
                        painter.save()
                        if obj.opacity < 1.0:
                            painter.setOpacity(obj.opacity)
                        fg_pen = FreeformPathLayer._make_pen(
                            obj.color, obj.width, obj.line_type,
                            obj.dash_length, obj.gap_length,
                            obj.texture_id, obj.texture_zoom,
                            obj.texture_rotation, obj.dash_cap,
                        )
                        painter.setPen(fg_pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawPath(path)
                        painter.restore()

            # Draw waypoint handles
            handle_radius = _HANDLE_SCREEN_PX * inv_scale

            painter.setPen(QPen(QColor(180, 0, 0), 1.5 * inv_scale))
            painter.setBrush(QColor(255, 60, 60))

            for px, py in obj.points:
                painter.drawEllipse(
                    QPointF(px, py), handle_radius, handle_radius,
                )

    def _hit_handle(
        self, wx: float, wy: float, hx: float, hy: float,
    ) -> bool:
        hit_r = _HANDLE_HIT_RADIUS_PX * self._cached_inv_scale
        return (wx - hx) ** 2 + (wy - hy) ** 2 <= hit_r ** 2
