"""Hexside tool - place, select, and edit hexside objects along hex edges."""

from __future__ import annotations

import math
import random as _random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen

from app.commands.command import CompoundCommand
from app.commands.command_stack import CommandStack
from app.commands.hexside_commands import (
    EditHexsideCommand,
    MoveControlPointCommand,
    MoveEndpointCommand,
    MoveSyncedEndpointsCommand,
    PlaceHexsideCommand,
    RemoveHexsideCommand,
    SyncRandomEndpointCommand,
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
from app.layers.hexside_layer import HexsideLayer, hex_vertex_endpoint_offset
from app.models.hexside_object import HexsideObject
from app.models.project import Project
from app.tools.base_tool import Tool

# Handle size in screen pixels
_HANDLE_SCREEN_PX = 5.0
_HANDLE_HIT_RADIUS_PX = 10.0


class HexsideTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack
        self.mode: str = "place"  # "place", "falloff", "teeth", or "select"

        # Placement settings
        self.paint_mode: str = "color"  # "color" or "texture"
        self.color: str = "#000000"
        self.width: float = 3.0
        self.outline: bool = False
        self.outline_color: str = "#000000"
        self.outline_width: float = 1.0
        self.outline_texture_id: str = ""
        self.outline_texture_zoom: float = 1.0
        self.outline_texture_rotation: float = 0.0
        self.shift: float = 0.0
        self.random: bool = False
        self.random_amplitude: float = 3.0
        self.random_distance: float = 0.0
        self.random_jitter: float = 0.0
        self.random_endpoint: float = 0.0
        self.random_offset: float = 0.0
        self.taper: bool = False
        self.taper_length: float = 0.5
        self.current_texture_id: str | None = None
        self.texture_zoom: float = 1.0
        self.texture_rotation: float = 0.0
        self.opacity: float = 1.0
        self.outline_opacity: float = 1.0

        # Falloff mode settings
        self.falloff_width: float = 20.0
        self.falloff_amount: float = 1.0
        self.falloff_random: float = 0.0

        # Teeth mode settings
        self.teeth_count: int = 4
        self.teeth_size: float = 8.0
        self.teeth_color: str = "#000000"
        self.teeth_opacity: float = 1.0
        self._teeth_edges_in_drag: set = set()

        # Hover state
        self._hover_edge: tuple[Hex, int] | None = None  # (hex, direction)
        self._last_world_pos: QPointF = QPointF(0, 0)

        # Drag state (place and falloff modes)
        self._is_dragging: bool = False
        self._drag_command: CompoundCommand | None = None
        self._placed_edges_in_drag: set = set()
        self._falloff_edges_in_drag: set = set()

        # Select mode state
        self._selected: HexsideObject | None = None
        self._interaction: str | None = None  # "control_point"
        self._cp_index: int = -1
        self._cp_initial_ep: list[float] = [0.0, 0.0]  # for endpoint undo
        self._cp_initial_ip: list[float] = [0.0, 0.0]  # for inner point undo
        # Synced endpoints: other hexsides sharing the same hex vertex as the dragged endpoint
        self._cp_synced_objs: list[tuple[HexsideObject, str, list[float]]] = []
        # (obj, "a"|"b", initial_ep)
        self._cp_dragging: bool = False
        self._cached_inv_scale: float = 1.0

        # Selection change callback
        self.on_selection_changed = None

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.mode = "place"
        self.paint_mode = "color"
        self.color = "#000000"
        self.width = 3.0
        self.outline = False
        self.outline_color = "#000000"
        self.outline_width = 1.0
        self.outline_texture_id = ""
        self.outline_texture_zoom = 1.0
        self.outline_texture_rotation = 0.0
        self.shift = 0.0
        self.random = False
        self.random_amplitude = 3.0
        self.random_distance = 0.0
        self.random_jitter = 0.0
        self.random_endpoint = 0.0
        self.random_offset = 0.0
        self.taper = False
        self.taper_length = 0.5
        self.current_texture_id = None
        self.texture_zoom = 1.0
        self.texture_rotation = 0.0
        self.opacity = 1.0
        self.outline_opacity = 1.0
        self.falloff_width = 20.0
        self.falloff_amount = 1.0
        self.falloff_random = 0.0
        self.teeth_count = 4
        self.teeth_size = 8.0
        self.teeth_color = "#000000"
        self.teeth_opacity = 1.0
        self._teeth_edges_in_drag = set()
        self._hover_edge = None
        self._selected = None
        self._interaction = None
        self._cp_dragging = False
        self._is_dragging = False
        self._drag_command = None
        self._placed_edges_in_drag = set()

    @property
    def name(self) -> str:
        return "Hexside"

    @property
    def cursor(self) -> Qt.CursorShape:
        if self.mode == "place":
            return Qt.CursorShape.CrossCursor
        if self.mode in ("falloff", "teeth"):
            return Qt.CursorShape.PointingHandCursor
        return Qt.CursorShape.ArrowCursor

    def _notify_selection(self) -> None:
        """Notify listener that the selected object changed."""
        if self.on_selection_changed:
            self.on_selection_changed(self._selected)

    def _get_active_hexside_layer(self) -> HexsideLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, HexsideLayer):
            return layer
        return None

    def _get_layout(self) -> Layout:
        return self._project.grid_config.create_layout()

    # --- Place mode helpers ---

    def _place_at_hover(self, layer: HexsideLayer, layout: Layout) -> None:
        """Place a hexside at the current hover edge."""
        if self._hover_edge is None:
            return

        hex_c, direction = self._hover_edge
        neighbor = hex_neighbor(hex_c, direction)
        key = hex_edge_key(hex_c, neighbor)

        if key in self._placed_edges_in_drag:
            return

        existing = layer.get_hexside_at_edge(hex_c, neighbor)
        # Skip if a real (visible) hexside already exists
        if existing is not None and (existing.width > 0 or existing.opacity > 0):
            return

        self._placed_edges_in_drag.add(key)

        # Build canonical key
        a = (hex_c.q, hex_c.r)
        b = (neighbor.q, neighbor.r)
        if a > b:
            a, b = b, a

        # Preserve falloff from existing invisible carrier
        fo_side = existing.falloff_side if existing else ""
        fo_width = existing.falloff_width if existing else 20.0
        fo_amount = existing.falloff_amount if existing else 1.0
        fo_random = existing.falloff_random if existing else 0.0
        fo_rseed = existing.falloff_random_seed if existing else _random.randint(0, 999999)
        # Preserve teeth from existing invisible carrier
        te_side = existing.teeth_side if existing else ""
        te_count = existing.teeth_count if existing else 4
        te_size = existing.teeth_size if existing else 8.0
        te_color = existing.teeth_color if existing else "#000000"
        te_opacity = existing.teeth_opacity if existing else 1.0
        obj = HexsideObject(
            hex_a_q=a[0],
            hex_a_r=a[1],
            hex_b_q=b[0],
            hex_b_r=b[1],
            color=self.color,
            width=self.width,
            outline=self.outline,
            outline_color=self.outline_color,
            outline_width=self.outline_width,
            outline_texture_id=self.outline_texture_id,
            outline_texture_zoom=self.outline_texture_zoom,
            outline_texture_rotation=self.outline_texture_rotation,
            shift=self.shift,
            random=self.random,
            random_seed=_random.randint(0, 999999),
            random_amplitude=self.random_amplitude,
            random_distance=self.random_distance,
            random_jitter=self.random_jitter,
            random_endpoint=self.random_endpoint,
            random_offset=self.random_offset,
            taper=self.taper,
            taper_length=self.taper_length,
            texture_id=self.current_texture_id if self.paint_mode == "texture" else None,
            texture_zoom=self.texture_zoom,
            texture_rotation=self.texture_rotation,
            opacity=self.opacity,
            outline_opacity=self.outline_opacity,
            falloff_side=fo_side,
            falloff_width=fo_width,
            falloff_amount=fo_amount,
            falloff_random=fo_random,
            falloff_random_seed=fo_rseed,
            teeth_side=te_side,
            teeth_count=te_count,
            teeth_size=te_size,
            teeth_color=te_color,
            teeth_opacity=te_opacity,
        )

        # Snap ep_a/ep_b and random_endpoint to existing hexsides sharing a vertex.
        # Use the hover edge geometry to get the raw corner positions of the new hexside.
        new_v1, new_v2 = hex_edge_vertices(layout, hex_c, direction)
        _random_endpoint_adopted = False

        for existing in layer.hexsides.values():
            existing_dir = layer._find_direction(existing)
            if existing_dir is None:
                continue
            ev1, ev2 = hex_edge_vertices(layout, existing.hex_a(), existing_dir)
            if math.hypot(new_v1[0] - ev1[0], new_v1[1] - ev1[1]) < 0.5:
                obj.ep_a = list(existing.ep_a)
                if not _random_endpoint_adopted:
                    obj.random_endpoint = existing.random_endpoint
                    _random_endpoint_adopted = True
                break
            if math.hypot(new_v1[0] - ev2[0], new_v1[1] - ev2[1]) < 0.5:
                obj.ep_a = list(existing.ep_b)
                if not _random_endpoint_adopted:
                    obj.random_endpoint = existing.random_endpoint
                    _random_endpoint_adopted = True
                break

        for existing in layer.hexsides.values():
            existing_dir = layer._find_direction(existing)
            if existing_dir is None:
                continue
            ev1, ev2 = hex_edge_vertices(layout, existing.hex_a(), existing_dir)
            if math.hypot(new_v2[0] - ev1[0], new_v2[1] - ev1[1]) < 0.5:
                obj.ep_b = list(existing.ep_a)
                if not _random_endpoint_adopted:
                    obj.random_endpoint = existing.random_endpoint
                    _random_endpoint_adopted = True
                break
            if math.hypot(new_v2[0] - ev2[0], new_v2[1] - ev2[1]) < 0.5:
                obj.ep_b = list(existing.ep_b)
                if not _random_endpoint_adopted:
                    obj.random_endpoint = existing.random_endpoint
                    _random_endpoint_adopted = True
                break

        cmd = PlaceHexsideCommand(layer, obj)
        cmd.execute()
        if self._drag_command:
            self._drag_command._commands.append(cmd)

    # --- Select mode helpers ---

    def _get_control_point_positions(
        self, layout: Layout, obj: HexsideObject,
    ) -> list[tuple[float, float]]:
        """Get world-space positions of the 4 control points.

        Mirrors _compute_hexside_path() logic so handle positions match rendered path.
        """
        layer = self._get_active_hexside_layer()
        if layer is None:
            return []

        direction = layer._find_direction(obj)
        if direction is None:
            return []

        v1, v2 = hex_edge_vertices(layout, obj.hex_a(), direction)
        nx, ny = layer._get_edge_normal(layout, obj.hex_a(), obj.hex_b())
        effective_shift = layer._compute_effective_shift(obj)
        sx, sy = effective_shift * nx, effective_shift * ny

        # Compute base vertices (same as _compute_hexside_path)
        base_v1 = (v1[0] + sx, v1[1] + sy)
        base_v2 = (v2[0] + sx, v2[1] + sy)

        if obj.random and obj.random_endpoint > 0:
            dv1 = hex_vertex_endpoint_offset(v1[0], v1[1], obj.random_endpoint)
            dv2 = hex_vertex_endpoint_offset(v2[0], v2[1], obj.random_endpoint)
            base_v1 = (base_v1[0] + dv1[0], base_v1[1] + dv1[1])
            base_v2 = (base_v2[0] + dv2[0], base_v2[1] + dv2[1])

        ex = base_v2[0] - base_v1[0]
        ey = base_v2[1] - base_v1[1]
        edge_len = math.hypot(ex, ey)
        if edge_len == 0:
            return []
        tx, ty = ex / edge_len, ey / edge_len
        perp_x, perp_y = -ty, tx
        dot = perp_x * nx + perp_y * ny
        if dot < 0:
            perp_x, perp_y = -perp_x, -perp_y

        t_positions = obj.cp_t_positions()
        positions = []
        num_cp = len(obj.control_points)
        for i in range(num_cp):
            if i == 0:
                positions.append((base_v1[0] + obj.ep_a[0], base_v1[1] + obj.ep_a[1]))
            elif i == num_cp - 1:
                positions.append((base_v2[0] + obj.ep_b[0], base_v2[1] + obj.ep_b[1]))
            else:
                t = t_positions[i]
                base_x = base_v1[0] + ex * t
                base_y = base_v1[1] + ey * t
                # Apply random_offset same as _compute_hexside_path() so handles match rendered path
                if obj.random_offset != 0.0:
                    rng = _random.Random(obj.random_seed + 11111 * i)
                    off = rng.uniform(-obj.random_offset, obj.random_offset)
                    base_x += perp_x * off
                    base_y += perp_y * off
                ip = obj.ip_a if i == 1 else obj.ip_b
                positions.append((base_x + ip[0], base_y + ip[1]))
        return positions

    def _get_perp_direction(
        self, layout: Layout, obj: HexsideObject,
    ) -> tuple[float, float]:
        """Get the perpendicular direction for control point dragging."""
        layer = self._get_active_hexside_layer()
        if layer is None:
            return (0.0, 1.0)

        direction = layer._find_direction(obj)
        if direction is None:
            return (0.0, 1.0)

        v1, v2 = hex_edge_vertices(layout, obj.hex_a(), direction)
        nx, ny = layer._get_edge_normal(layout, obj.hex_a(), obj.hex_b())

        ex = v2[0] - v1[0]
        ey = v2[1] - v1[1]
        edge_len = math.hypot(ex, ey)
        if edge_len == 0:
            return (0.0, 1.0)
        tx, ty = ex / edge_len, ey / edge_len
        perp_x, perp_y = -ty, tx
        dot = perp_x * nx + perp_y * ny
        if dot < 0:
            perp_x, perp_y = -perp_x, -perp_y
        return (perp_x, perp_y)

    def _hit_handle(
        self, wx: float, wy: float, hx: float, hy: float,
    ) -> bool:
        hit_r = _HANDLE_HIT_RADIUS_PX * self._cached_inv_scale
        return (wx - hx) ** 2 + (wy - hy) ** 2 <= hit_r ** 2

    def _find_shared_hexside_endpoints(
        self, layout: Layout, layer: HexsideLayer, selected: HexsideObject, which: str,
    ) -> list[tuple[HexsideObject, str]]:
        """Find other hexsides sharing the same raw vertex position.

        Returns list of (obj, "a"|"b") for all hexsides (excluding selected) whose
        v1 or v2 is geometrically identical to the target vertex of selected.
        """
        direction = layer._find_direction(selected)
        if direction is None:
            return []
        v1, v2 = hex_edge_vertices(layout, selected.hex_a(), direction)
        target_v = v1 if which == "a" else v2

        result = []
        for obj in layer.hexsides.values():
            if obj is selected:
                continue
            d = layer._find_direction(obj)
            if d is None:
                continue
            ev1, ev2 = hex_edge_vertices(layout, obj.hex_a(), d)
            if math.hypot(target_v[0] - ev1[0], target_v[1] - ev1[1]) < 0.5:
                result.append((obj, "a"))
            elif math.hypot(target_v[0] - ev2[0], target_v[1] - ev2[1]) < 0.5:
                result.append((obj, "b"))
        return result

    def _get_hexside_endpoint_base(
        self, layout: Layout, layer: HexsideLayer, obj: HexsideObject, which: str,
    ) -> tuple[float, float]:
        """Compute the base world position for a hexside endpoint (vertex + shift + random displacement)."""
        direction = layer._find_direction(obj)
        if direction is None:
            return (0.0, 0.0)
        v1, v2 = hex_edge_vertices(layout, obj.hex_a(), direction)
        raw_v = v1 if which == "a" else v2

        nx, ny = layer._get_edge_normal(layout, obj.hex_a(), obj.hex_b())
        eff_shift = layer._compute_effective_shift(obj)
        sx, sy = eff_shift * nx, eff_shift * ny
        bx = raw_v[0] + sx
        by = raw_v[1] + sy

        if obj.random and obj.random_endpoint > 0:
            dv = hex_vertex_endpoint_offset(raw_v[0], raw_v[1], obj.random_endpoint)
            bx += dv[0]
            by += dv[1]
        return (bx, by)

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
        layer = self._get_active_hexside_layer()
        if layer is None:
            return

        wx, wy = world_pos.x(), world_pos.y()
        layout = self._get_layout()

        if self.mode == "place":
            if event.button() == Qt.MouseButton.LeftButton:
                self._is_dragging = True
                self._drag_command = CompoundCommand("Place hexsides")
                self._placed_edges_in_drag = set()
                self._place_at_hover(layer, layout)

            elif event.button() == Qt.MouseButton.RightButton:
                if self._hover_edge:
                    hex_c, direction = self._hover_edge
                    neighbor = hex_neighbor(hex_c, direction)
                    existing = layer.get_hexside_at_edge(hex_c, neighbor)
                    if existing:
                        cmd = RemoveHexsideCommand(layer, existing)
                        self._command_stack.execute(cmd)

        elif self.mode == "falloff":
            if event.button() == Qt.MouseButton.LeftButton:
                self._is_dragging = True
                self._drag_command = CompoundCommand("Apply falloff")
                self._falloff_edges_in_drag = set()
                self._apply_falloff_at(layer, layout, wx, wy, hex_coord)

            elif event.button() == Qt.MouseButton.RightButton:
                # Remove falloff from nearest edge
                if self._project.grid_config.is_valid_hex(hex_coord):
                    direction, _dist = nearest_hex_edge(layout, hex_coord, wx, wy)
                    neighbor = hex_neighbor(hex_coord, direction)
                    existing = layer.get_hexside_at_edge(hex_coord, neighbor)
                    if existing and existing.falloff_side:
                        cmd = EditHexsideCommand(layer, existing, falloff_side="")
                        self._command_stack.execute(cmd)

        elif self.mode == "teeth":
            if event.button() == Qt.MouseButton.LeftButton:
                self._is_dragging = True
                self._drag_command = CompoundCommand("Apply teeth")
                self._teeth_edges_in_drag = set()
                self._apply_teeth_at(layer, layout, wx, wy, hex_coord)

            elif event.button() == Qt.MouseButton.RightButton:
                # Remove teeth from nearest edge
                if self._project.grid_config.is_valid_hex(hex_coord):
                    direction, _dist = nearest_hex_edge(layout, hex_coord, wx, wy)
                    neighbor = hex_neighbor(hex_coord, direction)
                    existing = layer.get_hexside_at_edge(hex_coord, neighbor)
                    if existing and existing.teeth_side:
                        cmd = EditHexsideCommand(layer, existing, teeth_side="")
                        self._command_stack.execute(cmd)

        else:  # select mode
            if event.button() != Qt.MouseButton.LeftButton:
                return

            # Check if clicking on a control point of the selected hexside
            if self._selected:
                cp_pos = self._get_control_point_positions(layout, self._selected)
                num_cp = len(self._selected.control_points)
                for i, (cpx, cpy) in enumerate(cp_pos):
                    if self._hit_handle(wx, wy, cpx, cpy):
                        self._interaction = "control_point"
                        self._cp_index = i
                        if i == 0:
                            self._cp_initial_ep = list(self._selected.ep_a)
                            shared = self._find_shared_hexside_endpoints(
                                layout, layer, self._selected, "a",
                            )
                            self._cp_synced_objs = [
                                (obj, w, list(getattr(obj, f"ep_{w}")))
                                for obj, w in shared
                            ]
                        elif i == num_cp - 1:
                            self._cp_initial_ep = list(self._selected.ep_b)
                            shared = self._find_shared_hexside_endpoints(
                                layout, layer, self._selected, "b",
                            )
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

            # Try selecting a hexside
            hit = layer.hit_test(wx, wy, layout)
            if hit:
                self._selected = hit
                self._notify_selection()
            else:
                self._selected = None
                self._notify_selection()
            self._interaction = None

    def mouse_move(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex,
    ) -> None:
        self._last_world_pos = world_pos
        wx, wy = world_pos.x(), world_pos.y()

        layer = self._get_active_hexside_layer()
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
                else:
                    self._hover_edge = None

            # Handle drag placement
            if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
                self._place_at_hover(layer, layout)

        elif self.mode == "falloff":
            # Hover edge detection (same as place mode)
            if not self._project.grid_config.is_valid_hex(hex_coord):
                self._hover_edge = None
            else:
                direction, dist = nearest_hex_edge(layout, hex_coord, wx, wy)
                if dist < self._project.grid_config.hex_size * 0.6:
                    self._hover_edge = (hex_coord, direction)
                else:
                    self._hover_edge = None

            # Handle drag falloff application
            if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
                self._apply_falloff_at(layer, layout, wx, wy, hex_coord)

        elif self.mode == "teeth":
            # Hover edge detection (same as place/falloff mode)
            if not self._project.grid_config.is_valid_hex(hex_coord):
                self._hover_edge = None
            else:
                direction, dist = nearest_hex_edge(layout, hex_coord, wx, wy)
                if dist < self._project.grid_config.hex_size * 0.6:
                    self._hover_edge = (hex_coord, direction)
                else:
                    self._hover_edge = None

            # Handle drag teeth application
            if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
                self._apply_teeth_at(layer, layout, wx, wy, hex_coord)

        elif self.mode == "select":
            if self._interaction == "control_point" and self._selected:
                direction_idx = layer._find_direction(self._selected)
                if direction_idx is None:
                    return

                v1, v2 = hex_edge_vertices(layout, self._selected.hex_a(), direction_idx)
                nx, ny = layer._get_edge_normal(
                    layout, self._selected.hex_a(), self._selected.hex_b(),
                )
                eff_shift = layer._compute_effective_shift(self._selected)
                sx, sy = eff_shift * nx, eff_shift * ny

                # Compute base vertices (same as _compute_hexside_path / _get_control_point_positions)
                base_v1 = (v1[0] + sx, v1[1] + sy)
                base_v2 = (v2[0] + sx, v2[1] + sy)
                if self._selected.random and self._selected.random_endpoint > 0:
                    dv1 = hex_vertex_endpoint_offset(v1[0], v1[1], self._selected.random_endpoint)
                    dv2 = hex_vertex_endpoint_offset(v2[0], v2[1], self._selected.random_endpoint)
                    base_v1 = (base_v1[0] + dv1[0], base_v1[1] + dv1[1])
                    base_v2 = (base_v2[0] + dv2[0], base_v2[1] + dv2[1])

                num_cp = len(self._selected.control_points)
                if self._cp_index == 0:
                    # Endpoint A: free 2D movement, clamped to 2 hexes (move all sharing same vertex)
                    ep_dx, ep_dy = self._clamp_to_2hex(wx - base_v1[0], wy - base_v1[1])
                    self._selected.ep_a = [ep_dx, ep_dy]
                    for obj, which, _initial in self._cp_synced_objs:
                        bx, by = self._get_hexside_endpoint_base(layout, layer, obj, which)
                        sx, sy = self._clamp_to_2hex(wx - bx, wy - by)
                        setattr(obj, f"ep_{which}", [sx, sy])
                elif self._cp_index == num_cp - 1:
                    # Endpoint B: free 2D movement, clamped to 2 hexes (move all sharing same vertex)
                    ep_dx, ep_dy = self._clamp_to_2hex(wx - base_v2[0], wy - base_v2[1])
                    self._selected.ep_b = [ep_dx, ep_dy]
                    for obj, which, _initial in self._cp_synced_objs:
                        bx, by = self._get_hexside_endpoint_base(layout, layer, obj, which)
                        sx, sy = self._clamp_to_2hex(wx - bx, wy - by)
                        setattr(obj, f"ep_{which}", [sx, sy])
                elif self._cp_index in (1, 2):
                    # Inner control points: free 2D movement, clamped to 2 hexes
                    ex = base_v2[0] - base_v1[0]
                    ey = base_v2[1] - base_v1[1]
                    edge_len = math.hypot(ex, ey)
                    if edge_len > 0:
                        tx, ty = ex / edge_len, ey / edge_len
                        perp_x, perp_y = -ty, tx
                        # Orient perpendicular toward hex interior (same as _compute_hexside_path)
                        dot = perp_x * nx + perp_y * ny
                        if dot < 0:
                            perp_x, perp_y = -perp_x, -perp_y
                    else:
                        perp_x, perp_y = 0.0, 1.0
                    t = self._selected.cp_t_positions()[self._cp_index]
                    base_x = base_v1[0] + ex * t
                    base_y = base_v1[1] + ey * t
                    # Apply random_offset to base (matches _compute_hexside_path and _get_control_point_positions)
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
                    self._command_stack.push_compound(self._drag_command)
                self._drag_command = None
                self._placed_edges_in_drag.clear()

        elif self.mode == "falloff":
            if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
                self._is_dragging = False
                if self._drag_command and not self._drag_command.is_empty:
                    self._command_stack.push_compound(self._drag_command)
                self._drag_command = None
                self._falloff_edges_in_drag.clear()

        elif self.mode == "teeth":
            if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
                self._is_dragging = False
                if self._drag_command and not self._drag_command.is_empty:
                    self._command_stack.push_compound(self._drag_command)
                self._drag_command = None
                self._teeth_edges_in_drag.clear()

        elif self.mode == "select":
            if event.button() == Qt.MouseButton.LeftButton and self._interaction == "control_point":
                self._cp_dragging = False
                if self._selected:
                    layer = self._get_active_hexside_layer()
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
                            cmd = EditHexsideCommand(layer, self._selected, ip_a=new_ip)
                            self._command_stack.execute(cmd)
                        elif layer:
                            layer.mark_dirty()  # Rebuild cache with all objects visible
                    elif self._cp_index == 2:
                        new_ip = list(self._selected.ip_b)
                        self._selected.ip_b = list(self._cp_initial_ip)
                        if new_ip != self._cp_initial_ip and layer:
                            cmd = EditHexsideCommand(layer, self._selected, ip_b=new_ip)
                            self._command_stack.execute(cmd)
                        elif layer:
                            layer.mark_dirty()  # Rebuild cache with all objects visible
                self._interaction = None
                self._cp_synced_objs = []

    def apply_random_endpoint_with_sync(self, new_value: float) -> None:
        """Apply random_endpoint change to selected hexside and all hexsides sharing its vertices.

        Mirrors the path_tool approach: all objects at the same vertex must carry
        the same amplitude so that hex_vertex_endpoint_offset() produces identical
        displacements, guaranteeing visual connectivity.
        """
        if self.mode != "select" or self._selected is None:
            return
        layer = self._get_active_hexside_layer()
        if layer is None:
            return

        layout = self._get_layout()

        # Gather all hexsides connected at either vertex (deduplicated)
        connected_a = self._find_shared_hexside_endpoints(layout, layer, self._selected, "a")
        connected_b = self._find_shared_hexside_endpoints(layout, layer, self._selected, "b")

        all_objs: list[HexsideObject] = [self._selected]
        seen_ids: set[int] = {id(self._selected)}
        for obj, _ in connected_a + connected_b:
            if id(obj) not in seen_ids:
                all_objs.append(obj)
                seen_ids.add(id(obj))

        changes = [(obj, obj.random_endpoint, new_value) for obj in all_objs]
        cmd = SyncRandomEndpointCommand(layer, changes)
        self._command_stack.execute(cmd)

    # --- Falloff mode helpers ---

    def _apply_falloff_at(
        self, layer: HexsideLayer, layout: Layout,
        wx: float, wy: float, hex_coord: Hex,
    ) -> None:
        """Apply falloff at the nearest hex edge, creating an invisible hexside if needed."""
        if not self._project.grid_config.is_valid_hex(hex_coord):
            return

        direction, _dist = nearest_hex_edge(layout, hex_coord, wx, wy)
        neighbor = hex_neighbor(hex_coord, direction)
        key = hex_edge_key(hex_coord, neighbor)

        if key in self._falloff_edges_in_drag:
            return
        self._falloff_edges_in_drag.add(key)

        # Canonical order
        a_q, a_r = key[0]
        b_q, b_r = key[1]
        hex_a = Hex(a_q, a_r)
        hex_b = Hex(b_q, b_r)

        # Determine which side of the edge was clicked
        ca_x, ca_y = hex_to_pixel(layout, hex_a)
        cb_x, cb_y = hex_to_pixel(layout, hex_b)
        nx = cb_x - ca_x
        ny = cb_y - ca_y
        length = math.hypot(nx, ny)
        if length == 0:
            return
        nx /= length
        ny /= length
        mid_x = (ca_x + cb_x) / 2
        mid_y = (ca_y + cb_y) / 2
        dot = (wx - mid_x) * nx + (wy - mid_y) * ny
        new_side = "b" if dot > 0 else "a"

        # Check that the SOURCE hex (opposite side) has a fill
        if new_side == "a":
            source_key = (b_q, b_r)
        else:
            source_key = (a_q, a_r)
        has_fill = (
            source_key in layer._fill_colors
            or source_key in layer._fill_textures
        )
        if not has_fill:
            return

        falloff_kwargs = dict(
            falloff_side=new_side,
            falloff_width=self.falloff_width,
            falloff_amount=self.falloff_amount,
            falloff_random=self.falloff_random,
            falloff_random_seed=_random.randint(0, 999999),
        )

        existing = layer.get_hexside_at_edge(hex_a, hex_b)
        if existing:
            # Edit existing hexside to add/update falloff
            cmd = EditHexsideCommand(layer, existing, **falloff_kwargs)
        else:
            # Create invisible carrier hexside (width=0, opacity=0)
            obj = HexsideObject(
                hex_a_q=a_q, hex_a_r=a_r,
                hex_b_q=b_q, hex_b_r=b_r,
                width=0.0,
                opacity=0.0,
                **falloff_kwargs,
            )
            cmd = PlaceHexsideCommand(layer, obj)

        if self._drag_command:
            self._drag_command.add(cmd)
            cmd.execute()
        else:
            self._command_stack.execute(cmd)

    # --- Teeth mode helpers ---

    def _apply_teeth_at(
        self, layer: HexsideLayer, layout: Layout,
        wx: float, wy: float, hex_coord: Hex,
    ) -> None:
        """Apply teeth at the nearest hex edge, creating an invisible hexside if needed."""
        if not self._project.grid_config.is_valid_hex(hex_coord):
            return

        direction, _dist = nearest_hex_edge(layout, hex_coord, wx, wy)
        neighbor = hex_neighbor(hex_coord, direction)
        key = hex_edge_key(hex_coord, neighbor)

        if key in self._teeth_edges_in_drag:
            return
        self._teeth_edges_in_drag.add(key)

        # Canonical order
        a_q, a_r = key[0]
        b_q, b_r = key[1]
        hex_a = Hex(a_q, a_r)
        hex_b = Hex(b_q, b_r)

        # Determine which side of the edge was clicked
        ca_x, ca_y = hex_to_pixel(layout, hex_a)
        cb_x, cb_y = hex_to_pixel(layout, hex_b)
        nx = cb_x - ca_x
        ny = cb_y - ca_y
        length = math.hypot(nx, ny)
        if length == 0:
            return
        nx /= length
        ny /= length
        mid_x = (ca_x + cb_x) / 2
        mid_y = (ca_y + cb_y) / 2
        dot = (wx - mid_x) * nx + (wy - mid_y) * ny
        new_side = "b" if dot > 0 else "a"

        teeth_kwargs = dict(
            teeth_side=new_side,
            teeth_count=self.teeth_count,
            teeth_size=self.teeth_size,
            teeth_color=self.teeth_color,
            teeth_opacity=self.teeth_opacity,
        )

        existing = layer.get_hexside_at_edge(hex_a, hex_b)
        if existing:
            # Edit existing hexside to add/update teeth
            cmd = EditHexsideCommand(layer, existing, **teeth_kwargs)
        else:
            # Create invisible carrier hexside (width=0, opacity=0)
            obj = HexsideObject(
                hex_a_q=a_q, hex_a_r=a_r,
                hex_b_q=b_q, hex_b_r=b_r,
                width=0.0,
                opacity=0.0,
                **teeth_kwargs,
            )
            cmd = PlaceHexsideCommand(layer, obj)

        if self._drag_command:
            self._drag_command.add(cmd)
            cmd.execute()
        else:
            self._command_stack.execute(cmd)

    def key_press(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete and self._selected:
            layer = self._get_active_hexside_layer()
            if layer:
                cmd = RemoveHexsideCommand(layer, self._selected)
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

        # Place / Falloff / Teeth mode: highlight hover edge
        if self.mode in ("place", "falloff", "teeth") and self._hover_edge:
            hex_c, direction = self._hover_edge
            v1, v2 = hex_edge_vertices(layout, hex_c, direction)

            preview_color = QColor(self.color)
            preview_color.setAlpha(128)
            pen = QPen(preview_color, max(self.width, 3.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(
                QPointF(v1[0], v1[1]), QPointF(v2[0], v2[1]),
            )

        # Select mode: draw selection + control point handles
        if self.mode == "select" and self._selected:
            obj = self._selected
            inv_scale = self._cached_inv_scale

            # During CP drag: render dragged objects as overlay preview
            # (layer cache has them hidden via _drag_hidden_keys)
            if self._cp_dragging:
                layer = self._get_active_hexside_layer()
                if layer:
                    preview_objs = [obj]
                    for synced_obj, _, _ in self._cp_synced_objs:
                        preview_objs.append(synced_obj)
                    for pobj in preview_objs:
                        eff_shift = layer._compute_effective_shift(pobj)
                        path = layer._get_cached_hexside_path(layout, pobj, eff_shift)
                        if path.isEmpty():
                            continue
                        # Outline pass
                        if pobj.outline:
                            painter.save()
                            if pobj.outline_opacity < 1.0:
                                painter.setOpacity(pobj.outline_opacity)
                            total_w = pobj.width + pobj.outline_width * 2
                            ol_pen = QPen(QColor(pobj.outline_color), total_w)
                            ol_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                            ol_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                            painter.setPen(ol_pen)
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawPath(path)
                            painter.restore()
                        # Main line pass
                        painter.save()
                        if pobj.opacity < 1.0:
                            painter.setOpacity(pobj.opacity)
                        pen = QPen(QColor(pobj.color), pobj.width)
                        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                        painter.setPen(pen)
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
