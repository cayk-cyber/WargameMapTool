"""Standalone image editor dialog for background layers.

Working copy workflow: edits are local until "Apply" commits them to the layer.
Navigation: scroll to zoom, right-click drag to pan.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap,
    QRadialGradient, QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from app.panels.tool_options.helpers import update_color_btn

try:
    import numpy as np
    _HAS_NP = True
except ImportError:
    _HAS_NP = False


# ---------------------------------------------------------------------------
# Numpy helpers (local, self-contained)
# ---------------------------------------------------------------------------

def _to_numpy(img: QImage):
    """ARGB32 QImage → (H, W, 4) uint8 numpy array (BGRA channels)."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=h * bpl)
    arr = arr.reshape(h, bpl)[:, : w * 4].reshape(h, w, 4)
    return arr.copy()


def _from_numpy(arr) -> QImage:
    """(H, W, 4) uint8 numpy array (BGRA) → ARGB32 QImage."""
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    data = arr.tobytes()
    img = QImage(data, w, h, w * 4, QImage.Format.Format_ARGB32)
    return img.copy()


def _posterize(img: QImage, levels: int) -> QImage:
    if _HAS_NP:
        arr = _to_numpy(img)
        step = 255.0 / max(1, levels - 1)
        lut = np.array(
            [min(255, int(round(v / step) * step)) for v in range(256)],
            dtype=np.uint8,
        )
        alpha_mask = arr[:, :, 3] > 0
        for c in range(3):
            ch = arr[:, :, c]
            arr[:, :, c] = np.where(alpha_mask, lut[ch], ch)
        return _from_numpy(arr)
    else:
        # Slow fallback
        img = img.convertToFormat(QImage.Format.Format_ARGB32).copy()
        step = 255.0 / max(1, levels - 1)
        for y in range(img.height()):
            for x in range(img.width()):
                c = QColor(img.pixel(x, y))
                if c.alpha() == 0:
                    continue
                img.setPixel(x, y, QColor(
                    min(255, int(round(c.red()   / step) * step)),
                    min(255, int(round(c.green() / step) * step)),
                    min(255, int(round(c.blue()  / step) * step)),
                    c.alpha(),
                ).rgba())
        return img


def _outline(img: QImage, width: int) -> QImage:
    if _HAS_NP:
        arr = _to_numpy(img)
        non_transp = arr[:, :, 3] > 0
        expanded = non_transp.copy()
        for _ in range(width):
            shifted = (
                np.roll(expanded, 1, axis=0) | np.roll(expanded, -1, axis=0)
                | np.roll(expanded, 1, axis=1) | np.roll(expanded, -1, axis=1)
                | expanded
            )
            shifted[0, :] = expanded[0, :]
            shifted[-1, :] = expanded[-1, :]
            shifted[:, 0] = expanded[:, 0]
            shifted[:, -1] = expanded[:, -1]
            expanded = shifted
        outline = expanded & ~non_transp
        arr[outline] = [0, 0, 0, 255]
        return _from_numpy(arr)
    else:
        img = img.convertToFormat(QImage.Format.Format_ARGB32).copy()
        w, h = img.width(), img.height()
        pts = []
        for y in range(h):
            for x in range(w):
                if QColor(img.pixel(x, y)).alpha() == 0:
                    continue
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and QColor(img.pixel(nx, ny)).alpha() == 0:
                        pts.append((x, y))
                        break
        black = QColor(0, 0, 0, 255).rgba()
        for x, y in pts:
            img.setPixel(x, y, black)
        return img


def _build_selection(img: QImage, ix: int, iy: int):
    """Return numpy bool (H, W) mask of pixels matching color at (ix, iy)."""
    if not _HAS_NP:
        return None
    arr = _to_numpy(img)
    target = arr[iy, ix, :3].copy()
    matches = np.all(arr[:, :, :3] == target, axis=2)
    return matches & (arr[:, :, 3] > 0)


