"""Non-modal dialog for configuring the global lighting tint overlay."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSlider, QVBoxLayout,
)

from app.panels.tool_options.helpers import update_color_btn


class GlobalLightingDialog(QDialog):
    """Live-preview dialog to set a color tint over the hex map area."""

    def __init__(self, project, canvas, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Global Lighting")
        self.setModal(False)
        self.setFixedWidth(300)

        self._project = project
        self._canvas = canvas

        cfg = project.grid_config

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Enable toggle
        self._enable_cb = QCheckBox("Enable Global Lighting")
        self._enable_cb.setChecked(cfg.global_lighting_enabled)
        self._enable_cb.toggled.connect(self._on_enabled)
        root.addWidget(self._enable_cb)

        # Settings group
        grp = QGroupBox("Tint")
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(8, 6, 8, 6)
        gl.setSpacing(6)

        # Color row
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(32, 32)
        update_color_btn(self._color_btn, cfg.global_lighting_color)
        self._color_btn.setToolTip("Pick tint color")
        self._color_btn.clicked.connect(self._on_pick_color)
        color_row.addWidget(self._color_btn)
        color_row.addStretch()
        gl.addLayout(color_row)

        # Opacity row
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Opacity:"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        pct = int(round(cfg.global_lighting_opacity / 255 * 100))
        self._opacity_slider.setValue(pct)
        self._opacity_slider.valueChanged.connect(self._on_opacity)
        opacity_row.addWidget(self._opacity_slider, stretch=1)
        self._opacity_lbl = QLabel(f"{pct}%")
        self._opacity_lbl.setFixedWidth(36)
        opacity_row.addWidget(self._opacity_lbl)
        gl.addLayout(opacity_row)

        root.addWidget(grp)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_enabled(self, checked: bool) -> None:
        self._project.grid_config.global_lighting_enabled = checked
        self._project.dirty = True
        self._canvas.update()

    def _on_pick_color(self) -> None:
        color = QColorDialog.getColor(
            self._project.grid_config.global_lighting_color, self, "Lighting Tint Color"
        )
        if color.isValid():
            self._project.grid_config.global_lighting_color = color
            update_color_btn(self._color_btn, color)
            self._project.dirty = True
            self._canvas.update()

    def _on_opacity(self, v: int) -> None:
        self._opacity_lbl.setText(f"{v}%")
        self._project.grid_config.global_lighting_opacity = int(round(v / 100 * 255))
        self._project.dirty = True
        self._canvas.update()
