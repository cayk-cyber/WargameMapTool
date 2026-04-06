"""Export dialog - choose format, content options, and resolution."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QPushButton,
)

from app.hex.hex_grid_config import HexGridConfig


@dataclass
class ExportSettings:
    """Settings chosen in the export dialog."""

    formats: list[str]  # subset of ["png", "pdf", "svg", "hexmap"]
    dpi: int  # 72, 96, 150, 300
    show_grid: bool
    show_center_dots: bool
    show_coordinates: bool
    show_megahexes: bool = True
    single_layer_id: str | None = None  # None = all layers


# DPI presets available in the dropdown
_DPI_PRESETS = [72, 96, 150, 300]


class ExportDialog(QDialog):
    """Dialog for configuring map export options."""

    def __init__(
        self,
        config: HexGridConfig,
        project_name: str = "Untitled",
        layers: list[tuple[str, str]] | None = None,
        parent=None,
    ):
        """
        Args:
            config: Grid configuration.
            project_name: Used for the default filename.
            layers: List of (layer_id, layer_name) tuples, top-to-bottom order.
        """
        super().__init__(parent)
        self.setWindowTitle("Export Map")
        self.setMinimumWidth(320)
        self._config = config
        self._project_name = project_name
        self._layers = layers or []

        layout = QVBoxLayout(self)

        # --- Format (multi-select) ---
        format_group = QGroupBox("Format")
        format_layout = QVBoxLayout(format_group)

        self._png_cb_fmt = QCheckBox("PNG (raster image)")
        self._pdf_cb_fmt = QCheckBox("PDF (vector)")
        self._svg_cb_fmt = QCheckBox("SVG (vector image)")
        self._hexmap_cb_fmt = QCheckBox("Hexmap (project file)")
        self._png_cb_fmt.setChecked(True)

        format_layout.addWidget(self._png_cb_fmt)
        format_layout.addWidget(self._pdf_cb_fmt)
        format_layout.addWidget(self._svg_cb_fmt)
        format_layout.addWidget(self._hexmap_cb_fmt)
        layout.addWidget(format_group)

        # --- Content ---
        self._content_group = QGroupBox("Content")
        content_layout = QVBoxLayout(self._content_group)

        self._grid_cb = QCheckBox("Show Grid")
        self._grid_cb.setChecked(config.show_grid)
        content_layout.addWidget(self._grid_cb)

        self._dots_cb = QCheckBox("Show Center Dots")
        self._dots_cb.setChecked(config.show_center_dots)
        content_layout.addWidget(self._dots_cb)

        self._coords_cb = QCheckBox("Show Coordinates")
        self._coords_cb.setChecked(config.show_coordinates)
        content_layout.addWidget(self._coords_cb)

        self._megahexes_cb = QCheckBox("Show Megahexes")
        self._megahexes_cb.setChecked(config.megahex_enabled)
        self._megahexes_cb.setEnabled(config.megahex_enabled)
        content_layout.addWidget(self._megahexes_cb)

        layout.addWidget(self._content_group)

        # --- Layer Selection ---
        self._layer_group = QGroupBox("Layers")
        layer_layout = QVBoxLayout(self._layer_group)

        self._all_layers_radio = QRadioButton("All Layers")
        self._all_layers_radio.setChecked(True)
        self._single_layer_radio = QRadioButton("Single Layer:")

        layer_btn_group = QButtonGroup(self)
        layer_btn_group.addButton(self._all_layers_radio)
        layer_btn_group.addButton(self._single_layer_radio)

        self._layer_combo = QComboBox()
        for layer_id, layer_name in self._layers:
            self._layer_combo.addItem(layer_name, layer_id)
        self._layer_combo.setEnabled(False)

        layer_layout.addWidget(self._all_layers_radio)
        layer_layout.addWidget(self._single_layer_radio)
        layer_layout.addWidget(self._layer_combo)

        # Hide group entirely when no layers are available
        if not self._layers:
            self._layer_group.setVisible(False)

        layout.addWidget(self._layer_group)

        # --- Resolution (PNG only) ---
        self._res_group = QGroupBox("Resolution (PNG)")
        res_layout = QFormLayout(self._res_group)

        self._dpi_combo = QComboBox()
        for dpi in _DPI_PRESETS:
            self._dpi_combo.addItem(f"{dpi} DPI", dpi)
        # Default to 150 DPI
        self._dpi_combo.setCurrentIndex(_DPI_PRESETS.index(150))
        res_layout.addRow("DPI:", self._dpi_combo)

        self._size_label = QLabel()
        res_layout.addRow("Estimated:", self._size_label)

        layout.addWidget(self._res_group)

        # --- Buttons ---
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # --- Signals ---
        self._png_cb_fmt.toggled.connect(self._on_format_changed)
        self._pdf_cb_fmt.toggled.connect(self._on_format_changed)
        self._svg_cb_fmt.toggled.connect(self._on_format_changed)
        self._hexmap_cb_fmt.toggled.connect(self._on_format_changed)
        self._dpi_combo.currentIndexChanged.connect(self._update_size_label)
        self._all_layers_radio.toggled.connect(self._on_layer_selection_changed)
        self._single_layer_radio.toggled.connect(self._on_layer_selection_changed)

        # Keep reference to OK button for enable/disable
        self._ok_btn: QPushButton = button_box.button(QDialogButtonBox.StandardButton.Ok)

        # Initial update
        self._on_format_changed()
        self._update_size_label()

    def _on_format_changed(self):
        """Enable/disable sections based on selected formats."""
        has_png = self._png_cb_fmt.isChecked()
        has_pdf = self._pdf_cb_fmt.isChecked()
        has_svg = self._svg_cb_fmt.isChecked()
        has_image = has_png or has_pdf or has_svg
        any_checked = has_image or self._hexmap_cb_fmt.isChecked()

        # Content/Layer only relevant when an image format is selected
        self._content_group.setEnabled(has_image)
        self._res_group.setEnabled(has_png)
        if self._layers:
            self._layer_group.setEnabled(has_image)

        # Must select at least one format
        self._ok_btn.setEnabled(any_checked)

    def _on_layer_selection_changed(self):
        """Enable/disable the layer combo based on the radio selection."""
        self._layer_combo.setEnabled(self._single_layer_radio.isChecked())

    def _update_size_label(self):
        """Update the estimated image size label."""
        dpi = self._dpi_combo.currentData()
        scale = dpi / 96.0

        bounds = self._config.get_effective_bounds()
        if bounds.isEmpty():
            self._size_label.setText("(empty map)")
            return

        margin = 20  # export whitespace margin
        w = int(bounds.width() * scale) + margin * 2
        h = int(bounds.height() * scale) + margin * 2
        self._size_label.setText(f"{w} x {h} px")

    def get_settings(self) -> ExportSettings:
        """Return the chosen export settings."""
        formats: list[str] = []
        if self._png_cb_fmt.isChecked():
            formats.append("png")
        if self._pdf_cb_fmt.isChecked():
            formats.append("pdf")
        if self._svg_cb_fmt.isChecked():
            formats.append("svg")
        if self._hexmap_cb_fmt.isChecked():
            formats.append("hexmap")

        has_image = "png" in formats or "pdf" in formats or "svg" in formats
        single_layer_id = None
        if (
            has_image
            and self._layers
            and self._single_layer_radio.isChecked()
            and self._layer_combo.count() > 0
        ):
            single_layer_id = self._layer_combo.currentData()

        return ExportSettings(
            formats=formats,
            dpi=self._dpi_combo.currentData(),
            show_grid=self._grid_cb.isChecked(),
            show_center_dots=self._dots_cb.isChecked(),
            show_coordinates=self._coords_cb.isChecked(),
            show_megahexes=self._megahexes_cb.isChecked(),
            single_layer_id=single_layer_id,
        )

    def get_default_basename(self) -> str:
        """Generate a default base filename (no extension) from project metadata."""
        config = self._config
        settings = self.get_settings()
        name = self._project_name
        size = f"{config.width}x{config.height}"
        hex_mm = f"{config.hex_size_mm:.0f}mm"

        layer_suffix = ""
        if settings.single_layer_id is not None and self._layer_combo.count() > 0:
            layer_name = self._layer_combo.currentText()
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in layer_name)
            layer_suffix = f"_{safe}"

        has_png = "png" in settings.formats
        half_suffix = "_half" if (has_png and config.half_hexes) else ""
        dpi_suffix = f"_{settings.dpi}dpi" if has_png else ""

        return f"{name}_{size}_{hex_mm}{layer_suffix}{dpi_suffix}{half_suffix}"
