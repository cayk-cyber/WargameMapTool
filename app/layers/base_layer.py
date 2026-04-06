"""Abstract base class for all layers."""

from __future__ import annotations

import math
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap, QTransform, Qt

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from app.hex.hex_math import Layout

# -------------------------------------------------------------------------
# Module-level emboss tile cache for structure effect
# -------------------------------------------------------------------------

_emboss_tile_cache: dict[tuple, QImage] = {}
_EMBOSS_CACHE_MAX = 32


def _compute_emboss_tile(
    texture_id: str, angle_deg: float, invert: bool,
) -> QImage | None:
    """Compute a gradient-based bump map tile from a texture.

    Uses central-difference gradients and a directional dot-product with the
    light vector for proper 3D lighting.  The result is a neutral-gray (128)
    based image where brighter = highlight (facing light), darker = shadow.
    Cached by (texture_id, angle rounded to 1°, invert).
    """
    if not _HAS_NUMPY:
        return None

    # Cache key — angle quantised to 1° for good precision without bloat
    angle_q = round(angle_deg % 360.0, 0)
    key = (texture_id, angle_q, invert)
    cached = _emboss_tile_cache.get(key)
    if cached is not None:
        return cached

    from app.io.texture_cache import get_texture_image

    tex_img = get_texture_image(texture_id)
    if tex_img is None:
        return None

    img = tex_img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    if w < 4 or h < 4:
        return None

    ptr = img.bits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, w, 4).copy()

    # BGRA layout: B=0, G=1, R=2, A=3 → luminance
    gray = (
        0.114 * arr[:, :, 0].astype(np.float32)
        + 0.587 * arr[:, :, 1].astype(np.float32)
        + 0.299 * arr[:, :, 2].astype(np.float32)
    ) / 255.0  # normalise to 0..1

    if invert:
        gray = 1.0 - gray

    # Central-difference gradients (float precision, wrapping for tileable textures)
    gx = (np.roll(gray, -1, axis=1) - np.roll(gray, 1, axis=1)) * 0.5
    gy = (np.roll(gray, -1, axis=0) - np.roll(gray, 1, axis=0)) * 0.5

    # Light direction (continuous float, not quantised to integer pixels)
    rad = math.radians(angle_deg)
    lx = math.cos(rad)
    ly = -math.sin(rad)

    # Dot product: how much each surface point faces the light
    lighting = gx * lx + gy * ly

    # Scale factor — 3.0 gives good visible relief without clipping too much
    embossed = np.clip(128.0 + lighting * 255.0 * 3.0, 0.0, 255.0).astype(
        np.uint8
    )

    result_arr = np.zeros((h, w, 4), dtype=np.uint8)
    result_arr[:, :, 0] = embossed  # B
    result_arr[:, :, 1] = embossed  # G
    result_arr[:, :, 2] = embossed  # R
    result_arr[:, :, 3] = 255  # A
    result_arr = np.ascontiguousarray(result_arr)

    result_img = QImage(
        result_arr.data, w, h, w * 4, QImage.Format.Format_ARGB32,
    ).copy()  # .copy() so the QImage owns its data

    # LRU-style eviction
    if len(_emboss_tile_cache) >= _EMBOSS_CACHE_MAX:
        oldest = next(iter(_emboss_tile_cache))
        del _emboss_tile_cache[oldest]
    _emboss_tile_cache[key] = result_img
    return result_img


def clear_emboss_cache() -> None:
    """Invalidate all cached emboss tiles (e.g. after texture library changes)."""
    _emboss_tile_cache.clear()


