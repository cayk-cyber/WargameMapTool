"""Path tool options builder."""

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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.io.palette_manager import (
    ColorPalette,
    ensure_default_palette,
    list_palettes,
    load_palette,
)
from app.io.path_preset_manager import (
    PathPreset,
    delete_path_preset,
    is_builtin_path_preset,
    list_path_presets,
    load_path_preset,
    save_path_preset,
)
from app.io.texture_library import (
    LibraryTexture,
    load_catalog as load_texture_catalog,
)
from app.panels.texture_manager_dialog import TextureManagerDialog
from app.panels.tool_options.helpers import update_color_btn
from app.panels.tool_options.sidebar_widgets import (
    PathPresetSidebar,
    TextureBrowserSidebar,
    render_path_preview,
)
from app.commands.path_commands import EditPathCommand
from app.tools.path_tool import PathTool

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel

# Maximum columns for the color grid
_PALETTE_GRID_COLS = 4

# Line type options
_LINE_TYPES = ["Solid", "Dashed", "Dotted"]
_LINE_TYPE_MAP = {"Solid": "solid", "Dashed": "dashed", "Dotted": "dotted"}
_LINE_TYPE_REVERSE = {"solid": "Solid", "dashed": "Dashed", "dotted": "Dotted"}

# Dash cap options
_CAP_TYPES = ["Flat", "Round", "Square"]
_CAP_MAP = {"Flat": "flat", "Round": "round", "Square": "square"}
_CAP_REVERSE = {"flat": "Flat", "round": "Round", "square": "Square"}


