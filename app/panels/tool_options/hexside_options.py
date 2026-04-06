"""Hexside tool options builder."""

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

from app.commands.hexside_commands import EditHexsideCommand, EditHexsideLayerEffectsCommand
from app.io.hexside_preset_manager import (
    HexsidePreset,
    delete_hexside_preset,
    is_builtin_hexside_preset,
    list_hexside_presets,
    load_hexside_preset,
    save_hexside_preset,
)
from app.io.palette_manager import (
    ColorPalette,
    ensure_default_palette,
    list_palettes,
    load_palette,
)
from app.io.texture_library import (
    LibraryTexture,
    TextureCatalog,
    load_catalog as load_texture_catalog,
)
from app.panels.tool_options.helpers import update_color_btn
from app.panels.tool_options.sidebar_widgets import (
    HexsidePresetSidebar,
    TextureBrowserSidebar,
    render_hexside_preview,
)
from app.panels.texture_manager_dialog import TextureManagerDialog
from app.tools.hexside_tool import HexsideTool

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel

# Maximum columns for the color grid
_PALETTE_GRID_COLS = 4


class HexsideOptions:
    """Builds and manages the hexside tool options UI."""

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._hexside_tool: HexsideTool | None = None
        self._hst_texture_sidebar: TextureBrowserSidebar | None = None
        self._hsp_preset_sidebar: HexsidePresetSidebar | None = None
        self._hs_ol_texture_sidebar: TextureBrowserSidebar | None = None
        self._selected_ol_browser_texture: LibraryTexture | None = None
        self._ol_texture_browser_buttons: dict[str, QToolButton] = {}

    def create(self, tool: HexsideTool) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        self._hexside_tool = tool
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

        self._hs_mode_group = QButtonGroup(widget)
        self._hs_mode_group.setExclusive(True)
        self._hs_mode_group.addButton(place_btn, 0)
        self._hs_mode_group.addButton(select_btn, 1)
        self._hs_mode_group.idToggled.connect(self._on_hs_mode_changed)

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
        self._hsp_preview = QLabel()
        self._hsp_preview.setFixedHeight(40)
        self._hsp_preview.setScaledContents(False)
        from PySide6.QtWidgets import QSizePolicy
        self._hsp_preview.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed,
        )
        self._hsp_preview.setStyleSheet(
            "background-color: #d0d0d0; border: 1px solid #999; padding: 2px;"
        )
        self._hsp_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preset_gl.addWidget(self._hsp_preview)

        # Combo
        combo_layout = QHBoxLayout()
        self._hsp_combo = QComboBox()
        self._hsp_combo.setMinimumWidth(60)
        self._hsp_combo.currentTextChanged.connect(self._hsp_on_selected)
        combo_layout.addWidget(self._hsp_combo, stretch=1)
        preset_gl.addLayout(combo_layout)

        # Expand button (own row, above action buttons)
        self._hsp_expand_btn = QPushButton("Expand")
        self._hsp_expand_btn.setCheckable(True)
        self._hsp_expand_btn.setToolTip("Show all presets in expanded sidebar")
        self._hsp_expand_btn.clicked.connect(self._hsp_on_toggle_sidebar)
        preset_gl.addWidget(self._hsp_expand_btn)

        # Buttons
        btn_layout = QHBoxLayout()
        load_btn = QPushButton("Load")
        load_btn.setToolTip("Apply selected preset to current settings")
        load_btn.clicked.connect(self._hsp_on_load)
        btn_layout.addWidget(load_btn)

        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save current settings as a new preset")
        save_btn.clicked.connect(self._hsp_on_save)
        btn_layout.addWidget(save_btn)

        del_btn = QPushButton("Del")
        del_btn.setToolTip("Delete selected preset")
        del_btn.clicked.connect(self._hsp_on_delete)
        btn_layout.addWidget(del_btn)
        preset_gl.addLayout(btn_layout)

        layout.addWidget(preset_group)

        # Populate preset combo
        self._hsp_refresh_combo()
        self._hsp_update_preview()

        # ===== Hexside section =====
        main_group = QGroupBox("Hexside")
        main_gl = QVBoxLayout(main_group)
        main_gl.setContentsMargins(6, 4, 6, 4)

        # ===== Paint mode selector =====
        paint_mode_group = QGroupBox("Paint Mode")
        pm_gl = QVBoxLayout(paint_mode_group)
        pm_gl.setContentsMargins(6, 4, 6, 4)
        pm_btn_layout = QHBoxLayout()

        pm_color_btn = QPushButton("Color")
        pm_color_btn.setCheckable(True)
        pm_color_btn.setChecked(True)
        pm_texture_btn = QPushButton("Texture")
        pm_texture_btn.setCheckable(True)

        self._hs_paint_mode_group = QButtonGroup(widget)
        self._hs_paint_mode_group.setExclusive(True)
        self._hs_paint_mode_group.addButton(pm_color_btn, 0)
        self._hs_paint_mode_group.addButton(pm_texture_btn, 1)
        self._hs_paint_mode_group.idToggled.connect(self._on_hs_paint_mode_changed)

        pm_btn_layout.addWidget(pm_color_btn)
        pm_btn_layout.addWidget(pm_texture_btn)
        pm_btn_layout.addStretch()
        pm_gl.addLayout(pm_btn_layout)
        main_gl.addWidget(paint_mode_group)

        # ===== Color group (with palette) =====
        self._hs_selected_palette_idx = -1
        self._hs_current_palette: ColorPalette | None = None
        self._hs_palette_color_buttons: list[QPushButton] = []

        self._hs_color_group = QGroupBox("Color")
        color_gl = QVBoxLayout(self._hs_color_group)
        color_gl.setContentsMargins(6, 4, 6, 4)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._hs_color_btn = QPushButton()
        self._hs_color_btn.setFixedSize(40, 25)
        update_color_btn(self._hs_color_btn, QColor(tool.color))
        self._hs_color_btn.clicked.connect(self._on_hs_color_pick)
        color_row.addWidget(self._hs_color_btn)
        color_row.addStretch()
        color_gl.addLayout(color_row)

        # --- Palette section ---
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        color_gl.addWidget(separator)

        self._hs_palette_combo = QComboBox()
        color_gl.addWidget(self._hs_palette_combo)

        self._hs_color_grid_widget = QWidget()
        self._hs_color_grid_layout = QGridLayout(self._hs_color_grid_widget)
        self._hs_color_grid_layout.setSpacing(3)
        self._hs_color_grid_layout.setContentsMargins(0, 0, 0, 0)
        color_gl.addWidget(self._hs_color_grid_widget)

        main_gl.addWidget(self._hs_color_group)

        # ===== Texture group =====
        self._hst_texture_catalog: TextureCatalog = load_texture_catalog()
        self._hst_thumb_cache: dict[str, QPixmap] = {}
        self._hst_browser_buttons: dict[str, QToolButton] = {}
        self._hst_selected_texture: LibraryTexture | None = None

        self._hs_texture_group = QGroupBox("Texture")
        tex_gl = QVBoxLayout(self._hs_texture_group)
        tex_gl.setContentsMargins(6, 4, 6, 4)

        # Game filter
        hst_game_layout = QHBoxLayout()
        hst_game_layout.addWidget(QLabel("Game:"))
        self._hst_game_combo = QComboBox()
        self._hst_game_combo.setMinimumWidth(80)
        self._hst_game_combo.currentTextChanged.connect(self._hst_on_filter_changed)
        hst_game_layout.addWidget(self._hst_game_combo, stretch=1)
        tex_gl.addLayout(hst_game_layout)

        # Category filter
        hst_cat_layout = QHBoxLayout()
        hst_cat_layout.addWidget(QLabel("Category:"))
        self._hst_category_combo = QComboBox()
        self._hst_category_combo.setMinimumWidth(80)
        self._hst_category_combo.currentTextChanged.connect(self._hst_on_filter_changed)
        hst_cat_layout.addWidget(self._hst_category_combo, stretch=1)
        tex_gl.addLayout(hst_cat_layout)

        # Search
        hst_search_layout = QHBoxLayout()
        hst_search_layout.addWidget(QLabel("Search:"))
        self._hst_search_edit = QLineEdit()
        self._hst_search_edit.setPlaceholderText("Filter by name...")
        self._hst_search_edit.textChanged.connect(self._hst_on_filter_changed)
        hst_search_layout.addWidget(self._hst_search_edit, stretch=1)
        tex_gl.addLayout(hst_search_layout)

        # Thumbnail grid
        hst_scroll = QScrollArea()
        hst_scroll.setWidgetResizable(True)
        hst_scroll.setMinimumHeight(80)
        hst_scroll.setMaximumHeight(200)
        self._hst_grid_container = QWidget()
        self._hst_grid_layout = QGridLayout(self._hst_grid_container)
        self._hst_grid_layout.setSpacing(4)
        self._hst_grid_layout.setContentsMargins(2, 2, 2, 2)
        hst_scroll.setWidget(self._hst_grid_container)
        tex_gl.addWidget(hst_scroll)

        # Manager + Expand buttons
        hst_btn_layout = QHBoxLayout()
        hst_manager_btn = QPushButton("Manager...")
        hst_manager_btn.clicked.connect(self._hst_on_open_manager)
        hst_btn_layout.addWidget(hst_manager_btn)
        self._hst_expand_btn = QPushButton("Expand")
        self._hst_expand_btn.setCheckable(True)
        self._hst_expand_btn.clicked.connect(self._hst_on_toggle_sidebar)
        hst_btn_layout.addWidget(self._hst_expand_btn)
        tex_gl.addLayout(hst_btn_layout)

        # Separator before transform controls
        hst_sep = QFrame()
        hst_sep.setFrameShape(QFrame.Shape.HLine)
        hst_sep.setFrameShadow(QFrame.Shadow.Sunken)
        tex_gl.addWidget(hst_sep)

        # Zoom
        tex_gl.addWidget(QLabel("Zoom:"))
        hst_zoom_row = QHBoxLayout()
        self._hst_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._hst_zoom_slider.setRange(1, 100)  # 0.1-10.0
        self._hst_zoom_slider.setValue(int(tool.texture_zoom * 10))
        self._hst_zoom_slider.valueChanged.connect(self._on_hst_zoom_slider)
        hst_zoom_row.addWidget(self._hst_zoom_slider, stretch=1)
        self._hst_zoom_spin = QDoubleSpinBox()
        self._hst_zoom_spin.setRange(0.1, 10.0)
        self._hst_zoom_spin.setSingleStep(0.1)
        self._hst_zoom_spin.setDecimals(2)
        self._hst_zoom_spin.setSuffix("x")
        self._hst_zoom_spin.setValue(tool.texture_zoom)
        self._hst_zoom_spin.setFixedWidth(70)
        self._hst_zoom_spin.valueChanged.connect(self._on_hst_zoom_spin)
        hst_zoom_row.addWidget(self._hst_zoom_spin)
        tex_gl.addLayout(hst_zoom_row)

        # Rotation
        tex_gl.addWidget(QLabel("Rotation:"))
        hst_rot_row = QHBoxLayout()
        self._hst_rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self._hst_rotation_slider.setRange(0, 359)
        self._hst_rotation_slider.setValue(int(tool.texture_rotation))
        self._hst_rotation_slider.valueChanged.connect(self._on_hst_rot_slider)
        hst_rot_row.addWidget(self._hst_rotation_slider, stretch=1)
        self._hst_rotation_spin = QSpinBox()
        self._hst_rotation_spin.setRange(0, 359)
        self._hst_rotation_spin.setSuffix("\u00b0")
        self._hst_rotation_spin.setWrapping(True)
        self._hst_rotation_spin.setValue(int(tool.texture_rotation))
        self._hst_rotation_spin.setFixedWidth(60)
        self._hst_rotation_spin.valueChanged.connect(self._on_hst_rot_spin)
        hst_rot_row.addWidget(self._hst_rotation_spin)
        tex_gl.addLayout(hst_rot_row)

        # Rotation preset buttons
        self._hst_rot_buttons: list[QPushButton] = []
        hst_rot_btn_layout = QHBoxLayout()
        hst_rot_btn_layout.setSpacing(2)
        for deg in (0, 60, 90, 120, 180, 270):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(32)
            btn.setChecked(deg == int(tool.texture_rotation))
            btn.clicked.connect(
                lambda _, d=deg: self._on_hst_rot_preset(d)
            )
            hst_rot_btn_layout.addWidget(btn)
            self._hst_rot_buttons.append(btn)
        hst_rot_btn_layout.addStretch()
        tex_gl.addLayout(hst_rot_btn_layout)

        # Set initial visibility based on tool paint mode
        _hs_init_texture = getattr(tool, 'paint_mode', 'color') == 'texture'
        self._hs_color_group.setVisible(not _hs_init_texture)
        self._hs_texture_group.setVisible(_hs_init_texture)
        main_gl.addWidget(self._hs_texture_group)

        # Width
        main_gl.addWidget(QLabel("Width:"))
        width_row = QHBoxLayout()
        self._hs_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_width_slider.setRange(1, 80)  # 0.5-40.0 in 0.5 steps
        self._hs_width_slider.setValue(int(tool.width * 2))
        self._hs_width_slider.valueChanged.connect(self._on_hs_width_slider)
        width_row.addWidget(self._hs_width_slider, stretch=1)
        self._hs_width_spin = QDoubleSpinBox()
        self._hs_width_spin.setRange(0.5, 40.0)
        self._hs_width_spin.setSingleStep(0.5)
        self._hs_width_spin.setValue(tool.width)
        self._hs_width_spin.setFixedWidth(65)
        self._hs_width_spin.valueChanged.connect(self._on_hs_width_spin)
        width_row.addWidget(self._hs_width_spin)
        main_gl.addLayout(width_row)

        # Opacity
        main_gl.addWidget(QLabel("Opacity:"))
        hs_opacity_row = QHBoxLayout()
        self._hs_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_opacity_slider.setRange(0, 100)
        self._hs_opacity_slider.setValue(round(tool.opacity * 100))
        self._hs_opacity_slider.valueChanged.connect(self._on_hs_opacity_slider)
        hs_opacity_row.addWidget(self._hs_opacity_slider, stretch=1)
        self._hs_opacity_spin = QSpinBox()
        self._hs_opacity_spin.setRange(0, 100)
        self._hs_opacity_spin.setSuffix("%")
        self._hs_opacity_spin.setValue(round(tool.opacity * 100))
        self._hs_opacity_spin.setFixedWidth(60)
        self._hs_opacity_spin.valueChanged.connect(self._on_hs_opacity_spin)
        hs_opacity_row.addWidget(self._hs_opacity_spin)
        main_gl.addLayout(hs_opacity_row)
        layout.addWidget(main_group)

        # ===== Outline group =====
        self._hs_ol_selected_palette_idx = -1
        self._hs_ol_current_palette: ColorPalette | None = None
        self._hs_ol_palette_color_buttons: list[QPushButton] = []

        outline_group = QGroupBox("Outline")
        outline_gl = QVBoxLayout(outline_group)
        outline_gl.setContentsMargins(6, 4, 6, 4)

        self._hs_outline_cb = QCheckBox("Enable Outline")
        self._hs_outline_cb.setChecked(tool.outline)
        self._hs_outline_cb.toggled.connect(self._on_hs_outline_toggled)
        outline_gl.addWidget(self._hs_outline_cb)

        self._hs_ol_container = QWidget()
        ol_c_layout = QVBoxLayout(self._hs_ol_container)
        ol_c_layout.setContentsMargins(0, 0, 0, 0)

        # --- Outline Paint Mode (Color | Texture) ---
        is_ol_texture = bool(tool.outline_texture_id)
        ol_pm_group = QGroupBox("Paint Mode")
        ol_pm_gl = QVBoxLayout(ol_pm_group)
        ol_pm_gl.setContentsMargins(6, 4, 6, 4)
        ol_pm_btn_layout = QHBoxLayout()
        ol_pm_color_btn = QPushButton("Color")
        ol_pm_color_btn.setCheckable(True)
        ol_pm_color_btn.setChecked(not is_ol_texture)
        ol_pm_texture_btn = QPushButton("Texture")
        ol_pm_texture_btn.setCheckable(True)
        ol_pm_texture_btn.setChecked(is_ol_texture)
        self._hs_ol_paint_mode_group = QButtonGroup(widget)
        self._hs_ol_paint_mode_group.setExclusive(True)
        self._hs_ol_paint_mode_group.addButton(ol_pm_color_btn, 0)
        self._hs_ol_paint_mode_group.addButton(ol_pm_texture_btn, 1)
        self._hs_ol_paint_mode_group.idToggled.connect(self._on_ol_paint_mode_changed)
        ol_pm_btn_layout.addWidget(ol_pm_color_btn)
        ol_pm_btn_layout.addWidget(ol_pm_texture_btn)
        ol_pm_btn_layout.addStretch()
        ol_pm_gl.addLayout(ol_pm_btn_layout)
        ol_c_layout.addWidget(ol_pm_group)

        # --- Outline Color section ---
        self._hs_ol_color_section = QGroupBox("Color")
        ol_color_sec_layout = QVBoxLayout(self._hs_ol_color_section)
        ol_color_sec_layout.setContentsMargins(6, 4, 6, 4)

        ol_row = QHBoxLayout()
        ol_row.addWidget(QLabel("Color:"))
        self._hs_ol_color_btn = QPushButton()
        self._hs_ol_color_btn.setFixedSize(40, 25)
        update_color_btn(self._hs_ol_color_btn, QColor(tool.outline_color))
        self._hs_ol_color_btn.clicked.connect(self._on_hs_outline_color_pick)
        ol_row.addWidget(self._hs_ol_color_btn)
        ol_row.addStretch()
        ol_color_sec_layout.addLayout(ol_row)

        ol_pal_sep = QFrame()
        ol_pal_sep.setFrameShape(QFrame.Shape.HLine)
        ol_pal_sep.setFrameShadow(QFrame.Shadow.Sunken)
        ol_color_sec_layout.addWidget(ol_pal_sep)

        self._hs_ol_palette_combo = QComboBox()
        ol_color_sec_layout.addWidget(self._hs_ol_palette_combo)

        self._hs_ol_color_grid_widget = QWidget()
        self._hs_ol_color_grid_layout = QGridLayout(self._hs_ol_color_grid_widget)
        self._hs_ol_color_grid_layout.setSpacing(3)
        self._hs_ol_color_grid_layout.setContentsMargins(0, 0, 0, 0)
        ol_color_sec_layout.addWidget(self._hs_ol_color_grid_widget)

        ol_c_layout.addWidget(self._hs_ol_color_section)
        self._hs_ol_color_section.setVisible(not is_ol_texture)

        # --- Outline Texture section ---
        self._hs_ol_texture_section = QGroupBox("Texture")
        ol_tex_sec_layout = QVBoxLayout(self._hs_ol_texture_section)
        ol_tex_sec_layout.setContentsMargins(6, 4, 6, 4)

        ol_tex_game_row = QHBoxLayout()
        ol_tex_game_row.addWidget(QLabel("Game:"))
        self._hs_ol_tex_game_combo = QComboBox()
        self._hs_ol_tex_game_combo.setMinimumWidth(80)
        self._hs_ol_tex_game_combo.currentTextChanged.connect(self._on_ol_tex_filter_changed)
        ol_tex_game_row.addWidget(self._hs_ol_tex_game_combo, stretch=1)
        ol_tex_sec_layout.addLayout(ol_tex_game_row)

        ol_tex_cat_row = QHBoxLayout()
        ol_tex_cat_row.addWidget(QLabel("Category:"))
        self._hs_ol_tex_category_combo = QComboBox()
        self._hs_ol_tex_category_combo.setMinimumWidth(80)
        self._hs_ol_tex_category_combo.currentTextChanged.connect(self._on_ol_tex_filter_changed)
        ol_tex_cat_row.addWidget(self._hs_ol_tex_category_combo, stretch=1)
        ol_tex_sec_layout.addLayout(ol_tex_cat_row)

        ol_tex_search_row = QHBoxLayout()
        ol_tex_search_row.addWidget(QLabel("Search:"))
        self._hs_ol_tex_search_edit = QLineEdit()
        self._hs_ol_tex_search_edit.setPlaceholderText("Filter by name...")
        self._hs_ol_tex_search_edit.textChanged.connect(self._on_ol_tex_filter_changed)
        ol_tex_search_row.addWidget(self._hs_ol_tex_search_edit, stretch=1)
        ol_tex_sec_layout.addLayout(ol_tex_search_row)

        self._hs_ol_tex_scroll = QScrollArea()
        self._hs_ol_tex_scroll.setWidgetResizable(True)
        self._hs_ol_tex_scroll.setMinimumHeight(80)
        self._hs_ol_tex_scroll.setMaximumHeight(200)
        ol_tex_grid_container = QWidget()
        self._hs_ol_tex_grid_layout = QGridLayout(ol_tex_grid_container)
        self._hs_ol_tex_grid_layout.setSpacing(4)
        self._hs_ol_tex_grid_layout.setContentsMargins(2, 2, 2, 2)
        self._hs_ol_tex_scroll.setWidget(ol_tex_grid_container)
        ol_tex_sec_layout.addWidget(self._hs_ol_tex_scroll)

        ol_tex_btn_row = QHBoxLayout()
        ol_tex_mgr_btn = QPushButton("Manager...")
        ol_tex_mgr_btn.clicked.connect(self._hst_on_open_manager)
        ol_tex_btn_row.addWidget(ol_tex_mgr_btn)
        self._hs_ol_tex_expand_btn = QPushButton("Expand")
        self._hs_ol_tex_expand_btn.setCheckable(True)
        self._hs_ol_tex_expand_btn.clicked.connect(self._on_toggle_ol_texture_sidebar)
        ol_tex_btn_row.addWidget(self._hs_ol_tex_expand_btn)
        ol_tex_sec_layout.addLayout(ol_tex_btn_row)

        ol_tex_sep = QFrame()
        ol_tex_sep.setFrameShape(QFrame.Shape.HLine)
        ol_tex_sep.setFrameShadow(QFrame.Shadow.Sunken)
        ol_tex_sec_layout.addWidget(ol_tex_sep)

        ol_tex_sec_layout.addWidget(QLabel("Zoom:"))
        ol_tex_zoom_row = QHBoxLayout()
        self._hs_ol_tex_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_ol_tex_zoom_slider.setRange(1, 100)
        self._hs_ol_tex_zoom_slider.setValue(int(tool.outline_texture_zoom * 10))
        self._hs_ol_tex_zoom_slider.valueChanged.connect(self._on_hs_ol_tex_zoom_slider)
        ol_tex_zoom_row.addWidget(self._hs_ol_tex_zoom_slider, stretch=1)
        self._hs_ol_tex_zoom_spin = QDoubleSpinBox()
        self._hs_ol_tex_zoom_spin.setRange(0.1, 10.0)
        self._hs_ol_tex_zoom_spin.setSingleStep(0.1)
        self._hs_ol_tex_zoom_spin.setDecimals(2)
        self._hs_ol_tex_zoom_spin.setSuffix("x")
        self._hs_ol_tex_zoom_spin.setValue(tool.outline_texture_zoom)
        self._hs_ol_tex_zoom_spin.setFixedWidth(70)
        self._hs_ol_tex_zoom_spin.valueChanged.connect(self._on_hs_ol_tex_zoom_spin)
        ol_tex_zoom_row.addWidget(self._hs_ol_tex_zoom_spin)
        ol_tex_sec_layout.addLayout(ol_tex_zoom_row)

        ol_tex_sec_layout.addWidget(QLabel("Rotation:"))
        ol_tex_rot_row = QHBoxLayout()
        self._hs_ol_tex_rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_ol_tex_rotation_slider.setRange(0, 359)
        self._hs_ol_tex_rotation_slider.setValue(int(tool.outline_texture_rotation))
        self._hs_ol_tex_rotation_slider.valueChanged.connect(self._on_hs_ol_tex_rot_slider)
        ol_tex_rot_row.addWidget(self._hs_ol_tex_rotation_slider, stretch=1)
        self._hs_ol_tex_rotation_spin = QSpinBox()
        self._hs_ol_tex_rotation_spin.setRange(0, 359)
        self._hs_ol_tex_rotation_spin.setSuffix("\u00b0")
        self._hs_ol_tex_rotation_spin.setWrapping(True)
        self._hs_ol_tex_rotation_spin.setValue(int(tool.outline_texture_rotation))
        self._hs_ol_tex_rotation_spin.setFixedWidth(60)
        self._hs_ol_tex_rotation_spin.valueChanged.connect(self._on_hs_ol_tex_rot_spin)
        ol_tex_rot_row.addWidget(self._hs_ol_tex_rotation_spin)
        ol_tex_sec_layout.addLayout(ol_tex_rot_row)

        self._hs_ol_tex_rot_buttons: list[QPushButton] = []
        ol_tex_rot_btn_row = QHBoxLayout()
        ol_tex_rot_btn_row.setSpacing(2)
        for deg in (0, 60, 90, 120, 180, 270):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(32)
            btn.setChecked(deg == int(tool.outline_texture_rotation))
            btn.clicked.connect(lambda _, d=deg: self._on_ol_tex_rot_preset(d))
            ol_tex_rot_btn_row.addWidget(btn)
            self._hs_ol_tex_rot_buttons.append(btn)
        ol_tex_rot_btn_row.addStretch()
        ol_tex_sec_layout.addLayout(ol_tex_rot_btn_row)

        ol_c_layout.addWidget(self._hs_ol_texture_section)
        self._hs_ol_texture_section.setVisible(is_ol_texture)

        # --- Outline Width ---
        ol_c_layout.addWidget(QLabel("Width:"))
        self._hs_ol_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_ol_width_slider.setRange(1, 40)  # 0.5-20.0 in 0.5 steps
        self._hs_ol_width_slider.setValue(int(tool.outline_width * 2))
        self._hs_ol_width_slider.valueChanged.connect(self._on_hs_ol_width_slider)
        ol_w_row = QHBoxLayout()
        ol_w_row.addWidget(self._hs_ol_width_slider, stretch=1)
        self._hs_ol_width_spin = QDoubleSpinBox()
        self._hs_ol_width_spin.setRange(0.5, 20.0)
        self._hs_ol_width_spin.setSingleStep(0.5)
        self._hs_ol_width_spin.setValue(tool.outline_width)
        self._hs_ol_width_spin.setFixedWidth(65)
        self._hs_ol_width_spin.valueChanged.connect(self._on_hs_ol_width_spin)
        ol_w_row.addWidget(self._hs_ol_width_spin)
        ol_c_layout.addLayout(ol_w_row)

        # Outline Opacity
        ol_c_layout.addWidget(QLabel("Opacity:"))
        ol_opacity_row = QHBoxLayout()
        self._hs_ol_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_ol_opacity_slider.setRange(0, 100)
        self._hs_ol_opacity_slider.setValue(round(tool.outline_opacity * 100))
        self._hs_ol_opacity_slider.valueChanged.connect(self._on_hs_ol_opacity_slider)
        ol_opacity_row.addWidget(self._hs_ol_opacity_slider, stretch=1)
        self._hs_ol_opacity_spin = QSpinBox()
        self._hs_ol_opacity_spin.setRange(0, 100)
        self._hs_ol_opacity_spin.setSuffix("%")
        self._hs_ol_opacity_spin.setValue(round(tool.outline_opacity * 100))
        self._hs_ol_opacity_spin.setFixedWidth(60)
        self._hs_ol_opacity_spin.valueChanged.connect(self._on_hs_ol_opacity_spin)
        ol_opacity_row.addWidget(self._hs_ol_opacity_spin)
        ol_c_layout.addLayout(ol_opacity_row)

        self._hs_ol_container.setEnabled(tool.outline)
        outline_gl.addWidget(self._hs_ol_container)

        layout.addWidget(outline_group)

        # ===== Shift group =====
        shift_group = QGroupBox("Shift")
        shift_gl = QVBoxLayout(shift_group)
        shift_gl.setContentsMargins(6, 4, 6, 4)

        self._hs_shift_cb = QCheckBox("Enable Auto-Shift")
        self._hs_shift_cb.setChecked(tool.shift_enabled)
        self._hs_shift_cb.setEnabled(not tool.outline)
        self._hs_shift_cb.toggled.connect(self._on_hs_shift_toggled)
        shift_gl.addWidget(self._hs_shift_cb)

        self._hs_shift_container = QWidget()
        shift_c_layout = QVBoxLayout(self._hs_shift_container)
        shift_c_layout.setContentsMargins(0, 0, 0, 0)

        shift_row = QHBoxLayout()
        self._hs_shift_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_shift_slider.setRange(0, 150)
        self._hs_shift_slider.setValue(int(tool.shift * 10))
        self._hs_shift_slider.valueChanged.connect(self._on_hs_shift_slider)
        shift_row.addWidget(self._hs_shift_slider, stretch=1)
        self._hs_shift_spin = QDoubleSpinBox()
        self._hs_shift_spin.setRange(0.0, 15.0)
        self._hs_shift_spin.setSingleStep(0.5)
        self._hs_shift_spin.setValue(tool.shift)
        self._hs_shift_spin.setFixedWidth(65)
        self._hs_shift_spin.valueChanged.connect(self._on_hs_shift_spin)
        shift_row.addWidget(self._hs_shift_spin)
        shift_c_layout.addLayout(shift_row)

        self._hs_shift_container.setEnabled(tool.shift_enabled and not tool.outline)
        shift_gl.addWidget(self._hs_shift_container)

        layout.addWidget(shift_group)

        # ===== Random group =====
        random_group = QGroupBox("Random")
        random_gl = QVBoxLayout(random_group)
        random_gl.setContentsMargins(6, 4, 6, 4)

        self._hs_random_cb = QCheckBox("Enable Random")
        self._hs_random_cb.setChecked(tool.random)
        self._hs_random_cb.toggled.connect(self._on_hs_random_toggled)
        random_gl.addWidget(self._hs_random_cb)

        self._hs_random_container = QWidget()
        random_c_layout = QVBoxLayout(self._hs_random_container)
        random_c_layout.setContentsMargins(0, 0, 0, 0)

        # Amplitude: slider + spin inline (0.0 - 20.0, step 0.5)
        random_c_layout.addWidget(QLabel("Amplitude:"))
        amp_row = QHBoxLayout()
        self._hs_amp_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_amp_slider.setRange(0, 200)  # 0.0 - 20.0 in 0.1 steps
        self._hs_amp_slider.setValue(int(tool.random_amplitude * 10))
        self._hs_amp_slider.valueChanged.connect(self._on_hs_amp_slider)
        amp_row.addWidget(self._hs_amp_slider, stretch=1)
        self._hs_amp_spin = QDoubleSpinBox()
        self._hs_amp_spin.setRange(0.0, 20.0)
        self._hs_amp_spin.setSingleStep(0.5)
        self._hs_amp_spin.setValue(tool.random_amplitude)
        self._hs_amp_spin.setFixedWidth(65)
        self._hs_amp_spin.valueChanged.connect(self._on_hs_amp_spin)
        amp_row.addWidget(self._hs_amp_spin)
        random_c_layout.addLayout(amp_row)

        # Offset: slider + spin inline (0.0 - 100.0, step 0.5)
        random_c_layout.addWidget(QLabel("Offset:"))
        hs_offset_row = QHBoxLayout()
        self._hs_offset_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_offset_slider.setRange(0, 200)  # 0.0 - 100.0 in 0.5 steps
        self._hs_offset_slider.setValue(round(tool.random_offset / 0.5))
        self._hs_offset_slider.valueChanged.connect(self._on_hs_offset_slider)
        hs_offset_row.addWidget(self._hs_offset_slider, stretch=1)
        self._hs_offset_spin = QDoubleSpinBox()
        self._hs_offset_spin.setRange(0.0, 100.0)
        self._hs_offset_spin.setSingleStep(0.5)
        self._hs_offset_spin.setValue(tool.random_offset)
        self._hs_offset_spin.setFixedWidth(65)
        self._hs_offset_spin.valueChanged.connect(self._on_hs_offset_spin)
        hs_offset_row.addWidget(self._hs_offset_spin)
        random_c_layout.addLayout(hs_offset_row)

        # Distance: slider + spin inline (0.0 - 1.0, step 0.05)
        random_c_layout.addWidget(QLabel("Distance:"))
        dist_row = QHBoxLayout()
        self._hs_dist_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_dist_slider.setRange(0, 100)  # 0.00 - 1.00 in 0.01 steps
        self._hs_dist_slider.setValue(int(tool.random_distance * 100))
        self._hs_dist_slider.valueChanged.connect(self._on_hs_dist_slider)
        dist_row.addWidget(self._hs_dist_slider, stretch=1)
        self._hs_dist_spin = QDoubleSpinBox()
        self._hs_dist_spin.setRange(0.0, 1.0)
        self._hs_dist_spin.setSingleStep(0.05)
        self._hs_dist_spin.setDecimals(2)
        self._hs_dist_spin.setValue(tool.random_distance)
        self._hs_dist_spin.setFixedWidth(65)
        self._hs_dist_spin.valueChanged.connect(self._on_hs_dist_spin)
        dist_row.addWidget(self._hs_dist_spin)
        random_c_layout.addLayout(dist_row)

        # Endpoint Disp.: slider + spin inline (0.0 - 50.0, step 0.5)
        random_c_layout.addWidget(QLabel("Endpoints:"))
        ep_disp_row = QHBoxLayout()
        self._hs_ep_disp_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_ep_disp_slider.setRange(0, 500)  # 0.0 - 50.0 in 0.1 steps
        self._hs_ep_disp_slider.setValue(int(tool.random_endpoint * 10))
        self._hs_ep_disp_slider.valueChanged.connect(self._on_hs_ep_disp_slider)
        ep_disp_row.addWidget(self._hs_ep_disp_slider, stretch=1)
        self._hs_ep_disp_spin = QDoubleSpinBox()
        self._hs_ep_disp_spin.setRange(0.0, 50.0)
        self._hs_ep_disp_spin.setSingleStep(0.5)
        self._hs_ep_disp_spin.setValue(tool.random_endpoint)
        self._hs_ep_disp_spin.setFixedWidth(65)
        self._hs_ep_disp_spin.valueChanged.connect(self._on_hs_ep_disp_spin)
        ep_disp_row.addWidget(self._hs_ep_disp_spin)
        random_c_layout.addLayout(ep_disp_row)

        # Jitter: slider + spin inline (0.0 - 10.0, step 0.5)
        random_c_layout.addWidget(QLabel("Jitter:"))
        jitter_row = QHBoxLayout()
        self._hs_jitter_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_jitter_slider.setRange(0, 100)  # 0.0 - 10.0 in 0.1 steps
        self._hs_jitter_slider.setValue(int(tool.random_jitter * 10))
        self._hs_jitter_slider.valueChanged.connect(self._on_hs_jitter_slider)
        jitter_row.addWidget(self._hs_jitter_slider, stretch=1)
        self._hs_jitter_spin = QDoubleSpinBox()
        self._hs_jitter_spin.setRange(0.0, 10.0)
        self._hs_jitter_spin.setSingleStep(0.5)
        self._hs_jitter_spin.setValue(tool.random_jitter)
        self._hs_jitter_spin.setFixedWidth(65)
        self._hs_jitter_spin.valueChanged.connect(self._on_hs_jitter_spin)
        jitter_row.addWidget(self._hs_jitter_spin)
        random_c_layout.addLayout(jitter_row)

        self._hs_random_container.setEnabled(tool.random)
        random_gl.addWidget(self._hs_random_container)

        layout.addWidget(random_group)

        # ===== Taper group =====
        taper_group = QGroupBox("Taper")
        taper_gl = QVBoxLayout(taper_group)
        taper_gl.setContentsMargins(6, 4, 6, 4)

        self._hs_taper_cb = QCheckBox("Taper Free Ends")
        self._hs_taper_cb.setChecked(tool.taper)
        self._hs_taper_cb.toggled.connect(self._on_hs_taper_toggled)
        taper_gl.addWidget(self._hs_taper_cb)

        self._hs_taper_container = QWidget()
        taper_c_layout = QVBoxLayout(self._hs_taper_container)
        taper_c_layout.setContentsMargins(0, 0, 0, 0)

        taper_c_layout.addWidget(QLabel("Length:"))
        tl_row = QHBoxLayout()
        self._hs_taper_slider = QSlider(Qt.Orientation.Horizontal)
        self._hs_taper_slider.setRange(1, 10)  # 0.1 - 1.0 in 0.1 steps
        self._hs_taper_slider.setValue(int(tool.taper_length * 10))
        self._hs_taper_slider.valueChanged.connect(self._on_hs_taper_slider)
        tl_row.addWidget(self._hs_taper_slider, stretch=1)
        self._hs_taper_spin = QDoubleSpinBox()
        self._hs_taper_spin.setRange(0.1, 1.0)
        self._hs_taper_spin.setSingleStep(0.1)
        self._hs_taper_spin.setDecimals(1)
        self._hs_taper_spin.setValue(tool.taper_length)
        self._hs_taper_spin.setFixedWidth(65)
        self._hs_taper_spin.valueChanged.connect(self._on_hs_taper_spin)
        tl_row.addWidget(self._hs_taper_spin)
        taper_c_layout.addLayout(tl_row)

        self._hs_taper_container.setEnabled(tool.taper)
        taper_gl.addWidget(self._hs_taper_container)

        layout.addWidget(taper_group)

        # Initialize main palette
        ensure_default_palette()
        self._hs_refresh_palette_combo()
        self._hs_palette_combo.currentTextChanged.connect(self._hs_on_palette_changed)
        idx = self._hs_palette_combo.findText("Default")
        if idx >= 0:
            self._hs_palette_combo.setCurrentIndex(idx)
        else:
            self._hs_on_palette_changed(self._hs_palette_combo.currentText())

        # Initialize outline palette
        self._hs_ol_refresh_palette_combo()
        self._hs_ol_palette_combo.currentTextChanged.connect(self._hs_ol_on_palette_changed)
        idx = self._hs_ol_palette_combo.findText("Default")
        if idx >= 0:
            self._hs_ol_palette_combo.setCurrentIndex(idx)
        else:
            self._hs_ol_on_palette_changed(self._hs_ol_palette_combo.currentText())

        # Initialize texture browsers
        self._hst_refresh_filter_combos()
        self._hst_rebuild_browser()
        self._refresh_ol_texture_browser()

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

        # ===== Bevel & Emboss group (includes Structure sub-section) =====
        bevel_group = QGroupBox("Bevel && Emboss")
        bevel_gl = QVBoxLayout(bevel_group)
        bevel_gl.setContentsMargins(6, 4, 6, 4)

        # Angle (always enabled — shared by Bevel and Structure)
        ba_row = QHBoxLayout()
        ba_row.addWidget(QLabel("Angle:"))
        self._bevel_angle_slider = QSlider(Qt.Orientation.Horizontal)
        self._bevel_angle_slider.setRange(0, 360)
        self._bevel_angle_slider.setValue(int(layer.bevel_angle if layer else 120))
        self._bevel_angle_slider.valueChanged.connect(self._on_bevel_angle_slider)
        ba_row.addWidget(self._bevel_angle_slider, 1)
        self._bevel_angle_spin = QSpinBox()
        self._bevel_angle_spin.setRange(0, 360)
        self._bevel_angle_spin.setSuffix("°")
        self._bevel_angle_spin.setFixedWidth(60)
        self._bevel_angle_spin.setValue(int(layer.bevel_angle if layer else 120))
        self._bevel_angle_spin.valueChanged.connect(self._on_bevel_angle_spin)
        ba_row.addWidget(self._bevel_angle_spin)
        bevel_gl.addLayout(ba_row)

        # --- Bevel sub-section ---
        self._bevel_cb = QCheckBox("Enable Bevel")
        self._bevel_cb.setChecked(layer.bevel_enabled if layer else False)
        self._bevel_cb.toggled.connect(self._on_bevel_toggled)
        bevel_gl.addWidget(self._bevel_cb)

        self._bevel_container = QWidget()
        bc_layout = QVBoxLayout(self._bevel_container)
        bc_layout.setContentsMargins(0, 0, 0, 0)

        bt_row = QHBoxLayout()
        bt_row.addWidget(QLabel("Type:"))
        self._bevel_type_combo = QComboBox()
        self._bevel_type_combo.addItems(["Inner", "Outer"])
        self._bevel_type_combo.setCurrentText(
            "Outer" if (layer and layer.bevel_type == "outer") else "Inner"
        )
        self._bevel_type_combo.currentTextChanged.connect(self._on_bevel_type)
        bt_row.addWidget(self._bevel_type_combo, 1)
        bc_layout.addLayout(bt_row)

        bs_row = QHBoxLayout()
        bs_row.addWidget(QLabel("Size:"))
        self._bevel_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._bevel_size_slider.setRange(1, 40)
        self._bevel_size_slider.setValue(int((layer.bevel_size if layer else 3.0) * 2))
        self._bevel_size_slider.valueChanged.connect(self._on_bevel_size_slider)
        bs_row.addWidget(self._bevel_size_slider, 1)
        self._bevel_size_spin = QDoubleSpinBox()
        self._bevel_size_spin.setRange(0.5, 20.0)
        self._bevel_size_spin.setSingleStep(0.5)
        self._bevel_size_spin.setDecimals(1)
        self._bevel_size_spin.setFixedWidth(60)
        self._bevel_size_spin.setValue(layer.bevel_size if layer else 3.0)
        self._bevel_size_spin.valueChanged.connect(self._on_bevel_size_spin)
        bs_row.addWidget(self._bevel_size_spin)
        bc_layout.addLayout(bs_row)

        bd_row = QHBoxLayout()
        bd_row.addWidget(QLabel("Depth:"))
        self._bevel_depth_slider = QSlider(Qt.Orientation.Horizontal)
        self._bevel_depth_slider.setRange(0, 100)
        self._bevel_depth_slider.setValue(int((layer.bevel_depth if layer else 0.5) * 100))
        self._bevel_depth_slider.valueChanged.connect(self._on_bevel_depth_slider)
        bd_row.addWidget(self._bevel_depth_slider, 1)
        self._bevel_depth_spin = QDoubleSpinBox()
        self._bevel_depth_spin.setRange(0.0, 1.0)
        self._bevel_depth_spin.setSingleStep(0.05)
        self._bevel_depth_spin.setDecimals(2)
        self._bevel_depth_spin.setFixedWidth(60)
        self._bevel_depth_spin.setValue(layer.bevel_depth if layer else 0.5)
        self._bevel_depth_spin.valueChanged.connect(self._on_bevel_depth_spin)
        bd_row.addWidget(self._bevel_depth_spin)
        bc_layout.addLayout(bd_row)

        bh_row = QHBoxLayout()
        bh_row.addWidget(QLabel("Highlight:"))
        self._bevel_hl_color_btn = QPushButton()
        self._bevel_hl_color_btn.setFixedSize(40, 25)
        update_color_btn(self._bevel_hl_color_btn, QColor(
            layer.bevel_highlight_color if layer else "#ffffff"))
        self._bevel_hl_color_btn.clicked.connect(self._on_bevel_hl_color)
        bh_row.addWidget(self._bevel_hl_color_btn)
        self._bevel_hl_opacity_spin = QDoubleSpinBox()
        self._bevel_hl_opacity_spin.setRange(0.0, 1.0)
        self._bevel_hl_opacity_spin.setSingleStep(0.05)
        self._bevel_hl_opacity_spin.setDecimals(2)
        self._bevel_hl_opacity_spin.setFixedWidth(60)
        self._bevel_hl_opacity_spin.setValue(
            layer.bevel_highlight_opacity if layer else 0.75)
        self._bevel_hl_opacity_spin.valueChanged.connect(self._on_bevel_hl_opacity)
        bh_row.addWidget(self._bevel_hl_opacity_spin)
        bh_row.addStretch()
        bc_layout.addLayout(bh_row)

        bsh_row = QHBoxLayout()
        bsh_row.addWidget(QLabel("Shadow:"))
        self._bevel_sh_color_btn = QPushButton()
        self._bevel_sh_color_btn.setFixedSize(40, 25)
        update_color_btn(self._bevel_sh_color_btn, QColor(
            layer.bevel_shadow_color if layer else "#000000"))
        self._bevel_sh_color_btn.clicked.connect(self._on_bevel_sh_color)
        bsh_row.addWidget(self._bevel_sh_color_btn)
        self._bevel_sh_opacity_spin = QDoubleSpinBox()
        self._bevel_sh_opacity_spin.setRange(0.0, 1.0)
        self._bevel_sh_opacity_spin.setSingleStep(0.05)
        self._bevel_sh_opacity_spin.setDecimals(2)
        self._bevel_sh_opacity_spin.setFixedWidth(60)
        self._bevel_sh_opacity_spin.setValue(
            layer.bevel_shadow_opacity if layer else 0.75)
        self._bevel_sh_opacity_spin.valueChanged.connect(self._on_bevel_sh_opacity)
        bsh_row.addWidget(self._bevel_sh_opacity_spin)
        bsh_row.addStretch()
        bc_layout.addLayout(bsh_row)

        bevel_gl.addWidget(self._bevel_container)
        self._bevel_container.setEnabled(layer.bevel_enabled if layer else False)

        # --- Structure sub-section ---
        self._struct_cb = QCheckBox("Enable Structure")
        self._struct_cb.setChecked(layer.structure_enabled if layer else False)
        self._struct_cb.toggled.connect(self._on_struct_toggled)
        bevel_gl.addWidget(self._struct_cb)

        self._struct_container = QWidget()
        stc_layout = QVBoxLayout(self._struct_container)
        stc_layout.setContentsMargins(0, 0, 0, 0)

        stx_row = QHBoxLayout()
        stx_row.addWidget(QLabel("Texture:"))
        self._struct_tex_combo = QComboBox()
        self._struct_tex_combo.setMinimumWidth(100)
        self._refresh_struct_tex_combo(layer)
        self._struct_tex_combo.currentIndexChanged.connect(self._on_struct_tex_changed)
        stx_row.addWidget(self._struct_tex_combo, 1)
        stc_layout.addLayout(stx_row)

        sts_row = QHBoxLayout()
        sts_row.addWidget(QLabel("Scale:"))
        self._struct_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._struct_scale_slider.setRange(10, 1000)
        self._struct_scale_slider.setValue(int((layer.structure_scale if layer else 1.0) * 100))
        self._struct_scale_slider.valueChanged.connect(self._on_struct_scale_slider)
        sts_row.addWidget(self._struct_scale_slider, 1)
        self._struct_scale_spin = QDoubleSpinBox()
        self._struct_scale_spin.setRange(0.1, 10.0)
        self._struct_scale_spin.setSingleStep(0.1)
        self._struct_scale_spin.setDecimals(2)
        self._struct_scale_spin.setFixedWidth(60)
        self._struct_scale_spin.setValue(layer.structure_scale if layer else 1.0)
        self._struct_scale_spin.valueChanged.connect(self._on_struct_scale_spin)
        sts_row.addWidget(self._struct_scale_spin)
        stc_layout.addLayout(sts_row)

        std_row = QHBoxLayout()
        std_row.addWidget(QLabel("Depth:"))
        self._struct_depth_slider = QSlider(Qt.Orientation.Horizontal)
        self._struct_depth_slider.setRange(0, 100)
        self._struct_depth_slider.setValue(int(layer.structure_depth if layer else 50))
        self._struct_depth_slider.valueChanged.connect(self._on_struct_depth_slider)
        std_row.addWidget(self._struct_depth_slider, 1)
        self._struct_depth_spin = QSpinBox()
        self._struct_depth_spin.setRange(0, 100)
        self._struct_depth_spin.setFixedWidth(60)
        self._struct_depth_spin.setValue(int(layer.structure_depth if layer else 50))
        self._struct_depth_spin.valueChanged.connect(self._on_struct_depth_spin)
        std_row.addWidget(self._struct_depth_spin)
        stc_layout.addLayout(std_row)

        self._struct_invert_cb = QCheckBox("Invert")
        self._struct_invert_cb.setChecked(
            layer.structure_invert if layer else False)
        self._struct_invert_cb.toggled.connect(self._on_struct_invert)
        stc_layout.addWidget(self._struct_invert_cb)

        bevel_gl.addWidget(self._struct_container)
        self._struct_container.setEnabled(layer.structure_enabled if layer else False)
        layout.addWidget(bevel_group)

        return widget

    def close_sidebar(self) -> None:
        """Hide all hexside sidebars and uncheck their expand buttons."""
        if self._hst_texture_sidebar:
            self._hst_texture_sidebar.hide()
        try:
            if hasattr(self, "_hst_expand_btn"):
                self._hst_expand_btn.setChecked(False)
        except RuntimeError:
            pass
        if self._hsp_preset_sidebar:
            self._hsp_preset_sidebar.hide()
        try:
            if hasattr(self, "_hsp_expand_btn"):
                self._hsp_expand_btn.setChecked(False)
        except RuntimeError:
            pass
        if self._hs_ol_texture_sidebar:
            self._hs_ol_texture_sidebar.hide()
        try:
            if hasattr(self, "_hs_ol_tex_expand_btn"):
                self._hs_ol_tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    def _on_hs_mode_changed(self, button_id: int, checked: bool) -> None:
        if checked and hasattr(self, "_hexside_tool"):
            self._hexside_tool.mode = "place" if button_id == 0 else "select"
            self._hexside_tool._selected = None
            self._hexside_tool._interaction = None
            self._hexside_tool._notify_selection()

    # --- Selection sync ---

    def _on_selection_changed(self, obj) -> None:
        """Called when the selected hexside object changes."""
        if obj:
            self._sync_widgets_from_object(obj)

    def _sync_widgets_from_object(self, obj) -> None:
        """Sync all hexside widgets from a selected HexsideObject."""
        tool = self._hexside_tool
        if tool is None:
            return

        # Determine paint mode from texture_id
        paint_mode = "texture" if obj.texture_id else "color"

        # Update tool properties
        tool.color = obj.color
        tool.width = obj.width
        tool.outline = obj.outline
        tool.outline_color = obj.outline_color
        tool.outline_width = obj.outline_width
        tool.outline_texture_id = obj.outline_texture_id
        tool.outline_texture_zoom = obj.outline_texture_zoom
        tool.outline_texture_rotation = obj.outline_texture_rotation
        tool.shift_enabled = obj.shift_enabled
        tool.shift = obj.shift
        tool.random = obj.random
        tool.random_amplitude = obj.random_amplitude
        tool.random_distance = obj.random_distance
        tool.random_jitter = obj.random_jitter
        tool.random_endpoint = obj.random_endpoint
        tool.random_offset = obj.random_offset
        tool.taper = obj.taper
        tool.taper_length = obj.taper_length
        tool.paint_mode = paint_mode
        if obj.texture_id:
            tool.current_texture_id = obj.texture_id
            tool.texture_zoom = obj.texture_zoom
            tool.texture_rotation = obj.texture_rotation
        tool.opacity = obj.opacity
        tool.outline_opacity = obj.outline_opacity

        # Color
        update_color_btn(self._hs_color_btn, QColor(obj.color))

        # Width
        self._hs_width_slider.blockSignals(True)
        self._hs_width_slider.setValue(int(obj.width * 2))
        self._hs_width_slider.blockSignals(False)
        self._hs_width_spin.blockSignals(True)
        self._hs_width_spin.setValue(obj.width)
        self._hs_width_spin.blockSignals(False)

        # Opacity
        self._hs_opacity_slider.blockSignals(True)
        self._hs_opacity_slider.setValue(round(obj.opacity * 100))
        self._hs_opacity_slider.blockSignals(False)
        self._hs_opacity_spin.blockSignals(True)
        self._hs_opacity_spin.setValue(round(obj.opacity * 100))
        self._hs_opacity_spin.blockSignals(False)

        # Outline
        self._hs_outline_cb.blockSignals(True)
        self._hs_outline_cb.setChecked(obj.outline)
        self._hs_outline_cb.blockSignals(False)
        update_color_btn(self._hs_ol_color_btn, QColor(obj.outline_color))
        self._hs_ol_width_slider.blockSignals(True)
        self._hs_ol_width_slider.setValue(int(obj.outline_width * 2))
        self._hs_ol_width_slider.blockSignals(False)
        self._hs_ol_width_spin.blockSignals(True)
        self._hs_ol_width_spin.setValue(obj.outline_width)
        self._hs_ol_width_spin.blockSignals(False)

        # Outline Opacity
        self._hs_ol_opacity_slider.blockSignals(True)
        self._hs_ol_opacity_slider.setValue(round(obj.outline_opacity * 100))
        self._hs_ol_opacity_slider.blockSignals(False)
        self._hs_ol_opacity_spin.blockSignals(True)
        self._hs_ol_opacity_spin.setValue(round(obj.outline_opacity * 100))
        self._hs_ol_opacity_spin.blockSignals(False)

        self._hs_ol_container.setEnabled(obj.outline)

        # Outline Paint Mode (Color | Texture)
        is_ol_texture = bool(obj.outline_texture_id)
        self._hs_ol_paint_mode_group.blockSignals(True)
        ol_pm_btn = self._hs_ol_paint_mode_group.button(1 if is_ol_texture else 0)
        if ol_pm_btn:
            ol_pm_btn.setChecked(True)
        self._hs_ol_paint_mode_group.blockSignals(False)
        self._hs_ol_color_section.setVisible(not is_ol_texture)
        self._hs_ol_texture_section.setVisible(is_ol_texture)
        if is_ol_texture:
            self._hs_ol_tex_zoom_slider.blockSignals(True)
            self._hs_ol_tex_zoom_slider.setValue(int(obj.outline_texture_zoom * 10))
            self._hs_ol_tex_zoom_slider.blockSignals(False)
            self._hs_ol_tex_zoom_spin.blockSignals(True)
            self._hs_ol_tex_zoom_spin.setValue(obj.outline_texture_zoom)
            self._hs_ol_tex_zoom_spin.blockSignals(False)
            self._hs_ol_tex_rotation_slider.blockSignals(True)
            self._hs_ol_tex_rotation_slider.setValue(int(obj.outline_texture_rotation))
            self._hs_ol_tex_rotation_slider.blockSignals(False)
            self._hs_ol_tex_rotation_spin.blockSignals(True)
            self._hs_ol_tex_rotation_spin.setValue(int(obj.outline_texture_rotation))
            self._hs_ol_tex_rotation_spin.blockSignals(False)
            self._sync_hs_ol_tex_rot_buttons(int(obj.outline_texture_rotation))
            # Update outline texture browser selection
            self._selected_ol_browser_texture = None
            for tex in self._hst_texture_catalog.textures:
                if tex.id == obj.outline_texture_id:
                    self._selected_ol_browser_texture = tex
                    break
            self._update_ol_texture_selection()
        else:
            # Clear outline texture selection when in color mode
            self._selected_ol_browser_texture = None
            self._update_ol_texture_selection()

        # Shift
        self._hs_shift_cb.blockSignals(True)
        self._hs_shift_cb.setChecked(obj.shift_enabled)
        self._hs_shift_cb.setEnabled(not obj.outline)
        self._hs_shift_cb.blockSignals(False)
        self._hs_shift_slider.blockSignals(True)
        self._hs_shift_slider.setValue(int(obj.shift * 10))
        self._hs_shift_slider.blockSignals(False)
        self._hs_shift_spin.blockSignals(True)
        self._hs_shift_spin.setValue(obj.shift)
        self._hs_shift_spin.blockSignals(False)
        self._hs_shift_container.setEnabled(obj.shift_enabled and not obj.outline)

        # Random
        self._hs_random_cb.blockSignals(True)
        self._hs_random_cb.setChecked(obj.random)
        self._hs_random_cb.blockSignals(False)
        self._hs_amp_slider.blockSignals(True)
        self._hs_amp_slider.setValue(int(obj.random_amplitude * 10))
        self._hs_amp_slider.blockSignals(False)
        self._hs_amp_spin.blockSignals(True)
        self._hs_amp_spin.setValue(obj.random_amplitude)
        self._hs_amp_spin.blockSignals(False)
        self._hs_dist_slider.blockSignals(True)
        self._hs_dist_slider.setValue(int(obj.random_distance * 100))
        self._hs_dist_slider.blockSignals(False)
        self._hs_dist_spin.blockSignals(True)
        self._hs_dist_spin.setValue(obj.random_distance)
        self._hs_dist_spin.blockSignals(False)
        self._hs_jitter_slider.blockSignals(True)
        self._hs_jitter_slider.setValue(int(obj.random_jitter * 10))
        self._hs_jitter_slider.blockSignals(False)
        self._hs_jitter_spin.blockSignals(True)
        self._hs_jitter_spin.setValue(obj.random_jitter)
        self._hs_jitter_spin.blockSignals(False)
        self._hs_ep_disp_slider.blockSignals(True)
        self._hs_ep_disp_slider.setValue(int(obj.random_endpoint * 10))
        self._hs_ep_disp_slider.blockSignals(False)
        self._hs_ep_disp_spin.blockSignals(True)
        self._hs_ep_disp_spin.setValue(obj.random_endpoint)
        self._hs_ep_disp_spin.blockSignals(False)
        self._hs_offset_slider.blockSignals(True)
        self._hs_offset_slider.setValue(round(obj.random_offset / 0.5))
        self._hs_offset_slider.blockSignals(False)
        self._hs_offset_spin.blockSignals(True)
        self._hs_offset_spin.setValue(obj.random_offset)
        self._hs_offset_spin.blockSignals(False)
        self._hs_random_container.setEnabled(obj.random)

        # Taper
        self._hs_taper_cb.blockSignals(True)
        self._hs_taper_cb.setChecked(obj.taper)
        self._hs_taper_cb.blockSignals(False)
        self._hs_taper_slider.blockSignals(True)
        self._hs_taper_slider.setValue(int(obj.taper_length * 10))
        self._hs_taper_slider.blockSignals(False)
        self._hs_taper_spin.blockSignals(True)
        self._hs_taper_spin.setValue(obj.taper_length)
        self._hs_taper_spin.blockSignals(False)
        self._hs_taper_container.setEnabled(obj.taper)

        # Paint mode
        pm_id = 1 if paint_mode == "texture" else 0
        self._hs_paint_mode_group.blockSignals(True)
        btn = self._hs_paint_mode_group.button(pm_id)
        if btn:
            btn.setChecked(True)
        self._hs_paint_mode_group.blockSignals(False)
        self._hs_color_group.setVisible(paint_mode == "color")
        self._hs_texture_group.setVisible(paint_mode == "texture")

        # Texture controls
        if obj.texture_id:
            self._hst_zoom_slider.blockSignals(True)
            self._hst_zoom_slider.setValue(int(obj.texture_zoom * 10))
            self._hst_zoom_slider.blockSignals(False)
            self._hst_zoom_spin.blockSignals(True)
            self._hst_zoom_spin.setValue(obj.texture_zoom)
            self._hst_zoom_spin.blockSignals(False)
            self._hst_rotation_slider.blockSignals(True)
            self._hst_rotation_slider.setValue(int(obj.texture_rotation))
            self._hst_rotation_slider.blockSignals(False)
            self._hst_rotation_spin.blockSignals(True)
            self._hst_rotation_spin.setValue(int(obj.texture_rotation))
            self._hst_rotation_spin.blockSignals(False)
            self._sync_hst_rot_buttons(int(obj.texture_rotation))
            # Update browser selection
            self._hst_selected_texture = None
            for tex in self._hst_texture_catalog.textures:
                if tex.id == obj.texture_id:
                    self._hst_selected_texture = tex
                    break
            self._hst_update_selection()

    def _apply_to_selected(self, **changes) -> None:
        """Apply property changes to the selected hexside via an undoable command."""
        if (
            self._hexside_tool
            and self._hexside_tool.mode == "select"
            and self._hexside_tool._selected is not None
        ):
            layer = self._hexside_tool._get_active_hexside_layer()
            if layer:
                cmd = EditHexsideCommand(
                    layer, self._hexside_tool._selected, **changes
                )
                self._hexside_tool._command_stack.execute(cmd)

    def _on_hs_color_pick(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._hexside_tool.color), self.dock, "Pick Hexside Color",
        )
        if color.isValid():
            self._hexside_tool.color = color.name()
            update_color_btn(self._hs_color_btn, color)
            self._apply_to_selected(color=color.name())

    # --- Width slider/spin sync ---

    def _on_hs_width_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._hexside_tool.width = real_val
        self._hs_width_spin.blockSignals(True)
        self._hs_width_spin.setValue(real_val)
        self._hs_width_spin.blockSignals(False)
        self._apply_to_selected(width=real_val)

    def _on_hs_width_spin(self, value: float) -> None:
        self._hexside_tool.width = value
        self._hs_width_slider.blockSignals(True)
        self._hs_width_slider.setValue(int(value * 2))
        self._hs_width_slider.blockSignals(False)
        self._apply_to_selected(width=value)

    def _on_hs_ol_width_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._hexside_tool.outline_width = real_val
        self._hs_ol_width_spin.blockSignals(True)
        self._hs_ol_width_spin.setValue(real_val)
        self._hs_ol_width_spin.blockSignals(False)
        self._apply_to_selected(outline_width=real_val)

    def _on_hs_ol_width_spin(self, value: float) -> None:
        self._hexside_tool.outline_width = value
        self._hs_ol_width_slider.blockSignals(True)
        self._hs_ol_width_slider.setValue(int(value * 2))
        self._hs_ol_width_slider.blockSignals(False)
        self._apply_to_selected(outline_width=value)

    def _on_hs_opacity_slider(self, value: int) -> None:
        real_val = value / 100.0
        self._hexside_tool.opacity = real_val
        self._hs_opacity_spin.blockSignals(True)
        self._hs_opacity_spin.setValue(value)
        self._hs_opacity_spin.blockSignals(False)
        self._apply_to_selected(opacity=real_val)

    def _on_hs_opacity_spin(self, value: int) -> None:
        real_val = value / 100.0
        self._hexside_tool.opacity = real_val
        self._hs_opacity_slider.blockSignals(True)
        self._hs_opacity_slider.setValue(value)
        self._hs_opacity_slider.blockSignals(False)
        self._apply_to_selected(opacity=real_val)

    def _on_hs_ol_opacity_slider(self, value: int) -> None:
        real_val = value / 100.0
        self._hexside_tool.outline_opacity = real_val
        self._hs_ol_opacity_spin.blockSignals(True)
        self._hs_ol_opacity_spin.setValue(value)
        self._hs_ol_opacity_spin.blockSignals(False)
        self._apply_to_selected(outline_opacity=real_val)

    def _on_hs_ol_opacity_spin(self, value: int) -> None:
        real_val = value / 100.0
        self._hexside_tool.outline_opacity = real_val
        self._hs_ol_opacity_slider.blockSignals(True)
        self._hs_ol_opacity_slider.setValue(value)
        self._hs_ol_opacity_slider.blockSignals(False)
        self._apply_to_selected(outline_opacity=real_val)

    def _on_hs_outline_toggled(self, checked: bool) -> None:
        self._hexside_tool.outline = checked
        self._hs_ol_container.setEnabled(checked)
        # Shift is mutually exclusive with outline
        self._hs_shift_cb.setEnabled(not checked)
        if checked:
            self._hs_shift_cb.setChecked(False)
            # Auto-set outline width only if it hasn't been customized yet
            if self._hexside_tool.outline_width <= 0:
                main_width = self._hexside_tool.width
                self._hexside_tool.outline_width = main_width
                self._hs_ol_width_slider.blockSignals(True)
                self._hs_ol_width_slider.setValue(int(main_width * 2))
                self._hs_ol_width_slider.blockSignals(False)
                self._hs_ol_width_spin.blockSignals(True)
                self._hs_ol_width_spin.setValue(main_width)
                self._hs_ol_width_spin.blockSignals(False)
        self._hs_shift_container.setEnabled(
            self._hs_shift_cb.isChecked() and not checked
        )
        if checked:
            # M19: include outline_width in the same command so undo restores both atomically
            self._apply_to_selected(outline=True, outline_width=self._hexside_tool.outline_width)
        else:
            self._apply_to_selected(outline=False)

    def _on_hs_outline_color_pick(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._hexside_tool.outline_color), self.dock, "Pick Outline Color",
        )
        if color.isValid():
            self._hexside_tool.outline_color = color.name()
            update_color_btn(self._hs_ol_color_btn, color)
            self._apply_to_selected(outline_color=color.name())

    def _on_hs_shift_toggled(self, checked: bool) -> None:
        self._hexside_tool.shift_enabled = checked
        self._hs_shift_container.setEnabled(checked)
        self._apply_to_selected(shift_enabled=checked)

    def _on_hs_shift_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._hexside_tool.shift = real_val
        self._hs_shift_spin.blockSignals(True)
        self._hs_shift_spin.setValue(real_val)
        self._hs_shift_spin.blockSignals(False)
        self._apply_to_selected(shift=real_val)

    def _on_hs_shift_spin(self, value: float) -> None:
        self._hexside_tool.shift = value
        self._hs_shift_slider.blockSignals(True)
        self._hs_shift_slider.setValue(int(value * 10))
        self._hs_shift_slider.blockSignals(False)
        self._apply_to_selected(shift=value)

    def _on_hs_random_toggled(self, checked: bool) -> None:
        self._hexside_tool.random = checked
        self._hs_random_container.setEnabled(checked)
        self._apply_to_selected(random=checked)

    def _on_hs_amp_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._hexside_tool.random_amplitude = real_val
        self._hs_amp_spin.blockSignals(True)
        self._hs_amp_spin.setValue(real_val)
        self._hs_amp_spin.blockSignals(False)
        self._apply_to_selected(random_amplitude=real_val)

    def _on_hs_amp_spin(self, value: float) -> None:
        self._hexside_tool.random_amplitude = value
        self._hs_amp_slider.blockSignals(True)
        self._hs_amp_slider.setValue(int(value * 10))
        self._hs_amp_slider.blockSignals(False)
        self._apply_to_selected(random_amplitude=value)

    def _on_hs_dist_slider(self, value: int) -> None:
        real_val = value / 100.0
        self._hexside_tool.random_distance = real_val
        self._hs_dist_spin.blockSignals(True)
        self._hs_dist_spin.setValue(real_val)
        self._hs_dist_spin.blockSignals(False)
        self._apply_to_selected(random_distance=real_val)

    def _on_hs_dist_spin(self, value: float) -> None:
        self._hexside_tool.random_distance = value
        self._hs_dist_slider.blockSignals(True)
        self._hs_dist_slider.setValue(int(value * 100))
        self._hs_dist_slider.blockSignals(False)
        self._apply_to_selected(random_distance=value)

    def _on_hs_jitter_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._hexside_tool.random_jitter = real_val
        self._hs_jitter_spin.blockSignals(True)
        self._hs_jitter_spin.setValue(real_val)
        self._hs_jitter_spin.blockSignals(False)
        self._apply_to_selected(random_jitter=real_val)

    def _on_hs_jitter_spin(self, value: float) -> None:
        self._hexside_tool.random_jitter = value
        self._hs_jitter_slider.blockSignals(True)
        self._hs_jitter_slider.setValue(int(value * 10))
        self._hs_jitter_slider.blockSignals(False)
        self._apply_to_selected(random_jitter=value)

    def _on_hs_ep_disp_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._hexside_tool.random_endpoint = real_val
        self._hs_ep_disp_spin.blockSignals(True)
        self._hs_ep_disp_spin.setValue(real_val)
        self._hs_ep_disp_spin.blockSignals(False)
        # Propagate to all hexsides sharing either vertex (select mode only)
        self._hexside_tool.apply_random_endpoint_with_sync(real_val)

    def _on_hs_ep_disp_spin(self, value: float) -> None:
        self._hexside_tool.random_endpoint = value
        self._hs_ep_disp_slider.blockSignals(True)
        self._hs_ep_disp_slider.setValue(int(value * 10))
        self._hs_ep_disp_slider.blockSignals(False)
        # Propagate to all hexsides sharing either vertex (select mode only)
        self._hexside_tool.apply_random_endpoint_with_sync(value)

    def _on_hs_offset_slider(self, value: int) -> None:
        real_val = value * 0.5
        self._hexside_tool.random_offset = real_val
        self._hs_offset_spin.blockSignals(True)
        self._hs_offset_spin.setValue(real_val)
        self._hs_offset_spin.blockSignals(False)
        self._apply_to_selected(random_offset=real_val)

    def _on_hs_offset_spin(self, value: float) -> None:
        self._hexside_tool.random_offset = value
        self._hs_offset_slider.blockSignals(True)
        self._hs_offset_slider.setValue(round(value / 0.5))
        self._hs_offset_slider.blockSignals(False)
        self._apply_to_selected(random_offset=value)

    # --- Taper handlers ---

    def _on_hs_taper_toggled(self, checked: bool) -> None:
        self._hexside_tool.taper = checked
        self._hs_taper_container.setEnabled(checked)
        self._apply_to_selected(taper=checked)

    def _on_hs_taper_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._hexside_tool.taper_length = real_val
        self._hs_taper_spin.blockSignals(True)
        self._hs_taper_spin.setValue(real_val)
        self._hs_taper_spin.blockSignals(False)
        self._apply_to_selected(taper_length=real_val)

    def _on_hs_taper_spin(self, value: float) -> None:
        self._hexside_tool.taper_length = value
        self._hs_taper_slider.blockSignals(True)
        self._hs_taper_slider.setValue(int(value * 10))
        self._hs_taper_slider.blockSignals(False)
        self._apply_to_selected(taper_length=value)

    # --- Texture zoom/rotation slider/spin sync ---

    def _on_hst_zoom_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._hexside_tool.texture_zoom = real_val
        self._hst_zoom_spin.blockSignals(True)
        self._hst_zoom_spin.setValue(real_val)
        self._hst_zoom_spin.blockSignals(False)
        self._apply_to_selected(texture_zoom=real_val)

    def _on_hst_zoom_spin(self, value: float) -> None:
        self._hexside_tool.texture_zoom = value
        self._hst_zoom_slider.blockSignals(True)
        self._hst_zoom_slider.setValue(int(value * 10))
        self._hst_zoom_slider.blockSignals(False)
        self._apply_to_selected(texture_zoom=value)

    def _on_hst_rot_slider(self, value: int) -> None:
        self._hexside_tool.texture_rotation = float(value)
        self._hst_rotation_spin.blockSignals(True)
        self._hst_rotation_spin.setValue(value)
        self._hst_rotation_spin.blockSignals(False)
        self._sync_hst_rot_buttons(value)
        self._apply_to_selected(texture_rotation=float(value))

    def _on_hst_rot_spin(self, value: int) -> None:
        self._hexside_tool.texture_rotation = float(value)
        self._hst_rotation_slider.blockSignals(True)
        self._hst_rotation_slider.setValue(value)
        self._hst_rotation_slider.blockSignals(False)
        self._sync_hst_rot_buttons(value)
        self._apply_to_selected(texture_rotation=float(value))

    def _on_hst_rot_preset(self, degrees: int) -> None:
        self._hexside_tool.texture_rotation = float(degrees)
        self._hst_rotation_slider.blockSignals(True)
        self._hst_rotation_slider.setValue(degrees)
        self._hst_rotation_slider.blockSignals(False)
        self._hst_rotation_spin.blockSignals(True)
        self._hst_rotation_spin.setValue(degrees)
        self._hst_rotation_spin.blockSignals(False)
        self._sync_hst_rot_buttons(degrees)
        self._apply_to_selected(texture_rotation=float(degrees))

    def _sync_hst_rot_buttons(self, value: int) -> None:
        """Highlight the preset button matching the current texture rotation value."""
        _PRESETS = (0, 60, 90, 120, 180, 270)
        for i, preset in enumerate(_PRESETS):
            self._hst_rot_buttons[i].setChecked(preset == value)

    # --- Hexside palette ---

    def _hs_refresh_palette_combo(self) -> None:
        self._hs_palette_combo.blockSignals(True)
        current = self._hs_palette_combo.currentText()
        self._hs_palette_combo.clear()
        for name in list_palettes():
            self._hs_palette_combo.addItem(name)
        idx = self._hs_palette_combo.findText(current)
        if idx >= 0:
            self._hs_palette_combo.setCurrentIndex(idx)
        self._hs_palette_combo.blockSignals(False)

    def _hs_on_palette_changed(self, name: str) -> None:
        if not name:
            return
        try:
            self._hs_current_palette = load_palette(name)
        except FileNotFoundError:
            self._hs_current_palette = None
        self._hs_selected_palette_idx = -1
        self._hs_rebuild_color_grid()

    def _hs_rebuild_color_grid(self) -> None:
        for btn in self._hs_palette_color_buttons:
            self._hs_color_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._hs_palette_color_buttons.clear()

        if not self._hs_current_palette:
            return

        for i, pc in enumerate(self._hs_current_palette.colors):
            btn = QPushButton()
            btn.setFixedSize(36, 36)
            btn.setToolTip(pc.name)
            self._style_palette_btn(btn, pc.color, selected=False)
            btn.clicked.connect(
                lambda checked, idx=i: self._hs_on_palette_color_clicked(idx)
            )
            row = i // _PALETTE_GRID_COLS
            col = i % _PALETTE_GRID_COLS
            self._hs_color_grid_layout.addWidget(btn, row, col)
            self._hs_palette_color_buttons.append(btn)

    def _hs_on_palette_color_clicked(self, idx: int) -> None:
        if not self._hs_current_palette or idx >= len(self._hs_current_palette.colors):
            return

        # Deselect previous
        if 0 <= self._hs_selected_palette_idx < len(self._hs_palette_color_buttons):
            old_pc = self._hs_current_palette.colors[self._hs_selected_palette_idx]
            self._style_palette_btn(
                self._hs_palette_color_buttons[self._hs_selected_palette_idx],
                old_pc.color, selected=False,
            )

        # Select new
        self._hs_selected_palette_idx = idx
        pc = self._hs_current_palette.colors[idx]
        self._style_palette_btn(
            self._hs_palette_color_buttons[idx], pc.color, selected=True,
        )

        # Set hexside color
        color = QColor(pc.color)
        self._hexside_tool.color = color.name()
        update_color_btn(self._hs_color_btn, color)
        self._apply_to_selected(color=color.name())

    def _style_palette_btn(self, btn: QPushButton, color_hex: str, selected: bool) -> None:
        """Style a palette color button."""
        border = "2px solid #00aaff" if selected else "1px solid #555"
        btn.setStyleSheet(
            f"background-color: {color_hex}; border: {border};"
        )

    # --- Outline palette ---

    def _hs_ol_refresh_palette_combo(self) -> None:
        self._hs_ol_palette_combo.blockSignals(True)
        current = self._hs_ol_palette_combo.currentText()
        self._hs_ol_palette_combo.clear()
        for name in list_palettes():
            self._hs_ol_palette_combo.addItem(name)
        idx = self._hs_ol_palette_combo.findText(current)
        if idx >= 0:
            self._hs_ol_palette_combo.setCurrentIndex(idx)
        self._hs_ol_palette_combo.blockSignals(False)

    def _hs_ol_on_palette_changed(self, name: str) -> None:
        if not name:
            return
        try:
            self._hs_ol_current_palette = load_palette(name)
        except FileNotFoundError:
            self._hs_ol_current_palette = None
        self._hs_ol_selected_palette_idx = -1
        self._hs_ol_rebuild_color_grid()

    def _hs_ol_rebuild_color_grid(self) -> None:
        for btn in self._hs_ol_palette_color_buttons:
            self._hs_ol_color_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._hs_ol_palette_color_buttons.clear()

        if not self._hs_ol_current_palette:
            return

        for i, pc in enumerate(self._hs_ol_current_palette.colors):
            btn = QPushButton()
            btn.setFixedSize(36, 36)
            btn.setToolTip(pc.name)
            self._style_palette_btn(btn, pc.color, selected=False)
            btn.clicked.connect(
                lambda checked, idx=i: self._hs_ol_on_palette_color_clicked(idx)
            )
            row = i // _PALETTE_GRID_COLS
            col = i % _PALETTE_GRID_COLS
            self._hs_ol_color_grid_layout.addWidget(btn, row, col)
            self._hs_ol_palette_color_buttons.append(btn)

    def _hs_ol_on_palette_color_clicked(self, idx: int) -> None:
        if not self._hs_ol_current_palette or idx >= len(self._hs_ol_current_palette.colors):
            return

        # Deselect previous
        if 0 <= self._hs_ol_selected_palette_idx < len(self._hs_ol_palette_color_buttons):
            old_pc = self._hs_ol_current_palette.colors[self._hs_ol_selected_palette_idx]
            self._style_palette_btn(
                self._hs_ol_palette_color_buttons[self._hs_ol_selected_palette_idx],
                old_pc.color, selected=False,
            )

        # Select new
        self._hs_ol_selected_palette_idx = idx
        pc = self._hs_ol_current_palette.colors[idx]
        self._style_palette_btn(
            self._hs_ol_palette_color_buttons[idx], pc.color, selected=True,
        )

        # Set outline color
        color = QColor(pc.color)
        self._hexside_tool.outline_color = color.name()
        update_color_btn(self._hs_ol_color_btn, color)
        self._apply_to_selected(outline_color=color.name())

    # --- Outline texture handlers ---

    def _on_ol_paint_mode_changed(self, button_id: int, checked: bool) -> None:
        if not checked or not hasattr(self, "_hexside_tool"):
            return
        is_texture = button_id == 1
        self._hs_ol_color_section.setVisible(not is_texture)
        self._hs_ol_texture_section.setVisible(is_texture)
        if not is_texture:
            self._hexside_tool.outline_texture_id = ""
            self._apply_to_selected(outline_texture_id="")

    def _refresh_ol_texture_browser(self) -> None:
        self._refresh_ol_texture_filter_combos()
        self._rebuild_ol_texture_browser()

    def _refresh_ol_texture_filter_combos(self) -> None:
        catalog = self._hst_texture_catalog
        for combo, fill_fn in (
            (self._hs_ol_tex_game_combo, catalog.games),
            (self._hs_ol_tex_category_combo, catalog.categories),
        ):
            combo.blockSignals(True)
            current = combo.currentText()
            combo.clear()
            combo.addItem("All")
            for item in fill_fn():
                combo.addItem(item)
            idx = combo.findText(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def _on_ol_tex_filter_changed(self) -> None:
        self._rebuild_ol_texture_browser()
        self._sync_ol_texture_sidebar()

    def _filtered_ol_browser_textures(self) -> list[LibraryTexture]:
        game = self._hs_ol_tex_game_combo.currentText()
        cat = self._hs_ol_tex_category_combo.currentText()
        search = self._hs_ol_tex_search_edit.text().strip().lower()
        result = []
        for tex in self._hst_texture_catalog.textures:
            if game != "All" and tex.game != game:
                continue
            if cat != "All" and tex.category != cat:
                continue
            if search and search not in tex.display_name.lower():
                continue
            result.append(tex)
        return result

    def _rebuild_ol_texture_browser(self) -> None:
        for btn in list(self._ol_texture_browser_buttons.values()):
            try:
                self._hs_ol_tex_grid_layout.removeWidget(btn)
                btn.deleteLater()
            except RuntimeError:
                pass  # C++ object already deleted
        self._ol_texture_browser_buttons.clear()

        textures = self._filtered_ol_browser_textures()
        cols = 4
        for i, tex in enumerate(textures):
            btn = self._make_ol_texture_thumb(tex)
            self._hs_ol_tex_grid_layout.addWidget(btn, i // cols, i % cols)
            self._ol_texture_browser_buttons[tex.id] = btn
        self._update_ol_texture_selection()

    def _make_ol_texture_thumb(self, tex: LibraryTexture) -> QToolButton:
        btn = QToolButton()
        btn.setFixedSize(QSize(48, 48))
        btn.setToolTip(tex.display_name)
        pm = self._hst_thumb_cache.get(tex.id)
        if pm is None:
            from app.io.texture_cache import get_texture_image
            img = get_texture_image(tex.id)
            if img:
                pm = QPixmap.fromImage(img).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            else:
                pm = QPixmap(48, 48)
                pm.fill(QColor("#888888"))
            self._hst_thumb_cache[tex.id] = pm
        if pm:
            btn.setIcon(QIcon(pm))
            btn.setIconSize(QSize(44, 44))
        btn.clicked.connect(lambda checked=False, t=tex: self._on_ol_texture_clicked(t))
        return btn

    def _on_ol_texture_clicked(self, tex: LibraryTexture) -> None:
        self._selected_ol_browser_texture = tex
        self._hexside_tool.outline_texture_id = tex.id
        self._update_ol_texture_selection()
        if self._hs_ol_texture_sidebar and self._hs_ol_texture_sidebar.isVisible():
            self._hs_ol_texture_sidebar.set_selected(tex.id)
        self._apply_to_selected(outline_texture_id=tex.id)

    def _update_ol_texture_selection(self) -> None:
        selected_id = self._selected_ol_browser_texture.id if self._selected_ol_browser_texture else None
        for tid, btn in self._ol_texture_browser_buttons.items():
            btn.setChecked(tid == selected_id)

    def _on_toggle_ol_texture_sidebar(self, checked: bool) -> None:
        if checked:
            self.dock._save_panel_width()
            if not self._hs_ol_texture_sidebar:
                self._hs_ol_texture_sidebar = TextureBrowserSidebar(self.dock.window())
                self._hs_ol_texture_sidebar.texture_clicked.connect(self._on_ol_tex_sidebar_clicked)
                self._hs_ol_texture_sidebar.closed.connect(self._on_ol_tex_sidebar_closed)
                main_win = self.dock.window()
                main_win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._hs_ol_texture_sidebar)
                main_win.splitDockWidget(self.dock, self._hs_ol_texture_sidebar, Qt.Orientation.Horizontal)
            self._hs_ol_texture_sidebar.show()
            self._sync_ol_texture_sidebar()
        else:
            if self._hs_ol_texture_sidebar:
                self._hs_ol_texture_sidebar.hide()
            self.dock._restore_panel_width()

    def _sync_ol_texture_sidebar(self) -> None:
        if not self._hs_ol_texture_sidebar or not self._hs_ol_texture_sidebar.isVisible():
            return
        filtered = self._filtered_ol_browser_textures()
        selected_id = self._selected_ol_browser_texture.id if self._selected_ol_browser_texture else None
        self._hs_ol_texture_sidebar.set_textures(filtered, selected_id)

    def _on_ol_tex_sidebar_clicked(self, tex: LibraryTexture) -> None:
        self._on_ol_texture_clicked(tex)

    def _on_ol_tex_sidebar_closed(self) -> None:
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_hs_ol_tex_expand_btn"):
                self._hs_ol_tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    def _on_hs_ol_tex_zoom_slider(self, value: int) -> None:
        real_val = value * 0.1
        self._hexside_tool.outline_texture_zoom = real_val
        self._hs_ol_tex_zoom_spin.blockSignals(True)
        self._hs_ol_tex_zoom_spin.setValue(real_val)
        self._hs_ol_tex_zoom_spin.blockSignals(False)
        self._apply_to_selected(outline_texture_zoom=real_val)

    def _on_hs_ol_tex_zoom_spin(self, value: float) -> None:
        self._hexside_tool.outline_texture_zoom = value
        self._hs_ol_tex_zoom_slider.blockSignals(True)
        self._hs_ol_tex_zoom_slider.setValue(max(1, round(value * 10)))
        self._hs_ol_tex_zoom_slider.blockSignals(False)
        self._apply_to_selected(outline_texture_zoom=value)

    def _on_hs_ol_tex_rot_slider(self, value: int) -> None:
        self._hexside_tool.outline_texture_rotation = float(value)
        self._hs_ol_tex_rotation_spin.blockSignals(True)
        self._hs_ol_tex_rotation_spin.setValue(value)
        self._hs_ol_tex_rotation_spin.blockSignals(False)
        self._sync_hs_ol_tex_rot_buttons(value)
        self._apply_to_selected(outline_texture_rotation=float(value))

    def _on_hs_ol_tex_rot_spin(self, value: int) -> None:
        self._hexside_tool.outline_texture_rotation = float(value)
        self._hs_ol_tex_rotation_slider.blockSignals(True)
        self._hs_ol_tex_rotation_slider.setValue(value)
        self._hs_ol_tex_rotation_slider.blockSignals(False)
        self._sync_hs_ol_tex_rot_buttons(value)
        self._apply_to_selected(outline_texture_rotation=float(value))

    def _on_ol_tex_rot_preset(self, deg: int) -> None:
        self._hexside_tool.outline_texture_rotation = float(deg)
        self._hs_ol_tex_rotation_slider.blockSignals(True)
        self._hs_ol_tex_rotation_slider.setValue(deg)
        self._hs_ol_tex_rotation_slider.blockSignals(False)
        self._hs_ol_tex_rotation_spin.blockSignals(True)
        self._hs_ol_tex_rotation_spin.setValue(deg)
        self._hs_ol_tex_rotation_spin.blockSignals(False)
        self._sync_hs_ol_tex_rot_buttons(deg)
        self._apply_to_selected(outline_texture_rotation=float(deg))

    def _sync_hs_ol_tex_rot_buttons(self, value: int) -> None:
        _PRESETS = (0, 60, 90, 120, 180, 270)
        for i, preset in enumerate(_PRESETS):
            self._hs_ol_tex_rot_buttons[i].setChecked(preset == value)

    # --- Hexside paint mode ---

    def _on_hs_paint_mode_changed(self, button_id: int, checked: bool) -> None:
        if not checked or not hasattr(self, "_hexside_tool"):
            return
        mode = "color" if button_id == 0 else "texture"
        self._hexside_tool.paint_mode = mode
        self._hs_color_group.setVisible(mode == "color")
        self._hs_texture_group.setVisible(mode == "texture")
        if mode == "color":
            self._apply_to_selected(texture_id=None)
        else:
            tex_id = self._hexside_tool.current_texture_id
            if tex_id:
                self._apply_to_selected(texture_id=tex_id)

    # --- Hexside texture browser ---

    def _hst_refresh_filter_combos(self) -> None:
        self._hst_game_combo.blockSignals(True)
        current_game = self._hst_game_combo.currentText()
        self._hst_game_combo.clear()
        self._hst_game_combo.addItem("All")
        for g in self._hst_texture_catalog.games():
            self._hst_game_combo.addItem(g)
        idx = self._hst_game_combo.findText(current_game)
        if idx >= 0:
            self._hst_game_combo.setCurrentIndex(idx)
        self._hst_game_combo.blockSignals(False)

        self._hst_category_combo.blockSignals(True)
        current_cat = self._hst_category_combo.currentText()
        self._hst_category_combo.clear()
        self._hst_category_combo.addItem("All")
        for cat in self._hst_texture_catalog.categories():
            self._hst_category_combo.addItem(cat)
        idx = self._hst_category_combo.findText(current_cat)
        if idx >= 0:
            self._hst_category_combo.setCurrentIndex(idx)
        self._hst_category_combo.blockSignals(False)

    def _hst_filtered_textures(self) -> list[LibraryTexture]:
        game = self._hst_game_combo.currentText()
        category = self._hst_category_combo.currentText()
        search = self._hst_search_edit.text().strip().lower()
        result = []
        for tex in self._hst_texture_catalog.textures:
            if game != "All" and tex.game != game:
                continue
            if category != "All" and tex.category != category:
                continue
            if search and search not in tex.display_name.lower():
                continue
            result.append(tex)
        return result

    def _hst_rebuild_browser(self) -> None:
        for btn in self._hst_browser_buttons.values():
            self._hst_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._hst_browser_buttons.clear()

        filtered = self._hst_filtered_textures()
        cols = 3
        for i, tex in enumerate(filtered):
            btn = self._hst_make_thumb(tex)
            self._hst_grid_layout.addWidget(btn, i // cols, i % cols)
            self._hst_browser_buttons[tex.id] = btn
        self._hst_update_selection()

    def _hst_make_thumb(self, tex: LibraryTexture) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(56, 70)
        game_info = f"  ({tex.game})" if tex.game else ""
        btn.setToolTip(f"{tex.display_name}{game_info}\n{tex.category}")

        if tex.id in self._hst_thumb_cache:
            pixmap = self._hst_thumb_cache[tex.id]
        elif tex.exists():
            image = QImage(tex.file_path())
            if not image.isNull():
                scaled = image.scaled(
                    48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                pixmap = QPixmap.fromImage(scaled)
                self._hst_thumb_cache[tex.id] = pixmap
            else:
                pixmap = None
        else:
            pixmap = None

        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(48, 48))
        btn.setText(tex.display_name[:8])
        btn.setStyleSheet("QToolButton { padding: 1px; }")
        btn.clicked.connect(lambda checked=False, t=tex: self._hst_on_texture_clicked(t))
        return btn

    def _hst_on_texture_clicked(self, tex: LibraryTexture) -> None:
        self._hst_selected_texture = tex
        self._hexside_tool.current_texture_id = tex.id
        self._hst_update_selection()
        if self._hst_texture_sidebar and self._hst_texture_sidebar.isVisible():
            self._hst_texture_sidebar.set_selected(tex.id)
        self._apply_to_selected(texture_id=tex.id)

    def _hst_update_selection(self) -> None:
        for tex_id, btn in self._hst_browser_buttons.items():
            if self._hst_selected_texture and tex_id == self._hst_selected_texture.id:
                btn.setStyleSheet(
                    "QToolButton { padding: 1px; border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 1px; }")

    def _hst_on_filter_changed(self) -> None:
        self._hst_rebuild_browser()
        self._hst_sync_sidebar()

    def _hst_on_open_manager(self) -> None:
        dialog = TextureManagerDialog(self.dock)
        dialog.catalog_changed.connect(self._hst_on_manager_changed)
        dialog.exec()

    def _hst_on_manager_changed(self) -> None:
        self._hst_thumb_cache.clear()
        if self._hst_texture_sidebar:
            self._hst_texture_sidebar.invalidate_cache()
        if self._hs_ol_texture_sidebar:
            self._hs_ol_texture_sidebar.invalidate_cache()
        self._hst_texture_catalog = load_texture_catalog()
        self._hst_refresh_filter_combos()
        self._hst_rebuild_browser()
        self._hst_sync_sidebar()
        if hasattr(self, "_hs_ol_tex_game_combo"):
            self._refresh_ol_texture_browser()
            self._sync_ol_texture_sidebar()

    def refresh_texture_catalog(self) -> None:
        """Reload texture catalog (called on tool switch to pick up imports from other tools)."""
        if not hasattr(self, "_hst_texture_catalog"):
            return
        self._hst_texture_catalog = load_texture_catalog()
        self._hst_refresh_filter_combos()
        self._hst_rebuild_browser()
        self._hst_sync_sidebar()

    def refresh_palette_catalog(self) -> None:
        """Reload palette combos (called when the palette editor reports changes)."""
        if not hasattr(self, "_hs_palette_combo"):
            return
        self._hs_refresh_palette_combo()
        self._hs_ol_refresh_palette_combo()

    def _hst_on_toggle_sidebar(self, checked: bool) -> None:
        """Toggle the expanded texture browser sidebar for hexside textures."""
        if checked:
            self.dock._save_panel_width()
            if not self._hst_texture_sidebar:
                self._hst_texture_sidebar = TextureBrowserSidebar(self.dock.window())
                self._hst_texture_sidebar.texture_clicked.connect(
                    self._hst_on_sidebar_clicked,
                )
                self._hst_texture_sidebar.closed.connect(
                    self._hst_on_sidebar_closed,
                )
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea,
                    self._hst_texture_sidebar,
                )
                main_win.splitDockWidget(
                    self.dock, self._hst_texture_sidebar, Qt.Orientation.Horizontal,
                )
            self._hst_texture_sidebar.show()
            self._hst_sync_sidebar()
        else:
            if self._hst_texture_sidebar:
                self._hst_texture_sidebar.hide()
            self.dock._restore_panel_width()

    def _hst_sync_sidebar(self) -> None:
        """Update hexside texture sidebar contents from current filter state."""
        if not self._hst_texture_sidebar or not self._hst_texture_sidebar.isVisible():
            return
        filtered = self._hst_filtered_textures()
        selected_id = (
            self._hst_selected_texture.id
            if self._hst_selected_texture
            else None
        )
        self._hst_texture_sidebar.set_textures(filtered, selected_id)

    def _hst_on_sidebar_clicked(self, tex: LibraryTexture) -> None:
        """Handle texture selection from the hexside sidebar."""
        self._hst_on_texture_clicked(tex)

    def _hst_on_sidebar_closed(self) -> None:
        """Handle hexside texture sidebar close button."""
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_hst_expand_btn"):
                self._hst_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Hexside preset sidebar ---

    def _hsp_on_toggle_sidebar(self, checked: bool) -> None:
        """Toggle the expanded preset browser sidebar."""
        if checked:
            self.dock._save_panel_width()
            if not self._hsp_preset_sidebar:
                self._hsp_preset_sidebar = HexsidePresetSidebar(self.dock.window())
                self._hsp_preset_sidebar.preset_clicked.connect(
                    self._hsp_on_sidebar_preset_clicked,
                )
                self._hsp_preset_sidebar.closed.connect(
                    self._hsp_on_preset_sidebar_closed,
                )
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea,
                    self._hsp_preset_sidebar,
                )
                main_win.splitDockWidget(
                    self.dock, self._hsp_preset_sidebar, Qt.Orientation.Horizontal,
                )
            self._hsp_preset_sidebar.show()
            self._hsp_sync_sidebar()
        else:
            if self._hsp_preset_sidebar:
                self._hsp_preset_sidebar.hide()
            self.dock._restore_panel_width()

    def _hsp_sync_sidebar(self) -> None:
        """Update preset sidebar contents from disk."""
        if not self._hsp_preset_sidebar or not self._hsp_preset_sidebar.isVisible():
            return
        names = list_hexside_presets()
        selected = self._hsp_combo.currentText() or None
        self._hsp_preset_sidebar.set_presets(names, selected)

    def _hsp_on_sidebar_preset_clicked(self, name: str) -> None:
        """Handle preset selection from the sidebar — load it."""
        # Sync combo selection
        idx = self._hsp_combo.findText(name)
        if idx >= 0:
            self._hsp_combo.setCurrentIndex(idx)
        self._hsp_on_load()
        # Update sidebar selection
        if self._hsp_preset_sidebar:
            self._hsp_preset_sidebar.set_selected(name)

    def _hsp_on_preset_sidebar_closed(self) -> None:
        """Handle preset sidebar close button."""
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_hsp_expand_btn"):
                self._hsp_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Hexside presets ---

    def _hsp_refresh_combo(self) -> None:
        """Reload hexside preset combo from disk."""
        self._hsp_combo.blockSignals(True)
        current = self._hsp_combo.currentText()
        self._hsp_combo.clear()
        names = list_hexside_presets()
        self._hsp_combo.addItems(names)
        idx = self._hsp_combo.findText(current)
        if idx >= 0:
            self._hsp_combo.setCurrentIndex(idx)
        elif names:
            self._hsp_combo.setCurrentIndex(0)
        self._hsp_combo.blockSignals(False)

    def _hsp_on_selected(self, name: str) -> None:
        """Update preview and auto-load when preset selection changes."""
        self._hsp_update_preview()
        if name:
            self._hsp_on_load()

    def _hsp_update_preview(self) -> None:
        """Render the preview for the currently selected preset."""
        name = self._hsp_combo.currentText()
        if name:
            try:
                preset = load_hexside_preset(name)
            except (FileNotFoundError, Exception):
                preset = self._hsp_current_as_preset()
        else:
            preset = self._hsp_current_as_preset()
        self._hsp_render_preview(preset)

    def _hsp_current_as_preset(self) -> HexsidePreset:
        """Capture current hexside tool settings as a preset."""
        tool = self._hexside_tool
        return HexsidePreset(
            name="(current)",
            paint_mode=tool.paint_mode,
            color=tool.color,
            width=tool.width,
            outline=tool.outline,
            outline_color=tool.outline_color,
            outline_width=tool.outline_width,
            outline_texture_id=tool.outline_texture_id,
            outline_texture_zoom=tool.outline_texture_zoom,
            outline_texture_rotation=tool.outline_texture_rotation,
            shift_enabled=tool.shift_enabled,
            shift=tool.shift,
            random=tool.random,
            random_amplitude=tool.random_amplitude,
            random_distance=tool.random_distance,
            random_endpoint=tool.random_endpoint,
            random_jitter=tool.random_jitter,
            random_offset=tool.random_offset,
            taper=tool.taper,
            taper_length=tool.taper_length,
            texture_id=tool.current_texture_id,
            texture_zoom=tool.texture_zoom,
            texture_rotation=tool.texture_rotation,
            opacity=tool.opacity,
            outline_opacity=tool.outline_opacity,
        )

    def _hsp_render_preview(self, preset: HexsidePreset) -> None:
        """Render a small preview pixmap for a hexside preset."""
        w = max(self._hsp_preview.width(), 200)
        h = max(self._hsp_preview.height(), 40)
        self._hsp_preview.setPixmap(render_hexside_preview(preset, w, h))

    def _hsp_on_load(self) -> None:
        """Apply selected preset to hexside tool and sync UI."""
        name = self._hsp_combo.currentText()
        if not name:
            return
        try:
            preset = load_hexside_preset(name)
        except FileNotFoundError:
            QMessageBox.warning(self.dock, "Preset Not Found", f"Preset '{name}' not found.")
            self._hsp_refresh_combo()
            return

        tool = self._hexside_tool

        # Apply all settings to tool
        tool.paint_mode = preset.paint_mode
        tool.color = preset.color
        tool.width = preset.width
        tool.outline = preset.outline
        tool.outline_color = preset.outline_color
        tool.outline_width = preset.outline_width
        tool.outline_texture_id = preset.outline_texture_id
        tool.outline_texture_zoom = preset.outline_texture_zoom
        tool.outline_texture_rotation = preset.outline_texture_rotation
        tool.shift_enabled = preset.shift_enabled
        tool.shift = preset.shift
        tool.random = preset.random
        tool.random_amplitude = preset.random_amplitude
        tool.random_distance = preset.random_distance
        tool.random_endpoint = preset.random_endpoint
        tool.random_jitter = preset.random_jitter
        tool.random_offset = preset.random_offset
        tool.taper = preset.taper
        tool.taper_length = preset.taper_length
        tool.current_texture_id = preset.texture_id
        tool.texture_zoom = preset.texture_zoom
        tool.texture_rotation = preset.texture_rotation
        tool.opacity = preset.opacity
        tool.outline_opacity = preset.outline_opacity

        # Sync UI widgets (block signals to avoid cascading updates)

        # Color
        update_color_btn(self._hs_color_btn, QColor(preset.color))

        # Width
        self._hs_width_slider.blockSignals(True)
        self._hs_width_slider.setValue(int(preset.width * 2))
        self._hs_width_slider.blockSignals(False)
        self._hs_width_spin.blockSignals(True)
        self._hs_width_spin.setValue(preset.width)
        self._hs_width_spin.blockSignals(False)

        # Outline
        self._hs_outline_cb.blockSignals(True)
        self._hs_outline_cb.setChecked(preset.outline)
        self._hs_outline_cb.blockSignals(False)
        update_color_btn(self._hs_ol_color_btn, QColor(preset.outline_color))
        self._hs_ol_width_slider.blockSignals(True)
        self._hs_ol_width_slider.setValue(int(preset.outline_width * 2))
        self._hs_ol_width_slider.blockSignals(False)
        self._hs_ol_width_spin.blockSignals(True)
        self._hs_ol_width_spin.setValue(preset.outline_width)
        self._hs_ol_width_spin.blockSignals(False)
        self._hs_ol_container.setEnabled(preset.outline)

        # Outline Paint Mode (Color | Texture)
        is_ol_texture = bool(preset.outline_texture_id)
        self._hs_ol_paint_mode_group.blockSignals(True)
        ol_pm_btn = self._hs_ol_paint_mode_group.button(1 if is_ol_texture else 0)
        if ol_pm_btn:
            ol_pm_btn.setChecked(True)
        self._hs_ol_paint_mode_group.blockSignals(False)
        self._hs_ol_color_section.setVisible(not is_ol_texture)
        self._hs_ol_texture_section.setVisible(is_ol_texture)
        if is_ol_texture:
            self._hs_ol_tex_zoom_slider.blockSignals(True)
            self._hs_ol_tex_zoom_slider.setValue(int(preset.outline_texture_zoom * 10))
            self._hs_ol_tex_zoom_slider.blockSignals(False)
            self._hs_ol_tex_zoom_spin.blockSignals(True)
            self._hs_ol_tex_zoom_spin.setValue(preset.outline_texture_zoom)
            self._hs_ol_tex_zoom_spin.blockSignals(False)
            self._hs_ol_tex_rotation_slider.blockSignals(True)
            self._hs_ol_tex_rotation_slider.setValue(int(preset.outline_texture_rotation))
            self._hs_ol_tex_rotation_slider.blockSignals(False)
            self._hs_ol_tex_rotation_spin.blockSignals(True)
            self._hs_ol_tex_rotation_spin.setValue(int(preset.outline_texture_rotation))
            self._hs_ol_tex_rotation_spin.blockSignals(False)
            self._sync_hs_ol_tex_rot_buttons(int(preset.outline_texture_rotation))

        # Shift
        self._hs_shift_cb.blockSignals(True)
        self._hs_shift_cb.setChecked(preset.shift_enabled)
        self._hs_shift_cb.setEnabled(not preset.outline)
        self._hs_shift_cb.blockSignals(False)
        self._hs_shift_slider.blockSignals(True)
        self._hs_shift_slider.setValue(int(preset.shift * 10))
        self._hs_shift_slider.blockSignals(False)
        self._hs_shift_spin.blockSignals(True)
        self._hs_shift_spin.setValue(preset.shift)
        self._hs_shift_spin.blockSignals(False)
        self._hs_shift_container.setEnabled(preset.shift_enabled and not preset.outline)

        # Random
        self._hs_random_cb.blockSignals(True)
        self._hs_random_cb.setChecked(preset.random)
        self._hs_random_cb.blockSignals(False)
        self._hs_amp_slider.blockSignals(True)
        self._hs_amp_slider.setValue(int(preset.random_amplitude * 10))
        self._hs_amp_slider.blockSignals(False)
        self._hs_amp_spin.blockSignals(True)
        self._hs_amp_spin.setValue(preset.random_amplitude)
        self._hs_amp_spin.blockSignals(False)
        self._hs_dist_slider.blockSignals(True)
        self._hs_dist_slider.setValue(int(preset.random_distance * 100))
        self._hs_dist_slider.blockSignals(False)
        self._hs_dist_spin.blockSignals(True)
        self._hs_dist_spin.setValue(preset.random_distance)
        self._hs_dist_spin.blockSignals(False)
        self._hs_jitter_slider.blockSignals(True)
        self._hs_jitter_slider.setValue(int(preset.random_jitter * 10))
        self._hs_jitter_slider.blockSignals(False)
        self._hs_jitter_spin.blockSignals(True)
        self._hs_jitter_spin.setValue(preset.random_jitter)
        self._hs_jitter_spin.blockSignals(False)
        self._hs_ep_disp_slider.blockSignals(True)
        self._hs_ep_disp_slider.setValue(int(preset.random_endpoint * 10))
        self._hs_ep_disp_slider.blockSignals(False)
        self._hs_ep_disp_spin.blockSignals(True)
        self._hs_ep_disp_spin.setValue(preset.random_endpoint)
        self._hs_ep_disp_spin.blockSignals(False)
        self._hs_offset_slider.blockSignals(True)
        self._hs_offset_slider.setValue(round(preset.random_offset / 0.5))
        self._hs_offset_slider.blockSignals(False)
        self._hs_offset_spin.blockSignals(True)
        self._hs_offset_spin.setValue(preset.random_offset)
        self._hs_offset_spin.blockSignals(False)
        self._hs_random_container.setEnabled(preset.random)

        # Taper
        self._hs_taper_cb.blockSignals(True)
        self._hs_taper_cb.setChecked(preset.taper)
        self._hs_taper_cb.blockSignals(False)
        self._hs_taper_slider.blockSignals(True)
        self._hs_taper_slider.setValue(int(preset.taper_length * 10))
        self._hs_taper_slider.blockSignals(False)
        self._hs_taper_spin.blockSignals(True)
        self._hs_taper_spin.setValue(preset.taper_length)
        self._hs_taper_spin.blockSignals(False)
        self._hs_taper_container.setEnabled(preset.taper)

        # Paint mode toggle
        pm_id = 0 if preset.paint_mode == "color" else 1
        self._hs_paint_mode_group.blockSignals(True)
        btn = self._hs_paint_mode_group.button(pm_id)
        if btn:
            btn.setChecked(True)
        self._hs_paint_mode_group.blockSignals(False)
        self._hs_color_group.setVisible(preset.paint_mode == "color")
        self._hs_texture_group.setVisible(preset.paint_mode == "texture")

        # Texture controls
        if preset.texture_id:
            self._hst_zoom_slider.blockSignals(True)
            self._hst_zoom_slider.setValue(int(preset.texture_zoom * 10))
            self._hst_zoom_slider.blockSignals(False)
            self._hst_zoom_spin.blockSignals(True)
            self._hst_zoom_spin.setValue(preset.texture_zoom)
            self._hst_zoom_spin.blockSignals(False)
            self._hst_rotation_slider.blockSignals(True)
            self._hst_rotation_slider.setValue(int(preset.texture_rotation))
            self._hst_rotation_slider.blockSignals(False)
            self._hst_rotation_spin.blockSignals(True)
            self._hst_rotation_spin.setValue(int(preset.texture_rotation))
            self._hst_rotation_spin.blockSignals(False)
            self._sync_hst_rot_buttons(int(preset.texture_rotation))
            # Update texture selection in browser
            self._hst_selected_texture = None
            for tex in self._hst_texture_catalog.textures:
                if tex.id == preset.texture_id:
                    self._hst_selected_texture = tex
                    break
            self._hst_update_selection()

        # Opacity
        self._hs_opacity_slider.blockSignals(True)
        self._hs_opacity_slider.setValue(round(preset.opacity * 100))
        self._hs_opacity_slider.blockSignals(False)
        self._hs_opacity_spin.blockSignals(True)
        self._hs_opacity_spin.setValue(round(preset.opacity * 100))
        self._hs_opacity_spin.blockSignals(False)

        # Outline Opacity
        self._hs_ol_opacity_slider.blockSignals(True)
        self._hs_ol_opacity_slider.setValue(round(preset.outline_opacity * 100))
        self._hs_ol_opacity_slider.blockSignals(False)
        self._hs_ol_opacity_spin.blockSignals(True)
        self._hs_ol_opacity_spin.setValue(round(preset.outline_opacity * 100))
        self._hs_ol_opacity_spin.blockSignals(False)

        self._hsp_update_preview()

    def _hsp_on_save(self) -> None:
        """Save current hexside tool settings as a named preset."""
        name, ok = QInputDialog.getText(
            self.dock, "Save Hexside Preset", "Preset name:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        # Check for overwrite
        existing = list_hexside_presets()
        if name in existing:
            reply = QMessageBox.question(
                self.dock, "Overwrite Preset",
                f"Preset '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        preset = self._hsp_current_as_preset()
        preset.name = name
        save_hexside_preset(preset)
        self._hsp_refresh_combo()
        idx = self._hsp_combo.findText(name)
        if idx >= 0:
            self._hsp_combo.setCurrentIndex(idx)
        self._hsp_update_preview()
        self._hsp_sync_sidebar()

    def _hsp_on_delete(self) -> None:
        """Delete the selected hexside preset."""
        name = self._hsp_combo.currentText()
        if not name:
            return
        if is_builtin_hexside_preset(name):
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
        delete_hexside_preset(name)
        self._hsp_refresh_combo()
        self._hsp_update_preview()
        self._hsp_sync_sidebar()

    # --- Layer helper ---

    def _get_layer(self):
        if self._hexside_tool is None:
            return None
        return self._hexside_tool._get_active_hexside_layer()

    def _apply_layer_effect(self, **changes) -> None:
        layer = self._get_layer()
        if layer is None:
            return
        cmd = EditHexsideLayerEffectsCommand(layer, **changes)
        self._hexside_tool._command_stack.execute(cmd)

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

    # --- Bevel & Emboss handlers ---

    def _on_bevel_toggled(self, checked: bool) -> None:
        self._bevel_container.setEnabled(checked)
        self._apply_layer_effect(bevel_enabled=checked)

    def _on_bevel_type(self, text: str) -> None:
        self._apply_layer_effect(bevel_type="inner" if text == "Inner" else "outer")

    def _on_bevel_angle_slider(self, val: int) -> None:
        self._bevel_angle_spin.blockSignals(True)
        self._bevel_angle_spin.setValue(val)
        self._bevel_angle_spin.blockSignals(False)
        self._apply_layer_effect(bevel_angle=float(val))

    def _on_bevel_angle_spin(self, val: int) -> None:
        self._bevel_angle_slider.blockSignals(True)
        self._bevel_angle_slider.setValue(val)
        self._bevel_angle_slider.blockSignals(False)
        self._apply_layer_effect(bevel_angle=float(val))

    def _on_bevel_size_slider(self, val: int) -> None:
        w = val / 2.0
        self._bevel_size_spin.blockSignals(True)
        self._bevel_size_spin.setValue(w)
        self._bevel_size_spin.blockSignals(False)
        self._apply_layer_effect(bevel_size=w)

    def _on_bevel_size_spin(self, val: float) -> None:
        self._bevel_size_slider.blockSignals(True)
        self._bevel_size_slider.setValue(int(val * 2))
        self._bevel_size_slider.blockSignals(False)
        self._apply_layer_effect(bevel_size=val)

    def _on_bevel_depth_slider(self, val: int) -> None:
        d = val / 100.0
        self._bevel_depth_spin.blockSignals(True)
        self._bevel_depth_spin.setValue(d)
        self._bevel_depth_spin.blockSignals(False)
        self._apply_layer_effect(bevel_depth=d)

    def _on_bevel_depth_spin(self, val: float) -> None:
        self._bevel_depth_slider.blockSignals(True)
        self._bevel_depth_slider.setValue(int(val * 100))
        self._bevel_depth_slider.blockSignals(False)
        self._apply_layer_effect(bevel_depth=val)

    def _on_bevel_hl_color(self) -> None:
        layer = self._get_layer()
        if layer is None:
            return
        old = QColor(layer.bevel_highlight_color)
        dlg = QColorDialog(old, self.dock.widget())
        if dlg.exec():
            update_color_btn(self._bevel_hl_color_btn, dlg.selectedColor())
            self._apply_layer_effect(
                bevel_highlight_color=dlg.selectedColor().name())

    def _on_bevel_hl_opacity(self, val: float) -> None:
        self._apply_layer_effect(bevel_highlight_opacity=val)

    def _on_bevel_sh_color(self) -> None:
        layer = self._get_layer()
        if layer is None:
            return
        old = QColor(layer.bevel_shadow_color)
        dlg = QColorDialog(old, self.dock.widget())
        if dlg.exec():
            update_color_btn(self._bevel_sh_color_btn, dlg.selectedColor())
            self._apply_layer_effect(
                bevel_shadow_color=dlg.selectedColor().name())

    def _on_bevel_sh_opacity(self, val: float) -> None:
        self._apply_layer_effect(bevel_shadow_opacity=val)

    # --- Structure handlers ---

    def _on_struct_toggled(self, checked: bool) -> None:
        self._struct_container.setEnabled(checked)
        self._apply_layer_effect(structure_enabled=checked)

    def _refresh_struct_tex_combo(self, layer=None) -> None:
        """Populate the structure texture combo from the texture library."""
        self._struct_tex_combo.blockSignals(True)
        self._struct_tex_combo.clear()
        self._struct_tex_combo.addItem("(None)", "")
        catalog = load_texture_catalog()
        current_id = (layer.structure_texture_id if layer else None) or ""
        idx = 0
        for i, tex in enumerate(catalog.textures):
            self._struct_tex_combo.addItem(tex.display_name, tex.id)
            if tex.id == current_id:
                idx = i + 1
        self._struct_tex_combo.setCurrentIndex(idx)
        self._struct_tex_combo.blockSignals(False)

    def _on_struct_tex_changed(self, index: int) -> None:
        tex_id = self._struct_tex_combo.itemData(index) or None
        self._apply_layer_effect(structure_texture_id=tex_id)

    def _on_struct_scale_slider(self, val: int) -> None:
        s = val / 100.0
        self._struct_scale_spin.blockSignals(True)
        self._struct_scale_spin.setValue(s)
        self._struct_scale_spin.blockSignals(False)
        self._apply_layer_effect(structure_scale=s)

    def _on_struct_scale_spin(self, val: float) -> None:
        self._struct_scale_slider.blockSignals(True)
        self._struct_scale_slider.setValue(int(val * 100))
        self._struct_scale_slider.blockSignals(False)
        self._apply_layer_effect(structure_scale=val)

    def _on_struct_depth_slider(self, val: int) -> None:
        self._struct_depth_spin.blockSignals(True)
        self._struct_depth_spin.setValue(val)
        self._struct_depth_spin.blockSignals(False)
        self._apply_layer_effect(structure_depth=float(val))

    def _on_struct_depth_spin(self, val: int) -> None:
        self._struct_depth_slider.blockSignals(True)
        self._struct_depth_slider.setValue(val)
        self._struct_depth_slider.blockSignals(False)
        self._apply_layer_effect(structure_depth=float(val))

    def _on_struct_invert(self, checked: bool) -> None:
        self._apply_layer_effect(structure_invert=checked)
