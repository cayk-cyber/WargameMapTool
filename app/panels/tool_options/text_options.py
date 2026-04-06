"""Text tool options builder."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.commands.text_commands import EditTextCommand
from app.io.text_preset_manager import (
    TextPreset,
    delete_text_preset,
    is_builtin_text_preset,
    list_text_presets,
    load_text_preset,
    save_text_preset,
)
from app.panels.tool_options.helpers import update_color_btn
from app.panels.tool_options.sidebar_widgets import (
    TextPresetSidebar,
    render_text_preset_preview_pm,
)
from app.tools.text_tool import TextTool

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel


class TextOptions:
    """Builds and manages the text tool options UI."""

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._text_tool: TextTool | None = None
        self._tsp_preset_sidebar: TextPresetSidebar | None = None

    def create(self, tool: TextTool) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)

        self._text_tool = tool
        tool.on_selection_changed = self._on_selection_changed

        # ===== Mode group =====
        mode_group = QGroupBox("Mode")
        mode_gl = QVBoxLayout(mode_group)
        mode_gl.setContentsMargins(6, 4, 6, 4)

        mode_btn_layout = QHBoxLayout()
        place_btn = QPushButton("Place")
        place_btn.setCheckable(True)
        place_btn.setChecked(tool.mode == "place")
        select_btn = QPushButton("Select")
        select_btn.setCheckable(True)
        select_btn.setChecked(tool.mode == "select")

        self._text_mode_group = QButtonGroup(widget)
        self._text_mode_group.setExclusive(True)
        self._text_mode_group.addButton(place_btn, 0)
        self._text_mode_group.addButton(select_btn, 1)
        self._text_mode_group.idToggled.connect(self._on_text_mode_changed)

        mode_btn_layout.addWidget(place_btn)
        mode_btn_layout.addWidget(select_btn)
        mode_btn_layout.addStretch()
        mode_gl.addLayout(mode_btn_layout)

        layout.addWidget(mode_group)

        # ===== Preset group =====
        preset_group = QGroupBox("Presets")
        preset_gl = QVBoxLayout(preset_group)
        preset_gl.setContentsMargins(6, 4, 6, 4)

        # Preview label
        self._text_preset_preview = QLabel()
        self._text_preset_preview.setFixedHeight(40)
        self._text_preset_preview.setScaledContents(False)
        from PySide6.QtWidgets import QSizePolicy
        self._text_preset_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._text_preset_preview.setStyleSheet(
            "background-color: #d0d0d0; border: 1px solid #999; padding: 2px;"
        )
        self._text_preset_preview.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        preset_gl.addWidget(self._text_preset_preview)

        # Combo + buttons row
        combo_layout = QHBoxLayout()
        self._text_preset_combo = QComboBox()
        self._text_preset_combo.setMinimumWidth(60)
        self._text_preset_combo.currentTextChanged.connect(
            self._on_text_preset_selected
        )
        combo_layout.addWidget(self._text_preset_combo, stretch=1)
        preset_gl.addLayout(combo_layout)

        # Expand button
        self._tsp_expand_btn = QPushButton("Expand")
        self._tsp_expand_btn.setCheckable(True)
        self._tsp_expand_btn.setToolTip("Show all presets in expanded sidebar")
        self._tsp_expand_btn.clicked.connect(self._tsp_on_toggle_sidebar)
        preset_gl.addWidget(self._tsp_expand_btn)

        btn_layout2 = QHBoxLayout()
        load_btn = QPushButton("Load")
        load_btn.setToolTip("Apply selected preset to current settings")
        load_btn.clicked.connect(self._on_text_preset_load)
        btn_layout2.addWidget(load_btn)

        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save current settings as a new preset")
        save_btn.clicked.connect(self._on_text_preset_save)
        btn_layout2.addWidget(save_btn)

        del_btn = QPushButton("Del")
        del_btn.setToolTip("Delete selected preset")
        del_btn.clicked.connect(self._on_text_preset_delete)
        btn_layout2.addWidget(del_btn)
        preset_gl.addLayout(btn_layout2)

        layout.addWidget(preset_group)

        # Populate preset combo
        self._refresh_text_preset_combo()
        self._update_text_preset_preview()

        # ===== Text group =====
        text_group = QGroupBox("Text")
        text_gl = QVBoxLayout(text_group)
        text_gl.setContentsMargins(6, 4, 6, 4)

        # Text content
        text_gl.addWidget(QLabel("Content:"))
        self._text_content_edit = QLineEdit()
        self._text_content_edit.setText(tool.pending_text)
        self._text_content_edit.setPlaceholderText("Enter text to place...")
        self._text_content_edit.textChanged.connect(self._on_text_content_changed)
        text_gl.addWidget(self._text_content_edit)

        # Font family
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("Font:"))
        from PySide6.QtWidgets import QFontComboBox, QSizePolicy
        self._text_font_combo = QFontComboBox()
        self._text_font_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._text_font_combo.setCurrentFont(QFont(tool.font_family))
        self._text_font_combo.currentFontChanged.connect(self._on_text_font_changed)
        font_layout.addWidget(self._text_font_combo)
        text_gl.addLayout(font_layout)

        # Font size
        text_gl.addWidget(QLabel("Size:"))
        size_slider_row = QHBoxLayout()
        self._text_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._text_size_slider.setRange(1, 500)
        self._text_size_slider.setValue(int(tool.font_size))
        self._text_size_slider.valueChanged.connect(self._on_text_size_slider)
        size_slider_row.addWidget(self._text_size_slider, stretch=1)
        self._text_size_spin = QDoubleSpinBox()
        self._text_size_spin.setRange(1.0, 500.0)
        self._text_size_spin.setSingleStep(1.0)
        self._text_size_spin.setDecimals(1)
        self._text_size_spin.setValue(tool.font_size)
        self._text_size_spin.setSuffix(" pt")
        self._text_size_spin.setFixedWidth(75)
        self._text_size_spin.valueChanged.connect(self._on_text_size_spin)
        size_slider_row.addWidget(self._text_size_spin)
        text_gl.addLayout(size_slider_row)

        # Bold / Italic
        style_layout = QHBoxLayout()
        self._text_bold_cb = QCheckBox("B")
        self._text_bold_cb.setChecked(tool.bold)
        self._text_bold_cb.setStyleSheet("font-weight: bold;")
        self._text_bold_cb.toggled.connect(self._on_text_bold_changed)
        style_layout.addWidget(self._text_bold_cb)

        self._text_italic_cb = QCheckBox("I")
        self._text_italic_cb.setChecked(tool.italic)
        self._text_italic_cb.setStyleSheet("font-style: italic;")
        self._text_italic_cb.toggled.connect(self._on_text_italic_changed)
        style_layout.addWidget(self._text_italic_cb)

        self._text_underline_cb = QCheckBox("U")
        self._text_underline_cb.setChecked(tool.underline)
        self._text_underline_cb.setStyleSheet("text-decoration: underline;")
        self._text_underline_cb.toggled.connect(self._on_text_underline_changed)
        style_layout.addWidget(self._text_underline_cb)
        style_layout.addStretch()
        text_gl.addLayout(style_layout)

        layout.addWidget(text_group)

        # ===== Style group =====
        style_group = QGroupBox("Style")
        style_gl = QVBoxLayout(style_group)
        style_gl.setContentsMargins(6, 4, 6, 4)

        # Color
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self._text_color_btn = QPushButton()
        self._text_color_btn.setFixedSize(40, 25)
        update_color_btn(self._text_color_btn, QColor(tool.color))
        self._text_color_btn.clicked.connect(self._on_text_color_pick)
        color_layout.addWidget(self._text_color_btn)
        color_layout.addStretch()
        style_gl.addLayout(color_layout)

        # Alignment
        align_layout = QHBoxLayout()
        align_layout.addWidget(QLabel("Align:"))
        self._text_align_combo = QComboBox()
        self._text_align_combo.addItem("Left", "left")
        self._text_align_combo.addItem("Center", "center")
        self._text_align_combo.addItem("Right", "right")
        idx = self._text_align_combo.findData(tool.alignment)
        if idx >= 0:
            self._text_align_combo.setCurrentIndex(idx)
        self._text_align_combo.currentIndexChanged.connect(self._on_text_align_changed)
        align_layout.addWidget(self._text_align_combo)
        align_layout.addStretch()
        style_gl.addLayout(align_layout)

        # Opacity
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("Opacity:"))
        self._text_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._text_opacity_slider.setRange(0, 100)
        self._text_opacity_slider.setValue(int(tool.opacity * 100))
        self._text_opacity_slider.valueChanged.connect(self._on_text_opacity_changed)
        opacity_layout.addWidget(self._text_opacity_slider, stretch=1)
        self._text_opacity_label = QLabel(f"{int(tool.opacity * 100)}%")
        self._text_opacity_label.setFixedWidth(35)
        opacity_layout.addWidget(self._text_opacity_label)
        style_gl.addLayout(opacity_layout)

        # Rotation
        style_gl.addWidget(QLabel("Rotation:"))
        rot_slider_row = QHBoxLayout()
        self._text_rot_slider = QSlider(Qt.Orientation.Horizontal)
        self._text_rot_slider.setRange(0, 359)
        self._text_rot_slider.setValue(int(tool.rotation) % 360)
        self._text_rot_slider.valueChanged.connect(self._on_text_rot_slider)
        rot_slider_row.addWidget(self._text_rot_slider, stretch=1)
        self._text_rot_spin = QSpinBox()
        self._text_rot_spin.setRange(0, 359)
        self._text_rot_spin.setSuffix("°")
        self._text_rot_spin.setWrapping(True)
        self._text_rot_spin.setValue(int(tool.rotation) % 360)
        self._text_rot_spin.setFixedWidth(60)
        self._text_rot_spin.valueChanged.connect(self._on_text_rotation_changed)
        rot_slider_row.addWidget(self._text_rot_spin)
        style_gl.addLayout(rot_slider_row)

        # Rotation preset buttons
        self._text_rot_buttons: list[QPushButton] = []
        rot_btn_layout = QHBoxLayout()
        rot_btn_layout.setSpacing(2)
        for deg in (0, 45, 90, 180, 270):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(32)
            btn.setChecked(deg == int(tool.rotation) % 360)
            btn.clicked.connect(
                lambda _, d=deg: self._set_text_rotation(d)
            )
            rot_btn_layout.addWidget(btn)
            self._text_rot_buttons.append(btn)
        rot_btn_layout.addStretch()
        style_gl.addLayout(rot_btn_layout)

        layout.addWidget(style_group)

        # ===== Outline group =====
        outline_group = QGroupBox("Outline")
        outline_gl = QVBoxLayout(outline_group)
        outline_gl.setContentsMargins(6, 4, 6, 4)

        self._text_outline_cb = QCheckBox("Enable Outline")
        self._text_outline_cb.setChecked(tool.outline)
        self._text_outline_cb.toggled.connect(self._on_text_outline_toggled)
        outline_gl.addWidget(self._text_outline_cb)

        self._text_outline_row = QWidget()
        ol_vl = QVBoxLayout(self._text_outline_row)
        ol_vl.setContentsMargins(0, 0, 0, 0)

        ol_color_row = QHBoxLayout()
        ol_color_row.addWidget(QLabel("Color:"))
        self._text_ol_color_btn = QPushButton()
        self._text_ol_color_btn.setFixedSize(40, 25)
        update_color_btn(self._text_ol_color_btn, QColor(tool.outline_color))
        self._text_ol_color_btn.clicked.connect(self._on_text_outline_color_pick)
        ol_color_row.addWidget(self._text_ol_color_btn)
        ol_color_row.addStretch()
        ol_vl.addLayout(ol_color_row)

        ol_vl.addWidget(QLabel("Width:"))
        ol_w_row = QHBoxLayout()
        self._text_ol_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._text_ol_width_slider.setRange(1, 100)  # 0.1-10.0 in 0.1 steps
        self._text_ol_width_slider.setValue(int(tool.outline_width * 10))
        self._text_ol_width_slider.valueChanged.connect(self._on_text_ol_width_slider)
        ol_w_row.addWidget(self._text_ol_width_slider, stretch=1)
        self._text_ol_width_spin = QDoubleSpinBox()
        self._text_ol_width_spin.setRange(0.1, 10.0)
        self._text_ol_width_spin.setSingleStep(0.1)
        self._text_ol_width_spin.setDecimals(1)
        self._text_ol_width_spin.setValue(tool.outline_width)
        self._text_ol_width_spin.setFixedWidth(60)
        self._text_ol_width_spin.valueChanged.connect(self._on_text_ol_width_spin)
        ol_w_row.addWidget(self._text_ol_width_spin)
        ol_vl.addLayout(ol_w_row)

        outline_gl.addWidget(self._text_outline_row)
        self._text_outline_row.setEnabled(tool.outline)

        layout.addWidget(outline_group)

        # ===== Rendering group =====
        render_group = QGroupBox("Rendering")
        render_gl = QVBoxLayout(render_group)
        render_gl.setContentsMargins(6, 4, 6, 4)

        self._text_over_grid_cb = QCheckBox("Draw over Grid")
        self._text_over_grid_cb.setChecked(tool.over_grid)
        self._text_over_grid_cb.setToolTip(
            "Render this text above the hex grid (like sketch objects)"
        )
        self._text_over_grid_cb.toggled.connect(self._on_text_over_grid_changed)
        render_gl.addWidget(self._text_over_grid_cb)

        layout.addWidget(render_group)

        # ===== Shadow group (layer-level) =====
        _layer = tool._get_active_text_layer()
        shadow_group = QGroupBox("Shadow")
        shadow_gl = QVBoxLayout(shadow_group)
        shadow_gl.setContentsMargins(6, 4, 6, 4)

        self._shadow_cb = QCheckBox("Enable Shadow")
        self._shadow_cb.setChecked(_layer.shadow_enabled if _layer else False)
        self._shadow_cb.toggled.connect(self._on_shadow_toggled)
        shadow_gl.addWidget(self._shadow_cb)

        self._shadow_container = QWidget()
        sc_layout = QVBoxLayout(self._shadow_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)

        # Type
        st_row = QHBoxLayout()
        st_row.addWidget(QLabel("Type:"))
        self._shadow_type_combo = QComboBox()
        self._shadow_type_combo.addItems(["Outer", "Inner"])
        self._shadow_type_combo.setCurrentText(
            "Inner" if (_layer and _layer.shadow_type == "inner") else "Outer"
        )
        self._shadow_type_combo.currentTextChanged.connect(self._on_shadow_type)
        st_row.addWidget(self._shadow_type_combo, 1)
        sc_layout.addLayout(st_row)

        # Color
        sc_row = QHBoxLayout()
        sc_row.addWidget(QLabel("Color:"))
        self._shadow_color_btn = QPushButton()
        self._shadow_color_btn.setFixedSize(40, 25)
        update_color_btn(self._shadow_color_btn, QColor(_layer.shadow_color if _layer else "#000000"))
        self._shadow_color_btn.clicked.connect(self._on_shadow_color)
        sc_row.addWidget(self._shadow_color_btn)
        sc_row.addStretch()
        sc_layout.addLayout(sc_row)

        # Opacity
        so_row = QHBoxLayout()
        so_row.addWidget(QLabel("Opacity:"))
        self._shadow_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_opacity_slider.setRange(0, 100)
        self._shadow_opacity_slider.setValue(int((_layer.shadow_opacity if _layer else 0.5) * 100))
        self._shadow_opacity_slider.valueChanged.connect(self._on_shadow_opacity_slider)
        so_row.addWidget(self._shadow_opacity_slider, 1)
        self._shadow_opacity_spin = QDoubleSpinBox()
        self._shadow_opacity_spin.setRange(0.0, 1.0)
        self._shadow_opacity_spin.setSingleStep(0.05)
        self._shadow_opacity_spin.setDecimals(2)
        self._shadow_opacity_spin.setFixedWidth(60)
        self._shadow_opacity_spin.setValue(_layer.shadow_opacity if _layer else 0.5)
        self._shadow_opacity_spin.valueChanged.connect(self._on_shadow_opacity_spin)
        so_row.addWidget(self._shadow_opacity_spin)
        sc_layout.addLayout(so_row)

        # Angle
        sa_row = QHBoxLayout()
        sa_row.addWidget(QLabel("Angle:"))
        self._shadow_angle_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_angle_slider.setRange(0, 360)
        self._shadow_angle_slider.setValue(int(_layer.shadow_angle if _layer else 120))
        self._shadow_angle_slider.valueChanged.connect(self._on_shadow_angle_slider)
        sa_row.addWidget(self._shadow_angle_slider, 1)
        self._shadow_angle_spin = QSpinBox()
        self._shadow_angle_spin.setRange(0, 360)
        self._shadow_angle_spin.setSuffix("°")
        self._shadow_angle_spin.setFixedWidth(60)
        self._shadow_angle_spin.setValue(int(_layer.shadow_angle if _layer else 120))
        self._shadow_angle_spin.valueChanged.connect(self._on_shadow_angle_spin)
        sa_row.addWidget(self._shadow_angle_spin)
        sc_layout.addLayout(sa_row)

        # Distance
        sd_row = QHBoxLayout()
        sd_row.addWidget(QLabel("Dist:"))
        self._shadow_dist_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_dist_slider.setRange(0, 50)
        self._shadow_dist_slider.setValue(int(_layer.shadow_distance if _layer else 5))
        self._shadow_dist_slider.valueChanged.connect(self._on_shadow_dist_slider)
        sd_row.addWidget(self._shadow_dist_slider, 1)
        self._shadow_dist_spin = QDoubleSpinBox()
        self._shadow_dist_spin.setRange(0.0, 50.0)
        self._shadow_dist_spin.setSingleStep(1.0)
        self._shadow_dist_spin.setDecimals(1)
        self._shadow_dist_spin.setFixedWidth(60)
        self._shadow_dist_spin.setValue(_layer.shadow_distance if _layer else 5.0)
        self._shadow_dist_spin.valueChanged.connect(self._on_shadow_dist_spin)
        sd_row.addWidget(self._shadow_dist_spin)
        sc_layout.addLayout(sd_row)

        # Spread
        ssp_row = QHBoxLayout()
        ssp_row.addWidget(QLabel("Spread:"))
        self._shadow_spread_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_spread_slider.setRange(0, 100)
        self._shadow_spread_slider.setValue(int(_layer.shadow_spread if _layer else 0))
        self._shadow_spread_slider.valueChanged.connect(self._on_shadow_spread_slider)
        ssp_row.addWidget(self._shadow_spread_slider, 1)
        self._shadow_spread_spin = QSpinBox()
        self._shadow_spread_spin.setRange(0, 100)
        self._shadow_spread_spin.setSuffix("%")
        self._shadow_spread_spin.setFixedWidth(60)
        self._shadow_spread_spin.setValue(int(_layer.shadow_spread if _layer else 0))
        self._shadow_spread_spin.valueChanged.connect(self._on_shadow_spread_spin)
        ssp_row.addWidget(self._shadow_spread_spin)
        sc_layout.addLayout(ssp_row)

        # Size
        ss_row = QHBoxLayout()
        ss_row.addWidget(QLabel("Size:"))
        self._shadow_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_size_slider.setRange(0, 50)
        self._shadow_size_slider.setValue(int(_layer.shadow_size if _layer else 5))
        self._shadow_size_slider.valueChanged.connect(self._on_shadow_size_slider)
        ss_row.addWidget(self._shadow_size_slider, 1)
        self._shadow_size_spin = QDoubleSpinBox()
        self._shadow_size_spin.setRange(0.0, 50.0)
        self._shadow_size_spin.setSingleStep(1.0)
        self._shadow_size_spin.setDecimals(1)
        self._shadow_size_spin.setFixedWidth(60)
        self._shadow_size_spin.setValue(_layer.shadow_size if _layer else 5.0)
        self._shadow_size_spin.valueChanged.connect(self._on_shadow_size_spin)
        ss_row.addWidget(self._shadow_size_spin)
        sc_layout.addLayout(ss_row)

        shadow_gl.addWidget(self._shadow_container)
        self._shadow_container.setEnabled(_layer.shadow_enabled if _layer else False)
        layout.addWidget(shadow_group)

        return widget

    def close_sidebar(self) -> None:
        """Hide text preset sidebar and uncheck expand button."""
        if self._tsp_preset_sidebar:
            self._tsp_preset_sidebar.hide()
        try:
            if hasattr(self, "_tsp_expand_btn"):
                self._tsp_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Text tool handlers ---

    def _on_text_mode_changed(self, button_id: int, checked: bool) -> None:
        if not checked:
            return
        if button_id == 0:
            self._text_tool.mode = "place"
            self._text_tool._selected = None
            self._text_tool._notify_selection()
        else:
            self._text_tool.mode = "select"

    # --- Selection sync ---

    def _on_selection_changed(self, obj) -> None:
        """Called when the selected text object changes."""
        if obj:
            self._sync_widgets_from_object(obj)

    def _sync_widgets_from_object(self, obj) -> None:
        """Sync all text widgets from a selected TextObject."""
        tool = self._text_tool
        if tool is None:
            return

        # Update tool properties so new placements inherit current selection's style
        tool.pending_text = obj.text
        tool.font_family = obj.font_family
        tool.font_size = obj.font_size
        tool.bold = obj.bold
        tool.italic = obj.italic
        tool.underline = obj.underline
        tool.color = obj.color
        tool.alignment = obj.alignment
        tool.opacity = obj.opacity
        tool.rotation = obj.rotation
        tool.outline = obj.outline
        tool.outline_color = obj.outline_color
        tool.outline_width = obj.outline_width
        tool.over_grid = obj.over_grid

        # Sync all other widgets via existing helper
        self._sync_text_ui_from_tool()

    def _apply_to_selected(self, **changes) -> None:
        """Apply property changes to the selected text object via an undoable command."""
        if (
            self._text_tool
            and self._text_tool.mode == "select"
            and self._text_tool._selected is not None
        ):
            layer = self._text_tool._get_active_text_layer()
            if layer:
                cmd = EditTextCommand(layer, self._text_tool._selected, **changes)
                self._text_tool._command_stack.execute(cmd)

    def _on_text_content_changed(self, text: str) -> None:
        self._text_tool.pending_text = text
        self._apply_to_selected(text=text)

    def _on_text_font_changed(self, font) -> None:
        self._text_tool.font_family = font.family()
        self._apply_to_selected(font_family=font.family())

    def _on_text_bold_changed(self, checked: bool) -> None:
        self._text_tool.bold = checked
        self._apply_to_selected(bold=checked)

    def _on_text_italic_changed(self, checked: bool) -> None:
        self._text_tool.italic = checked
        self._apply_to_selected(italic=checked)

    def _on_text_underline_changed(self, checked: bool) -> None:
        self._text_tool.underline = checked
        self._apply_to_selected(underline=checked)

    # --- Size slider/spin sync ---

    def _on_text_size_slider(self, value: int) -> None:
        self._text_tool.font_size = float(value)
        self._text_size_spin.blockSignals(True)
        self._text_size_spin.setValue(float(value))
        self._text_size_spin.blockSignals(False)
        self._apply_to_selected(font_size=float(value))

    def _on_text_size_spin(self, value: float) -> None:
        self._text_tool.font_size = value
        self._text_size_slider.blockSignals(True)
        self._text_size_slider.setValue(int(value))
        self._text_size_slider.blockSignals(False)
        self._apply_to_selected(font_size=value)

    def _on_text_size_changed(self, value: float) -> None:
        self._text_tool.font_size = value
        self._apply_to_selected(font_size=value)

    def _on_text_color_pick(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._text_tool.color), self.dock, "Pick Text Color"
        )
        if color.isValid():
            self._text_tool.color = color.name()
            update_color_btn(self._text_color_btn, color)
            self._apply_to_selected(color=color.name())

    def _on_text_align_changed(self) -> None:
        alignment = self._text_align_combo.currentData()
        self._text_tool.alignment = alignment
        self._apply_to_selected(alignment=alignment)

    def _on_text_opacity_changed(self, value: int) -> None:
        opacity = value / 100.0
        self._text_tool.opacity = opacity
        self._text_opacity_label.setText(f"{value}%")
        self._apply_to_selected(opacity=opacity)

    def _on_text_rot_slider(self, value: int) -> None:
        self._text_tool.rotation = float(value)
        self._text_rot_spin.blockSignals(True)
        self._text_rot_spin.setValue(value)
        self._text_rot_spin.blockSignals(False)
        self._sync_text_rot_buttons(value)
        self._apply_to_selected(rotation=float(value))

    def _on_text_rotation_changed(self, value: int) -> None:
        self._text_tool.rotation = float(value)
        self._text_rot_slider.blockSignals(True)
        self._text_rot_slider.setValue(value)
        self._text_rot_slider.blockSignals(False)
        self._sync_text_rot_buttons(value)
        self._apply_to_selected(rotation=float(value))

    def _set_text_rotation(self, degrees: int) -> None:
        """Set rotation from preset button (syncs slider + spin)."""
        self._text_tool.rotation = float(degrees)
        self._text_rot_slider.blockSignals(True)
        self._text_rot_slider.setValue(degrees)
        self._text_rot_slider.blockSignals(False)
        self._text_rot_spin.blockSignals(True)
        self._text_rot_spin.setValue(degrees)
        self._text_rot_spin.blockSignals(False)
        self._sync_text_rot_buttons(degrees)
        self._apply_to_selected(rotation=float(degrees))

    def _sync_text_rot_buttons(self, value: int) -> None:
        """Highlight the preset button matching the current rotation value."""
        _PRESETS = (0, 45, 90, 180, 270)
        for i, preset in enumerate(_PRESETS):
            self._text_rot_buttons[i].setChecked(preset == value)

    # --- Outline width slider/spin sync ---

    def _on_text_ol_width_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._text_tool.outline_width = real_val
        self._text_ol_width_spin.blockSignals(True)
        self._text_ol_width_spin.setValue(real_val)
        self._text_ol_width_spin.blockSignals(False)
        self._apply_to_selected(outline_width=real_val)

    def _on_text_ol_width_spin(self, value: float) -> None:
        self._text_tool.outline_width = value
        self._text_ol_width_slider.blockSignals(True)
        self._text_ol_width_slider.setValue(int(value * 10))
        self._text_ol_width_slider.blockSignals(False)
        self._apply_to_selected(outline_width=value)

    def _on_text_outline_toggled(self, checked: bool) -> None:
        self._text_tool.outline = checked
        self._text_outline_row.setEnabled(checked)
        self._apply_to_selected(outline=checked)

    def _on_text_outline_color_pick(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._text_tool.outline_color), self.dock, "Pick Outline Color"
        )
        if color.isValid():
            self._text_tool.outline_color = color.name()
            update_color_btn(self._text_ol_color_btn, color)
            self._apply_to_selected(outline_color=color.name())

    # --- Text preset handlers ---

    def _refresh_text_preset_combo(self) -> None:
        """Reload the preset combo from disk."""
        self._text_preset_combo.blockSignals(True)
        current = self._text_preset_combo.currentText()
        self._text_preset_combo.clear()
        names = list_text_presets()
        self._text_preset_combo.addItems(names)
        # Restore selection if still exists
        idx = self._text_preset_combo.findText(current)
        if idx >= 0:
            self._text_preset_combo.setCurrentIndex(idx)
        elif names:
            self._text_preset_combo.setCurrentIndex(0)
        self._text_preset_combo.blockSignals(False)
        self._update_text_preset_preview()
        self._tsp_sync_sidebar()

    def _on_text_preset_selected(self, name: str) -> None:
        """Update preview and auto-load when preset selection changes."""
        self._update_text_preset_preview()
        if name:
            self._on_text_preset_load()

    def _update_text_preset_preview(self) -> None:
        """Render a preview of the selected preset or current tool settings."""
        name = self._text_preset_combo.currentText()
        if name:
            try:
                preset = load_text_preset(name)
            except (FileNotFoundError, json.JSONDecodeError):
                preset = self._current_tool_as_preset()
        else:
            preset = self._current_tool_as_preset()

        self._render_text_preset_preview(preset)

    def _current_tool_as_preset(self) -> TextPreset:
        """Build a TextPreset from the current tool settings (for preview)."""
        tool = self._text_tool
        return TextPreset(
            name=tool.pending_text or "Sample",
            font_family=tool.font_family,
            font_size=tool.font_size,
            bold=tool.bold,
            italic=tool.italic,
            underline=tool.underline,
            color=tool.color,
            alignment=tool.alignment,
            opacity=tool.opacity,
            rotation=tool.rotation,
            outline=tool.outline,
            outline_color=tool.outline_color,
            outline_width=tool.outline_width,
            over_grid=tool.over_grid,
        )

    def _render_text_preset_preview(self, preset: TextPreset) -> None:
        """Paint a preview pixmap for the given preset."""
        w = self._text_preset_preview.width() or 180
        h = self._text_preset_preview.height() or 40

        pixmap = QPixmap(w, h)
        pixmap.fill(QColor("#d0d0d0"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        font = QFont(preset.font_family, int(preset.font_size))
        font.setBold(preset.bold)
        font.setItalic(preset.italic)
        font.setUnderline(preset.underline)

        # Scale font to fit within preview height
        fm = QFontMetrics(font)
        max_font_h = h - 6
        if fm.height() > max_font_h:
            scale_factor = max_font_h / fm.height()
            font.setPointSizeF(preset.font_size * scale_factor)
            fm = QFontMetrics(font)

        sample = preset.name
        text_width = fm.horizontalAdvance(sample)
        text_height = fm.height()

        # Center text in preview
        x = (w - text_width) / 2
        y = (h + fm.ascent() - fm.descent()) / 2

        painter.setOpacity(preset.opacity)

        if preset.outline:
            path = QPainterPath()
            path.addText(x, y, font, sample)
            pen = QPen(QColor(preset.outline_color), preset.outline_width * 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(QColor(preset.color))
            painter.drawPath(path)
        else:
            painter.setPen(QColor(preset.color))
            painter.setFont(font)
            painter.drawText(int(x), int(y), sample)

        painter.end()
        self._text_preset_preview.setPixmap(pixmap)

    def _on_text_preset_load(self) -> None:
        """Apply the selected preset to the text tool settings."""
        name = self._text_preset_combo.currentText()
        if not name:
            return
        try:
            preset = load_text_preset(name)
        except (FileNotFoundError, json.JSONDecodeError):
            QMessageBox.warning(self.dock, "Load Preset", f"Could not load preset '{name}'.")
            return

        tool = self._text_tool

        # Apply all settings to the tool
        tool.font_family = preset.font_family
        tool.font_size = preset.font_size
        tool.bold = preset.bold
        tool.italic = preset.italic
        tool.underline = preset.underline
        tool.color = preset.color
        tool.alignment = preset.alignment
        tool.opacity = preset.opacity
        tool.rotation = preset.rotation
        tool.outline = preset.outline
        tool.outline_color = preset.outline_color
        tool.outline_width = preset.outline_width
        tool.over_grid = preset.over_grid

        # Sync all UI widgets to match the new values
        self._sync_text_ui_from_tool()
        self._tsp_sync_sidebar()

    def _sync_text_ui_from_tool(self) -> None:
        """Update all text option widgets to match current tool values."""
        tool = self._text_tool

        self._text_content_edit.blockSignals(True)
        self._text_content_edit.setText(tool.pending_text)
        self._text_content_edit.blockSignals(False)

        self._text_font_combo.blockSignals(True)
        self._text_font_combo.setCurrentFont(QFont(tool.font_family))
        self._text_font_combo.blockSignals(False)

        self._text_size_slider.blockSignals(True)
        self._text_size_slider.setValue(int(tool.font_size))
        self._text_size_slider.blockSignals(False)
        self._text_size_spin.blockSignals(True)
        self._text_size_spin.setValue(tool.font_size)
        self._text_size_spin.blockSignals(False)

        self._text_bold_cb.blockSignals(True)
        self._text_bold_cb.setChecked(tool.bold)
        self._text_bold_cb.blockSignals(False)

        self._text_italic_cb.blockSignals(True)
        self._text_italic_cb.setChecked(tool.italic)
        self._text_italic_cb.blockSignals(False)

        self._text_underline_cb.blockSignals(True)
        self._text_underline_cb.setChecked(tool.underline)
        self._text_underline_cb.blockSignals(False)

        update_color_btn(self._text_color_btn, QColor(tool.color))

        idx = self._text_align_combo.findData(tool.alignment)
        if idx >= 0:
            self._text_align_combo.blockSignals(True)
            self._text_align_combo.setCurrentIndex(idx)
            self._text_align_combo.blockSignals(False)

        self._text_opacity_slider.blockSignals(True)
        self._text_opacity_slider.setValue(int(tool.opacity * 100))
        self._text_opacity_slider.blockSignals(False)
        self._text_opacity_label.setText(f"{int(tool.opacity * 100)}%")

        rot_val = int(tool.rotation) % 360
        self._text_rot_slider.blockSignals(True)
        self._text_rot_slider.setValue(rot_val)
        self._text_rot_slider.blockSignals(False)
        self._text_rot_spin.blockSignals(True)
        self._text_rot_spin.setValue(rot_val)
        self._text_rot_spin.blockSignals(False)
        self._sync_text_rot_buttons(rot_val)

        self._text_outline_cb.blockSignals(True)
        self._text_outline_cb.setChecked(tool.outline)
        self._text_outline_cb.blockSignals(False)
        self._text_outline_row.setEnabled(tool.outline)

        update_color_btn(self._text_ol_color_btn, QColor(tool.outline_color))

        self._text_ol_width_slider.blockSignals(True)
        self._text_ol_width_slider.setValue(int(tool.outline_width * 10))
        self._text_ol_width_slider.blockSignals(False)
        self._text_ol_width_spin.blockSignals(True)
        self._text_ol_width_spin.setValue(tool.outline_width)
        self._text_ol_width_spin.blockSignals(False)

        self._text_over_grid_cb.blockSignals(True)
        self._text_over_grid_cb.setChecked(tool.over_grid)
        self._text_over_grid_cb.blockSignals(False)

    def _on_text_preset_save(self) -> None:
        """Save current text settings as a named preset."""
        name, ok = QInputDialog.getText(
            self.dock, "Save Text Preset", "Preset name:"
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        # Check if exists
        existing = list_text_presets()
        if name in existing:
            reply = QMessageBox.question(
                self.dock, "Overwrite Preset",
                f"Preset '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        tool = self._text_tool
        preset = TextPreset(
            name=name,
            font_family=tool.font_family,
            font_size=tool.font_size,
            bold=tool.bold,
            italic=tool.italic,
            underline=tool.underline,
            color=tool.color,
            alignment=tool.alignment,
            opacity=tool.opacity,
            rotation=tool.rotation,
            outline=tool.outline,
            outline_color=tool.outline_color,
            outline_width=tool.outline_width,
            over_grid=tool.over_grid,
        )
        save_text_preset(preset)
        self._refresh_text_preset_combo()

        # Select the newly saved preset
        idx = self._text_preset_combo.findText(name)
        if idx >= 0:
            self._text_preset_combo.setCurrentIndex(idx)

    def _on_text_preset_delete(self) -> None:
        """Delete the selected preset."""
        name = self._text_preset_combo.currentText()
        if not name:
            return
        if is_builtin_text_preset(name):
            QMessageBox.information(
                self.dock, "Built-in Preset",
                f"'{name}' is a built-in preset and cannot be deleted.",
            )
            return
        reply = QMessageBox.question(
            self.dock, "Delete Preset",
            f"Delete preset '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_text_preset(name)
            self._refresh_text_preset_combo()

    # --- Preset sidebar ---

    def _tsp_on_toggle_sidebar(self, checked: bool) -> None:
        """Toggle the expanded preset browser sidebar."""
        if checked:
            self.dock._save_panel_width()
            if not self._tsp_preset_sidebar:
                self._tsp_preset_sidebar = TextPresetSidebar(self.dock.window())
                self._tsp_preset_sidebar.preset_clicked.connect(
                    self._tsp_on_sidebar_preset_clicked,
                )
                self._tsp_preset_sidebar.closed.connect(
                    self._tsp_on_preset_sidebar_closed,
                )
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea,
                    self._tsp_preset_sidebar,
                )
                main_win.splitDockWidget(
                    self.dock, self._tsp_preset_sidebar, Qt.Orientation.Horizontal,
                )
            self._tsp_preset_sidebar.show()
            self._tsp_sync_sidebar()
        else:
            if self._tsp_preset_sidebar:
                self._tsp_preset_sidebar.hide()
            self.dock._restore_panel_width()

    def _tsp_sync_sidebar(self) -> None:
        """Update preset sidebar contents from disk."""
        if not self._tsp_preset_sidebar or not self._tsp_preset_sidebar.isVisible():
            return
        names = list_text_presets()
        selected = self._text_preset_combo.currentText() or None
        self._tsp_preset_sidebar.set_presets(names, selected)

    def _tsp_on_sidebar_preset_clicked(self, name: str) -> None:
        """Handle preset selection from the sidebar - load it."""
        idx = self._text_preset_combo.findText(name)
        if idx >= 0:
            self._text_preset_combo.setCurrentIndex(idx)
        self._on_text_preset_load()
        if self._tsp_preset_sidebar:
            self._tsp_preset_sidebar.set_selected(name)

    def _tsp_on_preset_sidebar_closed(self) -> None:
        """Handle preset sidebar close button."""
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_tsp_expand_btn"):
                self._tsp_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Rendering ---

    def _on_text_over_grid_changed(self, checked: bool) -> None:
        self._text_tool.over_grid = checked
        self._apply_to_selected(over_grid=checked)

    # --- Shadow (layer-level) ---

    def sync_shadow_from_layer(self) -> None:
        """Sync shadow widgets from the currently active TextLayer."""
        layer = self._get_text_layer()
        if not layer:
            return
        self._shadow_cb.blockSignals(True)
        self._shadow_cb.setChecked(layer.shadow_enabled)
        self._shadow_cb.blockSignals(False)
        self._shadow_container.setEnabled(layer.shadow_enabled)
        self._shadow_type_combo.blockSignals(True)
        self._shadow_type_combo.setCurrentText(
            "Inner" if layer.shadow_type == "inner" else "Outer"
        )
        self._shadow_type_combo.blockSignals(False)
        update_color_btn(self._shadow_color_btn, QColor(layer.shadow_color))
        self._shadow_opacity_slider.blockSignals(True)
        self._shadow_opacity_slider.setValue(int(layer.shadow_opacity * 100))
        self._shadow_opacity_slider.blockSignals(False)
        self._shadow_opacity_spin.blockSignals(True)
        self._shadow_opacity_spin.setValue(layer.shadow_opacity)
        self._shadow_opacity_spin.blockSignals(False)
        self._shadow_angle_slider.blockSignals(True)
        self._shadow_angle_slider.setValue(int(layer.shadow_angle))
        self._shadow_angle_slider.blockSignals(False)
        self._shadow_angle_spin.blockSignals(True)
        self._shadow_angle_spin.setValue(int(layer.shadow_angle))
        self._shadow_angle_spin.blockSignals(False)
        self._shadow_dist_slider.blockSignals(True)
        self._shadow_dist_slider.setValue(int(layer.shadow_distance))
        self._shadow_dist_slider.blockSignals(False)
        self._shadow_dist_spin.blockSignals(True)
        self._shadow_dist_spin.setValue(layer.shadow_distance)
        self._shadow_dist_spin.blockSignals(False)
        self._shadow_spread_slider.blockSignals(True)
        self._shadow_spread_slider.setValue(int(layer.shadow_spread))
        self._shadow_spread_slider.blockSignals(False)
        self._shadow_spread_spin.blockSignals(True)
        self._shadow_spread_spin.setValue(int(layer.shadow_spread))
        self._shadow_spread_spin.blockSignals(False)
        self._shadow_size_slider.blockSignals(True)
        self._shadow_size_slider.setValue(int(layer.shadow_size))
        self._shadow_size_slider.blockSignals(False)
        self._shadow_size_spin.blockSignals(True)
        self._shadow_size_spin.setValue(layer.shadow_size)
        self._shadow_size_spin.blockSignals(False)

    def _get_text_layer(self):
        """Return the currently active TextLayer, or None."""
        if self._text_tool is None:
            return None
        return self._text_tool._get_active_text_layer()

    def _apply_layer_effect(self, **changes) -> None:
        from app.commands.text_commands import EditTextLayerEffectsCommand
        layer = self._get_text_layer()
        if layer is None:
            return
        cmd = EditTextLayerEffectsCommand(layer, **changes)
        self._text_tool._command_stack.execute(cmd)

    def _on_shadow_toggled(self, checked: bool) -> None:
        self._shadow_container.setEnabled(checked)
        self._apply_layer_effect(shadow_enabled=checked)

    def _on_shadow_type(self, text: str) -> None:
        self._apply_layer_effect(shadow_type="inner" if text == "Inner" else "outer")

    def _on_shadow_color(self) -> None:
        layer = self._get_text_layer()
        if layer is None:
            return
        old_color = QColor(layer.shadow_color)
        dlg = QColorDialog(old_color, self.dock.widget())
        if dlg.exec():
            update_color_btn(self._shadow_color_btn, dlg.selectedColor())
            self._apply_layer_effect(shadow_color=dlg.selectedColor().name())

    def _on_shadow_opacity_slider(self, val: int) -> None:
        self._shadow_opacity_spin.blockSignals(True)
        self._shadow_opacity_spin.setValue(val / 100.0)
        self._shadow_opacity_spin.blockSignals(False)
        self._apply_layer_effect(shadow_opacity=val / 100.0)

    def _on_shadow_opacity_spin(self, val: float) -> None:
        self._shadow_opacity_slider.blockSignals(True)
        self._shadow_opacity_slider.setValue(int(val * 100))
        self._shadow_opacity_slider.blockSignals(False)
        self._apply_layer_effect(shadow_opacity=val)

    def _on_shadow_angle_slider(self, val: int) -> None:
        self._shadow_angle_spin.blockSignals(True)
        self._shadow_angle_spin.setValue(val)
        self._shadow_angle_spin.blockSignals(False)
        self._apply_layer_effect(shadow_angle=float(val))

    def _on_shadow_angle_spin(self, val: int) -> None:
        self._shadow_angle_slider.blockSignals(True)
        self._shadow_angle_slider.setValue(val)
        self._shadow_angle_slider.blockSignals(False)
        self._apply_layer_effect(shadow_angle=float(val))

    def _on_shadow_dist_slider(self, val: int) -> None:
        self._shadow_dist_spin.blockSignals(True)
        self._shadow_dist_spin.setValue(float(val))
        self._shadow_dist_spin.blockSignals(False)
        self._apply_layer_effect(shadow_distance=float(val))

    def _on_shadow_dist_spin(self, val: float) -> None:
        self._shadow_dist_slider.blockSignals(True)
        self._shadow_dist_slider.setValue(int(val))
        self._shadow_dist_slider.blockSignals(False)
        self._apply_layer_effect(shadow_distance=val)

    def _on_shadow_spread_slider(self, val: int) -> None:
        self._shadow_spread_spin.blockSignals(True)
        self._shadow_spread_spin.setValue(val)
        self._shadow_spread_spin.blockSignals(False)
        self._apply_layer_effect(shadow_spread=float(val))

    def _on_shadow_spread_spin(self, val: int) -> None:
        self._shadow_spread_slider.blockSignals(True)
        self._shadow_spread_slider.setValue(val)
        self._shadow_spread_slider.blockSignals(False)
        self._apply_layer_effect(shadow_spread=float(val))

    def _on_shadow_size_slider(self, val: int) -> None:
        self._shadow_size_spin.blockSignals(True)
        self._shadow_size_spin.setValue(float(val))
        self._shadow_size_spin.blockSignals(False)
        self._apply_layer_effect(shadow_size=float(val))

    def _on_shadow_size_spin(self, val: float) -> None:
        self._shadow_size_slider.blockSignals(True)
        self._shadow_size_slider.setValue(int(val))
        self._shadow_size_slider.blockSignals(False)
        self._apply_layer_effect(shadow_size=val)
