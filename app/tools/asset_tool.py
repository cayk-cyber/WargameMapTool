"""Asset tool - place, move, rotate, scale assets."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtGui import QPolygonF

from app.commands.asset_commands import (
    MoveAssetCommand,
    PaintMaskCommand,
    PlaceAssetCommand,
    RemoveAssetCommand,
    TransformAssetCommand,
)
from app.commands.command import CompoundCommand
from app.commands.command_stack import CommandStack
from app.hex.hex_math import (
    Hex,
    Layout,
    hex_corner_offset,
    hex_corners,
    hex_distance,
    hex_to_pixel,
    pixel_to_hex,
)
from app.layers.asset_layer import AssetLayer
from app.models.asset_object import AssetObject
from app.models.project import Project
from app.tools.base_tool import Tool

# Handle size in screen pixels (constant regardless of zoom)
_HANDLE_SCREEN_PX = 6.0
# Distance of rotation handle above asset (in screen pixels)
_ROT_HANDLE_OFFSET_PX = 25.0
# Hit radius for handle detection (screen pixels)
_HANDLE_HIT_RADIUS_PX = 10.0


class AssetTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack
        self.snap_to_hex: bool = True
        self.mode: str = "place"  # "place", "select", or "erase"
        self.placement_radius: int = 0
        self.placement_scale: float = 1.0
        self.random_size: bool = False
        self.random_size_min: float = 0.5
        self.random_size_max: float = 1.5
        self.placement_rotation: float = 0.0
        self.random_rotation: bool = False
        self.rasterize: bool = False
        self.rasterize_mode: str = "edge"  # "edge" or "corner"
        self.rasterize_fixed: bool = False
        self.rasterize_fixed_pct: int = 50  # 0-100%
        self.randomize_assets: bool = False
        self._random_pool: list[str] = []
        self._selected_asset: AssetObject | None = None
        self._pending_image_path: str | None = None
        self._pending_pixmap: QPixmap | None = None
        self._last_world_pos: QPointF = QPointF(0, 0)

        # Drag state
        self._interaction: str | None = None  # "move", "scale", "rotate"
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0
        self._drag_asset_start_x = 0.0
        self._drag_asset_start_y = 0.0

        # Scale drag state
        self._scale_initial: float = 1.0
        self._scale_initial_dist: float = 1.0

        # Rotate drag state
        self._rotate_initial: float = 0.0
        self._rotate_initial_angle: float = 0.0

        # Modifier+drag adjustment state (place mode)
        # "scale" = Ctrl+drag vertical, "rotation" = Alt+drag horizontal
        self._adjust_dragging: bool = False
        self._adjust_type: str = ""  # "scale" or "rotation"
        self._adjust_screen_start_x: float = 0.0
        self._adjust_screen_start_y: float = 0.0
        self._adjust_initial_scale: float = 1.0
        self._adjust_initial_rotation: float = 0.0
        self._adjust_preview_pos: tuple[float, float] | None = None

        # Callback for UI sync after modifier+drag adjustment
        self._on_placement_changed: callable | None = None

        # Selection change callback
        self.on_selection_changed = None

        # Auto-Text: after placing a single asset, fire this callback with (x, y)
        # so the options panel can prompt for a label and place it in a TextLayer.
        self.auto_text_enabled: bool = False
        self.on_auto_text_place = None  # Callable[[float, float], None] | None

        # Cached inverse zoom scale (updated each paint_overlay call)
        self._cached_inv_scale: float = 1.0

        # Erase mode state
        self.erase_brush_size: float = 20.0
        self._erase_stroke_active: bool = False
        self._erase_pre_snapshot = None  # QImage snapshot before stroke
        self._last_erase_pos: QPointF | None = None

        # Erase size drag state (Ctrl+drag vertical)
        self._erase_size_dragging: bool = False
        self._erase_size_start_y: float = 0.0
        self._erase_size_initial: float = 20.0
        self._on_erase_size_changed = None  # Callable[[float], None] | None

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.snap_to_hex = True
        self.mode = "place"
        self.placement_radius = 0
        self.placement_scale = 1.0
        self.random_size = False
        self.random_size_min = 0.5
        self.random_size_max = 1.5
        self.placement_rotation = 0.0
        self.random_rotation = False
        self.rasterize = False
        self.rasterize_mode = "edge"
        self.rasterize_fixed = False
        self.rasterize_fixed_pct = 50
        self.randomize_assets = False
        self._random_pool = []
        self.auto_text_enabled = False
        self._selected_asset = None
        self._interaction = None
        self._adjust_dragging = False
        self._adjust_type = ""
        self._adjust_preview_pos = None

    @property
    def name(self) -> str:
        return "Asset"

    @property
    def cursor(self) -> Qt.CursorShape:
        if self.mode == "erase":
            return Qt.CursorShape.CrossCursor
        if self._pending_image_path:
            return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.ArrowCursor

    @property
    def selected_asset(self) -> AssetObject | None:
        return self._selected_asset

    def _get_active_asset_layer(self) -> AssetLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, AssetLayer):
            return layer
        return None

    def _notify_selection(self) -> None:
        """Notify listener that the selected asset changed."""
        if self.on_selection_changed:
            self.on_selection_changed(self._selected_asset)

    def set_pending_image(self, path: str) -> None:
        self._pending_image_path = path
        self._pending_pixmap = QPixmap(path) if path else None
        self._selected_asset = None

    def set_random_pool(self, paths: list[str]) -> None:
        """Set the random asset pool and pick first random image."""
        self._random_pool = list(paths)
        if self._random_pool:
            self._pick_random_image()
        else:
            self._pending_image_path = None
            self._pending_pixmap = None

    def _pick_random_image(self) -> None:
        """Pick a random image from the pool and set as pending."""
        if not self._random_pool:
            return
        path = random.choice(self._random_pool)
        self._pending_image_path = path
        self._pending_pixmap = QPixmap(path) if path else None

    # --- Radius helpers ---

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

    # --- Rasterize snap ---

    def _get_raster_directions(self, layout: Layout) -> list[tuple[float, float]]:
        """Return 6 radial direction vectors from hex center.

        Edge mode: directions to edge midpoints (average of adjacent corners).
        Corner mode: directions to hex corners.
        """
        if self.rasterize_mode == "corner":
            return [hex_corner_offset(layout, i) for i in range(6)]
        # Edge midpoints = average of corner i and corner (i+1)%6
        dirs = []
        for i in range(6):
            ox1, oy1 = hex_corner_offset(layout, i)
            ox2, oy2 = hex_corner_offset(layout, (i + 1) % 6)
            dirs.append(((ox1 + ox2) / 2, (oy1 + oy2) / 2))
        return dirs

    def _snap_to_raster(
        self, layout: Layout, wx: float, wy: float
    ) -> tuple[float, float]:
        """Snap world position to the nearest radial line from hex center.

        Returns the projected (x, y) on the nearest direction line.
        Parameter t ranges from 0 (center) to 1 (edge midpoint or corner).
        """
        h = pixel_to_hex(layout, wx, wy)
        cx, cy = hex_to_pixel(layout, h)
        dirs = self._get_raster_directions(layout)

        # Vector from center to mouse
        mx, my = wx - cx, wy - cy

        # Find nearest radial line by angle
        mouse_angle = math.atan2(my, mx)
        best_idx = 0
        best_diff = float("inf")
        for i, (dx, dy) in enumerate(dirs):
            dir_angle = math.atan2(dy, dx)
            diff = abs(
                math.atan2(
                    math.sin(mouse_angle - dir_angle),
                    math.cos(mouse_angle - dir_angle),
                )
            )
            if diff < best_diff:
                best_diff = diff
                best_idx = i

        # Project onto the nearest direction line
        dx, dy = dirs[best_idx]
        dot_dd = dx * dx + dy * dy
        if dot_dd < 1e-9:
            return cx, cy
        if self.rasterize_fixed:
            t = self.rasterize_fixed_pct / 100.0
        else:
            t = max(0.0, min(1.0, (mx * dx + my * dy) / dot_dd))
        return cx + dx * t, cy + dy * t

    # --- Handle geometry ---

    def _get_asset_corners(self, asset: AssetObject) -> list[tuple[float, float]]:
        """Get the 4 rotated corners of the asset in world coordinates."""
        pm = asset.get_pixmap()
        if pm.isNull():
            hw, hh = 16.0, 16.0
        else:
            hw = pm.width() * asset.scale / 2
            hh = pm.height() * asset.scale / 2

        # Local corners (before rotation)
        local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]

        angle_rad = math.radians(asset.rotation)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        return [
            (lx * cos_a - ly * sin_a + asset.x,
             lx * sin_a + ly * cos_a + asset.y)
            for lx, ly in local
        ]

    def _get_rotation_handle_pos(self, asset: AssetObject, inv_scale: float) -> tuple[float, float]:
        """Get the rotation handle position (above top center in rotated space)."""
        pm = asset.get_pixmap()
        if pm.isNull():
            hh = 16.0
        else:
            hh = pm.height() * asset.scale / 2

        offset = hh + _ROT_HANDLE_OFFSET_PX * inv_scale
        angle_rad = math.radians(asset.rotation)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        # Local position: (0, -offset) rotated
        rx = -(-offset) * sin_a + asset.x
        ry = (-offset) * cos_a + asset.y
        return (rx, ry)

    def _hit_handle(
        self, world_x: float, world_y: float, hx: float, hy: float, inv_scale: float,
    ) -> bool:
        """Check if a point hits a handle (in world coordinates)."""
        hit_r = _HANDLE_HIT_RADIUS_PX * inv_scale
        return (world_x - hx) ** 2 + (world_y - hy) ** 2 <= hit_r ** 2

    # --- Handle interaction helper ---

    def _try_handle_interaction(self, wx: float, wy: float) -> bool:
        """Try to start a handle interaction with the selected asset.

        Returns True if a handle or asset body was hit.
        """
        if not self._selected_asset:
            return False

        inv_scale = self._cached_inv_scale

        # Check rotation handle
        rot_pos = self._get_rotation_handle_pos(self._selected_asset, inv_scale)
        if self._hit_handle(wx, wy, rot_pos[0], rot_pos[1], inv_scale):
            self._interaction = "rotate"
            self._rotate_initial = self._selected_asset.rotation
            self._rotate_initial_angle = math.degrees(
                math.atan2(wx - self._selected_asset.x,
                           -(wy - self._selected_asset.y))
            )
            return True

        # Check corner handles (scale)
        corners = self._get_asset_corners(self._selected_asset)
        for cx, cy in corners:
            if self._hit_handle(wx, wy, cx, cy, inv_scale):
                self._interaction = "scale"
                self._scale_initial = self._selected_asset.scale
                self._scale_initial_dist = math.hypot(
                    wx - self._selected_asset.x,
                    wy - self._selected_asset.y,
                )
                if self._scale_initial_dist < 1.0:
                    self._scale_initial_dist = 1.0
                return True

        # Check asset body (move)
        if self._selected_asset.contains_point(wx, wy):
            self._interaction = "move"
            self._drag_start_x = wx
            self._drag_start_y = wy
            self._drag_asset_start_x = self._selected_asset.x
            self._drag_asset_start_y = self._selected_asset.y
            return True

        return False

    # --- Mouse handling ---

    def mouse_press(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        layer = self._get_active_asset_layer()
        if layer is None:
            return

        wx, wy = world_pos.x(), world_pos.y()

        if self.mode == "erase":
            if event.button() != Qt.MouseButton.LeftButton:
                return
            # Ctrl+click: start brush size drag (no erasing)
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._erase_size_dragging = True
                self._erase_size_start_y = event.position().y()
                self._erase_size_initial = self.erase_brush_size
                return
            # Ensure the mask covers the full map bounds
            map_bounds = self._project.grid_config.get_map_pixel_bounds()
            layer.ensure_mask(map_bounds)
            # Snapshot before the stroke (for undo)
            self._erase_pre_snapshot = layer.get_mask_snapshot()
            self._erase_stroke_active = True
            layer.begin_erase_stroke()
            self._last_erase_pos = world_pos
            # Apply first erase point
            layer.erase_at(wx, wy, self.erase_brush_size)
            return

        if event.button() != Qt.MouseButton.LeftButton:
            if event.button() != Qt.MouseButton.RightButton:
                return

        if self.mode == "place":
            # --- Place mode ---
            if event.button() == Qt.MouseButton.RightButton:
                # Delete asset under cursor
                hit = layer.hit_test(wx, wy)
                if hit:
                    cmd = RemoveAssetCommand(layer, hit)
                    self._command_stack.execute(cmd)
                return

            # Ctrl+left-click: start scale drag, Alt+left-click: start rotation drag
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            if ctrl or alt:
                pos = event.position()
                self._adjust_dragging = True
                self._adjust_type = "scale" if ctrl else "rotation"
                self._adjust_screen_start_x = pos.x()
                self._adjust_screen_start_y = pos.y()
                self._adjust_initial_scale = self.placement_scale
                self._adjust_initial_rotation = self.placement_rotation
                # Freeze preview position at current spot
                if self.snap_to_hex:
                    grid_layout = self._project.grid_config.create_layout()
                    fx, fy = hex_to_pixel(grid_layout, hex_coord)
                    self._adjust_preview_pos = (fx, fy)
                elif self.rasterize:
                    grid_layout = self._project.grid_config.create_layout()
                    fx, fy = self._snap_to_raster(
                        grid_layout,
                        self._last_world_pos.x(),
                        self._last_world_pos.y(),
                    )
                    self._adjust_preview_pos = (fx, fy)
                else:
                    self._adjust_preview_pos = (
                        self._last_world_pos.x(),
                        self._last_world_pos.y(),
                    )
                return

            # Left-click: place pending image
            if self._pending_image_path:
                # Reject placement outside the valid area
                if not self._project.grid_config.is_within_placement_area(
                    world_pos, hex_coord, allow_border_zone=True
                ):
                    return

                # Radius placement (snap_to_hex required)
                if self.snap_to_hex and self.placement_radius > 0:
                    hexes = self._get_hexes_in_radius(
                        hex_coord, self.placement_radius
                    )
                    if not hexes:
                        return
                    grid_layout = self._project.grid_config.create_layout()
                    compound = CompoundCommand("Place assets")
                    for h in hexes:
                        hx, hy = hex_to_pixel(grid_layout, h)
                        if layer.has_asset_at(self._pending_image_path, hx, hy):
                            continue
                        scale = (
                            random.uniform(self.random_size_min, self.random_size_max)
                            if self.random_size else self.placement_scale
                        )
                        rotation = (
                            random.uniform(0, 360) if self.random_rotation
                            else self.placement_rotation
                        )
                        asset = AssetObject(
                            image_path=self._pending_image_path,
                            x=hx, y=hy,
                            scale=scale, rotation=rotation,
                            snap_to_hex=True,
                        )
                        cmd = PlaceAssetCommand(layer, asset)
                        cmd.execute()
                        compound.add(cmd)
                    # Push compound as single undo step
                    self._command_stack._undo_stack.append(compound)
                    self._command_stack._redo_stack.clear()
                    if len(self._command_stack._undo_stack) > self._command_stack._max_size:
                        self._command_stack._undo_stack.pop(0)
                    self._command_stack.stack_changed.emit()
                else:
                    # Single asset placement
                    x, y = wx, wy
                    if self.snap_to_hex:
                        grid_layout = self._project.grid_config.create_layout()
                        x, y = hex_to_pixel(grid_layout, hex_coord)
                    elif self.rasterize:
                        grid_layout = self._project.grid_config.create_layout()
                        x, y = self._snap_to_raster(grid_layout, wx, wy)

                    # Skip if same asset already at exact position
                    if layer.has_asset_at(self._pending_image_path, x, y):
                        return

                    scale = (
                        random.uniform(self.random_size_min, self.random_size_max)
                        if self.random_size else self.placement_scale
                    )
                    rotation = (
                        random.uniform(0, 360) if self.random_rotation
                        else self.placement_rotation
                    )

                    asset = AssetObject(
                        image_path=self._pending_image_path,
                        x=x, y=y,
                        scale=scale, rotation=rotation,
                        snap_to_hex=self.snap_to_hex,
                    )
                    cmd = PlaceAssetCommand(layer, asset)
                    self._command_stack.execute(cmd)

                    # Auto-Text: prompt for a label immediately after placement
                    if self.auto_text_enabled and callable(self.on_auto_text_place):
                        self.on_auto_text_place(x, y)

                # Pick next random image for next placement
                if self.randomize_assets and self._random_pool:
                    self._pick_random_image()

        else:
            # --- Select mode: ignore right-click ---
            if event.button() == Qt.MouseButton.RightButton:
                return
            # --- Select mode: interact with handles or select asset ---
            if self._try_handle_interaction(wx, wy):
                return

            # No handle hit - try selecting a new asset
            hit = layer.hit_test(wx, wy)
            if hit:
                self._selected_asset = hit
                self._interaction = "move"
                self._drag_start_x = wx
                self._drag_start_y = wy
                self._drag_asset_start_x = hit.x
                self._drag_asset_start_y = hit.y
                self._notify_selection()
            else:
                self._selected_asset = None
                self._notify_selection()

    def mouse_move(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        ctrl_held = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        alt_held = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)

        # Always track mouse position (needed for erase cursor preview too)
        if not ctrl_held and not alt_held:
            self._last_world_pos = world_pos

        # Erase drag
        if self.mode == "erase":
            if self._erase_size_dragging:
                # Ctrl+drag: adjust brush size (drag up = larger, drag down = smaller)
                dy = event.position().y() - self._erase_size_start_y
                new_size = max(5.0, min(300.0, self._erase_size_initial - dy * 0.5))
                self.erase_brush_size = new_size
                if self._on_erase_size_changed:
                    self._on_erase_size_changed(new_size)
                return
            if self._erase_stroke_active and (
                event.buttons() & Qt.MouseButton.LeftButton
            ):
                layer = self._get_active_asset_layer()
                if layer:
                    # Throttle: skip stamps that are too close together
                    min_dist = max(2.0, self.erase_brush_size * 0.15)
                    if self._last_erase_pos is not None:
                        dx = world_pos.x() - self._last_erase_pos.x()
                        dy = world_pos.y() - self._last_erase_pos.y()
                        if dx * dx + dy * dy < min_dist * min_dist:
                            return
                    layer.erase_at(world_pos.x(), world_pos.y(), self.erase_brush_size)
                    self._last_erase_pos = world_pos
            return

        # Modifier+drag adjustment in place mode
        if self._adjust_dragging:
            # Check if the required modifier is still held
            modifier_held = (
                ctrl_held if self._adjust_type == "scale" else alt_held
            )
            if not modifier_held:
                self._adjust_dragging = False
                if self._on_placement_changed:
                    self._on_placement_changed()
                return
            pos = event.position()
            if self._adjust_type == "rotation":
                dx = pos.x() - self._adjust_screen_start_x
                self.placement_rotation = (self._adjust_initial_rotation + dx) % 360
            else:  # scale
                dy = pos.y() - self._adjust_screen_start_y
                self.placement_scale = max(0.1, self._adjust_initial_scale - dy * 0.01)
            return

        if not self._selected_asset or not self._interaction:
            return

        wx, wy = world_pos.x(), world_pos.y()

        if self._interaction == "move":
            dx = wx - self._drag_start_x
            dy = wy - self._drag_start_y
            self._selected_asset.x = self._drag_asset_start_x + dx
            self._selected_asset.y = self._drag_asset_start_y + dy

        elif self._interaction == "scale":
            dist = math.hypot(
                wx - self._selected_asset.x,
                wy - self._selected_asset.y,
            )
            ratio = dist / self._scale_initial_dist
            new_scale = max(0.05, self._scale_initial * ratio)
            self._selected_asset.scale = new_scale

        elif self._interaction == "rotate":
            current_angle = math.degrees(
                math.atan2(wx - self._selected_asset.x,
                           -(wy - self._selected_asset.y))
            )
            delta = current_angle - self._rotate_initial_angle
            self._selected_asset.rotation = self._rotate_initial + delta

    def mouse_release(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        # Erase stroke end: push undo command
        if self.mode == "erase" and event.button() == Qt.MouseButton.LeftButton:
            if self._erase_size_dragging:
                self._erase_size_dragging = False
                return
            if self._erase_stroke_active:
                self._erase_stroke_active = False
                layer = self._get_active_asset_layer()
                if layer and self._erase_pre_snapshot is not None:
                    # Close persistent painter before reading back the mask pixels
                    layer.end_erase_stroke()
                    post_snapshot = layer.get_mask_snapshot()
                    cmd = PaintMaskCommand(layer, self._erase_pre_snapshot, post_snapshot)
                    # Push without re-executing (stroke already applied during drag)
                    self._command_stack._undo_stack.append(cmd)
                    self._command_stack._redo_stack.clear()
                    if len(self._command_stack._undo_stack) > self._command_stack._max_size:
                        self._command_stack._undo_stack.pop(0)
                    self._command_stack.stack_changed.emit()
                self._erase_pre_snapshot = None
                self._last_erase_pos = None
            return

        # End modifier+drag adjustment
        if self._adjust_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._adjust_dragging = False
            if self._on_placement_changed:
                self._on_placement_changed()
            return

        # Right-click release: nothing to do (delete handled in mouse_press)
        if event.button() != Qt.MouseButton.LeftButton or not self._interaction:
            return

        if not self._selected_asset:
            self._interaction = None
            return

        if self._interaction == "move":
            new_x = self._selected_asset.x
            new_y = self._selected_asset.y

            if self.snap_to_hex:
                layout = self._project.grid_config.create_layout()
                snap_hex = Hex(hex_coord.q, hex_coord.r)
                new_x, new_y = hex_to_pixel(layout, snap_hex)
            elif self.rasterize:
                layout = self._project.grid_config.create_layout()
                new_x, new_y = self._snap_to_raster(layout, new_x, new_y)

            # Reset to start position then use command for undo support
            self._selected_asset.x = self._drag_asset_start_x
            self._selected_asset.y = self._drag_asset_start_y

            if (new_x != self._drag_asset_start_x or
                    new_y != self._drag_asset_start_y):
                layer = self._get_active_asset_layer()
                if layer:
                    cmd = MoveAssetCommand(layer, self._selected_asset, new_x, new_y)
                    self._command_stack.execute(cmd)

        elif self._interaction == "scale":
            new_scale = self._selected_asset.scale
            # Reset to initial then use command
            self._selected_asset.scale = self._scale_initial
            if new_scale != self._scale_initial:
                layer = self._get_active_asset_layer()
                if layer:
                    cmd = TransformAssetCommand(
                        layer, self._selected_asset, new_scale=new_scale
                    )
                    self._command_stack.execute(cmd)
            self._notify_selection()

        elif self._interaction == "rotate":
            new_rotation = self._selected_asset.rotation
            # Reset to initial then use command
            self._selected_asset.rotation = self._rotate_initial
            if new_rotation != self._rotate_initial:
                layer = self._get_active_asset_layer()
                if layer:
                    cmd = TransformAssetCommand(
                        layer, self._selected_asset, new_rotation=new_rotation
                    )
                    self._command_stack.execute(cmd)
            self._notify_selection()

        self._interaction = None

    def key_press(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete and self._selected_asset:
            layer = self._get_active_asset_layer()
            if layer:
                cmd = RemoveAssetCommand(layer, self._selected_asset)
                self._command_stack.execute(cmd)
                self._selected_asset = None
                self._notify_selection()
        elif event.key() == Qt.Key.Key_Escape:
            self._pending_image_path = None
            self._selected_asset = None
            self._notify_selection()

    def key_release(self, event: QKeyEvent) -> None:
        if not self._adjust_dragging:
            return
        # Stop scale drag when Ctrl is released
        if event.key() == Qt.Key.Key_Control and self._adjust_type == "scale":
            self._adjust_dragging = False
            if self._on_placement_changed:
                self._on_placement_changed()
        # Stop rotation drag when Alt is released
        elif event.key() == Qt.Key.Key_Alt and self._adjust_type == "rotation":
            self._adjust_dragging = False
            if self._on_placement_changed:
                self._on_placement_changed()

    def paint_overlay(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        hover_hex: Hex | None,
    ) -> None:
        # Get inverse scale from painter's current transform and cache it
        transform = painter.worldTransform()
        zoom_scale = transform.m11() if transform.m11() > 0 else 1.0
        inv_scale = 1.0 / zoom_scale
        self._cached_inv_scale = inv_scale

        # Erase mode: show brush circle cursor
        if self.mode == "erase":
            px, py = self._last_world_pos.x(), self._last_world_pos.y()
            r = self.erase_brush_size
            pen = QPen(QColor(255, 80, 80), 1.5)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.save()
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(px, py), r, r)
            painter.restore()
            return

        # Draw selection handles on the selected asset
        if self._selected_asset:
            asset = self._selected_asset
            corners = self._get_asset_corners(asset)

            # Draw selection rectangle (connecting the 4 corners)
            pen = QPen(QColor(0, 120, 255), 2)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 0, 0, 0))

            poly = QPolygonF([QPointF(x, y) for x, y in corners])
            painter.drawPolygon(poly)

            # Draw corner scale handles (filled white squares with blue border)
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

            # Draw rotation handle (circle above top center)
            rot_pos = self._get_rotation_handle_pos(asset, inv_scale)
            rot_x, rot_y = rot_pos

            # Line from top center to rotation handle
            top_mid_x = (corners[0][0] + corners[1][0]) / 2
            top_mid_y = (corners[0][1] + corners[1][1]) / 2

            pen_line = QPen(QColor(0, 120, 255), 1)
            pen_line.setCosmetic(True)
            painter.setPen(pen_line)
            painter.drawLine(QPointF(top_mid_x, top_mid_y), QPointF(rot_x, rot_y))

            # Rotation handle circle
            painter.setPen(pen_solid)
            painter.setBrush(QColor(0, 200, 0))
            rot_radius = _HANDLE_SCREEN_PX * inv_scale
            painter.drawEllipse(QPointF(rot_x, rot_y), rot_radius, rot_radius)

        # Preview placement with actual image
        if self._pending_pixmap and self.mode == "place":
            pm = self._pending_pixmap
            if pm.isNull():
                return

            # Radius preview: show hex outlines + image on each hex
            if self.snap_to_hex and self.placement_radius > 0 and hover_hex:
                hexes = self._get_hexes_in_radius(
                    hover_hex, self.placement_radius
                )
                # Draw hex outlines
                highlight = QColor(0, 170, 255, 60)
                painter.setBrush(highlight)
                pen = QPen(QColor(0, 170, 255), 2)
                pen.setCosmetic(True)
                painter.setPen(pen)
                for h in hexes:
                    corners = hex_corners(layout, h)
                    polygon = QPolygonF([QPointF(cx, cy) for cx, cy in corners])
                    painter.drawPolygon(polygon)
                # Draw image preview on each hex
                for h in hexes:
                    hx, hy = hex_to_pixel(layout, h)
                    painter.save()
                    painter.setOpacity(0.4)
                    painter.translate(hx, hy)
                    painter.rotate(self.placement_rotation)
                    painter.scale(self.placement_scale, self.placement_scale)
                    painter.drawPixmap(
                        int(-pm.width() / 2), int(-pm.height() / 2), pm
                    )
                    painter.restore()
            else:
                # Rasterize guide lines
                if self.rasterize:
                    h = pixel_to_hex(
                        layout,
                        self._last_world_pos.x(),
                        self._last_world_pos.y(),
                    )
                    cx, cy = hex_to_pixel(layout, h)
                    dirs = self._get_raster_directions(layout)
                    guide_pen = QPen(QColor(255, 165, 0, 100), 1.5)
                    guide_pen.setCosmetic(True)
                    guide_pen.setStyle(Qt.PenStyle.DotLine)
                    painter.setPen(guide_pen)
                    for dx, dy in dirs:
                        painter.drawLine(
                            QPointF(cx, cy),
                            QPointF(cx + dx, cy + dy),
                        )

                # Single preview
                if self._adjust_dragging and self._adjust_preview_pos:
                    px, py = self._adjust_preview_pos
                elif self.snap_to_hex and hover_hex:
                    px, py = hex_to_pixel(layout, hover_hex)
                elif self.rasterize:
                    px, py = self._snap_to_raster(
                        layout,
                        self._last_world_pos.x(),
                        self._last_world_pos.y(),
                    )
                else:
                    px, py = self._last_world_pos.x(), self._last_world_pos.y()
                painter.save()
                painter.setOpacity(0.5)
                painter.translate(px, py)
                painter.rotate(self.placement_rotation)
                scale = self.placement_scale
                painter.scale(scale, scale)
                painter.drawPixmap(
                    int(-pm.width() / 2), int(-pm.height() / 2), pm
                )
                painter.restore()
