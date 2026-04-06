"""Central map canvas widget with zoom, pan, and layer rendering."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import QWidget

from app.hex.hex_math import Hex, pixel_to_hex
from app.layers.fill_layer import FillLayer
from app.layers.hexside_layer import HexsideLayer
from app.layers.sketch_layer import SketchLayer
from app.layers.text_layer import TextLayer
from app.models.project import Project

# Minimum pixel distance before right-click drag becomes a pan
_RIGHT_DRAG_THRESHOLD = 5.0


class CanvasWidget(QWidget):
    ZOOM_MIN = 0.05
    ZOOM_MAX = 10.0
    ZOOM_FACTOR = 1.15

    viewport_changed = Signal()

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self._project = project
        self._tool_manager = None

        # Viewport state
        self._scale: float = 1.0
        self._pan_offset = QPointF(0, 0)
        self._is_panning: bool = False
        self._last_pan_pos = QPointF()
        self._hover_hex: Hex | None = None

        # Right-click pan state
        self._right_press_pos: QPointF | None = None
        self._right_is_panning: bool = False

        # B-key peek: layer temporarily hidden while B is held
        self._peek_hidden_layer = None

        # Fill context cache: rebuilt only when a FillLayer's data/visibility changes.
        # Key = tuple of (id, visible, _cache_dirty) for each FillLayer in stack order.
        self._fill_context_key: tuple = ()
        self._cached_fill_colors: dict[tuple[int, int], str] = {}
        self._cached_fill_textures: dict = {}
        self._cached_dot_overrides: dict = {}
        self._cached_coord_overrides: dict = {}
        # Incremented only when _cached_dot_overrides or _cached_coord_overrides
        # actually change.  The grid cache key uses this version instead of the
        # full _fill_context_key so that ordinary fill edits (hex colours) don't
        # invalidate the grid cache.
        self._dot_overrides_version: int = 0

        # Grid pixmap cache: rebuilt when config fields or fill context change.
        self._grid_cache_pixmap: QPixmap | None = None
        self._grid_cache_key: tuple = ()

        # Screen-resolution pixmap cache for layers that cannot use the world-res path:
        #   • cacheable=False layers (AssetLayer, DrawLayer*), and
        #   • cacheable=True layers when world area > 90 M px (can_cache=False).
        # Maps layer_id -> (pixmap, scale_rounded).  Invalidated via _cache_dirty flag.
        # (*DrawLayer has _managed_cache_pixmap and bypasses this dict.)
        self._screen_layer_caches: dict[str, tuple[QPixmap, float]] = {}

        # During active zooming, skip all screen-resolution cache rebuilds and render
        # directly.  The timer fires 300 ms after the last wheel event to trigger a
        # single rebuild of the grid and all screen-res layer caches.
        self._grid_zoom_active: bool = False
        self._grid_zoom_timer = QTimer(self)
        self._grid_zoom_timer.setSingleShot(True)
        self._grid_zoom_timer.setInterval(200)
        self._grid_zoom_timer.timeout.connect(self._on_grid_zoom_settled)

        # Deferred layer cache rebuild: when a layer is marked dirty, render it
        # directly (viewport-culled, screen-bounded → fast) instead of immediately
        # rebuilding the full-map pixmap cache.  A 200 ms debounce timer triggers
        # the actual cache rebuild once editing pauses.  This eliminates the
        # perceived lag after each object placement on large maps because direct
        # rendering is bounded by screen pixels (~2M) while the full-map cache
        # can be 10-15M+ pixels.
        self._layer_cache_deferred: bool = False
        self._layer_cache_timer = QTimer(self)
        self._layer_cache_timer.setSingleShot(True)
        self._layer_cache_timer.setInterval(200)
        self._layer_cache_timer.timeout.connect(self._on_layer_cache_settled)

        # Cached Layout object — rebuilt only when grid config changes.
        self._cached_layout = None
        self._cached_layout_key: tuple = ()

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)

    def set_tool_manager(self, tool_manager):
        self._tool_manager = tool_manager

    def set_cache_rebuild_delay(self, ms: int) -> None:
        """Set the deferred cache rebuild delay in milliseconds.

        0 disables deferral (always rebuild immediately).
        """
        self._layer_cache_timer.setInterval(max(0, ms))

    def set_zoom_settle_delay(self, ms: int) -> None:
        """Set the debounce delay after zoom events in milliseconds."""
        self._grid_zoom_timer.setInterval(max(50, ms))

    def reset_caches(self) -> None:
        """Clear all render caches. Call after loading a new project."""
        self._fill_context_key = ()
        self._cached_fill_colors = {}
        self._cached_fill_textures = {}
        self._cached_dot_overrides = {}
        self._cached_coord_overrides = {}
        self._grid_cache_pixmap = None
        self._grid_cache_key = ()
        self._screen_layer_caches.clear()
        self._layer_cache_deferred = False
        self._layer_cache_timer.stop()
        self._cached_layout = None
        self._cached_layout_key = ()

    # --- Coordinate transforms ---

    def screen_to_world(self, screen_pos: QPointF) -> QPointF:
        return (screen_pos - self._pan_offset) / self._scale

    def world_to_screen(self, world_pos: QPointF) -> QPointF:
        return world_pos * self._scale + self._pan_offset

    def get_visible_world_rect(self) -> QRectF:
        top_left = self.screen_to_world(QPointF(0, 0))
        bottom_right = self.screen_to_world(QPointF(self.width(), self.height()))
        return QRectF(top_left, bottom_right)

    def _get_layout(self):
        """Return a cached Layout, rebuilt only when grid config changes."""
        key = self._project.grid_config._bounds_key()
        if self._cached_layout is None or self._cached_layout_key != key:
            self._cached_layout = self._project.grid_config.create_layout()
            self._cached_layout_key = key
        return self._cached_layout

    def _world_hex(self, world_pos: QPointF) -> Hex:
        layout = self._get_layout()
        return pixel_to_hex(layout, world_pos.x(), world_pos.y())

    # --- Zoom helpers ---

    def zoom_to_fit(self):
        """Zoom and pan so the entire map is visible."""
        bounds = self._project.grid_config.get_effective_bounds()
        if bounds.isEmpty():
            return

        margin = 40
        available_w = self.width() - margin * 2
        available_h = self.height() - margin * 2

        if available_w <= 0 or available_h <= 0:
            return

        scale_x = available_w / bounds.width()
        scale_y = available_h / bounds.height()
        self._scale = min(scale_x, scale_y)
        self._scale = max(self.ZOOM_MIN, min(self.ZOOM_MAX, self._scale))

        center = bounds.center()
        screen_center = QPointF(self.width() / 2, self.height() / 2)
        self._pan_offset = screen_center - center * self._scale

        self.update()

    def center_on_world(self, world_x: float, world_y: float):
        """Pan so the given world coordinate is centered on screen."""
        screen_center = QPointF(self.width() / 2, self.height() / 2)
        self._pan_offset = screen_center - QPointF(world_x, world_y) * self._scale
        self.update()

    # --- Paint ---

    def _make_grid_key(self, config, map_bounds: QRectF) -> tuple:
        """Build a cache key that captures all grid renderer visual parameters."""
        return (
            round(self._scale, 3),            # cache is screen-resolution; must rebuild on zoom
            self._dot_overrides_version,      # only changes when center-dot colours change
            config.show_grid,
            config.show_center_dots,
            config.show_coordinates,
            config.line_width,
            config.grid_style,
            config.edge_color.rgba(),
            config.center_dot_color.rgba(),
            config.center_dot_size,
            config.center_dot_outline,
            config.center_dot_outline_width,
            config.center_dot_outline_color.rgba(),
            config.coord_format,
            config.coord_position,
            config.coord_font_scale,
            config.coord_offset_y,
            config.coord_start_one,
            config.show_border,
            config.border_color.rgba(),
            config.megahex_enabled,
            config.megahex_radius,
            config.megahex_mode,
            config.megahex_color.rgba(),
            config.megahex_width,
            config.megahex_offset_q,
            config.megahex_offset_r,
            int(map_bounds.x()),
            int(map_bounds.y()),
            int(map_bounds.width()),
            int(map_bounds.height()),
        )

    def _paint_layer(
        self, painter: QPainter, layer, map_bounds: QRectF,
        viewport: QRectF, layout, can_cache: bool,
        grid_clip: QPainterPath | None = None,
    ) -> None:
        """Paint a single layer with pixmap caching.

        Cacheable layers use a world-resolution cache (zoom-invariant, fast for pan).
        Non-cacheable layers (e.g. AssetLayer) get a screen-resolution cache that
        stays sharp at any zoom level, invalidated only when data or scale changes.
        Direct render is the final fallback when both cache types exceed their limits.
        """
        MAX_CACHE_PIXELS = 100_000_000
        # Screen-res cache limit is lower: during build, shadow layers may allocate
        # up to 3× this in QImage memory at the same time.
        MAX_SCREEN_CACHE_PIXELS = 25_000_000

        # Fast-path for layers that manage their own full QPixmap cache
        # (e.g. DrawLayer after a stroke completes). Bypasses the standard
        # cache rebuild and renders instantly during pan/zoom.
        _gfx = getattr(layer, '_gfx_effects_enabled', True)
        managed_pm = getattr(layer, '_managed_cache_pixmap', None)
        if managed_pm is not None:
            # The managed cache contains only the raw channel composite — layer
            # effects (outline/shadow) are NOT baked in.  Skip the fast-path
            # when effects are active so paint() → _draw_composite_screen()
            # can render them correctly.
            has_effects = (getattr(layer, 'outline_enabled', False)
                          or (_gfx and getattr(layer, 'shadow_enabled', False)))
            if has_effects:
                managed_pm = None
            else:
                managed_bounds = getattr(layer, '_managed_cache_bounds')
                # Verify the managed cache covers the visible portion of the layer.
                # After zoom-out the viewport may extend beyond the cached region;
                # in that case invalidate the managed cache and fall through to the
                # normal render path so the full visible area is painted.
                calc_bounds = getattr(layer, '_calculate_bounds', None)
                if calc_bounds is not None:
                    layer_bounds = calc_bounds()
                    visible_needed = viewport.intersected(layer_bounds)
                    if not visible_needed.isEmpty() and not managed_bounds.contains(visible_needed):
                        layer._managed_cache_pixmap = None
                        managed_pm = None  # fall through below
            if managed_pm is not None:
                painter.save()
                painter.setOpacity(layer.opacity)
                # Compute screen-space destination rect from world bounds.
                xf = painter.worldTransform()
                # Keep _last_paint_zoom current even when paint() is bypassed
                # by the managed-cache fast path.  Otherwise build_full_cache()
                # (called from draw_tool on Shift+click lines) would use a
                # stale zoom and produce a blurry cache.
                if hasattr(layer, '_last_paint_zoom'):
                    layer._last_paint_zoom = (
                        round(max(0.01, abs(xf.m11())), 4),
                        round(max(0.01, abs(xf.m22())), 4),
                    )
                sx = managed_bounds.x() * xf.m11() + xf.dx()
                sy = managed_bounds.y() * xf.m22() + xf.dy()
                dst_w = managed_bounds.width() * abs(xf.m11())
                dst_h = managed_bounds.height() * abs(xf.m22())
                # Set clip with world transform active so Qt bakes it into device
                # coordinates; it stays correct after resetTransform() below.
                if grid_clip is not None:
                    painter.setClipPath(grid_clip)
                painter.resetTransform()
                # When managed pixmap is at native screen resolution, draw
                # pixel-aligned (no bilinear sub-pixel softening from
                # SmoothPixmapTransform).  Matches _draw_composite_screen()'s
                # native=True path to keep hard brush strokes crisp.
                if (abs(managed_pm.width() - dst_w) < 1.5
                        and abs(managed_pm.height() - dst_h) < 1.5):
                    painter.drawPixmap(round(sx), round(sy), managed_pm)
                else:
                    painter.drawPixmap(
                        QRectF(sx, sy, dst_w, dst_h), managed_pm, QRectF(managed_pm.rect()),
                    )
                painter.restore()
                return

        # Effects cache fast-path: DrawLayer with outline/shadow active.
        # The managed cache is bypassed when effects are enabled (it contains only
        # the raw composite, not the baked outline/shadow).  Instead we use a
        # full-layer screen-res pixmap with effects baked in so panning is O(1).
        has_layer_effects = (getattr(layer, 'outline_enabled', False)
                             or (_gfx and getattr(layer, 'shadow_enabled', False)))
        if has_layer_effects and hasattr(layer, '_managed_cache_pixmap'):
            effects_pm = getattr(layer, '_effects_cache_pixmap', None)
            current_scale = round(self._scale, 3)

            # During active zoom: scale the stale effects cache (O(1) GPU op).
            if self._grid_zoom_active and effects_pm is not None and not layer._cache_dirty:
                eff_bounds = layer._effects_cache_bounds
                screen_tl = self.world_to_screen(eff_bounds.topLeft())
                dst_w = eff_bounds.width() * self._scale
                dst_h = eff_bounds.height() * self._scale
                painter.save()
                painter.setOpacity(layer.opacity)
                if grid_clip is not None:
                    painter.setClipPath(grid_clip)
                painter.resetTransform()
                painter.drawPixmap(
                    QRectF(screen_tl.x(), screen_tl.y(), dst_w, dst_h),
                    effects_pm,
                    QRectF(effects_pm.rect()),
                )
                painter.restore()
                return

            cache_hit = (
                effects_pm is not None
                and layer._effects_cache_scale == current_scale
                and not layer._cache_dirty
            )

            if not cache_hit and not self._grid_zoom_active:
                calc_bounds = getattr(layer, '_calculate_bounds', None)
                if calc_bounds is not None:
                    eff_layer_bounds = calc_bounds()
                    if not eff_layer_bounds.isEmpty():
                        sw = max(1, int(eff_layer_bounds.width() * current_scale))
                        sh = max(1, int(eff_layer_bounds.height() * current_scale))
                        if sw * sh <= MAX_SCREEN_CACHE_PIXELS:
                            eff_pm = QPixmap(sw, sh)
                            if not eff_pm.isNull():
                                eff_pm.fill(Qt.GlobalColor.transparent)
                                cp = QPainter(eff_pm)
                                cp.setRenderHint(QPainter.RenderHint.Antialiasing)
                                cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                                cp.scale(current_scale, current_scale)
                                cp.translate(-eff_layer_bounds.x(), -eff_layer_bounds.y())
                                if grid_clip is not None:
                                    cp.setClipPath(grid_clip)
                                layer.paint(cp, eff_layer_bounds, layout)
                                cp.end()
                                layer._effects_cache_pixmap = eff_pm
                                layer._effects_cache_bounds = eff_layer_bounds
                                layer._effects_cache_scale = current_scale
                                layer._cache_dirty = False
                                effects_pm = eff_pm
                                cache_hit = True

            if cache_hit and effects_pm is not None:
                eff_bounds = layer._effects_cache_bounds
                screen_tl = self.world_to_screen(eff_bounds.topLeft())
                painter.save()
                painter.setOpacity(layer.opacity)
                if grid_clip is not None:
                    painter.setClipPath(grid_clip)
                painter.resetTransform()
                painter.drawPixmap(screen_tl, effects_pm)
                painter.restore()
                return
            # Fall through to direct render if layer is too large to cache.

        # Some layers (e.g. AssetLayer) set cacheable=False to opt out of
        # world-resolution caching (which would blur raster images on zoom-in).
        cache_eligible = can_cache and getattr(layer, 'cacheable', True)

        # World-resolution cache hit: valid as long as data hasn't changed.
        cache_valid = (
            cache_eligible
            and not layer._cache_dirty
            and layer._cache_pixmap is not None
        )

        if cache_valid:
            painter.save()
            painter.setOpacity(layer.opacity)
            painter.drawPixmap(layer._cache_bounds.topLeft(), layer._cache_pixmap)
            painter.restore()
            return

        # ── Deferred cache rebuild ────────────────────────────────────
        # When a layer is dirty, render directly (viewport-culled, bounded
        # by screen pixels) instead of rebuilding the full-map pixmap cache
        # right away.  A debounce timer triggers the real rebuild once the
        # user pauses editing.  Disabled when interval is 0.
        if (layer._cache_dirty
                and not self._grid_zoom_active
                and self._layer_cache_timer.interval() > 0):
            if self._layer_cache_timer.isActive():
                # Still deferring — render directly, restart debounce
                self._layer_cache_timer.start()
                painter.save()
                painter.setOpacity(layer.opacity)
                if grid_clip is not None:
                    painter.setClipPath(grid_clip)
                layer.paint(painter, viewport, layout)
                painter.restore()
                return
            if self._layer_cache_deferred:
                # Timer just fired — fall through to rebuild caches below
                pass
            else:
                # First dirty encounter — enter deferred mode
                self._layer_cache_deferred = True
                self._layer_cache_timer.start()
                painter.save()
                painter.setOpacity(layer.opacity)
                if grid_clip is not None:
                    painter.setClipPath(grid_clip)
                layer.paint(painter, viewport, layout)
                painter.restore()
                return

        # World-resolution cache build.
        if cache_eligible:
            w = max(1, int(map_bounds.width()))
            h = max(1, int(map_bounds.height()))
            if w * h <= MAX_CACHE_PIXELS:
                cache_pm = QPixmap(w, h)
                if not cache_pm.isNull():
                    cache_pm.fill(Qt.GlobalColor.transparent)
                    cp = QPainter(cache_pm)
                    cp.setRenderHint(QPainter.RenderHint.Antialiasing)
                    cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    cp.translate(-map_bounds.x(), -map_bounds.y())
                    if grid_clip is not None:
                        cp.setClipPath(grid_clip)
                    layer.paint(cp, map_bounds, layout)
                    cp.end()

                    layer._cache_pixmap = cache_pm
                    layer._cache_bounds = QRectF(map_bounds)
                    layer._cache_dirty = False

                    painter.save()
                    painter.setOpacity(layer.opacity)
                    painter.drawPixmap(map_bounds.topLeft(), cache_pm)
                    painter.restore()
                    return
                # Null pixmap (GPU memory exhausted): fall through to screen-res.

        # Screen-resolution cache for layers that cannot use the world-res path:
        #  • cacheable=False layers (e.g. AssetLayer): always use screen-res
        #  • cacheable=True layers when can_cache=False (e.g. FillLayer on large
        #    maps with hex_size ≥ ~28 mm where world area > 90 M px): world-res
        #    pixmap would exceed memory budget, so fall back to screen-res which
        #    is bounded by the physical screen size (≈ screen_w × screen_h px²).
        # DrawLayer is excluded: it manages its own _managed_cache_pixmap and
        # uses a viewport-only render during active strokes (handled above).
        #
        # The full-map screen-res pixmap means pan never requires a rebuild.
        # During active zoom the stale cache is drawn scaled to the new zoom
        # (O(1) GPU op), identical to the grid stale-cache technique; the cache
        # is rebuilt once after zooming stops (_on_grid_zoom_settled).
        if not hasattr(layer, '_managed_cache_pixmap'):
            current_scale = round(self._scale, 3)
            cached = self._screen_layer_caches.get(layer.id)
            cache_hit = (
                cached is not None
                and cached[1] == current_scale
                and not layer._cache_dirty
            )

            # During zoom animation: scale the stale cache to the current zoom.
            # This avoids per-hex Python rendering on every wheel tick at any
            # map/hex size, matching the behaviour of the grid stale-cache path.
            if self._grid_zoom_active and cached is not None and not layer._cache_dirty:
                screen_tl = self.world_to_screen(map_bounds.topLeft())
                dst_w = map_bounds.width() * self._scale
                dst_h = map_bounds.height() * self._scale
                painter.save()
                painter.resetTransform()
                painter.setOpacity(layer.opacity)
                painter.drawPixmap(
                    QRectF(screen_tl.x(), screen_tl.y(), dst_w, dst_h),
                    cached[0],
                    QRectF(cached[0].rect()),
                )
                painter.restore()
                return

            if not cache_hit and not self._grid_zoom_active:
                sw = max(1, int(map_bounds.width() * current_scale))
                sh = max(1, int(map_bounds.height() * current_scale))
                if sw * sh <= MAX_SCREEN_CACHE_PIXELS:
                    screen_pm = QPixmap(sw, sh)
                    if not screen_pm.isNull():
                        screen_pm.fill(Qt.GlobalColor.transparent)
                        cp = QPainter(screen_pm)
                        cp.setRenderHint(QPainter.RenderHint.Antialiasing)
                        cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                        cp.scale(current_scale, current_scale)
                        cp.translate(-map_bounds.x(), -map_bounds.y())
                        if grid_clip is not None:
                            cp.setClipPath(grid_clip)
                        layer.paint(cp, map_bounds, layout)
                        cp.end()
                        self._screen_layer_caches[layer.id] = (screen_pm, current_scale)
                        layer._cache_dirty = False
                        cached = self._screen_layer_caches[layer.id]
                        cache_hit = True

            if cache_hit and cached is not None:
                screen_tl = self.world_to_screen(map_bounds.topLeft())
                painter.save()
                painter.resetTransform()
                painter.setOpacity(layer.opacity)
                painter.drawPixmap(screen_tl, cached[0])
                painter.restore()
                return

        # No cache (map too large at current zoom) – render directly with viewport culling.
        painter.save()
        painter.setOpacity(layer.opacity)
        if grid_clip is not None:
            painter.setClipPath(grid_clip)
        layer.paint(painter, viewport, layout)
        painter.restore()

    def _paint_global_lighting(self, painter: QPainter, config) -> None:
        """Draw a semi-transparent color tint over the hex area (not the border zone)."""
        if not config.global_lighting_enabled or config.global_lighting_opacity <= 0:
            return
        color = QColor(config.global_lighting_color)
        color.setAlpha(config.global_lighting_opacity)
        hex_path = config.get_grid_clip_path()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(hex_path)
        painter.restore()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 1. Background
        painter.fillRect(self.rect(), self._project.grid_config.canvas_bg_color)

        # 2. Apply world transform
        painter.translate(self._pan_offset)
        painter.scale(self._scale, self._scale)

        viewport = self.get_visible_world_rect()
        layout = self._get_layout()
        config = self._project.grid_config

        # 3. Grid clip path (applied selectively per layer, not globally)
        grid_clip = config.get_grid_clip_path()

        # In half-hex mode, hard-clip the entire canvas to the boundary rectangle so
        # that partial edge hexes, grid lines, and all layers are invisible outside it.
        if config.half_hexes:
            painter.setClipPath(grid_clip)

        # 4. Border fill (before layers so hex fills aren't covered)
        self._project.grid_renderer.paint_border_fill(painter, layout, config)

        # 5. Paint layers bottom to top (with pixmap caching)
        map_bounds = config.get_effective_bounds()
        max_cache_pixels = 100_000_000
        can_cache = (map_bounds.width() * map_bounds.height()) <= max_cache_pixels

        # Fill context cache: only rebuild when a FillLayer's data or visibility changes.
        # Key captures (id, visible, dirty) for every FillLayer – cheap O(n_layers) check.
        fill_key = tuple(
            (l.id, l.visible, l._cache_dirty)
            for l in self._project.layer_stack
            if isinstance(l, FillLayer)
        )
        if fill_key != self._fill_context_key:
            self._fill_context_key = fill_key
            fill_colors: dict[tuple[int, int], str] = {}
            fill_textures: dict[tuple[int, int], "FillLayer.HexTexture"] = {}
            for layer in self._project.layer_stack:
                if layer.visible and isinstance(layer, FillLayer):
                    for h, color in layer.fills.items():
                        fill_colors[(h.q, h.r)] = color.name()
                    for h, tex in layer.textures.items():
                        fill_textures[(h.q, h.r)] = tex
            self._cached_fill_colors = fill_colors
            self._cached_fill_textures = fill_textures
            # Dot overrides: recompute and bump version only when they actually change.
            # This keeps the grid cache stable during ordinary fill edits (hex colours).
            new_dot_overrides: dict = {}
            new_coord_overrides: dict = {}
            for layer in self._project.layer_stack:
                if layer.visible and hasattr(layer, 'dot_colors'):
                    new_dot_overrides.update(layer.dot_colors)
                if layer.visible and hasattr(layer, 'coord_colors'):
                    new_coord_overrides.update(layer.coord_colors)
            if (new_dot_overrides != self._cached_dot_overrides
                    or new_coord_overrides != self._cached_coord_overrides):
                self._dot_overrides_version += 1
            self._cached_dot_overrides = new_dot_overrides
            self._cached_coord_overrides = new_coord_overrides
            # Propagate fill context to HexsideLayers so their next paint is correct
            for layer in self._project.layer_stack:
                if isinstance(layer, HexsideLayer):
                    layer.set_fill_context(
                        self._cached_fill_colors, self._cached_fill_textures
                    )

        over_grid_layers: list[SketchLayer | TextLayer] = []
        for layer in self._project.layer_stack:
            if not layer.visible:
                continue
            # SketchLayer / TextLayer with over-grid objects need split rendering
            if isinstance(layer, (SketchLayer, TextLayer)) and layer.has_over_grid_objects:
                over_grid_layers.append(layer)
                # Paint only below-grid objects (no pixmap cache for split layers)
                painter.save()
                painter.setOpacity(layer.opacity)
                layer.paint_filtered(painter, viewport, layout, over_grid=False)
                painter.restore()
                continue
            # TextLayer: always render directly on the scaled painter so vector text stays crisp.
            # The pixmap cache renders at world scale then upsamples as a raster image, blurring text.
            if isinstance(layer, TextLayer):
                painter.save()
                painter.setOpacity(layer.opacity)
                layer.paint(painter, viewport, layout)
                painter.restore()
                continue
            layer_clip = grid_clip if layer.clip_to_grid else None
            self._paint_layer(painter, layer, map_bounds, viewport, layout, can_cache, layer_clip)

        # 6. Global lighting tint (over layers, under grid)
        self._paint_global_lighting(painter, config)

        # 7. Paint hex grid on top (cached as a screen-resolution QPixmap).
        # Screen-resolution is critical: cosmetic pens (1px regardless of zoom) are
        # pre-rendered at the correct device-pixel size, so lines stay crisp at any
        # zoom level.
        # During active zooming (_grid_zoom_active) the stale cache is drawn scaled
        # to the current zoom (O(1) GPU op) instead of triggering expensive per-hex
        # Python rendering.  The cache is rebuilt once 300 ms after the last zoom
        # event (_on_grid_zoom_settled).
        if config.show_grid:
            if self._grid_zoom_active:
                if self._grid_cache_pixmap is not None:
                    # Scale the stale cache to the current zoom level.
                    # GPU-accelerated O(1) operation: no per-hex Python cost at any
                    # map size.  Slightly interpolated during the gesture; rebuilt
                    # pixel-sharp once zoom settles.
                    screen_tl = self.world_to_screen(map_bounds.topLeft())
                    dst_w = map_bounds.width() * self._scale
                    dst_h = map_bounds.height() * self._scale
                    painter.save()
                    painter.resetTransform()
                    painter.drawPixmap(
                        QRectF(screen_tl.x(), screen_tl.y(), dst_w, dst_h),
                        self._grid_cache_pixmap,
                        QRectF(self._grid_cache_pixmap.rect()),
                    )
                    painter.restore()
                else:
                    # No cache yet (first zoom ever): fall back to direct render.
                    self._project.grid_renderer.paint(
                        painter, viewport, layout, config, self._cached_dot_overrides,
                        self._cached_coord_overrides
                    )
            else:
                # Normal path: use/build screen-resolution cache
                grid_key = self._make_grid_key(config, map_bounds)
                if grid_key != self._grid_cache_key or self._grid_cache_pixmap is None:
                    self._grid_cache_key = grid_key
                    # Build at screen-pixel resolution so cosmetic pens render correctly.
                    # 16M px limit keeps the pixmap small enough to allocate quickly and
                    # draw without stressing GPU memory.  Above the limit the fallback
                    # direct-render path uses viewport culling (only visible hexes),
                    # which is fast because few hexes are on screen at high zoom.
                    w = max(1, int(map_bounds.width() * self._scale))
                    h = max(1, int(map_bounds.height() * self._scale))
                    if w * h <= 16_000_000:
                        grid_pm = QPixmap(w, h)
                        grid_pm.fill(Qt.GlobalColor.transparent)
                        gp = QPainter(grid_pm)
                        gp.setRenderHint(QPainter.RenderHint.Antialiasing)
                        gp.scale(self._scale, self._scale)
                        gp.translate(-map_bounds.x(), -map_bounds.y())
                        self._project.grid_renderer.paint(
                            gp, map_bounds, layout, config, self._cached_dot_overrides,
                            self._cached_coord_overrides
                        )
                        gp.end()
                        self._grid_cache_pixmap = grid_pm
                    else:
                        self._grid_cache_pixmap = None

                if self._grid_cache_pixmap is not None:
                    # Draw at screen position without world transform.
                    # Device-space clip (half-hex etc.) is preserved across resetTransform().
                    screen_tl = self.world_to_screen(map_bounds.topLeft())
                    painter.save()
                    painter.resetTransform()
                    painter.drawPixmap(screen_tl, self._grid_cache_pixmap)
                    painter.restore()
                else:
                    # Too large to cache at this zoom: direct render with viewport culling.
                    # At zoom levels where the cache exceeds 16M px, the viewport shows
                    # only a small fraction of the map, so visible_hexes is small → fast.
                    self._project.grid_renderer.paint(
                        painter, viewport, layout, config, self._cached_dot_overrides,
                        self._cached_coord_overrides
                    )

        # 8. Paint over-grid objects (above grid)
        for layer in over_grid_layers:
            painter.save()
            painter.setOpacity(layer.opacity)
            layer.paint_filtered(painter, viewport, layout, over_grid=True)
            painter.restore()

        # 9. Paint tool overlay
        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.paint_overlay(
                painter, viewport, layout, self._hover_hex
            )

        painter.end()

        # Reset deferred-rebuild flag after all layers had the chance to rebuild.
        if self._layer_cache_deferred and not self._layer_cache_timer.isActive():
            self._layer_cache_deferred = False

        # M10: defer emission to avoid re-entrant repaint if a handler calls update().
        # Only emit when the viewport actually changed (pan/zoom/resize) to avoid
        # unnecessary minimap redraws during pure hover updates.
        current_vp = (round(viewport.x(), 1), round(viewport.y(), 1),
                      round(viewport.width(), 1), round(viewport.height(), 1))
        if current_vp != getattr(self, '_last_emitted_vp', None):
            self._last_emitted_vp = current_vp
            QTimer.singleShot(0, self.viewport_changed.emit)

    # --- Mouse handling ---

    def mousePressEvent(self, event: QMouseEvent):
        # Middle mouse: pan
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._last_pan_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        # Right mouse: defer decision (click vs drag-pan)
        if event.button() == Qt.MouseButton.RightButton:
            self._right_press_pos = event.position()
            self._right_is_panning = False
            return

        # Left mouse: forward to tool
        world_pos = self.screen_to_world(event.position())
        hex_coord = self._world_hex(world_pos)

        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.mouse_press(event, world_pos, hex_coord)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        # Middle mouse panning
        if self._is_panning:
            delta = event.position() - self._last_pan_pos
            self._pan_offset += delta
            self._last_pan_pos = event.position()
            self.update()
            return

        # Right mouse: check if drag threshold exceeded -> start panning
        if (event.buttons() & Qt.MouseButton.RightButton) and self._right_press_pos is not None:
            if not self._right_is_panning:
                delta = event.position() - self._right_press_pos
                dist = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
                if dist > _RIGHT_DRAG_THRESHOLD:
                    self._right_is_panning = True
                    self._last_pan_pos = event.position()
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._right_is_panning:
                delta = event.position() - self._last_pan_pos
                self._pan_offset += delta
                self._last_pan_pos = event.position()
                self.update()
                return

        # Normal move: update hover + forward to tool
        world_pos = self.screen_to_world(event.position())
        hex_coord = self._world_hex(world_pos)
        # Only highlight a hover hex when the mouse is inside the grid bounds.
        cfg = self._project.grid_config
        new_hover = hex_coord if cfg.is_valid_hex(hex_coord) else None
        hover_changed = (new_hover != self._hover_hex)
        self._hover_hex = new_hover

        tool_needs_repaint: bool | None = None
        if self._tool_manager and self._tool_manager.active_tool:
            tool_needs_repaint = self._tool_manager.active_tool.mouse_move(
                event, world_pos, hex_coord
            )

        # Repaint when: hover hex changed, tool requests it, or tool uses
        # the legacy None return (backward-compat: always repaint).
        if hover_changed or tool_needs_repaint is not False:
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        # Middle mouse: stop panning
        if event.button() == Qt.MouseButton.MiddleButton and self._is_panning:
            self._is_panning = False
            self._restore_cursor()
            return

        # Right mouse: if was panning, stop; if was click, forward to tool
        if event.button() == Qt.MouseButton.RightButton:
            if self._right_is_panning:
                # Was dragging to pan - just stop
                self._right_is_panning = False
                self._right_press_pos = None
                self._restore_cursor()
                self.update()
                return
            if self._right_press_pos is not None:
                # Was a short click - forward to tool as right-click
                world_pos = self.screen_to_world(self._right_press_pos)
                hex_coord = self._world_hex(world_pos)
                if self._tool_manager and self._tool_manager.active_tool:
                    self._tool_manager.active_tool.mouse_press(event, world_pos, hex_coord)
                    self._tool_manager.active_tool.mouse_release(event, world_pos, hex_coord)
                self._right_press_pos = None
                self.update()
                return

        # Left mouse: forward to tool
        world_pos = self.screen_to_world(event.position())
        hex_coord = self._world_hex(world_pos)

        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.mouse_release(event, world_pos, hex_coord)
        self.update()

    def _restore_cursor(self):
        if self._tool_manager and self._tool_manager.active_tool:
            self.setCursor(self._tool_manager.active_tool.cursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            world_pos = self.screen_to_world(event.position())
            hex_coord = self._world_hex(world_pos)
            if self._tool_manager and self._tool_manager.active_tool:
                self._tool_manager.active_tool.mouse_double_click(event, world_pos, hex_coord)
            self.update()

    def wheelEvent(self, event: QWheelEvent):
        old_world_pos = self.screen_to_world(event.position())

        if event.angleDelta().y() > 0:
            factor = self.ZOOM_FACTOR
        else:
            factor = 1.0 / self.ZOOM_FACTOR

        new_scale = self._scale * factor
        new_scale = max(self.ZOOM_MIN, min(self.ZOOM_MAX, new_scale))

        if new_scale != self._scale:
            self._scale = new_scale
            new_world_pos = self.screen_to_world(event.position())
            delta = new_world_pos - old_world_pos
            self._pan_offset += delta * self._scale
            # Mark grid cache as stale during zoom; rebuild after scrolling stops
            self._grid_zoom_active = True
            self._grid_zoom_timer.start()  # restarts if already running
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_B and not event.isAutoRepeat():
            ls = self._project.layer_stack
            active_idx = ls.active_index
            if active_idx > 0:
                below = ls[active_idx - 1]
                if below.visible:
                    below.visible = False
                    self._peek_hidden_layer = below
                    self.update()
        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.key_press(event)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_B and not event.isAutoRepeat():
            self._restore_peek_layer()
        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.key_release(event)
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._restore_peek_layer()
        super().focusOutEvent(event)

    def _restore_peek_layer(self):
        if self._peek_hidden_layer is not None:
            self._peek_hidden_layer.visible = True
            self._peek_hidden_layer = None
            self.update()

    def _on_layer_cache_settled(self):
        """Called 200 ms after the last layer dirty event.  Triggers cache rebuild."""
        # _layer_cache_deferred stays True as a signal for _paint_layer:
        # "timer fired → rebuild caches now instead of rendering directly."
        self.update()

    def _on_grid_zoom_settled(self):
        """Called 200 ms after the last zoom event. Triggers one clean cache rebuild."""
        self._grid_zoom_active = False
        self._grid_cache_key = ()       # force grid rebuild at the new scale
        self._screen_layer_caches.clear()  # force screen-res layer cache rebuild
        # Clear managed + effects caches (DrawLayer) so they rebuild at the new scale.
        for layer in self._project.layer_stack:
            if getattr(layer, '_managed_cache_pixmap', None) is not None:
                layer._managed_cache_pixmap = None
            if hasattr(layer, '_effects_cache_pixmap'):
                layer._effects_cache_pixmap = None
        self.update()
