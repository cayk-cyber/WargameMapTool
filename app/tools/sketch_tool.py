"""Sketch tool - draw and edit geometric shapes for administrative overlays."""

from __future__ import annotations

import copy
import math
import uuid

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
)

from app.commands.command_stack import CommandStack
from app.commands.sketch_commands import (
    MoveSketchCommand,
    PlaceSketchCommand,
    RemoveSketchCommand,
    ResizeSketchCommand,
    RotateSketchCommand,
)
from app.hex.hex_math import (
    Hex,
    Layout,
    hex_corners,
    hex_neighbor,
    hex_to_pixel,
    pixel_to_hex,
    snap_to_grid,
)
from app.layers.sketch_layer import SketchLayer
from app.models.project import Project
from app.models.sketch_object import SketchObject
from app.tools.base_tool import Tool

# Handle constants (screen pixels)
_HANDLE_SCREEN_PX = 6.0
_ROT_HANDLE_OFFSET_PX = 25.0
_HANDLE_HIT_RADIUS_PX = 10.0

# Drawing constants
_MIN_POINT_DISTANCE = 2.0
_MIN_SHAPE_SIZE = 3.0
_MAX_DP_EPSILON = 15.0


def _point_to_line_dist(
    px: float, py: float,
    ax: float, ay: float, bx: float, by: float,
) -> float:
    """Perpendicular distance from point to segment."""
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
    """Simplify a polyline using Douglas-Peucker."""
    if len(points) <= 2:
        return list(points)
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
    return [points[0], points[-1]]


