"""Export map as PNG, PDF, or Hexmap."""

from __future__ import annotations

import copy
import json

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter
from PySide6.QtWidgets import QApplication

from app.hex.hex_grid_config import MM_TO_PX, HexGridConfig
from app.layers.base_layer import Layer
from app.layers.fill_layer import FillLayer
from app.layers.hexside_layer import HexsideLayer
from app.layers.sketch_layer import SketchLayer
from app.layers.text_layer import TextLayer
from app.models.project import Project
from app.panels.export_dialog import ExportSettings


def _get_export_bounds(config: HexGridConfig) -> QRectF:
    """Get map bounds considering half_hexes or border margin."""
    return config.get_effective_bounds()


def _make_export_config(config: HexGridConfig, settings: ExportSettings) -> HexGridConfig:
    """Create a config copy with export-specific overrides."""
    export_config = copy.copy(config)
    # Deep copy QColor fields so originals are not affected
    export_config.edge_color = QColor(config.edge_color)
    export_config.center_dot_color = QColor(config.center_dot_color)
    export_config.border_color = QColor(config.border_color)
    export_config.border_fill_color = QColor(config.border_fill_color)
    export_config.center_dot_outline_color = QColor(config.center_dot_outline_color)
    export_config.global_lighting_color = QColor(config.global_lighting_color)
    # Apply export overrides
    export_config.show_grid = settings.show_grid
    export_config.show_center_dots = settings.show_center_dots
    export_config.show_coordinates = settings.show_coordinates
    export_config.megahex_enabled = settings.show_megahexes
    return export_config


def _paint_map(
    painter: QPainter,
    project: Project,
    bounds: QRectF,
    config: HexGridConfig,
    single_layer_id: str | None = None,
) -> None:
    """Paint the map with correct render order.

    Args:
        single_layer_id: When set, only the layer with this id is painted.
                         The image dimensions are identical to a full export.
    """
    # Force all layer effects ON during export regardless of the live
    # "Visible GFX" toggle (which only affects interactive canvas rendering).
    prev_gfx = Layer._gfx_effects_enabled
    Layer._gfx_effects_enabled = True
    try:
        _paint_map_impl(painter, project, bounds, config, single_layer_id)
    finally:
        Layer._gfx_effects_enabled = prev_gfx


def _paint_map_impl(
    painter: QPainter,
    project: Project,
    bounds: QRectF,
    config: HexGridConfig,
    single_layer_id: str | None = None,
) -> None:
    layout = config.create_layout()

    # 0. Grid clip path (applied selectively per layer, not globally)
    grid_clip = config.get_grid_clip_path()

    # In half-hex mode, clip all drawing to the boundary rectangle so that
    # partial edge hexes, grid lines, and all layers are invisible outside it.
    if config.half_hexes:
        painter.setClipPath(grid_clip)

    if single_layer_id is not None:
        # --- Single-layer export ---
        target = next(
            (l for l in project.layer_stack if l.id == single_layer_id), None
        )
        if target is None:
            return

        # Provide fill context in case the target is a HexsideLayer
        if isinstance(target, HexsideLayer):
            fill_colors: dict[tuple[int, int], str] = {}
            fill_textures: dict[tuple[int, int], object] = {}
            for layer in project.layer_stack:
                if layer.visible and isinstance(layer, FillLayer):
                    for h, color in layer.fills.items():
                        fill_colors[(h.q, h.r)] = color.name()
                    for h, tex in layer.textures.items():
                        fill_textures[(h.q, h.r)] = tex
            target.set_fill_context(fill_colors, fill_textures)

        # Paint the layer (handle over-grid split for Sketch/Text)
        if isinstance(target, (SketchLayer, TextLayer)) and target.has_over_grid_objects:
            painter.save()
            painter.setOpacity(target.opacity)
            target.paint_filtered(painter, bounds, layout, over_grid=False)
            painter.restore()
            if config.show_grid:
                project.grid_renderer.paint(painter, bounds, layout, config, {})
            painter.save()
            painter.setOpacity(target.opacity)
            target.paint_filtered(painter, bounds, layout, over_grid=True)
            painter.restore()
        else:
            painter.save()
            painter.setOpacity(target.opacity)
            if target.clip_to_grid:
                painter.setClipPath(grid_clip)
            target.paint(painter, bounds, layout)
            painter.restore()
            if config.show_grid:
                project.grid_renderer.paint(painter, bounds, layout, config, {})
        return

    # --- Full export (all layers) ---

    # 1. Border fill (before layers!)
    project.grid_renderer.paint_border_fill(painter, layout, config)

    # 2. Collect fill data for hexside auto-shift and texture matching
    fill_colors: dict[tuple[int, int], str] = {}
    fill_textures: dict[tuple[int, int], object] = {}
    for layer in project.layer_stack:
        if layer.visible and isinstance(layer, FillLayer):
            for h, color in layer.fills.items():
                fill_colors[(h.q, h.r)] = color.name()
            for h, tex in layer.textures.items():
                fill_textures[(h.q, h.r)] = tex
    for layer in project.layer_stack:
        if isinstance(layer, HexsideLayer):
            layer.set_fill_context(fill_colors, fill_textures)

    # 3. Layers bottom-to-top (split sketch/text layers with over-grid objects)
    over_grid_layers: list[SketchLayer | TextLayer] = []
    for layer in project.layer_stack:
        if not layer.visible:
            continue
        if isinstance(layer, (SketchLayer, TextLayer)) and layer.has_over_grid_objects:
            over_grid_layers.append(layer)
            painter.save()
            painter.setOpacity(layer.opacity)
            layer.paint_filtered(painter, bounds, layout, over_grid=False)
            painter.restore()
            continue
        painter.save()
        painter.setOpacity(layer.opacity)
        if layer.clip_to_grid:
            painter.setClipPath(grid_clip)
        layer.paint(painter, bounds, layout)
        painter.restore()

    # 4. Global lighting tint (over layers, under grid)
    if config.global_lighting_enabled and config.global_lighting_opacity > 0:
        color = QColor(config.global_lighting_color)
        color.setAlpha(config.global_lighting_opacity)
        hex_path = config.get_grid_clip_path()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(hex_path)
        painter.restore()

    # 5. Collect dot/coord color overrides from visible fill layers
    dot_overrides = {}
    coord_overrides = {}
    for layer in project.layer_stack:
        if layer.visible and hasattr(layer, 'dot_colors'):
            dot_overrides.update(layer.dot_colors)
        if layer.visible and hasattr(layer, 'coord_colors'):
            coord_overrides.update(layer.coord_colors)

    # 6. Grid overlay (conditional)
    if config.show_grid:
        project.grid_renderer.paint(painter, bounds, layout, config, dot_overrides, coord_overrides)

    # 7. Over-grid objects (sketch + text) above grid
    for layer in over_grid_layers:
        painter.save()
        painter.setOpacity(layer.opacity)
        layer.paint_filtered(painter, bounds, layout, over_grid=True)
        painter.restore()