def _sel_overlay(sel, color: QColor) -> QImage | None:
    """Build a selection overlay QImage from a numpy bool mask and a highlight color."""
    if not _HAS_NP or sel is None:
        return None
    h, w = sel.shape
    ov = np.zeros((h, w, 4), dtype=np.uint8)
    # QImage.Format_ARGB32 stores pixels as BGRA in memory on little-endian systems
    ov[sel] = [color.blue(), color.green(), color.red(), color.alpha()]
    img = QImage(ov.data, w, h, w * 4, QImage.Format.Format_ARGB32)
    return img.copy()


# ---------------------------------------------------------------------------
# Image editing canvas
# ---------------------------------------------------------------------------

class ImageEditCanvas(QWidget):
    """Zoomable/pannable canvas.  Right-click drag = pan.  Scroll = zoom."""

    selection_changed = Signal()
    brush_size_changed = Signal(int)

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self._img: QImage = image.copy().convertToFormat(QImage.Format.Format_ARGB32)
        self._zoom: float = 1.0
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0

        # Edit mode: "paint" | "erase" | "color_select" | "" (navigate)
        self._mode: str = ""
        self._paint_color: QColor = QColor(Qt.GlobalColor.white)
        self._paint_radius: int = 15
        self._hardness: float = 1.0   # 0.0–1.0 (0=max soft, 1=hard edge)
        self._flow: float = 1.0       # 0.01–1.0 (opacity per stamp)

        # Selection
        self._sel = None                        # numpy bool (H, W) or None
        self._sel_color: QColor = QColor(255, 0, 0, 120)   # highlight color (semi-transparent blue)
        self._sel_ov_cache: QImage | None = None
        self._sel_dirty: bool = True

        # Panning state (right-click or navigate mode left-click)
        self._panning: bool = False
        self._pan_start_mouse: QPointF | None = None
        self._pan_start_off: tuple[float, float] = (0.0, 0.0)

        # Painting state
        self._painting: bool = False
        self._last_paint: tuple[float, float] | None = None

        # Brush-size drag state (Ctrl+Left drag)
        self._size_drag_active: bool = False
        self._size_drag_start_y: float = 0.0
        self._size_drag_start_r: int = 15

        # Undo stack
        self._undo: list[QImage] = []

        # Checkerboard pixmap cache
        self._checker: QPixmap | None = None

        # Brush cursor overlay
        self._cursor_pos: QPointF | None = None

        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit_to_window(self) -> None:
        w, h = max(self.width(), 1), max(self.height(), 1)
        iw, ih = self._img.width(), self._img.height()
        if iw == 0 or ih == 0:
            return
        z = min(w / iw, h / ih) * 0.92
        self._zoom = max(0.01, min(z, 32.0))
        self._pan_x = (w - iw * self._zoom) / 2.0
        self._pan_y = (h - ih * self._zoom) / 2.0
        self.update()

    def get_image(self) -> QImage:
        return self._img

    def zoom_level(self) -> float:
        return self._zoom

    def set_mode(self, mode: str) -> None:
        """Set edit mode: 'paint', 'erase', 'color_select', or '' (navigate)."""
        self._mode = mode
        if mode in ("paint", "erase"):
            self.setCursor(Qt.CursorShape.BlankCursor)
        elif mode == "color_select":
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def set_paint_color(self, color: QColor) -> None:
        self._paint_color = color

    def set_paint_radius(self, r: int) -> None:
        self._paint_radius = r

    def set_hardness(self, h: float) -> None:
        self._hardness = max(0.0, min(1.0, h))

    def set_flow(self, f: float) -> None:
        self._flow = max(0.01, min(1.0, f))

    def set_sel_color(self, color: QColor) -> None:
        """Change the selection highlight color and redraw."""
        self._sel_color = color
        self._sel_dirty = True
        self.update()

    def has_selection(self) -> bool:
        return self._sel is not None

    def can_undo(self) -> bool:
        return bool(self._undo)

    # ------------------------------------------------------------------
    # Edit operations
    # ------------------------------------------------------------------

    def apply_posterize(self, levels: int) -> None:
        self._push_undo()
        self._img = _posterize(self._img, levels)
        self._clear_sel()
        self.update()

    def invert_selection(self) -> None:
        if not _HAS_NP:
            return
        arr = _to_numpy(self._img)
        non_transp = arr[:, :, 3] > 0
        self._sel = (~self._sel & non_transp) if self._sel is not None else non_transp
        self._sel_dirty = True
        self.update()
        self.selection_changed.emit()

    def delete_selection(self) -> None:
        if self._sel is None or not _HAS_NP:
            return
        self._push_undo()
        arr = _to_numpy(self._img)
        arr[self._sel, :] = 0
        self._img = _from_numpy(arr)
        self._clear_sel()
        self.update()

    def fill_selection(self, color: QColor) -> None:
        """Fill selected pixels with *color*. Keeps selection alive."""
        if self._sel is None or not _HAS_NP:
            return
        self._push_undo()
        arr = _to_numpy(self._img)
        arr[self._sel] = [color.blue(), color.green(), color.red(), color.alpha()]
        self._img = _from_numpy(arr)
        self.update()

    def clear_selection(self) -> None:
        self._clear_sel()
        self.update()

    def apply_outline(self, width: int) -> None:
        self._push_undo()
        self._img = _outline(self._img, width)
        self.update()

    def undo(self) -> None:
        if self._undo:
            self._img = self._undo.pop()
            self._sel_dirty = True
            self.update()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _push_undo(self) -> None:
        self._undo.append(self._img.copy())
        if len(self._undo) > 10:
            self._undo.pop(0)

    def _clear_sel(self) -> None:
        self._sel = None
        self._sel_ov_cache = None
        self._sel_dirty = True
        self.selection_changed.emit()

    def _canvas_to_img(self, cx: float, cy: float) -> tuple[float, float]:
        return ((cx - self._pan_x) / self._zoom,
                (cy - self._pan_y) / self._zoom)

    def _zoom_at(self, factor: float, cx: float, cy: float) -> None:
        new_z = max(0.05, min(self._zoom * factor, 64.0))
        self._pan_x = cx - (cx - self._pan_x) * new_z / self._zoom
        self._pan_y = cy - (cy - self._pan_y) * new_z / self._zoom
        self._zoom = new_z
        self.update()

    def _get_checker(self) -> QPixmap:
        if self._checker is None:
            self._checker = QPixmap(16, 16)
            p = QPainter(self._checker)
            p.fillRect(0, 0, 16, 16, QColor(200, 200, 200))
            p.fillRect(0, 0, 8, 8, QColor(155, 155, 155))
            p.fillRect(8, 8, 8, 8, QColor(155, 155, 155))
            p.end()
        return self._checker

    def _get_sel_overlay(self) -> QImage | None:
        if self._sel is None:
            return None
        if not self._sel_dirty and self._sel_ov_cache is not None:
            return self._sel_ov_cache
        self._sel_ov_cache = _sel_overlay(self._sel, self._sel_color)
        self._sel_dirty = False
        return self._sel_ov_cache

    def _make_brush_stamp(self, mode: str) -> QImage:
        """Build a brush stamp image (diameter = 2*r+2) with hardness and flow applied."""
        r = self._paint_radius
        d = r * 2 + 2
        stamp = QImage(d, d, QImage.Format.Format_ARGB32)
        stamp.fill(QColor(0, 0, 0, 0))
        cx = cy = r + 0.5

        base = QColor(0, 0, 0) if mode == "erase" else QColor(self._paint_color)
        alpha = int(round(self._flow * 255))

        p = QPainter(stamp)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.setPen(Qt.PenStyle.NoPen)

        if self._hardness >= 0.999:
            c = QColor(base)
            c.setAlpha(alpha)
            p.setBrush(c)
        else:
            c_full = QColor(base)
            c_full.setAlpha(alpha)
            c_zero = QColor(base)
            c_zero.setAlpha(0)
            grad = QRadialGradient(cx, cy, r)
            grad.setColorAt(0.0, c_full)
            if self._hardness > 0.0:
                grad.setColorAt(self._hardness, c_full)
            grad.setColorAt(1.0, c_zero)
            p.setBrush(QBrush(grad))

        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()
        return stamp

    def _paint_at(self, ix: float, iy: float) -> None:
        r = self._paint_radius
        stamp = self._make_brush_stamp(self._mode)
        # Top-left corner in image space where the stamp should be placed
        tx = int(round(ix)) - r - 1
        ty = int(round(iy)) - r - 1

        comp = (
            QPainter.CompositionMode.CompositionMode_DestinationOut
            if self._mode == "erase"
            else QPainter.CompositionMode.CompositionMode_SourceOver
        )

        if self._sel is None or not _HAS_NP:
            # No selection — paint directly
            p = QPainter(self._img)
            p.setCompositionMode(comp)
            p.drawImage(tx, ty, stamp)
            p.end()
            self.update()
            return

        # Selection-constrained paint/erase: only selected pixels are changed.
        x0 = max(0, tx)
        y0 = max(0, ty)
        x1 = min(self._img.width(),  tx + stamp.width())
        y1 = min(self._img.height(), ty + stamp.height())
        if x0 >= x1 or y0 >= y1:
            return

        # Snapshot pixels in bbox before painting
        before_sub = _to_numpy(self._img)[y0:y1, x0:x1].copy()

        # Apply stamp onto self._img
        p = QPainter(self._img)
        p.setCompositionMode(comp)
        p.drawImage(tx, ty, stamp)
        p.end()

        # Restore pixels outside selection within bbox
        after_arr = _to_numpy(self._img)
        sel_sub = self._sel[y0:y1, x0:x1]
        after_arr[y0:y1, x0:x1][~sel_sub] = before_sub[~sel_sub]

        # Write corrected sub-region back
        corrected = _from_numpy(after_arr[y0:y1, x0:x1])
        p2 = QPainter(self._img)
        p2.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p2.drawImage(x0, y0, corrected)
        p2.end()

        self.update()

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(60, 60, 60))

        iw = int(self._img.width() * self._zoom)
        ih = int(self._img.height() * self._zoom)
        img_rect = QRectF(self._pan_x, self._pan_y, iw, ih)

        # Checkerboard
        painter.save()
        painter.setClipRect(img_rect)
        painter.fillRect(img_rect, self._get_checker())
        painter.restore()

        # Image + selection overlay
        painter.save()
        painter.translate(self._pan_x, self._pan_y)
        painter.scale(self._zoom, self._zoom)
        if self._zoom < 1.0:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QPointF(0, 0), self._img)
        ov = self._get_sel_overlay()
        if ov:
            painter.drawImage(QPointF(0, 0), ov)
        painter.restore()

        # Brush size cursor (paint / erase mode)
        if self._mode in ("paint", "erase") and self._cursor_pos is not None:
            r = self._paint_radius * self._zoom
            cx, cy = self._cursor_pos.x(), self._cursor_pos.y()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Black outer ring
            painter.setPen(QColor(0, 0, 0, 200))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), r + 1, r + 1)
            # White inner ring
            from PySide6.QtGui import QPen
            pen = QPen(QColor(255, 255, 255, 220))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawEllipse(QPointF(cx, cy), r, r)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Ctrl+Left in paint/erase mode → brush size adjustment (no painting)
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and self._mode in ("paint", "erase")):
            self._size_drag_active = True
            self._size_drag_start_y = event.position().y()
            self._size_drag_start_r = self._paint_radius
            return

        # Right-click OR left-click in navigate mode → pan
        if event.button() == Qt.MouseButton.RightButton or (
            event.button() == Qt.MouseButton.LeftButton and self._mode == ""
        ):
            self._panning = True
            self._pan_start_mouse = event.position()
            self._pan_start_off = (self._pan_x, self._pan_y)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            ix, iy = self._canvas_to_img(event.position().x(), event.position().y())
            if self._mode in ("paint", "erase"):
                self._push_undo()
                self._painting = True
                self._last_paint = (ix, iy)
                self._paint_at(ix, iy)
            elif self._mode == "color_select":
                xi, yi = int(ix), int(iy)
                if 0 <= xi < self._img.width() and 0 <= yi < self._img.height():
                    self._sel = _build_selection(self._img, xi, yi)
                    self._sel_dirty = True
                    self.update()
                    self.selection_changed.emit()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._cursor_pos = event.position()

        # Ctrl+drag size adjustment
        if self._size_drag_active:
            dy = self._size_drag_start_y - event.position().y()   # up = larger
            new_r = max(1, min(200, self._size_drag_start_r + int(dy * 0.5)))
            if new_r != self._paint_radius:
                self._paint_radius = new_r
                self.brush_size_changed.emit(new_r)
            self.update()
            return

        self.update()

        if self._panning and self._pan_start_mouse is not None:
            dx = event.position().x() - self._pan_start_mouse.x()
            dy = event.position().y() - self._pan_start_mouse.y()
            self._pan_x = self._pan_start_off[0] + dx
            self._pan_y = self._pan_start_off[1] + dy
            return

        if self._painting and self._mode in ("paint", "erase"):
            ix, iy = self._canvas_to_img(event.position().x(), event.position().y())
            if self._last_paint is not None:
                lx, ly = self._last_paint
                spacing = max(1.0, self._paint_radius * 0.3)
                if (ix - lx) ** 2 + (iy - ly) ** 2 < spacing ** 2:
                    return
            self._last_paint = (ix, iy)
            self._paint_at(ix, iy)

    def leaveEvent(self, event) -> None:
        self._cursor_pos = None
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._size_drag_active:
            self._size_drag_active = False
            return

        if self._panning:
            self._panning = False
            self._pan_start_mouse = None
            # Restore cursor
            if self._mode in ("paint", "erase"):
                self.setCursor(Qt.CursorShape.BlankCursor)
            elif self._mode == "color_select":
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        if event.button() == Qt.MouseButton.LeftButton:
            self._painting = False
            self._last_paint = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        dy = event.angleDelta().y()
        if dy == 0:
            return
        factor = 1.15 if dy > 0 else 1.0 / 1.15
        self._zoom_at(factor, event.position().x(), event.position().y())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Z and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.undo()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class BackgroundEditDialog(QDialog):
    """Full image editor: zoom/pan canvas + editing tools. Apply on confirm."""

    apply_to_new_layer = Signal(QImage)

    def __init__(self, layer, command_stack, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Edit Background Image")
        self.setModal(False)
        self.resize(1100, 700)

        self._layer = layer
        self._command_stack = command_stack

        src = layer.get_qimage()
        working = src.copy().convertToFormat(QImage.Format.Format_ARGB32) if (src and not src.isNull()) else QImage()

        # Root: left panel | right (canvas + bottom bar)
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Left tool panel ─────────────────────────────────────────
        tool_panel = QWidget()
        tool_panel.setFixedWidth(230)
        tl = QVBoxLayout(tool_panel)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)

        # Navigation hint
        nav_lbl = QLabel("🖱 Right-drag: pan   Scroll: zoom")
        nav_lbl.setStyleSheet("color: #888; font-size: 10px;")
        nav_lbl.setWordWrap(True)
        tl.addWidget(nav_lbl)

        # Mode
        mode_group = QGroupBox("Active Tool")
        mode_gl = QVBoxLayout(mode_group)
        mode_gl.setContentsMargins(6, 4, 6, 4)

        self._paint_btn = QPushButton("Paint Brush")
        self._paint_btn.setCheckable(True)
        self._paint_btn.setToolTip("Left-click/drag to paint pixels")
        self._paint_btn.toggled.connect(lambda c: self._on_tool_toggled(self._paint_btn, c, "paint"))

        self._erase_btn = QPushButton("Eraser")
        self._erase_btn.setCheckable(True)
        self._erase_btn.setToolTip("Left-click/drag to erase pixels (make transparent)")
        self._erase_btn.toggled.connect(lambda c: self._on_tool_toggled(self._erase_btn, c, "erase"))

        self._select_btn = QPushButton("Select Color")
        self._select_btn.setCheckable(True)
        self._select_btn.setToolTip("Left-click to select all pixels of the same color")
        self._select_btn.toggled.connect(lambda c: self._on_tool_toggled(self._select_btn, c, "color_select"))

        mode_gl.addWidget(self._paint_btn)
        mode_gl.addWidget(self._erase_btn)
        mode_gl.addWidget(self._select_btn)
        tl.addWidget(mode_group)

        # Paint options
        paint_group = QGroupBox("Paint Brush")
        paint_gl = QVBoxLayout(paint_group)
        paint_gl.setContentsMargins(6, 4, 6, 4)
        paint_gl.setSpacing(4)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(32, 32)
        update_color_btn(self._color_btn, QColor(Qt.GlobalColor.white))
        self._color_btn.clicked.connect(self._on_pick_color)
        color_row.addWidget(self._color_btn)
        color_row.addStretch()
        paint_gl.addLayout(color_row)

        paint_gl.addWidget(QLabel("Brush Size:"))
        size_row = QHBoxLayout()
        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(1, 200)
        self._size_slider.setValue(15)
        self._size_slider.valueChanged.connect(self._on_size_slider)
        size_row.addWidget(self._size_slider, stretch=1)
        self._size_spin = QSpinBox()
        self._size_spin.setRange(1, 200)
        self._size_spin.setValue(15)
        self._size_spin.setSuffix(" px")
        self._size_spin.valueChanged.connect(self._on_size_spin)
        size_row.addWidget(self._size_spin)
        paint_gl.addLayout(size_row)

        paint_gl.addWidget(QLabel("Hardness:"))
        hard_row = QHBoxLayout()
        self._hard_slider = QSlider(Qt.Orientation.Horizontal)
        self._hard_slider.setRange(0, 100)
        self._hard_slider.setValue(100)
        self._hard_slider.valueChanged.connect(self._on_hardness_slider)
        hard_row.addWidget(self._hard_slider, stretch=1)
        self._hard_lbl = QLabel("100%")
        self._hard_lbl.setFixedWidth(36)
        hard_row.addWidget(self._hard_lbl)
        paint_gl.addLayout(hard_row)

        paint_gl.addWidget(QLabel("Flow:"))
        flow_row = QHBoxLayout()
        self._flow_slider = QSlider(Qt.Orientation.Horizontal)
        self._flow_slider.setRange(1, 100)
        self._flow_slider.setValue(100)
        self._flow_slider.valueChanged.connect(self._on_flow_slider)
        flow_row.addWidget(self._flow_slider, stretch=1)
        self._flow_lbl = QLabel("100%")
        self._flow_lbl.setFixedWidth(36)
        flow_row.addWidget(self._flow_lbl)
        paint_gl.addLayout(flow_row)

        tl.addWidget(paint_group)

        # Filters
        filter_group = QGroupBox("Filters")
        filter_gl = QVBoxLayout(filter_group)
        filter_gl.setContentsMargins(6, 4, 6, 4)
        filter_gl.setSpacing(4)

        filter_gl.addWidget(QLabel("Posterize – reduce color count:"))
        post_row = QHBoxLayout()
        self._post_btn = QPushButton("Apply Posterize")
        self._post_btn.clicked.connect(self._on_posterize)
        post_row.addWidget(self._post_btn)
        post_row.addWidget(QLabel("Levels:"))
        self._post_spin = QSpinBox()
        self._post_spin.setRange(2, 16)
        self._post_spin.setValue(4)
        self._post_spin.setToolTip("2 = 2 colors per channel (very harsh), 8 = gentle")
        post_row.addWidget(self._post_spin)
        filter_gl.addLayout(post_row)
        tl.addWidget(filter_group)

        # Selection
        sel_group = QGroupBox("Selection")
        sel_gl = QVBoxLayout(sel_group)
        sel_gl.setContentsMargins(6, 4, 6, 4)
        sel_gl.setSpacing(4)

        sel_row = QHBoxLayout()
        self._invert_btn = QPushButton("Invert")
        self._invert_btn.setToolTip("Invert selection within non-transparent area")
        self._invert_btn.clicked.connect(self._on_invert)
        sel_row.addWidget(self._invert_btn)
        self._clear_sel_btn = QPushButton("Deselect")
        self._clear_sel_btn.setEnabled(False)
        self._clear_sel_btn.clicked.connect(self._on_clear_sel)
        sel_row.addWidget(self._clear_sel_btn)
        sel_gl.addLayout(sel_row)

        self._delete_btn = QPushButton("Delete Selected Pixels  (→ transparent)")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        sel_gl.addWidget(self._delete_btn)

        self._fill_sel_btn = QPushButton("Fill Selection with Color")
        self._fill_sel_btn.setEnabled(False)
        self._fill_sel_btn.clicked.connect(self._on_fill_selection)
        sel_gl.addWidget(self._fill_sel_btn)

        # Highlight color picker
        hl_row = QHBoxLayout()
        hl_row.addWidget(QLabel("Highlight:"))
        self._sel_color_btn = QPushButton()
        self._sel_color_btn.setFixedSize(32, 32)
        self._sel_color_btn.setToolTip("Change selection highlight color")
        _default_sel_color = QColor(255, 0, 0, 120)
        update_color_btn(self._sel_color_btn, _default_sel_color)
        self._sel_color_btn.clicked.connect(self._on_pick_sel_color)
        hl_row.addWidget(self._sel_color_btn)
        hl_row.addStretch()
        sel_gl.addLayout(hl_row)

        tl.addWidget(sel_group)

        # Outline
        outline_group = QGroupBox("Outline")
        outline_gl = QHBoxLayout(outline_group)
        outline_gl.setContentsMargins(6, 4, 6, 4)
        self._outline_btn = QPushButton("Add Black Outline")
        self._outline_btn.clicked.connect(self._on_outline)
        outline_gl.addWidget(self._outline_btn)
        outline_gl.addWidget(QLabel("W:"))
        self._outline_spin = QSpinBox()
        self._outline_spin.setRange(1, 10)
        self._outline_spin.setValue(1)
        self._outline_spin.setSuffix(" px")
        outline_gl.addWidget(self._outline_spin)
        tl.addWidget(outline_group)

        tl.addStretch()
        root.addWidget(tool_panel)

        # ── Right: canvas + bottom bar ───────────────────────────────
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(4)

        self._canvas = ImageEditCanvas(working)
        self._canvas.selection_changed.connect(self._on_sel_changed)
        self._canvas.brush_size_changed.connect(self._on_brush_size_from_canvas)
        right.addWidget(self._canvas, stretch=1)

        # Bottom bar
        bot = QHBoxLayout()
        self._undo_btn = QPushButton("↩ Undo")
        self._undo_btn.setEnabled(False)
        self._undo_btn.setToolTip("Ctrl+Z")
        self._undo_btn.clicked.connect(self._on_undo)
        bot.addWidget(self._undo_btn)

        bot.addSpacing(12)
        bot.addWidget(QLabel("Zoom:"))
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(self._canvas.fit_to_window)
        bot.addWidget(fit_btn)
        zoom_out = QPushButton("−")
        zoom_out.setFixedWidth(28)
        zoom_out.clicked.connect(lambda: self._canvas._zoom_at(1.0 / 1.3, self._canvas.width() / 2, self._canvas.height() / 2))
        bot.addWidget(zoom_out)
        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setFixedWidth(52)
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bot.addWidget(self._zoom_lbl)
        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(28)
        zoom_in.clicked.connect(lambda: self._canvas._zoom_at(1.3, self._canvas.width() / 2, self._canvas.height() / 2))
        bot.addWidget(zoom_in)

        bot.addStretch()
        self._export_btn = QPushButton("Export Image…")
        self._export_btn.setToolTip("Save the current edited image to a file")
        self._export_btn.clicked.connect(self._on_export)
        bot.addWidget(self._export_btn)

        bot.addSpacing(8)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        bot.addWidget(self._cancel_btn)
        self._apply_new_btn = QPushButton("Apply to New Layer")
        self._apply_new_btn.setToolTip(
            "Create a new image layer above this one with the edited image"
        )
        self._apply_new_btn.clicked.connect(self._on_apply_to_new_layer)
        bot.addWidget(self._apply_new_btn)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setDefault(True)
        self._apply_btn.setToolTip("Apply edits to the layer and close")
        self._apply_btn.clicked.connect(self._on_apply)
        bot.addWidget(self._apply_btn)
        right.addLayout(bot)

        root.addLayout(right, stretch=1)

        # Zoom label refresh timer
        from PySide6.QtCore import QTimer
        self._ztimer = QTimer(self)
        self._ztimer.setInterval(150)
        self._ztimer.timeout.connect(self._refresh_zoom_label)
        self._ztimer.start()

        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._canvas.fit_to_window)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_tool_toggled(self, btn: QPushButton, checked: bool, mode: str) -> None:
        if checked:
            # Uncheck siblings
            for b in (self._paint_btn, self._erase_btn, self._select_btn):
                if b is not btn and b.isChecked():
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
            self._canvas.set_mode(mode)
        else:
            # If no button is active, revert to navigate
            if not any(b.isChecked() for b in (self._paint_btn, self._erase_btn, self._select_btn)):
                self._canvas.set_mode("")

    def _on_pick_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(self._canvas._paint_color, self, "Pick Paint Color")
        if color.isValid():
            self._canvas.set_paint_color(color)
            update_color_btn(self._color_btn, color)

    def _on_pick_sel_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog
        current = self._canvas._sel_color
        color = QColorDialog.getColor(
            current, self, "Pick Selection Highlight Color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if color.isValid():
            self._canvas.set_sel_color(color)
            update_color_btn(self._sel_color_btn, color)

    def _on_brush_size_from_canvas(self, v: int) -> None:
        """Sync slider/spinbox when brush size is changed via Ctrl+drag."""
        self._size_slider.blockSignals(True)
        self._size_spin.blockSignals(True)
        self._size_slider.setValue(v)
        self._size_spin.setValue(v)
        self._size_slider.blockSignals(False)
        self._size_spin.blockSignals(False)

    def _on_size_slider(self, v: int) -> None:
        self._size_spin.blockSignals(True)
        self._size_spin.setValue(v)
        self._size_spin.blockSignals(False)
        self._canvas.set_paint_radius(v)

    def _on_size_spin(self, v: int) -> None:
        self._size_slider.blockSignals(True)
        self._size_slider.setValue(v)
        self._size_slider.blockSignals(False)
        self._canvas.set_paint_radius(v)

    def _on_hardness_slider(self, v: int) -> None:
        self._hard_lbl.setText(f"{v}%")
        self._canvas.set_hardness(v / 100.0)

    def _on_flow_slider(self, v: int) -> None:
        self._flow_lbl.setText(f"{v}%")
        self._canvas.set_flow(v / 100.0)

    def _on_posterize(self) -> None:
        self._canvas.apply_posterize(self._post_spin.value())
        self._undo_btn.setEnabled(self._canvas.can_undo())

    def _on_invert(self) -> None:
        self._canvas.invert_selection()

    def _on_delete(self) -> None:
        self._canvas.delete_selection()
        self._undo_btn.setEnabled(self._canvas.can_undo())

    def _on_fill_selection(self) -> None:
        self._canvas.fill_selection(self._canvas._paint_color)
        self._undo_btn.setEnabled(self._canvas.can_undo())

    def _on_clear_sel(self) -> None:
        self._canvas.clear_selection()

    def _on_outline(self) -> None:
        self._canvas.apply_outline(self._outline_spin.value())
        self._undo_btn.setEnabled(self._canvas.can_undo())

    def _on_undo(self) -> None:
        self._canvas.undo()
        self._undo_btn.setEnabled(self._canvas.can_undo())

    def _on_export(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Image",
            "",
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;BMP Image (*.bmp)",
        )
        if not path:
            return
        img = self._canvas.get_image()
        if not img.save(path):
            QMessageBox.warning(self, "Export Failed", f"Could not save image to:\n{path}")

    def _on_apply(self) -> None:
        from app.commands.background_commands import EditImageCommand
        cmd = EditImageCommand(self._layer, self._canvas.get_image(), "Edit Image")
        self._command_stack.execute(cmd)
        self.accept()

    def _on_apply_to_new_layer(self) -> None:
        self.apply_to_new_layer.emit(self._canvas.get_image())
        self.accept()

    def _on_sel_changed(self) -> None:
        has = self._canvas.has_selection()
        self._delete_btn.setEnabled(has)
        self._fill_sel_btn.setEnabled(has)
        self._clear_sel_btn.setEnabled(has)

    def _refresh_zoom_label(self) -> None:
        self._zoom_lbl.setText(f"{int(round(self._canvas.zoom_level() * 100))}%")

    # ------------------------------------------------------------------
    # Close guard
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Warn before closing if there are unsaved edits."""
        if self._canvas.can_undo():
            from PySide6.QtWidgets import QMessageBox
            r = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved edits. Discard changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Z and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._canvas.undo()
            self._undo_btn.setEnabled(self._canvas.can_undo())
        else:
            super().keyPressEvent(event)
