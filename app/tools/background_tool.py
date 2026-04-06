"""Background tool - load, position, and edit background images."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QImage, QMouseEvent, QPainter, QPen, QPolygonF,
)
from PySide6.QtWidgets import QMessageBox, QWidget

from app.commands.background_commands import EditImageCommand, PaintBrushCommand
from app.commands.command_stack import CommandStack
from app.hex.hex_math import Hex, Layout, hex_corners
from app.layers.background_layer import BackgroundImageLayer
from app.models.project import Project
from app.tools.base_tool import Tool

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Pixel helpers
# ---------------------------------------------------------------------------

def _qimage_to_numpy(img: QImage):
    """Convert ARGB32 QImage to numpy uint8 array (H, W, 4) with BGRA channels."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    raw = np.frombuffer(img.constBits().tobytes(), dtype=np.uint8)
    if bpl == w * 4:
        return raw.reshape(h, w, 4).copy()
    # Padded rows
    return raw.reshape(h, bpl)[:, :w * 4].reshape(h, w, 4).copy()


def _numpy_to_qimage(arr) -> QImage:
    """Convert BGRA numpy array (H, W, 4) back to ARGB32 QImage."""
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, w * 4, QImage.Format.Format_ARGB32)
    return img.copy()


def _apply_posterize_np(arr, levels: int) -> None:
    """Apply posterize in-place (numpy, BGRA channels)."""
    step = 255.0 / max(1, levels - 1)
    alpha_mask = arr[:, :, 3] > 0
    for c in range(3):
        ch = arr[:, :, c].astype(np.float32)
        ch = np.clip(np.round(ch / step) * step, 0, 255).astype(np.uint8)
        arr[:, :, c] = np.where(alpha_mask, ch, arr[:, :, c])


def _apply_posterize_slow(img: QImage, levels: int) -> QImage:
    """Posterize without numpy (slow fallback)."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32).copy()
    step = 255.0 / max(1, levels - 1)
    w, h = img.width(), img.height()
    for y in range(h):
        for x in range(w):
            c = QColor(img.pixel(x, y))
            if c.alpha() == 0:
                continue
            r = int(round(c.red() / step) * step)
            g = int(round(c.green() / step) * step)
            b = int(round(c.blue() / step) * step)
            img.setPixel(x, y, QColor(
                min(255, r), min(255, g), min(255, b), c.alpha()
            ).rgba())
    return img


def _build_selection_np(img: QImage, img_x: int, img_y: int):
    """Return bool mask (H, W) of pixels matching color at (img_x, img_y)."""
    arr = _qimage_to_numpy(img)
    target = arr[img_y, img_x, :3].copy()
    matches = np.all(arr[:, :, :3] == target, axis=2)
    matches = matches & (arr[:, :, 3] > 0)
    return matches


def _build_selection_slow(img: QImage, img_x: int, img_y: int) -> QImage:
    """Return selection mask QImage without numpy (slow fallback)."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    target = QColor(img.pixel(img_x, img_y)).rgb()
    w, h = img.width(), img.height()
    sel = QImage(w, h, QImage.Format.Format_ARGB32)
    sel.fill(Qt.GlobalColor.transparent)
    sel_color = QColor(0, 100, 255, 120).rgba()
    for y in range(h):
        for x in range(w):
            c = QColor(img.pixel(x, y))
            if c.alpha() > 0 and c.rgb() == target:
                sel.setPixel(x, y, sel_color)
    return sel


def _apply_outline_np(arr, width: int) -> None:
    """Add black outline expanding outward by `width` pixels (in-place, numpy)."""
    non_transparent = arr[:, :, 3] > 0
    expanded = non_transparent.copy()
    for _ in range(width):
        shifted = (
            np.roll(expanded, 1, axis=0)
            | np.roll(expanded, -1, axis=0)
            | np.roll(expanded, 1, axis=1)
            | np.roll(expanded, -1, axis=1)
            | expanded
        )
        # Prevent wrap-around artifacts at image borders
        shifted[0, :] = expanded[0, :]
        shifted[-1, :] = expanded[-1, :]
        shifted[:, 0] = expanded[:, 0]
        shifted[:, -1] = expanded[:, -1]
        expanded = shifted
    outline = expanded & ~non_transparent
    arr[outline] = [0, 0, 0, 255]


