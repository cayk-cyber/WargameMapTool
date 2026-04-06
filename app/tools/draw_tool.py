"""Draw tool - channel-mask based freeform painting on a draw layer."""

from __future__ import annotations

import math
import random as _random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen

try:
    import numpy as np
    _HAS_NP = True
except ImportError:
    _HAS_NP = False

from app.commands.command_stack import CommandStack
from app.commands.draw_commands import DrawAddChannelCommand, DrawMaskCommand
from app.layers.draw_layer import DrawLayer
from app.models.draw_object import DrawChannel
from app.models.project import Project
from app.tools.base_tool import Tool

# Brush stamp spacing as a fraction of brush size.
# 0.1 = stamps every 10% of brush radius → smooth accumulation, no visible gaps.
_SPACING_FRACTION = 0.1
_MIN_SPACING = 1.0  # world-px

# Minimum screen-pixel drag distance before Shift+drag activates flow-adjust.
# Below this threshold a Shift+click draws a straight line instead.
_SHIFT_DRAG_THRESHOLD = 4.0  # screen-px


class DrawTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack

        # Active channel ID (shared across all draw layers; reset if not found)
        self.active_channel_id: str | None = None

        # Mode: "draw", "fill", or "erase"
        self.mode: str = "draw"

        # Fill mode: expand the filled region outward by this many pixels so it
        # overlaps the painted walls and leaves no gap at the boundary.
        self.fill_expand_px: int = 2

        # Brush settings
        self.brush_id: str = "round_hard"
        self.brush_size: float = 20.0
        self.hardness: float = 1.0

        # Random brush size
        self.random_brush_size: bool = False
        self.random_brush_min: float = 1.0
        self.random_brush_max: float = 50.0

        # Flow: how much alpha is added to the mask per stamp.
        # 0.01 = very soft/slow build-up, 1.0 = immediate full opacity.
        self.flow: float = 1.0

        # Drawing state
        self._is_drawing: bool = False
        self._last_paint_world: QPointF | None = None
        self._mask_snapshot: object = None  # QImage snapshot before current stroke
        self._last_mouse_world: QPointF | None = None

        # Drag-to-adjust state (Ctrl/Alt/Shift + left drag)
        # "size" | "hardness" | "flow" | None
        self._drag_param: str | None = None
        self._drag_start_y: float = 0.0
        self._drag_start_value: float = 0.0
        # Callback invoked when brush params change via drag.
        # Set by the tool options panel to keep sliders in sync.
        self._params_changed_cb = None

        # Shift+click straight-line state (Photoshop-style).
        # _last_stroke_end: world position of the last painted point.
        # _shift_was_drag: True once Shift+drag exceeded the threshold.
        # _shift_held: mirrors whether Shift is currently held (for overlay).
        self._last_stroke_end: QPointF | None = None
        self._shift_was_drag: bool = False
        self._shift_held: bool = False

        # Cached layout for map bounds (updated from paint_overlay)
        self._layout = None

        # Last known viewport rect (updated from paint_overlay).
        # Passed to build_full_cache() so it can limit the cache to the
        # visible area, avoiding the 100M-pixel cap that causes blur.
        self._last_viewport_rect: QRectF | None = None

        # Set to False by the options panel when Texture mode is active but no
        # texture has been selected yet. Prevents painting without content.
        self._can_paint: bool = True

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.active_channel_id = None
        self.mode = "draw"
        self.fill_expand_px = 2
        self.brush_id = "round_hard"
        self.brush_size = 20.0
        self.hardness = 1.0
        self.random_brush_size = False
        self.random_brush_min = 1.0
        self.random_brush_max = 50.0
        self.flow = 1.0
        self._is_drawing = False
        self._last_paint_world = None
        self._mask_snapshot = None
        self._last_mouse_world = None
        self._last_stroke_end = None
        self._shift_was_drag = False
        self._shift_held = False

    @property
    def name(self) -> str:
        return "Draw"

    @property
    def cursor(self) -> Qt.CursorShape:
        return Qt.CursorShape.CrossCursor

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_active_layer(self) -> DrawLayer | None:
        layer = self._project.layer_stack.active_layer
        if isinstance(layer, DrawLayer):
            return layer
        return None

    def _get_active_channel(self, layer: DrawLayer) -> DrawChannel | None:
        """Return the currently active channel, or None if not found."""
        if self.active_channel_id:
            ch = layer.find_channel(self.active_channel_id)
            if ch is not None:
                return ch
        if layer.channels:
            self.active_channel_id = layer.channels[0].id
            return layer.channels[0]
        return None

    def _get_or_create_active_channel(self, layer: DrawLayer) -> DrawChannel:
        """Return the active channel, auto-creating a default one if needed."""
        ch = self._get_active_channel(layer)
        if ch is not None:
            return ch
        # No channels yet — create a default one without a command (silent init)
        new_ch = DrawChannel(name="Channel 1", color="#000000")
        layer.add_channel(new_ch)
        self.active_channel_id = new_ch.id
        return new_ch

    def _get_map_bounds(self) -> QRectF:
        """Return world-space bounding rect of the full hex map."""
        if self._layout is not None:
            try:
                return self._layout.map_bounding_rect()
            except Exception:
                pass
        # Fallback: generous bounds covering any reasonable map
        return QRectF(-200, -200, 5000, 4000)

    def _paint_stamp(self, channel: DrawChannel, wx: float, wy: float) -> QRectF:
        """Paint one brush stamp at world position (wx, wy).

        Returns the world-space bounding rect of the stamp drawn.
        """
        return self._paint_stamps_along_path(
            channel, QPointF(wx, wy), QPointF(wx, wy), 1
        )

    def _paint_stamps_along_path(
        self,
        channel: DrawChannel,
        from_pos: QPointF,
        to_pos: QPointF,
        num_stamps: int,
    ) -> QRectF:
        """Paint num_stamps evenly spaced stamps from from_pos to to_pos.

        All stamps are drawn within a single QPainter session for efficiency.

        Draw mode: SourceOver + flow opacity → accumulating brush.
        Erase mode: DestinationOut + flow opacity → accumulating eraser.

        Returns the world-space bounding rect of all stamps drawn, or an empty
        QRectF if nothing was painted.  Used by mouse_move() to trigger an
        incremental composite update rather than a full rebuild.
        """
        from app.io.brush_cache import get_brush_stamp, get_stamp_draw_size

        if channel.mask_image is None:
            return QRectF()

        size_px = max(1, round(self.brush_size * channel._mask_world_scale))
        stamp = get_brush_stamp(self.brush_id, size_px, self.hardness)
        if stamp is None:
            return QRectF()

        draw_size = get_stamp_draw_size(self.brush_id, self.brush_size)
        draw_px = draw_size * channel._mask_world_scale
        half = draw_px / 2.0
        off_x, off_y = channel._mask_world_offset
        mscale = channel._mask_world_scale

        fx, fy = from_pos.x(), from_pos.y()
        tx, ty = to_pos.x(), to_pos.y()

        # World-space bounding rect covering all stamp positions.
        half_world = draw_size / 2.0
        dirty_rect = QRectF(
            min(fx, tx) - half_world,
            min(fy, ty) - half_world,
            abs(tx - fx) + draw_size,
            abs(ty - fy) + draw_size,
        )

        p = QPainter(channel.mask_image)
        # At full hardness, disable bilinear interpolation so the SDF 1px
        # anti-aliasing edge stays crisp instead of being softened to ~2px.
        hard_brush = self.hardness >= 1.0
        if not hard_brush:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.mode == "erase":
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut
            )
        else:
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
        p.setOpacity(self.flow)

        for i in range(1, num_stamps + 1):
            t = i / num_stamps
            wx = fx + t * (tx - fx)
            wy = fy + t * (ty - fy)
            mx = (wx - off_x) * mscale
            my = (wy - off_y) * mscale
            p.drawImage(QRectF(mx - half, my - half, draw_px, draw_px), stamp)

        p.end()
        return dirty_rect

    def _draw_shift_line(self, world_pos: QPointF) -> None:
        """Draw a straight brushed line from _last_stroke_end to world_pos."""
        if self._last_stroke_end is None:
            return
        layer = self._get_active_layer()
        if layer is None:
            return
        channel = self._get_active_channel(layer)
        if channel is None:
            return
        if self.mode == "draw" and not self._can_paint:
            return

        start = self._last_stroke_end
        end = world_pos
        dist = math.hypot(end.x() - start.x(), end.y() - start.y())
        if dist < 0.5:
            return

        channel.ensure_mask(self._get_map_bounds())
        snapshot = channel.get_mask_snapshot()

        min_dist = max(_MIN_SPACING, self.brush_size * _SPACING_FRACTION)
        num_stamps = max(1, int(dist / min_dist))
        self._paint_stamps_along_path(channel, start, end, num_stamps)
        layer.mark_channel_dirty(channel.id)

        after = channel.get_mask_snapshot()
        cmd = DrawMaskCommand(layer, channel.id, snapshot, after)
        self._command_stack.execute(cmd)
        layer.build_full_cache(self._last_viewport_rect)

        self._last_stroke_end = end

    def _flood_fill_at(self, channel, world_x: float, world_y: float) -> bool:
        """Flood-fill the channel mask from a world position.

        Uses a scanline BFS so large fills finish without excessive recursion.
        Returns True if any pixels were changed.
        """
        if not _HAS_NP:
            return False

        mask = channel.mask_image
        if mask is None:
            return False

        w, h = mask.width(), mask.height()
        off_x, off_y = channel._mask_world_offset
        mscale = channel._mask_world_scale
        px = int((world_x - off_x) * mscale)
        py = int((world_y - off_y) * mscale)

        if not (0 <= px < w and 0 <= py < h):
            return False

        # Read mask as writable numpy array (ARGB32_Premultiplied = BGRA bytes)
        bpl = mask.bytesPerLine()
        arr = np.frombuffer(mask.constBits(), dtype=np.uint8, count=h * bpl)
        arr = arr.reshape(h, bpl)[:, : w * 4].reshape(h, w, 4).copy()
        alpha = arr[:, :, 3]

        # Pixels with alpha > WALL_THRESHOLD are "painted" and act as walls.
        # At 100 % hardness every painted pixel is fully opaque (alpha = 255),
        # so threshold = 0 works; we use 16 to tolerate 1-px AA edges.
        WALL = 16

        if alpha[py, px] > WALL:
            return False  # Clicked on existing paint — nothing to fill

        # Scanline BFS: each stack entry is a single (row, col) seed.
        # For each seed we scan the whole run left/right, mark it filled,
        # then push one seed per unfilled run above/below.
        filled = np.zeros((h, w), dtype=np.bool_)
        stack = [(py, px)]
        while stack:
            cy, cx = stack.pop()
            if filled[cy, cx] or alpha[cy, cx] > WALL:
                continue
            # Extend left
            x1 = cx
            while x1 > 0 and not filled[cy, x1 - 1] and alpha[cy, x1 - 1] <= WALL:
                x1 -= 1
            # Extend right
            x2 = cx
            while x2 < w - 1 and not filled[cy, x2 + 1] and alpha[cy, x2 + 1] <= WALL:
                x2 += 1
            # Mark entire scanline
            filled[cy, x1 : x2 + 1] = True
            # Seed neighbours above and below (one seed per contiguous empty run)
            for row in (cy - 1, cy + 1):
                if not (0 <= row < h):
                    continue
                nx = x1
                while nx <= x2:
                    if not filled[row, nx] and alpha[row, nx] <= WALL:
                        stack.append((row, nx))
                        # Skip to end of this run so we don't push duplicates
                        while nx <= x2 and not filled[row, nx] and alpha[row, nx] <= WALL:
                            nx += 1
                    else:
                        nx += 1

        if not filled.any():
            return False

        # Expand the filled region outward so it overlaps the painted wall
        # pixels and leaves no hairline gap at the boundary.
        if self.fill_expand_px > 0:
            for _ in range(self.fill_expand_px):
                prev = filled.copy()
                filled[1:, :]  |= prev[:-1, :]
                filled[:-1, :] |= prev[1:, :]
                filled[:, 1:]  |= prev[:, :-1]
                filled[:, :-1] |= prev[:, 1:]

        # ARGB32_Premultiplied: bytes are [B, G, R, A] = [255, 255, 255, 255] for white
        arr[filled] = [255, 255, 255, 255]
        channel.mask_image = QImage(
            arr.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied
        ).copy()
        return True

    # -------------------------------------------------------------------------
    # Mouse events
    # -------------------------------------------------------------------------

    def _notify_params_changed(self) -> None:
        if self._params_changed_cb is not None:
            self._params_changed_cb()

    def mouse_press(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord,
    ) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Modifier + drag to adjust brush parameters interactively.
        # Ctrl = brush size, Alt = hardness, Shift = flow (or straight-line on click).
        mods = event.modifiers()
        self._shift_held = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if mods & Qt.KeyboardModifier.ControlModifier:
            self._drag_param = "size"
            self._drag_start_y = event.position().y()
            self._drag_start_value = self.brush_size
            return
        if mods & Qt.KeyboardModifier.AltModifier:
            self._drag_param = "hardness"
            self._drag_start_y = event.position().y()
            self._drag_start_value = self.hardness
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            # Treat as flow-drag initially; if released without significant drag
            # and a previous stroke end exists, draw a straight line instead.
            self._drag_param = "flow"
            self._drag_start_y = event.position().y()
            self._drag_start_value = self.flow
            self._shift_was_drag = False
            return

        layer = self._get_active_layer()
        if layer is None:
            return

        # Require an active channel before painting.
        channel = self._get_active_channel(layer)
        if channel is None:
            return  # No channel selected — user must create one first

        # Require a color or texture to be selected before painting.
        if self.mode in ("draw", "fill") and not self._can_paint:
            return

        channel.ensure_mask(self._get_map_bounds())

        # --- Fill mode: flood-fill from click position, no drag ---
        if self.mode == "fill":
            wx, wy = world_pos.x(), world_pos.y()
            snapshot = channel.get_mask_snapshot()
            changed = self._flood_fill_at(channel, wx, wy)
            if changed:
                layer.mark_channel_dirty(channel.id)
                after = channel.get_mask_snapshot()
                cmd = DrawMaskCommand(layer, channel.id, snapshot, after)
                self._command_stack.execute(cmd)
                layer.build_full_cache(self._last_viewport_rect)
            return

        # Randomize brush size for this stroke
        if self.random_brush_size:
            lo = min(self.random_brush_min, self.random_brush_max)
            hi = max(self.random_brush_min, self.random_brush_max)
            self.brush_size = _random.uniform(lo, hi)
            self._notify_params_changed()

        # Save mask snapshot for undo
        self._mask_snapshot = channel.get_mask_snapshot()
        self._is_drawing = True
        self._last_paint_world = world_pos

        wx, wy = world_pos.x(), world_pos.y()
        self._paint_stamp(channel, wx, wy)
        layer.mark_channel_dirty(channel.id)

    def mouse_move(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord,
    ) -> bool:
        self._last_mouse_world = world_pos

        self._shift_held = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        # Handle drag-to-adjust brush parameters.
        if self._drag_param is not None:
            # Dragging up = positive delta = larger/harder/more flow.
            delta = self._drag_start_y - event.position().y()
            if self._drag_param == "size":
                self.brush_size = max(0.1, self._drag_start_value + delta * 0.5)
                self._notify_params_changed()
            elif self._drag_param == "hardness":
                self.hardness = max(0.0, min(1.0, self._drag_start_value + delta * 0.005))
                self._notify_params_changed()
            elif self._drag_param == "flow":
                # Only activate flow-drag once the pointer moved past the threshold.
                # Below that we keep the option open for a straight-line click.
                if abs(delta) >= _SHIFT_DRAG_THRESHOLD:
                    self._shift_was_drag = True
                if self._shift_was_drag:
                    self.flow = max(0.01, min(1.0, self._drag_start_value + delta * 0.005))
                    self._notify_params_changed()
            return True  # brush cursor overlay follows mouse

        if not self._is_drawing:
            return True  # brush cursor overlay follows mouse

        layer = self._get_active_layer()
        if layer is None:
            return True

        channel = self._get_active_channel(layer)
        if channel is None or channel.mask_image is None:
            return True

        wx, wy = world_pos.x(), world_pos.y()

        if self._last_paint_world is None:
            return True

        lx = self._last_paint_world.x()
        ly = self._last_paint_world.y()
        dist = math.hypot(wx - lx, wy - ly)
        min_dist = max(_MIN_SPACING, self.brush_size * _SPACING_FRACTION)
        if dist < min_dist:
            return True

        # Interpolate stamps along the path so fast mouse movements
        # produce smooth lines instead of isolated dots.
        num_stamps = max(1, int(dist / min_dist))
        dirty_rect = self._paint_stamps_along_path(
            channel, self._last_paint_world, world_pos, num_stamps
        )
        self._last_paint_world = world_pos
        # Incremental update: only re-render the brush-stamp-sized dirty region
        # instead of rebuilding the entire viewport composite from scratch.
        layer.update_composite_dirty_rect(channel.id, dirty_rect)
        return True

    def mouse_release(
        self, event: QMouseEvent, world_pos: QPointF, hex_coord,
    ) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._shift_held = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        # End drag-to-adjust if active.
        if self._drag_param is not None:
            is_shift_click = (self._drag_param == "flow" and not self._shift_was_drag)
            self._drag_param = None
            self._shift_was_drag = False
            if is_shift_click:
                self._draw_shift_line(world_pos)
            return

        if not self._is_drawing:
            return

        self._is_drawing = False
        layer = self._get_active_layer()
        if layer is None:
            self._mask_snapshot = None
            return

        channel = self._get_active_channel(layer)
        if channel is None:
            self._mask_snapshot = None
            return

        after = channel.get_mask_snapshot()
        cmd = DrawMaskCommand(layer, channel.id, self._mask_snapshot, after)
        self._command_stack.execute(cmd)
        self._mask_snapshot = None
        # Remember the endpoint for the next Shift+click straight line.
        self._last_stroke_end = self._last_paint_world
        # Build viewport-scoped QPixmap cache for fast pan/zoom until next stroke.
        layer.build_full_cache(self._last_viewport_rect)

    # -------------------------------------------------------------------------
    # Keyboard
    # -------------------------------------------------------------------------

    def key_press(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_E:
            self.mode = "erase" if self.mode == "draw" else "draw"

    # -------------------------------------------------------------------------
    # Overlay
    # -------------------------------------------------------------------------

    def paint_overlay(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout,
        hover_hex,
    ) -> None:
        # Cache layout and viewport for mask initialization / build_full_cache.
        self._layout = layout
        self._last_viewport_rect = viewport_rect

        xf = painter.worldTransform()
        inv_scale = 1.0 / xf.m11() if xf.m11() != 0 else 1.0

        # Brush cursor at last mouse position
        # (only in draw/erase mode — fill uses the default cross cursor)
        if (self._last_mouse_world is not None
                and self.mode in ("draw", "erase")):
            mx, my = self._last_mouse_world.x(), self._last_mouse_world.y()
            radius = self.brush_size / 2.0

            if self.mode == "erase":
                inner_color = QColor(255, 80, 80, 230)
            else:
                inner_color = QColor(255, 255, 255, 230)

            painter.setBrush(Qt.BrushStyle.NoBrush)

            pen_outer = QPen(QColor(0, 0, 0, 160), 3.0 * inv_scale)
            pen_outer.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen_outer)
            painter.drawEllipse(QPointF(mx, my), radius, radius)

            pen_inner = QPen(inner_color, 1.5 * inv_scale)
            pen_inner.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen_inner)
            painter.drawEllipse(QPointF(mx, my), radius, radius)

        # Shift+click preview: dashed line from last stroke end to cursor.
        if (
            self._shift_held
            and self._last_stroke_end is not None
            and self._last_mouse_world is not None
            and not self._is_drawing
            and self._drag_param is None
        ):
            sx, sy = self._last_stroke_end.x(), self._last_stroke_end.y()
            mx2, my2 = self._last_mouse_world.x(), self._last_mouse_world.y()

            # Outer shadow line for readability.
            pen_shadow = QPen(QColor(0, 0, 0, 160), 3.0 * inv_scale)
            pen_shadow.setStyle(Qt.PenStyle.DashLine)
            pen_shadow.setCosmetic(True)
            painter.setPen(pen_shadow)
            painter.drawLine(QPointF(sx, sy), QPointF(mx2, my2))

            # White dashed line on top.
            pen_line = QPen(QColor(255, 255, 255, 220), 1.5 * inv_scale)
            pen_line.setStyle(Qt.PenStyle.DashLine)
            pen_line.setCosmetic(True)
            painter.setPen(pen_line)
            painter.drawLine(QPointF(sx, sy), QPointF(mx2, my2))

            # Small dot at the start point.
            r = 3.5 * inv_scale
            painter.setBrush(QColor(255, 255, 255, 220))
            pen_dot = QPen(QColor(0, 0, 0, 160), 1.5 * inv_scale)
            painter.setPen(pen_dot)
            painter.drawEllipse(QPointF(sx, sy), r, r)