def export_png(project: Project, file_path: str, settings: ExportSettings) -> bool:
    """Export map as PNG image."""
    export_config = _make_export_config(project.grid_config, settings)
    bounds = _get_export_bounds(export_config)
    if bounds.isEmpty():
        return False

    scale = settings.dpi / 96.0
    # Half-hex mode: image is cut exactly to the boundary, no extra padding.
    margin = 0 if export_config.half_hexes else 20
    width = int(bounds.width() * scale) + margin * 2
    height = int(bounds.height() * scale) + margin * 2

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(project.grid_config.canvas_bg_color)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.translate(margin - bounds.x() * scale, margin - bounds.y() * scale)
    painter.scale(scale, scale)

    _paint_map(painter, project, bounds, export_config, settings.single_layer_id)
    painter.end()

    return image.save(file_path)


def export_pdf(project: Project, file_path: str, settings: ExportSettings) -> bool:
    """Export map as PDF document."""
    from PySide6.QtGui import QPdfWriter

    export_config = _make_export_config(project.grid_config, settings)
    bounds = _get_export_bounds(export_config)
    if bounds.isEmpty():
        return False

    writer = QPdfWriter(file_path)

    # Page size exactly matches the map bounds.
    # MM_TO_PX = 96/25.4  →  mm_per_px = 25.4/96
    mm_per_px = 1.0 / MM_TO_PX
    w_mm = bounds.width() * mm_per_px
    h_mm = bounds.height() * mm_per_px

    # setPageLayout is more reliable than setPageSize for custom sizes in Qt 6.
    # Portrait orientation with explicit w×h keeps the dimensions as-is.
    writer.setPageLayout(QPageLayout(
        QPageSize(QSizeF(w_mm, h_mm), QPageSize.Unit.Millimeter),
        QPageLayout.Orientation.Portrait,
        QMarginsF(0, 0, 0, 0),
    ))

    resolution = writer.resolution()
    # World coordinates are at 96 DPI (MM_TO_PX = 96/25.4).
    # QPdfWriter device units are at `resolution` DPI.
    # → scale = resolution / 96  (NOT /72 which would overflow by 33 %)
    scale = resolution / 96.0

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.scale(scale, scale)
    painter.translate(-bounds.x(), -bounds.y())

    _paint_map(painter, project, bounds, export_config, settings.single_layer_id)
    painter.end()

    return True


def render_layer_to_image(project: Project, layer_id: str, file_path: str) -> bool:
    """Render a single layer to a PNG image at 1:1 world scale (no margin, transparent bg).

    Returns True on success.
    """
    config = project.grid_config
    bounds = config.get_effective_bounds()
    if bounds.isEmpty():
        return False

    width = int(bounds.width())
    height = int(bounds.height())
    if width <= 0 or height <= 0:
        return False

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.translate(-bounds.x(), -bounds.y())

    # Use the real config (no export overrides) but suppress grid
    render_config = copy.copy(config)
    render_config.show_grid = False
    render_config.show_center_dots = False
    render_config.show_coordinates = False
    _paint_map(painter, project, bounds, render_config, single_layer_id=layer_id)

    painter.end()
    return image.save(file_path)


def export_hexmap(project: Project, file_path: str) -> bool:
    """Export map as .hexmap file (project copy without changing project state)."""
    data = {
        "version": 1,
        "grid": project.grid_config.serialize(),
        "layers": [layer.serialize() for layer in project.layer_stack],
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return True
