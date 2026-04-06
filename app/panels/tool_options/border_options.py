"""Border tool options builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.commands.border_commands import EditBorderCommand, EditBorderLayerEffectsCommand
from app.layers.border_layer import BorderLayer
from app.io.border_preset_manager import (
    BorderPreset,
    delete_border_preset,
    is_builtin_border_preset,
    list_border_presets,
    load_border_preset,
    save_border_preset,
)
from app.io.palette_manager import (
    ColorPalette,
    ensure_default_palette,
    list_palettes,
    load_palette,
)
from app.panels.tool_options.helpers import update_color_btn
from app.panels.tool_options.sidebar_widgets import (
    BorderPresetSidebar,
    render_border_preview,
)
from app.tools.border_tool import BorderTool

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel

_PALETTE_GRID_COLS = 4

_LINE_TYPES = ["Solid", "Dotted", "Dashed"]
_LINE_TYPE_MAP = {"Solid": "solid", "Dotted": "dotted", "Dashed": "dashed"}
_LINE_TYPE_REVERSE = {"solid": "Solid", "dotted": "Dotted", "dashed": "Dashed"}

_CAP_TYPES = ["Flat", "Round", "Square"]
_CAP_MAP = {"Flat": "flat", "Round": "round", "Square": "square"}
_CAP_REVERSE = {"flat": "Flat", "round": "Round", "square": "Square"}


class BorderOptions:
    """Builds and manages the border tool options UI."""

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._border_tool: BorderTool | None = None
        self._bsp_preset_sidebar: BorderPresetSidebar | None = None

    def create(self, tool: BorderTool) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        self._border_tool = tool
        tool.on_selection_changed = self._on_selection_changed

        # ===== Mode group =====
        mode_group = QGroupBox("Mode")
        mode_gl = QVBoxLayout(mode_group)
        mode_gl.setContentsMargins(6, 4, 6, 4)
        mode_btn_layout = QHBoxLayout()

        place_btn = QPushButton("Place")
        place_btn.setCheckable(True)
        place_btn.setChecked(tool.mode != "select")  # L07: init from tool state
        select_btn = QPushButton("Select")
        select_btn.setCheckable(True)
        select_btn.setChecked(tool.mode == "select")

        self._bo_mode_group = QButtonGroup(widget)
        self._bo_mode_group.setExclusive(True)
        self._bo_mode_group.addButton(place_btn, 0)
        self._bo_mode_group.addButton(select_btn, 1)
        self._bo_mode_group.idToggled.connect(self._on_bo_mode_changed)

        mode_btn_layout.addWidget(place_btn)
        mode_btn_layout.addWidget(select_btn)
        mode_btn_layout.addStretch()
        mode_gl.addLayout(mode_btn_layout)
        layout.addWidget(mode_group)

        # ===== Presets group =====
        preset_group = QGroupBox("Presets")
        preset_gl = QVBoxLayout(preset_group)
        preset_gl.setContentsMargins(6, 4, 6, 4)

        # Preview label
        self._bsp_preview = QLabel()
        self._bsp_preview.setFixedHeight(40)
        self._bsp_preview.setScaledContents(False)
        from PySide6.QtWidgets import QSizePolicy
        self._bsp_preview.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed,
        )
        self._bsp_preview.setStyleSheet(
            "background-color: #d0d0d0; border: 1px solid #999; padding: 2px;"
        )
        self._bsp_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preset_gl.addWidget(self._bsp_preview)

        # Combo
        combo_layout = QHBoxLayout()
        self._bsp_combo = QComboBox()
        self._bsp_combo.setMinimumWidth(60)
        self._bsp_combo.currentTextChanged.connect(self._bsp_on_selected)
        combo_layout.addWidget(self._bsp_combo, stretch=1)
        preset_gl.addLayout(combo_layout)

        # Expand button
        self._bsp_expand_btn = QPushButton("Expand")
        self._bsp_expand_btn.setCheckable(True)
        self._bsp_expand_btn.setToolTip("Show all presets in expanded sidebar")
        self._bsp_expand_btn.clicked.connect(self._bsp_on_toggle_sidebar)
        preset_gl.addWidget(self._bsp_expand_btn)

        # Buttons
        btn_layout = QHBoxLayout()
        load_btn = QPushButton("Load")
        load_btn.setToolTip("Apply selected preset to current settings")
        load_btn.clicked.connect(self._bsp_on_load)
        btn_layout.addWidget(load_btn)

        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save current settings as a new preset")
        save_btn.clicked.connect(self._bsp_on_save)
        btn_layout.addWidget(save_btn)

        del_btn = QPushButton("Del")
        del_btn.setToolTip("Delete selected preset")
        del_btn.clicked.connect(self._bsp_on_delete)
        btn_layout.addWidget(del_btn)
        preset_gl.addLayout(btn_layout)

        layout.addWidget(preset_group)

        # Populate preset combo
        self._bsp_refresh_combo()
        self._bsp_update_preview()

        # ===== Color group (with palette) =====
        self._bo_selected_palette_idx = -1
        self._bo_current_palette: ColorPalette | None = None
        self._bo_palette_color_buttons: list[QPushButton] = []

        color_group = QGroupBox("Color")
        color_gl = QVBoxLayout(color_group)
        color_gl.setContentsMargins(6, 4, 6, 4)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._bo_color_btn = QPushButton()
        self._bo_color_btn.setFixedSize(40, 25)
        update_color_btn(self._bo_color_btn, QColor(tool.color))
        self._bo_color_btn.clicked.connect(self._on_bo_color_pick)
        color_row.addWidget(self._bo_color_btn)
        color_row.addStretch()
        color_gl.addLayout(color_row)

        # Palette section
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        color_gl.addWidget(separator)

        self._bo_palette_combo = QComboBox()
        color_gl.addWidget(self._bo_palette_combo)

        self._bo_color_grid_widget = QWidget()
        self._bo_color_grid_layout = QGridLayout(self._bo_color_grid_widget)
        self._bo_color_grid_layout.setSpacing(3)
        self._bo_color_grid_layout.setContentsMargins(0, 0, 0, 0)
        color_gl.addWidget(self._bo_color_grid_widget)

        layout.addWidget(color_group)

        # ===== Width group =====
        width_group = QGroupBox("Width")
        width_gl = QVBoxLayout(width_group)
        width_gl.setContentsMargins(6, 4, 6, 4)

        width_gl.addWidget(QLabel("Width:"))
        width_row = QHBoxLayout()
        self._bo_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._bo_width_slider.setRange(1, 80)
        self._bo_width_slider.setValue(int(tool.width * 2))
        self._bo_width_slider.valueChanged.connect(self._on_bo_width_slider)
        width_row.addWidget(self._bo_width_slider, stretch=1)
        self._bo_width_spin = QDoubleSpinBox()
        self._bo_width_spin.setRange(0.5, 40.0)
        self._bo_width_spin.setSingleStep(0.5)
        self._bo_width_spin.setValue(tool.width)
        self._bo_width_spin.setFixedWidth(65)
        self._bo_width_spin.valueChanged.connect(self._on_bo_width_spin)
        width_row.addWidget(self._bo_width_spin)
        width_gl.addLayout(width_row)
        layout.addWidget(width_group)

        # ===== Line Type group =====
        line_type_group = QGroupBox("Line Type")
        lt_gl = QVBoxLayout(line_type_group)
        lt_gl.setContentsMargins(6, 4, 6, 4)

        self._bo_line_type_combo = QComboBox()
        self._bo_line_type_combo.addItems(_LINE_TYPES)
        current_label = _LINE_TYPE_REVERSE.get(tool.line_type, "Solid")
        idx = self._bo_line_type_combo.findText(current_label)
        if idx >= 0:
            self._bo_line_type_combo.setCurrentIndex(idx)
        self._bo_line_type_combo.currentTextChanged.connect(self._on_bo_line_type_changed)
        lt_gl.addWidget(self._bo_line_type_combo)

        # Element Size + Gap Size container (hidden for Solid)
        self._bo_lt_container = QWidget()
        lt_c_layout = QVBoxLayout(self._bo_lt_container)
        lt_c_layout.setContentsMargins(0, 0, 0, 0)

        lt_c_layout.addWidget(QLabel("Element Size:"))
        es_row = QHBoxLayout()
        self._bo_element_slider = QSlider(Qt.Orientation.Horizontal)
        self._bo_element_slider.setRange(1, 60)
        self._bo_element_slider.setValue(int(tool.element_size * 2))
        self._bo_element_slider.valueChanged.connect(self._on_bo_element_slider)
        es_row.addWidget(self._bo_element_slider, stretch=1)
        self._bo_element_spin = QDoubleSpinBox()
        self._bo_element_spin.setRange(0.5, 30.0)
        self._bo_element_spin.setSingleStep(0.5)
        self._bo_element_spin.setValue(tool.element_size)
        self._bo_element_spin.setFixedWidth(65)
        self._bo_element_spin.valueChanged.connect(self._on_bo_element_spin)
        es_row.addWidget(self._bo_element_spin)
        lt_c_layout.addLayout(es_row)

        lt_c_layout.addWidget(QLabel("Gap Size:"))
        gs_row = QHBoxLayout()
        self._bo_gap_slider = QSlider(Qt.Orientation.Horizontal)
        self._bo_gap_slider.setRange(1, 60)
        self._bo_gap_slider.setValue(int(tool.gap_size * 2))
        self._bo_gap_slider.valueChanged.connect(self._on_bo_gap_slider)
        gs_row.addWidget(self._bo_gap_slider, stretch=1)
        self._bo_gap_spin = QDoubleSpinBox()
        self._bo_gap_spin.setRange(0.5, 30.0)
        self._bo_gap_spin.setSingleStep(0.5)
        self._bo_gap_spin.setValue(tool.gap_size)
        self._bo_gap_spin.setFixedWidth(65)
        self._bo_gap_spin.valueChanged.connect(self._on_bo_gap_spin)
        gs_row.addWidget(self._bo_gap_spin)
        lt_c_layout.addLayout(gs_row)

        # Cap style (only relevant for dashed)
        self._bo_cap_container = QWidget()
        cap_c_layout = QHBoxLayout(self._bo_cap_container)
        cap_c_layout.setContentsMargins(0, 0, 0, 0)
        cap_c_layout.addWidget(QLabel("Cap:"))
        self._bo_cap_combo = QComboBox()
        self._bo_cap_combo.addItems(_CAP_TYPES)
        self._bo_cap_combo.setCurrentText(
            _CAP_REVERSE.get(tool.dash_cap, "Round"),
        )
        self._bo_cap_combo.currentTextChanged.connect(self._on_bo_cap_changed)
        cap_c_layout.addWidget(self._bo_cap_combo)
        lt_c_layout.addWidget(self._bo_cap_container)
        self._bo_cap_container.setEnabled(tool.line_type == "dashed")

        self._bo_lt_container.setEnabled(tool.line_type != "solid")
        lt_gl.addWidget(self._bo_lt_container)
        layout.addWidget(line_type_group)

        # ===== Outline group =====
        outline_group = QGroupBox("Outline")
        outline_gl = QVBoxLayout(outline_group)
        outline_gl.setContentsMargins(6, 4, 6, 4)

        self._bo_outline_cb = QCheckBox("Enable Outline")
        self._bo_outline_cb.setChecked(tool.outline)
        self._bo_outline_cb.toggled.connect(self._on_bo_outline_toggled)
        outline_gl.addWidget(self._bo_outline_cb)

        self._bo_ol_container = QWidget()
        ol_c_layout = QVBoxLayout(self._bo_ol_container)
        ol_c_layout.setContentsMargins(0, 0, 0, 0)

        ol_row = QHBoxLayout()
        ol_row.addWidget(QLabel("Color:"))
        self._bo_ol_color_btn = QPushButton()
        self._bo_ol_color_btn.setFixedSize(40, 25)
        update_color_btn(self._bo_ol_color_btn, QColor(tool.outline_color))
        self._bo_ol_color_btn.clicked.connect(self._on_bo_outline_color_pick)
        ol_row.addWidget(self._bo_ol_color_btn)
        ol_row.addStretch()
        ol_c_layout.addLayout(ol_row)

        ol_c_layout.addWidget(QLabel("Width:"))
        ol_w_row = QHBoxLayout()
        self._bo_ol_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._bo_ol_width_slider.setRange(1, 40)
        self._bo_ol_width_slider.setValue(int(tool.outline_width * 2))
        self._bo_ol_width_slider.valueChanged.connect(self._on_bo_ol_width_slider)
        ol_w_row.addWidget(self._bo_ol_width_slider, stretch=1)
        self._bo_ol_width_spin = QDoubleSpinBox()
        self._bo_ol_width_spin.setRange(0.5, 20.0)
        self._bo_ol_width_spin.setSingleStep(0.5)
        self._bo_ol_width_spin.setValue(tool.outline_width)
        self._bo_ol_width_spin.setFixedWidth(65)
        self._bo_ol_width_spin.valueChanged.connect(self._on_bo_ol_width_spin)
        ol_w_row.addWidget(self._bo_ol_width_spin)
        ol_c_layout.addLayout(ol_w_row)

        self._bo_ol_container.setEnabled(tool.outline)
        outline_gl.addWidget(self._bo_ol_container)
        layout.addWidget(outline_group)

        # ===== Offset group =====
        offset_group = QGroupBox("Offset")
        offset_gl = QVBoxLayout(offset_group)
        offset_gl.setContentsMargins(6, 4, 6, 4)

        offset_gl.addWidget(QLabel("Offset:"))
        offset_row = QHBoxLayout()
        self._bo_offset_slider = QSlider(Qt.Orientation.Horizontal)
        self._bo_offset_slider.setRange(0, 150)
        self._bo_offset_slider.setValue(int(tool.offset * 10))
        self._bo_offset_slider.valueChanged.connect(self._on_bo_offset_slider)
        offset_row.addWidget(self._bo_offset_slider, stretch=1)
        self._bo_offset_spin = QDoubleSpinBox()
        self._bo_offset_spin.setRange(0.0, 15.0)
        self._bo_offset_spin.setSingleStep(0.5)
        self._bo_offset_spin.setValue(tool.offset)
        self._bo_offset_spin.setFixedWidth(65)
        self._bo_offset_spin.valueChanged.connect(self._on_bo_offset_spin)
        offset_row.addWidget(self._bo_offset_spin)
        offset_gl.addLayout(offset_row)
        layout.addWidget(offset_group)

        # Initialize palette
        ensure_default_palette()
        self._bo_refresh_palette_combo()
        self._bo_palette_combo.currentTextChanged.connect(self._bo_on_palette_changed)
        idx = self._bo_palette_combo.findText("Default")
        if idx >= 0:
            self._bo_palette_combo.setCurrentIndex(idx)
        else:
            self._bo_on_palette_changed(self._bo_palette_combo.currentText())

        # ===== Shadow group =====
        layer = self._get_layer()
        shadow_group = QGroupBox("Shadow")
        shadow_gl = QVBoxLayout(shadow_group)
        shadow_gl.setContentsMargins(6, 4, 6, 4)

        self._shadow_cb = QCheckBox("Enable Shadow")
        self._shadow_cb.setChecked(layer.shadow_enabled if layer else False)
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
            "Inner" if (layer and layer.shadow_type == "inner") else "Outer"
        )
        self._shadow_type_combo.currentTextChanged.connect(self._on_shadow_type)
        st_row.addWidget(self._shadow_type_combo, 1)
        sc_layout.addLayout(st_row)

        # Color
        sc_row = QHBoxLayout()
        sc_row.addWidget(QLabel("Color:"))
        self._shadow_color_btn = QPushButton()
        self._shadow_color_btn.setFixedSize(40, 25)
        update_color_btn(self._shadow_color_btn, QColor(layer.shadow_color if layer else "#000000"))
        self._shadow_color_btn.clicked.connect(self._on_shadow_color)
        sc_row.addWidget(self._shadow_color_btn)
        sc_row.addStretch()
        sc_layout.addLayout(sc_row)

        # Opacity
        so_row = QHBoxLayout()
        so_row.addWidget(QLabel("Opacity:"))
        self._shadow_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_opacity_slider.setRange(0, 100)
        self._shadow_opacity_slider.setValue(int((layer.shadow_opacity if layer else 0.5) * 100))
        self._shadow_opacity_slider.valueChanged.connect(self._on_shadow_opacity_slider)
        so_row.addWidget(self._shadow_opacity_slider, 1)
        self._shadow_opacity_spin = QDoubleSpinBox()
        self._shadow_opacity_spin.setRange(0.0, 1.0)
        self._shadow_opacity_spin.setSingleStep(0.05)
        self._shadow_opacity_spin.setDecimals(2)
        self._shadow_opacity_spin.setFixedWidth(60)
        self._shadow_opacity_spin.setValue(layer.shadow_opacity if layer else 0.5)
        self._shadow_opacity_spin.valueChanged.connect(self._on_shadow_opacity_spin)
        so_row.addWidget(self._shadow_opacity_spin)
        sc_layout.addLayout(so_row)

        # Angle
        sa_row = QHBoxLayout()
        sa_row.addWidget(QLabel("Angle:"))
        self._shadow_angle_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_angle_slider.setRange(0, 360)
        self._shadow_angle_slider.setValue(int(layer.shadow_angle if layer else 120))
        self._shadow_angle_slider.valueChanged.connect(self._on_shadow_angle_slider)
        sa_row.addWidget(self._shadow_angle_slider, 1)
        self._shadow_angle_spin = QSpinBox()
        self._shadow_angle_spin.setRange(0, 360)
        self._shadow_angle_spin.setSuffix("°")
        self._shadow_angle_spin.setFixedWidth(60)
        self._shadow_angle_spin.setValue(int(layer.shadow_angle if layer else 120))
        self._shadow_angle_spin.valueChanged.connect(self._on_shadow_angle_spin)
        sa_row.addWidget(self._shadow_angle_spin)
        sc_layout.addLayout(sa_row)

        # Distance
        sd_row = QHBoxLayout()
        sd_row.addWidget(QLabel("Dist:"))
        self._shadow_dist_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_dist_slider.setRange(0, 50)
        self._shadow_dist_slider.setValue(int(layer.shadow_distance if layer else 5))
        self._shadow_dist_slider.valueChanged.connect(self._on_shadow_dist_slider)
        sd_row.addWidget(self._shadow_dist_slider, 1)
        self._shadow_dist_spin = QDoubleSpinBox()
        self._shadow_dist_spin.setRange(0.0, 50.0)
        self._shadow_dist_spin.setSingleStep(1.0)
        self._shadow_dist_spin.setDecimals(1)
        self._shadow_dist_spin.setFixedWidth(60)
        self._shadow_dist_spin.setValue(layer.shadow_distance if layer else 5.0)
        self._shadow_dist_spin.valueChanged.connect(self._on_shadow_dist_spin)
        sd_row.addWidget(self._shadow_dist_spin)
        sc_layout.addLayout(sd_row)

        # Spread
        ssp_row = QHBoxLayout()
        ssp_row.addWidget(QLabel("Spread:"))
        self._shadow_spread_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_spread_slider.setRange(0, 100)
        self._shadow_spread_slider.setValue(int(layer.shadow_spread if layer else 0))
        self._shadow_spread_slider.valueChanged.connect(self._on_shadow_spread_slider)
        ssp_row.addWidget(self._shadow_spread_slider, 1)
        self._shadow_spread_spin = QSpinBox()
        self._shadow_spread_spin.setRange(0, 100)
        self._shadow_spread_spin.setSuffix("%")
        self._shadow_spread_spin.setFixedWidth(60)
        self._shadow_spread_spin.setValue(int(layer.shadow_spread if layer else 0))
        self._shadow_spread_spin.valueChanged.connect(self._on_shadow_spread_spin)
        ssp_row.addWidget(self._shadow_spread_spin)
        sc_layout.addLayout(ssp_row)

        # Size
        ss_row = QHBoxLayout()
        ss_row.addWidget(QLabel("Size:"))
        self._shadow_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_size_slider.setRange(0, 50)
        self._shadow_size_slider.setValue(int(layer.shadow_size if layer else 5))
        self._shadow_size_slider.valueChanged.connect(self._on_shadow_size_slider)
        ss_row.addWidget(self._shadow_size_slider, 1)
        self._shadow_size_spin = QDoubleSpinBox()
        self._shadow_size_spin.setRange(0.0, 50.0)
        self._shadow_size_spin.setSingleStep(1.0)
        self._shadow_size_spin.setDecimals(1)
        self._shadow_size_spin.setFixedWidth(60)
        self._shadow_size_spin.setValue(layer.shadow_size if layer else 5.0)
        self._shadow_size_spin.valueChanged.connect(self._on_shadow_size_spin)
        ss_row.addWidget(self._shadow_size_spin)
        sc_layout.addLayout(ss_row)

        shadow_gl.addWidget(self._shadow_container)
        self._shadow_container.setEnabled(layer.shadow_enabled if layer else False)
        layout.addWidget(shadow_group)

        return widget

    def close_sidebar(self) -> None:
        """Hide border preset sidebar and uncheck expand button."""
        if self._bsp_preset_sidebar:
            self._bsp_preset_sidebar.hide()
        try:
            if hasattr(self, "_bsp_expand_btn"):
                self._bsp_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Selection sync ---

    def _on_selection_changed(self, obj) -> None:
        """Called when the selected border object changes."""
        if obj:
            self._sync_widgets_from_object(obj)

    def _sync_widgets_from_object(self, obj) -> None:
        """Sync all border widgets from a selected BorderObject."""
        tool = self._border_tool
        if tool is None:
            return

        # Update tool properties so new placements inherit current selection's style
        tool.color = obj.color
        tool.width = obj.width
        tool.line_type = obj.line_type
        tool.element_size = obj.element_size
        tool.gap_size = obj.gap_size
        tool.dash_cap = obj.dash_cap
        tool.outline = obj.outline
        tool.outline_color = obj.outline_color
        tool.outline_width = obj.outline_width
        tool.offset = obj.offset  # L14: preserve sign (negative offset is valid)

        # Sync widgets
        update_color_btn(self._bo_color_btn, QColor(obj.color))

        self._bo_width_slider.blockSignals(True)
        self._bo_width_slider.setValue(int(obj.width * 2))
        self._bo_width_slider.blockSignals(False)
        self._bo_width_spin.blockSignals(True)
        self._bo_width_spin.setValue(obj.width)
        self._bo_width_spin.blockSignals(False)

        self._bo_line_type_combo.blockSignals(True)
        lt_label = _LINE_TYPE_REVERSE.get(obj.line_type, "Solid")
        idx = self._bo_line_type_combo.findText(lt_label)
        if idx >= 0:
            self._bo_line_type_combo.setCurrentIndex(idx)
        self._bo_line_type_combo.blockSignals(False)
        self._bo_lt_container.setEnabled(obj.line_type != "solid")

        self._bo_cap_combo.blockSignals(True)
        self._bo_cap_combo.setCurrentText(_CAP_REVERSE.get(obj.dash_cap, "Round"))
        self._bo_cap_combo.blockSignals(False)
        self._bo_cap_container.setEnabled(obj.line_type == "dashed")

        self._bo_element_slider.blockSignals(True)
        self._bo_element_slider.setValue(int(obj.element_size * 2))
        self._bo_element_slider.blockSignals(False)
        self._bo_element_spin.blockSignals(True)
        self._bo_element_spin.setValue(obj.element_size)
        self._bo_element_spin.blockSignals(False)

        self._bo_gap_slider.blockSignals(True)
        self._bo_gap_slider.setValue(int(obj.gap_size * 2))
        self._bo_gap_slider.blockSignals(False)
        self._bo_gap_spin.blockSignals(True)
        self._bo_gap_spin.setValue(obj.gap_size)
        self._bo_gap_spin.blockSignals(False)

        self._bo_outline_cb.blockSignals(True)
        self._bo_outline_cb.setChecked(obj.outline)
        self._bo_outline_cb.blockSignals(False)
        update_color_btn(self._bo_ol_color_btn, QColor(obj.outline_color))
        self._bo_ol_width_slider.blockSignals(True)
        self._bo_ol_width_slider.setValue(int(obj.outline_width * 2))
        self._bo_ol_width_slider.blockSignals(False)
        self._bo_ol_width_spin.blockSignals(True)
        self._bo_ol_width_spin.setValue(obj.outline_width)
        self._bo_ol_width_spin.blockSignals(False)
        self._bo_ol_container.setEnabled(obj.outline)

        abs_offset = abs(obj.offset)
        self._bo_offset_slider.blockSignals(True)
        self._bo_offset_slider.setValue(int(abs_offset * 10))
        self._bo_offset_slider.blockSignals(False)
        self._bo_offset_spin.blockSignals(True)
        self._bo_offset_spin.setValue(abs_offset)
        self._bo_offset_spin.blockSignals(False)

    def _apply_to_selected(self, **changes) -> None:
        """Apply property changes to the selected border via an undoable command."""
        if (
            self._border_tool
            and self._border_tool.mode == "select"
            and self._border_tool._selected is not None
        ):
            layer = self._border_tool._get_active_border_layer()
            if layer:
                cmd = EditBorderCommand(layer, self._border_tool._selected, **changes)
                self._border_tool._command_stack.execute(cmd)

    # --- Mode ---

    def _on_bo_mode_changed(self, button_id: int, checked: bool) -> None:
        if checked and self._border_tool:
            self._border_tool.mode = "place" if button_id == 0 else "select"
            self._border_tool._selected = None
            self._border_tool._notify_selection()

    # --- Color ---

    def _on_bo_color_pick(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._border_tool.color), self.dock, "Pick Border Color",
        )
        if color.isValid():
            self._border_tool.color = color.name()
            update_color_btn(self._bo_color_btn, color)
            self._apply_to_selected(color=color.name())

    # --- Width slider/spin sync ---

    def _on_bo_width_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._border_tool.width = real_val
        self._bo_width_spin.blockSignals(True)
        self._bo_width_spin.setValue(real_val)
        self._bo_width_spin.blockSignals(False)
        self._apply_to_selected(width=real_val)

    def _on_bo_width_spin(self, value: float) -> None:
        self._border_tool.width = value
        self._bo_width_slider.blockSignals(True)
        self._bo_width_slider.setValue(int(value * 2))
        self._bo_width_slider.blockSignals(False)
        self._apply_to_selected(width=value)

    # --- Line type ---

    def _on_bo_line_type_changed(self, label: str) -> None:
        lt = _LINE_TYPE_MAP.get(label, "solid")
        self._border_tool.line_type = lt
        self._bo_lt_container.setEnabled(lt != "solid")
        self._bo_cap_container.setEnabled(lt == "dashed")
        self._apply_to_selected(line_type=lt)

    def _on_bo_cap_changed(self, text: str) -> None:
        cap = _CAP_MAP.get(text, "round")
        self._border_tool.dash_cap = cap
        self._apply_to_selected(dash_cap=cap)

    # --- Element Size slider/spin sync ---

    def _on_bo_element_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._border_tool.element_size = real_val
        self._bo_element_spin.blockSignals(True)
        self._bo_element_spin.setValue(real_val)
        self._bo_element_spin.blockSignals(False)
        self._apply_to_selected(element_size=real_val)

    def _on_bo_element_spin(self, value: float) -> None:
        self._border_tool.element_size = value
        self._bo_element_slider.blockSignals(True)
        self._bo_element_slider.setValue(int(value * 2))
        self._bo_element_slider.blockSignals(False)
        self._apply_to_selected(element_size=value)

    # --- Gap Size slider/spin sync ---

    def _on_bo_gap_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._border_tool.gap_size = real_val
        self._bo_gap_spin.blockSignals(True)
        self._bo_gap_spin.setValue(real_val)
        self._bo_gap_spin.blockSignals(False)
        self._apply_to_selected(gap_size=real_val)

    def _on_bo_gap_spin(self, value: float) -> None:
        self._border_tool.gap_size = value
        self._bo_gap_slider.blockSignals(True)
        self._bo_gap_slider.setValue(int(value * 2))
        self._bo_gap_slider.blockSignals(False)
        self._apply_to_selected(gap_size=value)

    # --- Outline ---

    def _on_bo_outline_toggled(self, checked: bool) -> None:
        self._border_tool.outline = checked
        self._bo_ol_container.setEnabled(checked)
        self._apply_to_selected(outline=checked)

    def _on_bo_outline_color_pick(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._border_tool.outline_color), self.dock, "Pick Outline Color",
        )
        if color.isValid():
            self._border_tool.outline_color = color.name()
            update_color_btn(self._bo_ol_color_btn, color)
            self._apply_to_selected(outline_color=color.name())

    def _on_bo_ol_width_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._border_tool.outline_width = real_val
        self._bo_ol_width_spin.blockSignals(True)
        self._bo_ol_width_spin.setValue(real_val)
        self._bo_ol_width_spin.blockSignals(False)
        self._apply_to_selected(outline_width=real_val)

    def _on_bo_ol_width_spin(self, value: float) -> None:
        self._border_tool.outline_width = value
        self._bo_ol_width_slider.blockSignals(True)
        self._bo_ol_width_slider.setValue(int(value * 2))
        self._bo_ol_width_slider.blockSignals(False)
        self._apply_to_selected(outline_width=value)

    # --- Offset slider/spin sync ---

    def _on_bo_offset_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._border_tool.offset = real_val
        self._bo_offset_spin.blockSignals(True)
        self._bo_offset_spin.setValue(real_val)
        self._bo_offset_spin.blockSignals(False)
        self._apply_to_selected(offset=real_val)

    def _on_bo_offset_spin(self, value: float) -> None:
        self._border_tool.offset = value
        self._bo_offset_slider.blockSignals(True)
        self._bo_offset_slider.setValue(int(value * 10))
        self._bo_offset_slider.blockSignals(False)
        self._apply_to_selected(offset=value)

    # --- Palette ---

    def _bo_refresh_palette_combo(self) -> None:
        self._bo_palette_combo.blockSignals(True)
        current = self._bo_palette_combo.currentText()
        self._bo_palette_combo.clear()
        for name in list_palettes():
            self._bo_palette_combo.addItem(name)
        idx = self._bo_palette_combo.findText(current)
        if idx >= 0:
            self._bo_palette_combo.setCurrentIndex(idx)
        self._bo_palette_combo.blockSignals(False)

    def refresh_palette_catalog(self) -> None:
        """Reload palette combo (called when the palette editor reports changes)."""
        if not hasattr(self, "_bo_palette_combo"):
            return
        self._bo_refresh_palette_combo()

    def _bo_on_palette_changed(self, name: str) -> None:
        if not name:
            return
        try:
            self._bo_current_palette = load_palette(name)
        except FileNotFoundError:
            self._bo_current_palette = None
        self._bo_selected_palette_idx = -1
        self._bo_rebuild_color_grid()

    def _bo_rebuild_color_grid(self) -> None:
        for btn in self._bo_palette_color_buttons:
            self._bo_color_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._bo_palette_color_buttons.clear()

        if not self._bo_current_palette:
            return

        for i, pc in enumerate(self._bo_current_palette.colors):
            btn = QPushButton()
            btn.setFixedSize(36, 36)
            btn.setToolTip(pc.name)
            border = "1px solid #555"
            btn.setStyleSheet(f"background-color: {pc.color}; border: {border};")
            btn.clicked.connect(
                lambda checked, idx=i: self._bo_on_palette_color_clicked(idx)
            )
            row = i // _PALETTE_GRID_COLS
            col = i % _PALETTE_GRID_COLS
            self._bo_color_grid_layout.addWidget(btn, row, col)
            self._bo_palette_color_buttons.append(btn)

    def _bo_on_palette_color_clicked(self, idx: int) -> None:
        if not self._bo_current_palette or idx >= len(self._bo_current_palette.colors):
            return

        # Deselect previous
        if 0 <= self._bo_selected_palette_idx < len(self._bo_palette_color_buttons):
            old_pc = self._bo_current_palette.colors[self._bo_selected_palette_idx]
            self._bo_palette_color_buttons[self._bo_selected_palette_idx].setStyleSheet(
                f"background-color: {old_pc.color}; border: 1px solid #555;"
            )

        # Select new
        self._bo_selected_palette_idx = idx
        pc = self._bo_current_palette.colors[idx]
        self._bo_palette_color_buttons[idx].setStyleSheet(
            f"background-color: {pc.color}; border: 2px solid #00aaff;"
        )

        # Set border color
        color = QColor(pc.color)
        self._border_tool.color = color.name()
        update_color_btn(self._bo_color_btn, color)
        self._apply_to_selected(color=color.name())

    # --- Preset sidebar ---

    def _bsp_on_toggle_sidebar(self, checked: bool) -> None:
        """Toggle the expanded preset browser sidebar."""
        if checked:
            self.dock._save_panel_width()
            if not self._bsp_preset_sidebar:
                self._bsp_preset_sidebar = BorderPresetSidebar(self.dock.window())
                self._bsp_preset_sidebar.preset_clicked.connect(
                    self._bsp_on_sidebar_preset_clicked,
                )
                self._bsp_preset_sidebar.closed.connect(
                    self._bsp_on_preset_sidebar_closed,
                )
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea,
                    self._bsp_preset_sidebar,
                )
                main_win.splitDockWidget(
                    self.dock, self._bsp_preset_sidebar, Qt.Orientation.Horizontal,
                )
            self._bsp_preset_sidebar.show()
            self._bsp_sync_sidebar()
        else:
            if self._bsp_preset_sidebar:
                self._bsp_preset_sidebar.hide()
            self.dock._restore_panel_width()

    def _bsp_sync_sidebar(self) -> None:
        """Update preset sidebar contents from disk."""
        if not self._bsp_preset_sidebar or not self._bsp_preset_sidebar.isVisible():
            return
        names = list_border_presets()
        selected = self._bsp_combo.currentText() or None
        self._bsp_preset_sidebar.set_presets(names, selected)

    def _bsp_on_sidebar_preset_clicked(self, name: str) -> None:
        """Handle preset selection from the sidebar - load it."""
        idx = self._bsp_combo.findText(name)
        if idx >= 0:
            self._bsp_combo.setCurrentIndex(idx)
        self._bsp_on_load()
        if self._bsp_preset_sidebar:
            self._bsp_preset_sidebar.set_selected(name)

    def _bsp_on_preset_sidebar_closed(self) -> None:
        """Handle preset sidebar close button."""
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_bsp_expand_btn"):
                self._bsp_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Presets ---

    def _bsp_refresh_combo(self) -> None:
        """Reload border preset combo from disk."""
        self._bsp_combo.blockSignals(True)
        current = self._bsp_combo.currentText()
        self._bsp_combo.clear()
        names = list_border_presets()
        self._bsp_combo.addItems(names)
        idx = self._bsp_combo.findText(current)
        if idx >= 0:
            self._bsp_combo.setCurrentIndex(idx)
        elif names:
            self._bsp_combo.setCurrentIndex(0)
        self._bsp_combo.blockSignals(False)

    def _bsp_on_selected(self, name: str) -> None:
        """Update preview and auto-load when preset selection changes."""
        self._bsp_update_preview()
        if name:
            self._bsp_on_load()

    def _bsp_update_preview(self) -> None:
        """Render the preview for the currently selected preset."""
        name = self._bsp_combo.currentText()
        if name:
            try:
                preset = load_border_preset(name)
            except (FileNotFoundError, Exception):
                preset = self._bsp_current_as_preset()
        else:
            preset = self._bsp_current_as_preset()
        w = max(self._bsp_preview.width(), 200)
        h = max(self._bsp_preview.height(), 40)
        self._bsp_preview.setPixmap(render_border_preview(preset, w, h))

    def _bsp_current_as_preset(self) -> BorderPreset:
        """Capture current border tool settings as a preset."""
        tool = self._border_tool
        return BorderPreset(
            name="(current)",
            color=tool.color,
            width=tool.width,
            line_type=tool.line_type,
            element_size=tool.element_size,
            gap_size=tool.gap_size,
            dash_cap=tool.dash_cap,
            outline=tool.outline,
            outline_color=tool.outline_color,
            outline_width=tool.outline_width,
            offset=tool.offset,
        )

    def _bsp_on_load(self) -> None:
        """Apply selected preset to border tool and sync UI."""
        name = self._bsp_combo.currentText()
        if not name:
            return
        try:
            preset = load_border_preset(name)
        except FileNotFoundError:
            QMessageBox.warning(self.dock, "Preset Not Found", f"Preset '{name}' not found.")
            self._bsp_refresh_combo()
            return

        tool = self._border_tool

        # Apply all settings to tool
        tool.color = preset.color
        tool.width = preset.width
        tool.line_type = preset.line_type
        tool.element_size = preset.element_size
        tool.gap_size = preset.gap_size
        tool.dash_cap = preset.dash_cap
        tool.outline = preset.outline
        tool.outline_color = preset.outline_color
        tool.outline_width = preset.outline_width
        tool.offset = abs(preset.offset)

        # Sync UI widgets (block signals to avoid cascading updates)

        # Color
        update_color_btn(self._bo_color_btn, QColor(preset.color))

        # Width
        self._bo_width_slider.blockSignals(True)
        self._bo_width_slider.setValue(int(preset.width * 2))
        self._bo_width_slider.blockSignals(False)
        self._bo_width_spin.blockSignals(True)
        self._bo_width_spin.setValue(preset.width)
        self._bo_width_spin.blockSignals(False)

        # Line type
        self._bo_line_type_combo.blockSignals(True)
        lt_label = _LINE_TYPE_REVERSE.get(preset.line_type, "Solid")
        idx = self._bo_line_type_combo.findText(lt_label)
        if idx >= 0:
            self._bo_line_type_combo.setCurrentIndex(idx)
        self._bo_line_type_combo.blockSignals(False)
        self._bo_lt_container.setEnabled(preset.line_type != "solid")

        # Cap
        self._bo_cap_combo.blockSignals(True)
        self._bo_cap_combo.setCurrentText(
            _CAP_REVERSE.get(preset.dash_cap, "Round"),
        )
        self._bo_cap_combo.blockSignals(False)
        self._bo_cap_container.setEnabled(preset.line_type == "dashed")

        # Element size
        self._bo_element_slider.blockSignals(True)
        self._bo_element_slider.setValue(int(preset.element_size * 2))
        self._bo_element_slider.blockSignals(False)
        self._bo_element_spin.blockSignals(True)
        self._bo_element_spin.setValue(preset.element_size)
        self._bo_element_spin.blockSignals(False)

        # Gap size
        self._bo_gap_slider.blockSignals(True)
        self._bo_gap_slider.setValue(int(preset.gap_size * 2))
        self._bo_gap_slider.blockSignals(False)
        self._bo_gap_spin.blockSignals(True)
        self._bo_gap_spin.setValue(preset.gap_size)
        self._bo_gap_spin.blockSignals(False)

        # Outline
        self._bo_outline_cb.blockSignals(True)
        self._bo_outline_cb.setChecked(preset.outline)
        self._bo_outline_cb.blockSignals(False)
        update_color_btn(self._bo_ol_color_btn, QColor(preset.outline_color))
        self._bo_ol_width_slider.blockSignals(True)
        self._bo_ol_width_slider.setValue(int(preset.outline_width * 2))
        self._bo_ol_width_slider.blockSignals(False)
        self._bo_ol_width_spin.blockSignals(True)
        self._bo_ol_width_spin.setValue(preset.outline_width)
        self._bo_ol_width_spin.blockSignals(False)
        self._bo_ol_container.setEnabled(preset.outline)

        # Offset (abs for backward compat with presets that stored negative values)
        self._bo_offset_slider.blockSignals(True)
        self._bo_offset_slider.setValue(int(abs(preset.offset) * 10))
        self._bo_offset_slider.blockSignals(False)
        self._bo_offset_spin.blockSignals(True)
        self._bo_offset_spin.setValue(abs(preset.offset))
        self._bo_offset_spin.blockSignals(False)

        self._bsp_update_preview()

    def _bsp_on_save(self) -> None:
        """Save current border tool settings as a named preset."""
        name, ok = QInputDialog.getText(
            self.dock, "Save Border Preset", "Preset name:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        # Check for overwrite
        existing = list_border_presets()
        if name in existing:
            reply = QMessageBox.question(
                self.dock, "Overwrite Preset",
                f"Preset '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        preset = self._bsp_current_as_preset()
        preset.name = name
        save_border_preset(preset)
        self._bsp_refresh_combo()
        idx = self._bsp_combo.findText(name)
        if idx >= 0:
            self._bsp_combo.setCurrentIndex(idx)
        self._bsp_update_preview()
        self._bsp_sync_sidebar()

    def _bsp_on_delete(self) -> None:
        """Delete the selected border preset."""
        name = self._bsp_combo.currentText()
        if not name:
            return
        if is_builtin_border_preset(name):
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
        if reply != QMessageBox.StandardButton.Yes:
            return
        delete_border_preset(name)
        self._bsp_refresh_combo()
        self._bsp_update_preview()
        self._bsp_sync_sidebar()

    def sync_shadow_from_layer(self) -> None:
        """Sync shadow widgets from the currently active BorderLayer."""
        layer = self._get_layer()
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

    # --- Layer helper ---

    def _get_layer(self):
        if self._border_tool is None:
            return None
        return self._border_tool._get_active_border_layer()

    def _apply_layer_effect(self, **changes) -> None:
        layer = self._get_layer()
        if layer is None:
            return
        cmd = EditBorderLayerEffectsCommand(layer, **changes)
        self._border_tool._command_stack.execute(cmd)

    # --- Shadow handlers ---

    def _on_shadow_toggled(self, checked: bool) -> None:
        self._shadow_container.setEnabled(checked)
        self._apply_layer_effect(shadow_enabled=checked)

    def _on_shadow_type(self, text: str) -> None:
        self._apply_layer_effect(shadow_type="inner" if text == "Inner" else "outer")

    def _on_shadow_color(self) -> None:
        layer = self._get_layer()
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
