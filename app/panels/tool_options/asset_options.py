"""Asset tool options builder."""

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
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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

from app.panels.tool_options.helpers import update_color_btn

from app.io.asset_library import (
    AssetCatalog,
    LibraryAsset,
    load_catalog,
)
from app.panels.asset_manager_dialog import AssetManagerDialog
from app.panels.tool_options.sidebar_widgets import AssetBrowserSidebar
from app.tools.asset_tool import AssetTool
from app.io.text_preset_manager import list_text_presets, load_text_preset
from app.models.text_object import TextObject
from app.layers.text_layer import TextLayer
from app.commands.text_commands import PlaceTextCommand

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel


class AssetOptions:
    """Builds and manages the asset tool options UI."""

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._asset_tool: AssetTool | None = None
        self._sidebar: AssetBrowserSidebar | None = None

    def create(self, tool: AssetTool) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)

        self._asset_tool = tool
        tool.on_selection_changed = self._on_selection_changed
        tool._on_erase_size_changed = self._sync_erase_size
        self._asset_catalog: AssetCatalog = load_catalog()
        self._asset_thumb_cache: dict[str, QPixmap] = {}
        self._asset_browser_buttons: dict[str, QPushButton] = {}
        self._selected_browser_asset: LibraryAsset | None = None

        # ===== Mode group =====
        mode_group = QGroupBox("Mode")
        mode_gl = QVBoxLayout(mode_group)
        mode_gl.setContentsMargins(6, 4, 6, 4)

        mode_btn_layout = QHBoxLayout()
        place_btn = QPushButton("Place")
        place_btn.setCheckable(True)
        place_btn.setChecked(True)
        select_btn = QPushButton("Select")
        select_btn.setCheckable(True)
        erase_btn = QPushButton("Erase")
        erase_btn.setCheckable(True)

        self._asset_mode_group = QButtonGroup(widget)
        self._asset_mode_group.setExclusive(True)
        self._asset_mode_group.addButton(place_btn, 0)
        self._asset_mode_group.addButton(select_btn, 1)
        self._asset_mode_group.addButton(erase_btn, 2)
        self._asset_mode_group.idToggled.connect(self._on_asset_mode_changed)

        mode_btn_layout.addWidget(place_btn)
        mode_btn_layout.addWidget(select_btn)
        mode_btn_layout.addWidget(erase_btn)
        mode_btn_layout.addStretch()
        mode_gl.addLayout(mode_btn_layout)

        # Erase size controls (visible only in erase mode)
        self._erase_size_container = QWidget()
        erase_size_vl = QVBoxLayout(self._erase_size_container)
        erase_size_vl.setContentsMargins(0, 4, 0, 0)
        erase_size_vl.addWidget(QLabel("Size:"))
        erase_slider_row = QHBoxLayout()
        self._erase_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._erase_size_slider.setRange(5, 300)
        self._erase_size_slider.setValue(int(tool.erase_brush_size))
        self._erase_size_slider.valueChanged.connect(self._on_erase_size_slider)
        erase_slider_row.addWidget(self._erase_size_slider, stretch=1)
        self._erase_size_spin = QSpinBox()
        self._erase_size_spin.setRange(5, 300)
        self._erase_size_spin.setValue(int(tool.erase_brush_size))
        self._erase_size_spin.setSuffix("px")
        self._erase_size_spin.setFixedWidth(70)
        self._erase_size_spin.valueChanged.connect(self._on_erase_size_spin)
        erase_slider_row.addWidget(self._erase_size_spin)
        erase_size_vl.addLayout(erase_slider_row)
        self._erase_size_container.setVisible(False)
        mode_gl.addWidget(self._erase_size_container)

        layout.addWidget(mode_group)

        # ===== Browser group =====
        browser_group = QGroupBox("Assets")
        browser_gl = QVBoxLayout(browser_group)
        browser_gl.setContentsMargins(6, 4, 6, 4)

        game_layout = QHBoxLayout()
        game_layout.addWidget(QLabel("Game:"))
        self._asset_game_combo = QComboBox()
        self._asset_game_combo.setMinimumWidth(80)
        self._asset_game_combo.currentTextChanged.connect(self._on_asset_filter_changed)
        game_layout.addWidget(self._asset_game_combo, stretch=1)
        browser_gl.addLayout(game_layout)

        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("Category:"))
        self._asset_category_combo = QComboBox()
        self._asset_category_combo.setMinimumWidth(80)
        self._asset_category_combo.currentTextChanged.connect(self._on_asset_filter_changed)
        cat_layout.addWidget(self._asset_category_combo, stretch=1)
        browser_gl.addLayout(cat_layout)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self._asset_search_edit = QLineEdit()
        self._asset_search_edit.setPlaceholderText("Filter by name...")
        self._asset_search_edit.textChanged.connect(self._on_asset_filter_changed)
        search_layout.addWidget(self._asset_search_edit, stretch=1)
        browser_gl.addLayout(search_layout)

        self._asset_scroll = QScrollArea()
        self._asset_scroll.setWidgetResizable(True)
        self._asset_scroll.setMinimumHeight(180)
        self._asset_scroll.setMaximumHeight(180)
        self._asset_grid_container = QWidget()
        self._asset_grid_layout = QGridLayout(self._asset_grid_container)
        self._asset_grid_layout.setSpacing(4)
        self._asset_grid_layout.setContentsMargins(2, 2, 2, 2)
        self._asset_scroll.setWidget(self._asset_grid_container)
        browser_gl.addWidget(self._asset_scroll)

        btn_layout = QHBoxLayout()
        manager_btn = QPushButton("Manager...")
        manager_btn.clicked.connect(self._on_open_asset_manager)
        btn_layout.addWidget(manager_btn)
        self._maximize_btn = QPushButton("Expand")
        self._maximize_btn.setCheckable(True)
        self._maximize_btn.clicked.connect(self._on_toggle_sidebar)
        btn_layout.addWidget(self._maximize_btn)
        browser_gl.addLayout(btn_layout)

        layout.addWidget(browser_group)

        # ===== Placement group =====
        placement_group = QGroupBox("Placement")
        placement_gl = QVBoxLayout(placement_group)
        placement_gl.setContentsMargins(6, 4, 6, 4)

        # Randomize assets (top of group)
        randomize_layout = QHBoxLayout()
        self._randomize_cb = QCheckBox("Randomize")
        self._randomize_cb.setChecked(False)
        self._randomize_cb.toggled.connect(self._on_randomize_toggled)
        randomize_layout.addWidget(self._randomize_cb)
        self._pool_label = QLabel("(0 assets)")
        self._pool_label.setEnabled(False)
        randomize_layout.addWidget(self._pool_label)
        randomize_layout.addStretch()
        placement_gl.addLayout(randomize_layout)

        self._random_pool_ids: set[str] = set()

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        placement_gl.addWidget(sep1)

        # Rasterize controls
        self._rasterize_cb = QCheckBox("Rasterize")
        self._rasterize_cb.setChecked(tool.rasterize)
        placement_gl.addWidget(self._rasterize_cb)

        # Rasterize sub-controls (visible only when rasterize is checked)
        self._rasterize_details = QWidget()
        rasterize_details_gl = QVBoxLayout(self._rasterize_details)
        rasterize_details_gl.setContentsMargins(0, 0, 0, 0)

        rasterize_mode_layout = QHBoxLayout()
        rasterize_mode_layout.setSpacing(4)
        rasterize_mode_layout.addWidget(QLabel("Mode:"))
        self._rasterize_edge_btn = QPushButton("Edge")
        self._rasterize_edge_btn.setCheckable(True)
        self._rasterize_edge_btn.setChecked(tool.rasterize_mode == "edge")
        self._rasterize_corner_btn = QPushButton("Corner")
        self._rasterize_corner_btn.setCheckable(True)
        self._rasterize_corner_btn.setChecked(tool.rasterize_mode == "corner")
        self._rasterize_mode_group = QButtonGroup(widget)
        self._rasterize_mode_group.setExclusive(True)
        self._rasterize_mode_group.addButton(self._rasterize_edge_btn, 0)
        self._rasterize_mode_group.addButton(self._rasterize_corner_btn, 1)
        self._rasterize_mode_group.idToggled.connect(self._on_rasterize_mode_changed)
        rasterize_mode_layout.addWidget(self._rasterize_edge_btn)
        rasterize_mode_layout.addWidget(self._rasterize_corner_btn)
        rasterize_mode_layout.addStretch()
        rasterize_details_gl.addLayout(rasterize_mode_layout)

        self._rasterize_fixed_cb = QCheckBox("Fixed")
        self._rasterize_fixed_cb.setChecked(tool.rasterize_fixed)
        self._rasterize_fixed_cb.toggled.connect(self._on_rasterize_fixed_toggled)
        rasterize_details_gl.addWidget(self._rasterize_fixed_cb)

        self._rasterize_pct_row = QWidget()
        rasterize_pct_vl = QVBoxLayout(self._rasterize_pct_row)
        rasterize_pct_vl.setContentsMargins(0, 0, 0, 0)
        pct_slider_row = QHBoxLayout()
        self._rasterize_pct_slider = QSlider(Qt.Orientation.Horizontal)
        self._rasterize_pct_slider.setRange(0, 100)
        self._rasterize_pct_slider.setValue(tool.rasterize_fixed_pct)
        self._rasterize_pct_slider.valueChanged.connect(self._on_rasterize_pct_slider)
        pct_slider_row.addWidget(self._rasterize_pct_slider, stretch=1)
        self._rasterize_pct_spin = QSpinBox()
        self._rasterize_pct_spin.setRange(0, 100)
        self._rasterize_pct_spin.setValue(tool.rasterize_fixed_pct)
        self._rasterize_pct_spin.setSuffix("%")
        self._rasterize_pct_spin.setFixedWidth(70)
        self._rasterize_pct_spin.valueChanged.connect(self._on_rasterize_pct_spin)
        pct_slider_row.addWidget(self._rasterize_pct_spin)
        rasterize_pct_vl.addLayout(pct_slider_row)
        self._rasterize_pct_row.setEnabled(tool.rasterize_fixed)
        rasterize_details_gl.addWidget(self._rasterize_pct_row)

        self._rasterize_details.setEnabled(tool.rasterize)
        placement_gl.addWidget(self._rasterize_details)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        placement_gl.addWidget(sep2)

        # Snap to hex
        self._snap_cb = QCheckBox("Snap to Hex Center")
        self._snap_cb.setChecked(tool.snap_to_hex)
        placement_gl.addWidget(self._snap_cb)

        # Radius sub-controls (visible only when snap is checked)
        self._snap_radius_details = QWidget()
        snap_radius_gl = QVBoxLayout(self._snap_radius_details)
        snap_radius_gl.setContentsMargins(0, 0, 0, 0)

        snap_radius_gl.addWidget(QLabel("Radius:"))
        radius_slider_row = QHBoxLayout()
        self._asset_radius_slider = QSlider(Qt.Orientation.Horizontal)
        self._asset_radius_slider.setRange(0, 10)
        self._asset_radius_slider.setValue(tool.placement_radius)
        self._asset_radius_slider.valueChanged.connect(self._on_asset_radius_slider)
        radius_slider_row.addWidget(self._asset_radius_slider, stretch=1)
        self._asset_radius_spin = QSpinBox()
        self._asset_radius_spin.setRange(0, 10)
        self._asset_radius_spin.setValue(tool.placement_radius)
        self._asset_radius_spin.setFixedWidth(55)
        self._asset_radius_spin.valueChanged.connect(self._on_asset_radius_spin_changed)
        radius_slider_row.addWidget(self._asset_radius_spin)
        snap_radius_gl.addLayout(radius_slider_row)

        self._asset_radius_buttons: list[QPushButton] = []
        radius_btn_layout = QHBoxLayout()
        radius_btn_layout.setSpacing(2)
        for val in (0, 1, 2, 3, 5):
            btn = QPushButton(str(val))
            btn.setCheckable(True)
            btn.setFixedWidth(28)
            btn.setChecked(val == tool.placement_radius)
            btn.clicked.connect(lambda _, v=val: self._on_asset_radius_btn(v))
            radius_btn_layout.addWidget(btn)
            self._asset_radius_buttons.append(btn)
        radius_btn_layout.addStretch()
        snap_radius_gl.addLayout(radius_btn_layout)

        self._snap_radius_details.setEnabled(tool.snap_to_hex)
        placement_gl.addWidget(self._snap_radius_details)

        # Connect snap and rasterize toggles
        self._snap_cb.toggled.connect(self._on_snap_toggled)
        self._rasterize_cb.toggled.connect(self._on_rasterize_toggled)


        layout.addWidget(placement_group)

        # ===== Scale group =====
        scale_group = QGroupBox("Scale")
        scale_gl = QVBoxLayout(scale_group)
        scale_gl.setContentsMargins(6, 4, 6, 4)

        scale_gl.addWidget(QLabel("Scale:"))
        scale_slider_row = QHBoxLayout()
        self._asset_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._asset_scale_slider.setRange(5, 500)  # 0.05-5.0 in 0.01 steps
        self._asset_scale_slider.setValue(max(5, round(tool.placement_scale * 100)))
        self._asset_scale_slider.valueChanged.connect(self._on_asset_scale_slider)
        scale_slider_row.addWidget(self._asset_scale_slider, stretch=1)
        self._asset_scale_spin = QDoubleSpinBox()
        self._asset_scale_spin.setRange(0.05, 5.0)
        self._asset_scale_spin.setSingleStep(0.01)
        self._asset_scale_spin.setDecimals(2)
        self._asset_scale_spin.setValue(tool.placement_scale)
        self._asset_scale_spin.setSuffix("x")
        self._asset_scale_spin.setFixedWidth(65)
        self._asset_scale_spin.valueChanged.connect(self._on_asset_scale_spin)
        scale_slider_row.addWidget(self._asset_scale_spin)
        scale_gl.addLayout(scale_slider_row)

        self._random_size_cb = QCheckBox("Random Size")
        self._random_size_cb.setChecked(tool.random_size)
        self._random_size_cb.toggled.connect(self._on_random_size_toggled)
        scale_gl.addWidget(self._random_size_cb)

        # Min/Max controls (visible only when random size is checked)
        self._random_size_details = QWidget()
        random_size_gl = QVBoxLayout(self._random_size_details)
        random_size_gl.setContentsMargins(0, 0, 0, 0)

        random_size_gl.addWidget(QLabel("Min:"))
        min_slider_row = QHBoxLayout()
        self._random_size_min_slider = QSlider(Qt.Orientation.Horizontal)
        self._random_size_min_slider.setRange(1, 50)  # 0.1-5.0
        self._random_size_min_slider.setValue(int(tool.random_size_min * 10))
        self._random_size_min_slider.valueChanged.connect(self._on_size_min_slider)
        min_slider_row.addWidget(self._random_size_min_slider, stretch=1)
        self._random_size_min_spin = QDoubleSpinBox()
        self._random_size_min_spin.setRange(0.1, 5.0)
        self._random_size_min_spin.setSingleStep(0.1)
        self._random_size_min_spin.setValue(tool.random_size_min)
        self._random_size_min_spin.setSuffix("x")
        self._random_size_min_spin.setFixedWidth(65)
        self._random_size_min_spin.valueChanged.connect(self._on_size_min_spin)
        min_slider_row.addWidget(self._random_size_min_spin)
        random_size_gl.addLayout(min_slider_row)

        random_size_gl.addWidget(QLabel("Max:"))
        max_slider_row = QHBoxLayout()
        self._random_size_max_slider = QSlider(Qt.Orientation.Horizontal)
        self._random_size_max_slider.setRange(1, 50)  # 0.1-5.0
        self._random_size_max_slider.setValue(int(tool.random_size_max * 10))
        self._random_size_max_slider.valueChanged.connect(self._on_size_max_slider)
        max_slider_row.addWidget(self._random_size_max_slider, stretch=1)
        self._random_size_max_spin = QDoubleSpinBox()
        self._random_size_max_spin.setRange(0.1, 5.0)
        self._random_size_max_spin.setSingleStep(0.1)
        self._random_size_max_spin.setValue(tool.random_size_max)
        self._random_size_max_spin.setSuffix("x")
        self._random_size_max_spin.setFixedWidth(65)
        self._random_size_max_spin.valueChanged.connect(self._on_size_max_spin)
        max_slider_row.addWidget(self._random_size_max_spin)
        random_size_gl.addLayout(max_slider_row)

        self._random_size_details.setEnabled(tool.random_size)
        scale_gl.addWidget(self._random_size_details)

        self._asset_scale_spin.setEnabled(not tool.random_size)

        layout.addWidget(scale_group)

        # ===== Rotation group =====
        rotation_group = QGroupBox("Rotation")
        rotation_gl = QVBoxLayout(rotation_group)
        rotation_gl.setContentsMargins(6, 4, 6, 4)

        rotation_gl.addWidget(QLabel("Rotation:"))
        rot_slider_row = QHBoxLayout()
        self._asset_rot_slider = QSlider(Qt.Orientation.Horizontal)
        self._asset_rot_slider.setRange(0, 359)
        self._asset_rot_slider.setValue(0)
        self._asset_rot_slider.valueChanged.connect(self._on_asset_rot_slider)
        rot_slider_row.addWidget(self._asset_rot_slider, stretch=1)
        self._asset_rot_spin = QSpinBox()
        self._asset_rot_spin.setRange(0, 359)
        self._asset_rot_spin.setSuffix("\u00b0")
        self._asset_rot_spin.setValue(0)
        self._asset_rot_spin.setFixedWidth(70)
        self._asset_rot_spin.setWrapping(True)
        self._asset_rot_spin.valueChanged.connect(self._on_asset_rotation_changed)
        rot_slider_row.addWidget(self._asset_rot_spin)
        rotation_gl.addLayout(rot_slider_row)

        self._random_rot_cb = QCheckBox("Random Rotation")
        self._random_rot_cb.setChecked(tool.random_rotation)
        self._random_rot_cb.toggled.connect(self._on_random_rotation_toggled)
        rotation_gl.addWidget(self._random_rot_cb)

        # 30° step rotation buttons (two rows)
        self._rot_buttons: list[QPushButton] = []
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(2)
        for deg in (0, 30, 60, 90, 120, 150):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(36)
            btn.setChecked(deg == 0)
            btn.clicked.connect(lambda _, d=deg: self._on_rot_btn_clicked(d))
            row1_layout.addWidget(btn)
            self._rot_buttons.append(btn)
        row1_layout.addStretch()
        rotation_gl.addLayout(row1_layout)

        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(2)
        for deg in (180, 210, 240, 270, 300, 330):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(36)
            btn.clicked.connect(lambda _, d=deg: self._on_rot_btn_clicked(d))
            row2_layout.addWidget(btn)
            self._rot_buttons.append(btn)
        row2_layout.addStretch()
        rotation_gl.addLayout(row2_layout)

        self._set_rotation_controls_enabled(not tool.random_rotation)

        layout.addWidget(rotation_group)

        # ===== Shadow group (layer-level) =====
        shadow_group = QGroupBox("Shadow")
        shadow_gl = QVBoxLayout(shadow_group)
        shadow_gl.setContentsMargins(6, 4, 6, 4)

        self._shadow_cb = QCheckBox("Enable Shadow")
        layer = self._get_asset_layer()
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
        update_color_btn(
            self._shadow_color_btn,
            QColor(layer.shadow_color if layer else "#000000"),
        )
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

        # ===== Eraser group =====
        eraser_group = QGroupBox("Eraser")
        eraser_gl = QVBoxLayout(eraser_group)
        eraser_gl.setContentsMargins(6, 4, 6, 4)

        clear_mask_btn = QPushButton("Clear Mask")
        clear_mask_btn.setToolTip("Remove the erase mask and restore all assets")
        clear_mask_btn.clicked.connect(self._on_clear_mask)
        eraser_gl.addWidget(clear_mask_btn)

        self._eraser_group = eraser_group
        eraser_group.setEnabled(False)
        layout.addWidget(eraser_group)

        # ===== Auto-Text group =====
        auto_text_group = QGroupBox("Auto-Text")
        auto_text_gl = QVBoxLayout(auto_text_group)
        auto_text_gl.setContentsMargins(6, 4, 6, 4)

        self._auto_text_cb = QCheckBox("Enable Auto-Text")
        self._auto_text_cb.setChecked(tool.auto_text_enabled)
        auto_text_gl.addWidget(self._auto_text_cb)

        # Sub-panel shown only when enabled
        self._auto_text_sub = QWidget()
        at_sub_gl = QVBoxLayout(self._auto_text_sub)
        at_sub_gl.setContentsMargins(0, 2, 0, 0)
        at_sub_gl.setSpacing(4)

        at_preset_row = QHBoxLayout()
        at_preset_row.addWidget(QLabel("Preset:"))
        self._auto_text_preset_combo = QComboBox()
        self._auto_text_preset_combo.addItem("(Default Settings)", "")
        for pname in list_text_presets():
            self._auto_text_preset_combo.addItem(pname, pname)
        at_preset_row.addWidget(self._auto_text_preset_combo, stretch=1)
        at_sub_gl.addLayout(at_preset_row)

        at_layer_row = QHBoxLayout()
        at_layer_row.addWidget(QLabel("Layer:"))
        self._auto_text_layer_combo = QComboBox()
        self._auto_text_layer_combo.addItem("(Create New)", "")
        at_layer_row.addWidget(self._auto_text_layer_combo, stretch=1)
        at_sub_gl.addLayout(at_layer_row)

        at_offset_row = QHBoxLayout()
        at_offset_row.addWidget(QLabel("Y Offset:"))
        self._auto_text_y_offset_spin = QDoubleSpinBox()
        self._auto_text_y_offset_spin.setRange(-500.0, 500.0)
        self._auto_text_y_offset_spin.setSingleStep(5.0)
        self._auto_text_y_offset_spin.setValue(-30.0)
        self._auto_text_y_offset_spin.setSuffix(" px")
        at_offset_row.addWidget(self._auto_text_y_offset_spin, stretch=1)
        at_sub_gl.addLayout(at_offset_row)

        self._auto_text_sub.setEnabled(False)
        auto_text_gl.addWidget(self._auto_text_sub)

        self._auto_text_cb.toggled.connect(self._on_auto_text_toggled)
        layout.addWidget(auto_text_group)

        # Set up Auto-Text placement callback
        tool.on_auto_text_place = self._on_auto_text_place

        # Initialize browser
        self._refresh_asset_browser()

        # Register callback for Ctrl+drag UI sync
        tool._on_placement_changed = self._sync_placement_spinners

        return widget

    # --- Asset browser ---

    def _on_asset_mode_changed(self, button_id: int, checked: bool) -> None:
        if not checked:
            return
        if button_id == 0:
            self._asset_tool.mode = "place"
            self._asset_tool._selected_asset = None
            self._asset_tool._notify_selection()
        elif button_id == 1:
            self._asset_tool.mode = "select"
        else:
            self._asset_tool.mode = "erase"
            self._asset_tool._selected_asset = None
            self._asset_tool._notify_selection()
        self._erase_size_container.setVisible(button_id == 2)
        self._eraser_group.setEnabled(button_id == 2)

    # --- Selection sync ---

    def _on_selection_changed(self, asset) -> None:
        """Called when the selected asset changes."""
        if asset:
            self._sync_widgets_from_object(asset)

    def _sync_widgets_from_object(self, asset) -> None:
        """Sync scale and rotation widgets from a selected AssetObject."""
        tool = self._asset_tool
        if tool is None:
            return

        # Update placement defaults so new placements inherit selected style
        tool.placement_scale = asset.scale
        tool.placement_rotation = asset.rotation % 360

        # Sync scale widgets
        self._asset_scale_slider.blockSignals(True)
        self._asset_scale_slider.setValue(max(5, round(asset.scale * 100)))
        self._asset_scale_slider.blockSignals(False)
        self._asset_scale_spin.blockSignals(True)
        self._asset_scale_spin.setValue(asset.scale)
        self._asset_scale_spin.blockSignals(False)

        # Sync rotation widgets
        rot_val = int(asset.rotation) % 360
        self._asset_rot_slider.blockSignals(True)
        self._asset_rot_slider.setValue(rot_val)
        self._asset_rot_slider.blockSignals(False)
        self._asset_rot_spin.blockSignals(True)
        self._asset_rot_spin.setValue(rot_val)
        self._asset_rot_spin.blockSignals(False)
        self._sync_rot_buttons(rot_val)

    def _apply_scale_to_selected(self, scale: float) -> None:
        """Apply scale to selected asset via TransformAssetCommand."""
        if (
            self._asset_tool
            and self._asset_tool.mode == "select"
            and self._asset_tool._selected_asset is not None
        ):
            from app.commands.asset_commands import TransformAssetCommand
            layer = self._asset_tool._get_active_asset_layer()
            asset = self._asset_tool._selected_asset
            if layer and asset.scale != scale:
                cmd = TransformAssetCommand(layer, asset, new_scale=scale)
                self._asset_tool._command_stack.execute(cmd)

    # --- Slider/spin sync handlers ---

    def _on_rasterize_pct_slider(self, value: int) -> None:
        self._asset_tool.rasterize_fixed_pct = value
        self._rasterize_pct_spin.blockSignals(True)
        self._rasterize_pct_spin.setValue(value)
        self._rasterize_pct_spin.blockSignals(False)

    def _on_rasterize_pct_spin(self, value: int) -> None:
        self._asset_tool.rasterize_fixed_pct = value
        self._rasterize_pct_slider.blockSignals(True)
        self._rasterize_pct_slider.setValue(value)
        self._rasterize_pct_slider.blockSignals(False)

    def _on_asset_radius_slider(self, value: int) -> None:
        self._asset_tool.placement_radius = value
        self._asset_radius_spin.blockSignals(True)
        self._asset_radius_spin.setValue(value)
        self._asset_radius_spin.blockSignals(False)
        self._sync_asset_radius_buttons(value)

    def _on_asset_scale_slider(self, value: int) -> None:
        real_val = value * 0.01
        self._asset_tool.placement_scale = real_val
        self._asset_scale_spin.blockSignals(True)
        self._asset_scale_spin.setValue(real_val)
        self._asset_scale_spin.blockSignals(False)
        self._apply_scale_to_selected(real_val)

    def _on_asset_scale_spin(self, value: float) -> None:
        self._asset_tool.placement_scale = value
        self._asset_scale_slider.blockSignals(True)
        self._asset_scale_slider.setValue(round(value * 100))
        self._asset_scale_slider.blockSignals(False)
        self._apply_scale_to_selected(value)

    def _on_size_min_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._asset_tool.random_size_min = real_val
        self._random_size_min_spin.blockSignals(True)
        self._random_size_min_spin.setValue(real_val)
        self._random_size_min_spin.blockSignals(False)

    def _on_size_min_spin(self, value: float) -> None:
        self._asset_tool.random_size_min = value
        self._random_size_min_slider.blockSignals(True)
        self._random_size_min_slider.setValue(int(value * 10))
        self._random_size_min_slider.blockSignals(False)

    def _on_size_max_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._asset_tool.random_size_max = real_val
        self._random_size_max_spin.blockSignals(True)
        self._random_size_max_spin.setValue(real_val)
        self._random_size_max_spin.blockSignals(False)

    def _on_size_max_spin(self, value: float) -> None:
        self._asset_tool.random_size_max = value
        self._random_size_max_slider.blockSignals(True)
        self._random_size_max_slider.setValue(int(value * 10))
        self._random_size_max_slider.blockSignals(False)

    def _on_asset_rot_slider(self, value: int) -> None:
        self._asset_rot_spin.blockSignals(True)
        self._asset_rot_spin.setValue(value)
        self._asset_rot_spin.blockSignals(False)
        self._sync_rot_buttons(value)
        self._apply_rotation(value)

    def _sync_placement_spinners(self) -> None:
        """Sync UI spinners after Ctrl+drag adjustment."""
        self._asset_scale_slider.blockSignals(True)
        self._asset_scale_slider.setValue(max(5, round(self._asset_tool.placement_scale * 100)))
        self._asset_scale_slider.blockSignals(False)
        self._asset_scale_spin.blockSignals(True)
        self._asset_scale_spin.setValue(self._asset_tool.placement_scale)
        self._asset_scale_spin.blockSignals(False)

        rot_val = int(self._asset_tool.placement_rotation) % 360
        self._asset_rot_slider.blockSignals(True)
        self._asset_rot_slider.setValue(rot_val)
        self._asset_rot_slider.blockSignals(False)
        self._asset_rot_spin.blockSignals(True)
        self._asset_rot_spin.setValue(rot_val)
        self._asset_rot_spin.blockSignals(False)
        self._sync_rot_buttons(rot_val)

    def _on_asset_radius_spin_changed(self, value: int) -> None:
        self._asset_tool.placement_radius = value
        self._asset_radius_slider.blockSignals(True)
        self._asset_radius_slider.setValue(value)
        self._asset_radius_slider.blockSignals(False)
        self._sync_asset_radius_buttons(value)

    def _on_snap_toggled(self, checked: bool) -> None:
        self._asset_tool.snap_to_hex = checked
        self._snap_radius_details.setEnabled(checked)
        if checked:
            # Mutual exclusion: uncheck rasterize
            self._rasterize_cb.blockSignals(True)
            self._rasterize_cb.setChecked(False)
            self._rasterize_cb.blockSignals(False)
            self._asset_tool.rasterize = False
            self._rasterize_details.setEnabled(False)

    def _on_rasterize_toggled(self, checked: bool) -> None:
        self._asset_tool.rasterize = checked
        self._rasterize_details.setEnabled(checked)
        if checked:
            # Mutual exclusion: uncheck snap
            self._snap_cb.blockSignals(True)
            self._snap_cb.setChecked(False)
            self._snap_cb.blockSignals(False)
            self._asset_tool.snap_to_hex = False
            self._snap_radius_details.setEnabled(False)

    def _on_rasterize_mode_changed(self, id: int, checked: bool) -> None:
        if not checked:
            return
        self._asset_tool.rasterize_mode = "edge" if id == 0 else "corner"

    def _on_rasterize_fixed_toggled(self, checked: bool) -> None:
        self._asset_tool.rasterize_fixed = checked
        self._rasterize_pct_row.setEnabled(checked)

    def _on_asset_radius_btn(self, value: int) -> None:
        self._asset_radius_slider.blockSignals(True)
        self._asset_radius_slider.setValue(value)
        self._asset_radius_slider.blockSignals(False)
        self._asset_radius_spin.blockSignals(True)
        self._asset_radius_spin.setValue(value)
        self._asset_radius_spin.blockSignals(False)
        self._asset_tool.placement_radius = value
        self._sync_asset_radius_buttons(value)

    def _sync_asset_radius_buttons(self, value: int) -> None:
        presets = (0, 1, 2, 3, 5)
        for i, btn in enumerate(self._asset_radius_buttons):
            btn.setChecked(presets[i] == value)

    def _on_randomize_toggled(self, checked: bool) -> None:
        self._asset_tool.randomize_assets = checked
        self._pool_label.setEnabled(checked)
        if checked:
            # Reset radius
            self._asset_radius_slider.blockSignals(True)
            self._asset_radius_slider.setValue(0)
            self._asset_radius_slider.blockSignals(False)
            self._asset_radius_spin.setValue(0)
            self._asset_tool.placement_radius = 0
            self._sync_asset_radius_buttons(0)
            # Clear single selection, start fresh pool
            self._selected_browser_asset = None
            self._random_pool_ids.clear()
            self._sync_random_pool()
        else:
            # Clear pool, revert to single-select
            self._random_pool_ids.clear()
            self._asset_tool.randomize_assets = False
            self._asset_tool.set_random_pool([])
        self._update_browser_selection()
        if self._sidebar and self._sidebar.isVisible():
            self._sidebar.set_selected(None)

    def _sync_random_pool(self) -> None:
        """Sync pool paths from pool IDs to the asset tool."""
        paths = []
        for asset in self._asset_catalog.assets:
            if asset.id in self._random_pool_ids and asset.exists():
                paths.append(asset.file_path())
        self._asset_tool.set_random_pool(paths)
        self._pool_label.setText(f"({len(paths)} assets)")

    def _on_random_size_toggled(self, checked: bool) -> None:
        self._asset_tool.random_size = checked
        self._random_size_details.setEnabled(checked)
        self._asset_scale_spin.setEnabled(not checked)

    def _on_rot_btn_clicked(self, degrees: int) -> None:
        self._asset_rot_slider.blockSignals(True)
        self._asset_rot_slider.setValue(degrees)
        self._asset_rot_slider.blockSignals(False)
        self._asset_rot_spin.blockSignals(True)
        self._asset_rot_spin.setValue(degrees)
        self._asset_rot_spin.blockSignals(False)
        self._sync_rot_buttons(degrees)
        self._apply_rotation(degrees)

    def _on_asset_rotation_changed(self, value: int) -> None:
        self._asset_rot_slider.blockSignals(True)
        self._asset_rot_slider.setValue(value)
        self._asset_rot_slider.blockSignals(False)
        self._sync_rot_buttons(value)
        self._apply_rotation(value)

    def _apply_rotation(self, degrees: int) -> None:
        """Apply rotation to placement default or selected asset."""
        self._asset_tool.placement_rotation = float(degrees)
        # If in select mode with a selected asset, apply immediately
        if (self._asset_tool.mode == "select"
                and self._asset_tool._selected_asset is not None):
            from app.commands.asset_commands import TransformAssetCommand
            layer = self._asset_tool._get_active_asset_layer()
            asset = self._asset_tool._selected_asset
            if layer and asset.rotation != float(degrees):
                cmd = TransformAssetCommand(layer, asset, new_rotation=float(degrees))
                self._asset_tool._command_stack.execute(cmd)

    def _uncheck_all_rot_buttons(self) -> None:
        for btn in self._rot_buttons:
            btn.setChecked(False)

    def _sync_rot_buttons(self, value: int) -> None:
        _ALL_PRESETS = (0, 60, 120, 180, 240, 300, 45, 90, 135, 225, 270, 315)
        for i, preset in enumerate(_ALL_PRESETS):
            self._rot_buttons[i].setChecked(preset == value)

    def _on_random_rotation_toggled(self, checked: bool) -> None:
        self._asset_tool.random_rotation = checked
        self._set_rotation_controls_enabled(not checked)

    def _set_rotation_controls_enabled(self, enabled: bool) -> None:
        self._asset_rot_spin.setEnabled(enabled)
        for btn in self._rot_buttons:
            btn.setEnabled(enabled)

    def _refresh_asset_browser(self):
        """Reload catalog and refresh filter combos + grid."""
        self._asset_catalog = load_catalog()
        self._refresh_asset_filter_combos()
        self._rebuild_asset_browser()

    def _refresh_asset_filter_combos(self):
        """Update the game and category filter combos."""
        self._asset_game_combo.blockSignals(True)
        current_game = self._asset_game_combo.currentText()
        self._asset_game_combo.clear()
        self._asset_game_combo.addItem("All")
        for g in self._asset_catalog.games():
            self._asset_game_combo.addItem(g)
        idx = self._asset_game_combo.findText(current_game)
        if idx >= 0:
            self._asset_game_combo.setCurrentIndex(idx)
        self._asset_game_combo.blockSignals(False)

        self._asset_category_combo.blockSignals(True)
        current_cat = self._asset_category_combo.currentText()
        self._asset_category_combo.clear()
        self._asset_category_combo.addItem("All")
        for cat in self._asset_catalog.categories():
            self._asset_category_combo.addItem(cat)
        idx = self._asset_category_combo.findText(current_cat)
        if idx >= 0:
            self._asset_category_combo.setCurrentIndex(idx)
        self._asset_category_combo.blockSignals(False)

    def _filtered_browser_assets(self) -> list[LibraryAsset]:
        """Return assets matching current browser filter."""
        game = self._asset_game_combo.currentText()
        category = self._asset_category_combo.currentText()
        search = self._asset_search_edit.text().strip().lower()

        result = []
        for asset in self._asset_catalog.assets:
            if game != "All" and asset.game != game:
                continue
            if category != "All" and asset.category != category:
                continue
            if search and search not in asset.display_name.lower():
                continue
            result.append(asset)
        return result

    def _rebuild_asset_browser(self):
        """Rebuild thumbnail grid from filtered results."""
        # Clear existing
        for btn in self._asset_browser_buttons.values():
            self._asset_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._asset_browser_buttons.clear()

        filtered = self._filtered_browser_assets()
        cols = 3
        for i, asset in enumerate(filtered):
            btn = self._make_browser_thumb(asset)
            row = i // cols
            col = i % cols
            self._asset_grid_layout.addWidget(btn, row, col)
            self._asset_browser_buttons[asset.id] = btn

        self._update_browser_selection()

    def _make_browser_thumb(self, asset: LibraryAsset) -> QToolButton:
        """Create a 48x48 thumbnail button for the browser."""
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(56, 70)
        game_info = f"  ({asset.game})" if asset.game else ""
        btn.setToolTip(f"{asset.display_name}{game_info}\n{asset.category}")

        pixmap = self._get_browser_thumb(asset)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(48, 48))

        btn.setText(asset.display_name[:8])
        btn.setStyleSheet(
            "QToolButton { padding: 1px; }"
        )
        btn.clicked.connect(lambda checked=False, a=asset: self._on_browser_asset_clicked(a))
        return btn

    def _get_browser_thumb(self, asset: LibraryAsset) -> QPixmap | None:
        """Get or create a cached 48x48 thumbnail."""
        if asset.id in self._asset_thumb_cache:
            return self._asset_thumb_cache[asset.id]

        if not asset.exists():
            return None

        image = QImage(asset.file_path())
        if image.isNull():
            return None

        scaled = image.scaled(
            48, 48,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        self._asset_thumb_cache[asset.id] = pixmap
        return pixmap

    def _on_browser_asset_clicked(self, asset: LibraryAsset):
        """Select an asset from the browser and activate it in the tool."""
        if self._asset_tool.randomize_assets:
            # Multi-select mode: toggle asset in/out of pool
            if asset.id in self._random_pool_ids:
                self._random_pool_ids.discard(asset.id)
            else:
                self._random_pool_ids.add(asset.id)
            self._sync_random_pool()
            self._update_browser_selection()
            # Sync sidebar
            if self._sidebar and self._sidebar.isVisible():
                self._sidebar.set_multi_selected(self._random_pool_ids)
            return

        # Normal single-select mode
        self._selected_browser_asset = asset
        self._update_browser_selection()

        if asset.exists():
            self._asset_tool.set_pending_image(asset.file_path())

        # Sync sidebar selection
        if self._sidebar and self._sidebar.isVisible():
            self._sidebar.set_selected(asset.id)

    def _update_browser_selection(self):
        """Update button borders to show selection."""
        for asset_id, btn in self._asset_browser_buttons.items():
            if self._asset_tool.randomize_assets:
                # Green border for pool members
                if asset_id in self._random_pool_ids:
                    btn.setStyleSheet(
                        "QToolButton { padding: 1px; "
                        "border: 2px solid #00cc44; }"
                    )
                else:
                    btn.setStyleSheet(
                        "QToolButton { padding: 1px; }"
                    )
            else:
                # Blue border for single selection
                if self._selected_browser_asset and asset_id == self._selected_browser_asset.id:
                    btn.setStyleSheet(
                        "QToolButton { padding: 1px; "
                        "border: 2px solid #00aaff; }"
                    )
                else:
                    btn.setStyleSheet(
                        "QToolButton { padding: 1px; }"
                    )

    def _on_asset_filter_changed(self):
        """Rebuild browser when filter changes."""
        self._rebuild_asset_browser()
        self._sync_sidebar()

    def _on_open_asset_manager(self):
        """Open the full Asset Manager dialog."""
        dialog = AssetManagerDialog(self.dock.window())  # L12: center on main window, not dock panel
        dialog.catalog_changed.connect(self._on_asset_manager_changed)
        dialog.exec()

    def _on_asset_manager_changed(self):
        """Refresh browser when the manager changes the catalog."""
        self._asset_thumb_cache.clear()
        if self._sidebar:
            self._sidebar.invalidate_cache()
        self._refresh_asset_browser()

    def refresh_asset_catalog(self) -> None:
        """Reload asset catalog (called when the catalog has actually changed)."""
        if not hasattr(self, "_asset_catalog"):
            return
        self._asset_thumb_cache.clear()
        if self._sidebar:
            self._sidebar.invalidate_cache()
        self._refresh_asset_browser()

    # --- Sidebar management ---

    def _on_toggle_sidebar(self, checked: bool):
        """Toggle the expanded asset browser sidebar."""
        if checked:
            self.dock._save_panel_width()
            if not self._sidebar:
                self._sidebar = AssetBrowserSidebar(self.dock.window())
                self._sidebar.asset_clicked.connect(self._on_sidebar_asset_clicked)
                self._sidebar.closed.connect(self._on_sidebar_closed)
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea, self._sidebar
                )
                main_win.splitDockWidget(
                    self.dock, self._sidebar, Qt.Orientation.Horizontal
                )
            self._sidebar.show()
            self._sync_sidebar()
        else:
            if self._sidebar:
                self._sidebar.hide()
            self.dock._restore_panel_width()

    def _sync_sidebar(self):
        """Update sidebar contents from current filter state."""
        if not self._sidebar or not self._sidebar.isVisible():
            return
        filtered = self._filtered_browser_assets()
        selected_id = (
            self._selected_browser_asset.id
            if self._selected_browser_asset
            else None
        )
        self._sidebar.set_assets(filtered, selected_id)
        # Sync multi-select state for randomize mode
        if self._asset_tool.randomize_assets:
            self._sidebar.set_multi_selected(self._random_pool_ids)

    def close_sidebar(self):
        """Hide the sidebar and reset toggle button."""
        if self._sidebar:
            self._sidebar.hide()
        try:
            if hasattr(self, "_maximize_btn"):
                self._maximize_btn.setChecked(False)
        except RuntimeError:
            pass  # C++ object already deleted

    def _on_sidebar_asset_clicked(self, asset: LibraryAsset):
        """Handle asset selection from the sidebar."""
        # Delegate to main handler (handles both single and randomize modes)
        self._on_browser_asset_clicked(asset)

    def _on_sidebar_closed(self):
        """Handle sidebar close button."""
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_maximize_btn"):
                self._maximize_btn.setChecked(False)
        except RuntimeError:
            pass  # C++ object already deleted

    # --- Eraser helpers ---

    def _sync_erase_size(self, new_size: float) -> None:
        """Sync erase size slider/spin after Ctrl+drag adjustment."""
        value = max(5, min(300, round(new_size)))
        self._erase_size_slider.blockSignals(True)
        self._erase_size_slider.setValue(value)
        self._erase_size_slider.blockSignals(False)
        self._erase_size_spin.blockSignals(True)
        self._erase_size_spin.setValue(value)
        self._erase_size_spin.blockSignals(False)

    def _on_erase_size_slider(self, value: int) -> None:
        if self._asset_tool:
            self._asset_tool.erase_brush_size = float(value)
        self._erase_size_spin.blockSignals(True)
        self._erase_size_spin.setValue(value)
        self._erase_size_spin.blockSignals(False)

    def _on_erase_size_spin(self, value: int) -> None:
        if self._asset_tool:
            self._asset_tool.erase_brush_size = float(value)
        self._erase_size_slider.blockSignals(True)
        self._erase_size_slider.setValue(value)
        self._erase_size_slider.blockSignals(False)

    def _on_clear_mask(self) -> None:
        layer = self._get_asset_layer()
        if layer and self._asset_tool:
            pre = layer.get_mask_snapshot()
            layer.clear_mask()
            post = layer.get_mask_snapshot()
            if pre is not None:
                from app.commands.asset_commands import PaintMaskCommand
                cmd = PaintMaskCommand(layer, pre, post)
                self._asset_tool._command_stack.execute(cmd)

    def sync_shadow_from_layer(self) -> None:
        """Sync shadow widgets from the currently active AssetLayer."""
        layer = self._get_asset_layer()
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

    # --- Shadow helpers ---

    def _get_asset_layer(self):
        """Return the active AssetLayer, or None."""
        from app.layers.asset_layer import AssetLayer
        if not self._asset_tool:
            return None
        layer = self._asset_tool._project.layer_stack.active_layer
        if isinstance(layer, AssetLayer):
            return layer
        return None

    def _apply_asset_layer_effect(self, **changes) -> None:
        """Apply a layer-level effect change via undoable command."""
        from app.commands.asset_commands import EditAssetLayerEffectsCommand
        layer = self._get_asset_layer()
        if not layer or not self._asset_tool:
            return
        cmd = EditAssetLayerEffectsCommand(layer, **changes)
        self._asset_tool._command_stack.execute(cmd)

    def _on_shadow_toggled(self, checked: bool) -> None:
        self._shadow_container.setEnabled(checked)
        self._apply_asset_layer_effect(shadow_enabled=checked)

    def _on_shadow_type(self, text: str) -> None:
        self._apply_asset_layer_effect(
            shadow_type="inner" if text == "Inner" else "outer"
        )

    def _on_shadow_color(self) -> None:
        layer = self._get_asset_layer()
        current = QColor(layer.shadow_color if layer else "#000000")
        color = QColorDialog.getColor(current, self.dock, "Shadow Color")
        if color.isValid():
            update_color_btn(self._shadow_color_btn, color)
            self._apply_asset_layer_effect(shadow_color=color.name())

    def _on_shadow_opacity_slider(self, val: int) -> None:
        o = val / 100.0
        self._shadow_opacity_spin.blockSignals(True)
        self._shadow_opacity_spin.setValue(o)
        self._shadow_opacity_spin.blockSignals(False)
        self._apply_asset_layer_effect(shadow_opacity=o)

    def _on_shadow_opacity_spin(self, val: float) -> None:
        self._shadow_opacity_slider.blockSignals(True)
        self._shadow_opacity_slider.setValue(int(val * 100))
        self._shadow_opacity_slider.blockSignals(False)
        self._apply_asset_layer_effect(shadow_opacity=val)

    def _on_shadow_angle_slider(self, val: int) -> None:
        self._shadow_angle_spin.blockSignals(True)
        self._shadow_angle_spin.setValue(val)
        self._shadow_angle_spin.blockSignals(False)
        self._apply_asset_layer_effect(shadow_angle=float(val))

    def _on_shadow_angle_spin(self, val: int) -> None:
        self._shadow_angle_slider.blockSignals(True)
        self._shadow_angle_slider.setValue(val)
        self._shadow_angle_slider.blockSignals(False)
        self._apply_asset_layer_effect(shadow_angle=float(val))

    def _on_shadow_dist_slider(self, val: int) -> None:
        self._shadow_dist_spin.blockSignals(True)
        self._shadow_dist_spin.setValue(float(val))
        self._shadow_dist_spin.blockSignals(False)
        self._apply_asset_layer_effect(shadow_distance=float(val))

    def _on_shadow_dist_spin(self, val: float) -> None:
        self._shadow_dist_slider.blockSignals(True)
        self._shadow_dist_slider.setValue(int(val))
        self._shadow_dist_slider.blockSignals(False)
        self._apply_asset_layer_effect(shadow_distance=val)

    def _on_shadow_spread_slider(self, val: int) -> None:
        self._shadow_spread_spin.blockSignals(True)
        self._shadow_spread_spin.setValue(val)
        self._shadow_spread_spin.blockSignals(False)
        self._apply_asset_layer_effect(shadow_spread=float(val))

    def _on_shadow_spread_spin(self, val: int) -> None:
        self._shadow_spread_slider.blockSignals(True)
        self._shadow_spread_slider.setValue(val)
        self._shadow_spread_slider.blockSignals(False)
        self._apply_asset_layer_effect(shadow_spread=float(val))

    def _on_shadow_size_slider(self, val: int) -> None:
        self._shadow_size_spin.blockSignals(True)
        self._shadow_size_spin.setValue(float(val))
        self._shadow_size_spin.blockSignals(False)
        self._apply_asset_layer_effect(shadow_size=float(val))

    def _on_shadow_size_spin(self, val: float) -> None:
        self._shadow_size_slider.blockSignals(True)
        self._shadow_size_slider.setValue(int(val))
        self._shadow_size_slider.blockSignals(False)
        self._apply_asset_layer_effect(shadow_size=val)

    # --- Auto-Text helpers ---

    def _on_auto_text_toggled(self, checked: bool) -> None:
        self._auto_text_sub.setEnabled(checked)
        if self._asset_tool:
            self._asset_tool.auto_text_enabled = checked
        if checked:
            self._refresh_auto_text_layer_combo()

    def _refresh_auto_text_layer_combo(self) -> None:
        """Populate layer combo with TextLayers above the active asset layer."""
        if self._asset_tool is None:
            return
        project = self._asset_tool._project
        layers = list(project.layer_stack)
        asset_layer = self._asset_tool._get_active_asset_layer()
        asset_idx = next((i for i, l in enumerate(layers) if l is asset_layer), -1)

        current = self._auto_text_layer_combo.currentData() or ""
        self._auto_text_layer_combo.blockSignals(True)
        self._auto_text_layer_combo.clear()
        self._auto_text_layer_combo.addItem("(Create New)", "")
        for i, layer in enumerate(layers):
            if isinstance(layer, TextLayer) and i > asset_idx:
                self._auto_text_layer_combo.addItem(layer.name, layer.id)  # M14: use UUID as data
        idx = self._auto_text_layer_combo.findData(current)
        if idx >= 0:
            self._auto_text_layer_combo.setCurrentIndex(idx)
        self._auto_text_layer_combo.blockSignals(False)

    def _resolve_auto_text_layer(self) -> TextLayer | None:
        """Return the target TextLayer, creating one above the asset layer if needed."""
        if self._asset_tool is None:
            return None
        project = self._asset_tool._project
        layer_id = self._auto_text_layer_combo.currentData() or ""

        if layer_id:
            for layer in project.layer_stack:
                if isinstance(layer, TextLayer) and layer.id == layer_id:  # M14: match by UUID
                    return layer
            # Layer was deleted — fall through to create a new one

        # Create a new TextLayer directly above the active asset layer
        asset_layer = self._asset_tool._get_active_asset_layer()
        layers = list(project.layer_stack)
        asset_idx = next((i for i, l in enumerate(layers) if l is asset_layer), -1)
        insert_idx = asset_idx + 1 if asset_idx >= 0 else len(layers)

        new_layer = TextLayer("Auto-Text")
        project.layer_stack.add_layer(new_layer, insert_idx)

        # Refresh UI
        self._refresh_auto_text_layer_combo()
        idx = self._auto_text_layer_combo.findData(new_layer.id)  # M14: find by UUID
        if idx >= 0:
            self._auto_text_layer_combo.setCurrentIndex(idx)
        main_window = self.dock.window()
        if hasattr(main_window, "_layer_panel"):
            main_window._layer_panel._refresh_list()

        return new_layer

    def _on_auto_text_place(self, x: float, y: float) -> None:
        """Called by AssetTool after a single asset is placed with Auto-Text active."""
        if self._asset_tool is None:
            return

        # Remember the asset layer by identity so we can restore it after text placement
        # (creating a new TextLayer via add_layer() changes the active layer as a side effect)
        asset_layer = self._asset_tool._get_active_asset_layer()

        parent = self.dock.window()
        text, ok = QInputDialog.getText(parent, "Auto-Text", "Enter label:")
        if not ok or not text.strip():
            return
        text = text.strip()

        text_layer = self._resolve_auto_text_layer()
        if text_layer is None:
            return

        # Load preset (or use defaults)
        preset_name = self._auto_text_preset_combo.currentData() or ""
        preset = None
        if preset_name:
            try:
                preset = load_text_preset(preset_name)
            except Exception:
                preset = None

        y_offset = self._auto_text_y_offset_spin.value()

        obj = TextObject(
            text=text,
            x=x,
            y=y + y_offset,
            font_family=preset.font_family if preset else "Arial",
            font_size=preset.font_size if preset else 12.0,
            bold=preset.bold if preset else False,
            italic=preset.italic if preset else False,
            color=preset.color if preset else "#000000",
            alignment=preset.alignment if preset else "center",
            opacity=preset.opacity if preset else 1.0,
            rotation=preset.rotation if preset else 0.0,
            outline=preset.outline if preset else False,
            outline_color=preset.outline_color if preset else "#ffffff",
            outline_width=preset.outline_width if preset else 1.0,
        )

        cmd = PlaceTextCommand(text_layer, obj)
        self._asset_tool._command_stack.execute(cmd)

        # Restore active layer back to the asset layer so the user stays in asset placement mode
        if asset_layer is not None:
            layer_stack = self._asset_tool._project.layer_stack
            asset_idx = next((i for i, l in enumerate(layer_stack) if l is asset_layer), -1)
            if asset_idx >= 0 and layer_stack.active_index != asset_idx:
                layer_stack.active_index = asset_idx

