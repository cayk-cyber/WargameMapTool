"""New Map dialog with live hex preview and preset management."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.hex.hex_grid_config import HexGridConfig
from app.hex.hex_grid_renderer import HexGridRenderer
from app.hex.hex_math import Layout, hex_corners, hex_to_pixel, offset_to_axial
from app.io.preset_manager import delete_preset, is_builtin_preset, list_presets, load_preset, save_preset


class HexPreviewWidget(QWidget):
    """Renders a small preview of hexes with current settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self._config = HexGridConfig()
        self._renderer = HexGridRenderer()
        self._fill_color: QColor = QColor("#c3d89b")

    def set_config(self, config: HexGridConfig) -> None:
        self._config = config
        self.update()

    def set_fill_color(self, color: QColor) -> None:
        self._fill_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        painter.fillRect(self.rect(), QColor("#e8e8e8"))

        # Create a preview config with small grid for display
        preview = HexGridConfig(
            hex_size=self._config.hex_size,
            width=min(self._config.width, 4),
            height=min(self._config.height, 4),
            orientation=self._config.orientation,
            line_width=self._config.line_width,
            edge_color=QColor(self._config.edge_color),
            show_center_dots=self._config.show_center_dots,
            show_coordinates=self._config.show_coordinates,
            first_row_offset=self._config.first_row_offset,
            hex_size_mm=self._config.hex_size_mm,
            center_dot_size=self._config.center_dot_size,
            center_dot_color=QColor(self._config.center_dot_color),
            coord_position=self._config.coord_position,
            coord_format=self._config.coord_format,
            show_border=self._config.show_border,
            border_color=QColor(self._config.border_color),
            coord_offset_y=self._config.coord_offset_y,
            coord_font_scale=self._config.coord_font_scale,
            coord_start_one=self._config.coord_start_one,
            border_margin=self._config.border_margin,
            border_fill=self._config.border_fill,
            border_fill_color=QColor(self._config.border_fill_color),
            half_hexes=self._config.half_hexes,
            grid_style=self._config.grid_style,
            center_dot_outline=self._config.center_dot_outline,
            center_dot_outline_width=self._config.center_dot_outline_width,
            center_dot_outline_color=QColor(self._config.center_dot_outline_color),
        )

        # Compute bounds and scale to fit widget
        layout = preview.create_layout()
        bounds = preview.get_effective_bounds()
        if bounds.isEmpty():
            painter.end()
            return

        # Scale to fit with margin
        margin = 20
        available_w = self.width() - margin * 2
        available_h = self.height() - margin * 2
        if available_w <= 0 or available_h <= 0:
            painter.end()
            return

        scale_x = available_w / bounds.width()
        scale_y = available_h / bounds.height()
        scale = min(scale_x, scale_y)

        # Center in widget
        scaled_w = bounds.width() * scale
        scaled_h = bounds.height() * scale
        offset_x = (self.width() - scaled_w) / 2 - bounds.x() * scale
        offset_y = (self.height() - scaled_h) / 2 - bounds.y() * scale

        painter.translate(offset_x, offset_y)
        painter.scale(scale, scale)

        viewport = bounds.adjusted(
            -preview.hex_size, -preview.hex_size,
            preview.hex_size, preview.hex_size,
        )

        # Draw light gray background for the map area
        painter.fillRect(bounds, QColor("#d0d0d0"))

        # Half-hex clipping
        if preview.half_hexes:
            painter.setClipRect(preview.get_half_hex_bounds())

        # 1. Border fill first (fills outer border strip, same as canvas render order)
        self._renderer.paint_border_fill(painter, layout, preview)

        # 2. Fill color for each hex (on top of border fill, clipped to map bounds)
        if self._fill_color.isValid():
            painter.save()
            painter.setClipRect(bounds, Qt.ClipOperation.IntersectClip)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._fill_color)
            for col in range(preview.width):
                for row in range(preview.height):
                    hex_axial = offset_to_axial(col, row, preview.first_row_offset, preview.orientation)
                    corners = hex_corners(layout, hex_axial)
                    polygon = QPolygonF([QPointF(c[0], c[1]) for c in corners])
                    painter.drawPolygon(polygon)
            painter.restore()

        # 3. Grid overlay (hex lines, dots, coordinates)
        self._renderer.paint(painter, viewport, layout, preview)
        painter.end()


