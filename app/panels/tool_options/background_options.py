"""Background tool options builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

# Process-local clipboard for copying position+zoom between background layers.
# Stores {"offset_x": float, "offset_y": float, "scale": float} or None.
_transform_clipboard: dict | None = None

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.hex.hex_math import hex_corners
from app.tools.background_tool import BackgroundTool

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel


class BackgroundOptions:
    """Builds and manages the background tool options UI."""

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._bg_tool: BackgroundTool | None = None
        self._edit_dialog = None  # BackgroundEditDialog instance (modeless)

    def create(self, tool: BackgroundTool) -> QWidget:
        """Build background options widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)

        self._bg_tool = tool
        bg_layer = tool.find_background_layer()

        # ===== Image group =====
        image_group = QGroupBox("Image")
        image_gl = QVBoxLayout(image_group)
        image_gl.setContentsMargins(6, 4, 6, 4)

        load_btn = QPushButton("Load Image...")
        load_btn.clicked.connect(self._on_load_bg_image)
        image_gl.addWidget(load_btn)

        self._bg_filename_label = QLabel("No image loaded")
        self._bg_filename_label.setWordWrap(True)
        if bg_layer and bg_layer.image_path:
            import os
            self._bg_filename_label.setText(os.path.basename(bg_layer.image_path))
        image_gl.addWidget(self._bg_filename_label)

        self._clip_cb = QCheckBox("Cut at Edges")
        self._clip_cb.setToolTip(
            "Clip the image to the outer boundary of the hex grid"
        )
        self._clip_cb.setChecked(bg_layer.clip_to_grid if bg_layer else False)
        self._clip_cb.toggled.connect(self._on_clip_toggled)
        image_gl.addWidget(self._clip_cb)

        self._edit_image_btn = QPushButton("Edit Image...")
        self._edit_image_btn.setToolTip(
            "Open the image editor (Paint, Posterize, Select Color, Outline)"
        )
        self._edit_image_btn.clicked.connect(self._on_edit_image)
        image_gl.addWidget(self._edit_image_btn)

        layout.addWidget(image_group)

        # ===== Zoom group =====
        zoom_group = QGroupBox("Zoom")
        zoom_gl = QVBoxLayout(zoom_group)
        zoom_gl.setContentsMargins(6, 4, 6, 4)

        zoom_layout = QHBoxLayout()
        self._bg_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._bg_zoom_slider.setRange(1, 500)
        current_scale = bg_layer.scale if bg_layer else 1.0
        self._bg_zoom_slider.setValue(int(current_scale * 100))
        self._bg_zoom_slider.valueChanged.connect(self._on_bg_zoom_slider_changed)
        zoom_layout.addWidget(self._bg_zoom_slider, stretch=1)

        self._bg_zoom_spin = QDoubleSpinBox()
        self._bg_zoom_spin.setRange(0.01, 5.0)
        self._bg_zoom_spin.setSingleStep(0.05)
        self._bg_zoom_spin.setDecimals(2)
        self._bg_zoom_spin.setSuffix("x")
        self._bg_zoom_spin.setValue(current_scale)
        self._bg_zoom_spin.valueChanged.connect(self._on_bg_zoom_spin_changed)
        zoom_layout.addWidget(self._bg_zoom_spin)
        zoom_gl.addLayout(zoom_layout)

        layout.addWidget(zoom_group)

        # ===== Opacity group =====
        opacity_group = QGroupBox("Opacity")
        opacity_gl = QVBoxLayout(opacity_group)
        opacity_gl.setContentsMargins(6, 4, 6, 4)

        opacity_layout = QHBoxLayout()
        self._bg_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._bg_opacity_slider.setRange(0, 100)
        current_opacity = bg_layer.opacity if bg_layer else 1.0
        self._bg_opacity_slider.setValue(int(current_opacity * 100))
        self._bg_opacity_slider.valueChanged.connect(self._on_bg_opacity_slider_changed)
        opacity_layout.addWidget(self._bg_opacity_slider, stretch=1)

        self._bg_opacity_spin = QDoubleSpinBox()
        self._bg_opacity_spin.setRange(0.0, 1.0)
        self._bg_opacity_spin.setSingleStep(0.05)
        self._bg_opacity_spin.setDecimals(2)
        self._bg_opacity_spin.setValue(current_opacity)
        self._bg_opacity_spin.valueChanged.connect(self._on_bg_opacity_spin_changed)
        opacity_layout.addWidget(self._bg_opacity_spin)
        opacity_gl.addLayout(opacity_layout)

        layout.addWidget(opacity_group)

        # ===== Position group =====
        position_group = QGroupBox("Position")
        position_gl = QVBoxLayout(position_group)
        position_gl.setContentsMargins(6, 4, 6, 4)

        self._bg_lock_cb = QCheckBox("Lock Position && Zoom")
        self._bg_lock_cb.setChecked(tool.locked)
        self._bg_lock_cb.toggled.connect(self._on_bg_lock_toggled)
        position_gl.addWidget(self._bg_lock_cb)

        self._bg_reset_btn = QPushButton("Reset Position")
        self._bg_reset_btn.clicked.connect(self._on_bg_reset_position)
        position_gl.addWidget(self._bg_reset_btn)

        # Align corner to hex grid
        position_gl.addWidget(QLabel("Align Corner to Grid:"))
        align_row1 = QHBoxLayout()
        self._align_tl_btn = QPushButton("↖ TL")
        self._align_tr_btn = QPushButton("↗ TR")
        align_row1.addWidget(self._align_tl_btn)
        align_row1.addWidget(self._align_tr_btn)
        position_gl.addLayout(align_row1)

        align_row2 = QHBoxLayout()
        self._align_bl_btn = QPushButton("↙ BL")
        self._align_br_btn = QPushButton("↘ BR")
        align_row2.addWidget(self._align_bl_btn)
        align_row2.addWidget(self._align_br_btn)
        position_gl.addLayout(align_row2)

        self._align_tl_btn.clicked.connect(lambda: self._on_align_corner("tl"))
        self._align_tr_btn.clicked.connect(lambda: self._on_align_corner("tr"))
        self._align_bl_btn.clicked.connect(lambda: self._on_align_corner("bl"))
        self._align_br_btn.clicked.connect(lambda: self._on_align_corner("br"))

        # Copy / Paste transform
        copy_paste_row = QHBoxLayout()
        self._copy_transform_btn = QPushButton("Copy Transform")
        self._copy_transform_btn.setToolTip(
            "Copy position and zoom of this layer to the clipboard"
        )
        self._copy_transform_btn.clicked.connect(self._on_copy_transform)
        copy_paste_row.addWidget(self._copy_transform_btn)

        self._paste_transform_btn = QPushButton("Paste Transform")
        self._paste_transform_btn.setToolTip(
            "Apply the copied position and zoom to this layer"
        )
        self._paste_transform_btn.clicked.connect(self._on_paste_transform)
        copy_paste_row.addWidget(self._paste_transform_btn)
        position_gl.addLayout(copy_paste_row)

        layout.addWidget(position_group)

        # Store group references for lock toggle
        self._bg_zoom_group = zoom_group
        self._bg_position_group = position_group

        # Apply initial lock state
        self._set_bg_lock_state(tool.locked)

        # Track anchor corner for zoom
        self._zoom_anchor: str | None = None
        tool._on_offset_changed = self._on_image_dragged

        return widget

    def sync_from_layer(self) -> None:
        """Sync background options UI with the current active background layer."""
        if self._bg_tool is None:
            return
        bg_layer = self._bg_tool.find_background_layer()
        if bg_layer:
            import os
            if bg_layer.has_edits and bg_layer.edited_image_path:  # L22: use public property
                label = os.path.basename(bg_layer.edited_image_path) + " (edited)"
            elif bg_layer.image_path:
                label = os.path.basename(bg_layer.image_path)
            else:
                label = "No image loaded"
            self._bg_filename_label.setText(label)
            self._clip_cb.blockSignals(True)
            self._clip_cb.setChecked(bg_layer.clip_to_grid)
            self._clip_cb.blockSignals(False)
            self._sync_bg_zoom(bg_layer.scale)
            self._sync_bg_opacity(bg_layer.opacity)
        else:
            self._bg_filename_label.setText("No image loaded")
            self._clip_cb.blockSignals(True)
            self._clip_cb.setChecked(False)
            self._clip_cb.blockSignals(False)
            self._sync_bg_zoom(1.0)
            self._sync_bg_opacity(1.0)

    def close_sidebar(self) -> None:
        """Close the edit dialog if open (called when tool is deactivated)."""
        if self._edit_dialog is not None and self._edit_dialog.isVisible():
            self._edit_dialog.close()

    # ------------------------------------------------------------------
    # Edit Image dialog
    # ------------------------------------------------------------------

    def _on_edit_image(self) -> None:
        """Open the image editor dialog (or raise if already open)."""
        if not self._bg_tool:
            return
        bg_layer = self._bg_tool.find_background_layer()
        if not bg_layer or not bg_layer.has_image():
            QMessageBox.information(
                self.dock, "Edit Image", "Please load an image first."
            )
            return

        from app.panels.background_edit_dialog import BackgroundEditDialog

        if self._edit_dialog is None or not self._edit_dialog.isVisible():
            self._edit_dialog = BackgroundEditDialog(
                bg_layer,
                self._bg_tool._command_stack,
                self.dock.window(),
            )
            self._edit_dialog.apply_to_new_layer.connect(
                self._on_apply_to_new_layer,
            )
            self._edit_dialog.show()
        else:
            self._edit_dialog.raise_()
            self._edit_dialog.activateWindow()

    def _on_apply_to_new_layer(self, image: 'QImage') -> None:
        """Handle 'Apply to New Layer' from the edit dialog."""
        if not self._bg_tool:
            return
        bg_layer = self._bg_tool.find_background_layer()
        if not bg_layer:
            return
        from app.commands.background_commands import ApplyToNewLayerCommand
        cmd = ApplyToNewLayerCommand(
            self._bg_tool._project.layer_stack,
            bg_layer,
            image,
        )
        self._bg_tool._command_stack.execute(cmd)

    # ------------------------------------------------------------------
    # Image load
    # ------------------------------------------------------------------

    def _on_load_bg_image(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self.dock, "Load Background Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;All Files (*)"
        )
        if not path:
            return

        if self._bg_tool.load_image(path):
            import os
            self._bg_filename_label.setText(os.path.basename(path))
            bg_layer = self._bg_tool.find_background_layer()
            if bg_layer:
                self._sync_bg_opacity(bg_layer.opacity)
                self._sync_bg_zoom(bg_layer.scale)
        else:
            QMessageBox.warning(self.dock, "Error", "Failed to load image.")

    # --- Background lock ---

    def _on_bg_lock_toggled(self, checked: bool):
        self._bg_tool.locked = checked
        self._set_bg_lock_state(checked)

    def _set_bg_lock_state(self, locked: bool):
        self._bg_zoom_group.setEnabled(not locked)
        self._bg_reset_btn.setEnabled(not locked)
        self._paste_transform_btn.setEnabled(not locked)
        for btn in (self._align_tl_btn, self._align_tr_btn,
                    self._align_bl_btn, self._align_br_btn):
            btn.setEnabled(not locked)

    # --- Background zoom ---

    def _on_bg_zoom_slider_changed(self, value: int):
        scale = value / 100.0
        self._bg_zoom_spin.blockSignals(True)
        self._bg_zoom_spin.setValue(scale)
        self._bg_zoom_spin.blockSignals(False)
        self._apply_bg_zoom(scale)

    def _on_bg_zoom_spin_changed(self, value: float):
        self._bg_zoom_slider.blockSignals(True)
        self._bg_zoom_slider.setValue(int(value * 100))
        self._bg_zoom_slider.blockSignals(False)
        self._apply_bg_zoom(value)

    def _apply_bg_zoom(self, scale: float):
        bg_layer = self._bg_tool.find_background_layer()
        if bg_layer:
            bg_layer.scale = scale
            if self._zoom_anchor:
                self._recalculate_anchor_offset(bg_layer)
            bg_layer.mark_dirty()
            self._bg_tool._project.layer_stack.layers_changed.emit()

    def _sync_bg_zoom(self, scale: float):
        self._bg_zoom_slider.blockSignals(True)
        self._bg_zoom_slider.setValue(int(scale * 100))
        self._bg_zoom_slider.blockSignals(False)
        self._bg_zoom_spin.blockSignals(True)
        self._bg_zoom_spin.setValue(scale)
        self._bg_zoom_spin.blockSignals(False)

    # --- Background opacity ---

    def _on_bg_opacity_slider_changed(self, value: int):
        opacity = value / 100.0
        self._bg_opacity_spin.blockSignals(True)
        self._bg_opacity_spin.setValue(opacity)
        self._bg_opacity_spin.blockSignals(False)
        self._apply_bg_opacity(opacity)

    def _on_bg_opacity_spin_changed(self, value: float):
        self._bg_opacity_slider.blockSignals(True)
        self._bg_opacity_slider.setValue(int(value * 100))
        self._bg_opacity_slider.blockSignals(False)
        self._apply_bg_opacity(value)

    def _apply_bg_opacity(self, opacity: float):
        bg_layer = self._bg_tool.find_background_layer()
        if bg_layer:
            bg_layer.opacity = opacity
            bg_layer.mark_dirty()
            self._bg_tool._project.layer_stack.layers_changed.emit()

    def _sync_bg_opacity(self, opacity: float):
        self._bg_opacity_slider.blockSignals(True)
        self._bg_opacity_slider.setValue(int(opacity * 100))
        self._bg_opacity_slider.blockSignals(False)
        self._bg_opacity_spin.blockSignals(True)
        self._bg_opacity_spin.setValue(opacity)
        self._bg_opacity_spin.blockSignals(False)

    # --- Background position ---

    def _on_bg_reset_position(self):
        reply = QMessageBox.question(
            self.dock, "Reset Position",
            "Reset position and zoom to default?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._zoom_anchor = None
        bg_layer = self._bg_tool.find_background_layer()
        if bg_layer:
            bg_layer.offset_x = 0.0
            bg_layer.offset_y = 0.0
            bg_layer.scale = 1.0  # M12: also reset scale (dialog says "position and zoom")
            self._sync_bg_zoom(1.0)
            bg_layer.mark_dirty()
            self._bg_tool._project.layer_stack.layers_changed.emit()

    def _get_tight_grid_bounds(self) -> QRectF:
        config = self._bg_tool._project.grid_config
        layout = config.create_layout()
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        for h in config.get_all_hexes():
            for vx, vy in hex_corners(layout, h):
                if vx < min_x: min_x = vx
                if vy < min_y: min_y = vy
                if vx > max_x: max_x = vx
                if vy > max_y: max_y = vy
        if min_x == float('inf'):
            return QRectF()
        return QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

    def _recalculate_anchor_offset(self, bg_layer) -> None:
        if not self._zoom_anchor or not bg_layer.has_image():
            return
        bounds = self._get_tight_grid_bounds()
        if bounds.isEmpty():
            return
        img_w = bg_layer.image_width() * bg_layer.scale
        img_h = bg_layer.image_height() * bg_layer.scale
        if self._zoom_anchor == "tl":
            bg_layer.offset_x = bounds.left()
            bg_layer.offset_y = bounds.top()
        elif self._zoom_anchor == "tr":
            bg_layer.offset_x = bounds.right() - img_w
            bg_layer.offset_y = bounds.top()
        elif self._zoom_anchor == "bl":
            bg_layer.offset_x = bounds.left()
            bg_layer.offset_y = bounds.bottom() - img_h
        elif self._zoom_anchor == "br":
            bg_layer.offset_x = bounds.right() - img_w
            bg_layer.offset_y = bounds.bottom() - img_h

    def _on_align_corner(self, corner: str) -> None:
        bg_layer = self._bg_tool.find_background_layer()
        if not bg_layer or not bg_layer.has_image():
            return
        self._zoom_anchor = corner
        self._recalculate_anchor_offset(bg_layer)
        bg_layer.mark_dirty()
        self._bg_tool._project.layer_stack.layers_changed.emit()

    def _on_image_dragged(self) -> None:
        self._zoom_anchor = None

    # --- Copy / Paste transform ---

    def _on_copy_transform(self) -> None:
        global _transform_clipboard
        bg_layer = self._bg_tool.find_background_layer()
        if not bg_layer:
            QMessageBox.information(self.dock, "Copy Transform", "No image layer active.")
            return
        _transform_clipboard = {
            "offset_x": bg_layer.offset_x,
            "offset_y": bg_layer.offset_y,
            "scale":    bg_layer.scale,
        }

    def _on_clip_toggled(self, checked: bool) -> None:
        bg_layer = self._bg_tool.find_background_layer()
        if not bg_layer:
            return
        bg_layer.clip_to_grid = checked
        bg_layer.mark_dirty()
        self._bg_tool._project.layer_stack.layers_changed.emit()

    def _on_paste_transform(self) -> None:
        global _transform_clipboard
        if _transform_clipboard is None:
            QMessageBox.information(
                self.dock, "Paste Transform",
                "Nothing copied yet.\n"
                "Switch to a source layer and click 'Copy Transform' first."
            )
            return
        bg_layer = self._bg_tool.find_background_layer()
        if not bg_layer:
            return
        self._zoom_anchor = None
        bg_layer.offset_x = _transform_clipboard["offset_x"]
        bg_layer.offset_y = _transform_clipboard["offset_y"]
        bg_layer.scale    = _transform_clipboard["scale"]
        bg_layer.mark_dirty()
        self._sync_bg_zoom(bg_layer.scale)
        self._bg_tool._project.layer_stack.layers_changed.emit()