class PathOptions:
    """Builds and manages the path tool options UI."""

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._path_tool: PathTool | None = None
        self._pp_preset_sidebar: PathPresetSidebar | None = None
        self._pt_texture_sidebar: TextureBrowserSidebar | None = None
        self._texture_catalog = load_texture_catalog()
        self._texture_thumb_cache: dict[str, QPixmap] = {}
        self._texture_browser_buttons: dict[str, QToolButton] = {}
        self._selected_browser_texture: LibraryTexture | None = None
        self._pt_bg_texture_sidebar: TextureBrowserSidebar | None = None
        self._selected_bg_browser_texture: LibraryTexture | None = None
        self._bg_texture_browser_buttons: dict[str, QToolButton] = {}
        self._pt_bg_palette_color_buttons: list[QPushButton] = []
        self._pt_bg_selected_palette_idx: int = -1

    def create(self, tool: PathTool) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        self._path_tool = tool
        # Reset stale widget references from previous create() call (after invalidate_cache)
        self._texture_browser_buttons = {}
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

        self._pt_mode_group = QButtonGroup(widget)
        self._pt_mode_group.setExclusive(True)
        self._pt_mode_group.addButton(place_btn, 0)
        self._pt_mode_group.addButton(select_btn, 1)
        self._pt_mode_group.idToggled.connect(self._on_mode_changed)

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
        self._pp_preview = QLabel()
        self._pp_preview.setFixedHeight(40)
        self._pp_preview.setScaledContents(False)
        from PySide6.QtWidgets import QSizePolicy
        self._pp_preview.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed,
        )
        self._pp_preview.setStyleSheet(
            "background-color: #d0d0d0; border: 1px solid #999; padding: 2px;"
        )
        self._pp_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preset_gl.addWidget(self._pp_preview)

        # Combo
        combo_layout = QHBoxLayout()
        self._pp_combo = QComboBox()
        self._pp_combo.setMinimumWidth(60)
        self._pp_combo.currentTextChanged.connect(self._pp_on_selected)
        combo_layout.addWidget(self._pp_combo, stretch=1)
        preset_gl.addLayout(combo_layout)

        # Expand button
        self._pp_expand_btn = QPushButton("Expand")
        self._pp_expand_btn.setCheckable(True)
        self._pp_expand_btn.setToolTip("Show all presets in expanded sidebar")
        self._pp_expand_btn.clicked.connect(self._pp_on_toggle_sidebar)
        preset_gl.addWidget(self._pp_expand_btn)

        # Buttons
        btn_layout = QHBoxLayout()
        load_btn = QPushButton("Load")
        load_btn.setToolTip("Apply selected preset to current settings")
        load_btn.clicked.connect(self._pp_on_load)
        btn_layout.addWidget(load_btn)

        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save current settings as a new preset")
        save_btn.clicked.connect(self._pp_on_save)
        btn_layout.addWidget(save_btn)

        del_btn = QPushButton("Del")
        del_btn.setToolTip("Delete selected preset")
        del_btn.clicked.connect(self._pp_on_delete)
        btn_layout.addWidget(del_btn)
        preset_gl.addLayout(btn_layout)

        layout.addWidget(preset_group)

        # Populate preset combo
        self._pp_refresh_combo()
        self._pp_update_preview()

        # ===== Main Path section =====
        main_group = QGroupBox("Main Path")
        main_gl = QVBoxLayout(main_group)
        main_gl.setContentsMargins(6, 4, 6, 4)

        # ===== Paint mode selector =====
        paint_mode_group = QGroupBox("Paint Mode")
        pm_gl = QVBoxLayout(paint_mode_group)
        pm_gl.setContentsMargins(6, 4, 6, 4)
        pm_btn_layout = QHBoxLayout()

        is_texture = bool(tool.texture_id)
        pm_color_btn = QPushButton("Color")
        pm_color_btn.setCheckable(True)
        pm_color_btn.setChecked(not is_texture)
        pm_texture_btn = QPushButton("Texture")
        pm_texture_btn.setCheckable(True)
        pm_texture_btn.setChecked(is_texture)

        self._pt_paint_mode_group = QButtonGroup(widget)
        self._pt_paint_mode_group.setExclusive(True)
        self._pt_paint_mode_group.addButton(pm_color_btn, 0)
        self._pt_paint_mode_group.addButton(pm_texture_btn, 1)
        self._pt_paint_mode_group.idToggled.connect(self._on_paint_mode_changed)

        pm_btn_layout.addWidget(pm_color_btn)
        pm_btn_layout.addWidget(pm_texture_btn)
        pm_btn_layout.addStretch()
        pm_gl.addLayout(pm_btn_layout)
        main_gl.addWidget(paint_mode_group)

        # ===== Color group (with palette) =====
        self._pt_selected_palette_idx = -1
        self._pt_current_palette: ColorPalette | None = None
        self._pt_palette_color_buttons: list[QPushButton] = []

        self._pt_color_group = QGroupBox("Color")
        color_gl = QVBoxLayout(self._pt_color_group)
        color_gl.setContentsMargins(6, 4, 6, 4)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._pt_color_btn = QPushButton()
        self._pt_color_btn.setFixedSize(40, 25)
        update_color_btn(self._pt_color_btn, QColor(tool.color))
        self._pt_color_btn.clicked.connect(self._on_color_pick)
        color_row.addWidget(self._pt_color_btn)
        color_row.addStretch()
        color_gl.addLayout(color_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        color_gl.addWidget(separator)

        self._pt_palette_combo = QComboBox()
        color_gl.addWidget(self._pt_palette_combo)

        self._pt_color_grid_widget = QWidget()
        self._pt_color_grid_layout = QGridLayout(self._pt_color_grid_widget)
        self._pt_color_grid_layout.setSpacing(3)
        self._pt_color_grid_layout.setContentsMargins(0, 0, 0, 0)
        color_gl.addWidget(self._pt_color_grid_widget)

        main_gl.addWidget(self._pt_color_group)

        # ===== Texture group =====
        self._pt_texture_group = QGroupBox("Texture")
        tex_gl = QVBoxLayout(self._pt_texture_group)
        tex_gl.setContentsMargins(6, 4, 6, 4)

        # Game filter
        tex_game_row = QHBoxLayout()
        tex_game_row.addWidget(QLabel("Game:"))
        self._pt_tex_game_combo = QComboBox()
        self._pt_tex_game_combo.setMinimumWidth(80)
        self._pt_tex_game_combo.currentTextChanged.connect(self._on_tex_filter_changed)
        tex_game_row.addWidget(self._pt_tex_game_combo, stretch=1)
        tex_gl.addLayout(tex_game_row)

        # Category filter
        tex_cat_row = QHBoxLayout()
        tex_cat_row.addWidget(QLabel("Category:"))
        self._pt_tex_category_combo = QComboBox()
        self._pt_tex_category_combo.setMinimumWidth(80)
        self._pt_tex_category_combo.currentTextChanged.connect(
            self._on_tex_filter_changed
        )
        tex_cat_row.addWidget(self._pt_tex_category_combo, stretch=1)
        tex_gl.addLayout(tex_cat_row)

        # Search
        tex_search_row = QHBoxLayout()
        tex_search_row.addWidget(QLabel("Search:"))
        self._pt_tex_search_edit = QLineEdit()
        self._pt_tex_search_edit.setPlaceholderText("Filter by name...")
        self._pt_tex_search_edit.textChanged.connect(self._on_tex_filter_changed)
        tex_search_row.addWidget(self._pt_tex_search_edit, stretch=1)
        tex_gl.addLayout(tex_search_row)

        # Thumbnail grid
        self._pt_tex_scroll = QScrollArea()
        self._pt_tex_scroll.setWidgetResizable(True)
        self._pt_tex_scroll.setMinimumHeight(80)
        self._pt_tex_scroll.setMaximumHeight(200)
        self._pt_tex_grid_container = QWidget()
        self._pt_tex_grid_layout = QGridLayout(self._pt_tex_grid_container)
        self._pt_tex_grid_layout.setSpacing(4)
        self._pt_tex_grid_layout.setContentsMargins(2, 2, 2, 2)
        self._pt_tex_scroll.setWidget(self._pt_tex_grid_container)
        tex_gl.addWidget(self._pt_tex_scroll)

        # Manager + Expand buttons
        tex_btn_row = QHBoxLayout()
        tex_mgr_btn = QPushButton("Manager...")
        tex_mgr_btn.clicked.connect(self._on_open_texture_manager)
        tex_btn_row.addWidget(tex_mgr_btn)
        self._pt_tex_expand_btn = QPushButton("Expand")
        self._pt_tex_expand_btn.setCheckable(True)
        self._pt_tex_expand_btn.clicked.connect(self._on_toggle_texture_sidebar)
        tex_btn_row.addWidget(self._pt_tex_expand_btn)
        tex_gl.addLayout(tex_btn_row)

        # Separator before transform controls
        tex_sep = QFrame()
        tex_sep.setFrameShape(QFrame.Shape.HLine)
        tex_sep.setFrameShadow(QFrame.Shadow.Sunken)
        tex_gl.addWidget(tex_sep)

        # Zoom
        tex_gl.addWidget(QLabel("Zoom:"))
        tex_zoom_row = QHBoxLayout()
        self._pt_tex_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_tex_zoom_slider.setRange(1, 100)  # 0.1-10.0
        self._pt_tex_zoom_slider.setValue(int(tool.texture_zoom * 10))
        self._pt_tex_zoom_slider.valueChanged.connect(self._on_pt_tex_zoom_slider)
        tex_zoom_row.addWidget(self._pt_tex_zoom_slider, stretch=1)
        self._pt_tex_zoom_spin = QDoubleSpinBox()
        self._pt_tex_zoom_spin.setRange(0.1, 10.0)
        self._pt_tex_zoom_spin.setSingleStep(0.1)
        self._pt_tex_zoom_spin.setDecimals(2)
        self._pt_tex_zoom_spin.setSuffix("x")
        self._pt_tex_zoom_spin.setValue(tool.texture_zoom)
        self._pt_tex_zoom_spin.setFixedWidth(70)
        self._pt_tex_zoom_spin.valueChanged.connect(self._on_pt_tex_zoom_spin)
        tex_zoom_row.addWidget(self._pt_tex_zoom_spin)
        tex_gl.addLayout(tex_zoom_row)

        # Rotation
        tex_gl.addWidget(QLabel("Rotation:"))
        tex_rot_row = QHBoxLayout()
        self._pt_tex_rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_tex_rotation_slider.setRange(0, 359)
        self._pt_tex_rotation_slider.setValue(int(tool.texture_rotation))
        self._pt_tex_rotation_slider.valueChanged.connect(self._on_pt_tex_rot_slider)
        tex_rot_row.addWidget(self._pt_tex_rotation_slider, stretch=1)
        self._pt_tex_rotation_spin = QSpinBox()
        self._pt_tex_rotation_spin.setRange(0, 359)
        self._pt_tex_rotation_spin.setSuffix("\u00b0")
        self._pt_tex_rotation_spin.setWrapping(True)
        self._pt_tex_rotation_spin.setValue(int(tool.texture_rotation))
        self._pt_tex_rotation_spin.setFixedWidth(60)
        self._pt_tex_rotation_spin.valueChanged.connect(self._on_pt_tex_rot_spin)
        tex_rot_row.addWidget(self._pt_tex_rotation_spin)
        tex_gl.addLayout(tex_rot_row)

        # Rotation preset buttons
        self._pt_tex_rot_buttons: list[QPushButton] = []
        tex_rot_btn_row = QHBoxLayout()
        tex_rot_btn_row.setSpacing(2)
        for deg in (0, 60, 90, 120, 180, 270):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(32)
            btn.setChecked(deg == int(tool.texture_rotation))
            btn.clicked.connect(lambda _, d=deg: self._on_tex_rot_preset(d))
            tex_rot_btn_row.addWidget(btn)
            self._pt_tex_rot_buttons.append(btn)
        tex_rot_btn_row.addStretch()
        tex_gl.addLayout(tex_rot_btn_row)

        self._pt_texture_group.setVisible(is_texture)
        self._pt_color_group.setVisible(not is_texture)
        main_gl.addWidget(self._pt_texture_group)

        # Width
        main_gl.addWidget(QLabel("Width:"))
        width_row = QHBoxLayout()
        self._pt_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_width_slider.setRange(1, 200)  # 0.5-100.0 in 0.5 steps
        self._pt_width_slider.setValue(int(tool.width * 2))
        self._pt_width_slider.valueChanged.connect(self._on_pt_width_slider)
        width_row.addWidget(self._pt_width_slider, stretch=1)
        self._pt_width_spin = QDoubleSpinBox()
        self._pt_width_spin.setRange(0.5, 100.0)
        self._pt_width_spin.setSingleStep(0.5)
        self._pt_width_spin.setValue(tool.width)
        self._pt_width_spin.setFixedWidth(65)
        self._pt_width_spin.valueChanged.connect(self._on_pt_width_spin)
        width_row.addWidget(self._pt_width_spin)
        main_gl.addLayout(width_row)

        # Opacity
        main_gl.addWidget(QLabel("Opacity:"))
        opacity_row = QHBoxLayout()
        self._pt_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_opacity_slider.setRange(0, 100)
        self._pt_opacity_slider.setValue(round(tool.opacity * 100))
        self._pt_opacity_slider.valueChanged.connect(self._on_opacity_slider)
        opacity_row.addWidget(self._pt_opacity_slider, stretch=1)
        self._pt_opacity_spin = QSpinBox()
        self._pt_opacity_spin.setRange(0, 100)
        self._pt_opacity_spin.setSuffix("%")
        self._pt_opacity_spin.setValue(round(tool.opacity * 100))
        self._pt_opacity_spin.setFixedWidth(60)
        self._pt_opacity_spin.valueChanged.connect(self._on_opacity_spin)
        opacity_row.addWidget(self._pt_opacity_spin)
        main_gl.addLayout(opacity_row)

        # Type
        lt_row = QHBoxLayout()
        lt_row.addWidget(QLabel("Type:"))
        self._pt_line_type_combo = QComboBox()
        self._pt_line_type_combo.addItems(_LINE_TYPES)
        self._pt_line_type_combo.setCurrentText(
            _LINE_TYPE_REVERSE.get(tool.line_type, "Solid")
        )
        self._pt_line_type_combo.currentTextChanged.connect(self._on_line_type_changed)
        lt_row.addWidget(self._pt_line_type_combo)
        lt_row.addStretch()
        main_gl.addLayout(lt_row)

        # Dash length / gap / cap controls
        self._pt_dash_container = QWidget()
        dash_c_layout = QVBoxLayout(self._pt_dash_container)
        dash_c_layout.setContentsMargins(0, 0, 0, 0)

        dash_c_layout.addWidget(QLabel("Dash:"))
        dash_row = QHBoxLayout()
        self._pt_dash_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_dash_slider.setRange(1, 300)  # 0.1-30.0 in 0.1 steps
        self._pt_dash_slider.setValue(max(1, round(tool.dash_length * 10)))
        self._pt_dash_slider.valueChanged.connect(self._on_pt_dash_slider)
        dash_row.addWidget(self._pt_dash_slider, stretch=1)
        self._pt_dash_spin = QDoubleSpinBox()
        self._pt_dash_spin.setRange(0.1, 30.0)
        self._pt_dash_spin.setSingleStep(0.1)
        self._pt_dash_spin.setDecimals(1)
        self._pt_dash_spin.setValue(tool.dash_length)
        self._pt_dash_spin.setFixedWidth(60)
        self._pt_dash_spin.valueChanged.connect(self._on_pt_dash_spin)
        dash_row.addWidget(self._pt_dash_spin)
        dash_c_layout.addLayout(dash_row)

        dash_c_layout.addWidget(QLabel("Gap:"))
        gap_row = QHBoxLayout()
        self._pt_gap_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_gap_slider.setRange(1, 300)  # 0.1-30.0 in 0.1 steps
        self._pt_gap_slider.setValue(max(1, round(tool.gap_length * 10)))
        self._pt_gap_slider.valueChanged.connect(self._on_pt_gap_slider)
        gap_row.addWidget(self._pt_gap_slider, stretch=1)
        self._pt_gap_spin = QDoubleSpinBox()
        self._pt_gap_spin.setRange(0.1, 30.0)
        self._pt_gap_spin.setSingleStep(0.1)
        self._pt_gap_spin.setDecimals(1)
        self._pt_gap_spin.setValue(tool.gap_length)
        self._pt_gap_spin.setFixedWidth(60)
        self._pt_gap_spin.valueChanged.connect(self._on_pt_gap_spin)
        gap_row.addWidget(self._pt_gap_spin)
        dash_c_layout.addLayout(gap_row)

        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("Cap:"))
        self._pt_cap_combo = QComboBox()
        self._pt_cap_combo.addItems(_CAP_TYPES)
        self._pt_cap_combo.setCurrentText(
            _CAP_REVERSE.get(tool.dash_cap, "Flat")
        )
        self._pt_cap_combo.currentTextChanged.connect(self._on_cap_changed)
        cap_row.addWidget(self._pt_cap_combo)
        cap_row.addStretch()
        dash_c_layout.addLayout(cap_row)

        self._pt_dash_container.setEnabled(tool.line_type != "solid")
        main_gl.addWidget(self._pt_dash_container)
        layout.addWidget(main_group)

        # ===== Background Path group =====
        bg_group = QGroupBox("Background Path")
        bg_gl = QVBoxLayout(bg_group)
        bg_gl.setContentsMargins(6, 4, 6, 4)

        self._pt_bg_cb = QCheckBox("Enable Background Path")
        self._pt_bg_cb.setChecked(tool.bg_enabled)
        self._pt_bg_cb.toggled.connect(self._on_bg_toggled)
        bg_gl.addWidget(self._pt_bg_cb)

        self._pt_bg_container = QWidget()
        bg_c_layout = QVBoxLayout(self._pt_bg_container)
        bg_c_layout.setContentsMargins(0, 0, 0, 0)

        # BG Paint Mode toggle (Color | Texture)
        is_bg_texture = bool(tool.bg_texture_id)
        bg_pm_group = QGroupBox("Paint Mode")
        bg_pm_gl = QVBoxLayout(bg_pm_group)
        bg_pm_gl.setContentsMargins(6, 4, 6, 4)
        bg_pm_btn_layout = QHBoxLayout()
        bg_pm_color_btn = QPushButton("Color")
        bg_pm_color_btn.setCheckable(True)
        bg_pm_color_btn.setChecked(not is_bg_texture)
        bg_pm_texture_btn = QPushButton("Texture")
        bg_pm_texture_btn.setCheckable(True)
        bg_pm_texture_btn.setChecked(is_bg_texture)
        self._pt_bg_paint_mode_group = QButtonGroup(widget)
        self._pt_bg_paint_mode_group.setExclusive(True)
        self._pt_bg_paint_mode_group.addButton(bg_pm_color_btn, 0)
        self._pt_bg_paint_mode_group.addButton(bg_pm_texture_btn, 1)
        self._pt_bg_paint_mode_group.idToggled.connect(self._on_bg_paint_mode_changed)
        bg_pm_btn_layout.addWidget(bg_pm_color_btn)
        bg_pm_btn_layout.addWidget(bg_pm_texture_btn)
        bg_pm_btn_layout.addStretch()
        bg_pm_gl.addLayout(bg_pm_btn_layout)
        bg_c_layout.addWidget(bg_pm_group)

        # BG Color section
        self._pt_bg_color_section = QGroupBox("Color")
        bg_color_sec_layout = QVBoxLayout(self._pt_bg_color_section)
        bg_color_sec_layout.setContentsMargins(6, 4, 6, 4)

        bg_color_row = QHBoxLayout()
        bg_color_row.addWidget(QLabel("Color:"))
        self._pt_bg_color_btn = QPushButton()
        self._pt_bg_color_btn.setFixedSize(40, 25)
        update_color_btn(self._pt_bg_color_btn, QColor(tool.bg_color))
        self._pt_bg_color_btn.clicked.connect(self._on_bg_color_pick)
        bg_color_row.addWidget(self._pt_bg_color_btn)
        bg_color_row.addStretch()
        bg_color_sec_layout.addLayout(bg_color_row)

        bg_pal_sep = QFrame()
        bg_pal_sep.setFrameShape(QFrame.Shape.HLine)
        bg_pal_sep.setFrameShadow(QFrame.Shadow.Sunken)
        bg_color_sec_layout.addWidget(bg_pal_sep)

        self._pt_bg_color_grid_widget = QWidget()
        self._pt_bg_color_grid_layout = QGridLayout(self._pt_bg_color_grid_widget)
        self._pt_bg_color_grid_layout.setSpacing(3)
        self._pt_bg_color_grid_layout.setContentsMargins(0, 0, 0, 0)
        bg_color_sec_layout.addWidget(self._pt_bg_color_grid_widget)

        bg_c_layout.addWidget(self._pt_bg_color_section)
        self._pt_bg_color_section.setVisible(not is_bg_texture)

        # BG Texture section
        self._pt_bg_texture_section = QGroupBox("Texture")
        bg_tex_sec_layout = QVBoxLayout(self._pt_bg_texture_section)
        bg_tex_sec_layout.setContentsMargins(6, 4, 6, 4)

        bg_tex_game_row = QHBoxLayout()
        bg_tex_game_row.addWidget(QLabel("Game:"))
        self._pt_bg_tex_game_combo = QComboBox()
        self._pt_bg_tex_game_combo.setMinimumWidth(80)
        self._pt_bg_tex_game_combo.currentTextChanged.connect(self._on_bg_tex_filter_changed)
        bg_tex_game_row.addWidget(self._pt_bg_tex_game_combo, stretch=1)
        bg_tex_sec_layout.addLayout(bg_tex_game_row)

        bg_tex_cat_row = QHBoxLayout()
        bg_tex_cat_row.addWidget(QLabel("Category:"))
        self._pt_bg_tex_category_combo = QComboBox()
        self._pt_bg_tex_category_combo.setMinimumWidth(80)
        self._pt_bg_tex_category_combo.currentTextChanged.connect(self._on_bg_tex_filter_changed)
        bg_tex_cat_row.addWidget(self._pt_bg_tex_category_combo, stretch=1)
        bg_tex_sec_layout.addLayout(bg_tex_cat_row)

        bg_tex_search_row = QHBoxLayout()
        bg_tex_search_row.addWidget(QLabel("Search:"))
        self._pt_bg_tex_search_edit = QLineEdit()
        self._pt_bg_tex_search_edit.setPlaceholderText("Filter by name...")
        self._pt_bg_tex_search_edit.textChanged.connect(self._on_bg_tex_filter_changed)
        bg_tex_search_row.addWidget(self._pt_bg_tex_search_edit, stretch=1)
        bg_tex_sec_layout.addLayout(bg_tex_search_row)

        self._pt_bg_tex_scroll = QScrollArea()
        self._pt_bg_tex_scroll.setWidgetResizable(True)
        self._pt_bg_tex_scroll.setMinimumHeight(80)
        self._pt_bg_tex_scroll.setMaximumHeight(200)
        bg_tex_grid_container = QWidget()
        self._pt_bg_tex_grid_layout = QGridLayout(bg_tex_grid_container)
        self._pt_bg_tex_grid_layout.setSpacing(4)
        self._pt_bg_tex_grid_layout.setContentsMargins(2, 2, 2, 2)
        self._pt_bg_tex_scroll.setWidget(bg_tex_grid_container)
        bg_tex_sec_layout.addWidget(self._pt_bg_tex_scroll)

        bg_tex_btn_row = QHBoxLayout()
        bg_tex_mgr_btn = QPushButton("Manager...")
        bg_tex_mgr_btn.clicked.connect(self._on_open_texture_manager)
        bg_tex_btn_row.addWidget(bg_tex_mgr_btn)
        self._pt_bg_tex_expand_btn = QPushButton("Expand")
        self._pt_bg_tex_expand_btn.setCheckable(True)
        self._pt_bg_tex_expand_btn.clicked.connect(self._on_toggle_bg_texture_sidebar)
        bg_tex_btn_row.addWidget(self._pt_bg_tex_expand_btn)
        bg_tex_sec_layout.addLayout(bg_tex_btn_row)

        bg_tex_sep = QFrame()
        bg_tex_sep.setFrameShape(QFrame.Shape.HLine)
        bg_tex_sep.setFrameShadow(QFrame.Shadow.Sunken)
        bg_tex_sec_layout.addWidget(bg_tex_sep)

        bg_tex_sec_layout.addWidget(QLabel("Zoom:"))
        bg_tex_zoom_row = QHBoxLayout()
        self._pt_bg_tex_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_bg_tex_zoom_slider.setRange(1, 100)
        self._pt_bg_tex_zoom_slider.setValue(int(tool.bg_texture_zoom * 10))
        self._pt_bg_tex_zoom_slider.valueChanged.connect(self._on_pt_bg_tex_zoom_slider)
        bg_tex_zoom_row.addWidget(self._pt_bg_tex_zoom_slider, stretch=1)
        self._pt_bg_tex_zoom_spin = QDoubleSpinBox()
        self._pt_bg_tex_zoom_spin.setRange(0.1, 10.0)
        self._pt_bg_tex_zoom_spin.setSingleStep(0.1)
        self._pt_bg_tex_zoom_spin.setDecimals(2)
        self._pt_bg_tex_zoom_spin.setSuffix("x")
        self._pt_bg_tex_zoom_spin.setValue(tool.bg_texture_zoom)
        self._pt_bg_tex_zoom_spin.setFixedWidth(70)
        self._pt_bg_tex_zoom_spin.valueChanged.connect(self._on_pt_bg_tex_zoom_spin)
        bg_tex_zoom_row.addWidget(self._pt_bg_tex_zoom_spin)
        bg_tex_sec_layout.addLayout(bg_tex_zoom_row)

        bg_tex_sec_layout.addWidget(QLabel("Rotation:"))
        bg_tex_rot_row = QHBoxLayout()
        self._pt_bg_tex_rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_bg_tex_rotation_slider.setRange(0, 359)
        self._pt_bg_tex_rotation_slider.setValue(int(tool.bg_texture_rotation))
        self._pt_bg_tex_rotation_slider.valueChanged.connect(self._on_pt_bg_tex_rot_slider)
        bg_tex_rot_row.addWidget(self._pt_bg_tex_rotation_slider, stretch=1)
        self._pt_bg_tex_rotation_spin = QSpinBox()
        self._pt_bg_tex_rotation_spin.setRange(0, 359)
        self._pt_bg_tex_rotation_spin.setSuffix("\u00b0")
        self._pt_bg_tex_rotation_spin.setWrapping(True)
        self._pt_bg_tex_rotation_spin.setValue(int(tool.bg_texture_rotation))
        self._pt_bg_tex_rotation_spin.setFixedWidth(60)
        self._pt_bg_tex_rotation_spin.valueChanged.connect(self._on_pt_bg_tex_rot_spin)
        bg_tex_rot_row.addWidget(self._pt_bg_tex_rotation_spin)
        bg_tex_sec_layout.addLayout(bg_tex_rot_row)

        self._pt_bg_tex_rot_buttons: list[QPushButton] = []
        bg_tex_rot_btn_row = QHBoxLayout()
        bg_tex_rot_btn_row.setSpacing(2)
        for deg in (0, 60, 90, 120, 180, 270):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(32)
            btn.setChecked(deg == int(tool.bg_texture_rotation))
            btn.clicked.connect(lambda _, d=deg: self._on_bg_tex_rot_preset(d))
            bg_tex_rot_btn_row.addWidget(btn)
            self._pt_bg_tex_rot_buttons.append(btn)
        bg_tex_rot_btn_row.addStretch()
        bg_tex_sec_layout.addLayout(bg_tex_rot_btn_row)

        bg_c_layout.addWidget(self._pt_bg_texture_section)
        self._pt_bg_texture_section.setVisible(is_bg_texture)

        # BG Width
        bg_c_layout.addWidget(QLabel("Width:"))
        self._pt_bg_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_bg_width_slider.setRange(1, 200)  # 0.5-100.0 in 0.5 steps
        self._pt_bg_width_slider.setValue(int(tool.bg_width * 2))
        self._pt_bg_width_slider.valueChanged.connect(self._on_pt_bg_width_slider)
        bg_w_row = QHBoxLayout()
        bg_w_row.addWidget(self._pt_bg_width_slider, stretch=1)
        self._pt_bg_width_spin = QDoubleSpinBox()
        self._pt_bg_width_spin.setRange(0.5, 100.0)
        self._pt_bg_width_spin.setSingleStep(0.5)
        self._pt_bg_width_spin.setValue(tool.bg_width)
        self._pt_bg_width_spin.setFixedWidth(65)
        self._pt_bg_width_spin.valueChanged.connect(self._on_pt_bg_width_spin)
        bg_w_row.addWidget(self._pt_bg_width_spin)
        bg_c_layout.addLayout(bg_w_row)

        # BG Line Type
        bg_lt_row = QHBoxLayout()
        bg_lt_row.addWidget(QLabel("Type:"))
        self._pt_bg_line_type_combo = QComboBox()
        self._pt_bg_line_type_combo.addItems(_LINE_TYPES)
        self._pt_bg_line_type_combo.setCurrentText(
            _LINE_TYPE_REVERSE.get(tool.bg_line_type, "Solid")
        )
        self._pt_bg_line_type_combo.currentTextChanged.connect(
            self._on_bg_line_type_changed
        )
        bg_lt_row.addWidget(self._pt_bg_line_type_combo)
        bg_lt_row.addStretch()
        bg_c_layout.addLayout(bg_lt_row)

        # BG Dash/Gap
        self._pt_bg_dash_container = QWidget()
        bg_dash_c_layout = QVBoxLayout(self._pt_bg_dash_container)
        bg_dash_c_layout.setContentsMargins(0, 0, 0, 0)

        bg_dash_c_layout.addWidget(QLabel("Dash:"))
        bg_dash_row = QHBoxLayout()
        self._pt_bg_dash_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_bg_dash_slider.setRange(1, 300)  # 0.1-30.0 in 0.1 steps
        self._pt_bg_dash_slider.setValue(max(1, round(tool.bg_dash_length * 10)))
        self._pt_bg_dash_slider.valueChanged.connect(self._on_pt_bg_dash_slider)
        bg_dash_row.addWidget(self._pt_bg_dash_slider, stretch=1)
        self._pt_bg_dash_spin = QDoubleSpinBox()
        self._pt_bg_dash_spin.setRange(0.1, 30.0)
        self._pt_bg_dash_spin.setSingleStep(0.1)
        self._pt_bg_dash_spin.setDecimals(1)
        self._pt_bg_dash_spin.setValue(tool.bg_dash_length)
        self._pt_bg_dash_spin.setFixedWidth(60)
        self._pt_bg_dash_spin.valueChanged.connect(self._on_pt_bg_dash_spin)
        bg_dash_row.addWidget(self._pt_bg_dash_spin)
        bg_dash_c_layout.addLayout(bg_dash_row)

        bg_dash_c_layout.addWidget(QLabel("Gap:"))
        bg_gap_row = QHBoxLayout()
        self._pt_bg_gap_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_bg_gap_slider.setRange(1, 300)  # 0.1-30.0 in 0.1 steps
        self._pt_bg_gap_slider.setValue(max(1, round(tool.bg_gap_length * 10)))
        self._pt_bg_gap_slider.valueChanged.connect(self._on_pt_bg_gap_slider)
        bg_gap_row.addWidget(self._pt_bg_gap_slider, stretch=1)
        self._pt_bg_gap_spin = QDoubleSpinBox()
        self._pt_bg_gap_spin.setRange(0.1, 30.0)
        self._pt_bg_gap_spin.setSingleStep(0.1)
        self._pt_bg_gap_spin.setDecimals(1)
        self._pt_bg_gap_spin.setValue(tool.bg_gap_length)
        self._pt_bg_gap_spin.setFixedWidth(60)
        self._pt_bg_gap_spin.valueChanged.connect(self._on_pt_bg_gap_spin)
        bg_gap_row.addWidget(self._pt_bg_gap_spin)
        bg_dash_c_layout.addLayout(bg_gap_row)

        bg_cap_row = QHBoxLayout()
        bg_cap_row.addWidget(QLabel("Cap:"))
        self._pt_bg_cap_combo = QComboBox()
        self._pt_bg_cap_combo.addItems(_CAP_TYPES)
        self._pt_bg_cap_combo.setCurrentText(_CAP_REVERSE.get(tool.bg_dash_cap, "Flat"))
        self._pt_bg_cap_combo.currentTextChanged.connect(self._on_bg_cap_changed)
        bg_cap_row.addWidget(self._pt_bg_cap_combo)
        bg_cap_row.addStretch()
        bg_dash_c_layout.addLayout(bg_cap_row)

        self._pt_bg_dash_container.setEnabled(tool.bg_line_type != "solid")
        bg_c_layout.addWidget(self._pt_bg_dash_container)

        # BG Opacity
        bg_c_layout.addWidget(QLabel("Opacity:"))
        bg_opacity_row = QHBoxLayout()
        self._pt_bg_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_bg_opacity_slider.setRange(0, 100)
        self._pt_bg_opacity_slider.setValue(round(tool.bg_opacity * 100))
        self._pt_bg_opacity_slider.valueChanged.connect(self._on_pt_bg_opacity_slider)
        bg_opacity_row.addWidget(self._pt_bg_opacity_slider, stretch=1)
        self._pt_bg_opacity_spin = QSpinBox()
        self._pt_bg_opacity_spin.setRange(0, 100)
        self._pt_bg_opacity_spin.setSuffix("%")
        self._pt_bg_opacity_spin.setValue(round(tool.bg_opacity * 100))
        self._pt_bg_opacity_spin.setFixedWidth(60)
        self._pt_bg_opacity_spin.valueChanged.connect(self._on_pt_bg_opacity_spin)
        bg_opacity_row.addWidget(self._pt_bg_opacity_spin)
        bg_c_layout.addLayout(bg_opacity_row)

        self._pt_bg_container.setEnabled(tool.bg_enabled)
        bg_gl.addWidget(self._pt_bg_container)

        layout.addWidget(bg_group)

        # ===== Random group =====
        random_group = QGroupBox("Random")
        random_gl = QVBoxLayout(random_group)
        random_gl.setContentsMargins(6, 4, 6, 4)

        self._pt_random_cb = QCheckBox("Enable Random")
        self._pt_random_cb.setChecked(tool.random)
        self._pt_random_cb.toggled.connect(self._on_random_toggled)
        random_gl.addWidget(self._pt_random_cb)

        self._pt_random_container = QWidget()
        random_c_layout = QVBoxLayout(self._pt_random_container)
        random_c_layout.setContentsMargins(0, 0, 0, 0)

        # Amplitude: slider + spin inline (0.0 - 50.0, step 0.5)
        random_c_layout.addWidget(QLabel("Amplitude:"))
        amp_row = QHBoxLayout()
        self._pt_amp_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_amp_slider.setRange(0, 100)  # 0.0 - 50.0 in 0.5 steps
        self._pt_amp_slider.setValue(round(tool.random_amplitude / 0.5))
        self._pt_amp_slider.valueChanged.connect(self._on_amp_slider)
        amp_row.addWidget(self._pt_amp_slider, stretch=1)
        self._pt_amp_spin = QDoubleSpinBox()
        self._pt_amp_spin.setRange(0.0, 50.0)
        self._pt_amp_spin.setSingleStep(0.5)
        self._pt_amp_spin.setValue(tool.random_amplitude)
        self._pt_amp_spin.setFixedWidth(65)
        self._pt_amp_spin.valueChanged.connect(self._on_amp_spin)
        amp_row.addWidget(self._pt_amp_spin)
        random_c_layout.addLayout(amp_row)

        # Offset: slider + spin inline (-100.0 - 100.0, step 0.5)
        random_c_layout.addWidget(QLabel("Offset:"))
        offset_row = QHBoxLayout()
        self._pt_offset_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_offset_slider.setRange(0, 200)  # 0.0 - 100.0 in 0.5 steps
        self._pt_offset_slider.setValue(round(tool.random_offset / 0.5))
        self._pt_offset_slider.valueChanged.connect(self._on_offset_slider)
        offset_row.addWidget(self._pt_offset_slider, stretch=1)
        self._pt_offset_spin = QDoubleSpinBox()
        self._pt_offset_spin.setRange(0.0, 100.0)
        self._pt_offset_spin.setSingleStep(0.5)
        self._pt_offset_spin.setValue(tool.random_offset)
        self._pt_offset_spin.setFixedWidth(65)
        self._pt_offset_spin.valueChanged.connect(self._on_offset_spin)
        offset_row.addWidget(self._pt_offset_spin)
        random_c_layout.addLayout(offset_row)

        # Distance: slider + spin inline (0.0 - 1.0, step 0.05)
        random_c_layout.addWidget(QLabel("Distance:"))
        dist_row = QHBoxLayout()
        self._pt_dist_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_dist_slider.setRange(0, 100)  # 0.00 - 1.00 in 0.01 steps
        self._pt_dist_slider.setValue(int(tool.random_distance * 100))
        self._pt_dist_slider.valueChanged.connect(self._on_dist_slider)
        dist_row.addWidget(self._pt_dist_slider, stretch=1)
        self._pt_dist_spin = QDoubleSpinBox()
        self._pt_dist_spin.setRange(0.0, 1.0)
        self._pt_dist_spin.setSingleStep(0.05)
        self._pt_dist_spin.setDecimals(2)
        self._pt_dist_spin.setValue(tool.random_distance)
        self._pt_dist_spin.setFixedWidth(65)
        self._pt_dist_spin.valueChanged.connect(self._on_dist_spin)
        dist_row.addWidget(self._pt_dist_spin)
        random_c_layout.addLayout(dist_row)

        # Endpoint: slider + spin inline (0.0 - 100.0, step 0.5)
        random_c_layout.addWidget(QLabel("Endpoint:"))
        endpoint_row = QHBoxLayout()
        self._pt_endpoint_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_endpoint_slider.setRange(0, 1000)  # 0.0 - 100.0 in 0.1 steps
        self._pt_endpoint_slider.setValue(int(tool.random_endpoint * 10))
        self._pt_endpoint_slider.valueChanged.connect(self._on_endpoint_slider)
        endpoint_row.addWidget(self._pt_endpoint_slider, stretch=1)
        self._pt_endpoint_spin = QDoubleSpinBox()
        self._pt_endpoint_spin.setRange(0.0, 100.0)
        self._pt_endpoint_spin.setSingleStep(0.5)
        self._pt_endpoint_spin.setValue(tool.random_endpoint)
        self._pt_endpoint_spin.setFixedWidth(65)
        self._pt_endpoint_spin.valueChanged.connect(self._on_endpoint_spin)
        endpoint_row.addWidget(self._pt_endpoint_spin)
        random_c_layout.addLayout(endpoint_row)

        # Jitter: slider + spin inline (0.0 - 10.0, step 0.1)
        random_c_layout.addWidget(QLabel("Jitter:"))
        jitter_row = QHBoxLayout()
        self._pt_jitter_slider = QSlider(Qt.Orientation.Horizontal)
        self._pt_jitter_slider.setRange(0, 100)  # 0.0 - 10.0 in 0.1 steps
        self._pt_jitter_slider.setValue(round(tool.random_jitter * 10))
        self._pt_jitter_slider.valueChanged.connect(self._on_jitter_slider)
        jitter_row.addWidget(self._pt_jitter_slider, stretch=1)
        self._pt_jitter_spin = QDoubleSpinBox()
        self._pt_jitter_spin.setRange(0.0, 10.0)
        self._pt_jitter_spin.setSingleStep(0.1)
        self._pt_jitter_spin.setDecimals(1)
        self._pt_jitter_spin.setValue(tool.random_jitter)
        self._pt_jitter_spin.setFixedWidth(65)
        self._pt_jitter_spin.valueChanged.connect(self._on_jitter_spin)
        jitter_row.addWidget(self._pt_jitter_spin)
        random_c_layout.addLayout(jitter_row)

        self._pt_random_container.setEnabled(tool.random)
        random_gl.addWidget(self._pt_random_container)

        layout.addWidget(random_group)

        # Initialize palette
        ensure_default_palette()
        self._pt_refresh_palette_combo()
        self._pt_palette_combo.currentTextChanged.connect(self._pt_on_palette_changed)
        idx = self._pt_palette_combo.findText("Default")
        if idx >= 0:
            self._pt_palette_combo.setCurrentIndex(idx)
        else:
            self._pt_on_palette_changed(self._pt_palette_combo.currentText())

        # Initialize texture browsers
        self._refresh_texture_browser()
        self._refresh_bg_texture_browser()

        # ===== Shadow group =====
        shadow_group = QGroupBox("Shadow")
        shadow_gl = QVBoxLayout(shadow_group)
        shadow_gl.setContentsMargins(6, 4, 6, 4)

        self._shadow_cb = QCheckBox("Enable Shadow")
        layer = self._get_layer()
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
        """Hide all path sidebars and uncheck their expand buttons."""
        if self._pp_preset_sidebar:
            self._pp_preset_sidebar.hide()
        try:
            if hasattr(self, "_pp_expand_btn"):
                self._pp_expand_btn.setChecked(False)
        except RuntimeError:
            pass
        if self._pt_texture_sidebar:
            self._pt_texture_sidebar.hide()
        try:
            if hasattr(self, "_pt_tex_expand_btn"):
                self._pt_tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass
        if self._pt_bg_texture_sidebar:
            self._pt_bg_texture_sidebar.hide()
        try:
            if hasattr(self, "_pt_bg_tex_expand_btn"):
                self._pt_bg_tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Selection sync ---

    def _on_selection_changed(self, obj) -> None:
        if obj:
            self._sync_widgets_from_object(obj)

    def _sync_widgets_from_object(self, obj) -> None:
        """Sync all widgets and tool properties from a selected PathObject."""
        tool = self._path_tool
        if tool is None:
            return

        # Update tool properties
        tool.color = obj.color
        tool.width = obj.width
        tool.line_type = obj.line_type
        tool.dash_length = obj.dash_length
        tool.gap_length = obj.gap_length
        tool.dash_cap = obj.dash_cap
        tool.texture_id = obj.texture_id
        tool.texture_zoom = obj.texture_zoom
        tool.texture_rotation = obj.texture_rotation
        tool.bg_enabled = obj.bg_enabled
        tool.bg_color = obj.bg_color
        tool.bg_width = obj.bg_width
        tool.bg_line_type = obj.bg_line_type
        tool.bg_dash_length = obj.bg_dash_length
        tool.bg_gap_length = obj.bg_gap_length
        tool.bg_dash_cap = obj.bg_dash_cap
        tool.bg_texture_id = obj.bg_texture_id
        tool.bg_texture_zoom = obj.bg_texture_zoom
        tool.bg_texture_rotation = obj.bg_texture_rotation
        tool.bg_opacity = obj.bg_opacity
        tool.random = obj.random
        tool.random_amplitude = obj.random_amplitude
        tool.random_distance = obj.random_distance
        tool.random_endpoint = obj.random_endpoint
        tool.random_jitter = obj.random_jitter
        tool.random_offset = obj.random_offset
        tool.opacity = obj.opacity

        # Paint mode
        is_texture = bool(obj.texture_id)
        self._pt_paint_mode_group.blockSignals(True)
        btn = self._pt_paint_mode_group.button(1 if is_texture else 0)
        if btn:
            btn.setChecked(True)
        self._pt_paint_mode_group.blockSignals(False)
        self._pt_color_group.setVisible(not is_texture)
        self._pt_texture_group.setVisible(is_texture)

        # Color
        update_color_btn(self._pt_color_btn, QColor(obj.color))

        # Width
        self._pt_width_slider.blockSignals(True)
        self._pt_width_slider.setValue(int(obj.width * 2))
        self._pt_width_slider.blockSignals(False)
        self._pt_width_spin.blockSignals(True)
        self._pt_width_spin.setValue(obj.width)
        self._pt_width_spin.blockSignals(False)

        # Line type
        self._pt_line_type_combo.blockSignals(True)
        self._pt_line_type_combo.setCurrentText(_LINE_TYPE_REVERSE.get(obj.line_type, "Solid"))
        self._pt_line_type_combo.blockSignals(False)
        self._pt_dash_container.setEnabled(obj.line_type != "solid")

        self._pt_dash_slider.blockSignals(True)
        self._pt_dash_slider.setValue(max(1, round(obj.dash_length * 10)))
        self._pt_dash_slider.blockSignals(False)
        self._pt_dash_spin.blockSignals(True)
        self._pt_dash_spin.setValue(obj.dash_length)
        self._pt_dash_spin.blockSignals(False)

        self._pt_gap_slider.blockSignals(True)
        self._pt_gap_slider.setValue(max(1, round(obj.gap_length * 10)))
        self._pt_gap_slider.blockSignals(False)
        self._pt_gap_spin.blockSignals(True)
        self._pt_gap_spin.setValue(obj.gap_length)
        self._pt_gap_spin.blockSignals(False)

        self._pt_cap_combo.blockSignals(True)
        self._pt_cap_combo.setCurrentText(_CAP_REVERSE.get(obj.dash_cap, "Flat"))
        self._pt_cap_combo.blockSignals(False)

        # Texture
        if is_texture:
            self._pt_tex_zoom_slider.blockSignals(True)
            self._pt_tex_zoom_slider.setValue(int(obj.texture_zoom * 10))
            self._pt_tex_zoom_slider.blockSignals(False)
            self._pt_tex_zoom_spin.blockSignals(True)
            self._pt_tex_zoom_spin.setValue(obj.texture_zoom)
            self._pt_tex_zoom_spin.blockSignals(False)

            self._pt_tex_rotation_slider.blockSignals(True)
            self._pt_tex_rotation_slider.setValue(int(obj.texture_rotation))
            self._pt_tex_rotation_slider.blockSignals(False)
            self._pt_tex_rotation_spin.blockSignals(True)
            self._pt_tex_rotation_spin.setValue(int(obj.texture_rotation))
            self._pt_tex_rotation_spin.blockSignals(False)
            self._sync_pt_tex_rot_buttons(int(obj.texture_rotation))
            # Update FG texture browser selection
            self._selected_browser_texture = None
            for tex in self._texture_catalog.textures:
                if tex.id == obj.texture_id:
                    self._selected_browser_texture = tex
                    break
            self._update_texture_selection()
        else:
            # Clear FG texture selection when in color mode
            self._selected_browser_texture = None
            self._update_texture_selection()

        # Background path
        self._pt_bg_cb.blockSignals(True)
        self._pt_bg_cb.setChecked(obj.bg_enabled)
        self._pt_bg_cb.blockSignals(False)
        self._pt_bg_container.setEnabled(obj.bg_enabled)

        update_color_btn(self._pt_bg_color_btn, QColor(obj.bg_color))

        self._pt_bg_width_slider.blockSignals(True)
        self._pt_bg_width_slider.setValue(int(obj.bg_width * 2))
        self._pt_bg_width_slider.blockSignals(False)
        self._pt_bg_width_spin.blockSignals(True)
        self._pt_bg_width_spin.setValue(obj.bg_width)
        self._pt_bg_width_spin.blockSignals(False)

        self._pt_bg_line_type_combo.blockSignals(True)
        self._pt_bg_line_type_combo.setCurrentText(
            _LINE_TYPE_REVERSE.get(obj.bg_line_type, "Solid")
        )
        self._pt_bg_line_type_combo.blockSignals(False)
        self._pt_bg_dash_container.setEnabled(obj.bg_line_type != "solid")

        self._pt_bg_dash_slider.blockSignals(True)
        self._pt_bg_dash_slider.setValue(max(1, round(obj.bg_dash_length * 10)))
        self._pt_bg_dash_slider.blockSignals(False)
        self._pt_bg_dash_spin.blockSignals(True)
        self._pt_bg_dash_spin.setValue(obj.bg_dash_length)
        self._pt_bg_dash_spin.blockSignals(False)

        self._pt_bg_gap_slider.blockSignals(True)
        self._pt_bg_gap_slider.setValue(max(1, round(obj.bg_gap_length * 10)))
        self._pt_bg_gap_slider.blockSignals(False)
        self._pt_bg_gap_spin.blockSignals(True)
        self._pt_bg_gap_spin.setValue(obj.bg_gap_length)
        self._pt_bg_gap_spin.blockSignals(False)

        self._pt_bg_cap_combo.blockSignals(True)
        self._pt_bg_cap_combo.setCurrentText(_CAP_REVERSE.get(obj.bg_dash_cap, "Flat"))
        self._pt_bg_cap_combo.blockSignals(False)

        # BG Texture
        is_bg_texture = bool(obj.bg_texture_id)
        if is_bg_texture:
            self._pt_bg_paint_mode_group.blockSignals(True)
            self._pt_bg_paint_mode_group.button(1).setChecked(True)
            self._pt_bg_paint_mode_group.blockSignals(False)
        else:
            self._pt_bg_paint_mode_group.blockSignals(True)
            self._pt_bg_paint_mode_group.button(0).setChecked(True)
            self._pt_bg_paint_mode_group.blockSignals(False)
        self._pt_bg_color_section.setVisible(not is_bg_texture)
        self._pt_bg_texture_section.setVisible(is_bg_texture)
        if is_bg_texture:
            self._pt_bg_tex_zoom_slider.blockSignals(True)
            self._pt_bg_tex_zoom_slider.setValue(int(obj.bg_texture_zoom * 10))
            self._pt_bg_tex_zoom_slider.blockSignals(False)
            self._pt_bg_tex_zoom_spin.blockSignals(True)
            self._pt_bg_tex_zoom_spin.setValue(obj.bg_texture_zoom)
            self._pt_bg_tex_zoom_spin.blockSignals(False)
            self._pt_bg_tex_rotation_slider.blockSignals(True)
            self._pt_bg_tex_rotation_slider.setValue(int(obj.bg_texture_rotation))
            self._pt_bg_tex_rotation_slider.blockSignals(False)
            self._pt_bg_tex_rotation_spin.blockSignals(True)
            self._pt_bg_tex_rotation_spin.setValue(int(obj.bg_texture_rotation))
            self._pt_bg_tex_rotation_spin.blockSignals(False)
            for btn in self._pt_bg_tex_rot_buttons:
                btn.setChecked(int(btn.text()) == int(obj.bg_texture_rotation))
            # Update BG texture browser selection
            self._selected_bg_browser_texture = None
            for tex in self._texture_catalog.textures:
                if tex.id == obj.bg_texture_id:
                    self._selected_bg_browser_texture = tex
                    break
            self._update_bg_texture_selection()
        else:
            # Clear BG texture selection when in color mode
            self._selected_bg_browser_texture = None
            self._update_bg_texture_selection()

        # Random
        self._pt_random_cb.blockSignals(True)
        self._pt_random_cb.setChecked(obj.random)
        self._pt_random_cb.blockSignals(False)
        self._pt_random_container.setEnabled(obj.random)

        self._pt_amp_slider.blockSignals(True)
        self._pt_amp_slider.setValue(round(obj.random_amplitude / 0.5))
        self._pt_amp_slider.blockSignals(False)
        self._pt_amp_spin.blockSignals(True)
        self._pt_amp_spin.setValue(obj.random_amplitude)
        self._pt_amp_spin.blockSignals(False)

        self._pt_dist_slider.blockSignals(True)
        self._pt_dist_slider.setValue(int(obj.random_distance * 100))
        self._pt_dist_slider.blockSignals(False)
        self._pt_dist_spin.blockSignals(True)
        self._pt_dist_spin.setValue(obj.random_distance)
        self._pt_dist_spin.blockSignals(False)

        self._pt_endpoint_slider.blockSignals(True)
        self._pt_endpoint_slider.setValue(int(obj.random_endpoint * 10))
        self._pt_endpoint_slider.blockSignals(False)
        self._pt_endpoint_spin.blockSignals(True)
        self._pt_endpoint_spin.setValue(obj.random_endpoint)
        self._pt_endpoint_spin.blockSignals(False)

        self._pt_offset_slider.blockSignals(True)
        self._pt_offset_slider.setValue(round(obj.random_offset / 0.5))
        self._pt_offset_slider.blockSignals(False)
        self._pt_offset_spin.blockSignals(True)
        self._pt_offset_spin.setValue(obj.random_offset)
        self._pt_offset_spin.blockSignals(False)

        self._pt_jitter_slider.blockSignals(True)
        self._pt_jitter_slider.setValue(round(obj.random_jitter * 10))
        self._pt_jitter_slider.blockSignals(False)
        self._pt_jitter_spin.blockSignals(True)
        self._pt_jitter_spin.setValue(obj.random_jitter)
        self._pt_jitter_spin.blockSignals(False)

        # Opacity
        self._pt_opacity_slider.blockSignals(True)
        self._pt_opacity_slider.setValue(round(obj.opacity * 100))
        self._pt_opacity_slider.blockSignals(False)
        self._pt_opacity_spin.blockSignals(True)
        self._pt_opacity_spin.setValue(round(obj.opacity * 100))
        self._pt_opacity_spin.blockSignals(False)

        # BG Opacity
        self._pt_bg_opacity_slider.blockSignals(True)
        self._pt_bg_opacity_slider.setValue(round(obj.bg_opacity * 100))
        self._pt_bg_opacity_slider.blockSignals(False)
        self._pt_bg_opacity_spin.blockSignals(True)
        self._pt_bg_opacity_spin.setValue(round(obj.bg_opacity * 100))
        self._pt_bg_opacity_spin.blockSignals(False)

    def _apply_to_selected(self, **changes) -> None:
        """Apply property changes to the currently selected PathObject via command."""
        if (self._path_tool and self._path_tool.mode == "select"
                and self._path_tool._selected is not None):
            layer = self._path_tool._get_active_path_layer()
            if layer:
                cmd = EditPathCommand(layer, self._path_tool._selected, **changes)
                self._path_tool._command_stack.execute(cmd)

    # --- Mode ---

    def _on_mode_changed(self, button_id: int, checked: bool) -> None:
        if checked and self._path_tool:
            self._path_tool.mode = "place" if button_id == 0 else "select"
            self._path_tool._selected = None
            self._path_tool._interaction = None
            if button_id == 0:
                self._path_tool._notify_selection()

    # --- Color ---

    def _on_color_pick(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._path_tool.color), self.dock, "Pick Path Color",
        )
        if color.isValid():
            self._path_tool.color = color.name()
            update_color_btn(self._pt_color_btn, color)
            self._apply_to_selected(color=color.name())

    # --- Paint Mode (Color / Texture) ---

    def _on_paint_mode_changed(self, button_id: int, checked: bool) -> None:
        if not checked or not self._path_tool:
            return
        is_texture = button_id == 1
        self._pt_color_group.setVisible(not is_texture)
        self._pt_texture_group.setVisible(is_texture)
        if not is_texture:
            self._path_tool.texture_id = ""
            self._apply_to_selected(texture_id="")

    # --- Texture browser ---

    def _refresh_texture_browser(self) -> None:
        self._texture_catalog = load_texture_catalog()
        self._refresh_texture_filter_combos()
        self._rebuild_texture_browser()
        self._refresh_bg_texture_browser()

    def _refresh_texture_filter_combos(self) -> None:
        self._pt_tex_game_combo.blockSignals(True)
        current_game = self._pt_tex_game_combo.currentText()
        self._pt_tex_game_combo.clear()
        self._pt_tex_game_combo.addItem("All")
        for g in self._texture_catalog.games():
            self._pt_tex_game_combo.addItem(g)
        idx = self._pt_tex_game_combo.findText(current_game)
        if idx >= 0:
            self._pt_tex_game_combo.setCurrentIndex(idx)
        self._pt_tex_game_combo.blockSignals(False)

        self._pt_tex_category_combo.blockSignals(True)
        current_cat = self._pt_tex_category_combo.currentText()
        self._pt_tex_category_combo.clear()
        self._pt_tex_category_combo.addItem("All")
        for cat in self._texture_catalog.categories():
            self._pt_tex_category_combo.addItem(cat)
        idx = self._pt_tex_category_combo.findText(current_cat)
        if idx >= 0:
            self._pt_tex_category_combo.setCurrentIndex(idx)
        self._pt_tex_category_combo.blockSignals(False)

    def _filtered_browser_textures(self) -> list[LibraryTexture]:
        game = self._pt_tex_game_combo.currentText()
        category = self._pt_tex_category_combo.currentText()
        search = self._pt_tex_search_edit.text().strip().lower()
        result = []
        for tex in self._texture_catalog.textures:
            if game != "All" and tex.game != game:
                continue
            if category != "All" and tex.category != category:
                continue
            if search and search not in tex.display_name.lower():
                continue
            result.append(tex)
        return result

    def _rebuild_texture_browser(self) -> None:
        for btn in list(self._texture_browser_buttons.values()):
            try:
                self._pt_tex_grid_layout.removeWidget(btn)
                btn.deleteLater()
            except RuntimeError:
                pass
        self._texture_browser_buttons.clear()

        filtered = self._filtered_browser_textures()
        cols = 3
        for i, tex in enumerate(filtered):
            btn = self._make_texture_thumb(tex)
            row = i // cols
            col = i % cols
            self._pt_tex_grid_layout.addWidget(btn, row, col)
            self._texture_browser_buttons[tex.id] = btn
        self._update_texture_selection()

    def _make_texture_thumb(self, tex: LibraryTexture) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(56, 70)
        game_info = f"  ({tex.game})" if tex.game else ""
        btn.setToolTip(f"{tex.display_name}{game_info}\n{tex.category}")
        pixmap = self._get_texture_thumb(tex)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(48, 48))
        btn.setText(tex.display_name[:8])
        btn.setStyleSheet("QToolButton { padding: 1px; }")
        btn.clicked.connect(lambda checked=False, t=tex: self._on_texture_clicked(t))
        return btn

    def _get_texture_thumb(self, tex: LibraryTexture) -> QPixmap | None:
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

    def _on_texture_clicked(self, tex: LibraryTexture) -> None:
        self._selected_browser_texture = tex
        self._path_tool.texture_id = tex.id
        self._update_texture_selection()
        if self._pt_texture_sidebar and self._pt_texture_sidebar.isVisible():
            self._pt_texture_sidebar.set_selected(tex.id)
        self._apply_to_selected(texture_id=tex.id)

    def _update_texture_selection(self) -> None:
        for tex_id, btn in self._texture_browser_buttons.items():
            if self._selected_browser_texture and tex_id == self._selected_browser_texture.id:
                btn.setStyleSheet(
                    "QToolButton { padding: 1px; border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 1px; }")

    def _on_tex_filter_changed(self) -> None:
        self._rebuild_texture_browser()
        self._sync_texture_sidebar()

    def _on_open_texture_manager(self) -> None:
        dialog = TextureManagerDialog(self.dock)
        dialog.catalog_changed.connect(self._on_texture_manager_changed)
        dialog.exec()

    def _on_texture_manager_changed(self) -> None:
        self._texture_thumb_cache.clear()
        if self._pt_texture_sidebar:
            self._pt_texture_sidebar.invalidate_cache()
        self._refresh_texture_browser()
        self._sync_texture_sidebar()

    def refresh_texture_catalog(self) -> None:
        """Reload texture catalog (called on tool switch to pick up imports from other tools)."""
        if not hasattr(self, "_texture_catalog"):
            return
        self._refresh_texture_browser()
        self._sync_texture_sidebar()

    def refresh_palette_catalog(self) -> None:
        """Reload palette combo (called when the palette editor reports changes)."""
        if not hasattr(self, "_pt_palette_combo"):
            return
        self._pt_refresh_palette_combo()

    def _on_tex_rot_preset(self, degrees: int) -> None:
        self._path_tool.texture_rotation = float(degrees)
        self._pt_tex_rotation_slider.blockSignals(True)
        self._pt_tex_rotation_slider.setValue(degrees)
        self._pt_tex_rotation_slider.blockSignals(False)
        self._pt_tex_rotation_spin.blockSignals(True)
        self._pt_tex_rotation_spin.setValue(degrees)
        self._pt_tex_rotation_spin.blockSignals(False)
        self._sync_pt_tex_rot_buttons(degrees)
        self._apply_to_selected(texture_rotation=float(degrees))

    # --- Texture sidebar ---

    def _on_toggle_texture_sidebar(self, checked: bool) -> None:
        if checked:
            self.dock._save_panel_width()
            if not self._pt_texture_sidebar:
                self._pt_texture_sidebar = TextureBrowserSidebar(self.dock.window())
                self._pt_texture_sidebar.texture_clicked.connect(
                    self._on_tex_sidebar_clicked,
                )
                self._pt_texture_sidebar.closed.connect(
                    self._on_tex_sidebar_closed,
                )
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea,
                    self._pt_texture_sidebar,
                )
                main_win.splitDockWidget(
                    self.dock, self._pt_texture_sidebar, Qt.Orientation.Horizontal,
                )
            self._pt_texture_sidebar.show()
            self._sync_texture_sidebar()
        else:
            if self._pt_texture_sidebar:
                self._pt_texture_sidebar.hide()
            self.dock._restore_panel_width()

    def _sync_texture_sidebar(self) -> None:
        if not self._pt_texture_sidebar or not self._pt_texture_sidebar.isVisible():
            return
        filtered = self._filtered_browser_textures()
        selected_id = (
            self._selected_browser_texture.id
            if self._selected_browser_texture
            else None
        )
        self._pt_texture_sidebar.set_textures(filtered, selected_id)

    def _on_tex_sidebar_clicked(self, tex: LibraryTexture) -> None:
        self._on_texture_clicked(tex)

    def _on_tex_sidebar_closed(self) -> None:
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_pt_tex_expand_btn"):
                self._pt_tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Width slider/spin sync ---

    def _on_pt_width_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._path_tool.width = real_val
        self._pt_width_spin.blockSignals(True)
        self._pt_width_spin.setValue(real_val)
        self._pt_width_spin.blockSignals(False)
        self._apply_to_selected(width=real_val)

    def _on_pt_width_spin(self, value: float) -> None:
        self._path_tool.width = value
        self._pt_width_slider.blockSignals(True)
        self._pt_width_slider.setValue(int(value * 2))
        self._pt_width_slider.blockSignals(False)
        self._apply_to_selected(width=value)

    def _on_pt_bg_width_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._path_tool.bg_width = real_val
        self._pt_bg_width_spin.blockSignals(True)
        self._pt_bg_width_spin.setValue(real_val)
        self._pt_bg_width_spin.blockSignals(False)
        self._apply_to_selected(bg_width=real_val)

    def _on_pt_bg_width_spin(self, value: float) -> None:
        self._path_tool.bg_width = value
        self._pt_bg_width_slider.blockSignals(True)
        self._pt_bg_width_slider.setValue(int(value * 2))
        self._pt_bg_width_slider.blockSignals(False)
        self._apply_to_selected(bg_width=value)

    # --- Texture zoom/rotation slider/spin sync ---

    def _on_pt_tex_zoom_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._path_tool.texture_zoom = real_val
        self._pt_tex_zoom_spin.blockSignals(True)
        self._pt_tex_zoom_spin.setValue(real_val)
        self._pt_tex_zoom_spin.blockSignals(False)
        self._apply_to_selected(texture_zoom=real_val)

    def _on_pt_tex_zoom_spin(self, value: float) -> None:
        self._path_tool.texture_zoom = value
        self._pt_tex_zoom_slider.blockSignals(True)
        self._pt_tex_zoom_slider.setValue(int(value * 10))
        self._pt_tex_zoom_slider.blockSignals(False)
        self._apply_to_selected(texture_zoom=value)

    def _on_pt_tex_rot_slider(self, value: int) -> None:
        self._path_tool.texture_rotation = float(value)
        self._pt_tex_rotation_spin.blockSignals(True)
        self._pt_tex_rotation_spin.setValue(value)
        self._pt_tex_rotation_spin.blockSignals(False)
        self._sync_pt_tex_rot_buttons(value)
        self._apply_to_selected(texture_rotation=float(value))

    def _on_pt_tex_rot_spin(self, value: int) -> None:
        self._path_tool.texture_rotation = float(value)
        self._pt_tex_rotation_slider.blockSignals(True)
        self._pt_tex_rotation_slider.setValue(value)
        self._pt_tex_rotation_slider.blockSignals(False)
        self._sync_pt_tex_rot_buttons(value)
        self._apply_to_selected(texture_rotation=float(value))

    def _sync_pt_tex_rot_buttons(self, value: int) -> None:
        """Highlight the preset button matching the current texture rotation value."""
        _PRESETS = (0, 60, 90, 120, 180, 270)
        for i, preset in enumerate(_PRESETS):
            self._pt_tex_rot_buttons[i].setChecked(preset == value)

    # --- Dash/Gap slider/spin sync ---

    def _on_pt_dash_slider(self, value: int) -> None:
        real_val = value * 0.1
        self._path_tool.dash_length = real_val
        self._pt_dash_spin.blockSignals(True)
        self._pt_dash_spin.setValue(real_val)
        self._pt_dash_spin.blockSignals(False)
        self._apply_to_selected(dash_length=real_val)

    def _on_pt_dash_spin(self, value: float) -> None:
        self._path_tool.dash_length = value
        self._pt_dash_slider.blockSignals(True)
        self._pt_dash_slider.setValue(max(1, round(value * 10)))
        self._pt_dash_slider.blockSignals(False)
        self._apply_to_selected(dash_length=value)

    def _on_pt_gap_slider(self, value: int) -> None:
        real_val = value * 0.1
        self._path_tool.gap_length = real_val
        self._pt_gap_spin.blockSignals(True)
        self._pt_gap_spin.setValue(real_val)
        self._pt_gap_spin.blockSignals(False)
        self._apply_to_selected(gap_length=real_val)

    def _on_pt_gap_spin(self, value: float) -> None:
        self._path_tool.gap_length = value
        self._pt_gap_slider.blockSignals(True)
        self._pt_gap_slider.setValue(max(1, round(value * 10)))
        self._pt_gap_slider.blockSignals(False)
        self._apply_to_selected(gap_length=value)

    def _on_pt_bg_dash_slider(self, value: int) -> None:
        real_val = value * 0.1
        self._path_tool.bg_dash_length = real_val
        self._pt_bg_dash_spin.blockSignals(True)
        self._pt_bg_dash_spin.setValue(real_val)
        self._pt_bg_dash_spin.blockSignals(False)
        self._apply_to_selected(bg_dash_length=real_val)

    def _on_pt_bg_dash_spin(self, value: float) -> None:
        self._path_tool.bg_dash_length = value
        self._pt_bg_dash_slider.blockSignals(True)
        self._pt_bg_dash_slider.setValue(max(1, round(value * 10)))
        self._pt_bg_dash_slider.blockSignals(False)
        self._apply_to_selected(bg_dash_length=value)

    def _on_pt_bg_gap_slider(self, value: int) -> None:
        real_val = value * 0.1
        self._path_tool.bg_gap_length = real_val
        self._pt_bg_gap_spin.blockSignals(True)
        self._pt_bg_gap_spin.setValue(real_val)
        self._pt_bg_gap_spin.blockSignals(False)
        self._apply_to_selected(bg_gap_length=real_val)

    def _on_pt_bg_gap_spin(self, value: float) -> None:
        self._path_tool.bg_gap_length = value
        self._pt_bg_gap_slider.blockSignals(True)
        self._pt_bg_gap_slider.setValue(max(1, round(value * 10)))
        self._pt_bg_gap_slider.blockSignals(False)
        self._apply_to_selected(bg_gap_length=value)

    # --- Line Type ---

    def _on_line_type_changed(self, text: str) -> None:
        lt = _LINE_TYPE_MAP.get(text, "solid")
        self._path_tool.line_type = lt
        self._pt_dash_container.setEnabled(lt != "solid")
        self._apply_to_selected(line_type=lt)

    def _on_cap_changed(self, text: str) -> None:
        cap = _CAP_MAP.get(text, "flat")
        self._path_tool.dash_cap = cap
        self._apply_to_selected(dash_cap=cap)

    # --- Background Path ---

    def _on_bg_toggled(self, checked: bool) -> None:
        self._path_tool.bg_enabled = checked
        if checked:
            # Auto-set BG width to match FG width on first enable
            fg_width = self._path_tool.width
            self._path_tool.bg_width = fg_width
            self._pt_bg_width_slider.blockSignals(True)
            self._pt_bg_width_slider.setValue(int(fg_width * 2))
            self._pt_bg_width_slider.blockSignals(False)
            self._pt_bg_width_spin.blockSignals(True)
            self._pt_bg_width_spin.setValue(fg_width)
            self._pt_bg_width_spin.blockSignals(False)
        self._pt_bg_container.setEnabled(checked)
        self._apply_to_selected(bg_enabled=checked)

    def _on_bg_color_pick(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._path_tool.bg_color), self.dock, "Pick Background Color",
        )
        if color.isValid():
            self._path_tool.bg_color = color.name()
            update_color_btn(self._pt_bg_color_btn, color)
            self._apply_to_selected(bg_color=color.name())

    def _on_bg_line_type_changed(self, text: str) -> None:
        lt = _LINE_TYPE_MAP.get(text, "solid")
        self._path_tool.bg_line_type = lt
        self._pt_bg_dash_container.setEnabled(lt != "solid")
        self._apply_to_selected(bg_line_type=lt)

    def _on_bg_cap_changed(self, text: str) -> None:
        cap = _CAP_MAP.get(text, "flat")
        self._path_tool.bg_dash_cap = cap
        self._apply_to_selected(bg_dash_cap=cap)

    # --- BG Texture ---

    def _on_bg_paint_mode_changed(self, button_id: int, checked: bool) -> None:
        if not checked or not self._path_tool:
            return
        is_texture = button_id == 1
        self._pt_bg_color_section.setVisible(not is_texture)
        self._pt_bg_texture_section.setVisible(is_texture)
        if not is_texture:
            self._path_tool.bg_texture_id = ""
            self._apply_to_selected(bg_texture_id="")

    def _refresh_bg_texture_browser(self) -> None:
        self._refresh_bg_texture_filter_combos()
        self._rebuild_bg_texture_browser()

    def _refresh_bg_texture_filter_combos(self) -> None:
        self._pt_bg_tex_game_combo.blockSignals(True)
        current_game = self._pt_bg_tex_game_combo.currentText()
        self._pt_bg_tex_game_combo.clear()
        self._pt_bg_tex_game_combo.addItem("All")
        for g in self._texture_catalog.games():
            self._pt_bg_tex_game_combo.addItem(g)
        idx = self._pt_bg_tex_game_combo.findText(current_game)
        if idx >= 0:
            self._pt_bg_tex_game_combo.setCurrentIndex(idx)
        self._pt_bg_tex_game_combo.blockSignals(False)

        self._pt_bg_tex_category_combo.blockSignals(True)
        current_cat = self._pt_bg_tex_category_combo.currentText()
        self._pt_bg_tex_category_combo.clear()
        self._pt_bg_tex_category_combo.addItem("All")
        for cat in self._texture_catalog.categories():
            self._pt_bg_tex_category_combo.addItem(cat)
        idx = self._pt_bg_tex_category_combo.findText(current_cat)
        if idx >= 0:
            self._pt_bg_tex_category_combo.setCurrentIndex(idx)
        self._pt_bg_tex_category_combo.blockSignals(False)

    def _on_bg_tex_filter_changed(self) -> None:
        self._rebuild_bg_texture_browser()
        self._sync_bg_texture_sidebar()

    def _filtered_bg_browser_textures(self) -> list[LibraryTexture]:
        game = self._pt_bg_tex_game_combo.currentText()
        category = self._pt_bg_tex_category_combo.currentText()
        search = self._pt_bg_tex_search_edit.text().strip().lower()
        result = []
        for tex in self._texture_catalog.textures:
            if game != "All" and tex.game != game:
                continue
            if category != "All" and tex.category != category:
                continue
            if search and search not in tex.display_name.lower():
                continue
            result.append(tex)
        return result

    def _rebuild_bg_texture_browser(self) -> None:
        for btn in list(self._bg_texture_browser_buttons.values()):
            try:
                self._pt_bg_tex_grid_layout.removeWidget(btn)
                btn.deleteLater()
            except RuntimeError:
                pass
        self._bg_texture_browser_buttons.clear()

        filtered = self._filtered_bg_browser_textures()
        cols = 3
        for i, tex in enumerate(filtered):
            btn = self._make_bg_texture_thumb(tex)
            row = i // cols
            col = i % cols
            self._pt_bg_tex_grid_layout.addWidget(btn, row, col)
            self._bg_texture_browser_buttons[tex.id] = btn
        self._update_bg_texture_selection()

    def _make_bg_texture_thumb(self, tex: LibraryTexture) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(56, 70)
        game_info = f"  ({tex.game})" if tex.game else ""
        btn.setToolTip(f"{tex.display_name}{game_info}\n{tex.category}")
        pixmap = self._get_texture_thumb(tex)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(48, 48))
        btn.setText(tex.display_name[:8])
        btn.setStyleSheet("QToolButton { padding: 1px; }")
        btn.clicked.connect(lambda checked=False, t=tex: self._on_bg_texture_clicked(t))
        return btn

    def _on_bg_texture_clicked(self, tex: LibraryTexture) -> None:
        self._selected_bg_browser_texture = tex
        self._path_tool.bg_texture_id = tex.id
        self._update_bg_texture_selection()
        if self._pt_bg_texture_sidebar and self._pt_bg_texture_sidebar.isVisible():
            self._pt_bg_texture_sidebar.set_selected(tex.id)
        self._apply_to_selected(bg_texture_id=tex.id)

    def _update_bg_texture_selection(self) -> None:
        sel_id = self._selected_bg_browser_texture.id if self._selected_bg_browser_texture else None
        for tex_id, btn in self._bg_texture_browser_buttons.items():
            if sel_id and tex_id == sel_id:
                btn.setStyleSheet("QToolButton { padding: 1px; border: 2px solid #00aaff; }")
            else:
                btn.setStyleSheet("QToolButton { padding: 1px; }")

    def _on_toggle_bg_texture_sidebar(self, checked: bool) -> None:
        if checked:
            self.dock._save_panel_width()
            if not self._pt_bg_texture_sidebar:
                self._pt_bg_texture_sidebar = TextureBrowserSidebar(self.dock.window())
                self._pt_bg_texture_sidebar.texture_clicked.connect(self._on_bg_tex_sidebar_clicked)
                self._pt_bg_texture_sidebar.closed.connect(self._on_bg_tex_sidebar_closed)
                main_win = self.dock.window()
                main_win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._pt_bg_texture_sidebar)
                main_win.splitDockWidget(self.dock, self._pt_bg_texture_sidebar, Qt.Orientation.Horizontal)
            self._pt_bg_texture_sidebar.show()
            self._sync_bg_texture_sidebar()
        else:
            if self._pt_bg_texture_sidebar:
                self._pt_bg_texture_sidebar.hide()
            self.dock._restore_panel_width()

    def _sync_bg_texture_sidebar(self) -> None:
        if not self._pt_bg_texture_sidebar or not self._pt_bg_texture_sidebar.isVisible():
            return
        filtered = self._filtered_bg_browser_textures()
        selected_id = self._selected_bg_browser_texture.id if self._selected_bg_browser_texture else None
        self._pt_bg_texture_sidebar.set_textures(filtered, selected_id)

    def _on_bg_tex_sidebar_clicked(self, tex: LibraryTexture) -> None:
        self._on_bg_texture_clicked(tex)

    def _on_bg_tex_sidebar_closed(self) -> None:
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_pt_bg_tex_expand_btn"):
                self._pt_bg_tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    def _on_pt_bg_tex_zoom_slider(self, value: int) -> None:
        zoom = value / 10.0
        self._pt_bg_tex_zoom_spin.blockSignals(True)
        self._pt_bg_tex_zoom_spin.setValue(zoom)
        self._pt_bg_tex_zoom_spin.blockSignals(False)
        if self._path_tool:
            self._path_tool.bg_texture_zoom = zoom
            self._apply_to_selected(bg_texture_zoom=zoom)

    def _on_pt_bg_tex_zoom_spin(self, value: float) -> None:
        self._pt_bg_tex_zoom_slider.blockSignals(True)
        self._pt_bg_tex_zoom_slider.setValue(int(value * 10))
        self._pt_bg_tex_zoom_slider.blockSignals(False)
        if self._path_tool:
            self._path_tool.bg_texture_zoom = value
            self._apply_to_selected(bg_texture_zoom=value)

    def _on_pt_bg_tex_rot_slider(self, value: int) -> None:
        self._pt_bg_tex_rotation_spin.blockSignals(True)
        self._pt_bg_tex_rotation_spin.setValue(value)
        self._pt_bg_tex_rotation_spin.blockSignals(False)
        for btn in self._pt_bg_tex_rot_buttons:
            btn.setChecked(int(btn.text()) == value)
        if self._path_tool:
            self._path_tool.bg_texture_rotation = float(value)
            self._apply_to_selected(bg_texture_rotation=float(value))

    def _on_pt_bg_tex_rot_spin(self, value: int) -> None:
        self._pt_bg_tex_rotation_slider.blockSignals(True)
        self._pt_bg_tex_rotation_slider.setValue(value)
        self._pt_bg_tex_rotation_slider.blockSignals(False)
        for btn in self._pt_bg_tex_rot_buttons:
            btn.setChecked(int(btn.text()) == value)
        if self._path_tool:
            self._path_tool.bg_texture_rotation = float(value)
            self._apply_to_selected(bg_texture_rotation=float(value))

    def _on_bg_tex_rot_preset(self, deg: int) -> None:
        self._pt_bg_tex_rotation_slider.blockSignals(True)
        self._pt_bg_tex_rotation_slider.setValue(deg)
        self._pt_bg_tex_rotation_slider.blockSignals(False)
        self._pt_bg_tex_rotation_spin.blockSignals(True)
        self._pt_bg_tex_rotation_spin.setValue(deg)
        self._pt_bg_tex_rotation_spin.blockSignals(False)
        for btn in self._pt_bg_tex_rot_buttons:
            btn.setChecked(int(btn.text()) == deg)
        if self._path_tool:
            self._path_tool.bg_texture_rotation = float(deg)
            self._apply_to_selected(bg_texture_rotation=float(deg))

    # --- Random ---

    def _on_random_toggled(self, checked: bool) -> None:
        self._path_tool.random = checked
        self._pt_random_container.setEnabled(checked)
        self._apply_to_selected(random=checked)

    def _on_amp_slider(self, value: int) -> None:
        real_val = value * 0.5
        self._path_tool.random_amplitude = real_val
        self._pt_amp_spin.blockSignals(True)
        self._pt_amp_spin.setValue(real_val)
        self._pt_amp_spin.blockSignals(False)
        self._apply_to_selected(random_amplitude=real_val)

    def _on_amp_spin(self, value: float) -> None:
        self._path_tool.random_amplitude = value
        self._pt_amp_slider.blockSignals(True)
        self._pt_amp_slider.setValue(round(value / 0.5))
        self._pt_amp_slider.blockSignals(False)
        self._apply_to_selected(random_amplitude=value)

    def _on_dist_slider(self, value: int) -> None:
        real_val = value / 100.0
        self._path_tool.random_distance = real_val
        self._pt_dist_spin.blockSignals(True)
        self._pt_dist_spin.setValue(real_val)
        self._pt_dist_spin.blockSignals(False)
        self._apply_to_selected(random_distance=real_val)

    def _on_dist_spin(self, value: float) -> None:
        self._path_tool.random_distance = value
        self._pt_dist_slider.blockSignals(True)
        self._pt_dist_slider.setValue(int(value * 100))
        self._pt_dist_slider.blockSignals(False)
        self._apply_to_selected(random_distance=value)

    def _on_endpoint_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._path_tool.random_endpoint = real_val
        self._pt_endpoint_spin.blockSignals(True)
        self._pt_endpoint_spin.setValue(real_val)
        self._pt_endpoint_spin.blockSignals(False)
        self._apply_to_selected(random_endpoint=real_val)

    def _on_endpoint_spin(self, value: float) -> None:
        self._path_tool.random_endpoint = value
        self._pt_endpoint_slider.blockSignals(True)
        self._pt_endpoint_slider.setValue(int(value * 10))
        self._pt_endpoint_slider.blockSignals(False)
        self._apply_to_selected(random_endpoint=value)

    def _on_offset_slider(self, value: int) -> None:
        real_val = value * 0.5
        self._path_tool.random_offset = real_val
        self._pt_offset_spin.blockSignals(True)
        self._pt_offset_spin.setValue(real_val)
        self._pt_offset_spin.blockSignals(False)
        self._apply_to_selected(random_offset=real_val)

    def _on_offset_spin(self, value: float) -> None:
        self._path_tool.random_offset = value
        self._pt_offset_slider.blockSignals(True)
        self._pt_offset_slider.setValue(round(value / 0.5))
        self._pt_offset_slider.blockSignals(False)
        self._apply_to_selected(random_offset=value)

    def _on_jitter_slider(self, value: int) -> None:
        real_val = value * 0.1
        self._path_tool.random_jitter = real_val
        self._pt_jitter_spin.blockSignals(True)
        self._pt_jitter_spin.setValue(real_val)
        self._pt_jitter_spin.blockSignals(False)
        self._apply_to_selected(random_jitter=real_val)

    def _on_jitter_spin(self, value: float) -> None:
        self._path_tool.random_jitter = value
        self._pt_jitter_slider.blockSignals(True)
        self._pt_jitter_slider.setValue(round(value * 10))
        self._pt_jitter_slider.blockSignals(False)
        self._apply_to_selected(random_jitter=value)

    def _on_opacity_slider(self, value: int) -> None:
        real_val = value / 100.0
        self._path_tool.opacity = real_val
        self._pt_opacity_spin.blockSignals(True)
        self._pt_opacity_spin.setValue(value)
        self._pt_opacity_spin.blockSignals(False)
        self._apply_to_selected(opacity=real_val)

    def _on_opacity_spin(self, value: int) -> None:
        real_val = value / 100.0
        self._path_tool.opacity = real_val
        self._pt_opacity_slider.blockSignals(True)
        self._pt_opacity_slider.setValue(value)
        self._pt_opacity_slider.blockSignals(False)
        self._apply_to_selected(opacity=real_val)

    def _on_pt_bg_opacity_slider(self, value: int) -> None:
        real_val = value / 100.0
        self._path_tool.bg_opacity = real_val
        self._pt_bg_opacity_spin.blockSignals(True)
        self._pt_bg_opacity_spin.setValue(value)
        self._pt_bg_opacity_spin.blockSignals(False)
        self._apply_to_selected(bg_opacity=real_val)

    def _on_pt_bg_opacity_spin(self, value: int) -> None:
        real_val = value / 100.0
        self._path_tool.bg_opacity = real_val
        self._pt_bg_opacity_slider.blockSignals(True)
        self._pt_bg_opacity_slider.setValue(value)
        self._pt_bg_opacity_slider.blockSignals(False)
        self._apply_to_selected(bg_opacity=real_val)

    # --- Palette ---

    def _pt_refresh_palette_combo(self) -> None:
        self._pt_palette_combo.blockSignals(True)
        current = self._pt_palette_combo.currentText()
        self._pt_palette_combo.clear()
        for name in list_palettes():
            self._pt_palette_combo.addItem(name)
        idx = self._pt_palette_combo.findText(current)
        if idx >= 0:
            self._pt_palette_combo.setCurrentIndex(idx)
        self._pt_palette_combo.blockSignals(False)

    def _pt_on_palette_changed(self, name: str) -> None:
        if not name:
            return
        try:
            self._pt_current_palette = load_palette(name)
        except FileNotFoundError:
            self._pt_current_palette = None
        self._pt_selected_palette_idx = -1
        self._pt_rebuild_color_grid()

    def _pt_rebuild_color_grid(self) -> None:
        for btn in self._pt_palette_color_buttons:
            try:
                self._pt_color_grid_layout.removeWidget(btn)
                btn.deleteLater()
            except RuntimeError:
                pass
        self._pt_palette_color_buttons.clear()

        # Also clear BG grid
        for btn in self._pt_bg_palette_color_buttons:
            try:
                if hasattr(self, "_pt_bg_color_grid_layout"):
                    self._pt_bg_color_grid_layout.removeWidget(btn)
                btn.deleteLater()
            except RuntimeError:
                pass
        self._pt_bg_palette_color_buttons.clear()
        self._pt_bg_selected_palette_idx = -1

        if not self._pt_current_palette:
            return

        for i, pc in enumerate(self._pt_current_palette.colors):
            # FG grid button
            btn = QPushButton()
            btn.setFixedSize(36, 36)
            btn.setToolTip(pc.name)
            self._pt_style_palette_btn(btn, pc.color, selected=False)
            btn.clicked.connect(
                lambda checked, idx=i: self._pt_on_palette_color_clicked(idx)
            )
            row = i // _PALETTE_GRID_COLS
            col = i % _PALETTE_GRID_COLS
            self._pt_color_grid_layout.addWidget(btn, row, col)
            self._pt_palette_color_buttons.append(btn)

            # BG grid button
            if hasattr(self, "_pt_bg_color_grid_layout"):
                bg_btn = QPushButton()
                bg_btn.setFixedSize(36, 36)
                bg_btn.setToolTip(pc.name)
                self._pt_style_palette_btn(bg_btn, pc.color, selected=False)
                bg_btn.clicked.connect(
                    lambda checked, idx=i: self._pt_on_bg_palette_color_clicked(idx)
                )
                self._pt_bg_color_grid_layout.addWidget(bg_btn, row, col)
                self._pt_bg_palette_color_buttons.append(bg_btn)

    def _pt_on_palette_color_clicked(self, idx: int) -> None:
        if not self._pt_current_palette or idx >= len(self._pt_current_palette.colors):
            return

        # Deselect previous
        if 0 <= self._pt_selected_palette_idx < len(self._pt_palette_color_buttons):
            old_pc = self._pt_current_palette.colors[self._pt_selected_palette_idx]
            self._pt_style_palette_btn(
                self._pt_palette_color_buttons[self._pt_selected_palette_idx],
                old_pc.color, selected=False,
            )

        # Select new
        self._pt_selected_palette_idx = idx
        pc = self._pt_current_palette.colors[idx]
        self._pt_style_palette_btn(
            self._pt_palette_color_buttons[idx], pc.color, selected=True,
        )

        # Set path color
        color = QColor(pc.color)
        self._path_tool.color = color.name()
        update_color_btn(self._pt_color_btn, color)
        self._apply_to_selected(color=color.name())

    def _pt_on_bg_palette_color_clicked(self, idx: int) -> None:
        if not self._pt_current_palette or idx >= len(self._pt_current_palette.colors):
            return

        # Deselect previous BG selection
        if 0 <= self._pt_bg_selected_palette_idx < len(self._pt_bg_palette_color_buttons):
            old_pc = self._pt_current_palette.colors[self._pt_bg_selected_palette_idx]
            self._pt_style_palette_btn(
                self._pt_bg_palette_color_buttons[self._pt_bg_selected_palette_idx],
                old_pc.color, selected=False,
            )

        # Select new
        self._pt_bg_selected_palette_idx = idx
        pc = self._pt_current_palette.colors[idx]
        self._pt_style_palette_btn(
            self._pt_bg_palette_color_buttons[idx], pc.color, selected=True,
        )

        # Set background path color
        color = QColor(pc.color)
        self._path_tool.bg_color = color.name()
        update_color_btn(self._pt_bg_color_btn, color)
        self._apply_to_selected(bg_color=color.name())

    def _pt_style_palette_btn(self, btn: QPushButton, color_hex: str, selected: bool) -> None:
        border = "2px solid #00aaff" if selected else "1px solid #555"
        btn.setStyleSheet(
            f"background-color: {color_hex}; border: {border};"
        )

    # --- Preset sidebar ---

    def _pp_on_toggle_sidebar(self, checked: bool) -> None:
        if checked:
            self.dock._save_panel_width()
            if not self._pp_preset_sidebar:
                self._pp_preset_sidebar = PathPresetSidebar(self.dock.window())
                self._pp_preset_sidebar.preset_clicked.connect(
                    self._pp_on_sidebar_preset_clicked,
                )
                self._pp_preset_sidebar.closed.connect(
                    self._pp_on_preset_sidebar_closed,
                )
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea,
                    self._pp_preset_sidebar,
                )
                main_win.splitDockWidget(
                    self.dock, self._pp_preset_sidebar, Qt.Orientation.Horizontal,
                )
            self._pp_preset_sidebar.show()
            self._pp_sync_sidebar()
        else:
            if self._pp_preset_sidebar:
                self._pp_preset_sidebar.hide()
            self.dock._restore_panel_width()

    def _pp_sync_sidebar(self) -> None:
        if not self._pp_preset_sidebar or not self._pp_preset_sidebar.isVisible():
            return
        names = list_path_presets()
        selected = self._pp_combo.currentText() or None
        self._pp_preset_sidebar.set_presets(names, selected)

    def _pp_on_sidebar_preset_clicked(self, name: str) -> None:
        idx = self._pp_combo.findText(name)
        if idx >= 0:
            self._pp_combo.setCurrentIndex(idx)
        self._pp_on_load()
        if self._pp_preset_sidebar:
            self._pp_preset_sidebar.set_selected(name)

    def _pp_on_preset_sidebar_closed(self) -> None:
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_pp_expand_btn"):
                self._pp_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Presets ---

    def _pp_refresh_combo(self) -> None:
        self._pp_combo.blockSignals(True)
        current = self._pp_combo.currentText()
        self._pp_combo.clear()
        names = list_path_presets()
        self._pp_combo.addItems(names)
        idx = self._pp_combo.findText(current)
        if idx >= 0:
            self._pp_combo.setCurrentIndex(idx)
        elif names:
            self._pp_combo.setCurrentIndex(0)
        self._pp_combo.blockSignals(False)

    def _pp_on_selected(self, name: str) -> None:
        self._pp_update_preview()
        if name:
            self._pp_on_load()

    def _pp_update_preview(self) -> None:
        name = self._pp_combo.currentText()
        if name:
            try:
                preset = load_path_preset(name)
            except (FileNotFoundError, Exception):
                preset = self._pp_current_as_preset()
        else:
            preset = self._pp_current_as_preset()
        self._pp_render_preview(preset)

    def _pp_current_as_preset(self) -> PathPreset:
        tool = self._path_tool
        return PathPreset(
            name="(current)",
            color=tool.color,
            width=tool.width,
            line_type=tool.line_type,
            dash_length=tool.dash_length,
            gap_length=tool.gap_length,
            dash_cap=tool.dash_cap,
            texture_id=tool.texture_id,
            texture_zoom=tool.texture_zoom,
            texture_rotation=tool.texture_rotation,
            bg_enabled=tool.bg_enabled,
            bg_color=tool.bg_color,
            bg_width=tool.bg_width,
            bg_line_type=tool.bg_line_type,
            bg_dash_length=tool.bg_dash_length,
            bg_gap_length=tool.bg_gap_length,
            bg_dash_cap=tool.bg_dash_cap,
            bg_texture_id=tool.bg_texture_id,
            bg_texture_zoom=tool.bg_texture_zoom,
            bg_texture_rotation=tool.bg_texture_rotation,
            opacity=tool.opacity,
            bg_opacity=tool.bg_opacity,
            random=tool.random,
            random_amplitude=tool.random_amplitude,
            random_distance=tool.random_distance,
            random_endpoint=tool.random_endpoint,
            random_offset=tool.random_offset,
            random_jitter=tool.random_jitter,
        )

    def _pp_render_preview(self, preset: PathPreset) -> None:
        w = max(self._pp_preview.width(), 200)
        h = max(self._pp_preview.height(), 40)
        self._pp_preview.setPixmap(render_path_preview(preset, w, h))

    def _pp_on_load(self) -> None:
        name = self._pp_combo.currentText()
        if not name:
            return
        try:
            preset = load_path_preset(name)
        except FileNotFoundError:
            QMessageBox.warning(self.dock, "Preset Not Found", f"Preset '{name}' not found.")
            self._pp_refresh_combo()
            return

        tool = self._path_tool

        # Apply all settings to tool
        tool.color = preset.color
        tool.width = preset.width
        tool.line_type = preset.line_type
        tool.dash_length = preset.dash_length
        tool.gap_length = preset.gap_length
        tool.dash_cap = preset.dash_cap
        tool.texture_id = preset.texture_id
        tool.texture_zoom = preset.texture_zoom
        tool.texture_rotation = preset.texture_rotation
        tool.bg_enabled = preset.bg_enabled
        tool.bg_color = preset.bg_color
        tool.bg_width = preset.bg_width
        tool.bg_line_type = preset.bg_line_type
        tool.bg_dash_length = preset.bg_dash_length
        tool.bg_gap_length = preset.bg_gap_length
        tool.bg_dash_cap = preset.bg_dash_cap
        tool.bg_texture_id = preset.bg_texture_id
        tool.bg_texture_zoom = preset.bg_texture_zoom
        tool.bg_texture_rotation = preset.bg_texture_rotation
        tool.opacity = preset.opacity
        tool.bg_opacity = preset.bg_opacity
        tool.random = preset.random
        tool.random_amplitude = preset.random_amplitude
        tool.random_distance = preset.random_distance
        tool.random_endpoint = preset.random_endpoint
        tool.random_offset = preset.random_offset
        tool.random_jitter = preset.random_jitter

        # Sync UI widgets
        update_color_btn(self._pt_color_btn, QColor(preset.color))

        self._pt_width_slider.blockSignals(True)
        self._pt_width_slider.setValue(int(preset.width * 2))
        self._pt_width_slider.blockSignals(False)
        self._pt_width_spin.blockSignals(True)
        self._pt_width_spin.setValue(preset.width)
        self._pt_width_spin.blockSignals(False)

        self._pt_line_type_combo.blockSignals(True)
        self._pt_line_type_combo.setCurrentText(
            _LINE_TYPE_REVERSE.get(preset.line_type, "Solid")
        )
        self._pt_line_type_combo.blockSignals(False)
        self._pt_dash_container.setEnabled(preset.line_type != "solid")

        self._pt_dash_slider.blockSignals(True)
        self._pt_dash_slider.setValue(max(1, round(preset.dash_length * 10)))
        self._pt_dash_slider.blockSignals(False)
        self._pt_dash_spin.blockSignals(True)
        self._pt_dash_spin.setValue(preset.dash_length)
        self._pt_dash_spin.blockSignals(False)

        self._pt_gap_slider.blockSignals(True)
        self._pt_gap_slider.setValue(max(1, round(preset.gap_length * 10)))
        self._pt_gap_slider.blockSignals(False)
        self._pt_gap_spin.blockSignals(True)
        self._pt_gap_spin.setValue(preset.gap_length)
        self._pt_gap_spin.blockSignals(False)

        self._pt_cap_combo.blockSignals(True)
        self._pt_cap_combo.setCurrentText(
            _CAP_REVERSE.get(preset.dash_cap, "Flat")
        )
        self._pt_cap_combo.blockSignals(False)

        # Texture / Color mode
        is_texture = bool(preset.texture_id)
        pm_id = 1 if is_texture else 0
        self._pt_paint_mode_group.blockSignals(True)
        btn = self._pt_paint_mode_group.button(pm_id)
        if btn:
            btn.setChecked(True)
        self._pt_paint_mode_group.blockSignals(False)
        self._pt_color_group.setVisible(not is_texture)
        self._pt_texture_group.setVisible(is_texture)

        if is_texture:
            self._pt_tex_zoom_slider.blockSignals(True)
            self._pt_tex_zoom_slider.setValue(int(preset.texture_zoom * 10))
            self._pt_tex_zoom_slider.blockSignals(False)
            self._pt_tex_zoom_spin.blockSignals(True)
            self._pt_tex_zoom_spin.setValue(preset.texture_zoom)
            self._pt_tex_zoom_spin.blockSignals(False)

            self._pt_tex_rotation_slider.blockSignals(True)
            self._pt_tex_rotation_slider.setValue(int(preset.texture_rotation))
            self._pt_tex_rotation_slider.blockSignals(False)
            self._pt_tex_rotation_spin.blockSignals(True)
            self._pt_tex_rotation_spin.setValue(int(preset.texture_rotation))
            self._pt_tex_rotation_spin.blockSignals(False)
            self._sync_pt_tex_rot_buttons(int(preset.texture_rotation))

        # Background path
        self._pt_bg_cb.blockSignals(True)
        self._pt_bg_cb.setChecked(preset.bg_enabled)
        self._pt_bg_cb.blockSignals(False)
        self._pt_bg_container.setEnabled(preset.bg_enabled)

        update_color_btn(self._pt_bg_color_btn, QColor(preset.bg_color))

        self._pt_bg_width_slider.blockSignals(True)
        self._pt_bg_width_slider.setValue(int(preset.bg_width * 2))
        self._pt_bg_width_slider.blockSignals(False)
        self._pt_bg_width_spin.blockSignals(True)
        self._pt_bg_width_spin.setValue(preset.bg_width)
        self._pt_bg_width_spin.blockSignals(False)

        self._pt_bg_line_type_combo.blockSignals(True)
        self._pt_bg_line_type_combo.setCurrentText(
            _LINE_TYPE_REVERSE.get(preset.bg_line_type, "Solid")
        )
        self._pt_bg_line_type_combo.blockSignals(False)
        self._pt_bg_dash_container.setEnabled(preset.bg_line_type != "solid")

        self._pt_bg_dash_slider.blockSignals(True)
        self._pt_bg_dash_slider.setValue(max(1, round(preset.bg_dash_length * 10)))
        self._pt_bg_dash_slider.blockSignals(False)
        self._pt_bg_dash_spin.blockSignals(True)
        self._pt_bg_dash_spin.setValue(preset.bg_dash_length)
        self._pt_bg_dash_spin.blockSignals(False)

        self._pt_bg_gap_slider.blockSignals(True)
        self._pt_bg_gap_slider.setValue(max(1, round(preset.bg_gap_length * 10)))
        self._pt_bg_gap_slider.blockSignals(False)
        self._pt_bg_gap_spin.blockSignals(True)
        self._pt_bg_gap_spin.setValue(preset.bg_gap_length)
        self._pt_bg_gap_spin.blockSignals(False)

        self._pt_bg_cap_combo.blockSignals(True)
        self._pt_bg_cap_combo.setCurrentText(_CAP_REVERSE.get(preset.bg_dash_cap, "Flat"))
        self._pt_bg_cap_combo.blockSignals(False)

        # BG Texture (preset)
        is_bg_tex = bool(preset.bg_texture_id)
        self._pt_bg_paint_mode_group.blockSignals(True)
        self._pt_bg_paint_mode_group.button(1 if is_bg_tex else 0).setChecked(True)
        self._pt_bg_paint_mode_group.blockSignals(False)
        self._pt_bg_color_section.setVisible(not is_bg_tex)
        self._pt_bg_texture_section.setVisible(is_bg_tex)
        if is_bg_tex:
            self._pt_bg_tex_zoom_slider.blockSignals(True)
            self._pt_bg_tex_zoom_slider.setValue(int(preset.bg_texture_zoom * 10))
            self._pt_bg_tex_zoom_slider.blockSignals(False)
            self._pt_bg_tex_zoom_spin.blockSignals(True)
            self._pt_bg_tex_zoom_spin.setValue(preset.bg_texture_zoom)
            self._pt_bg_tex_zoom_spin.blockSignals(False)
            self._pt_bg_tex_rotation_slider.blockSignals(True)
            self._pt_bg_tex_rotation_slider.setValue(int(preset.bg_texture_rotation))
            self._pt_bg_tex_rotation_slider.blockSignals(False)
            self._pt_bg_tex_rotation_spin.blockSignals(True)
            self._pt_bg_tex_rotation_spin.setValue(int(preset.bg_texture_rotation))
            self._pt_bg_tex_rotation_spin.blockSignals(False)
            for btn in self._pt_bg_tex_rot_buttons:
                btn.setChecked(int(btn.text()) == int(preset.bg_texture_rotation))

        # Random
        self._pt_random_cb.blockSignals(True)
        self._pt_random_cb.setChecked(preset.random)
        self._pt_random_cb.blockSignals(False)
        self._pt_random_container.setEnabled(preset.random)

        self._pt_amp_slider.blockSignals(True)
        self._pt_amp_slider.setValue(round(preset.random_amplitude / 0.5))
        self._pt_amp_slider.blockSignals(False)
        self._pt_amp_spin.blockSignals(True)
        self._pt_amp_spin.setValue(preset.random_amplitude)
        self._pt_amp_spin.blockSignals(False)

        self._pt_dist_slider.blockSignals(True)
        self._pt_dist_slider.setValue(int(preset.random_distance * 100))
        self._pt_dist_slider.blockSignals(False)
        self._pt_dist_spin.blockSignals(True)
        self._pt_dist_spin.setValue(preset.random_distance)
        self._pt_dist_spin.blockSignals(False)

        self._pt_endpoint_slider.blockSignals(True)
        self._pt_endpoint_slider.setValue(int(preset.random_endpoint * 10))
        self._pt_endpoint_slider.blockSignals(False)
        self._pt_endpoint_spin.blockSignals(True)
        self._pt_endpoint_spin.setValue(preset.random_endpoint)
        self._pt_endpoint_spin.blockSignals(False)

        self._pt_offset_slider.blockSignals(True)
        self._pt_offset_slider.setValue(round(preset.random_offset / 0.5))
        self._pt_offset_slider.blockSignals(False)
        self._pt_offset_spin.blockSignals(True)
        self._pt_offset_spin.setValue(preset.random_offset)
        self._pt_offset_spin.blockSignals(False)

        self._pt_jitter_slider.blockSignals(True)
        self._pt_jitter_slider.setValue(round(preset.random_jitter * 10))
        self._pt_jitter_slider.blockSignals(False)
        self._pt_jitter_spin.blockSignals(True)
        self._pt_jitter_spin.setValue(preset.random_jitter)
        self._pt_jitter_spin.blockSignals(False)

        self._pt_opacity_slider.blockSignals(True)
        self._pt_opacity_slider.setValue(round(preset.opacity * 100))
        self._pt_opacity_slider.blockSignals(False)
        self._pt_opacity_spin.blockSignals(True)
        self._pt_opacity_spin.setValue(round(preset.opacity * 100))
        self._pt_opacity_spin.blockSignals(False)

        self._pt_bg_opacity_slider.blockSignals(True)
        self._pt_bg_opacity_slider.setValue(round(preset.bg_opacity * 100))
        self._pt_bg_opacity_slider.blockSignals(False)
        self._pt_bg_opacity_spin.blockSignals(True)
        self._pt_bg_opacity_spin.setValue(round(preset.bg_opacity * 100))
        self._pt_bg_opacity_spin.blockSignals(False)

        self._pp_update_preview()

    def _pp_on_save(self) -> None:
        name, ok = QInputDialog.getText(
            self.dock, "Save Path Preset", "Preset name:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        existing = list_path_presets()
        if name in existing:
            reply = QMessageBox.question(
                self.dock, "Overwrite Preset",
                f"Preset '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        preset = self._pp_current_as_preset()
        preset.name = name
        save_path_preset(preset)
        self._pp_refresh_combo()
        idx = self._pp_combo.findText(name)
        if idx >= 0:
            self._pp_combo.setCurrentIndex(idx)
        self._pp_update_preview()
        self._pp_sync_sidebar()

    def _pp_on_delete(self) -> None:
        name = self._pp_combo.currentText()
        if not name:
            return
        if is_builtin_path_preset(name):
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
        delete_path_preset(name)
        self._pp_refresh_combo()
        self._pp_update_preview()
        self._pp_sync_sidebar()

    # --- Layer-level effects ---

    def _get_layer(self):
        if self._path_tool is None:
            return None
        return self._path_tool._get_active_path_layer()

    def _apply_layer_effect(self, **changes) -> None:
        from app.commands.path_commands import EditPathLayerEffectsCommand
        layer = self._get_layer()
        if layer is None:
            return
        cmd = EditPathLayerEffectsCommand(layer, **changes)
        self._path_tool._command_stack.execute(cmd)

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