class NewMapDialog(QDialog):
    """Dialog for creating a new map or editing visual grid settings."""

    def __init__(self, parent=None, settings_only: bool = False):
        super().__init__(parent)
        self._settings_only = settings_only
        self._fill_color = QColor("#c3d89b")
        self.setWindowTitle("Map Settings" if settings_only else "New Map")
        self.setMinimumSize(850, 700)

        # Outer layout: content + buttons
        outer_layout = QVBoxLayout(self)

        # Main layout: settings columns left, preview right
        main_layout = QHBoxLayout()

        # Settings in two columns
        settings_columns = QHBoxLayout()
        settings_columns.setSpacing(8)

        # --- LEFT COLUMN: Presets, Grid, Lines ---
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        # Presets
        preset_group = QGroupBox("Presets")
        preset_layout = QVBoxLayout(preset_group)

        self._preset_combo = QComboBox()
        self._refresh_presets()
        preset_layout.addWidget(self._preset_combo)

        preset_btn_layout = QHBoxLayout()
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._on_load_preset)
        preset_btn_layout.addWidget(load_btn)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save_preset)
        preset_btn_layout.addWidget(save_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete_preset)
        preset_btn_layout.addWidget(delete_btn)

        preset_layout.addLayout(preset_btn_layout)
        left_col.addWidget(preset_group)

        if settings_only:
            preset_group.setEnabled(False)

        # Grid
        grid_group = QGroupBox("Grid")
        grid_form = QFormLayout(grid_group)

        self._hex_size_spin = QDoubleSpinBox()
        self._hex_size_spin.setRange(5.0, 50.0)
        self._hex_size_spin.setSingleStep(0.5)
        self._hex_size_spin.setValue(19.0)
        self._hex_size_spin.setSuffix(" mm")
        grid_form.addRow("Hex Size:", self._hex_size_spin)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 100)
        self._width_spin.setValue(20)
        grid_form.addRow("Columns (Width):", self._width_spin)

        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 100)
        self._height_spin.setValue(20)
        grid_form.addRow("Rows (Height):", self._height_spin)

        self._orientation_combo = QComboBox()
        self._orientation_combo.addItem("Upright (Pointy-Top)", "pointy")
        self._orientation_combo.addItem("Flat (Flat-Top)", "flat")
        self._orientation_combo.setCurrentIndex(1)  # Default: flat
        grid_form.addRow("Orientation:", self._orientation_combo)

        self._first_row_combo = QComboBox()
        self._first_row_combo.addItem("Offset Down (Even)", "even")
        self._first_row_combo.addItem("Offset Up (Odd)", "odd")
        grid_form.addRow("First Row:", self._first_row_combo)

        left_col.addWidget(grid_group)

        if settings_only:
            grid_group.setEnabled(False)

        # Lines
        lines_group = QGroupBox("Lines")
        lines_form = QFormLayout(lines_group)

        self._grid_style_combo = QComboBox()
        self._grid_style_combo.addItem("Full Lines", "lines")
        self._grid_style_combo.addItem("Crossings Only", "crossings")
        lines_form.addRow("Style:", self._grid_style_combo)

        self._line_width_spin = QDoubleSpinBox()
        self._line_width_spin.setRange(0.5, 10.0)
        self._line_width_spin.setSingleStep(0.5)
        self._line_width_spin.setValue(1.0)
        lines_form.addRow("Line Width:", self._line_width_spin)

        self._edge_color = QColor(0, 0, 0)
        self._edge_color_btn = QPushButton()
        self._edge_color_btn.setFixedSize(40, 25)
        self._update_color_btn(self._edge_color_btn, self._edge_color)
        self._edge_color_btn.clicked.connect(lambda: self._pick_color("edge"))
        lines_form.addRow("Edge Color:", self._edge_color_btn)

        left_col.addWidget(lines_group)

        # Center Dots
        dots_group = QGroupBox("Center Dots")
        dots_form = QFormLayout(dots_group)

        self._show_dots_cb = QCheckBox("Show")
        dots_form.addRow(self._show_dots_cb)

        self._dot_size_spin = QDoubleSpinBox()
        self._dot_size_spin.setRange(1.0, 10.0)
        self._dot_size_spin.setSingleStep(0.5)
        self._dot_size_spin.setValue(3.0)
        self._dot_size_spin.setEnabled(False)
        dots_form.addRow("Size:", self._dot_size_spin)

        self._dot_color = QColor(0, 0, 0)
        self._dot_color_btn = QPushButton()
        self._dot_color_btn.setFixedSize(40, 25)
        self._update_color_btn(self._dot_color_btn, self._dot_color)
        self._dot_color_btn.clicked.connect(lambda: self._pick_color("dot"))
        self._dot_color_btn.setEnabled(False)
        dots_form.addRow("Color:", self._dot_color_btn)

        self._dot_outline_cb = QCheckBox("Outline")
        self._dot_outline_cb.setEnabled(False)
        dots_form.addRow(self._dot_outline_cb)

        self._dot_outline_width_spin = QDoubleSpinBox()
        self._dot_outline_width_spin.setRange(0.5, 10.0)
        self._dot_outline_width_spin.setSingleStep(0.5)
        self._dot_outline_width_spin.setValue(1.0)
        self._dot_outline_width_spin.setEnabled(False)
        dots_form.addRow("Outline Width:", self._dot_outline_width_spin)

        self._dot_outline_color = QColor(255, 255, 255)
        self._dot_outline_color_btn = QPushButton()
        self._dot_outline_color_btn.setFixedSize(40, 25)
        self._update_color_btn(self._dot_outline_color_btn, self._dot_outline_color)
        self._dot_outline_color_btn.clicked.connect(lambda: self._pick_color("dot_outline"))
        self._dot_outline_color_btn.setEnabled(False)
        dots_form.addRow("Outline Color:", self._dot_outline_color_btn)

        self._show_dots_cb.toggled.connect(self._dot_size_spin.setEnabled)
        self._show_dots_cb.toggled.connect(self._dot_color_btn.setEnabled)
        self._show_dots_cb.toggled.connect(self._dot_outline_cb.setEnabled)
        self._show_dots_cb.toggled.connect(self._on_dots_toggled)
        self._dot_outline_cb.toggled.connect(self._on_dot_outline_toggled)

        left_col.addWidget(dots_group)
        left_col.addStretch()

        settings_columns.addLayout(left_col)

        # --- RIGHT COLUMN: Coordinates, Border ---
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # Coordinates
        coords_group = QGroupBox("Coordinates")
        coords_form = QFormLayout(coords_group)

        self._show_coords_cb = QCheckBox("Show")
        coords_form.addRow(self._show_coords_cb)

        self._coord_pos_combo = QComboBox()
        self._coord_pos_combo.addItem("Top", "top")
        self._coord_pos_combo.addItem("Bottom", "bottom")
        self._coord_pos_combo.setEnabled(False)
        coords_form.addRow("Position:", self._coord_pos_combo)

        self._coord_offset_spin = QDoubleSpinBox()
        self._coord_offset_spin.setRange(-0.5, 0.5)
        self._coord_offset_spin.setSingleStep(0.05)
        self._coord_offset_spin.setValue(0.0)
        self._coord_offset_spin.setEnabled(False)
        coords_form.addRow("Y-Offset:", self._coord_offset_spin)

        self._coord_format_combo = QComboBox()
        self._coord_format_combo.addItem("0101", "numeric")
        self._coord_format_combo.addItem("01.01", "numeric_dot")
        self._coord_format_combo.addItem("A1", "letter")
        self._coord_format_combo.addItem("1,1", "plain")
        self._coord_format_combo.setCurrentIndex(1)  # Default: 01.01
        self._coord_format_combo.setEnabled(False)
        coords_form.addRow("Format:", self._coord_format_combo)

        self._coord_font_scale_spin = QSpinBox()
        self._coord_font_scale_spin.setRange(5, 50)
        self._coord_font_scale_spin.setSingleStep(1)
        self._coord_font_scale_spin.setValue(18)
        self._coord_font_scale_spin.setSuffix(" %")
        self._coord_font_scale_spin.setEnabled(False)
        coords_form.addRow("Font Size:", self._coord_font_scale_spin)

        self._coord_start_one_cb = QCheckBox("Start at 1")
        self._coord_start_one_cb.setEnabled(False)
        coords_form.addRow(self._coord_start_one_cb)

        self._show_coords_cb.toggled.connect(self._coord_pos_combo.setEnabled)
        self._show_coords_cb.toggled.connect(self._coord_offset_spin.setEnabled)
        self._show_coords_cb.toggled.connect(self._coord_format_combo.setEnabled)
        self._show_coords_cb.toggled.connect(self._coord_font_scale_spin.setEnabled)
        self._show_coords_cb.toggled.connect(self._coord_start_one_cb.setEnabled)

        right_col.addWidget(coords_group)

        # Border / Half Hexes
        border_group = QGroupBox("Border / Edges")
        border_form = QFormLayout(border_group)

        self._half_hexes_cb = QCheckBox("Half Hexes (tileable)")
        border_form.addRow(self._half_hexes_cb)

        self._show_border_cb = QCheckBox("Show Border")
        border_form.addRow(self._show_border_cb)

        self._border_color = QColor(0, 0, 0)
        self._border_color_btn = QPushButton()
        self._border_color_btn.setFixedSize(40, 25)
        self._update_color_btn(self._border_color_btn, self._border_color)
        self._border_color_btn.clicked.connect(lambda: self._pick_color("border"))
        self._border_color_btn.setEnabled(False)
        border_form.addRow("Color:", self._border_color_btn)

        self._border_margin_spin = QDoubleSpinBox()
        self._border_margin_spin.setRange(0.0, 150.0)
        self._border_margin_spin.setSingleStep(0.5)
        self._border_margin_spin.setValue(2.0)
        self._border_margin_spin.setSuffix(" mm")
        self._border_margin_spin.setEnabled(False)
        border_form.addRow("Margin:", self._border_margin_spin)

        self._border_fill_cb = QCheckBox("Fill")
        self._border_fill_cb.setEnabled(False)
        border_form.addRow(self._border_fill_cb)

        self._border_fill_color = QColor(255, 255, 255)
        self._border_fill_color_btn = QPushButton()
        self._border_fill_color_btn.setFixedSize(40, 25)
        self._update_color_btn(self._border_fill_color_btn, self._border_fill_color)
        self._border_fill_color_btn.clicked.connect(lambda: self._pick_color("border_fill"))
        self._border_fill_color_btn.setEnabled(False)
        border_form.addRow("Fill Color:", self._border_fill_color_btn)

        self._show_border_cb.toggled.connect(self._on_border_toggled)
        self._border_fill_cb.toggled.connect(self._on_border_fill_toggled)
        self._half_hexes_cb.toggled.connect(self._on_half_hexes_toggled)

        right_col.addWidget(border_group)

        # Megahexes
        megahex_group = QGroupBox("Megahexes")
        megahex_form = QFormLayout(megahex_group)

        self._megahex_cb = QCheckBox("Enable Megahexes")
        megahex_form.addRow(self._megahex_cb)

        _spin_h = self._hex_size_spin.sizeHint().height()

        self._megahex_radius_spin = QSpinBox()
        self._megahex_radius_spin.setRange(1, 10)
        self._megahex_radius_spin.setValue(1)
        self._megahex_radius_spin.setMinimumHeight(_spin_h)
        self._megahex_radius_spin.setEnabled(False)
        megahex_form.addRow("Radius:", self._megahex_radius_spin)

        self._megahex_mode_combo = QComboBox()
        self._megahex_mode_combo.addItem("Hex Edges", "hex_edges")
        self._megahex_mode_combo.addItem("Geometric", "geometric")
        self._megahex_mode_combo.setMinimumHeight(_spin_h)
        self._megahex_mode_combo.setEnabled(False)
        megahex_form.addRow("Mode:", self._megahex_mode_combo)

        self._megahex_color = QColor(100, 100, 100)
        self._megahex_color_btn = QPushButton()
        self._megahex_color_btn.setFixedSize(40, 25)
        self._update_color_btn(self._megahex_color_btn, self._megahex_color)
        self._megahex_color_btn.clicked.connect(lambda: self._pick_color("megahex"))
        self._megahex_color_btn.setEnabled(False)
        megahex_form.addRow("Color:", self._megahex_color_btn)

        self._megahex_width_spin = QDoubleSpinBox()
        self._megahex_width_spin.setRange(1.0, 10.0)
        self._megahex_width_spin.setSingleStep(0.5)
        self._megahex_width_spin.setValue(3.0)
        self._megahex_width_spin.setMinimumHeight(_spin_h)
        self._megahex_width_spin.setEnabled(False)
        megahex_form.addRow("Width:", self._megahex_width_spin)

        self._megahex_offset_q_spin = QSpinBox()
        self._megahex_offset_q_spin.setRange(-20, 20)
        self._megahex_offset_q_spin.setValue(0)
        self._megahex_offset_q_spin.setMinimumHeight(_spin_h)
        self._megahex_offset_q_spin.setEnabled(False)
        megahex_form.addRow("Offset Q:", self._megahex_offset_q_spin)

        self._megahex_offset_r_spin = QSpinBox()
        self._megahex_offset_r_spin.setRange(-20, 20)
        self._megahex_offset_r_spin.setValue(0)
        self._megahex_offset_r_spin.setMinimumHeight(_spin_h)
        self._megahex_offset_r_spin.setEnabled(False)
        megahex_form.addRow("Offset R:", self._megahex_offset_r_spin)

        # Connect enable/disable
        self._megahex_cb.toggled.connect(self._megahex_radius_spin.setEnabled)
        self._megahex_cb.toggled.connect(self._megahex_mode_combo.setEnabled)
        self._megahex_cb.toggled.connect(self._megahex_color_btn.setEnabled)
        self._megahex_cb.toggled.connect(self._megahex_width_spin.setEnabled)
        self._megahex_cb.toggled.connect(self._megahex_offset_q_spin.setEnabled)
        self._megahex_cb.toggled.connect(self._megahex_offset_r_spin.setEnabled)

        right_col.addWidget(megahex_group)

        # Fill Color (only for new map, not settings)
        if not settings_only:
            fill_group = QGroupBox("Fill Color")
            fill_form = QFormLayout(fill_group)

            self._fill_color_btn = QPushButton()
            self._fill_color_btn.setFixedSize(40, 25)
            self._update_color_btn(self._fill_color_btn, self._fill_color)
            self._fill_color_btn.clicked.connect(lambda: self._pick_color("fill"))
            fill_form.addRow("Color:", self._fill_color_btn)

            right_col.addWidget(fill_group)

        right_col.addStretch()

        settings_columns.addLayout(right_col)

        main_layout.addLayout(settings_columns, stretch=0)

        # Right: preview
        right_layout = QVBoxLayout()
        preview_label = QLabel("Preview")
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(preview_label)

        self._preview = HexPreviewWidget()
        right_layout.addWidget(self._preview, stretch=1)

        # Map size info
        self._size_info_label = QLabel()
        self._size_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self._size_info_label)

        self._size_warning_label = QLabel()
        self._size_warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._size_warning_label.setStyleSheet("color: #d05030; font-weight: bold;")
        self._size_warning_label.setWordWrap(True)
        self._size_warning_label.hide()
        right_layout.addWidget(self._size_warning_label)

        main_layout.addLayout(right_layout, stretch=1)

        outer_layout.addLayout(main_layout, stretch=1)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Apply" if settings_only else "OK")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        outer_layout.addWidget(button_box)

        # Connect all signals to update preview
        self._hex_size_spin.valueChanged.connect(self._update_preview)
        self._width_spin.valueChanged.connect(self._update_preview)
        self._height_spin.valueChanged.connect(self._update_preview)
        self._orientation_combo.currentIndexChanged.connect(self._update_preview)
        self._first_row_combo.currentIndexChanged.connect(self._update_preview)
        self._grid_style_combo.currentIndexChanged.connect(self._update_preview)
        self._line_width_spin.valueChanged.connect(self._update_preview)
        self._show_dots_cb.toggled.connect(self._update_preview)
        self._dot_size_spin.valueChanged.connect(self._update_preview)
        self._dot_outline_cb.toggled.connect(self._update_preview)
        self._dot_outline_width_spin.valueChanged.connect(self._update_preview)
        self._show_coords_cb.toggled.connect(self._update_preview)
        self._coord_pos_combo.currentIndexChanged.connect(self._update_preview)
        self._coord_format_combo.currentIndexChanged.connect(self._update_preview)
        self._coord_offset_spin.valueChanged.connect(self._update_preview)
        self._coord_font_scale_spin.valueChanged.connect(self._update_preview)
        self._coord_start_one_cb.toggled.connect(self._update_preview)
        self._half_hexes_cb.toggled.connect(self._update_preview)
        self._show_border_cb.toggled.connect(self._update_preview)
        self._border_margin_spin.valueChanged.connect(self._update_preview)
        self._border_fill_cb.toggled.connect(self._update_preview)
        self._megahex_cb.toggled.connect(self._update_preview)
        self._megahex_radius_spin.valueChanged.connect(self._update_preview)
        self._megahex_mode_combo.currentIndexChanged.connect(self._update_preview)
        self._megahex_width_spin.valueChanged.connect(self._update_preview)
        self._megahex_offset_q_spin.valueChanged.connect(self._update_preview)
        self._megahex_offset_r_spin.valueChanged.connect(self._update_preview)

        # Initial preview
        self._update_preview()

    # --- Config build / apply ---

    def _build_config(self) -> HexGridConfig:
        """Build a HexGridConfig from current dialog values."""
        hex_size_mm = self._hex_size_spin.value()
        hex_size_px = HexGridConfig.mm_to_pixel_size(hex_size_mm)

        return HexGridConfig(
            hex_size=hex_size_px,
            hex_size_mm=hex_size_mm,
            width=self._width_spin.value(),
            height=self._height_spin.value(),
            orientation=self._orientation_combo.currentData(),
            line_width=self._line_width_spin.value(),
            edge_color=QColor(self._edge_color),
            show_center_dots=self._show_dots_cb.isChecked(),
            show_coordinates=self._show_coords_cb.isChecked(),
            first_row_offset=self._first_row_combo.currentData(),
            center_dot_size=self._dot_size_spin.value(),
            center_dot_color=QColor(self._dot_color),
            coord_position=self._coord_pos_combo.currentData(),
            coord_format=self._coord_format_combo.currentData(),
            coord_offset_y=self._coord_offset_spin.value(),
            coord_font_scale=self._coord_font_scale_spin.value(),
            coord_start_one=self._coord_start_one_cb.isChecked(),
            show_border=self._show_border_cb.isChecked(),
            border_color=QColor(self._border_color),
            border_margin=self._border_margin_spin.value(),
            border_fill=self._border_fill_cb.isChecked(),
            border_fill_color=QColor(self._border_fill_color),
            half_hexes=self._half_hexes_cb.isChecked(),
            grid_style=self._grid_style_combo.currentData(),
            center_dot_outline=self._dot_outline_cb.isChecked(),
            center_dot_outline_width=self._dot_outline_width_spin.value(),
            center_dot_outline_color=QColor(self._dot_outline_color),
            megahex_enabled=self._megahex_cb.isChecked(),
            megahex_radius=self._megahex_radius_spin.value(),
            megahex_mode=self._megahex_mode_combo.currentData(),
            megahex_color=QColor(self._megahex_color),
            megahex_width=self._megahex_width_spin.value(),
            megahex_offset_q=self._megahex_offset_q_spin.value(),
            megahex_offset_r=self._megahex_offset_r_spin.value(),
            default_fill_color=self._fill_color.name() if not self._settings_only else "",
        )

    def _apply_config(self, config: HexGridConfig) -> None:
        """Populate all UI widgets from a HexGridConfig."""
        self._hex_size_spin.setValue(config.hex_size_mm)
        self._width_spin.setValue(config.width)
        self._height_spin.setValue(config.height)

        # Orientation combo
        idx = self._orientation_combo.findData(config.orientation)
        if idx >= 0:
            self._orientation_combo.setCurrentIndex(idx)

        # First row combo
        idx = self._first_row_combo.findData(config.first_row_offset)
        if idx >= 0:
            self._first_row_combo.setCurrentIndex(idx)

        self._line_width_spin.setValue(config.line_width)

        self._edge_color = QColor(config.edge_color)
        self._update_color_btn(self._edge_color_btn, self._edge_color)

        self._show_dots_cb.setChecked(config.show_center_dots)
        self._dot_size_spin.setValue(config.center_dot_size)
        self._dot_color = QColor(config.center_dot_color)
        self._update_color_btn(self._dot_color_btn, self._dot_color)

        self._show_coords_cb.setChecked(config.show_coordinates)

        idx = self._coord_pos_combo.findData(config.coord_position)
        if idx >= 0:
            self._coord_pos_combo.setCurrentIndex(idx)

        self._coord_offset_spin.setValue(config.coord_offset_y)
        self._coord_font_scale_spin.setValue(config.coord_font_scale)
        self._coord_start_one_cb.setChecked(config.coord_start_one)

        idx = self._coord_format_combo.findData(config.coord_format)
        if idx >= 0:
            self._coord_format_combo.setCurrentIndex(idx)

        idx = self._grid_style_combo.findData(config.grid_style)
        if idx >= 0:
            self._grid_style_combo.setCurrentIndex(idx)

        self._dot_outline_cb.setChecked(config.center_dot_outline)
        self._dot_outline_width_spin.setValue(config.center_dot_outline_width)
        self._dot_outline_color = QColor(config.center_dot_outline_color)
        self._update_color_btn(self._dot_outline_color_btn, self._dot_outline_color)

        self._half_hexes_cb.setChecked(config.half_hexes)
        self._show_border_cb.setChecked(config.show_border)
        self._border_color = QColor(config.border_color)
        self._update_color_btn(self._border_color_btn, self._border_color)
        self._border_margin_spin.setValue(config.border_margin)
        self._border_fill_cb.setChecked(config.border_fill)
        self._border_fill_color = QColor(config.border_fill_color)
        self._update_color_btn(self._border_fill_color_btn, self._border_fill_color)

        # Megahexes
        self._megahex_cb.setChecked(config.megahex_enabled)
        self._megahex_radius_spin.setValue(config.megahex_radius)
        idx = self._megahex_mode_combo.findData(config.megahex_mode)
        if idx >= 0:
            self._megahex_mode_combo.setCurrentIndex(idx)
        self._megahex_color = QColor(config.megahex_color)
        self._update_color_btn(self._megahex_color_btn, self._megahex_color)
        self._megahex_width_spin.setValue(config.megahex_width)
        self._megahex_offset_q_spin.setValue(config.megahex_offset_q)
        self._megahex_offset_r_spin.setValue(config.megahex_offset_r)

        # Apply preset default fill color if present (only in new-map mode)
        if config.default_fill_color and not self._settings_only:
            c = QColor(config.default_fill_color)
            if c.isValid():
                self._fill_color = c
                self._update_color_btn(self._fill_color_btn, c)

        self._update_preview()

    def get_config(self) -> HexGridConfig:
        """Return the configured HexGridConfig."""
        return self._build_config()

    def get_fill_color(self) -> QColor:
        """Return the selected fill color for all hexes."""
        return QColor(self._fill_color)

    # --- Preview ---

    def _update_preview(self):
        config = self._build_config()
        self._preview.set_config(config)
        self._preview.set_fill_color(self._fill_color)

        # Update size info
        w_mm = config.width * config.hex_size_mm
        h_mm = config.height * config.hex_size_mm * 0.866  # approx for row spacing
        self._size_info_label.setText(
            f"Map: {config.width} x {config.height} hexes  "
            f"(~{w_mm:.0f} x {h_mm:.0f} mm)"
        )

        # Warn when map pixel area would exceed the render cache limit (must match
        # MAX_CACHE_PIXELS / max_cache_pixels in canvas_widget.py).
        # Uses get_effective_bounds() so border + margin is included in the check.
        bounds = config.get_effective_bounds()
        area = bounds.width() * bounds.height()
        if area > 100_000_000:
            mpx = area / 1_000_000
            self._size_warning_label.setText(
                f"Map area ({mpx:.0f} Mpx, incl. border margin) exceeds the 100 Mpx render limit. "
                "Reduce hex size, grid dimensions, or border margin."
            )
            self._size_warning_label.show()
        else:
            self._size_warning_label.hide()

    def accept(self) -> None:
        """Block dialog acceptance when map area (incl. border margin) exceeds the render limit."""
        config = self._build_config()
        bounds = config.get_effective_bounds()
        if bounds.width() * bounds.height() > 100_000_000:
            QMessageBox.warning(
                self,
                "Map Too Large",
                "The map area (including border margin) exceeds the 100 Mpx render limit.\n"
                "Please reduce the hex size, grid dimensions, or border margin.",
            )
            return
        super().accept()

    # --- Preset management ---

    def _refresh_presets(self):
        self._preset_combo.clear()
        self._preset_combo.addItem("(None)")
        for name in list_presets():
            self._preset_combo.addItem(name)

    def _on_load_preset(self):
        name = self._preset_combo.currentText()
        if name == "(None)":
            return
        try:
            config = load_preset(name)
            self._apply_config(config)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load preset:\n{e}")

    def _on_save_preset(self):
        name, ok = QInputDialog.getText(
            self, "Save Preset", "Preset name:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        try:
            config = self._build_config()
            save_preset(name, config)
            self._refresh_presets()
            # Select the newly saved preset
            idx = self._preset_combo.findText(name)
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save preset:\n{e}")

    def _on_delete_preset(self):
        name = self._preset_combo.currentText()
        if name == "(None)":
            return
        if is_builtin_preset(name):
            QMessageBox.information(
                self, "Built-in Preset",
                f"'{name}' is a built-in preset and cannot be deleted.",
            )
            return
        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Delete preset '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                delete_preset(name)
                self._refresh_presets()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete preset:\n{e}")

    # --- Color pickers ---

    def _pick_color(self, which: str):
        if which == "edge":
            color = QColorDialog.getColor(self._edge_color, self, "Edge Color")
            if color.isValid():
                self._edge_color = color
                self._update_color_btn(self._edge_color_btn, color)
        elif which == "dot":
            color = QColorDialog.getColor(self._dot_color, self, "Dot Color")
            if color.isValid():
                self._dot_color = color
                self._update_color_btn(self._dot_color_btn, color)
        elif which == "border":
            color = QColorDialog.getColor(self._border_color, self, "Border Color")
            if color.isValid():
                self._border_color = color
                self._update_color_btn(self._border_color_btn, color)
        elif which == "dot_outline":
            color = QColorDialog.getColor(self._dot_outline_color, self, "Dot Outline Color")
            if color.isValid():
                self._dot_outline_color = color
                self._update_color_btn(self._dot_outline_color_btn, color)
        elif which == "border_fill":
            color = QColorDialog.getColor(self._border_fill_color, self, "Border Fill Color")
            if color.isValid():
                self._border_fill_color = color
                self._update_color_btn(self._border_fill_color_btn, color)
        elif which == "megahex":
            color = QColorDialog.getColor(self._megahex_color, self, "Megahex Color")
            if color.isValid():
                self._megahex_color = color
                self._update_color_btn(self._megahex_color_btn, color)
        elif which == "fill":
            color = QColorDialog.getColor(self._fill_color, self, "Fill Color")
            if color.isValid():
                self._fill_color = color
                self._update_color_btn(self._fill_color_btn, color)
        self._update_preview()

    def _on_dots_toggled(self, checked: bool):
        """Enable/disable dot outline controls when dots are toggled."""
        outline_enabled = checked and self._dot_outline_cb.isChecked()
        self._dot_outline_width_spin.setEnabled(outline_enabled)
        self._dot_outline_color_btn.setEnabled(outline_enabled)

    def _on_dot_outline_toggled(self, checked: bool):
        """Enable/disable dot outline width/color when outline is toggled."""
        enabled = checked and self._show_dots_cb.isChecked()
        self._dot_outline_width_spin.setEnabled(enabled)
        self._dot_outline_color_btn.setEnabled(enabled)

    def _on_half_hexes_toggled(self, checked: bool):
        """Half hexes and border are mutually exclusive."""
        if checked:
            self._show_border_cb.setChecked(False)
        self._show_border_cb.setEnabled(not checked)
        # M15: when unchecking half-hexes, restore border controls based on current border state
        border_on = self._show_border_cb.isChecked()
        self._border_color_btn.setEnabled(border_on)
        self._border_margin_spin.setEnabled(border_on)
        self._border_fill_cb.setEnabled(border_on)
        self._border_fill_color_btn.setEnabled(border_on and self._border_fill_cb.isChecked())

    def _on_border_toggled(self, checked: bool):
        """Border and half hexes are mutually exclusive."""
        if checked:
            self._half_hexes_cb.setChecked(False)
        self._half_hexes_cb.setEnabled(not checked)
        self._border_color_btn.setEnabled(checked)
        self._border_margin_spin.setEnabled(checked)
        self._border_fill_cb.setEnabled(checked)
        fill_enabled = checked and self._border_fill_cb.isChecked()
        self._border_fill_color_btn.setEnabled(fill_enabled)

    def _on_border_fill_toggled(self, checked: bool):
        self._border_fill_color_btn.setEnabled(
            checked and self._show_border_cb.isChecked()
        )

    def _update_color_btn(self, btn: QPushButton, color: QColor):
        btn.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid #999;"
        )
