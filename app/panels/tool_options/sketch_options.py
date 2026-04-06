"""Sketch tool options builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.commands.sketch_commands import EditSketchCommand, EditSketchLayerEffectsCommand
from app.io.texture_library import (
    LibraryTexture,
    TextureCatalog,
    load_catalog as load_texture_catalog,
)
from app.layers.sketch_layer import SketchLayer
from app.panels.tool_options.helpers import update_color_btn
from app.tools.sketch_tool import SketchTool

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel

_SHAPE_TYPES = ["Line", "Rectangle", "Polygon", "Ellipse", "Freehand"]
_SHAPE_MAP = {
    "Line": "line", "Rectangle": "rect", "Polygon": "polygon",
    "Ellipse": "ellipse", "Freehand": "freehand",
}
_SHAPE_REVERSE = {v: k for k, v in _SHAPE_MAP.items()}


class SketchOptions:
    """Builds and manages the sketch tool options UI."""

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._tool: SketchTool | None = None
        self._texture_catalog: TextureCatalog | None = None
        self._texture_thumb_cache: dict[str, QPixmap] = {}
        self._texture_browser_buttons: dict[str, QToolButton] = {}
        self._selected_fill_texture: LibraryTexture | None = None

    def create(self, tool: SketchTool) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        self._tool = tool
        tool.on_selection_changed = self._on_selection_changed

        self._texture_catalog = load_texture_catalog()
        self._texture_thumb_cache = {}
        self._texture_browser_buttons = {}
        self._selected_fill_texture = None

        # ===== Mode group =====
        mode_group = QGroupBox("Mode")
        mode_gl = QVBoxLayout(mode_group)
        mode_gl.setContentsMargins(6, 4, 6, 4)
        mode_btn_layout = QHBoxLayout()

        draw_btn = QPushButton("Draw")
        draw_btn.setCheckable(True)
        draw_btn.setChecked(True)
        select_btn = QPushButton("Select")
        select_btn.setCheckable(True)

        self._mode_group = QButtonGroup(widget)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(draw_btn, 0)
        self._mode_group.addButton(select_btn, 1)
        self._mode_group.idToggled.connect(self._on_mode_changed)

        mode_btn_layout.addWidget(draw_btn)
        mode_btn_layout.addWidget(select_btn)
        mode_btn_layout.addStretch()
        mode_gl.addLayout(mode_btn_layout)

        # Draw over grid checkbox (per-object: default for new, or toggle selected)
        self._over_grid_cb = QCheckBox("Draw over Grid")
        self._over_grid_cb.setChecked(tool.draw_over_grid)
        self._over_grid_cb.toggled.connect(self._on_over_grid_changed)
        mode_gl.addWidget(self._over_grid_cb)

        layout.addWidget(mode_group)

        # ===== Shape group =====
        shape_group = QGroupBox("Shape")
        shape_gl = QVBoxLayout(shape_group)
        shape_gl.setContentsMargins(6, 4, 6, 4)

        # Shape type combo
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._shape_combo = QComboBox()
        self._shape_combo.addItems(_SHAPE_TYPES)
        self._shape_combo.setCurrentText(_SHAPE_REVERSE.get(tool.shape_type, "Rectangle"))
        self._shape_combo.currentTextChanged.connect(self._on_shape_changed)
        type_row.addWidget(self._shape_combo, 1)
        shape_gl.addLayout(type_row)

        # Polygon sides (visible only when polygon)
        self._sides_container = QWidget()
        sides_row = QHBoxLayout(self._sides_container)
        sides_row.setContentsMargins(0, 0, 0, 0)
        sides_row.addWidget(QLabel("Sides:"))
        self._sides_spin = QSpinBox()
        self._sides_spin.setRange(3, 12)
        self._sides_spin.setValue(tool.num_sides)
        self._sides_spin.valueChanged.connect(self._on_sides_changed)
        sides_row.addWidget(self._sides_spin, 1)
        shape_gl.addWidget(self._sides_container)
        self._sides_container.setEnabled(tool.shape_type == "polygon")

        # Freehand close checkbox (visible only when freehand)
        self._close_cb = QCheckBox("Close Path")
        self._close_cb.setChecked(tool.closed)
        self._close_cb.toggled.connect(self._on_close_changed)
        shape_gl.addWidget(self._close_cb)
        self._close_cb.setEnabled(tool.shape_type == "freehand")

        # Perfect circle (visible only when ellipse)
        self._perfect_circle_cb = QCheckBox("Perfect Circle")
        self._perfect_circle_cb.setChecked(tool.perfect_circle)
        self._perfect_circle_cb.toggled.connect(self._on_perfect_circle_changed)
        shape_gl.addWidget(self._perfect_circle_cb)
        self._perfect_circle_cb.setEnabled(tool.shape_type == "ellipse")

        # Snap to grid
        self._snap_cb = QCheckBox("Snap to Grid")
        self._snap_cb.setChecked(tool.snap_to_grid)
        self._snap_cb.toggled.connect(self._on_snap_changed)
        shape_gl.addWidget(self._snap_cb)

        layout.addWidget(shape_group)

        # ===== Stroke group =====
        stroke_group = QGroupBox("Stroke")
        stroke_gl = QVBoxLayout(stroke_group)
        stroke_gl.setContentsMargins(6, 4, 6, 4)

        # Color
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._stroke_color_btn = QPushButton()
        self._stroke_color_btn.setFixedSize(40, 25)
        update_color_btn(self._stroke_color_btn, QColor(tool.stroke_color))
        self._stroke_color_btn.clicked.connect(self._on_stroke_color)
        color_row.addWidget(self._stroke_color_btn)
        color_row.addStretch()
        stroke_gl.addLayout(color_row)

        # Width
        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Width:"))
        self._width_slider = QSlider(Qt.Orientation.Horizontal)
        self._width_slider.setRange(1, 80)
        self._width_slider.setValue(int(tool.stroke_width * 2))
        self._width_slider.valueChanged.connect(self._on_width_slider)
        width_row.addWidget(self._width_slider, 1)
        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0.5, 40.0)
        self._width_spin.setSingleStep(0.5)
        self._width_spin.setDecimals(1)
        self._width_spin.setValue(tool.stroke_width)
        self._width_spin.valueChanged.connect(self._on_width_spin)
        width_row.addWidget(self._width_spin)
        stroke_gl.addLayout(width_row)

        # Line type
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._stroke_type_combo = QComboBox()
        self._stroke_type_combo.addItems(["Solid", "Dashed", "Dotted"])
        self._stroke_type_combo.setCurrentText(
            {"solid": "Solid", "dashed": "Dashed", "dotted": "Dotted"}.get(tool.stroke_type, "Solid")
        )
        self._stroke_type_combo.currentTextChanged.connect(self._on_stroke_type)
        type_row.addWidget(self._stroke_type_combo)
        type_row.addStretch()
        stroke_gl.addLayout(type_row)

        # Dash / gap / cap container (visible only for Dashed / Dotted)
        self._dash_gap_widget = QWidget()
        dg_vbox = QVBoxLayout(self._dash_gap_widget)
        dg_vbox.setContentsMargins(0, 0, 0, 0)

        dg_vbox.addWidget(QLabel("Dash:"))
        dash_row = QHBoxLayout()
        self._dash_length_slider = QSlider(Qt.Orientation.Horizontal)
        self._dash_length_slider.setRange(1, 300)   # 0.1 – 30.0
        self._dash_length_slider.setValue(max(1, round(tool.dash_length * 10)))
        self._dash_length_slider.valueChanged.connect(self._on_dash_slider)
        dash_row.addWidget(self._dash_length_slider, stretch=1)
        self._dash_length_spin = QDoubleSpinBox()
        self._dash_length_spin.setRange(0.1, 30.0)
        self._dash_length_spin.setSingleStep(0.1)
        self._dash_length_spin.setDecimals(1)
        self._dash_length_spin.setValue(tool.dash_length)
        self._dash_length_spin.setFixedWidth(60)
        self._dash_length_spin.valueChanged.connect(self._on_dash_spin)
        dash_row.addWidget(self._dash_length_spin)
        dg_vbox.addLayout(dash_row)

        dg_vbox.addWidget(QLabel("Gap:"))
        gap_row = QHBoxLayout()
        self._gap_length_slider = QSlider(Qt.Orientation.Horizontal)
        self._gap_length_slider.setRange(1, 300)    # 0.1 – 30.0
        self._gap_length_slider.setValue(max(1, round(tool.gap_length * 10)))
        self._gap_length_slider.valueChanged.connect(self._on_gap_slider)
        gap_row.addWidget(self._gap_length_slider, stretch=1)
        self._gap_length_spin = QDoubleSpinBox()
        self._gap_length_spin.setRange(0.1, 30.0)
        self._gap_length_spin.setSingleStep(0.1)
        self._gap_length_spin.setDecimals(1)
        self._gap_length_spin.setValue(tool.gap_length)
        self._gap_length_spin.setFixedWidth(60)
        self._gap_length_spin.valueChanged.connect(self._on_gap_spin)
        gap_row.addWidget(self._gap_length_spin)
        dg_vbox.addLayout(gap_row)

        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("Cap:"))
        self._stroke_cap_combo = QComboBox()
        self._stroke_cap_combo.addItems(["Flat", "Round", "Square"])
        self._stroke_cap_combo.setCurrentText(
            {"flat": "Flat", "round": "Round", "square": "Square"}.get(tool.stroke_cap, "Round")
        )
        self._stroke_cap_combo.currentTextChanged.connect(self._on_stroke_cap)
        cap_row.addWidget(self._stroke_cap_combo)
        cap_row.addStretch()
        dg_vbox.addLayout(cap_row)

        stroke_gl.addWidget(self._dash_gap_widget)
        self._dash_gap_widget.setEnabled(tool.stroke_type != "solid")

        layout.addWidget(stroke_group)

        # ===== Fill group =====
        fill_group = QGroupBox("Fill")
        fill_gl = QVBoxLayout(fill_group)
        fill_gl.setContentsMargins(6, 4, 6, 4)

        self._fill_cb = QCheckBox("Enable Fill")
        self._fill_cb.setChecked(tool.fill_enabled)
        self._fill_cb.toggled.connect(self._on_fill_toggled)
        fill_gl.addWidget(self._fill_cb)

        self._fill_container = QWidget()
        fill_cl = QVBoxLayout(self._fill_container)
        fill_cl.setContentsMargins(0, 0, 0, 0)
        fill_cl.setSpacing(4)

        # Fill type buttons: Color / Texture
        fill_type_row = QHBoxLayout()
        fill_type_row.addWidget(QLabel("Type:"))
        fill_type_color_btn = QPushButton("Color")
        fill_type_color_btn.setCheckable(True)
        fill_type_texture_btn = QPushButton("Texture")
        fill_type_texture_btn.setCheckable(True)
        self._fill_type_group = QButtonGroup(widget)
        self._fill_type_group.setExclusive(True)
        self._fill_type_group.addButton(fill_type_color_btn, 0)
        self._fill_type_group.addButton(fill_type_texture_btn, 1)
        self._fill_type_group.idToggled.connect(self._on_fill_type_changed)
        # Block signals — _fill_color_sub/_fill_texture_sub not yet created
        self._fill_type_group.blockSignals(True)
        if tool.fill_type == "texture":
            fill_type_texture_btn.setChecked(True)
        else:
            fill_type_color_btn.setChecked(True)
        self._fill_type_group.blockSignals(False)
        fill_type_row.addWidget(fill_type_color_btn)
        fill_type_row.addWidget(fill_type_texture_btn)
        fill_cl.addLayout(fill_type_row)

        # --- Color sub-container ---
        self._fill_color_sub = QWidget()
        color_sub_layout = QVBoxLayout(self._fill_color_sub)
        color_sub_layout.setContentsMargins(0, 0, 0, 0)
        color_sub_layout.setSpacing(4)

        fc_row = QHBoxLayout()
        fc_row.addWidget(QLabel("Color:"))
        self._fill_color_btn = QPushButton()
        self._fill_color_btn.setFixedSize(40, 25)
        update_color_btn(self._fill_color_btn, QColor(tool.fill_color))
        self._fill_color_btn.clicked.connect(self._on_fill_color)
        fc_row.addWidget(self._fill_color_btn)
        fc_row.addStretch()
        color_sub_layout.addLayout(fc_row)
        fill_cl.addWidget(self._fill_color_sub)

        # --- Texture sub-container ---
        self._fill_texture_sub = QWidget()
        tex_sub_layout = QVBoxLayout(self._fill_texture_sub)
        tex_sub_layout.setContentsMargins(0, 0, 0, 0)
        tex_sub_layout.setSpacing(4)

        # Game filter
        tex_game_row = QHBoxLayout()
        tex_game_row.addWidget(QLabel("Game:"))
        self._fill_tex_game_combo = QComboBox()
        self._fill_tex_game_combo.setMinimumWidth(80)
        self._fill_tex_game_combo.currentTextChanged.connect(self._on_fill_tex_filter_changed)
        tex_game_row.addWidget(self._fill_tex_game_combo, 1)
        tex_sub_layout.addLayout(tex_game_row)

        # Category filter
        tex_cat_row = QHBoxLayout()
        tex_cat_row.addWidget(QLabel("Cat:"))
        self._fill_tex_cat_combo = QComboBox()
        self._fill_tex_cat_combo.setMinimumWidth(80)
        self._fill_tex_cat_combo.currentTextChanged.connect(self._on_fill_tex_filter_changed)
        tex_cat_row.addWidget(self._fill_tex_cat_combo, 1)
        tex_sub_layout.addLayout(tex_cat_row)

        # Search
        tex_search_row = QHBoxLayout()
        tex_search_row.addWidget(QLabel("Search:"))
        self._fill_tex_search = QLineEdit()
        self._fill_tex_search.setPlaceholderText("Filter by name...")
        self._fill_tex_search.textChanged.connect(self._on_fill_tex_filter_changed)
        tex_search_row.addWidget(self._fill_tex_search, 1)
        tex_sub_layout.addLayout(tex_search_row)

        # Thumbnail grid
        self._fill_tex_scroll = QScrollArea()
        self._fill_tex_scroll.setWidgetResizable(True)
        self._fill_tex_scroll.setMinimumHeight(80)
        self._fill_tex_scroll.setMaximumHeight(200)
        self._fill_tex_grid_container = QWidget()
        self._fill_tex_grid_layout = QGridLayout(self._fill_tex_grid_container)
        self._fill_tex_grid_layout.setSpacing(4)
        self._fill_tex_grid_layout.setContentsMargins(2, 2, 2, 2)
        self._fill_tex_scroll.setWidget(self._fill_tex_grid_container)
        tex_sub_layout.addWidget(self._fill_tex_scroll)

        # Zoom
        tex_zoom_row = QHBoxLayout()
        tex_zoom_row.addWidget(QLabel("Zoom:"))
        self._fill_tex_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._fill_tex_zoom_slider.setRange(1, 100)
        self._fill_tex_zoom_slider.setValue(max(1, round(tool.fill_texture_zoom * 20)))
        self._fill_tex_zoom_slider.valueChanged.connect(self._on_fill_tex_zoom_slider)
        tex_zoom_row.addWidget(self._fill_tex_zoom_slider, 1)
        self._fill_tex_zoom_spin = QDoubleSpinBox()
        self._fill_tex_zoom_spin.setRange(0.05, 5.0)
        self._fill_tex_zoom_spin.setSingleStep(0.05)
        self._fill_tex_zoom_spin.setDecimals(2)
        self._fill_tex_zoom_spin.setSuffix("x")
        self._fill_tex_zoom_spin.setValue(tool.fill_texture_zoom)
        self._fill_tex_zoom_spin.setFixedWidth(70)
        self._fill_tex_zoom_spin.valueChanged.connect(self._on_fill_tex_zoom_spin)
        tex_zoom_row.addWidget(self._fill_tex_zoom_spin)
        tex_sub_layout.addLayout(tex_zoom_row)

        # Rotation
        tex_rot_row = QHBoxLayout()
        tex_rot_row.addWidget(QLabel("Rotation:"))
        self._fill_tex_rot_slider = QSlider(Qt.Orientation.Horizontal)
        self._fill_tex_rot_slider.setRange(0, 359)
        self._fill_tex_rot_slider.setValue(int(tool.fill_texture_rotation))
        self._fill_tex_rot_slider.valueChanged.connect(self._on_fill_tex_rot_slider)
        tex_rot_row.addWidget(self._fill_tex_rot_slider, 1)
        self._fill_tex_rot_spin = QSpinBox()
        self._fill_tex_rot_spin.setRange(0, 359)
        self._fill_tex_rot_spin.setSuffix("\u00b0")
        self._fill_tex_rot_spin.setWrapping(True)
        self._fill_tex_rot_spin.setValue(int(tool.fill_texture_rotation))
        self._fill_tex_rot_spin.setFixedWidth(60)
        self._fill_tex_rot_spin.valueChanged.connect(self._on_fill_tex_rot_spin)
        tex_rot_row.addWidget(self._fill_tex_rot_spin)
        tex_sub_layout.addLayout(tex_rot_row)

        # Rotation preset buttons
        self._fill_tex_rot_buttons: list[QPushButton] = []
        tex_rot_btn_row = QHBoxLayout()
        tex_rot_btn_row.setSpacing(2)
        for deg in (0, 60, 90, 120, 180, 270):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(40)
            btn.setChecked(deg == int(tool.fill_texture_rotation))
            btn.clicked.connect(lambda _, d=deg: self._on_fill_tex_rot_preset(d))
            tex_rot_btn_row.addWidget(btn)
            self._fill_tex_rot_buttons.append(btn)
        tex_rot_btn_row.addStretch()
        tex_sub_layout.addLayout(tex_rot_btn_row)

        fill_cl.addWidget(self._fill_texture_sub)

        # Show correct sub-container
        is_texture = tool.fill_type == "texture"
        self._fill_color_sub.setVisible(not is_texture)
        self._fill_texture_sub.setVisible(is_texture)

        # Fill opacity (always visible when fill enabled)
        fo_row = QHBoxLayout()
        fo_row.addWidget(QLabel("Opacity:"))
        self._fill_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._fill_opacity_slider.setRange(0, 100)
        self._fill_opacity_slider.setValue(int(tool.fill_opacity * 100))
        self._fill_opacity_slider.valueChanged.connect(self._on_fill_opacity_slider)
        fo_row.addWidget(self._fill_opacity_slider, 1)
        self._fill_opacity_spin = QDoubleSpinBox()
        self._fill_opacity_spin.setRange(0.0, 1.0)
        self._fill_opacity_spin.setSingleStep(0.05)
        self._fill_opacity_spin.setDecimals(2)
        self._fill_opacity_spin.setValue(tool.fill_opacity)
        self._fill_opacity_spin.valueChanged.connect(self._on_fill_opacity_spin)
        fo_row.addWidget(self._fill_opacity_spin)
        fill_cl.addLayout(fo_row)

        fill_gl.addWidget(self._fill_container)
        self._fill_container.setEnabled(tool.fill_enabled)

        layout.addWidget(fill_group)

        # ===== Shadow group (layer-level) =====
        layer = self._get_sketch_layer()
        _se = layer.shadow_enabled if layer else False
        _sc = layer.shadow_color if layer else "#000000"
        _so = layer.shadow_opacity if layer else 0.5
        _sa = layer.shadow_angle if layer else 120.0
        _sd = layer.shadow_distance if layer else 5.0
        _ss = layer.shadow_spread if layer else 0.0
        _sz = layer.shadow_size if layer else 5.0

        shadow_group = QGroupBox("Shadow")
        shadow_gl = QVBoxLayout(shadow_group)
        shadow_gl.setContentsMargins(6, 4, 6, 4)

        self._shadow_cb = QCheckBox("Enable Shadow")
        self._shadow_cb.setChecked(_se)
        self._shadow_cb.toggled.connect(self._on_shadow_toggled)
        shadow_gl.addWidget(self._shadow_cb)

        self._shadow_container = QWidget()
        sc_layout = QVBoxLayout(self._shadow_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)

        # Shadow type
        st_row = QHBoxLayout()
        st_row.addWidget(QLabel("Type:"))
        self._shadow_type_combo = QComboBox()
        self._shadow_type_combo.addItems(["Outer", "Inner"])
        self._shadow_type_combo.setCurrentText("Outer")
        self._shadow_type_combo.currentTextChanged.connect(self._on_shadow_type)
        st_row.addWidget(self._shadow_type_combo, 1)
        sc_layout.addLayout(st_row)

        # Shadow color
        sc_row = QHBoxLayout()
        sc_row.addWidget(QLabel("Color:"))
        self._shadow_color_btn = QPushButton()
        self._shadow_color_btn.setFixedSize(40, 25)
        update_color_btn(self._shadow_color_btn, QColor(_sc))
        self._shadow_color_btn.clicked.connect(self._on_shadow_color)
        sc_row.addWidget(self._shadow_color_btn)
        sc_row.addStretch()
        sc_layout.addLayout(sc_row)

        # Shadow opacity
        so_row = QHBoxLayout()
        so_row.addWidget(QLabel("Opacity:"))
        self._shadow_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_opacity_slider.setRange(0, 100)
        self._shadow_opacity_slider.setValue(int(_so * 100))
        self._shadow_opacity_slider.valueChanged.connect(self._on_shadow_opacity_slider)
        so_row.addWidget(self._shadow_opacity_slider, 1)
        self._shadow_opacity_spin = QDoubleSpinBox()
        self._shadow_opacity_spin.setRange(0.0, 1.0)
        self._shadow_opacity_spin.setSingleStep(0.05)
        self._shadow_opacity_spin.setDecimals(2)
        self._shadow_opacity_spin.setValue(_so)
        self._shadow_opacity_spin.valueChanged.connect(self._on_shadow_opacity_spin)
        so_row.addWidget(self._shadow_opacity_spin)
        sc_layout.addLayout(so_row)

        # Angle
        sa_row = QHBoxLayout()
        sa_row.addWidget(QLabel("Angle:"))
        self._shadow_angle_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_angle_slider.setRange(0, 360)
        self._shadow_angle_slider.setValue(int(_sa))
        self._shadow_angle_slider.valueChanged.connect(self._on_shadow_angle_slider)
        sa_row.addWidget(self._shadow_angle_slider, 1)
        self._shadow_angle_spin = QSpinBox()
        self._shadow_angle_spin.setRange(0, 360)
        self._shadow_angle_spin.setSuffix("°")
        self._shadow_angle_spin.setFixedWidth(60)
        self._shadow_angle_spin.setValue(int(_sa))
        self._shadow_angle_spin.valueChanged.connect(self._on_shadow_angle_spin)
        sa_row.addWidget(self._shadow_angle_spin)
        sc_layout.addLayout(sa_row)

        # Distance
        sd_row = QHBoxLayout()
        sd_row.addWidget(QLabel("Dist:"))
        self._shadow_dist_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_dist_slider.setRange(0, 50)
        self._shadow_dist_slider.setValue(int(_sd))
        self._shadow_dist_slider.valueChanged.connect(self._on_shadow_dist_slider)
        sd_row.addWidget(self._shadow_dist_slider, 1)
        self._shadow_dist_spin = QDoubleSpinBox()
        self._shadow_dist_spin.setRange(0.0, 50.0)
        self._shadow_dist_spin.setSingleStep(1.0)
        self._shadow_dist_spin.setDecimals(1)
        self._shadow_dist_spin.setValue(_sd)
        self._shadow_dist_spin.valueChanged.connect(self._on_shadow_dist_spin)
        sd_row.addWidget(self._shadow_dist_spin)
        sc_layout.addLayout(sd_row)

        # Spread
        ssp_row = QHBoxLayout()
        ssp_row.addWidget(QLabel("Spread:"))
        self._shadow_spread_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_spread_slider.setRange(0, 100)
        self._shadow_spread_slider.setValue(int(_ss))
        self._shadow_spread_slider.valueChanged.connect(self._on_shadow_spread_slider)
        ssp_row.addWidget(self._shadow_spread_slider, 1)
        self._shadow_spread_spin = QSpinBox()
        self._shadow_spread_spin.setRange(0, 100)
        self._shadow_spread_spin.setSuffix("%")
        self._shadow_spread_spin.setFixedWidth(60)
        self._shadow_spread_spin.setValue(int(_ss))
        self._shadow_spread_spin.valueChanged.connect(self._on_shadow_spread_spin)
        ssp_row.addWidget(self._shadow_spread_spin)
        sc_layout.addLayout(ssp_row)

        # Size
        ss_row = QHBoxLayout()
        ss_row.addWidget(QLabel("Size:"))
        self._shadow_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_size_slider.setRange(0, 50)
        self._shadow_size_slider.setValue(int(_sz))
        self._shadow_size_slider.valueChanged.connect(self._on_shadow_size_slider)
        ss_row.addWidget(self._shadow_size_slider, 1)
        self._shadow_size_spin = QDoubleSpinBox()
        self._shadow_size_spin.setRange(0.0, 50.0)
        self._shadow_size_spin.setSingleStep(1.0)
        self._shadow_size_spin.setDecimals(1)
        self._shadow_size_spin.setValue(_sz)
        self._shadow_size_spin.valueChanged.connect(self._on_shadow_size_spin)
        ss_row.addWidget(self._shadow_size_spin)
        sc_layout.addLayout(ss_row)

        shadow_gl.addWidget(self._shadow_container)
        self._shadow_container.setEnabled(_se)

        layout.addWidget(shadow_group)

        # ===== Rotation group =====
        rot_group = QGroupBox("Rotation")
        rot_gl = QVBoxLayout(rot_group)
        rot_gl.setContentsMargins(6, 4, 6, 4)

        rot_row = QHBoxLayout()
        self._rot_slider = QSlider(Qt.Orientation.Horizontal)
        self._rot_slider.setRange(0, 359)
        self._rot_slider.setValue(int(tool.rotation) % 360)
        self._rot_slider.valueChanged.connect(self._on_rot_slider)
        rot_row.addWidget(self._rot_slider, 1)
        self._rot_spin = QSpinBox()
        self._rot_spin.setRange(0, 359)
        self._rot_spin.setSuffix("\u00b0")
        self._rot_spin.setWrapping(True)
        self._rot_spin.setValue(int(tool.rotation) % 360)
        self._rot_spin.valueChanged.connect(self._on_rot_spin)
        rot_row.addWidget(self._rot_spin)
        rot_gl.addLayout(rot_row)

        # Preset buttons
        preset_row = QHBoxLayout()
        for angle in (0, 45, 90, 180, 270):
            btn = QPushButton(f"{angle}\u00b0")
            btn.setFixedWidth(42)
            btn.clicked.connect(lambda checked, a=angle: self._set_rotation(a))
            preset_row.addWidget(btn)
        preset_row.addStretch()
        rot_gl.addLayout(preset_row)

        layout.addWidget(rot_group)

        # Initialize texture browser
        self._refresh_fill_texture_browser()

        layout.addStretch()
        return widget

    def close_sidebar(self) -> None:
        pass  # No sidebars for sketch tool

    # --- Texture browser ---

    def _refresh_fill_texture_browser(self) -> None:
        """Reload catalog and refresh filter combos + grid."""
        self._texture_catalog = load_texture_catalog()
        self._texture_browser_buttons = {}
        self._refresh_fill_tex_filter_combos()
        self._rebuild_fill_tex_browser()

    def refresh_texture_catalog(self) -> None:
        """Reload texture catalog (called on tool switch to pick up imports from other tools)."""
        if not hasattr(self, "_texture_catalog"):
            return
        self._refresh_fill_texture_browser()

    def _refresh_fill_tex_filter_combos(self) -> None:
        self._fill_tex_game_combo.blockSignals(True)
        cur_game = self._fill_tex_game_combo.currentText()
        self._fill_tex_game_combo.clear()
        self._fill_tex_game_combo.addItem("All")
        for g in self._texture_catalog.games():
            self._fill_tex_game_combo.addItem(g)
        idx = self._fill_tex_game_combo.findText(cur_game)
        if idx >= 0:
            self._fill_tex_game_combo.setCurrentIndex(idx)
        self._fill_tex_game_combo.blockSignals(False)

        self._fill_tex_cat_combo.blockSignals(True)
        cur_cat = self._fill_tex_cat_combo.currentText()
        self._fill_tex_cat_combo.clear()
        self._fill_tex_cat_combo.addItem("All")
        for cat in self._texture_catalog.categories():
            self._fill_tex_cat_combo.addItem(cat)
        idx = self._fill_tex_cat_combo.findText(cur_cat)
        if idx >= 0:
            self._fill_tex_cat_combo.setCurrentIndex(idx)
        self._fill_tex_cat_combo.blockSignals(False)

    def _filtered_fill_textures(self) -> list[LibraryTexture]:
        game = self._fill_tex_game_combo.currentText()
        cat = self._fill_tex_cat_combo.currentText()
        search = self._fill_tex_search.text().strip().lower()
        result = []
        for tex in self._texture_catalog.textures:
            if game != "All" and tex.game != game:
                continue
            if cat != "All" and tex.category != cat:
                continue
            if search and search not in tex.display_name.lower():
                continue
            result.append(tex)
        return result

    def _rebuild_fill_tex_browser(self) -> None:
        for btn in self._texture_browser_buttons.values():
            self._fill_tex_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._texture_browser_buttons.clear()

        filtered = self._filtered_fill_textures()
        cols = 3
        for i, tex in enumerate(filtered):
            btn = self._make_fill_tex_thumb(tex)
            self._fill_tex_grid_layout.addWidget(btn, i // cols, i % cols)
            self._texture_browser_buttons[tex.id] = btn

        self._update_fill_tex_selection()

    def _make_fill_tex_thumb(self, tex: LibraryTexture) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(56, 70)
        game_info = f"  ({tex.game})" if tex.game else ""
        btn.setToolTip(f"{tex.display_name}{game_info}\n{tex.category}")
        pixmap = self._get_fill_tex_thumb(tex)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(48, 48))
        btn.setText(tex.display_name[:8])
        btn.setStyleSheet("QToolButton { padding: 1px; }")
        btn.clicked.connect(lambda checked=False, t=tex: self._on_fill_tex_clicked(t))
        return btn

    def _get_fill_tex_thumb(self, tex: LibraryTexture) -> QPixmap | None:
        if tex.id in self._texture_thumb_cache:
            return self._texture_thumb_cache[tex.id]
        if not tex.exists():
            return None
        image = QImage(tex.file_path())
        if image.isNull():
            return None
        scaled = image.scaled(
            48, 48,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        self._texture_thumb_cache[tex.id] = pixmap
        return pixmap

    def _on_fill_tex_clicked(self, tex: LibraryTexture) -> None:
        self._selected_fill_texture = tex
        if self._tool:
            self._tool.fill_texture_id = tex.id
        self._update_fill_tex_selection()
        self._apply_to_selected(fill_texture_id=tex.id)

    def _update_fill_tex_selection(self) -> None:
        for tex_id, btn in self._texture_browser_buttons.items():
            if self._selected_fill_texture and tex_id == self._selected_fill_texture.id:
                btn.setStyleSheet(
                    "QToolButton { padding: 1px; border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 1px; }")

    def _on_fill_tex_filter_changed(self) -> None:
        self._rebuild_fill_tex_browser()

    def _on_fill_tex_zoom_slider(self, val: int) -> None:
        real_val = val * 0.05
        if self._tool:
            self._tool.fill_texture_zoom = real_val
        self._fill_tex_zoom_spin.blockSignals(True)
        self._fill_tex_zoom_spin.setValue(real_val)
        self._fill_tex_zoom_spin.blockSignals(False)
        self._apply_to_selected(fill_texture_zoom=real_val)

    def _on_fill_tex_zoom_spin(self, val: float) -> None:
        if self._tool:
            self._tool.fill_texture_zoom = val
        self._fill_tex_zoom_slider.blockSignals(True)
        self._fill_tex_zoom_slider.setValue(max(1, round(val * 20)))
        self._fill_tex_zoom_slider.blockSignals(False)
        self._apply_to_selected(fill_texture_zoom=val)

    def _on_fill_tex_rot_slider(self, val: int) -> None:
        if self._tool:
            self._tool.fill_texture_rotation = float(val)
        self._fill_tex_rot_spin.blockSignals(True)
        self._fill_tex_rot_spin.setValue(val)
        self._fill_tex_rot_spin.blockSignals(False)
        self._sync_fill_tex_rot_buttons(val)
        self._apply_to_selected(fill_texture_rotation=float(val))

    def _on_fill_tex_rot_spin(self, val: int) -> None:
        if self._tool:
            self._tool.fill_texture_rotation = float(val)
        self._fill_tex_rot_slider.blockSignals(True)
        self._fill_tex_rot_slider.setValue(val)
        self._fill_tex_rot_slider.blockSignals(False)
        self._sync_fill_tex_rot_buttons(val)
        self._apply_to_selected(fill_texture_rotation=float(val))

    def _on_fill_tex_rot_preset(self, degrees: int) -> None:
        if self._tool:
            self._tool.fill_texture_rotation = float(degrees)
        self._fill_tex_rot_slider.blockSignals(True)
        self._fill_tex_rot_slider.setValue(degrees)
        self._fill_tex_rot_slider.blockSignals(False)
        self._fill_tex_rot_spin.blockSignals(True)
        self._fill_tex_rot_spin.setValue(degrees)
        self._fill_tex_rot_spin.blockSignals(False)
        self._sync_fill_tex_rot_buttons(degrees)
        self._apply_to_selected(fill_texture_rotation=float(degrees))

    def _sync_fill_tex_rot_buttons(self, val: int) -> None:
        for i, deg in enumerate((0, 60, 90, 120, 180, 270)):
            self._fill_tex_rot_buttons[i].setChecked(deg == val)

    # --- Selection sync ---

    def _get_sketch_layer(self) -> SketchLayer | None:
        if not self._tool:
            return None
        layer = self._tool._project.layer_stack.active_layer
        if isinstance(layer, SketchLayer):
            return layer
        return None

    def _on_selection_changed(self, obj) -> None:
        """Called when the selected sketch object changes."""
        if obj:
            self._sync_widgets_from_object(obj)

    def _sync_widgets_from_object(self, obj) -> None:
        """Sync all widget values from a SketchObject."""
        self._over_grid_cb.blockSignals(True)
        self._over_grid_cb.setChecked(obj.draw_over_grid)
        self._over_grid_cb.blockSignals(False)

        self._shape_combo.blockSignals(True)
        self._shape_combo.setCurrentText(_SHAPE_REVERSE.get(obj.shape_type, "Rectangle"))
        self._shape_combo.blockSignals(False)
        self._sides_container.setEnabled(obj.shape_type == "polygon")
        self._close_cb.setEnabled(obj.shape_type == "freehand")
        self._perfect_circle_cb.setEnabled(obj.shape_type == "ellipse")

        self._sides_spin.blockSignals(True)
        self._sides_spin.setValue(obj.num_sides)
        self._sides_spin.blockSignals(False)

        self._close_cb.blockSignals(True)
        self._close_cb.setChecked(obj.closed)
        self._close_cb.blockSignals(False)

        update_color_btn(self._stroke_color_btn, QColor(obj.stroke_color))

        self._width_slider.blockSignals(True)
        self._width_slider.setValue(int(obj.stroke_width * 2))
        self._width_slider.blockSignals(False)
        self._width_spin.blockSignals(True)
        self._width_spin.setValue(obj.stroke_width)
        self._width_spin.blockSignals(False)

        stroke_type = getattr(obj, "stroke_type", "solid")
        self._stroke_type_combo.blockSignals(True)
        self._stroke_type_combo.setCurrentText(
            {"solid": "Solid", "dashed": "Dashed", "dotted": "Dotted"}.get(stroke_type, "Solid")
        )
        self._stroke_type_combo.blockSignals(False)
        self._dash_gap_widget.setEnabled(stroke_type != "solid")

        stroke_cap = getattr(obj, "stroke_cap", "round")
        self._stroke_cap_combo.blockSignals(True)
        self._stroke_cap_combo.setCurrentText(
            {"flat": "Flat", "round": "Round", "square": "Square"}.get(stroke_cap, "Round")
        )
        self._stroke_cap_combo.blockSignals(False)

        dash_len = getattr(obj, "dash_length", 8.0)
        self._dash_length_slider.blockSignals(True)
        self._dash_length_slider.setValue(max(1, round(dash_len * 10)))
        self._dash_length_slider.blockSignals(False)
        self._dash_length_spin.blockSignals(True)
        self._dash_length_spin.setValue(dash_len)
        self._dash_length_spin.blockSignals(False)

        gap_len = getattr(obj, "gap_length", 4.0)
        self._gap_length_slider.blockSignals(True)
        self._gap_length_slider.setValue(max(1, round(gap_len * 10)))
        self._gap_length_slider.blockSignals(False)
        self._gap_length_spin.blockSignals(True)
        self._gap_length_spin.setValue(gap_len)
        self._gap_length_spin.blockSignals(False)

        self._fill_cb.blockSignals(True)
        self._fill_cb.setChecked(obj.fill_enabled)
        self._fill_cb.blockSignals(False)
        self._fill_container.setEnabled(obj.fill_enabled)
        update_color_btn(self._fill_color_btn, QColor(obj.fill_color))

        # Fill type (M11: blockSignals to avoid undo pollution on selection)
        fill_type = getattr(obj, "fill_type", "color")
        _fill_btn = self._fill_type_group.button(1 if fill_type == "texture" else 0)
        _fill_btn.blockSignals(True)
        _fill_btn.setChecked(True)
        _fill_btn.blockSignals(False)
        self._fill_color_sub.setVisible(fill_type != "texture")
        self._fill_texture_sub.setVisible(fill_type == "texture")

        self._fill_opacity_slider.blockSignals(True)
        self._fill_opacity_slider.setValue(int(obj.fill_opacity * 100))
        self._fill_opacity_slider.blockSignals(False)
        self._fill_opacity_spin.blockSignals(True)
        self._fill_opacity_spin.setValue(obj.fill_opacity)
        self._fill_opacity_spin.blockSignals(False)

        # Texture fill widgets
        fill_tex_zoom = getattr(obj, "fill_texture_zoom", 1.0)
        fill_tex_rot = getattr(obj, "fill_texture_rotation", 0.0)
        self._fill_tex_zoom_slider.blockSignals(True)
        self._fill_tex_zoom_slider.setValue(max(1, round(fill_tex_zoom * 20)))
        self._fill_tex_zoom_slider.blockSignals(False)
        self._fill_tex_zoom_spin.blockSignals(True)
        self._fill_tex_zoom_spin.setValue(fill_tex_zoom)
        self._fill_tex_zoom_spin.blockSignals(False)
        self._fill_tex_rot_slider.blockSignals(True)
        self._fill_tex_rot_slider.setValue(int(fill_tex_rot))
        self._fill_tex_rot_slider.blockSignals(False)
        self._fill_tex_rot_spin.blockSignals(True)
        self._fill_tex_rot_spin.setValue(int(fill_tex_rot))
        self._fill_tex_rot_spin.blockSignals(False)
        self._sync_fill_tex_rot_buttons(int(fill_tex_rot))

        # Update fill texture browser selection
        fill_texture_id = getattr(obj, "fill_texture_id", "")
        if fill_texture_id and self._texture_catalog:
            self._selected_fill_texture = None
            for tex in self._texture_catalog.textures:
                if tex.id == fill_texture_id:
                    self._selected_fill_texture = tex
                    break
            self._update_fill_tex_selection()
        else:
            self._selected_fill_texture = None
            self._update_fill_tex_selection()

        self._rot_slider.blockSignals(True)
        self._rot_slider.setValue(int(obj.rotation) % 360)
        self._rot_slider.blockSignals(False)
        self._rot_spin.blockSignals(True)
        self._rot_spin.setValue(int(obj.rotation) % 360)
        self._rot_spin.blockSignals(False)

        # Update tool properties so new objects use same settings
        self._tool.stroke_color = obj.stroke_color
        self._tool.stroke_width = obj.stroke_width
        self._tool.stroke_type = getattr(obj, "stroke_type", "solid")
        self._tool.dash_length = getattr(obj, "dash_length", 8.0)
        self._tool.gap_length = getattr(obj, "gap_length", 4.0)
        self._tool.stroke_cap = getattr(obj, "stroke_cap", "round")
        self._tool.fill_enabled = obj.fill_enabled
        self._tool.fill_color = obj.fill_color
        self._tool.fill_opacity = obj.fill_opacity
        self._tool.fill_type = getattr(obj, "fill_type", "color")
        self._tool.fill_texture_id = getattr(obj, "fill_texture_id", "")
        self._tool.fill_texture_zoom = getattr(obj, "fill_texture_zoom", 1.0)
        self._tool.fill_texture_rotation = getattr(obj, "fill_texture_rotation", 0.0)
        self._tool.rotation = obj.rotation
        self._tool.draw_over_grid = obj.draw_over_grid
        self._tool.shape_type = obj.shape_type
        self._tool.num_sides = getattr(obj, "num_sides", 6)
        self._tool.closed = getattr(obj, "closed", True)

    def _apply_to_selected(self, **changes) -> None:
        """Apply property changes to the selected object via EditCommand."""
        if self._tool and self._tool.mode == "select" and self._tool.selected:
            layer = self._get_sketch_layer()
            if layer:
                cmd = EditSketchCommand(layer, self._tool.selected, **changes)
                self._tool._command_stack.execute(cmd)

    # --- Mode ---

    def _on_mode_changed(self, btn_id: int, checked: bool) -> None:
        if not checked or not self._tool:
            return
        self._tool.mode = "draw" if btn_id == 0 else "select"
        self._tool._selected = None
        self._tool._interaction = None
        self._tool._notify_selection()

    def _on_over_grid_changed(self, checked: bool) -> None:
        if not self._tool:
            return
        self._tool.draw_over_grid = checked
        self._apply_to_selected(draw_over_grid=checked)

    # --- Shape ---

    def _on_shape_changed(self, text: str) -> None:
        if not self._tool:
            return
        self._tool.shape_type = _SHAPE_MAP.get(text, "rect")
        self._sides_container.setEnabled(text == "Polygon")
        self._close_cb.setEnabled(text == "Freehand")
        self._perfect_circle_cb.setEnabled(text == "Ellipse")

    def _on_sides_changed(self, val: int) -> None:
        if self._tool:
            self._tool.num_sides = val
            self._apply_to_selected(num_sides=val)

    def _on_close_changed(self, checked: bool) -> None:
        if self._tool:
            self._tool.closed = checked
            self._apply_to_selected(closed=checked)

    def _on_perfect_circle_changed(self, checked: bool) -> None:
        if self._tool:
            self._tool.perfect_circle = checked

    def _on_snap_changed(self, checked: bool) -> None:
        if self._tool:
            self._tool.snap_to_grid = checked

    # --- Stroke ---

    def _on_stroke_color(self) -> None:
        if not self._tool:
            return
        color = QColorDialog.getColor(
            QColor(self._tool.stroke_color),
            self.dock.window(), "Stroke Color",
        )
        if color.isValid():
            self._tool.stroke_color = color.name()
            update_color_btn(self._stroke_color_btn, color)
            self._apply_to_selected(stroke_color=color.name())

    def _on_width_slider(self, val: int) -> None:
        if not self._tool:
            return
        w = val / 2.0
        self._tool.stroke_width = w
        self._width_spin.blockSignals(True)
        self._width_spin.setValue(w)
        self._width_spin.blockSignals(False)
        self._apply_to_selected(stroke_width=w)

    def _on_width_spin(self, val: float) -> None:
        if not self._tool:
            return
        self._tool.stroke_width = val
        self._width_slider.blockSignals(True)
        self._width_slider.setValue(int(val * 2))
        self._width_slider.blockSignals(False)
        self._apply_to_selected(stroke_width=val)

    def _on_stroke_type(self, text: str) -> None:
        t = {"Solid": "solid", "Dashed": "dashed", "Dotted": "dotted"}.get(text, "solid")
        if self._tool:
            self._tool.stroke_type = t
            self._apply_to_selected(stroke_type=t)
        self._dash_gap_widget.setEnabled(t != "solid")

    def _on_stroke_cap(self, text: str) -> None:
        c = {"Flat": "flat", "Round": "round", "Square": "square"}.get(text, "round")
        if self._tool:
            self._tool.stroke_cap = c
            self._apply_to_selected(stroke_cap=c)

    def _on_dash_slider(self, val: int) -> None:
        real_val = val * 0.1
        if self._tool:
            self._tool.dash_length = real_val
        self._dash_length_spin.blockSignals(True)
        self._dash_length_spin.setValue(real_val)
        self._dash_length_spin.blockSignals(False)
        self._apply_to_selected(dash_length=real_val)

    def _on_dash_spin(self, val: float) -> None:
        if self._tool:
            self._tool.dash_length = val
        self._dash_length_slider.blockSignals(True)
        self._dash_length_slider.setValue(max(1, round(val * 10)))
        self._dash_length_slider.blockSignals(False)
        self._apply_to_selected(dash_length=val)

    def _on_gap_slider(self, val: int) -> None:
        real_val = val * 0.1
        if self._tool:
            self._tool.gap_length = real_val
        self._gap_length_spin.blockSignals(True)
        self._gap_length_spin.setValue(real_val)
        self._gap_length_spin.blockSignals(False)
        self._apply_to_selected(gap_length=real_val)

    def _on_gap_spin(self, val: float) -> None:
        if self._tool:
            self._tool.gap_length = val
        self._gap_length_slider.blockSignals(True)
        self._gap_length_slider.setValue(max(1, round(val * 10)))
        self._gap_length_slider.blockSignals(False)
        self._apply_to_selected(gap_length=val)

    # --- Fill ---

    def _on_fill_toggled(self, checked: bool) -> None:
        if self._tool:
            self._tool.fill_enabled = checked
            self._apply_to_selected(fill_enabled=checked)
        self._fill_container.setEnabled(checked)

    def _on_fill_type_changed(self, btn_id: int, checked: bool) -> None:
        if not checked or not self._tool:
            return
        ft = "texture" if btn_id == 1 else "color"
        self._tool.fill_type = ft
        self._fill_color_sub.setVisible(ft == "color")
        self._fill_texture_sub.setVisible(ft == "texture")
        self._apply_to_selected(fill_type=ft)

    def _on_fill_color(self) -> None:
        if not self._tool:
            return
        color = QColorDialog.getColor(
            QColor(self._tool.fill_color),
            self.dock.window(), "Fill Color",
        )
        if color.isValid():
            self._tool.fill_color = color.name()
            update_color_btn(self._fill_color_btn, color)
            self._apply_to_selected(fill_color=color.name())

    def _on_fill_opacity_slider(self, val: int) -> None:
        if not self._tool:
            return
        o = val / 100.0
        self._tool.fill_opacity = o
        self._fill_opacity_spin.blockSignals(True)
        self._fill_opacity_spin.setValue(o)
        self._fill_opacity_spin.blockSignals(False)
        self._apply_to_selected(fill_opacity=o)

    def _on_fill_opacity_spin(self, val: float) -> None:
        if not self._tool:
            return
        self._tool.fill_opacity = val
        self._fill_opacity_slider.blockSignals(True)
        self._fill_opacity_slider.setValue(int(val * 100))
        self._fill_opacity_slider.blockSignals(False)
        self._apply_to_selected(fill_opacity=val)

    # --- Shadow (layer-level) ---

    def _apply_shadow_to_layer(self, **changes) -> None:
        """Apply shadow property changes to the sketch layer."""
        layer = self._get_sketch_layer()
        if layer and self._tool:
            cmd = EditSketchLayerEffectsCommand(layer, **changes)
            self._tool._command_stack.execute(cmd)

    def sync_shadow_from_layer(self) -> None:
        """Sync shadow widgets from the active sketch layer."""
        layer = self._get_sketch_layer()
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

    def _on_shadow_toggled(self, checked: bool) -> None:
        self._apply_shadow_to_layer(shadow_enabled=checked)
        self._shadow_container.setEnabled(checked)

    def _on_shadow_type(self, text: str) -> None:
        t = "inner" if text == "Inner" else "outer"
        self._apply_shadow_to_layer(shadow_type=t)

    def _on_shadow_color(self) -> None:
        layer = self._get_sketch_layer()
        cur = layer.shadow_color if layer else "#000000"
        color = QColorDialog.getColor(
            QColor(cur), self.dock.window(), "Shadow Color",
        )
        if color.isValid():
            update_color_btn(self._shadow_color_btn, color)
            self._apply_shadow_to_layer(shadow_color=color.name())

    def _on_shadow_opacity_slider(self, val: int) -> None:
        o = val / 100.0
        self._shadow_opacity_spin.blockSignals(True)
        self._shadow_opacity_spin.setValue(o)
        self._shadow_opacity_spin.blockSignals(False)
        self._apply_shadow_to_layer(shadow_opacity=o)

    def _on_shadow_opacity_spin(self, val: float) -> None:
        self._shadow_opacity_slider.blockSignals(True)
        self._shadow_opacity_slider.setValue(int(val * 100))
        self._shadow_opacity_slider.blockSignals(False)
        self._apply_shadow_to_layer(shadow_opacity=val)

    def _on_shadow_angle_slider(self, val: int) -> None:
        self._shadow_angle_spin.blockSignals(True)
        self._shadow_angle_spin.setValue(val)
        self._shadow_angle_spin.blockSignals(False)
        self._apply_shadow_to_layer(shadow_angle=float(val))

    def _on_shadow_angle_spin(self, val: int) -> None:
        self._shadow_angle_slider.blockSignals(True)
        self._shadow_angle_slider.setValue(val)
        self._shadow_angle_slider.blockSignals(False)
        self._apply_shadow_to_layer(shadow_angle=float(val))

    def _on_shadow_dist_slider(self, val: int) -> None:
        self._shadow_dist_spin.blockSignals(True)
        self._shadow_dist_spin.setValue(float(val))
        self._shadow_dist_spin.blockSignals(False)
        self._apply_shadow_to_layer(shadow_distance=float(val))

    def _on_shadow_dist_spin(self, val: float) -> None:
        self._shadow_dist_slider.blockSignals(True)
        self._shadow_dist_slider.setValue(int(val))
        self._shadow_dist_slider.blockSignals(False)
        self._apply_shadow_to_layer(shadow_distance=val)

    def _on_shadow_spread_slider(self, val: int) -> None:
        self._shadow_spread_spin.blockSignals(True)
        self._shadow_spread_spin.setValue(val)
        self._shadow_spread_spin.blockSignals(False)
        self._apply_shadow_to_layer(shadow_spread=float(val))

    def _on_shadow_spread_spin(self, val: int) -> None:
        self._shadow_spread_slider.blockSignals(True)
        self._shadow_spread_slider.setValue(val)
        self._shadow_spread_slider.blockSignals(False)
        self._apply_shadow_to_layer(shadow_spread=float(val))

    def _on_shadow_size_slider(self, val: int) -> None:
        self._shadow_size_spin.blockSignals(True)
        self._shadow_size_spin.setValue(float(val))
        self._shadow_size_spin.blockSignals(False)
        self._apply_shadow_to_layer(shadow_size=float(val))

    def _on_shadow_size_spin(self, val: float) -> None:
        self._shadow_size_slider.blockSignals(True)
        self._shadow_size_slider.setValue(int(val))
        self._shadow_size_slider.blockSignals(False)
        self._apply_shadow_to_layer(shadow_size=val)

    # --- Rotation ---

    def _on_rot_slider(self, val: int) -> None:
        if not self._tool:
            return
        self._tool.rotation = float(val)
        self._rot_spin.blockSignals(True)
        self._rot_spin.setValue(val)
        self._rot_spin.blockSignals(False)
        self._apply_to_selected(rotation=float(val))

    def _on_rot_spin(self, val: int) -> None:
        if not self._tool:
            return
        self._tool.rotation = float(val)
        self._rot_slider.blockSignals(True)
        self._rot_slider.setValue(val)
        self._rot_slider.blockSignals(False)
        self._apply_to_selected(rotation=float(val))

    def _set_rotation(self, angle: int) -> None:
        if not self._tool:
            return
        self._tool.rotation = float(angle)
        self._rot_slider.blockSignals(True)
        self._rot_slider.setValue(angle)
        self._rot_slider.blockSignals(False)
        self._rot_spin.blockSignals(True)
        self._rot_spin.setValue(angle)
        self._rot_spin.blockSignals(False)
        self._apply_to_selected(rotation=float(angle))
