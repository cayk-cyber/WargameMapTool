"""Asset layer - places PNG images on the map."""

from __future__ import annotations

import base64
import math

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from app.hex.hex_math import Layout
from app.layers.base_layer import Layer
from app.models.asset_object import AssetObject

_MAX_MASK_DIM = 2048


class _SpatialGrid:
    """Grid-based spatial index for fast asset lookup."""

    def __init__(self, cell_size: float = 256.0):
        self._cell_size = cell_size
        self._cells: dict[tuple[int, int], list[AssetObject]] = {}
        self._asset_cells: dict[str, list[tuple[int, int]]] = {}

    def _cell_keys(self, rect: QRectF) -> list[tuple[int, int]]:
        cs = self._cell_size
        min_c = int(rect.left() // cs)
        max_c = int(rect.right() // cs)
        min_r = int(rect.top() // cs)
        max_r = int(rect.bottom() // cs)
        return [
            (c, r)
            for c in range(min_c, max_c + 1)
            for r in range(min_r, max_r + 1)
        ]

    def insert(self, asset: AssetObject) -> None:
        keys = self._cell_keys(asset.bounding_rect())
        self._asset_cells[asset.id] = keys
        for key in keys:
            if key not in self._cells:
                self._cells[key] = []
            self._cells[key].append(asset)

    def remove(self, asset: AssetObject) -> None:
        keys = self._asset_cells.pop(asset.id, [])
        for key in keys:
            cell = self._cells.get(key)
            if cell:
                cell[:] = [a for a in cell if a.id != asset.id]
                if not cell:
                    del self._cells[key]

    def query_point(self, x: float, y: float) -> list[AssetObject]:
        cs = self._cell_size
        key = (int(x // cs), int(y // cs))
        return list(self._cells.get(key, []))

    def query_rect(self, rect: QRectF) -> set[str]:
        keys = self._cell_keys(rect)
        result: set[str] = set()
        for key in keys:
            cell = self._cells.get(key)
            if cell:
                for asset in cell:
                    result.add(asset.id)
        return result

    def rebuild(self, assets: list[AssetObject]) -> None:
        self._cells.clear()
        self._asset_cells.clear()
        for asset in assets:
            self.insert(asset)

    def clear(self) -> None:
        self._cells.clear()
        self._asset_cells.clear()


class AssetLayer(Layer):
    clip_to_grid = True
    # Assets render sharply when drawn directly via the world transform (no pixmap cache upsampling)
    cacheable = False

    def __init__(self, name: str = "Assets"):
        super().__init__(name)
        self.objects: list[AssetObject] = []
        self._spatial = _SpatialGrid()

        # Layer-level drop shadow
        self.shadow_enabled: bool = False
        self.shadow_type: str = "outer"  # "outer" or "inner"
        self.shadow_color: str = "#000000"
        self.shadow_opacity: float = 0.5
        self.shadow_angle: float = 120.0
        self.shadow_distance: float = 5.0
        self.shadow_spread: float = 0.0
        self.shadow_size: float = 5.0

        # Erase mask (world-pixel coordinates)
        self.mask_image: QImage | None = None
        self._mask_world_offset: tuple[float, float] = (0.0, 0.0)
        self._mask_world_scale: float = 1.0  # mask px = world unit * scale

        # Composite cache (assets-only, without mask applied)
        self._composite_cache: QImage | None = None
        self._composite_cache_key: tuple | None = None

        # Persistent QPainter held open during a single erase stroke
        self._stroke_painter: QPainter | None = None

    def add_asset(self, asset: AssetObject) -> None:
        self.objects.append(asset)
        self._spatial.insert(asset)
        self.mark_dirty()

    def remove_asset(self, asset: AssetObject) -> None:
        self._spatial.remove(asset)
        self.objects = [o for o in self.objects if o.id != asset.id]
        self.mark_dirty()

    def has_asset_at(self, image_path: str, x: float, y: float) -> bool:
        """Check if an asset with the same image already exists at exact position."""
        for obj in self.objects:
            if obj.image_path == image_path and obj.x == x and obj.y == y:
                return True
        return False

    def hit_test(self, world_x: float, world_y: float) -> AssetObject | None:
        """Find the topmost asset at the given world position."""
        candidates = {a.id for a in self._spatial.query_point(world_x, world_y)}
        for asset in reversed(self.objects):
            if asset.id in candidates and asset.contains_point(world_x, world_y):
                return asset
        return None

    def mark_dirty(self) -> None:
        super().mark_dirty()
        self._spatial.rebuild(self.objects)
        self._composite_cache = None
        self._composite_cache_key = None

    def _mark_visual_dirty(self) -> None:
        """Mark render cache dirty without rebuilding the spatial index.

        Use this for mask-only mutations (erase, restore) where no object
        positions or sizes have changed.  Avoids an O(N) spatial rebuild on
        every brush stamp during an erase-drag operation.
        """
        super().mark_dirty()

    # --- Erase mask ---

    def ensure_mask(self, world_rect: QRectF) -> None:
        """Create an all-white (fully visible) erase mask if not already present."""
        if self.mask_image is not None:
            return
        w_raw = max(1, math.ceil(world_rect.width()))
        h_raw = max(1, math.ceil(world_rect.height()))
        scale = 1.0
        if w_raw > _MAX_MASK_DIM or h_raw > _MAX_MASK_DIM:
            scale = min(_MAX_MASK_DIM / w_raw, _MAX_MASK_DIM / h_raw)
        w = max(1, int(w_raw * scale))
        h = max(1, int(h_raw * scale))
        self._mask_world_offset = (world_rect.x(), world_rect.y())
        self._mask_world_scale = scale
        self.mask_image = QImage(w, h, QImage.Format.Format_ARGB32)
        self.mask_image.fill(QColor(255, 255, 255, 255))

    def clear_mask(self) -> None:
        """Remove the erase mask (restore all assets to fully visible)."""
        self.mask_image = None
        self.mark_dirty()

    def begin_erase_stroke(self) -> None:
        """Open a persistent QPainter on the mask for the duration of an erase stroke.

        Avoids the overhead of creating and destroying a QPainter for every stamp.
        Must be paired with end_erase_stroke() when the mouse button is released.
        """
        if self.mask_image is None or self._stroke_painter is not None:
            return
        self._stroke_painter = QPainter(self.mask_image)
        self._stroke_painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._stroke_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        self._stroke_painter.setBrush(QColor(0, 0, 0, 0))
        self._stroke_painter.setPen(Qt.PenStyle.NoPen)

    def end_erase_stroke(self) -> None:
        """Close the persistent stroke painter opened by begin_erase_stroke()."""
        if self._stroke_painter is not None:
            self._stroke_painter.end()
            self._stroke_painter = None

    def erase_at(self, wx: float, wy: float, radius_world: float) -> QRect:
        """Paint a hard-edged transparent circle onto the mask at world position.

        Returns the affected pixel rect in mask coordinates (for undo tracking).
        """
        if self.mask_image is None:
            return QRect()
        mx = (wx - self._mask_world_offset[0]) * self._mask_world_scale
        my = (wy - self._mask_world_offset[1]) * self._mask_world_scale
        r = max(1.0, radius_world * self._mask_world_scale)

        if self._stroke_painter is not None:
            # Reuse persistent painter (no open/close overhead per stamp)
            self._stroke_painter.drawEllipse(QPointF(mx, my), r, r)
        else:
            p = QPainter(self.mask_image)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.setBrush(QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(mx, my), r, r)
            p.end()

        self._mark_visual_dirty()
        ri = int(r) + 1
        return QRect(int(mx - ri), int(my - ri), 2 * ri + 2, 2 * ri + 2)

    def get_mask_snapshot(self) -> QImage | None:
        """Return a copy of the current mask image (for undo snapshots)."""
        if self.mask_image is None:
            return None
        return self.mask_image.copy()

    def restore_mask(self, snapshot: QImage | None) -> None:
        """Restore the mask from a saved snapshot."""
        self.mask_image = snapshot.copy() if snapshot is not None else None
        # Mask is purely visual — same as erase_at(), skip spatial rebuild.
        self._mark_visual_dirty()

    def _apply_mask_to_composite(
        self, composite: QImage, viewport_rect: QRectF, device_scale: float
    ) -> None:
        """Apply the erase mask to the composite via DestinationIn composition."""
        if self.mask_image is None:
            return
        mp = QPainter(composite)
        mp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        mp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        # mask pixel (0,0) is at world position _mask_world_offset
        # composite pixel (cpx,cpy) = world pos (viewport_rect.x + cpx/device_scale, ...)
        # We need to position the mask so mask px (mpx,mpy) aligns with composite px:
        #   cpx = (world_x - viewport_rect.x) * device_scale
        #       = (mask_offset_x + mpx/scale - viewport_rect.x) * device_scale
        # => translate by (mask_offset - viewport_tl) * device_scale
        # => scale mask by device_scale / _mask_world_scale
        ox = (self._mask_world_offset[0] - viewport_rect.x()) * device_scale
        oy = (self._mask_world_offset[1] - viewport_rect.y()) * device_scale
        mask_scale = device_scale / self._mask_world_scale
        mp.translate(ox, oy)
        mp.scale(mask_scale, mask_scale)
        mp.drawImage(QPointF(0.0, 0.0), self.mask_image)
        mp.end()

    def paint(self, painter: QPainter, viewport_rect: QRectF, layout: Layout) -> None:
        if (self._gfx_effects_enabled and self.shadow_enabled) or self.mask_image is not None:
            # Composite path: needed for shadow and/or erase mask.
            # Derive device-pixel scale from the painter's current world transform so
            # the composite image is built at screen resolution (sharp at any zoom level).
            xform = painter.transform()
            device_scale = math.sqrt(xform.m11() ** 2 + xform.m21() ** 2)
            if device_scale < 0.01:
                device_scale = 1.0

            # Screen position of viewport top-left (before resetting transform)
            bx, by = viewport_rect.x(), viewport_rect.y()
            screen_tl = xform.map(QPointF(bx, by))

            # Use composite cache to avoid full re-render on every erase stamp.
            # The cache is keyed on viewport + scale; it is invalidated by mark_dirty()
            # (asset changes) but NOT by _mark_visual_dirty() (mask-only changes).
            cache_key = (
                round(bx, 1), round(by, 1),
                round(viewport_rect.width(), 1), round(viewport_rect.height(), 1),
                round(device_scale, 4),
            )
            if self._composite_cache is None or self._composite_cache_key != cache_key:
                self._composite_cache = self._build_composite(viewport_rect, device_scale)
                self._composite_cache_key = cache_key

            # Apply erase mask (DestinationIn) to a copy so the cached original is preserved
            if self.mask_image is not None:
                composite = self._composite_cache.copy()
                self._apply_mask_to_composite(composite, viewport_rect, device_scale)
            else:
                composite = self._composite_cache

            # Render shadow + composite in screen space (no world transform interpolation)
            painter.save()
            painter.resetTransform()
            gfx = self._gfx_effects_enabled
            if gfx and self.shadow_enabled and self.shadow_type == "outer":
                self._paint_outer_shadow(painter, composite, screen_tl, device_scale)
            painter.drawImage(screen_tl, composite)
            if gfx and self.shadow_enabled and self.shadow_type == "inner":
                self._paint_inner_shadow(painter, composite, screen_tl, device_scale)
            painter.restore()
        else:
            # Direct rendering: painter has the world transform, so QPainter renders the
            # original PNG pixmaps via SmoothPixmapTransform at full quality (no cache
            # upsampling blur).
            visible_ids = self._spatial.query_rect(viewport_rect)
            for asset in self.objects:
                if asset.id not in visible_ids:
                    continue
                if not viewport_rect.intersects(asset.bounding_rect()):
                    continue

                pm = asset.get_pixmap()
                if pm.isNull():
                    painter.save()
                    painter.translate(asset.x, asset.y)
                    painter.drawRect(QRectF(-16, -16, 32, 32))
                    painter.restore()
                    continue

                painter.save()
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.translate(asset.x, asset.y)
                painter.rotate(asset.rotation)
                painter.scale(asset.scale, asset.scale)

                w = pm.width()
                h = pm.height()
                painter.drawPixmap(QPointF(-w / 2, -h / 2), pm)

                painter.restore()

    # --- Composite helpers ---

    def _build_composite(self, viewport_rect: QRectF, device_scale: float = 1.0) -> QImage:
        """Render all visible assets onto a QImage at device-pixel resolution (sharp)."""
        bx, by = viewport_rect.x(), viewport_rect.y()
        w = max(1, int(viewport_rect.width() * device_scale))
        h = max(1, int(viewport_rect.height() * device_scale))

        composite = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        composite.fill(Qt.GlobalColor.transparent)

        cp = QPainter(composite)
        cp.setRenderHint(QPainter.RenderHint.Antialiasing)
        cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Scale up to device pixels, then translate to world origin
        cp.scale(device_scale, device_scale)
        cp.translate(-bx, -by)

        visible_ids = self._spatial.query_rect(viewport_rect)
        for asset in self.objects:
            if asset.id not in visible_ids:
                continue
            if not viewport_rect.intersects(asset.bounding_rect()):
                continue

            pm = asset.get_pixmap()
            if pm.isNull():
                continue

            cp.save()
            cp.translate(asset.x, asset.y)
            cp.rotate(asset.rotation)
            cp.scale(asset.scale, asset.scale)
            cp.drawPixmap(QPointF(-pm.width() / 2, -pm.height() / 2), pm)
            cp.restore()

        cp.end()
        return composite

    # --- Shadow rendering ---

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
        screen_tl: QPointF,
        device_scale: float,
    ) -> None:
        """Render outer drop shadow using multi-offset radial technique."""
        w, h = composite.width(), composite.height()
        shadow_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
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

        off_x, off_y = self._shadow_offset()
        ox = off_x * device_scale
        oy = off_y * device_scale
        blur = self.shadow_size * device_scale
        solid_fraction = max(0.0, min(1.0, self.shadow_spread / 100.0))
        sx, sy = screen_tl.x(), screen_tl.y()
        src_rect = QRectF(shadow_img.rect())
        dst = QRectF(sx + ox, sy + oy, w, h)

        if blur <= 0 or solid_fraction >= 1.0:
            painter.setOpacity(self.shadow_opacity)
            painter.drawImage(dst, shadow_img, src_rect)
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
            painter.drawImage(QRectF(sx + ox + dx, sy + oy + dy, w, h), shadow_img, src_rect)

        painter.setOpacity(self.shadow_opacity * 0.5)
        painter.drawImage(dst, shadow_img, src_rect)
        painter.setOpacity(1.0)

    def _paint_inner_shadow(
        self,
        painter: QPainter,
        composite: QImage,
        screen_tl: QPointF,
        device_scale: float,
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
        ox = off_x * device_scale
        oy = off_y * device_scale
        blur = self.shadow_size * device_scale
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

        sx, sy = screen_tl.x(), screen_tl.y()
        painter.drawImage(QRectF(sx, sy, w, h), shadow_result, QRectF(shadow_result.rect()))

    # --- Serialization ---

    def serialize(self) -> dict:
        data = self._base_serialize()
        data["type"] = "asset"
        data["objects"] = [obj.serialize() for obj in self.objects]

        # Always save all effect fields so disabled settings survive round-trip
        data["shadow_enabled"] = self.shadow_enabled
        data["shadow_type"] = self.shadow_type
        data["shadow_color"] = self.shadow_color
        data["shadow_opacity"] = round(self.shadow_opacity, 2)
        data["shadow_angle"] = round(self.shadow_angle, 1)
        data["shadow_distance"] = round(self.shadow_distance, 1)
        data["shadow_spread"] = round(self.shadow_spread, 1)
        data["shadow_size"] = round(self.shadow_size, 1)

        if self.mask_image is not None:
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QBuffer.OpenModeFlag.WriteOnly)
            self.mask_image.save(buf, "PNG")
            buf.close()
            data["mask_image"] = base64.b64encode(ba.data()).decode("ascii")
            data["mask_world_offset_x"] = round(self._mask_world_offset[0], 4)
            data["mask_world_offset_y"] = round(self._mask_world_offset[1], 4)
            data["mask_world_scale"] = round(self._mask_world_scale, 6)

        return data

    @classmethod
    def deserialize(cls, data: dict) -> AssetLayer:
        layer = cls(data.get("name", "Assets"))
        layer._base_deserialize(data)

        layer.shadow_enabled = data.get("shadow_enabled", False)
        layer.shadow_type = data.get("shadow_type", "outer")
        layer.shadow_color = data.get("shadow_color", "#000000")
        layer.shadow_opacity = data.get("shadow_opacity", 0.5)
        layer.shadow_angle = data.get("shadow_angle", 120.0)
        layer.shadow_distance = data.get("shadow_distance", 5.0)
        layer.shadow_spread = data.get("shadow_spread", 0.0)
        layer.shadow_size = data.get("shadow_size", data.get("shadow_blur_radius", 5.0))

        if "mask_image" in data:
            raw = base64.b64decode(data["mask_image"])
            img = QImage()
            img.loadFromData(raw, "PNG")
            if not img.isNull():
                layer.mask_image = img
                layer._mask_world_offset = (
                    data.get("mask_world_offset_x", 0.0),
                    data.get("mask_world_offset_y", 0.0),
                )
                layer._mask_world_scale = data.get("mask_world_scale", 1.0)

        for obj_data in data.get("objects", []):
            layer.objects.append(AssetObject.deserialize(obj_data))
        layer._spatial.rebuild(layer.objects)
        return layer