def _apply_outline_slow(img: QImage, width: int) -> QImage:
    """Add black outline without numpy (slow fallback)."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32).copy()
    w, h = img.width(), img.height()
    # Collect border pixels (non-transparent with at least one transparent neighbor)
    outline: list[tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if QColor(img.pixel(x, y)).alpha() == 0:
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if QColor(img.pixel(nx, ny)).alpha() == 0:
                        outline.append((x, y))
                        break
    black = QColor(0, 0, 0, 255).rgba()
    for (x, y) in outline:
        img.setPixel(x, y, black)
    return img


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class BackgroundTool(Tool):
    def __init__(self, project: Project, command_stack: CommandStack):
        self._project = project
        self._command_stack = command_stack

        # Move state
        self._is_dragging = False
        self._drag_start_world: QPointF | None = None
        self._drag_start_offset_x: float = 0.0
        self._drag_start_offset_y: float = 0.0
        self.locked = False

        # Edit state
        self.edit_mode: str = "move"       # "move" | "paint" | "color_select"
        self.paint_color: QColor = QColor(Qt.GlobalColor.white)
        self.paint_brush_size: int = 15    # radius in image pixels

        # Selection (pixel-space mask, same size as image)
        # Stored as numpy bool array (H, W) when numpy is available,
        # or as QImage otherwise.
        self._selection_np = None          # numpy bool array | None
        self._selection_qimg: QImage | None = None   # fallback or overlay cache
        self._selection_overlay_dirty = True

        # Paint command in progress (open during a drag stroke)
        self._painting = False
        self._paint_command: PaintBrushCommand | None = None
        self._last_paint_pos: QPointF | None = None

        # Callbacks for UI sync
        self._on_offset_changed: callable | None = None
        self._on_selection_changed: callable | None = None

    def reset_to_defaults(self) -> None:
        """Reset all user-facing settings to constructor defaults."""
        self.locked = False

    # ------------------------------------------------------------------
    # Tool interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Background"

    @property
    def cursor(self) -> Qt.CursorShape:
        if self.edit_mode == "move":
            if self.locked:
                return Qt.CursorShape.ArrowCursor
            return Qt.CursorShape.OpenHandCursor
        return Qt.CursorShape.CrossCursor

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mouse_press(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.edit_mode == "move":
            if self.locked:
                return
            bg_layer = self.find_background_layer()
            if bg_layer and bg_layer.has_image():
                self._is_dragging = True
                self._drag_start_world = world_pos
                self._drag_start_offset_x = bg_layer.offset_x
                self._drag_start_offset_y = bg_layer.offset_y

        elif self.edit_mode == "paint":
            bg_layer = self.find_background_layer()
            if bg_layer and bg_layer.has_image():
                cmd = PaintBrushCommand(bg_layer)
                cmd.begin()
                self._paint_command = cmd
                self._painting = True
                self._last_paint_pos = world_pos
                self._paint_at(bg_layer, world_pos)

        elif self.edit_mode == "color_select":
            self._do_color_select(world_pos)

    def mouse_move(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        if self.edit_mode == "move":
            if not self._is_dragging or not self._drag_start_world:
                return
            bg_layer = self.find_background_layer()
            if not bg_layer:
                return
            dx = world_pos.x() - self._drag_start_world.x()
            dy = world_pos.y() - self._drag_start_world.y()
            bg_layer.offset_x = self._drag_start_offset_x + dx
            bg_layer.offset_y = self._drag_start_offset_y + dy
            bg_layer.mark_dirty()
            self._project.layer_stack.layers_changed.emit()
            if self._on_offset_changed:
                self._on_offset_changed()

        elif self.edit_mode == "paint" and self._painting:
            bg_layer = self.find_background_layer()
            if not bg_layer or not bg_layer.has_image():
                return
            # Spacing: paint every (brush_size * 0.3) world units
            if self._last_paint_pos is not None:
                dx = world_pos.x() - self._last_paint_pos.x()
                dy = world_pos.y() - self._last_paint_pos.y()
                spacing = max(1.0, self.paint_brush_size * bg_layer.scale * 0.3)
                if dx * dx + dy * dy < spacing * spacing:
                    return
            self._last_paint_pos = world_pos
            self._paint_at(bg_layer, world_pos)

    def mouse_release(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.edit_mode == "move":
                self._is_dragging = False
                self._drag_start_world = None
            elif self.edit_mode == "paint" and self._painting:
                bg_layer = self.find_background_layer()
                if self._paint_command and bg_layer:
                    self._paint_command.commit()
                    self._command_stack.execute(self._paint_command)
                self._paint_command = None
                self._painting = False
                self._last_paint_pos = None

    # ------------------------------------------------------------------
    # Overlay
    # ------------------------------------------------------------------

    def paint_overlay(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        hover_hex: Hex | None,
    ) -> None:
        # In move mode: show hex hover highlight
        if self.edit_mode == "move" and hover_hex is not None:
            corners = hex_corners(layout, hover_hex)
            polygon = QPolygonF([QPointF(x, y) for x, y in corners])
            painter.setBrush(QColor(255, 255, 255, 30))
            pen = QPen(QColor(255, 255, 255, 120), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPolygon(polygon)

        # Selection overlay
        bg_layer = self.find_background_layer()
        if bg_layer and bg_layer.has_image() and self._has_selection():
            overlay = self._get_selection_overlay()
            if overlay and not overlay.isNull():
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.translate(bg_layer.offset_x, bg_layer.offset_y)
                painter.scale(bg_layer.scale, bg_layer.scale)
                painter.drawImage(QPointF(0, 0), overlay)
                painter.restore()

    # ------------------------------------------------------------------
    # Paint brush helper
    # ------------------------------------------------------------------

    def _paint_at(self, bg_layer: BackgroundImageLayer, world_pos: QPointF) -> None:
        """Paint a filled circle onto the layer's QImage at the given world position."""
        img_x, img_y = bg_layer.world_to_pixel(world_pos.x(), world_pos.y())
        img = bg_layer.get_qimage()
        if img is None:
            return

        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.paint_color)
        r = self.paint_brush_size
        p.drawEllipse(QPointF(img_x, img_y), r, r)
        p.end()

        bg_layer._pixmap = None  # invalidate render cache
        self._project.layer_stack.layers_changed.emit()

    # ------------------------------------------------------------------
    # Color select
    # ------------------------------------------------------------------

    def _do_color_select(self, world_pos: QPointF) -> None:
        bg_layer = self.find_background_layer()
        if not bg_layer or not bg_layer.has_image():
            return
        img_x, img_y = bg_layer.world_to_pixel(world_pos.x(), world_pos.y())
        img_x, img_y = int(img_x), int(img_y)  # numpy requires integer indices
        if not bg_layer.pixel_in_bounds(img_x, img_y):
            return
        img = bg_layer.get_qimage()

        if _HAS_NUMPY:
            self._selection_np = _build_selection_np(img, img_x, img_y)
            self._selection_qimg = None
        else:
            self._selection_qimg = _build_selection_slow(img, img_x, img_y)
            self._selection_np = None

        self._selection_overlay_dirty = True
        self._project.layer_stack.layers_changed.emit()

        if self._on_selection_changed:
            self._on_selection_changed()

    # ------------------------------------------------------------------
    # Selection operations
    # ------------------------------------------------------------------

    def _has_selection(self) -> bool:
        if _HAS_NUMPY:
            return self._selection_np is not None
        return self._selection_qimg is not None

    def _selection_count(self) -> int:
        if _HAS_NUMPY and self._selection_np is not None:
            return int(self._selection_np.sum())
        if self._selection_qimg is not None:
            return 1  # non-zero means selection exists
        return 0

    def invert_selection(self) -> None:
        bg_layer = self.find_background_layer()
        if not bg_layer or not bg_layer.has_image():
            return
        img = bg_layer.get_qimage()
        h, w = img.height(), img.width()

        if _HAS_NUMPY:
            if self._selection_np is None:
                # No selection → select all non-transparent
                arr = _qimage_to_numpy(img)
                self._selection_np = arr[:, :, 3] > 0
            else:
                arr = _qimage_to_numpy(img)
                non_transparent = arr[:, :, 3] > 0
                self._selection_np = (~self._selection_np) & non_transparent
        else:
            if self._selection_qimg is None:
                # No selection → select all non-transparent pixels
                self._selection_qimg = QImage(w, h, QImage.Format.Format_ARGB32)
                sel_color = QColor(0, 100, 255, 120).rgba()
                for y in range(h):
                    for x in range(w):
                        c = QColor(img.pixel(x, y))
                        if c.alpha() > 0:
                            self._selection_qimg.setPixel(x, y, sel_color)
                        else:
                            self._selection_qimg.setPixel(x, y, 0)
            else:
                new_sel = QImage(w, h, QImage.Format.Format_ARGB32)
                new_sel.fill(Qt.GlobalColor.transparent)
                sel_color = QColor(0, 100, 255, 120).rgba()
                for y in range(h):
                    for x in range(w):
                        was_selected = QColor(self._selection_qimg.pixel(x, y)).alpha() > 0
                        orig_alpha = QColor(img.pixel(x, y)).alpha() > 0
                        if orig_alpha and not was_selected:
                            new_sel.setPixel(x, y, sel_color)
                self._selection_qimg = new_sel

        self._selection_overlay_dirty = True
        self._project.layer_stack.layers_changed.emit()
        if self._on_selection_changed:
            self._on_selection_changed()

    def delete_selection(self) -> None:
        """Delete selected pixels (set to transparent). Creates an undo command."""
        if not self._has_selection():
            return
        bg_layer = self.find_background_layer()
        if not bg_layer or not bg_layer.has_image():
            return
        img = bg_layer.get_qimage()

        if _HAS_NUMPY and self._selection_np is not None:
            arr = _qimage_to_numpy(img)
            arr[self._selection_np, :] = 0  # set to fully transparent black
            new_img = _numpy_to_qimage(arr)
        else:
            new_img = img.convertToFormat(QImage.Format.Format_ARGB32).copy()
            h, w = new_img.height(), new_img.width()
            for y in range(h):
                for x in range(w):
                    if QColor(self._selection_qimg.pixel(x, y)).alpha() > 0:
                        new_img.setPixel(x, y, 0)

        cmd = EditImageCommand(bg_layer, new_img, "Delete Selection")
        self._command_stack.execute(cmd)
        self.clear_selection()
        self._project.layer_stack.layers_changed.emit()

    def clear_selection(self) -> None:
        self._selection_np = None
        self._selection_qimg = None
        self._selection_overlay_dirty = True
        self._project.layer_stack.layers_changed.emit()
        if self._on_selection_changed:
            self._on_selection_changed()

    # ------------------------------------------------------------------
    # Posterize
    # ------------------------------------------------------------------

    def apply_posterize(self, levels: int) -> None:
        bg_layer = self.find_background_layer()
        if not bg_layer or not bg_layer.has_image():
            return
        img = bg_layer.get_qimage()

        if _HAS_NUMPY:
            arr = _qimage_to_numpy(img)
            _apply_posterize_np(arr, levels)
            new_img = _numpy_to_qimage(arr)
        else:
            new_img = _apply_posterize_slow(img, levels)

        cmd = EditImageCommand(bg_layer, new_img, f"Posterize ({levels} levels)")
        self._command_stack.execute(cmd)
        # Clear selection since pixel colors changed
        self.clear_selection()
        self._project.layer_stack.layers_changed.emit()

    # ------------------------------------------------------------------
    # Outline
    # ------------------------------------------------------------------

    def apply_outline(self, width: int) -> None:
        bg_layer = self.find_background_layer()
        if not bg_layer or not bg_layer.has_image():
            return
        img = bg_layer.get_qimage()

        if _HAS_NUMPY:
            arr = _qimage_to_numpy(img)
            _apply_outline_np(arr, width)
            new_img = _numpy_to_qimage(arr)
        else:
            new_img = _apply_outline_slow(img, width)

        cmd = EditImageCommand(bg_layer, new_img, f"Add Outline ({width}px)")
        self._command_stack.execute(cmd)
        self._project.layer_stack.layers_changed.emit()

    # ------------------------------------------------------------------
    # Selection overlay cache
    # ------------------------------------------------------------------

    def _get_selection_overlay(self) -> QImage | None:
        """Return a QImage with the selection visualized as a blue overlay."""
        bg_layer = self.find_background_layer()
        if not bg_layer or not bg_layer.has_image():
            return None

        if not self._selection_overlay_dirty:
            return self._selection_qimg

        img = bg_layer.get_qimage()
        w, h = img.width(), img.height()
        sel_color = QColor(0, 100, 255, 120).rgba()

        if _HAS_NUMPY and self._selection_np is not None:
            overlay = QImage(w, h, QImage.Format.Format_ARGB32)
            overlay.fill(Qt.GlobalColor.transparent)
            # Build using numpy for speed
            # QImage Format_ARGB32 on little-endian = BGRA in memory
            # QColor(R=0, G=100, B=255, A=120) → BGRA = [255, 100, 0, 120]
            sel_arr = np.zeros((h, w, 4), dtype=np.uint8)
            sel_arr[self._selection_np] = [255, 100, 0, 120]  # BGRA: blue overlay
            img_tmp = QImage(sel_arr.data, w, h, w * 4, QImage.Format.Format_ARGB32)
            self._selection_qimg = img_tmp.copy()
        elif self._selection_qimg is None:
            return None

        self._selection_overlay_dirty = False
        return self._selection_qimg

    # ------------------------------------------------------------------
    # Edit mode
    # ------------------------------------------------------------------

    def set_edit_mode(self, mode: str) -> None:
        if mode not in ("move", "paint", "color_select"):
            return
        self.edit_mode = mode
        self._is_dragging = False

    # ------------------------------------------------------------------
    # Image loading
    # ------------------------------------------------------------------

    def load_image(self, path: str) -> bool:
        """Load a background image into the active background layer."""
        bg_layer = self.find_background_layer()

        if bg_layer is None:
            bg_layer = BackgroundImageLayer("Background")
            active_idx = self._project.layer_stack.active_index
            insert_idx = active_idx + 1 if active_idx >= 0 else 0
            self._project.layer_stack.add_layer(bg_layer, insert_idx)

        if bg_layer.load_image(path):
            self.clear_selection()
            self._project.layer_stack.layers_changed.emit()
            return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def find_background_layer(self) -> BackgroundImageLayer | None:
        """Return the active layer if it's a BackgroundImageLayer, else first match."""
        active = self._project.layer_stack.active_layer
        if isinstance(active, BackgroundImageLayer):
            return active
        for layer in self._project.layer_stack:
            if isinstance(layer, BackgroundImageLayer):
                return layer
        return None

    def _require_numpy_dialog(self, parent: QWidget | None = None) -> None:
        """Show a dialog if numpy is not installed."""
        QMessageBox.warning(
            parent,
            "numpy required",
            "This operation requires numpy.\n\nInstall it with:\n  pip install numpy",
        )
