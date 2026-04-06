"""Draw layer - channel-mask based painting surface."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPixmap,
    QTransform,
    Qt,
)

from app.layers.base_layer import Layer
from app.models.draw_object import DrawChannel


class DrawLayer(Layer):
    clip_to_grid = True
    # Bypass the full-map pixmap cache in _paint_layer; DrawLayer manages its
    # own viewport-sized composite buffer so only the visible area is rebuilt
    # on each paint call (typically 800×600 instead of the full map).
    cacheable = False

    def __init__(self, name: str = "Draw"):
        super().__init__(name)
        self.channels: list[DrawChannel] = []
        # Optional callback invoked whenever the channel list changes.
        # Set by the tool options panel to keep its UI in sync.
        self._channels_changed_cb = None

        # Layer-level outline effect
        self.outline_enabled: bool = False
        self.outline_color: str = "#000000"
        self.outline_width: float = 2.0

        # Layer-level drop shadow effect
        self.shadow_enabled: bool = False
        self.shadow_type: str = "outer"  # "outer" or "inner"
        self.shadow_color: str = "#000000"
        self.shadow_opacity: float = 0.5
        self.shadow_angle: float = 120.0
        self.shadow_distance: float = 5.0
        self.shadow_spread: float = 0.0
        self.shadow_size: float = 5.0

        # Layer-level bevel & emboss
        self.bevel_enabled: bool = False
        self.bevel_type: str = "inner"  # "inner" or "outer"
        self.bevel_angle: float = 120.0
        self.bevel_size: float = 3.0
        self.bevel_depth: float = 0.5
        self.bevel_highlight_color: str = "#ffffff"
        self.bevel_highlight_opacity: float = 0.75
        self.bevel_shadow_color: str = "#000000"
        self.bevel_shadow_opacity: float = 0.75

        # Layer-level structure (texture bump)
        self.structure_enabled: bool = False
        self.structure_texture_id: str | None = None
        self.structure_scale: float = 1.0
        self.structure_depth: float = 50.0
        self.structure_invert: bool = False

        # Viewport-sized composite buffer.  Valid as long as neither the layer
        # data, viewport region, nor zoom scale has changed.  Cleared by mark_dirty().
        self._ibuf: QImage | None = None
        self._ibuf_bounds: QRectF = QRectF()
        self._ibuf_scale: tuple[float, float] = (1.0, 1.0)

        # Full-layer QPixmap cache for fast pan/zoom after a stroke completes.
        # Built by build_full_cache() (called from draw_tool after mouse_release).
        # Cleared by mark_dirty() when data changes.
        # _paint_layer in canvas_widget detects this attribute and uses it as a
        # fast-path that bypasses the standard full-map cache rebuild.
        self._managed_cache_pixmap: QPixmap | None = None
        self._managed_cache_bounds: QRectF = QRectF()

        # Last zoom scale seen in paint().  Used by build_full_cache() so the
        # managed pixmap is built at screen-pixel resolution (same as the live
        # rendering path) and therefore looks identical to an active stroke.
        self._last_paint_zoom: tuple[float, float] = (1.0, 1.0)

        # Per-channel rendered QImage cache keyed by channel.id.
        # When only one channel's mask changes (e.g. during a brush stroke),
        # mark_channel_dirty() removes only that channel's entry so all other
        # channels can be composited from cache instead of being re-rendered.
        # Invalidated (cleared completely) by mark_dirty() and when render_bounds
        # or scale change between frames.
        self._channel_cache: dict[str, QImage | None] = {}
        self._channel_cache_bounds: QRectF = QRectF()
        self._channel_cache_scale: tuple[float, float] = (1.0, 1.0)

        # Effect image caches — avoid re-creating per frame.
        self._outline_cache: QImage | None = None
        self._outline_cache_key: tuple | None = None
        self._shadow_cache: QImage | None = None
        self._shadow_cache_key: tuple | None = None

        # Full-layer effects cache (outline/shadow baked in, screen-pixel resolution).
        # Valid as long as neither the layer data nor the zoom scale has changed.
        # Built by canvas_widget._paint_layer() so panning is O(1) even with effects.
        # Invalidated by mark_dirty() / mark_channel_dirty() and on zoom change.
        self._effects_cache_pixmap: QPixmap | None = None
        self._effects_cache_bounds: QRectF = QRectF()
        self._effects_cache_scale: float = 0.0

    # -------------------------------------------------------------------------
    # Data mutation
    # -------------------------------------------------------------------------

    def mark_dirty(self) -> None:
        super().mark_dirty()
        self._ibuf = None
        self._managed_cache_pixmap = None
        self._effects_cache_pixmap = None
        self._channel_cache.clear()
        self._outline_cache = None
        self._shadow_cache = None

    def mark_channel_dirty(self, channel_id: str) -> None:
        """Partially invalidate caches for a single channel only.

        Use this instead of mark_dirty() when exactly one channel's mask has
        changed (e.g. every stamp during a brush stroke).  All other channels
        keep their cached rendered QImages so only the modified channel is
        re-rendered on the next paint call.
        """
        # Invalidate composite buffers (they include the changed channel).
        super().mark_dirty()
        self._ibuf = None
        self._managed_cache_pixmap = None
        self._effects_cache_pixmap = None
        # Remove only the painted channel from the per-channel cache.
        self._channel_cache.pop(channel_id, None)
        self._outline_cache = None
        self._shadow_cache = None

    def update_composite_dirty_rect(
        self, channel_id: str, dirty_world_rect: QRectF
    ) -> None:
        """Incrementally update the cached composite for the region changed by a brush stamp.

        Called from draw_tool.mouse_move() instead of mark_channel_dirty() so that
        only the brush-stamp-sized dirty region is re-rendered per frame, rather than
        rebuilding the entire viewport composite from scratch.

        Falls back to mark_channel_dirty() when the incremental path is unavailable
        (e.g. _ibuf not yet built, channel not in cache, or empty dirty rect).
        """
        if dirty_world_rect.isEmpty() or self._ibuf is None:
            self.mark_channel_dirty(channel_id)
            return

        ch = self.find_channel(channel_id)
        if ch is None or ch.mask_image is None:
            self.mark_channel_dirty(channel_id)
            return

        ch_img = self._channel_cache.get(channel_id)
        if ch_img is None:
            self.mark_channel_dirty(channel_id)
            return

        render_bounds = self._ibuf_bounds
        scale_x, scale_y = self._ibuf_scale

        # Convert dirty world rect to composite pixel rect, plus a 2px rounding margin.
        px_x = (dirty_world_rect.x() - render_bounds.x()) * scale_x
        px_y = (dirty_world_rect.y() - render_bounds.y()) * scale_y
        px_w = dirty_world_rect.width() * scale_x
        px_h = dirty_world_rect.height() * scale_y
        dirty_px = QRectF(px_x - 2.0, px_y - 2.0, px_w + 4.0, px_h + 4.0)
        # Snap to integer pixel boundaries so that the Clear pass and the
        # subsequent SourceOver drawImage affect exactly the same pixels.
        # With fractional coordinates, fillRect(Clear) and drawImage may
        # round differently, leaving 1px transparent gaps at the edges that
        # let the layer below show through as rectangular artifacts.
        dirty_px = QRectF(dirty_px.toAlignedRect())
        dirty_px = dirty_px.intersected(QRectF(self._ibuf.rect()))
        if dirty_px.isEmpty():
            return

        # Transform coefficients (composite_px = (world - mask_offset) * scale).
        ox = (ch._mask_world_offset[0] - render_bounds.x()) * scale_x
        oy = (ch._mask_world_offset[1] - render_bounds.y()) * scale_y
        ms_x = scale_x / ch._mask_world_scale
        ms_y = scale_y / ch._mask_world_scale

        # --- Re-render just the dirty region of the channel image ---
        cp = QPainter(ch_img)
        cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if ch.texture_id:
            # Texture fill: clip painter to dirty region so only those pixels
            # are overwritten, then restore clipping for the DestinationIn pass.
            cp.setClipRect(dirty_px)
            self._fill_texture(cp, ch_img, ch, render_bounds, scale_x, scale_y)
            cp.setClipping(False)
        else:
            cp.fillRect(dirty_px, QColor(ch.color))

        # Re-apply the mask via DestinationIn using the exact mask sub-rect that
        # maps to dirty_px, so Qt only processes those pixels.
        cp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        mask_src_x = (dirty_px.x() - ox) / ms_x
        mask_src_y = (dirty_px.y() - oy) / ms_y
        mask_src_w = dirty_px.width() / ms_x
        mask_src_h = dirty_px.height() / ms_y
        cp.drawImage(dirty_px, ch.mask_image, QRectF(mask_src_x, mask_src_y, mask_src_w, mask_src_h))
        cp.end()

        # --- Re-composite just the dirty region of _ibuf ---
        visible = [c for c in self.channels if c.visible and c.mask_image is not None]
        ibuf_p = QPainter(self._ibuf)
        ibuf_p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        ibuf_p.fillRect(dirty_px, Qt.GlobalColor.transparent)
        ibuf_p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        for channel in reversed(visible):
            cached = self._channel_cache.get(channel.id)
            if cached is None:
                # A channel has no cached image — fall back to full rebuild.
                ibuf_p.end()
                self.mark_channel_dirty(channel_id)
                return
            ibuf_p.setOpacity(channel.opacity)
            ibuf_p.drawImage(dirty_px.topLeft(), cached, dirty_px)
        ibuf_p.end()

        # Managed cache (pan/zoom fast-path) will be rebuilt at stroke end.
        self._managed_cache_pixmap = None
        # Signal that this layer has changed and needs to be repainted.
        self._cache_dirty = True

    def _notify_channels_changed(self) -> None:
        if self._channels_changed_cb is not None:
            self._channels_changed_cb()

    def add_channel(self, channel: DrawChannel) -> None:
        self.channels.append(channel)
        self.mark_dirty()
        self._notify_channels_changed()

    def remove_channel(self, channel: DrawChannel) -> None:
        self.channels = [c for c in self.channels if c.id != channel.id]
        self.mark_dirty()
        self._notify_channels_changed()

    def insert_channel(self, index: int, channel: DrawChannel) -> None:
        self.channels.insert(index, channel)
        self.mark_dirty()
        self._notify_channels_changed()

    def index_of(self, channel: DrawChannel) -> int:
        for i, c in enumerate(self.channels):
            if c.id == channel.id:
                return i
        return -1

    def find_channel(self, channel_id: str) -> DrawChannel | None:
        for c in self.channels:
            if c.id == channel_id:
                return c
        return None

    # -------------------------------------------------------------------------
    # Bounds
    # -------------------------------------------------------------------------

    def _calculate_bounds(self) -> QRectF:
        """Combined world-space bounds of all visible channel masks + effects margin."""
        bounds = QRectF()
        for ch in self.channels:
            if not ch.visible or ch.mask_image is None:
                continue
            mx_off, my_off = ch._mask_world_offset
            mask_w_world = ch.mask_image.width() / ch._mask_world_scale
            mask_h_world = ch.mask_image.height() / ch._mask_world_scale
            ch_rect = QRectF(mx_off, my_off, mask_w_world, mask_h_world)
            if bounds.isEmpty():
                bounds = ch_rect
            else:
                bounds = bounds.united(ch_rect)

        if bounds.isEmpty():
            return QRectF()

        gfx = self._gfx_effects_enabled
        margin = 0.0
        if self.outline_enabled:
            margin = max(margin, self.outline_width + 2.0)
        if gfx and self.shadow_enabled:
            margin = max(
                margin,
                self.shadow_distance + self.shadow_size + 2.0,
            )
        if gfx and self.bevel_enabled and self.bevel_type == "outer":
            margin = max(margin, self.bevel_size + 2.0)
        if margin > 0:
            bounds = bounds.adjusted(-margin, -margin, margin, margin)
        return bounds

    # -------------------------------------------------------------------------
    # Full-layer managed cache
    # -------------------------------------------------------------------------

    def build_full_cache(self, viewport_rect: QRectF | None = None) -> None:
        """Build a QPixmap cache after a stroke completes for fast pan/zoom.

        Called from draw_tool after a stroke completes (mouse_release).
        Stores the result in _managed_cache_pixmap, which _paint_layer picks
        up as a fast-path for the first paint call after the stroke.

        When *viewport_rect* is provided the cache covers exactly the
        viewport–layer intersection (same region paint() would render).
        This guarantees pixel-perfect sharpness because the pixmap is built
        at screen resolution and never needs to be up-scaled.

        Skipped silently if the layer has no visible content.
        """
        visible = [ch for ch in self.channels if ch.visible and ch.mask_image is not None]
        if not visible:
            return

        layer_bounds = self._calculate_bounds()
        if layer_bounds.isEmpty():
            return

        # Use the viewport intersection (same as paint()) so the cache
        # stays at 1:1 screen resolution.  This avoids the 100M-pixel cap
        # that caused downscaling → blur when using full layer bounds.
        if viewport_rect is not None:
            gfx = self._gfx_effects_enabled
            margin = 0.0
            if self.outline_enabled:
                margin = max(margin, self.outline_width + 2.0)
            if gfx and self.shadow_enabled:
                margin = max(
                    margin,
                    self.shadow_distance + self.shadow_size + 2.0,
                )
            expanded = viewport_rect.adjusted(-margin, -margin, margin, margin)
            bounds = layer_bounds.intersected(expanded)
        else:
            bounds = layer_bounds

        if bounds.isEmpty():
            return

        scale_x, scale_y = self._last_paint_zoom
        w = max(1, int(math.ceil(bounds.width() * scale_x)))
        h = max(1, int(math.ceil(bounds.height() * scale_y)))

        # Safety cap (should rarely trigger with viewport-scoped bounds).
        if w * h > 100_000_000:
            sf = math.sqrt(100_000_000 / (w * h))
            w = max(1, int(w * sf))
            h = max(1, int(h * sf))
            scale_x = w / bounds.width()
            scale_y = h / bounds.height()

        # use_channel_cache=True: reuse cached channel images for unchanged
        # channels (only the active channel was removed from the cache by
        # mark_channel_dirty).
        composite = self._build_composite_image(bounds, w, h, scale_x, scale_y, visible, use_channel_cache=True)
        if composite is None:
            return

        self._managed_cache_pixmap = QPixmap.fromImage(composite)
        self._managed_cache_bounds = bounds

    # -------------------------------------------------------------------------
    # Rendering helpers
    # -------------------------------------------------------------------------

    def _get_channel_image(
        self,
        ch: DrawChannel,
        render_bounds: QRectF,
        w: int,
        h: int,
        scale_x: float,
        scale_y: float,
    ) -> QImage | None:
        """Return the per-channel rendered image from cache, or render and cache it.

        The cache is keyed by channel.id and is valid only for a specific
        render_bounds + scale combination.  When either changes, the entire
        per-channel cache is cleared and rebuilt from scratch.
        """
        new_scale = (scale_x, scale_y)
        if self._channel_cache_bounds != render_bounds or self._channel_cache_scale != new_scale:
            self._channel_cache.clear()
            self._channel_cache_bounds = render_bounds
            self._channel_cache_scale = new_scale

        if ch.id not in self._channel_cache:
            self._channel_cache[ch.id] = self._render_channel_to_image(
                ch, render_bounds, w, h, scale_x, scale_y
            )
        return self._channel_cache[ch.id]

    def _build_composite_image(
        self,
        render_bounds: QRectF,
        w: int,
        h: int,
        scale_x: float,
        scale_y: float,
        visible: list[DrawChannel],
        use_channel_cache: bool = True,
    ) -> QImage | None:
        """Build a w×h composite QImage for render_bounds from visible channels.

        When use_channel_cache=True (the default), each channel's rendered image
        is fetched from (or stored into) _channel_cache.  Pass False for
        build_full_cache() so the viewport-bounds cache is not overwritten.
        """
        composite = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        if composite.isNull():
            return None
        composite.fill(Qt.GlobalColor.transparent)
        cp = QPainter(composite)
        cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for ch in reversed(visible):
            if use_channel_cache:
                ch_img = self._get_channel_image(ch, render_bounds, w, h, scale_x, scale_y)
            else:
                ch_img = self._render_channel_to_image(ch, render_bounds, w, h, scale_x, scale_y)
            if ch_img is None:
                continue
            cp.setOpacity(ch.opacity)
            cp.drawImage(0, 0, ch_img)
        cp.setOpacity(1.0)
        cp.end()
        return composite

    # -------------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------------

    def _render_channel_to_image(
        self,
        ch: DrawChannel,
        composite_bounds: QRectF,
        w: int,
        h: int,
        scale_x: float,
        scale_y: float,
    ) -> QImage | None:
        """Render one channel to a w×h QImage matching composite_bounds.

        Step 1: Fill the image with the channel's color or world-locked texture.
        Step 2: Apply the channel mask via DestinationIn so only painted regions
                remain visible.

        Returns None if the channel has no mask (nothing painted yet).
        """
        if ch.mask_image is None:
            return None

        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        if img.isNull():
            return None

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # --- Fill with color or world-locked texture ---
        if ch.texture_id:
            self._fill_texture(p, img, ch, composite_bounds, scale_x, scale_y)
        else:
            p.fillRect(img.rect(), QColor(ch.color))

        # --- Apply mask via DestinationIn ---
        # Transform: mask_px → composite_px
        #   offset: (mask_world_offset - bounds.topLeft) * scale
        #   scale:  composite_px_per_world_unit / mask_px_per_world_unit
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.resetTransform()
        ox = (ch._mask_world_offset[0] - composite_bounds.x()) * scale_x
        oy = (ch._mask_world_offset[1] - composite_bounds.y()) * scale_y
        sx = scale_x / ch._mask_world_scale
        sy = scale_y / ch._mask_world_scale
        p.translate(ox, oy)
        p.scale(sx, sy)
        p.drawImage(QPointF(0.0, 0.0), ch.mask_image)
        p.end()

        return img

    @staticmethod
    def _fill_texture(
        p: QPainter,
        img: QImage,
        ch: DrawChannel,
        bounds: QRectF,
        scale_x: float,
        scale_y: float,
    ) -> None:
        """Fill img with a world-locked tiled texture."""
        from app.io.texture_cache import get_texture_image

        tex_img = get_texture_image(ch.texture_id)
        if tex_img is None:
            p.fillRect(img.rect(), QColor(ch.color))
            return

        tex_pixmap = QPixmap.fromImage(tex_img)
        brush = QBrush(tex_pixmap)
        xf = QTransform()
        # World-lock: composite_px(0,0) ↔ world(bounds.x(), bounds.y())
        # Translate so that texture tiles from world origin (0, 0).
        xf.translate(-bounds.x() * scale_x, -bounds.y() * scale_y)
        # Scale brush by the composite scale so texture tiles stay world-locked:
        # one texture pixel covers the same world area regardless of zoom level.
        xf.scale(scale_x, scale_y)
        if ch.texture_zoom != 1.0:
            xf.scale(ch.texture_zoom, ch.texture_zoom)
        if ch.texture_rotation != 0.0:
            xf.rotate(ch.texture_rotation)
        brush.setTransform(xf)
        p.fillRect(img.rect(), brush)

    def paint(self, painter: QPainter, viewport_rect: QRectF, layout) -> None:
        visible = [ch for ch in self.channels if ch.visible and ch.mask_image is not None]
        if not visible:
            return

        bounds = self._calculate_bounds()
        if bounds.isEmpty():
            return

        # Viewport culling
        gfx = self._gfx_effects_enabled
        margin = 0.0
        if self.outline_enabled:
            margin = max(margin, self.outline_width + 2.0)
        if gfx and self.shadow_enabled:
            margin = max(
                margin,
                self.shadow_distance + self.shadow_size + 2.0,
            )
        expanded = viewport_rect.adjusted(-margin, -margin, margin, margin)
        if not expanded.intersects(bounds):
            return

        # Clip composite to the visible area.
        # Renders only the intersection of layer bounds and (viewport + effect margin).
        render_bounds = bounds.intersected(expanded)
        if render_bounds.isEmpty():
            return

        # Derive screen-pixel scale from the world transform so the composite is
        # built at the actual display resolution.  At zoom 0.5 this halves both
        # dimensions (4× fewer pixels); at zoom 2 it doubles them.  Rounded to 4
        # decimal places to avoid spurious cache misses from floating-point noise.
        xf = painter.worldTransform()
        zoom_x = round(max(0.01, abs(xf.m11())), 4)
        zoom_y = round(max(0.01, abs(xf.m22())), 4)
        self._last_paint_zoom = (zoom_x, zoom_y)

        # Fast path: viewport buffer exact match (same region + same zoom).
        if (self._ibuf is not None
                and self._ibuf_bounds == render_bounds
                and self._ibuf_scale == (zoom_x, zoom_y)):
            self._draw_composite_screen(painter, self._ibuf, render_bounds, zoom_x, zoom_y)
            return

        # Composite needs rebuilding (pan/zoom changed render_bounds or scale).
        # Effect caches (outline/shadow) contain the silhouette of the old composite,
        # so they must be invalidated here — otherwise they lag behind during panning.
        self._outline_cache = None
        self._shadow_cache = None

        # Build composite at screen-pixel resolution (zoom_x/y pixels per world unit).
        w = max(1, int(math.ceil(render_bounds.width() * zoom_x)))
        h = max(1, int(math.ceil(render_bounds.height() * zoom_y)))
        scale_x, scale_y = zoom_x, zoom_y
        if w * h > 100_000_000:
            sf = math.sqrt(100_000_000 / (w * h))
            w = max(1, int(w * sf))
            h = max(1, int(h * sf))
            scale_x = w / render_bounds.width()
            scale_y = h / render_bounds.height()

        # Build composite from all visible channels.
        # Reversed so channels[0] (top of list) is drawn last = on top.
        composite = self._build_composite_image(render_bounds, w, h, scale_x, scale_y, visible)

        # Store in viewport buffer so identical subsequent repaints are free.
        self._ibuf = composite
        self._ibuf_bounds = render_bounds
        self._ibuf_scale = (scale_x, scale_y)

        self._draw_composite_screen(painter, composite, render_bounds, scale_x, scale_y)

    def _draw_composite_screen(
        self,
        painter: QPainter,
        composite: QImage,
        bounds: QRectF,
        scale_x: float,
        scale_y: float,
    ) -> None:
        """Draw composite at screen coordinates (without world transform).

        Converts bounds.topLeft() from world space to screen space using the
        painter's current world transform, then draws with resetTransform so
        the pre-scaled composite pixels map 1:1 to device pixels.  Effect
        offsets are multiplied by zoom_x/zoom_y (actual device scale) to stay
        in screen pixels.

        When the composite is at native screen resolution (no 100M-cap
        downsampling), drawImage(QPointF) is used so the image maps 1:1 to
        device pixels with no bilinear sub-pixel softening.  This keeps
        hard brush strokes crisp.  When downsampled, QRectF is used to
        upscale to the correct display size.
        """
        xf = painter.worldTransform()
        sx = bounds.x() * xf.m11() + xf.dx()
        sy = bounds.y() * xf.m22() + xf.dy()
        # Actual device-pixel scale from the world transform (not the possibly
        # reduced composite scale).  Used to size the destination rect and
        # effect offsets so the layer always appears at the correct size.
        zoom_x = abs(xf.m11())
        zoom_y = abs(xf.m22())
        dst_w = bounds.width() * zoom_x
        dst_h = bounds.height() * zoom_y

        # When composite was built at native screen resolution (scale matches
        # zoom), draw at natural pixel size to avoid bilinear sub-pixel
        # softening.  The ceil()-vs-exact difference is at most 1 device pixel.
        native = (abs(scale_x - zoom_x) < 0.001 and abs(scale_y - zoom_y) < 0.001)

        gfx = self._gfx_effects_enabled
        has_effects = (
            self.outline_enabled
            or (gfx and self.shadow_enabled)
            or (gfx and self.bevel_enabled)
            or (gfx and self.structure_enabled)
        )

        painter.save()
        painter.resetTransform()

        if not has_effects:
            if native:
                painter.drawImage(QPointF(round(sx), round(sy)), composite)
            else:
                painter.drawImage(QRectF(sx, sy, dst_w, dst_h), composite, QRectF(composite.rect()))
            painter.restore()
            return

        # Integer base position for effects — keeps outline/shadow aligned
        # with the main composite (offset error ≤ 0.5 device pixels).
        bsx = round(sx) if native else sx
        bsy = round(sy) if native else sy

        # --- Outer effects (behind composite) ---
        if gfx and self.shadow_enabled and self.shadow_type == "outer":
            self._paint_outer_shadow(painter, composite, bsx, bsy, zoom_x, zoom_y, dst_w, dst_h)

        if self.outline_enabled:
            self._paint_outline(painter, composite, bsx, bsy, zoom_x, zoom_y, dst_w, dst_h)

        if gfx and self.bevel_enabled and self.bevel_type == "outer":
            avg_zoom = (zoom_x + zoom_y) * 0.5
            self._paint_outer_bevel(
                painter, composite, bsx, bsy, avg_zoom, dst_w, dst_h,
            )

        # --- Apply structure to a copy before drawing ---
        draw_composite = composite
        if gfx and self.structure_enabled and self.structure_texture_id:
            draw_composite = self._apply_structure_to_composite(composite)

        painter.setOpacity(1.0)
        if native:
            painter.drawImage(QPointF(bsx, bsy), draw_composite)
        else:
            painter.drawImage(QRectF(sx, sy, dst_w, dst_h), draw_composite, QRectF(draw_composite.rect()))

        # --- Inner effects (over composite) ---
        if gfx and self.bevel_enabled and self.bevel_type == "inner":
            avg_zoom = (zoom_x + zoom_y) * 0.5
            self._paint_inner_bevel(
                painter, composite, bsx, bsy, avg_zoom, dst_w, dst_h,
            )

        if gfx and self.shadow_enabled and self.shadow_type == "inner":
            self._paint_inner_shadow(painter, composite, bsx, bsy, scale_x, scale_y, dst_w, dst_h)

        painter.restore()

    def _paint_outline(
        self,
        painter: QPainter,
        composite: QImage,
        sx: float,
        sy: float,
        zoom_x: float,
        zoom_y: float,
        dst_w: float,
        dst_h: float,
    ) -> None:
        """Render outline by drawing the content silhouette at multiple offsets."""
        cache_key = (composite.width(), composite.height(), self.outline_color, self.outline_width)
        if self._outline_cache is None or self._outline_cache_key != cache_key:
            outline_img = QImage(composite.size(), QImage.Format.Format_ARGB32_Premultiplied)
            if outline_img.isNull():
                return
            outline_img.fill(Qt.GlobalColor.transparent)
            op = QPainter(outline_img)
            op.drawImage(0, 0, composite)
            op.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            op.fillRect(outline_img.rect(), QColor(self.outline_color))
            op.end()
            self._outline_cache = outline_img
            self._outline_cache_key = cache_key

        num_offsets = 16
        # Use zoom_x/zoom_y (device scale) so the ring radius is correct in
        # device pixels regardless of whether the composite was downsampled.
        w_px = self.outline_width * (zoom_x + zoom_y) * 0.5
        src_rect = QRectF(self._outline_cache.rect())
        for i in range(num_offsets):
            angle = 2.0 * math.pi * i / num_offsets
            dx = math.cos(angle) * w_px
            dy = math.sin(angle) * w_px
            painter.drawImage(QRectF(sx + dx, sy + dy, dst_w, dst_h), self._outline_cache, src_rect)

    def _shadow_offset(self) -> tuple[float, float]:
        """Compute X/Y offset from angle (degrees) and distance."""
        rad = math.radians(self.shadow_angle)
        return (
            self.shadow_distance * math.cos(rad),
            self.shadow_distance * math.sin(rad),
        )

    def _paint_outer_shadow(
        self,
        painter: QPainter,
        composite: QImage,
        sx: float,
        sy: float,
        zoom_x: float,
        zoom_y: float,
        dst_w: float,
        dst_h: float,
    ) -> None:
        """Render outer drop shadow using multi-offset radial technique."""
        cache_key = (composite.width(), composite.height(), self.shadow_color)
        if self._shadow_cache is None or self._shadow_cache_key != cache_key:
            shadow_img = QImage(composite.size(), QImage.Format.Format_ARGB32_Premultiplied)
            if shadow_img.isNull():
                return
            shadow_img.fill(Qt.GlobalColor.transparent)
            sp = QPainter(shadow_img)
            sp.drawImage(0, 0, composite)
            sp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            color = QColor(self.shadow_color)
            color.setAlphaF(1.0)
            sp.fillRect(shadow_img.rect(), color)
            sp.end()
            self._shadow_cache = shadow_img
            self._shadow_cache_key = cache_key

        off_x, off_y = self._shadow_offset()
        ox = off_x * zoom_x
        oy = off_y * zoom_y
        blur = self.shadow_size * (zoom_x + zoom_y) * 0.5
        # Spread reduces the soft zone: at 100% the shadow is fully solid
        solid_fraction = max(0.0, min(1.0, self.shadow_spread / 100.0))
        src_rect = QRectF(self._shadow_cache.rect())

        if blur <= 0 or solid_fraction >= 1.0:
            painter.setOpacity(self.shadow_opacity)
            painter.drawImage(QRectF(sx + ox, sy + oy, dst_w, dst_h), self._shadow_cache, src_rect)
            painter.setOpacity(1.0)
            return

        num_passes = 12
        soft_blur = blur * (1.0 - solid_fraction)
        alpha_per_pass = self.shadow_opacity / (num_passes + 1)
        for i in range(num_passes):
            angle = 2.0 * math.pi * i / num_passes
            dx = math.cos(angle) * soft_blur * 0.5
            dy = math.sin(angle) * soft_blur * 0.5
            painter.setOpacity(alpha_per_pass)
            painter.drawImage(QRectF(sx + ox + dx, sy + oy + dy, dst_w, dst_h), self._shadow_cache, src_rect)

        painter.setOpacity(self.shadow_opacity * 0.5)
        painter.drawImage(QRectF(sx + ox, sy + oy, dst_w, dst_h), self._shadow_cache, src_rect)
        painter.setOpacity(1.0)

    def _paint_inner_shadow(
        self,
        painter: QPainter,
        composite: QImage,
        sx: float,
        sy: float,
        scale_x: float,
        scale_y: float,
        dst_w: float,
        dst_h: float,
    ) -> None:
        """Render inner shadow by inverting alpha and clipping to content."""
        w, h = composite.width(), composite.height()

        inverted = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        if inverted.isNull():
            return
        inverted.fill(QColor(self.shadow_color))
        ip = QPainter(inverted)
        ip.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        ip.drawImage(0, 0, composite)
        ip.end()

        off_x, off_y = self._shadow_offset()
        ox = off_x * scale_x
        oy = off_y * scale_y
        blur = self.shadow_size * (scale_x + scale_y) * 0.5
        solid_fraction = max(0.0, min(1.0, self.shadow_spread / 100.0))

        shadow_result = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        if shadow_result.isNull():
            return
        shadow_result.fill(Qt.GlobalColor.transparent)
        sp = QPainter(shadow_result)

        if blur <= 0 or solid_fraction >= 1.0:
            sp.setOpacity(self.shadow_opacity)
            sp.drawImage(QPointF(ox, oy), inverted)
        else:
            num_passes = 12
            soft_blur = blur * (1.0 - solid_fraction)
            alpha_per_pass = self.shadow_opacity / (num_passes + 1)
            for i in range(num_passes):
                angle = 2.0 * math.pi * i / num_passes
                dx = math.cos(angle) * soft_blur * 0.5
                dy = math.sin(angle) * soft_blur * 0.5
                sp.setOpacity(alpha_per_pass)
                sp.drawImage(QPointF(ox + dx, oy + dy), inverted)
            sp.setOpacity(self.shadow_opacity * 0.5)
            sp.drawImage(QPointF(ox, oy), inverted)

        sp.setOpacity(1.0)
        sp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        sp.drawImage(0, 0, composite)
        sp.end()

        painter.drawImage(QRectF(sx, sy, dst_w, dst_h), shadow_result, QRectF(shadow_result.rect()))

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "draw"
        data["channels"] = [ch.serialize() for ch in self.channels]
        # Always save all effect fields so disabled settings survive round-trip
        data["outline_enabled"] = self.outline_enabled
        data["outline_color"] = self.outline_color
        data["outline_width"] = round(self.outline_width, 2)
        data["shadow_enabled"] = self.shadow_enabled
        data["shadow_type"] = self.shadow_type
        data["shadow_color"] = self.shadow_color
        data["shadow_opacity"] = round(self.shadow_opacity, 2)
        data["shadow_angle"] = round(self.shadow_angle, 1)
        data["shadow_distance"] = round(self.shadow_distance, 1)
        data["shadow_spread"] = round(self.shadow_spread, 1)
        data["shadow_size"] = round(self.shadow_size, 1)
        data["bevel_enabled"] = self.bevel_enabled
        data["bevel_type"] = self.bevel_type
        data["bevel_angle"] = round(self.bevel_angle, 1)
        data["bevel_size"] = round(self.bevel_size, 2)
        data["bevel_depth"] = round(self.bevel_depth, 3)
        data["bevel_highlight_color"] = self.bevel_highlight_color
        data["bevel_highlight_opacity"] = round(self.bevel_highlight_opacity, 2)
        data["bevel_shadow_color"] = self.bevel_shadow_color
        data["bevel_shadow_opacity"] = round(self.bevel_shadow_opacity, 2)
        data["structure_enabled"] = self.structure_enabled
        if self.structure_texture_id is not None:
            data["structure_texture_id"] = self.structure_texture_id
        data["structure_scale"] = round(self.structure_scale, 3)
        data["structure_depth"] = round(self.structure_depth, 1)
        data["structure_invert"] = self.structure_invert
        return data

    @classmethod
    def deserialize(cls, data: dict) -> DrawLayer:
        layer = cls(data.get("name", "Draw"))
        layer._base_deserialize(data)
        layer.outline_enabled = data.get("outline_enabled", False)
        layer.outline_color = data.get("outline_color", "#000000")
        layer.outline_width = data.get("outline_width", 2.0)
        layer.shadow_enabled = data.get("shadow_enabled", False)
        layer.shadow_type = data.get("shadow_type", "outer")
        layer.shadow_color = data.get("shadow_color", "#000000")
        layer.shadow_opacity = data.get("shadow_opacity", 0.5)
        layer.shadow_angle = data.get("shadow_angle", 120.0)
        layer.shadow_distance = data.get("shadow_distance", 5.0)
        layer.shadow_spread = data.get("shadow_spread", 0.0)
        layer.shadow_size = data.get("shadow_size", data.get("shadow_blur_radius", 5.0))
        layer.bevel_enabled = data.get("bevel_enabled", False)
        layer.bevel_type = data.get("bevel_type", "inner")
        layer.bevel_angle = data.get("bevel_angle", 120.0)
        layer.bevel_size = data.get("bevel_size", 3.0)
        layer.bevel_depth = data.get("bevel_depth", 0.5)
        layer.bevel_highlight_color = data.get("bevel_highlight_color", "#ffffff")
        layer.bevel_highlight_opacity = data.get("bevel_highlight_opacity", 0.75)
        layer.bevel_shadow_color = data.get("bevel_shadow_color", "#000000")
        layer.bevel_shadow_opacity = data.get("bevel_shadow_opacity", 0.75)
        layer.structure_enabled = data.get("structure_enabled", False)
        layer.structure_texture_id = data.get("structure_texture_id", None)
        layer.structure_scale = data.get("structure_scale", 1.0)
        layer.structure_depth = data.get("structure_depth", 50.0)
        layer.structure_invert = data.get("structure_invert", False)
        for ch_data in data.get("channels", []):
            layer.channels.append(DrawChannel.deserialize(ch_data))
        # Note: old format with "strokes" key is silently ignored (incompatible).
        # Pre-build the managed cache so loaded projects pan/zoom instantly.
        layer.build_full_cache()
        return layer