class Layer(ABC):
    # Subclasses that should be clipped to the hex grid boundary set this to True
    clip_to_grid: bool = False
    # Subclasses that render better without the pixmap cache (e.g. vector/direct layers)
    cacheable: bool = True
    # Global toggle: when False, shadow/bevel/structure effects are suppressed
    # across ALL layers.  Outline (DrawLayer only) is NOT affected.
    _gfx_effects_enabled: bool = True

    def __init__(self, name: str):
        self.id: str = str(uuid.uuid4())
        self.name: str = name
        self.visible: bool = True
        self.opacity: float = 1.0
        # Pixmap cache for fast pan/zoom (managed by canvas_widget)
        self._cache_dirty: bool = True
        self._cache_pixmap: QPixmap | None = None
        self._cache_bounds: QRectF | None = None

    def mark_dirty(self) -> None:
        """Mark layer cache as stale. Call from all data mutation methods."""
        self._cache_dirty = True
        self._cache_pixmap = None

    @abstractmethod
    def paint(self, painter: QPainter, viewport_rect: QRectF, layout: Layout) -> None:
        pass

    @abstractmethod
    def serialize(self) -> dict:
        pass

    @classmethod
    @abstractmethod
    def deserialize(cls, data: dict) -> Layer:
        pass

    def _base_serialize(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "visible": self.visible,
            "opacity": self.opacity,
        }

    def _base_deserialize(self, data: dict) -> None:
        self.id = data.get("id", self.id)
        self.name = data.get("name", self.name)
        self.visible = data.get("visible", True)
        self.opacity = data.get("opacity", 1.0)

    # -------------------------------------------------------------------------
    # Shared shadow helpers (used by any layer that has shadow_* fields)
    # -------------------------------------------------------------------------

    def _build_shadow_composite(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        paint_fn: Callable[[QPainter, QRectF, Layout], None],
    ) -> tuple[QImage | None, QPointF, float]:
        """Render layer content into an off-screen QImage for shadow application.

        Builds the composite at device-pixel resolution so the result is crisp
        at any zoom level.  Returns (image, screen_top_left, device_scale).
        Returns (None, screen_tl, device_scale) if the area is too large.
        """
        xf = painter.worldTransform()
        device_scale = math.sqrt(xf.m11() ** 2 + xf.m21() ** 2)
        if device_scale < 0.01:
            device_scale = 1.0

        bx, by = viewport_rect.x(), viewport_rect.y()
        screen_tl = xf.map(QPointF(bx, by))

        pw = max(1, int(math.ceil(viewport_rect.width() * device_scale)))
        ph = max(1, int(math.ceil(viewport_rect.height() * device_scale)))
        if pw * ph > 25_000_000:
            return None, screen_tl, device_scale

        composite = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
        if composite.isNull():
            return None, screen_tl, device_scale
        composite.fill(Qt.GlobalColor.transparent)
        cp = QPainter(composite)
        cp.setRenderHint(QPainter.RenderHint.Antialiasing)
        cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cp.scale(device_scale, device_scale)
        cp.translate(-bx, -by)
        paint_fn(cp, viewport_rect, layout)
        cp.end()
        return composite, screen_tl, device_scale

    @staticmethod
    def _shadow_offset(angle_deg: float, distance: float) -> tuple[float, float]:
        """Convert Photoshop-style angle+distance to (ox, oy) world-space offset."""
        rad = math.radians(180.0 - angle_deg)
        return distance * math.cos(rad), distance * math.sin(rad)

    def _paint_outer_shadow(
        self,
        painter: QPainter,
        composite: QImage,
        screen_tl: QPointF,
        device_scale: float = 1.0,
    ) -> None:
        """Outer drop shadow via multi-offset radial technique.

        Expects painter to have no world transform (screen space).
        Uses self.shadow_color / shadow_opacity / shadow_angle / shadow_distance /
        shadow_spread / shadow_size.
        """
        shadow_img = QImage(composite.size(), QImage.Format.Format_ARGB32_Premultiplied)
        if shadow_img.isNull():
            return
        shadow_img.fill(Qt.GlobalColor.transparent)
        sp = QPainter(shadow_img)
        sp.drawImage(0, 0, composite)
        sp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        color = QColor(self.shadow_color)  # type: ignore[attr-defined]
        color.setAlphaF(1.0)
        sp.fillRect(shadow_img.rect(), color)
        sp.end()

        raw_ox, raw_oy = self._shadow_offset(
            self.shadow_angle, self.shadow_distance,  # type: ignore[attr-defined]
        )
        ox = raw_ox * device_scale
        oy = raw_oy * device_scale
        # Spread [0-100] hardens the edge by reducing the effective blur radius
        spread = getattr(self, "shadow_spread", 0.0)  # type: ignore[attr-defined]
        blur = self.shadow_size * max(0.0, 1.0 - spread / 100.0) * device_scale  # type: ignore[attr-defined]
        sx, sy = screen_tl.x(), screen_tl.y()

        painter.save()
        if blur <= 0:
            painter.setOpacity(self.shadow_opacity)  # type: ignore[attr-defined]
            painter.drawImage(QPointF(sx + ox, sy + oy), shadow_img)
            painter.restore()
            return

        num_passes = 12
        alpha_per_pass = self.shadow_opacity / (num_passes + 1)  # type: ignore[attr-defined]
        for i in range(num_passes):
            angle = 2.0 * math.pi * i / num_passes
            dx = math.cos(angle) * blur * 0.5
            dy = math.sin(angle) * blur * 0.5
            painter.setOpacity(alpha_per_pass)
            painter.drawImage(QPointF(sx + ox + dx, sy + oy + dy), shadow_img)
        painter.setOpacity(self.shadow_opacity * 0.5)  # type: ignore[attr-defined]
        painter.drawImage(QPointF(sx + ox, sy + oy), shadow_img)
        painter.restore()

    def _paint_inner_shadow(
        self,
        painter: QPainter,
        composite: QImage,
        screen_tl: QPointF,
        device_scale: float = 1.0,
    ) -> None:
        """Inner shadow via inverted-alpha clipped technique.

        Expects painter to have no world transform (screen space).
        Uses self.shadow_color / shadow_opacity / shadow_angle / shadow_distance /
        shadow_spread / shadow_size.
        """
        w, h = composite.width(), composite.height()

        inverted = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        if inverted.isNull():
            return
        inverted.fill(QColor(self.shadow_color))  # type: ignore[attr-defined]
        ip = QPainter(inverted)
        ip.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        ip.drawImage(0, 0, composite)
        ip.end()

        raw_ox, raw_oy = self._shadow_offset(
            self.shadow_angle, self.shadow_distance,  # type: ignore[attr-defined]
        )
        ox = raw_ox * device_scale
        oy = raw_oy * device_scale
        spread = getattr(self, "shadow_spread", 0.0)  # type: ignore[attr-defined]
        blur = self.shadow_size * max(0.0, 1.0 - spread / 100.0) * device_scale  # type: ignore[attr-defined]

        shadow_result = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        shadow_result.fill(Qt.GlobalColor.transparent)
        sp = QPainter(shadow_result)
        if blur <= 0:
            sp.setOpacity(self.shadow_opacity)  # type: ignore[attr-defined]
            sp.drawImage(QPointF(ox, oy), inverted)
        else:
            num_passes = 12
            alpha_per_pass = self.shadow_opacity / (num_passes + 1)  # type: ignore[attr-defined]
            for i in range(num_passes):
                angle = 2.0 * math.pi * i / num_passes
                dx = math.cos(angle) * blur * 0.5
                dy = math.sin(angle) * blur * 0.5
                sp.setOpacity(alpha_per_pass)
                sp.drawImage(QPointF(ox + dx, oy + dy), inverted)
            sp.setOpacity(self.shadow_opacity * 0.5)  # type: ignore[attr-defined]
            sp.drawImage(QPointF(ox, oy), inverted)
        sp.setOpacity(1.0)
        sp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        sp.drawImage(0, 0, composite)
        sp.end()

        painter.drawImage(screen_tl, shadow_result)

    # -------------------------------------------------------------------------
    # Shared bevel & emboss helpers (used by layers with bevel_* fields)
    # -------------------------------------------------------------------------

    def _paint_inner_bevel(
        self,
        painter: QPainter,
        composite: QImage,
        pos_x: float,
        pos_y: float,
        scale: float,
        dst_w: float = 0.0,
        dst_h: float = 0.0,
    ) -> None:
        """Inner bevel: highlight and shadow edges rendered inside content.

        When *dst_w* > 0 the images are drawn via QRectF (DrawLayer path for
        non-native resolution).  Otherwise QPointF is used (HexsideLayer path).
        Uses self.bevel_angle / bevel_size / bevel_depth /
        bevel_highlight_color / bevel_highlight_opacity /
        bevel_shadow_color / bevel_shadow_opacity.
        """
        size_px = self.bevel_size * scale  # type: ignore[attr-defined]
        if size_px < 0.5:
            return

        w, h = composite.width(), composite.height()

        # Direction vector: compute inline to avoid subclass override conflicts
        # with _shadow_offset (DrawLayer/AssetLayer redefine the signature).
        rad = math.radians(180.0 - self.bevel_angle)  # type: ignore[attr-defined]
        shadow_dx, shadow_dy = math.cos(rad), math.sin(rad)

        num_passes = max(1, min(4, int(math.ceil(size_px))))

        highlight = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        highlight.fill(Qt.GlobalColor.transparent)
        shadow_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        shadow_img.fill(Qt.GlobalColor.transparent)
        temp = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)

        per_alpha = 1.0 / num_passes

        for i in range(1, num_passes + 1):
            offset = i * size_px / num_passes

            # Highlight: shift composite in shadow direction → exposes
            # the edge facing the light.
            temp.fill(Qt.GlobalColor.transparent)
            tp = QPainter(temp)
            tp.drawImage(0, 0, composite)
            tp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut,
            )
            tp.drawImage(
                QPointF(shadow_dx * offset, shadow_dy * offset), composite,
            )
            tp.end()

            hp = QPainter(highlight)
            hp.setOpacity(per_alpha)
            hp.drawImage(0, 0, temp)
            hp.end()

            # Shadow: shift composite in light direction (opposite).
            temp.fill(Qt.GlobalColor.transparent)
            tp = QPainter(temp)
            tp.drawImage(0, 0, composite)
            tp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut,
            )
            tp.drawImage(
                QPointF(-shadow_dx * offset, -shadow_dy * offset), composite,
            )
            tp.end()

            sp = QPainter(shadow_img)
            sp.setOpacity(per_alpha)
            sp.drawImage(0, 0, temp)
            sp.end()

        # Colorize highlight
        hp = QPainter(highlight)
        hp.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn,
        )
        hp.fillRect(
            highlight.rect(),
            QColor(self.bevel_highlight_color),  # type: ignore[attr-defined]
        )
        hp.end()

        # Colorize shadow
        sp = QPainter(shadow_img)
        sp.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn,
        )
        sp.fillRect(
            shadow_img.rect(),
            QColor(self.bevel_shadow_color),  # type: ignore[attr-defined]
        )
        sp.end()

        # Clip to content alpha so bevel only appears over visible strokes
        hp = QPainter(highlight)
        hp.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn,
        )
        hp.drawImage(0, 0, composite)
        hp.end()

        sp = QPainter(shadow_img)
        sp.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn,
        )
        sp.drawImage(0, 0, composite)
        sp.end()

        depth = self.bevel_depth  # type: ignore[attr-defined]
        use_rectf = dst_w > 0

        painter.save()
        if use_rectf:
            src_rect = QRectF(highlight.rect())
            dst = QRectF(pos_x, pos_y, dst_w, dst_h)
            painter.setOpacity(depth * self.bevel_highlight_opacity)  # type: ignore[attr-defined]
            painter.drawImage(dst, highlight, src_rect)
            painter.setOpacity(depth * self.bevel_shadow_opacity)  # type: ignore[attr-defined]
            painter.drawImage(dst, shadow_img, src_rect)
        else:
            pt = QPointF(pos_x, pos_y)
            painter.setOpacity(depth * self.bevel_highlight_opacity)  # type: ignore[attr-defined]
            painter.drawImage(pt, highlight)
            painter.setOpacity(depth * self.bevel_shadow_opacity)  # type: ignore[attr-defined]
            painter.drawImage(pt, shadow_img)
        painter.restore()

    def _paint_outer_bevel(
        self,
        painter: QPainter,
        composite: QImage,
        pos_x: float,
        pos_y: float,
        scale: float,
        dst_w: float = 0.0,
        dst_h: float = 0.0,
    ) -> None:
        """Outer bevel: highlight and shadow halos outside the content.

        Same API as _paint_inner_bevel.
        """
        size_px = self.bevel_size * scale  # type: ignore[attr-defined]
        if size_px < 0.5:
            return

        w, h = composite.width(), composite.height()
        rad = math.radians(180.0 - self.bevel_angle)  # type: ignore[attr-defined]
        shadow_dx, shadow_dy = math.cos(rad), math.sin(rad)

        num_passes = max(1, min(4, int(math.ceil(size_px))))

        highlight = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        highlight.fill(Qt.GlobalColor.transparent)
        shadow_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        shadow_img.fill(Qt.GlobalColor.transparent)
        temp = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)

        per_alpha = 1.0 / num_passes

        for i in range(1, num_passes + 1):
            offset = i * size_px / num_passes

            # Outer highlight: shift composite toward light, then subtract
            # original → halo on the light side.
            temp.fill(Qt.GlobalColor.transparent)
            tp = QPainter(temp)
            tp.drawImage(
                QPointF(-shadow_dx * offset, -shadow_dy * offset), composite,
            )
            tp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut,
            )
            tp.drawImage(0, 0, composite)
            tp.end()

            hp = QPainter(highlight)
            hp.setOpacity(per_alpha)
            hp.drawImage(0, 0, temp)
            hp.end()

            # Outer shadow: shift composite away from light, subtract original.
            temp.fill(Qt.GlobalColor.transparent)
            tp = QPainter(temp)
            tp.drawImage(
                QPointF(shadow_dx * offset, shadow_dy * offset), composite,
            )
            tp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut,
            )
            tp.drawImage(0, 0, composite)
            tp.end()

            sp = QPainter(shadow_img)
            sp.setOpacity(per_alpha)
            sp.drawImage(0, 0, temp)
            sp.end()

        # Colorize
        hp = QPainter(highlight)
        hp.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn,
        )
        hp.fillRect(
            highlight.rect(),
            QColor(self.bevel_highlight_color),  # type: ignore[attr-defined]
        )
        hp.end()

        sp = QPainter(shadow_img)
        sp.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn,
        )
        sp.fillRect(
            shadow_img.rect(),
            QColor(self.bevel_shadow_color),  # type: ignore[attr-defined]
        )
        sp.end()

        depth = self.bevel_depth  # type: ignore[attr-defined]
        use_rectf = dst_w > 0

        painter.save()
        if use_rectf:
            src_rect = QRectF(highlight.rect())
            dst = QRectF(pos_x, pos_y, dst_w, dst_h)
            painter.setOpacity(depth * self.bevel_highlight_opacity)  # type: ignore[attr-defined]
            painter.drawImage(dst, highlight, src_rect)
            painter.setOpacity(depth * self.bevel_shadow_opacity)  # type: ignore[attr-defined]
            painter.drawImage(dst, shadow_img, src_rect)
        else:
            pt = QPointF(pos_x, pos_y)
            painter.setOpacity(depth * self.bevel_highlight_opacity)  # type: ignore[attr-defined]
            painter.drawImage(pt, highlight)
            painter.setOpacity(depth * self.bevel_shadow_opacity)  # type: ignore[attr-defined]
            painter.drawImage(pt, shadow_img)
        painter.restore()

    # -------------------------------------------------------------------------
    # Shared structure (texture bump) helpers
    # -------------------------------------------------------------------------

    def _apply_structure_to_composite(
        self,
        composite: QImage,
    ) -> QImage:
        """Apply structure texture bump mapping to composite.

        Uses a gradient-based emboss tile split into per-pixel highlight
        (white) and shadow (black) masks for a proper 3D lighting look.

        Returns a NEW QImage (never modifies *composite* in place).
        Uses self.structure_texture_id / structure_scale / structure_depth /
        structure_invert and self.bevel_angle for the emboss direction.
        """
        if not _HAS_NUMPY:
            return composite

        texture_id = self.structure_texture_id  # type: ignore[attr-defined]
        if not texture_id:
            return composite

        depth = self.structure_depth  # type: ignore[attr-defined]
        if depth <= 0:
            return composite

        angle = getattr(self, "bevel_angle", 120.0)
        tile = _compute_emboss_tile(
            texture_id,
            angle,
            self.structure_invert,  # type: ignore[attr-defined]
        )
        if tile is None:
            return composite

        w, h = composite.width(), composite.height()

        # --- 1. Tile the emboss map across composite dimensions ---
        structure = QImage(w, h, QImage.Format.Format_ARGB32)
        structure.fill(QColor(128, 128, 128, 255))
        sp = QPainter(structure)
        tile_pixmap = QPixmap.fromImage(tile)
        brush = QBrush(tile_pixmap)
        scale = self.structure_scale  # type: ignore[attr-defined]
        if abs(scale - 1.0) > 0.001:
            xf = QTransform()
            xf.scale(scale, scale)
            brush.setTransform(xf)
        sp.fillRect(structure.rect(), brush)
        sp.end()

        # --- 2. Extract emboss values and composite alpha via numpy ---
        s_ptr = structure.bits()
        s_arr = np.frombuffer(s_ptr, dtype=np.uint8).reshape(h, w, 4).copy()
        emboss = s_arr[:, :, 0].astype(np.float32)  # grayscale (all channels equal)

        comp_a = composite.convertToFormat(QImage.Format.Format_ARGB32)
        ca_ptr = comp_a.bits()
        ca_arr = np.frombuffer(ca_ptr, dtype=np.uint8).reshape(h, w, 4)
        comp_alpha = ca_arr[:, :, 3].astype(np.float32) / 255.0

        depth_factor = min(depth / 100.0, 1.0)

        # --- 3. Build highlight mask (white, alpha proportional to brightness above 128) ---
        hl_strength = np.maximum(emboss - 128.0, 0.0) / 127.0  # 0..1
        hl_alpha = np.clip(
            hl_strength * depth_factor * comp_alpha * 255.0, 0, 255
        ).astype(np.uint8)

        hi_arr = np.empty((h, w, 4), dtype=np.uint8)
        hi_arr[:, :, 0] = 255  # B
        hi_arr[:, :, 1] = 255  # G
        hi_arr[:, :, 2] = 255  # R
        hi_arr[:, :, 3] = hl_alpha
        hi_arr = np.ascontiguousarray(hi_arr)
        hi_img = QImage(
            hi_arr.data, w, h, w * 4, QImage.Format.Format_ARGB32
        ).copy()

        # --- 4. Build shadow mask (black, alpha proportional to darkness below 128) ---
        sh_strength = np.maximum(128.0 - emboss, 0.0) / 128.0  # 0..1
        sh_alpha = np.clip(
            sh_strength * depth_factor * comp_alpha * 255.0, 0, 255
        ).astype(np.uint8)

        sh_arr = np.zeros((h, w, 4), dtype=np.uint8)
        sh_arr[:, :, 3] = sh_alpha
        sh_arr = np.ascontiguousarray(sh_arr)
        sh_img = QImage(
            sh_arr.data, w, h, w * 4, QImage.Format.Format_ARGB32
        ).copy()

        # --- 5. Composite highlight + shadow onto result ---
        result = QImage(composite)  # copy preserves format
        rp = QPainter(result)
        rp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        rp.drawImage(0, 0, hi_img)
        rp.drawImage(0, 0, sh_img)
        rp.end()

        return result