class SketchTool(Tool):
    # Class-level clipboard: persists across tool mode changes within one session
    _clipboard: SketchObject | None = None

    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack
        self.mode: str = "draw"  # "draw" or "select"

        # Drawing settings
        self.shape_type: str = "rect"
        self.stroke_color: str = "#000000"
        self.stroke_width: float = 2.0
        self.stroke_type: str = "solid"
        self.dash_length: float = 8.0
        self.gap_length: float = 4.0
        self.stroke_cap: str = "round"
        self.fill_enabled: bool = False
        self.fill_color: str = "#ffff00"
        self.fill_opacity: float = 0.3
        self.fill_type: str = "color"
        self.fill_texture_id: str = ""
        self.fill_texture_zoom: float = 1.0
        self.fill_texture_rotation: float = 0.0
        self.rotation: float = 0.0
        self.num_sides: int = 6
        self.closed: bool = False
        self.snap_to_grid: bool = False
        self.perfect_circle: bool = False

        # Render order
        self.draw_over_grid: bool = False

        # Selection change callback
        self.on_selection_changed = None

        # Draw state
        self._is_drawing: bool = False
        self._draw_start: tuple[float, float] = (0.0, 0.0)
        self._draw_current: tuple[float, float] = (0.0, 0.0)
        self._freehand_points: list[tuple[float, float]] = []

        # Select state
        self._selected: SketchObject | None = None
        self._interaction: str | None = None  # "move", "resize", "rotate"
        self._cached_inv_scale: float = 1.0

        # Move drag
        self._drag_start: tuple[float, float] = (0.0, 0.0)
        self._drag_obj_points: list[tuple[float, float]] = []

        # Resize drag
        self._resize_handle_index: int = -1
        self._resize_old_points: list[tuple[float, float]] = []
        self._resize_old_radius: float = 0.0
        self._resize_old_rx: float = 0.0
        self._resize_old_ry: float = 0.0
        self._resize_anchor: tuple[float, float] = (0.0, 0.0)

        # Rotate drag
        self._rotate_initial: float = 0.0
        self._rotate_initial_angle: float = 0.0

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.mode = "draw"
        self.shape_type = "rect"
        self.stroke_color = "#000000"
        self.stroke_width = 2.0
        self.stroke_type = "solid"
        self.dash_length = 8.0
        self.gap_length = 4.0
        self.stroke_cap = "round"
        self.fill_enabled = False
        self.fill_color = "#ffff00"
        self.fill_opacity = 0.3
        self.fill_type = "color"
        self.fill_texture_id = ""
        self.fill_texture_zoom = 1.0
        self.fill_texture_rotation = 0.0
        self.rotation = 0.0
        self.num_sides = 6
        self.closed = False
        self.snap_to_grid = False
        self.perfect_circle = False
        self.draw_over_grid = False
        self._is_drawing = False
        self._freehand_points = []
        self._selected = None
        self._interaction = None

    @property
    def name(self) -> str:
        return "Sketch"

    @property
    def cursor(self) -> Qt.CursorShape:
        if self.mode == "draw":
            return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.ArrowCursor

    @property
    def selected(self) -> SketchObject | None:
        return self._selected

    def _get_active_layer(self) -> SketchLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, SketchLayer):
            return layer
        return None

    def _notify_selection(self) -> None:
        """Notify listener that the selected object changed."""
        if self.on_selection_changed:
            self.on_selection_changed(self._selected)

    def _copy_object(self, obj: SketchObject) -> SketchObject:
        """Return a fully independent copy of a SketchObject with a fresh id."""
        new_obj = copy.copy(obj)
        new_obj.points = list(obj.points)
        new_obj.id = uuid.uuid4().hex[:8]
        new_obj._path_cache = None
        new_obj._path_cache_key = None
        return new_obj

    def _snap(self, wx: float, wy: float) -> tuple[float, float]:
        """Apply grid snapping if enabled."""
        if not self.snap_to_grid:
            return (wx, wy)
        cfg = self._project.grid_config
        layout = cfg.create_layout()
        return snap_to_grid(layout, wx, wy, cfg.width, cfg.height, cfg.orientation, cfg.first_row_offset)

    # --- Select mode handle geometry ---

    def _get_corners(self, obj: SketchObject) -> list[tuple[float, float]]:
        """Get 4 bounding box corners of a sketch object, rotated."""
        path = obj.build_path()
        rect = path.boundingRect()
        if rect.isEmpty():
            cx, cy = obj.center()
            return [(cx, cy)] * 4

        margin = obj.stroke_width / 2.0
        rect = rect.adjusted(-margin, -margin, margin, margin)

        corners_local = [
            (rect.left(), rect.top()),
            (rect.right(), rect.top()),
            (rect.right(), rect.bottom()),
            (rect.left(), rect.bottom()),
        ]

        cx, cy = obj.center()
        if obj.rotation == 0.0:
            return corners_local

        angle_rad = math.radians(obj.rotation)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        return [
            (
                cos_a * (lx - cx) - sin_a * (ly - cy) + cx,
                sin_a * (lx - cx) + cos_a * (ly - cy) + cy,
            )
            for lx, ly in corners_local
        ]

    def _get_rotation_handle_pos(
        self, obj: SketchObject, inv_scale: float,
    ) -> tuple[float, float]:
        """Get rotation handle position above the shape."""
        corners = self._get_corners(obj)
        top_mid_x = (corners[0][0] + corners[1][0]) / 2.0
        top_mid_y = (corners[0][1] + corners[1][1]) / 2.0
        cx, cy = obj.center()

        # Direction from center to top-mid
        dx = top_mid_x - cx
        dy = top_mid_y - cy
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            dx, dy = 0.0, -1.0
            dist = 1.0

        offset = _ROT_HANDLE_OFFSET_PX * inv_scale
        nx, ny = dx / dist, dy / dist
        return (top_mid_x + nx * offset, top_mid_y + ny * offset)

    def _hit_handle(
        self, wx: float, wy: float, hx: float, hy: float,
    ) -> bool:
        hit_r = _HANDLE_HIT_RADIUS_PX * self._cached_inv_scale
        return (wx - hx) ** 2 + (wy - hy) ** 2 <= hit_r ** 2

    def _try_handle_interaction(self, wx: float, wy: float) -> bool:
        """Try to start a handle interaction. Returns True if handled."""
        if not self._selected:
            return False

        obj = self._selected

        # Check rotation handle
        rot_pos = self._get_rotation_handle_pos(obj, self._cached_inv_scale)
        if self._hit_handle(wx, wy, rot_pos[0], rot_pos[1]):
            self._interaction = "rotate"
            self._rotate_initial = obj.rotation
            cx, cy = obj.center()
            self._rotate_initial_angle = math.degrees(
                math.atan2(wx - cx, -(wy - cy))
            )
            return True

        # Check corner handles (resize)
        corners = self._get_corners(obj)
        for i, (cx, cy) in enumerate(corners):
            if self._hit_handle(wx, wy, cx, cy):
                self._interaction = "resize"
                self._resize_handle_index = i
                self._resize_old_points = list(obj.points)
                self._resize_old_radius = obj.radius
                self._resize_old_rx = obj.rx
                self._resize_old_ry = obj.ry
                # Anchor is the opposite corner
                opp = (i + 2) % 4
                self._resize_anchor = corners[opp]
                return True

        # Check shape body (move)
        if obj.contains_point(wx, wy):
            self._interaction = "move"
            self._drag_start = (wx, wy)
            self._drag_obj_points = list(obj.points)
            return True

        return False

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
                sx, sy = self._snap(wx, wy)
                self._is_drawing = True

                if self.shape_type == "freehand":
                    self._freehand_points = [(sx, sy)]
                else:
                    self._draw_start = (sx, sy)
                    self._draw_current = (sx, sy)

            elif event.button() == Qt.MouseButton.RightButton:
                hit = layer.hit_test(wx, wy)
                if hit:
                    cmd = RemoveSketchCommand(layer, hit)
                    self._command_stack.execute(cmd)

        else:  # select mode
            if event.button() != Qt.MouseButton.LeftButton:
                return

            # Try handle interaction first
            if self._try_handle_interaction(wx, wy):
                return

            # Try selecting a new object
            hit = layer.hit_test(wx, wy)
            if hit:
                self._selected = hit
                self._notify_selection()
                self._interaction = "move"
                self._drag_start = (wx, wy)
                self._drag_obj_points = list(hit.points)
            else:
                self._selected = None
                self._notify_selection()
                self._interaction = None

    def mouse_move(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        wx, wy = world_pos.x(), world_pos.y()

        if self.mode == "draw" and self._is_drawing:
            if self.shape_type == "freehand":
                if self._freehand_points:
                    last_x, last_y = self._freehand_points[-1]
                    if math.hypot(wx - last_x, wy - last_y) >= _MIN_POINT_DISTANCE:
                        self._freehand_points.append((wx, wy))
            else:
                sx, sy = self._snap(wx, wy)
                self._draw_current = (sx, sy)

        elif self.mode == "select" and self._selected and self._interaction:
            obj = self._selected
            layer = self._get_active_layer()
            if not layer:
                return

            if self._interaction == "move":
                dx = wx - self._drag_start[0]
                dy = wy - self._drag_start[1]
                obj.points = [
                    (p[0] + dx, p[1] + dy) for p in self._drag_obj_points
                ]
                layer.mark_dirty()

            elif self._interaction == "resize":
                self._apply_resize(obj, wx, wy)
                layer.mark_dirty()

            elif self._interaction == "rotate":
                cx, cy = obj.center()
                current_angle = math.degrees(
                    math.atan2(wx - cx, -(wy - cy))
                )
                delta = current_angle - self._rotate_initial_angle
                obj.rotation = self._rotate_initial + delta
                layer.mark_dirty()

    def _apply_resize(self, obj: SketchObject, wx: float, wy: float) -> None:
        """Apply resize based on drag from corner handle."""
        cx, cy = obj.center()

        # Un-rotate the mouse position relative to shape center
        if obj.rotation != 0.0:
            rad = -math.radians(obj.rotation)
            dx, dy = wx - cx, wy - cy
            wx = cx + dx * math.cos(rad) - dy * math.sin(rad)
            wy = cy + dx * math.sin(rad) + dy * math.cos(rad)

        # Un-rotate the anchor
        ax, ay = self._resize_anchor
        if obj.rotation != 0.0:
            rad = -math.radians(obj.rotation)
            dx, dy = ax - cx, ay - cy
            ax = cx + dx * math.cos(rad) - dy * math.sin(rad)
            ay = cy + dx * math.sin(rad) + dy * math.cos(rad)

        st = obj.shape_type
        if st in ("line", "rect"):
            # Map the two points
            old_p = self._resize_old_points
            if len(old_p) < 2:
                return

            # Compute scale from old bbox to new bbox
            old_xs = [p[0] for p in old_p]
            old_ys = [p[1] for p in old_p]
            old_w = max(old_xs) - min(old_xs)
            old_h = max(old_ys) - min(old_ys)
            old_cx = (min(old_xs) + max(old_xs)) / 2
            old_cy = (min(old_ys) + max(old_ys)) / 2

            new_w = abs(wx - ax)
            new_h = abs(wy - ay)
            new_cx = (wx + ax) / 2
            new_cy = (wy + ay) / 2

            if old_w > 0 and old_h > 0:
                sx = new_w / old_w
                sy = new_h / old_h
                obj.points = [
                    (new_cx + (p[0] - old_cx) * sx,
                     new_cy + (p[1] - old_cy) * sy)
                    for p in old_p
                ]
            else:
                obj.points = [(ax, ay), (wx, wy)]

        elif st == "polygon":
            # Scale radius
            new_center_x = (wx + ax) / 2
            new_center_y = (wy + ay) / 2
            new_radius = math.hypot(wx - new_center_x, wy - new_center_y)
            obj.radius = max(5.0, new_radius)
            obj.points = [(new_center_x, new_center_y)]

        elif st == "ellipse":
            new_cx = (wx + ax) / 2
            new_cy = (wy + ay) / 2
            obj.rx = max(5.0, abs(wx - ax) / 2)
            obj.ry = max(5.0, abs(wy - ay) / 2)
            obj.points = [(new_cx, new_cy)]

        elif st == "freehand":
            # Scale all points relative to old center
            old_p = self._resize_old_points
            if len(old_p) < 2:
                return
            old_xs = [p[0] for p in old_p]
            old_ys = [p[1] for p in old_p]
            old_cx = sum(old_xs) / len(old_xs)
            old_cy = sum(old_ys) / len(old_ys)
            old_w = max(old_xs) - min(old_xs) or 1.0
            old_h = max(old_ys) - min(old_ys) or 1.0

            new_w = abs(wx - ax) or 1.0
            new_h = abs(wy - ay) or 1.0
            new_cx = (wx + ax) / 2
            new_cy = (wy + ay) / 2

            sx = new_w / old_w
            sy = new_h / old_h
            obj.points = [
                (new_cx + (p[0] - old_cx) * sx,
                 new_cy + (p[1] - old_cy) * sy)
                for p in old_p
            ]

    def mouse_release(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        if self.mode == "draw":
            if event.button() == Qt.MouseButton.LeftButton and self._is_drawing:
                self._is_drawing = False
                layer = self._get_active_layer()
                if layer is None:
                    return

                if self.shape_type == "freehand":
                    self._finish_freehand(layer)
                else:
                    self._finish_shape(layer)

        elif self.mode == "select":
            if event.button() != Qt.MouseButton.LeftButton or not self._interaction:
                return

            if not self._selected:
                self._interaction = None
                return

            layer = self._get_active_layer()
            obj = self._selected

            if self._interaction == "move":
                new_points = list(obj.points)
                obj.points = list(self._drag_obj_points)
                dx = new_points[0][0] - self._drag_obj_points[0][0] if new_points else 0
                dy = new_points[0][1] - self._drag_obj_points[0][1] if new_points else 0
                if (abs(dx) > 0.1 or abs(dy) > 0.1) and layer:
                    cmd = MoveSketchCommand(layer, obj, dx, dy)
                    self._command_stack.execute(cmd)

            elif self._interaction == "resize":
                new_points = list(obj.points)
                new_radius = obj.radius
                new_rx = obj.rx
                new_ry = obj.ry
                # Reset for undo
                obj.points = list(self._resize_old_points)
                obj.radius = self._resize_old_radius
                obj.rx = self._resize_old_rx
                obj.ry = self._resize_old_ry
                if layer:
                    cmd = ResizeSketchCommand(
                        layer, obj,
                        self._resize_old_points, new_points,
                        self._resize_old_radius, new_radius,
                        self._resize_old_rx, new_rx,
                        self._resize_old_ry, new_ry,
                    )
                    self._command_stack.execute(cmd)

            elif self._interaction == "rotate":
                new_rotation = obj.rotation
                obj.rotation = self._rotate_initial
                if new_rotation != self._rotate_initial and layer:
                    cmd = RotateSketchCommand(
                        layer, obj,
                        self._rotate_initial, new_rotation,
                    )
                    self._command_stack.execute(cmd)

            self._interaction = None

    def _finish_shape(self, layer: SketchLayer) -> None:
        """Create a shape object from draw start/current."""
        x1, y1 = self._draw_start
        x2, y2 = self._draw_current

        # Min size check
        if math.hypot(x2 - x1, y2 - y1) < _MIN_SHAPE_SIZE:
            return

        st = self.shape_type
        if st == "line":
            points = [(x1, y1), (x2, y2)]
            obj = self._make_object(points)
        elif st == "rect":
            points = [(x1, y1), (x2, y2)]
            obj = self._make_object(points)
        elif st == "polygon":
            cx, cy = x1, y1
            radius = math.hypot(x2 - x1, y2 - y1)
            obj = self._make_object([(cx, cy)])
            obj.radius = radius
        elif st == "ellipse":
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            obj = self._make_object([(cx, cy)])
            if self.perfect_circle:
                r = min(abs(x2 - x1), abs(y2 - y1)) / 2.0
                obj.rx = r
                obj.ry = r
            else:
                obj.rx = abs(x2 - x1) / 2.0
                obj.ry = abs(y2 - y1) / 2.0
        else:
            return

        cmd = PlaceSketchCommand(layer, obj)
        self._command_stack.execute(cmd)

    def _finish_freehand(self, layer: SketchLayer) -> None:
        """Create a freehand object from collected points."""
        if len(self._freehand_points) < 2:
            self._freehand_points.clear()
            return

        # Douglas-Peucker simplification
        epsilon = 0.5 * _MAX_DP_EPSILON
        simplified = _douglas_peucker(self._freehand_points, epsilon)
        if len(simplified) < 2:
            self._freehand_points.clear()
            return

        obj = self._make_object(simplified)
        obj.shape_type = "freehand"
        obj.closed = self.closed

        cmd = PlaceSketchCommand(layer, obj)
        self._command_stack.execute(cmd)
        self._freehand_points.clear()

    def _make_object(self, points: list[tuple[float, float]]) -> SketchObject:
        """Create a SketchObject with current tool settings."""
        return SketchObject(
            shape_type=self.shape_type,
            points=points,
            num_sides=self.num_sides,
            stroke_color=self.stroke_color,
            stroke_width=self.stroke_width,
            stroke_type=self.stroke_type,
            dash_length=self.dash_length,
            gap_length=self.gap_length,
            stroke_cap=self.stroke_cap,
            fill_enabled=self.fill_enabled,
            fill_color=self.fill_color,
            fill_opacity=self.fill_opacity,
            fill_type=self.fill_type,
            fill_texture_id=self.fill_texture_id,
            fill_texture_zoom=self.fill_texture_zoom,
            fill_texture_rotation=self.fill_texture_rotation,
            rotation=self.rotation,
            draw_over_grid=self.draw_over_grid,
        )

    def key_press(self, event: QKeyEvent) -> None:
        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier

        if ctrl and event.key() == Qt.Key.Key_C:
            if self.mode == "select" and self._selected:
                SketchTool._clipboard = self._copy_object(self._selected)
            return

        if ctrl and event.key() == Qt.Key.Key_V:
            if self.mode == "select" and SketchTool._clipboard is not None:
                layer = self._get_active_layer()
                if layer is not None:
                    pasted = self._copy_object(SketchTool._clipboard)
                    pasted.points = [(x + 10.0, y + 10.0) for x, y in pasted.points]
                    cmd = PlaceSketchCommand(layer, pasted)
                    self._command_stack.execute(cmd)
                    self._selected = pasted
                    self._notify_selection()
            return

        if event.key() == Qt.Key.Key_Delete and self._selected:
            layer = self._get_active_layer()
            if layer:
                cmd = RemoveSketchCommand(layer, self._selected)
                self._command_stack.execute(cmd)
                self._selected = None
                self._interaction = None
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
        transform = painter.worldTransform()
        zoom_scale = transform.m11() if transform.m11() > 0 else 1.0
        self._cached_inv_scale = 1.0 / zoom_scale

        # Draw mode: live preview
        if self.mode == "draw" and self._is_drawing:
            if self.shape_type == "freehand":
                self._paint_freehand_preview(painter)
            else:
                self._paint_shape_preview(painter)

        # Select mode: selection handles
        if self.mode == "select" and self._selected:
            self._paint_selection_handles(painter)

    def _paint_shape_preview(self, painter: QPainter) -> None:
        """Draw semi-transparent preview of the shape being created."""
        x1, y1 = self._draw_start
        x2, y2 = self._draw_current

        if math.hypot(x2 - x1, y2 - y1) < 1.0:
            return

        # Build preview object
        st = self.shape_type
        if st == "line":
            preview = SketchObject(shape_type="line", points=[(x1, y1), (x2, y2)])
        elif st == "rect":
            preview = SketchObject(shape_type="rect", points=[(x1, y1), (x2, y2)])
        elif st == "polygon":
            radius = math.hypot(x2 - x1, y2 - y1)
            preview = SketchObject(
                shape_type="polygon", points=[(x1, y1)],
                radius=radius, num_sides=self.num_sides,
            )
        elif st == "ellipse":
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if self.perfect_circle:
                r = min(abs(x2 - x1), abs(y2 - y1)) / 2
                preview = SketchObject(
                    shape_type="ellipse", points=[(cx, cy)],
                    rx=r, ry=r,
                )
            else:
                preview = SketchObject(
                    shape_type="ellipse", points=[(cx, cy)],
                    rx=abs(x2 - x1) / 2, ry=abs(y2 - y1) / 2,
                )
        else:
            return

        preview.rotation = self.rotation
        path = preview.build_path()
        if path.isEmpty():
            return

        cx, cy = preview.center()
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(preview.rotation)
        painter.translate(-cx, -cy)

        # Semi-transparent fill
        if self.fill_enabled and st != "line":
            fill_c = QColor(self.fill_color)
            fill_c.setAlpha(int(self.fill_opacity * 128))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fill_c))
            painter.drawPath(path)

        # Stroke
        stroke_c = QColor(self.stroke_color)
        stroke_c.setAlpha(128)
        pen = QPen(stroke_c, self.stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.restore()

    def _paint_freehand_preview(self, painter: QPainter) -> None:
        """Draw semi-transparent preview of freehand stroke."""
        if len(self._freehand_points) < 2:
            return

        color = QColor(self.stroke_color)
        color.setAlpha(128)
        pen = QPen(color, max(self.stroke_width, 2.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for i in range(len(self._freehand_points) - 1):
            x1, y1 = self._freehand_points[i]
            x2, y2 = self._freehand_points[i + 1]
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _paint_selection_handles(self, painter: QPainter) -> None:
        """Draw selection rectangle, corner handles, and rotation handle."""
        obj = self._selected
        if not obj:
            return

        inv_scale = self._cached_inv_scale
        corners = self._get_corners(obj)

        # Selection rectangle (dashed blue)
        pen = QPen(QColor(0, 120, 255), 2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(0, 0, 0, 0))
        poly = QPolygonF([QPointF(x, y) for x, y in corners])
        painter.drawPolygon(poly)

        # Corner resize handles (white squares)
        handle_size = _HANDLE_SCREEN_PX * inv_scale
        pen_solid = QPen(QColor(0, 120, 255), 1.5)
        pen_solid.setCosmetic(True)
        painter.setPen(pen_solid)
        painter.setBrush(QColor(255, 255, 255))

        for cx, cy in corners:
            painter.drawRect(QRectF(
                cx - handle_size, cy - handle_size,
                handle_size * 2, handle_size * 2,
            ))

        # Rotation handle (green circle)
        rot_pos = self._get_rotation_handle_pos(obj, inv_scale)
        rot_x, rot_y = rot_pos

        # Line from top center to rotation handle
        top_mid_x = (corners[0][0] + corners[1][0]) / 2
        top_mid_y = (corners[0][1] + corners[1][1]) / 2

        pen_line = QPen(QColor(0, 120, 255), 1)
        pen_line.setCosmetic(True)
        painter.setPen(pen_line)
        painter.drawLine(
            QPointF(top_mid_x, top_mid_y), QPointF(rot_x, rot_y),
        )

        painter.setPen(pen_solid)
        painter.setBrush(QColor(0, 200, 0))
        rot_radius = _HANDLE_SCREEN_PX * inv_scale
        painter.drawEllipse(QPointF(rot_x, rot_y), rot_radius, rot_radius)
