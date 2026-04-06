"""Path tool - place, select, and edit path objects between hex centers."""

from __future__ import annotations

import math
import random as _random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen

from app.commands.command import CompoundCommand
from app.commands.command_stack import CommandStack
from app.commands.path_commands import (
    EditPathCommand,
    MoveControlPointCommand,
    MoveEndpointCommand,
    MoveSyncedEndpointsCommand,
    PlacePathCommand,
    RemovePathCommand,
)
from app.hex.hex_math import (
    Hex,
    Layout,
    hex_edge_key,
    hex_neighbor,
    hex_to_pixel,
)
from app.layers.path_layer import PathLayer, hex_endpoint_offset
from app.models.path_object import PathObject
from app.models.project import Project
from app.tools.base_tool import Tool

# Handle size in screen pixels
_HANDLE_SCREEN_PX = 5.0
_HANDLE_HIT_RADIUS_PX = 10.0


def _nearest_center_link(
    layout: Layout, hex_coord: Hex, world_x: float, world_y: float,
) -> tuple[int, float]:
    """Find the nearest center-to-center link from the given hex.

    Tests all 6 neighbor directions and returns (direction, distance) where
    distance is the perpendicular distance from the mouse to the line segment
    connecting hex_coord's center to the neighbor's center.
    """
    cx, cy = hex_to_pixel(layout, hex_coord)
    best_dir = 0
    best_dist = float("inf")

    for direction in range(6):
        neighbor = hex_neighbor(hex_coord, direction)
        nx, ny = hex_to_pixel(layout, neighbor)
        dist = _point_to_segment_dist(world_x, world_y, cx, cy, nx, ny)
        if dist < best_dist:
            best_dist = dist
            best_dir = direction

    return best_dir, best_dist


