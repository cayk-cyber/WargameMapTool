"""Export map as SVG using QSvgGenerator.

This module is intentionally separate from export.py so that the existing
PNG/PDF/Hexmap export pipeline is not touched.  It reuses the shared helpers
_make_export_config, _get_export_bounds and _paint_map from export.py (read-only
imports, nothing in that module is modified).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgGenerator

from app.models.project import Project
from app.panels.export_dialog import ExportSettings

# Reuse the shared paint helpers from export.py without modifying that file.
from app.io.export import _get_export_bounds, _make_export_config, _paint_map


def export_svg(project: Project, file_path: str, settings: ExportSettings) -> bool:
    """Export the map as an SVG vector image.

    Vector layers (fill colours, grid lines, hexside/border/path lines, text,
    sketch shapes) are stored as true SVG elements and scale losslessly.
    Raster layers (background images, assets, draw channels) are embedded as
    base64-encoded PNG data – they render correctly in every SVG viewer.

    Returns True on success, False when the map bounds are empty.
    """
    export_config = _make_export_config(project.grid_config, settings)
    bounds = _get_export_bounds(export_config)
    if bounds.isEmpty():
        return False

    # Match the PNG export: half-hex maps get no extra margin.
    margin = 0 if export_config.half_hexes else 20
    w = bounds.width() + margin * 2
    h = bounds.height() + margin * 2

    generator = QSvgGenerator()
    generator.setFileName(file_path)
    # setSize expects integer pixel dimensions (used as the SVG width/height attrs).
    generator.setSize(QSize(int(w), int(h)))
    # setViewBox defines the coordinate system; keep as float for precision.
    generator.setViewBox(QRectF(0.0, 0.0, w, h))
    generator.setTitle(project.file_path or "Wargame Map")
    generator.setDescription("Exported from Wargame Map Tool")

    painter = QPainter(generator)
    if not painter.isActive():
        return False

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # Canvas background colour (fill entire viewbox before applying world transform).
    painter.fillRect(QRectF(0.0, 0.0, w, h), project.grid_config.canvas_bg_color)

    # World transform: map (bounds.x, bounds.y) → (margin, margin) in SVG space.
    painter.translate(margin - bounds.x(), margin - bounds.y())

    _paint_map(painter, project, bounds, export_config, settings.single_layer_id)

    painter.end()
    return True