def _point_to_segment_dist(
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


class PathTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack
        self.mode: str = "place"  # "place" or "select"

        # Placement settings
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
        self.random: bool = False
        self.random_amplitude: float = 2.0
        self.random_distance: float = 0.0
        self.random_endpoint: float = 0.0
        self.random_jitter: float = 0.0
        self.random_offset: float = 0.0
        self.opacity: float = 1.0
        self.bg_opacity: float = 1.0

        # Hover state
        self._hover_link: tuple[Hex, int] | None = None  # (hex, direction)
        self._last_world_pos: QPointF = QPointF(0, 0)

        # Drag state (place mode)
        self._is_dragging: bool = False
        self._drag_command: CompoundCommand | None = None
        self._placed_links_in_drag: set = set()

        # Select mode state
        self._selected: PathObject | None = None
        self._interaction: str | None = None  # "control_point"
        self._cp_index: int = -1
        self._cp_initial_ep: list[float] = [0.0, 0.0]  # for endpoint undo
        self._cp_initial_ip: list[float] = [0.0, 0.0]  # for inner point undo
        # Synced endpoints: other paths sharing the same hex center as the dragged endpoint
        self._cp_synced_objs: list[tuple[PathObject, str, list[float]]] = []
        # (obj, "a"|"b", initial_ep)
        self._cp_dragging: bool = False
        self._cached_inv_scale: float = 1.0

        # Selection change callback
        self.on_selection_changed = None

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.mode = "place"
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
        self.random = False
        self.random_amplitude = 2.0
        self.random_distance = 0.0
        self.random_endpoint = 0.0
        self.random_jitter = 0.0
        self.random_offset = 0.0
        self.opacity = 1.0
        self.bg_opacity = 1.0
        self._hover_link = None
        self._selected = None
        self._interaction = None
        self._cp_dragging = False
        self._is_dragging = False
        self._drag_command = None
        self._placed_links_in_drag = set()

    @property
    def name(self) -> str:
        return "Path (Center)"

    @property
    def cursor(self) -> Qt.CursorShape:
        if self.mode == "place":
            return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.ArrowCursor

    def _notify_selection(self) -> None:
        """Notify listener that the selected object changed."""
        if self.on_selection_changed:
            self.on_selection_changed(self._selected)

    def _get_active_path_layer(self) -> PathLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, PathLayer):
            return layer
        return None

    def _get_layout(self) -> Layout:
        return self._project.grid_config.create_layout()

    # --- Place mode helpers ---

    def _place_at_hover(self, layer: PathLayer, layout: Layout) -> None:
        """Place a path at the current hover link."""
        if self._hover_link is None:
            return

        hex_c, direction = self._hover_link
        neighbor = hex_neighbor(hex_c, direction)
        key = hex_edge_key(hex_c, neighbor)

        if key in self._placed_links_in_drag:
            return
        if layer.get_path_at_edge(hex_c, neighbor) is not None:
            return  # Link already occupied

        self._placed_links_in_drag.add(key)

        # Build canonical key
        a = (hex_c.q, hex_c.r)
        b = (neighbor.q, neighbor.r)
        if a > b:
            a, b = b, a

        obj = PathObject(
            hex_a_q=a[0],
            hex_a_r=a[1],
            hex_b_q=b[0],
            hex_b_r=b[1],
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
            random=self.random,
            random_seed=_random.randint(0, 999999),
            random_amplitude=self.random_amplitude,
            random_distance=self.random_distance,
            random_endpoint=self.random_endpoint,
            random_jitter=self.random_jitter,
            random_offset=self.random_offset,
            opacity=self.opacity,
            bg_opacity=self.bg_opacity,
        )

        # Snap ep_a to existing paths sharing hex_a endpoint
        for existing in layer.paths.values():
            if (existing.hex_a_q, existing.hex_a_r) == (obj.hex_a_q, obj.hex_a_r):
                obj.ep_a = list(existing.ep_a)
                break
            if (existing.hex_b_q, existing.hex_b_r) == (obj.hex_a_q, obj.hex_a_r):
                obj.ep_a = list(existing.ep_b)
                break

        # Snap ep_b to existing paths sharing hex_b endpoint
        for existing in layer.paths.values():
            if (existing.hex_a_q, existing.hex_a_r) == (obj.hex_b_q, obj.hex_b_r):
                obj.ep_b = list(existing.ep_a)
                break
            if (existing.hex_b_q, existing.hex_b_r) == (obj.hex_b_q, obj.hex_b_r):
                obj.ep_b = list(existing.ep_b)
                break

        cmd = PlacePathCommand(layer, obj)
        cmd.execute()
        if self._drag_command:
            self._drag_command._commands.append(cmd)

    # --- Select mode helpers ---

    def _get_control_point_positions(
        self, layout: Layout, obj: PathObject,
    ) -> list[tuple[float, float]]:
        """Get world-space positions of the 4 control points."""
        layer = self._get_active_path_layer()
        if layer is None:
            return []

        direction = layer._find_direction(obj)
        if direction is None:
            return []

        c1x, c1y = hex_to_pixel(layout, obj.hex_a())
        c2x, c2y = hex_to_pixel(layout, obj.hex_b())

        dx = c2x - c1x
        dy = c2y - c1y
        seg_len = math.hypot(dx, dy)
        if seg_len == 0:
            return []

        # Perpendicular direction
        tx, ty = dx / seg_len, dy / seg_len
        perp_x, perp_y = -ty, tx

        # Reconstruct endpoint displacement (hex-coordinate-based for connectivity)
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

        ex = end_x - start_x
        ey = end_y - start_y

        t_positions = obj.cp_t_positions()
        positions = []
        num_cp = len(obj.control_points)
        for i in range(num_cp):
            if i == 0:
                positions.append((start_x + obj.ep_a[0], start_y + obj.ep_a[1]))
            elif i == num_cp - 1:
                positions.append((end_x + obj.ep_b[0], end_y + obj.ep_b[1]))
            else:
                t = t_positions[i]
                base_x = start_x + ex * t
                base_y = start_y + ey * t
                # Apply random_offset same as _compute_path() so handles match rendered path
                if obj.random_offset != 0.0:
                    rng = _random.Random(obj.random_seed + 11111 * i)
                    off = rng.uniform(-obj.random_offset, obj.random_offset)
                    base_x += perp_x * off
                    base_y += perp_y * off
                ip = obj.ip_a if i == 1 else obj.ip_b
                positions.append((base_x + ip[0], base_y + ip[1]))
        return positions

    def _get_perp_direction(
        self, layout: Layout, obj: PathObject,
    ) -> tuple[float, float]:
        """Get the perpendicular direction for control point dragging."""
        c1x, c1y = hex_to_pixel(layout, obj.hex_a())
        c2x, c2y = hex_to_pixel(layout, obj.hex_b())

        dx = c2x - c1x
        dy = c2y - c1y
        seg_len = math.hypot(dx, dy)
        if seg_len == 0:
            return (0.0, 1.0)

        tx, ty = dx / seg_len, dy / seg_len
        return (-ty, tx)

    def _hit_handle(
        self, wx: float, wy: float, hx: float, hy: float,
    ) -> bool:
        hit_r = _HANDLE_HIT_RADIUS_PX * self._cached_inv_scale
        return (wx - hx) ** 2 + (wy - hy) ** 2 <= hit_r ** 2

    def _find_shared_path_endpoints(
        self, layer: PathLayer, selected: PathObject, which: str,
    ) -> list[tuple[PathObject, str]]:
        """Find other paths in the layer sharing the same hex center endpoint.

        Returns list of (obj, "a"|"b") for all paths (excluding selected) that
        have the same hex coordinate at the given endpoint side.
        """
        if which == "a":
            shared_q, shared_r = selected.hex_a_q, selected.hex_a_r
        else:
            shared_q, shared_r = selected.hex_b_q, selected.hex_b_r

        result = []
        for obj in layer.paths.values():
            if obj is selected:
                continue
            if (obj.hex_a_q, obj.hex_a_r) == (shared_q, shared_r):
                result.append((obj, "a"))
            elif (obj.hex_b_q, obj.hex_b_r) == (shared_q, shared_r):
                result.append((obj, "b"))
        return result

    def _get_path_endpoint_base(
        self, layout: Layout, obj: PathObject, which: str,
    ) -> tuple[float, float]:
        """Get the base world position for a path endpoint (hex center ± random displacement)."""
        if which == "a":
            cx, cy = hex_to_pixel(layout, obj.hex_a())
            if obj.random and obj.random_endpoint > 0:
                dx, dy = hex_endpoint_offset(obj.hex_a_q, obj.hex_a_r, obj.random_endpoint)
                return (cx + dx, cy + dy)
            return (cx, cy)
        else:
            cx, cy = hex_to_pixel(layout, obj.hex_b())
            if obj.random and obj.random_endpoint > 0:
                dx, dy = hex_endpoint_offset(obj.hex_b_q, obj.hex_b_r, obj.random_endpoint)
                return (cx + dx, cy + dy)
            return (cx, cy)

    def _clamp_to_2hex(self, dx: float, dy: float) -> tuple[float, float]:
        """Clamp a 2D offset to at most 2 hex-sizes in distance."""
        max_dist = 2.0 * self._project.grid_config.hex_size
        dist = math.hypot(dx, dy)
        if dist > max_dist:
            scale = max_dist / dist
            return (dx * scale, dy * scale)
        return (dx, dy)

    # --- Mouse events ---

    def mouse_press(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        layer = self._get_active_path_layer()
        if layer is None:
            return

        wx, wy = world_pos.x(), world_pos.y()
        layout = self._get_layout()

        if self.mode == "place":
            if event.button() == Qt.MouseButton.LeftButton:
                self._is_dragging = True
                self._drag_command = CompoundCommand("Place paths")
                self._placed_links_in_drag = set()
                self._place_at_hover(layer, layout)

            elif event.button() == Qt.MouseButton.RightButton:
                if self._hover_link:
                    hex_c, direction = self._hover_link
                    neighbor = hex_neighbor(hex_c, direction)
                    existing = layer.get_path_at_edge(hex_c, neighbor)
                    if existing:
                        cmd = RemovePathCommand(layer, existing)
                        self._command_stack.execute(cmd)

        else:  # select mode
            if event.button() != Qt.MouseButton.LeftButton:
                return

            # Check if clicking on a control point of the selected path
            if self._selected:
                cp_pos = self._get_control_point_positions(layout, self._selected)
                num_cp = len(self._selected.control_points)
                for i, (cpx, cpy) in enumerate(cp_pos):
                    if self._hit_handle(wx, wy, cpx, cpy):
                        self._interaction = "control_point"
                        self._cp_index = i
                        if i == 0:
                            self._cp_initial_ep = list(self._selected.ep_a)
                            shared = self._find_shared_path_endpoints(layer, self._selected, "a")
                            self._cp_synced_objs = [
                                (obj, w, list(getattr(obj, f"ep_{w}")))
                                for obj, w in shared
                            ]
                        elif i == num_cp - 1:
                            self._cp_initial_ep = list(self._selected.ep_b)
                            shared = self._find_shared_path_endpoints(layer, self._selected, "b")
                            self._cp_synced_objs = [
                                (obj, w, list(getattr(obj, f"ep_{w}")))
                                for obj, w in shared
                            ]
                        elif i == 1:
                            self._cp_initial_ip = list(self._selected.ip_a)
                            self._cp_synced_objs = []
                        elif i == 2:
                            self._cp_initial_ip = list(self._selected.ip_b)
                            self._cp_synced_objs = []
                        else:
                            self._cp_synced_objs = []
                        # Hide dragged objects from layer cache and rebuild once
                        self._cp_dragging = True
                        hidden = {self._selected.edge_key()}
                        for obj_s, _, _ in self._cp_synced_objs:
                            hidden.add(obj_s.edge_key())
                        layer._drag_hidden_keys = hidden
                        layer.mark_dirty()
                        return

            # Try selecting a path
            hit = layer.hit_test(wx, wy, layout)
            if hit:
                self._selected = hit
            else:
                self._selected = None
            self._interaction = None
            self._notify_selection()

    def mouse_move(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        self._last_world_pos = world_pos
        wx, wy = world_pos.x(), world_pos.y()

        layer = self._get_active_path_layer()
        if layer is None:
            self._hover_link = None
            return

        layout = self._get_layout()

        if self.mode == "place":
            # Update hover link — only within valid hexes
            if not self._project.grid_config.is_valid_hex(hex_coord):
                self._hover_link = None
            else:
                direction, dist = _nearest_center_link(layout, hex_coord, wx, wy)
                if dist < self._project.grid_config.hex_size * 0.8:
                    self._hover_link = (hex_coord, direction)
                else:
                    self._hover_link = None

            # Handle drag placement
            if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
                self._place_at_hover(layer, layout)

        elif self.mode == "select":
            if self._interaction == "control_point" and self._selected:
                c1x, c1y = hex_to_pixel(layout, self._selected.hex_a())
                c2x, c2y = hex_to_pixel(layout, self._selected.hex_b())

                # Perpendicular direction from original hex center positions
                # (same reference as _compute_path and _get_control_point_positions)
                dx_hex = c2x - c1x
                dy_hex = c2y - c1y
                seg_len_hex = math.hypot(dx_hex, dy_hex)
                if seg_len_hex > 0:
                    perp_x = -dy_hex / seg_len_hex
                    perp_y = dx_hex / seg_len_hex
                else:
                    perp_x, perp_y = 0.0, 1.0

                # Reconstruct base endpoint positions (hex-coordinate-based displacement)
                start_x, start_y = c1x, c1y
                end_x, end_y = c2x, c2y
                if self._selected.random and self._selected.random_endpoint > 0:
                    s_dx, s_dy = hex_endpoint_offset(
                        self._selected.hex_a_q, self._selected.hex_a_r,
                        self._selected.random_endpoint,
                    )
                    e_dx, e_dy = hex_endpoint_offset(
                        self._selected.hex_b_q, self._selected.hex_b_r,
                        self._selected.random_endpoint,
                    )
                    start_x += s_dx
                    start_y += s_dy
                    end_x += e_dx
                    end_y += e_dy

                num_cp = len(self._selected.control_points)
                if self._cp_index == 0:
                    # Endpoint A: free 2D movement, clamped to 2 hexes (move all sharing hex_a)
                    ep_dx, ep_dy = self._clamp_to_2hex(wx - start_x, wy - start_y)
                    self._selected.ep_a = [ep_dx, ep_dy]
                    for obj, which, _initial in self._cp_synced_objs:
                        bx, by = self._get_path_endpoint_base(layout, obj, which)
                        sx, sy = self._clamp_to_2hex(wx - bx, wy - by)
                        setattr(obj, f"ep_{which}", [sx, sy])
                elif self._cp_index == num_cp - 1:
                    # Endpoint B: free 2D movement, clamped to 2 hexes (move all sharing hex_b)
                    ep_dx, ep_dy = self._clamp_to_2hex(wx - end_x, wy - end_y)
                    self._selected.ep_b = [ep_dx, ep_dy]
                    for obj, which, _initial in self._cp_synced_objs:
                        bx, by = self._get_path_endpoint_base(layout, obj, which)
                        sx, sy = self._clamp_to_2hex(wx - bx, wy - by)
                        setattr(obj, f"ep_{which}", [sx, sy])
                elif self._cp_index in (1, 2):
                    # Inner control points: free 2D movement, clamped to 2 hexes
                    t = self._selected.cp_t_positions()[self._cp_index]
                    base_x = start_x + (end_x - start_x) * t
                    base_y = start_y + (end_y - start_y) * t
                    # Apply random_offset to base (matches _compute_path and _get_control_point_positions)
                    if self._selected.random_offset != 0.0:
                        rng = _random.Random(self._selected.random_seed + 11111 * self._cp_index)
                        off = rng.uniform(-self._selected.random_offset, self._selected.random_offset)
                        base_x += perp_x * off
                        base_y += perp_y * off
                    ip_dx, ip_dy = self._clamp_to_2hex(wx - base_x, wy - base_y)
                    if self._cp_index == 1:
                        self._selected.ip_a = [ip_dx, ip_dy]
                    else:
                        self._selected.ip_b = [ip_dx, ip_dy]

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
                self._placed_links_in_drag.clear()

        elif self.mode == "select":
            if event.button() == Qt.MouseButton.LeftButton and self._interaction == "control_point":
                self._cp_dragging = False
                if self._selected:
                    layer = self._get_active_path_layer()
                    # Clear drag preview state before command (which calls mark_dirty)
                    if layer:
                        layer._drag_hidden_keys = set()
                    num_cp = len(self._selected.control_points)
                    if self._cp_index == 0:
                        new_ep_primary = list(self._selected.ep_a)
                        synced_new = [list(getattr(o, f"ep_{w}")) for o, w, _ in self._cp_synced_objs]
                        # Revert all for command pattern
                        self._selected.ep_a = list(self._cp_initial_ep)
                        for (o, w, init), _ in zip(self._cp_synced_objs, synced_new):
                            setattr(o, f"ep_{w}", list(init))
                        if layer:
                            all_moves = [(self._selected, "a", self._cp_initial_ep, new_ep_primary)]
                            for (o, w, init), new in zip(self._cp_synced_objs, synced_new):
                                all_moves.append((o, w, init, new))
                            if any(n != old for _, _, old, n in all_moves):
                                cmd = MoveSyncedEndpointsCommand(layer, all_moves)
                                self._command_stack.execute(cmd)
                            else:
                                layer.mark_dirty()  # Rebuild cache with all objects visible
                    elif self._cp_index == num_cp - 1:
                        new_ep_primary = list(self._selected.ep_b)
                        synced_new = [list(getattr(o, f"ep_{w}")) for o, w, _ in self._cp_synced_objs]
                        # Revert all for command pattern
                        self._selected.ep_b = list(self._cp_initial_ep)
                        for (o, w, init), _ in zip(self._cp_synced_objs, synced_new):
                            setattr(o, f"ep_{w}", list(init))
                        if layer:
                            all_moves = [(self._selected, "b", self._cp_initial_ep, new_ep_primary)]
                            for (o, w, init), new in zip(self._cp_synced_objs, synced_new):
                                all_moves.append((o, w, init, new))
                            if any(n != old for _, _, old, n in all_moves):
                                cmd = MoveSyncedEndpointsCommand(layer, all_moves)
                                self._command_stack.execute(cmd)
                            else:
                                layer.mark_dirty()  # Rebuild cache with all objects visible
                    elif self._cp_index == 1:
                        new_ip = list(self._selected.ip_a)
                        self._selected.ip_a = list(self._cp_initial_ip)
                        if new_ip != self._cp_initial_ip and layer:
                            cmd = EditPathCommand(layer, self._selected, ip_a=new_ip)
                            self._command_stack.execute(cmd)
                        elif layer:
                            layer.mark_dirty()  # Rebuild cache with all objects visible
                    elif self._cp_index == 2:
                        new_ip = list(self._selected.ip_b)
                        self._selected.ip_b = list(self._cp_initial_ip)
                        if new_ip != self._cp_initial_ip and layer:
                            cmd = EditPathCommand(layer, self._selected, ip_b=new_ip)
                            self._command_stack.execute(cmd)
                        elif layer:
                            layer.mark_dirty()  # Rebuild cache with all objects visible
                self._interaction = None
                self._cp_synced_objs = []

    def key_press(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete and self._selected:
            layer = self._get_active_path_layer()
            if layer:
                cmd = RemovePathCommand(layer, self._selected)
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
        # Cache inverse scale
        transform = painter.worldTransform()
        zoom_scale = transform.m11() if transform.m11() > 0 else 1.0
        self._cached_inv_scale = 1.0 / zoom_scale

        # Place mode: highlight hover link with accurate line style preview
        if self.mode == "place" and self._hover_link:
            hex_c, direction = self._hover_link
            neighbor = hex_neighbor(hex_c, direction)
            c1x, c1y = hex_to_pixel(layout, hex_c)
            c2x, c2y = hex_to_pixel(layout, neighbor)

            preview_path = QPainterPath()
            preview_path.moveTo(QPointF(c1x, c1y))
            preview_path.lineTo(QPointF(c2x, c2y))

            painter.save()
            painter.setOpacity(0.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            if self.bg_enabled:
                bg_pen = PathLayer._make_pen(
                    self.bg_color, self.bg_width, self.bg_line_type,
                    self.bg_dash_length, self.bg_gap_length,
                    self.bg_texture_id, self.bg_texture_zoom, self.bg_texture_rotation,
                    self.bg_dash_cap,
                )
                painter.setPen(bg_pen)
                painter.drawPath(preview_path)

            fg_pen = PathLayer._make_pen(
                self.color, self.width, self.line_type,
                self.dash_length, self.gap_length,
                self.texture_id, self.texture_zoom, self.texture_rotation,
                self.dash_cap,
            )
            painter.setPen(fg_pen)
            painter.drawPath(preview_path)

            painter.restore()

        # Select mode: draw selection + control point handles
        if self.mode == "select" and self._selected:
            obj = self._selected
            inv_scale = self._cached_inv_scale

            # During CP drag: render dragged objects as overlay preview
            # (layer cache has them hidden via _drag_hidden_keys)
            if self._cp_dragging:
                layer = self._get_active_path_layer()
                if layer:
                    preview_objs = [obj]
                    for synced_obj, _, _ in self._cp_synced_objs:
                        preview_objs.append(synced_obj)
                    for pobj in preview_objs:
                        path = layer._get_cached_path(layout, pobj)
                        if path.isEmpty():
                            continue
                        # Background pass
                        if pobj.bg_enabled:
                            painter.save()
                            if pobj.bg_opacity < 1.0:
                                painter.setOpacity(pobj.bg_opacity)
                            bg_pen = PathLayer._make_pen(
                                pobj.bg_color, pobj.bg_width, pobj.bg_line_type,
                                pobj.bg_dash_length, pobj.bg_gap_length,
                                pobj.bg_texture_id, pobj.bg_texture_zoom,
                                pobj.bg_texture_rotation, pobj.bg_dash_cap,
                            )
                            painter.setPen(bg_pen)
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawPath(path)
                            painter.restore()
                        # Foreground pass
                        painter.save()
                        if pobj.opacity < 1.0:
                            painter.setOpacity(pobj.opacity)
                        fg_pen = PathLayer._make_pen(
                            pobj.color, pobj.width, pobj.line_type,
                            pobj.dash_length, pobj.gap_length,
                            pobj.texture_id, pobj.texture_zoom,
                            pobj.texture_rotation, pobj.dash_cap,
                        )
                        painter.setPen(fg_pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawPath(path)
                        painter.restore()

            # Draw control point handles
            cp_positions = self._get_control_point_positions(layout, obj)
            handle_radius = _HANDLE_SCREEN_PX * inv_scale

            painter.setPen(QPen(QColor(180, 0, 0), 1.5 * inv_scale))
            painter.setBrush(QColor(255, 60, 60))

            for cpx, cpy in cp_positions:
                painter.drawEllipse(
                    QPointF(cpx, cpy), handle_radius, handle_radius,
                )
