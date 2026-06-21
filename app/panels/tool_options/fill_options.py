"""Fill tool options builder."""

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
from app.commands.fill_commands import FillAllCommand
from app.panels.texture_manager_dialog import TextureManagerDialog
from app.panels.tool_options.helpers import (
    PALETTE_GRID_COLS,
    update_color_btn,
)
from app.panels.tool_options.sidebar_widgets import TextureBrowserSidebar
from app.tools.fill_tool import FillTool

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel


class FillOptions:
    """Builds and manages the fill tool options UI."""

    _RADIUS_PRESETS = (0, 1, 2, 3, 5, 10)

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._fill_tool: FillTool | None = None
        self._selected_palette_idx: int = -1
        self._current_palette: ColorPalette | None = None
        self._palette_color_buttons: list[QPushButton] = []
        self._texture_catalog: TextureCatalog | None = None
        self._texture_thumb_cache: dict[str, QPixmap] = {}
        self._texture_browser_buttons: dict[str, QToolButton] = {}
        self._selected_browser_texture: LibraryTexture | None = None
        self._texture_sidebar: TextureBrowserSidebar | None = None
        self._radius_buttons: list[QPushButton] = []
        # Stipple texture browser state
        self._stip_tex_buttons: dict[str, QToolButton] = {}
        self._stip_selected_texture: LibraryTexture | None = None
        self._stip_tex_sidebar: TextureBrowserSidebar | None = None

    def create(self, tool: FillTool) -> QWidget:
        """Build fill options widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)

        # Store references for palette and texture interaction
        self._fill_tool = tool
        self._selected_palette_idx = -1
        self._current_palette = None
        self._palette_color_buttons = []
        self._texture_catalog = load_texture_catalog()
        self._texture_thumb_cache = {}
        self._texture_browser_buttons = {}
        self._selected_browser_texture = None

        # ===== Mode group =====
        mode_group = QGroupBox("Mode")
        mode_gl = QVBoxLayout(mode_group)
        mode_gl.setContentsMargins(6, 4, 6, 4)

        # Top-level mode: Hex / Dot Color / Coord Color / Hex Edge
        hex_btn = QPushButton("Hex")
        hex_btn.setCheckable(True)
        dot_color_btn = QPushButton("Dot Color")
        dot_color_btn.setCheckable(True)
        coord_color_btn = QPushButton("Coord Color")
        coord_color_btn.setCheckable(True)
        hex_edge_btn = QPushButton("Hex Edge")
        hex_edge_btn.setCheckable(True)
        stipple_btn = QPushButton("Stipple")
        stipple_btn.setCheckable(True)

        self._fill_mode_group = QButtonGroup(widget)
        self._fill_mode_group.setExclusive(True)
        self._fill_mode_group.addButton(hex_btn, 0)
        self._fill_mode_group.addButton(dot_color_btn, 1)
        self._fill_mode_group.addButton(coord_color_btn, 3)
        self._fill_mode_group.addButton(hex_edge_btn, 2)
        self._fill_mode_group.addButton(stipple_btn, 4)
        self._fill_mode_group.idToggled.connect(self._on_fill_mode_changed)

        mode_grid = QGridLayout()
        mode_grid.setSpacing(4)
        mode_grid.addWidget(hex_btn, 0, 0)
        mode_grid.addWidget(dot_color_btn, 0, 1)
        mode_grid.addWidget(coord_color_btn, 1, 0)
        mode_grid.addWidget(hex_edge_btn, 1, 1)
        mode_grid.addWidget(stipple_btn, 2, 0)
        mode_gl.addLayout(mode_grid)

        # Restore top-level mode (block signals — dependent widgets not yet created)
        self._fill_mode_group.blockSignals(True)
        if tool.paint_mode in ("hex_fill", "texture"):
            self._fill_mode_group.button(0).setChecked(True)  # Hex
        elif tool.paint_mode == "dot_color":
            self._fill_mode_group.button(1).setChecked(True)
        elif tool.paint_mode == "coord_color":
            self._fill_mode_group.button(3).setChecked(True)
        elif tool.paint_mode == "stipple":
            self._fill_mode_group.button(4).setChecked(True)
        else:
            self._fill_mode_group.button(2).setChecked(True)  # hex_edge
        self._fill_mode_group.blockSignals(False)

        layout.addWidget(mode_group)

        # ===== Paint Mode group (visible only when Hex is selected) =====
        self._fill_paint_mode_container = QGroupBox("Paint Mode")
        pm_layout = QHBoxLayout(self._fill_paint_mode_container)
        pm_layout.setContentsMargins(6, 4, 6, 4)
        color_pm_btn = QPushButton("Color")
        color_pm_btn.setCheckable(True)
        texture_pm_btn = QPushButton("Texture")
        texture_pm_btn.setCheckable(True)
        self._fill_paint_mode_group = QButtonGroup(widget)
        self._fill_paint_mode_group.setExclusive(True)
        self._fill_paint_mode_group.addButton(color_pm_btn, 0)
        self._fill_paint_mode_group.addButton(texture_pm_btn, 1)
        self._fill_paint_mode_group.idToggled.connect(self._on_fill_paint_mode_changed)
        pm_layout.addWidget(color_pm_btn)
        pm_layout.addWidget(texture_pm_btn)

        # Restore paint mode (block signals — dependent widgets not yet created)
        # Texture toggle applies to both Hex and Stipple modes
        self._fill_paint_mode_group.blockSignals(True)
        if tool.paint_mode == "texture" or tool.stipple_texture_id is not None:
            self._fill_paint_mode_group.button(1).setChecked(True)  # Texture
        else:
            self._fill_paint_mode_group.button(0).setChecked(True)  # Color
        self._fill_paint_mode_group.blockSignals(False)

        layout.addWidget(self._fill_paint_mode_container)

        # ===== Color group (with palette merged inside) =====
        self._fill_color_group = QGroupBox("Color")
        color_gl = QVBoxLayout(self._fill_color_group)
        color_gl.setContentsMargins(6, 4, 6, 4)

        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self._fill_color_btn = QPushButton()
        self._fill_color_btn.setFixedSize(40, 25)
        update_color_btn(self._fill_color_btn, tool.current_color)

        def pick_color():
            color = QColorDialog.getColor(tool.current_color, self.dock, "Pick Fill Color")
            if color.isValid():
                tool.current_color = color
                update_color_btn(self._fill_color_btn, color)

        self._fill_color_btn.clicked.connect(pick_color)
        color_layout.addWidget(self._fill_color_btn)
        color_layout.addStretch()
        color_gl.addLayout(color_layout)

        # --- Palette section (merged into color group) ---
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        color_gl.addWidget(separator)

        self._palette_combo = QComboBox()
        color_gl.addWidget(self._palette_combo)

        self._color_grid_widget = QWidget()
        self._color_grid_layout = QGridLayout(self._color_grid_widget)
        self._color_grid_layout.setSpacing(3)
        self._color_grid_layout.setContentsMargins(0, 0, 0, 0)
        color_gl.addWidget(self._color_grid_widget)

        layout.addWidget(self._fill_color_group)

        # ===== Texture group =====
        self._fill_texture_group = QGroupBox("Texture")
        texture_gl = QVBoxLayout(self._fill_texture_group)
        texture_gl.setContentsMargins(6, 4, 6, 4)

        # Game filter
        tex_game_layout = QHBoxLayout()
        tex_game_layout.addWidget(QLabel("Game:"))
        self._tex_game_combo = QComboBox()
        self._tex_game_combo.setMinimumWidth(80)
        self._tex_game_combo.currentTextChanged.connect(self._on_texture_filter_changed)
        tex_game_layout.addWidget(self._tex_game_combo, stretch=1)
        texture_gl.addLayout(tex_game_layout)

        # Category filter
        tex_cat_layout = QHBoxLayout()
        tex_cat_layout.addWidget(QLabel("Category:"))
        self._tex_category_combo = QComboBox()
        self._tex_category_combo.setMinimumWidth(80)
        self._tex_category_combo.currentTextChanged.connect(self._on_texture_filter_changed)
        tex_cat_layout.addWidget(self._tex_category_combo, stretch=1)
        texture_gl.addLayout(tex_cat_layout)

        # Search
        tex_search_layout = QHBoxLayout()
        tex_search_layout.addWidget(QLabel("Search:"))
        self._tex_search_edit = QLineEdit()
        self._tex_search_edit.setPlaceholderText("Filter by name...")
        self._tex_search_edit.textChanged.connect(self._on_texture_filter_changed)
        tex_search_layout.addWidget(self._tex_search_edit, stretch=1)
        texture_gl.addLayout(tex_search_layout)

        # Thumbnail grid
        self._tex_scroll = QScrollArea()
        self._tex_scroll.setWidgetResizable(True)
        self._tex_scroll.setMinimumHeight(80)
        self._tex_scroll.setMaximumHeight(200)
        self._tex_grid_container = QWidget()
        self._tex_grid_layout = QGridLayout(self._tex_grid_container)
        self._tex_grid_layout.setSpacing(4)
        self._tex_grid_layout.setContentsMargins(2, 2, 2, 2)
        self._tex_scroll.setWidget(self._tex_grid_container)
        texture_gl.addWidget(self._tex_scroll)

        # Manager + Expand buttons
        tex_btn_layout = QHBoxLayout()
        tex_manager_btn = QPushButton("Manager...")
        tex_manager_btn.clicked.connect(self._on_open_texture_manager)
        tex_btn_layout.addWidget(tex_manager_btn)
        self._tex_expand_btn = QPushButton("Expand")
        self._tex_expand_btn.setCheckable(True)
        self._tex_expand_btn.clicked.connect(self._on_toggle_texture_sidebar)
        tex_btn_layout.addWidget(self._tex_expand_btn)
        texture_gl.addLayout(tex_btn_layout)

        # Separator before transform controls
        tex_sep = QFrame()
        tex_sep.setFrameShape(QFrame.Shape.HLine)
        tex_sep.setFrameShadow(QFrame.Shadow.Sunken)
        texture_gl.addWidget(tex_sep)

        # Zoom/Offset/Rotation container — label directly above slider, minimal gap
        _tf = QWidget()
        _tf_layout = QVBoxLayout(_tf)
        _tf_layout.setContentsMargins(0, 0, 0, 0)
        _tf_layout.setSpacing(4)  # Gap between control groups

        def _ctrl(label_text):
            """Return a QVBoxLayout with 0 spacing for label + slider row."""
            vl = QVBoxLayout()
            vl.setSpacing(0)
            vl.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text)
            lbl.setContentsMargins(0, 0, 0, 0)
            vl.addWidget(lbl)
            return vl

        # Zoom
        zoom_vl = _ctrl("Zoom:")
        self._tex_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._tex_zoom_slider.setRange(1, 100)  # 0.05-5.0 in 0.05 steps
        self._tex_zoom_slider.setValue(max(1, round(tool.texture_zoom * 20)))
        self._tex_zoom_slider.valueChanged.connect(self._on_tex_zoom_slider)
        self._tex_zoom_spin = QDoubleSpinBox()
        self._tex_zoom_spin.setRange(0.05, 5.0)
        self._tex_zoom_spin.setSingleStep(0.05)
        self._tex_zoom_spin.setDecimals(2)
        self._tex_zoom_spin.setSuffix("x")
        self._tex_zoom_spin.setValue(tool.texture_zoom)
        self._tex_zoom_spin.setFixedWidth(70)
        self._tex_zoom_spin.valueChanged.connect(self._on_tex_zoom_spin)
        tex_zoom_sl_row = QHBoxLayout()
        tex_zoom_sl_row.addWidget(self._tex_zoom_slider, stretch=1)
        tex_zoom_sl_row.addWidget(self._tex_zoom_spin)
        zoom_vl.addLayout(tex_zoom_sl_row)
        _tf_layout.addLayout(zoom_vl)

        # Offset X
        ox_vl = _ctrl("Offset X:")
        self._tex_offset_x_slider = QSlider(Qt.Orientation.Horizontal)
        self._tex_offset_x_slider.setRange(-500, 500)
        self._tex_offset_x_slider.setValue(int(tool.texture_offset_x))
        self._tex_offset_x_slider.valueChanged.connect(self._on_tex_ox_slider)
        self._tex_offset_x_spin = QDoubleSpinBox()
        self._tex_offset_x_spin.setRange(-500.0, 500.0)
        self._tex_offset_x_spin.setSingleStep(1.0)
        self._tex_offset_x_spin.setDecimals(1)
        self._tex_offset_x_spin.setSuffix(" px")
        self._tex_offset_x_spin.setValue(tool.texture_offset_x)
        self._tex_offset_x_spin.setFixedWidth(80)
        self._tex_offset_x_spin.valueChanged.connect(self._on_tex_ox_spin)
        tex_ox_sl_row = QHBoxLayout()
        tex_ox_sl_row.addWidget(self._tex_offset_x_slider, stretch=1)
        tex_ox_sl_row.addWidget(self._tex_offset_x_spin)
        ox_vl.addLayout(tex_ox_sl_row)
        _tf_layout.addLayout(ox_vl)

        # Offset Y
        oy_vl = _ctrl("Offset Y:")
        self._tex_offset_y_slider = QSlider(Qt.Orientation.Horizontal)
        self._tex_offset_y_slider.setRange(-500, 500)
        self._tex_offset_y_slider.setValue(int(tool.texture_offset_y))
        self._tex_offset_y_slider.valueChanged.connect(self._on_tex_oy_slider)
        self._tex_offset_y_spin = QDoubleSpinBox()
        self._tex_offset_y_spin.setRange(-500.0, 500.0)
        self._tex_offset_y_spin.setSingleStep(1.0)
        self._tex_offset_y_spin.setDecimals(1)
        self._tex_offset_y_spin.setSuffix(" px")
        self._tex_offset_y_spin.setValue(tool.texture_offset_y)
        self._tex_offset_y_spin.setFixedWidth(80)
        self._tex_offset_y_spin.valueChanged.connect(self._on_tex_oy_spin)
        tex_oy_sl_row = QHBoxLayout()
        tex_oy_sl_row.addWidget(self._tex_offset_y_slider, stretch=1)
        tex_oy_sl_row.addWidget(self._tex_offset_y_spin)
        oy_vl.addLayout(tex_oy_sl_row)
        _tf_layout.addLayout(oy_vl)

        # Rotation
        rot_vl = _ctrl("Rotation:")
        self._tex_rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self._tex_rotation_slider.setRange(0, 359)
        self._tex_rotation_slider.setValue(int(tool.texture_rotation))
        self._tex_rotation_slider.valueChanged.connect(self._on_tex_rot_slider)
        self._tex_rotation_spin = QSpinBox()
        self._tex_rotation_spin.setRange(0, 359)
        self._tex_rotation_spin.setSuffix("\u00b0")
        self._tex_rotation_spin.setWrapping(True)
        self._tex_rotation_spin.setValue(int(tool.texture_rotation))
        self._tex_rotation_spin.setFixedWidth(60)
        self._tex_rotation_spin.valueChanged.connect(self._on_tex_rot_spin)
        tex_rot_sl_row = QHBoxLayout()
        tex_rot_sl_row.addWidget(self._tex_rotation_slider, stretch=1)
        tex_rot_sl_row.addWidget(self._tex_rotation_spin)
        rot_vl.addLayout(tex_rot_sl_row)
        _tf_layout.addLayout(rot_vl)

        # Rotation preset buttons
        self._tex_rot_buttons: list[QPushButton] = []
        tex_rot_btn_layout = QHBoxLayout()
        tex_rot_btn_layout.setSpacing(2)
        for deg in (0, 60, 90, 120, 180, 270):
            btn = QPushButton(f"{deg}")
            btn.setCheckable(True)
            btn.setFixedWidth(40)
            btn.setChecked(deg == int(tool.texture_rotation))
            btn.clicked.connect(lambda _, d=deg: self._on_tex_rot_preset(d))
            tex_rot_btn_layout.addWidget(btn)
            self._tex_rot_buttons.append(btn)
        tex_rot_btn_layout.addStretch()
        _tf_layout.addLayout(tex_rot_btn_layout)
        _tf_layout.addStretch()

        texture_gl.addWidget(_tf)
        texture_gl.addStretch()

        layout.addWidget(self._fill_texture_group)

        # ===== Edge Width group (visible only in hex_edge mode) =====
        self._fill_edge_group = QGroupBox("Edge Width")
        edge_gl = QVBoxLayout(self._fill_edge_group)
        edge_gl.setContentsMargins(6, 4, 6, 4)

        edge_gl.addWidget(QLabel("Width:"))
        edge_w_row = QHBoxLayout()
        self._edge_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._edge_width_slider.setRange(1, 40)  # 0.5-20.0 in 0.5 steps
        self._edge_width_slider.setValue(int(tool.edge_width * 2))
        self._edge_width_slider.valueChanged.connect(self._on_edge_width_slider)
        edge_w_row.addWidget(self._edge_width_slider, stretch=1)
        self._edge_width_spin = QDoubleSpinBox()
        self._edge_width_spin.setRange(0.5, 20.0)
        self._edge_width_spin.setSingleStep(0.5)
        self._edge_width_spin.setDecimals(1)
        self._edge_width_spin.setValue(tool.edge_width)
        self._edge_width_spin.setFixedWidth(65)
        self._edge_width_spin.valueChanged.connect(self._on_edge_width_spin)
        edge_w_row.addWidget(self._edge_width_spin)
        edge_gl.addLayout(edge_w_row)

        # Quick width preset buttons
        self._edge_width_buttons: list[QPushButton] = []
        edge_btn_layout = QHBoxLayout()
        edge_btn_layout.setSpacing(3)
        for val in (0.5, 1.0, 2.0, 3.0, 5.0):
            btn = QPushButton(f"{val:g}")
            btn.setCheckable(True)
            btn.setFixedWidth(32)
            btn.setChecked(val == tool.edge_width)
            btn.clicked.connect(
                lambda checked, v=val: self._set_edge_width(v)
            )
            edge_btn_layout.addWidget(btn)
            self._edge_width_buttons.append(btn)
        edge_btn_layout.addStretch()
        edge_gl.addLayout(edge_btn_layout)

        # --- Outline section ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        edge_gl.addWidget(sep)

        self._edge_outline_cb = QCheckBox("Outline")
        self._edge_outline_cb.setChecked(tool.edge_outline)
        self._edge_outline_cb.toggled.connect(self._on_edge_outline_toggled)
        edge_gl.addWidget(self._edge_outline_cb)

        # Outline color + width
        self._edge_outline_row = QWidget()
        ol_vl = QVBoxLayout(self._edge_outline_row)
        ol_vl.setContentsMargins(0, 0, 0, 0)

        ol_color_row = QHBoxLayout()
        ol_color_row.addWidget(QLabel("Color:"))
        self._edge_ol_color_btn = QPushButton()
        self._edge_ol_color_btn.setFixedSize(40, 25)
        update_color_btn(self._edge_ol_color_btn, tool.edge_outline_color)

        def pick_ol_color():
            color = QColorDialog.getColor(
                tool.edge_outline_color, self.dock, "Pick Outline Color"
            )
            if color.isValid():
                tool.edge_outline_color = color
                update_color_btn(self._edge_ol_color_btn, color)

        self._edge_ol_color_btn.clicked.connect(pick_ol_color)
        ol_color_row.addWidget(self._edge_ol_color_btn)
        ol_color_row.addStretch()
        ol_vl.addLayout(ol_color_row)

        ol_vl.addWidget(QLabel("Width:"))
        ol_w_row = QHBoxLayout()
        self._edge_ol_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._edge_ol_width_slider.setRange(1, 50)  # 0.1-5.0 in 0.1 steps
        self._edge_ol_width_slider.setValue(int(tool.edge_outline_width * 10))
        self._edge_ol_width_slider.valueChanged.connect(self._on_edge_ol_width_slider)
        ol_w_row.addWidget(self._edge_ol_width_slider, stretch=1)
        self._edge_ol_width_spin = QDoubleSpinBox()
        self._edge_ol_width_spin.setRange(0.1, 5.0)
        self._edge_ol_width_spin.setSingleStep(0.1)
        self._edge_ol_width_spin.setDecimals(1)
        self._edge_ol_width_spin.setValue(tool.edge_outline_width)
        self._edge_ol_width_spin.setFixedWidth(60)
        self._edge_ol_width_spin.valueChanged.connect(self._on_edge_ol_width_spin)
        ol_w_row.addWidget(self._edge_ol_width_spin)
        ol_vl.addLayout(ol_w_row)

        edge_gl.addWidget(self._edge_outline_row)
        self._edge_outline_row.setEnabled(tool.edge_outline)

        layout.addWidget(self._fill_edge_group)

        # ===== Stipple group (visible only in stipple mode) =====
        self._fill_stipple_group = QGroupBox("Stipple")
        stipple_gl = QVBoxLayout(self._fill_stipple_group)
        stipple_gl.setContentsMargins(6, 4, 6, 4)

        # --- Color sub-container ---
        self._stip_color_container = QWidget()
        stip_color_vl = QVBoxLayout(self._stip_color_container)
        stip_color_vl.setContentsMargins(0, 0, 0, 0)
        stipple_color_row = QHBoxLayout()
        stipple_color_row.addWidget(QLabel("Color:"))
        self._stipple_color_btn = QPushButton()
        self._stipple_color_btn.setFixedSize(40, 25)
        update_color_btn(self._stipple_color_btn, tool.stipple_color)

        def pick_stipple_color():
            color = QColorDialog.getColor(
                tool.stipple_color, self.dock, "Pick Stipple Color"
            )
            if color.isValid():
                tool.stipple_color = color
                update_color_btn(self._stipple_color_btn, color)

        self._stipple_color_btn.clicked.connect(pick_stipple_color)
        stipple_color_row.addWidget(self._stipple_color_btn)
        stipple_color_row.addStretch()
        stip_color_vl.addLayout(stipple_color_row)
        stipple_gl.addWidget(self._stip_color_container)

        # --- Texture sub-container ---
        self._stip_tex_container = QWidget()
        stip_tex_vl = QVBoxLayout(self._stip_tex_container)
        stip_tex_vl.setContentsMargins(0, 0, 0, 0)

        # Game filter
        stg_row = QHBoxLayout()
        stg_row.addWidget(QLabel("Game:"))
        self._stip_tex_game_combo = QComboBox()
        self._stip_tex_game_combo.setMinimumWidth(80)
        self._stip_tex_game_combo.currentTextChanged.connect(self._on_stip_tex_filter_changed)
        stg_row.addWidget(self._stip_tex_game_combo, stretch=1)
        stip_tex_vl.addLayout(stg_row)

        # Category filter
        stc_row = QHBoxLayout()
        stc_row.addWidget(QLabel("Category:"))
        self._stip_tex_cat_combo = QComboBox()
        self._stip_tex_cat_combo.setMinimumWidth(80)
        self._stip_tex_cat_combo.currentTextChanged.connect(self._on_stip_tex_filter_changed)
        stc_row.addWidget(self._stip_tex_cat_combo, stretch=1)
        stip_tex_vl.addLayout(stc_row)

        # Search
        sts_row = QHBoxLayout()
        sts_row.addWidget(QLabel("Search:"))
        self._stip_tex_search = QLineEdit()
        self._stip_tex_search.setPlaceholderText("Filter by name...")
        self._stip_tex_search.textChanged.connect(self._on_stip_tex_filter_changed)
        sts_row.addWidget(self._stip_tex_search, stretch=1)
        stip_tex_vl.addLayout(sts_row)

        # Thumbnail grid
        self._stip_tex_scroll = QScrollArea()
        self._stip_tex_scroll.setWidgetResizable(True)
        self._stip_tex_scroll.setMinimumHeight(80)
        self._stip_tex_scroll.setMaximumHeight(200)
        self._stip_tex_grid_container = QWidget()
        self._stip_tex_grid_layout = QGridLayout(self._stip_tex_grid_container)
        self._stip_tex_grid_layout.setSpacing(4)
        self._stip_tex_grid_layout.setContentsMargins(2, 2, 2, 2)
        self._stip_tex_scroll.setWidget(self._stip_tex_grid_container)
        stip_tex_vl.addWidget(self._stip_tex_scroll)

        # Manager + Expand buttons
        stip_btn_row = QHBoxLayout()
        stip_mgr_btn = QPushButton("Manager...")
        stip_mgr_btn.clicked.connect(self._on_open_texture_manager)
        stip_btn_row.addWidget(stip_mgr_btn)
        self._stip_tex_expand_btn = QPushButton("Expand")
        self._stip_tex_expand_btn.setCheckable(True)
        self._stip_tex_expand_btn.clicked.connect(self._on_toggle_stip_tex_sidebar)
        stip_btn_row.addWidget(self._stip_tex_expand_btn)
        stip_tex_vl.addLayout(stip_btn_row)

        # Separator
        stip_sep = QFrame()
        stip_sep.setFrameShape(QFrame.Shape.HLine)
        stip_sep.setFrameShadow(QFrame.Shadow.Sunken)
        stip_tex_vl.addWidget(stip_sep)

        # Zoom
        stip_tex_vl.addWidget(QLabel("Zoom:"))
        stz_row = QHBoxLayout()
        self._stip_tex_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._stip_tex_zoom_slider.setRange(1, 100)
        self._stip_tex_zoom_slider.setValue(max(1, round(tool.stipple_texture_zoom * 20)))
        self._stip_tex_zoom_slider.valueChanged.connect(self._on_stip_tex_zoom_slider)
        stz_row.addWidget(self._stip_tex_zoom_slider, stretch=1)
        self._stip_tex_zoom_spin = QDoubleSpinBox()
        self._stip_tex_zoom_spin.setRange(0.05, 5.0)
        self._stip_tex_zoom_spin.setSingleStep(0.05)
        self._stip_tex_zoom_spin.setDecimals(2)
        self._stip_tex_zoom_spin.setSuffix("x")
        self._stip_tex_zoom_spin.setValue(tool.stipple_texture_zoom)
        self._stip_tex_zoom_spin.setFixedWidth(70)
        self._stip_tex_zoom_spin.valueChanged.connect(self._on_stip_tex_zoom_spin)
        stz_row.addWidget(self._stip_tex_zoom_spin)
        stip_tex_vl.addLayout(stz_row)

        # Rotation
        stip_tex_vl.addWidget(QLabel("Rotation:"))
        str_row = QHBoxLayout()
        self._stip_tex_rot_slider = QSlider(Qt.Orientation.Horizontal)
        self._stip_tex_rot_slider.setRange(0, 359)
        self._stip_tex_rot_slider.setValue(int(tool.stipple_texture_rotation))
        self._stip_tex_rot_slider.valueChanged.connect(self._on_stip_tex_rot_slider)
        str_row.addWidget(self._stip_tex_rot_slider, stretch=1)
        self._stip_tex_rot_spin = QSpinBox()
        self._stip_tex_rot_spin.setRange(0, 359)
        self._stip_tex_rot_spin.setSuffix("\u00b0")
        self._stip_tex_rot_spin.setWrapping(True)
        self._stip_tex_rot_spin.setValue(int(tool.stipple_texture_rotation))
        self._stip_tex_rot_spin.setFixedWidth(60)
        self._stip_tex_rot_spin.valueChanged.connect(self._on_stip_tex_rot_spin)
        str_row.addWidget(self._stip_tex_rot_spin)
        stip_tex_vl.addLayout(str_row)

        # Separator between texture controls and shared stipple controls
        stip_tex_sep2 = QFrame()
        stip_tex_sep2.setFrameShape(QFrame.Shape.HLine)
        stip_tex_sep2.setFrameShadow(QFrame.Shadow.Sunken)
        stip_tex_vl.addWidget(stip_tex_sep2)

        stipple_gl.addWidget(self._stip_tex_container)

        # Initial visibility driven by Paint Mode toggle
        stip_is_tex = tool.stipple_texture_id is not None
        self._stip_color_container.setVisible(not stip_is_tex)
        self._stip_tex_container.setVisible(stip_is_tex)

        # Spread
        stipple_gl.addWidget(QLabel("Spread (mm):"))
        spread_row = QHBoxLayout()
        self._stipple_spread_slider = QSlider(Qt.Orientation.Horizontal)
        self._stipple_spread_slider.setRange(1, 80)  # 0.5-40.0 in 0.5 steps
        self._stipple_spread_slider.setValue(int(tool.stipple_spread * 2))
        self._stipple_spread_slider.valueChanged.connect(self._on_stipple_spread_slider)
        spread_row.addWidget(self._stipple_spread_slider, stretch=1)
        self._stipple_spread_spin = QDoubleSpinBox()
        self._stipple_spread_spin.setRange(0.5, 40.0)
        self._stipple_spread_spin.setSingleStep(0.5)
        self._stipple_spread_spin.setDecimals(1)
        self._stipple_spread_spin.setSuffix(" mm")
        self._stipple_spread_spin.setValue(tool.stipple_spread)
        self._stipple_spread_spin.setFixedWidth(75)
        self._stipple_spread_spin.valueChanged.connect(self._on_stipple_spread_spin)
        spread_row.addWidget(self._stipple_spread_spin)
        stipple_gl.addLayout(spread_row)

        # Falloff (% of spread with alpha transition)
        stipple_gl.addWidget(QLabel("Falloff:"))
        falloff_row = QHBoxLayout()
        self._stipple_falloff_slider = QSlider(Qt.Orientation.Horizontal)
        self._stipple_falloff_slider.setRange(0, 100)
        self._stipple_falloff_slider.setValue(int(tool.stipple_falloff * 100))
        self._stipple_falloff_slider.valueChanged.connect(self._on_stipple_falloff_slider)
        falloff_row.addWidget(self._stipple_falloff_slider, stretch=1)
        self._stipple_falloff_spin = QSpinBox()
        self._stipple_falloff_spin.setRange(0, 100)
        self._stipple_falloff_spin.setSingleStep(5)
        self._stipple_falloff_spin.setSuffix(" %")
        self._stipple_falloff_spin.setValue(int(tool.stipple_falloff * 100))
        self._stipple_falloff_spin.setFixedWidth(65)
        self._stipple_falloff_spin.valueChanged.connect(self._on_stipple_falloff_spin)
        falloff_row.addWidget(self._stipple_falloff_spin)
        stipple_gl.addLayout(falloff_row)

        # Inset
        stipple_gl.addWidget(QLabel("Inset (mm):"))
        inset_row = QHBoxLayout()
        self._stipple_inset_slider = QSlider(Qt.Orientation.Horizontal)
        self._stipple_inset_slider.setRange(0, 80)  # 0.0-40.0 in 0.5 steps
        self._stipple_inset_slider.setValue(int(tool.stipple_inset * 2))
        self._stipple_inset_slider.valueChanged.connect(self._on_stipple_inset_slider)
        inset_row.addWidget(self._stipple_inset_slider, stretch=1)
        self._stipple_inset_spin = QDoubleSpinBox()
        self._stipple_inset_spin.setRange(0.0, 40.0)
        self._stipple_inset_spin.setSingleStep(0.5)
        self._stipple_inset_spin.setDecimals(1)
        self._stipple_inset_spin.setSuffix(" mm")
        self._stipple_inset_spin.setValue(tool.stipple_inset)
        self._stipple_inset_spin.setFixedWidth(75)
        self._stipple_inset_spin.valueChanged.connect(self._on_stipple_inset_spin)
        inset_row.addWidget(self._stipple_inset_spin)
        stipple_gl.addLayout(inset_row)

        # Inset Falloff (% of inset with alpha transition)
        self._stip_inset_falloff_label = QLabel("Inset Falloff:")
        stipple_gl.addWidget(self._stip_inset_falloff_label)
        inset_falloff_row = QHBoxLayout()
        self._stipple_inset_falloff_slider = QSlider(Qt.Orientation.Horizontal)
        self._stipple_inset_falloff_slider.setRange(0, 100)
        self._stipple_inset_falloff_slider.setValue(
            int(tool.stipple_inset_falloff * 100)
        )
        self._stipple_inset_falloff_slider.valueChanged.connect(
            self._on_stipple_inset_falloff_slider
        )
        inset_falloff_row.addWidget(
            self._stipple_inset_falloff_slider, stretch=1
        )
        self._stipple_inset_falloff_spin = QSpinBox()
        self._stipple_inset_falloff_spin.setRange(0, 100)
        self._stipple_inset_falloff_spin.setSingleStep(5)
        self._stipple_inset_falloff_spin.setSuffix(" %")
        self._stipple_inset_falloff_spin.setValue(
            int(tool.stipple_inset_falloff * 100)
        )
        self._stipple_inset_falloff_spin.setFixedWidth(65)
        self._stipple_inset_falloff_spin.valueChanged.connect(
            self._on_stipple_inset_falloff_spin
        )
        inset_falloff_row.addWidget(self._stipple_inset_falloff_spin)
        stipple_gl.addLayout(inset_falloff_row)

        # Jitter
        stipple_gl.addWidget(QLabel("Jitter:"))
        jitter_row = QHBoxLayout()
        self._stipple_jitter_slider = QSlider(Qt.Orientation.Horizontal)
        self._stipple_jitter_slider.setRange(0, 100)  # 0.0-1.0 in 0.01 steps
        self._stipple_jitter_slider.setValue(int(tool.stipple_jitter * 100))
        self._stipple_jitter_slider.valueChanged.connect(self._on_stipple_jitter_slider)
        jitter_row.addWidget(self._stipple_jitter_slider, stretch=1)
        self._stipple_jitter_spin = QDoubleSpinBox()
        self._stipple_jitter_spin.setRange(0.0, 1.0)
        self._stipple_jitter_spin.setSingleStep(0.05)
        self._stipple_jitter_spin.setDecimals(2)
        self._stipple_jitter_spin.setValue(tool.stipple_jitter)
        self._stipple_jitter_spin.setFixedWidth(60)
        self._stipple_jitter_spin.valueChanged.connect(self._on_stipple_jitter_spin)
        jitter_row.addWidget(self._stipple_jitter_spin)
        stipple_gl.addLayout(jitter_row)

        # Priority (nesting level)
        priority_row = QHBoxLayout()
        priority_row.addWidget(QLabel("Priority:"))
        self._stipple_priority_spin = QSpinBox()
        self._stipple_priority_spin.setRange(0, 10)
        self._stipple_priority_spin.setValue(tool.stipple_priority)
        self._stipple_priority_spin.setFixedWidth(55)
        self._stipple_priority_spin.setToolTip(
            "Nesting level: higher priority zones extend\n"
            "their gradient into lower priority zones"
        )
        self._stipple_priority_spin.valueChanged.connect(self._on_stipple_priority_changed)
        priority_row.addWidget(self._stipple_priority_spin)

        prio_up_btn = QPushButton("\u25B2")
        prio_up_btn.setFixedSize(24, 24)
        prio_up_btn.setToolTip("Increase priority")
        prio_up_btn.clicked.connect(self._on_stipple_priority_up)
        priority_row.addWidget(prio_up_btn)

        prio_dn_btn = QPushButton("\u25BC")
        prio_dn_btn.setFixedSize(24, 24)
        prio_dn_btn.setToolTip("Decrease priority")
        prio_dn_btn.clicked.connect(self._on_stipple_priority_down)
        priority_row.addWidget(prio_dn_btn)

        priority_row.addStretch()
        stipple_gl.addLayout(priority_row)

        layout.addWidget(self._fill_stipple_group)

        # Populate stipple texture browser
        self._refresh_stip_tex_browser()

        # ===== Radius group =====
        self._fill_radius_group = QGroupBox("Radius")
        radius_gl = QVBoxLayout(self._fill_radius_group)
        radius_gl.setContentsMargins(6, 4, 6, 4)

        radius_gl.addWidget(QLabel("Radius:"))
        radius_slider_row = QHBoxLayout()
        self._radius_slider = QSlider(Qt.Orientation.Horizontal)
        self._radius_slider.setRange(0, 10)
        self._radius_slider.setValue(tool.fill_radius)
        self._radius_slider.valueChanged.connect(self._on_radius_slider)
        radius_slider_row.addWidget(self._radius_slider, stretch=1)
        self._radius_spin = QSpinBox()
        self._radius_spin.setRange(0, 10)
        self._radius_spin.setValue(tool.fill_radius)
        self._radius_spin.setFixedWidth(55)
        self._radius_spin.valueChanged.connect(self._on_radius_value_changed)
        radius_slider_row.addWidget(self._radius_spin)
        radius_gl.addLayout(radius_slider_row)

        self._radius_buttons = []
        radius_btn_layout = QHBoxLayout()
        radius_btn_layout.setSpacing(3)
        for val in (0, 1, 2, 3, 5, 10):
            btn = QPushButton(str(val))
            btn.setCheckable(True)
            btn.setFixedWidth(28)
            btn.setChecked(val == tool.fill_radius)
            btn.clicked.connect(lambda checked, v=val: self._on_radius_btn_clicked(v))
            radius_btn_layout.addWidget(btn)
            self._radius_buttons.append(btn)
        radius_btn_layout.addStretch()
        radius_gl.addLayout(radius_btn_layout)

        layout.addWidget(self._fill_radius_group)

        # ===== Fill All group (Hex mode only) =====
        self._fill_all_group = QGroupBox("Fill All")
        fill_all_gl = QVBoxLayout(self._fill_all_group)
        fill_all_gl.setContentsMargins(6, 4, 6, 4)
        fill_all_btn = QPushButton("Fill Everything")
        fill_all_btn.setToolTip(
            "Fill every hex on the map with the current color or texture"
        )
        fill_all_btn.clicked.connect(self._on_fill_all)
        fill_all_gl.addWidget(fill_all_btn)
        layout.addWidget(self._fill_all_group)

        layout.addStretch()

        # Initialize palette system
        ensure_default_palette()
        self._refresh_palette_combo()
        self._palette_combo.currentTextChanged.connect(self._on_palette_changed)

        # Auto-select "Default" palette
        idx = self._palette_combo.findText("Default")
        if idx >= 0:
            self._palette_combo.setCurrentIndex(idx)
        else:
            self._on_palette_changed(self._palette_combo.currentText())

        # Initialize texture browser
        self._refresh_texture_browser()

        # Apply initial mode visibility
        self._apply_fill_mode_visibility(tool.paint_mode)

        return widget

    # --- Fill mode visibility ---

    def _on_fill_mode_changed(self, button_id: int, checked: bool) -> None:
        """Handle top-level fill mode button toggle (Hex / Dot Color / Coord Color / Hex Edge / Stipple)."""
        if not checked:
            return
        if button_id == 0:  # Hex — delegate to paint-mode subgroup
            paint_id = self._fill_paint_mode_group.checkedId()
            mode = "texture" if paint_id == 1 else "hex_fill"
        elif button_id == 1:
            mode = "dot_color"
        elif button_id == 3:
            mode = "coord_color"
        elif button_id == 4:
            mode = "stipple"
        else:
            mode = "hex_edge"
        self._fill_tool.paint_mode = mode
        self._apply_fill_mode_visibility(mode)

    def _on_fill_paint_mode_changed(self, button_id: int, checked: bool) -> None:
        """Handle Color/Texture paint-mode toggle (applies to Hex and Stipple modes)."""
        if not checked:
            return
        top_id = self._fill_mode_group.checkedId()
        is_tex = button_id == 1
        if top_id == 4:
            # Stipple mode: toggle stipple texture on/off, keep paint_mode "stipple"
            if is_tex:
                if self._stip_selected_texture:
                    self._fill_tool.stipple_texture_id = self._stip_selected_texture.id
            else:
                self._fill_tool.stipple_texture_id = None
            self._apply_fill_mode_visibility("stipple")
        else:
            # Hex mode: switch between hex_fill and texture
            mode = "texture" if is_tex else "hex_fill"
            self._fill_tool.paint_mode = mode
            self._apply_fill_mode_visibility(mode)

    def _apply_fill_mode_visibility(self, mode: str) -> None:
        """Show/hide Color and Texture groups based on current mode."""
        is_stip_tex = (
            mode == "stipple"
            and self._fill_paint_mode_group.checkedId() == 1
        )
        self._fill_color_group.setVisible(mode in ("hex_fill", "dot_color", "coord_color", "hex_edge"))
        self._fill_texture_group.setVisible(mode == "texture")
        self._fill_edge_group.setVisible(mode == "hex_edge")
        self._fill_stipple_group.setVisible(mode == "stipple")
        self._fill_radius_group.setEnabled(mode in ("hex_fill", "texture", "dot_color", "coord_color", "stipple"))
        # Paint Mode subgroup enabled for Hex and Stipple
        self._fill_paint_mode_container.setEnabled(mode in ("hex_fill", "texture", "stipple"))
        # Fill All only available in Hex mode (color or texture)
        self._fill_all_group.setVisible(mode in ("hex_fill", "texture"))
        # Stipple sub-containers: color vs texture
        if mode == "stipple":
            self._stip_color_container.setVisible(not is_stip_tex)
            self._stip_tex_container.setVisible(is_stip_tex)

    # --- Radius slider/spin sync ---

    def _on_radius_slider(self, value: int) -> None:
        self._fill_tool.fill_radius = value
        self._radius_spin.blockSignals(True)
        self._radius_spin.setValue(value)
        self._radius_spin.blockSignals(False)
        self._sync_radius_buttons(value)

    # --- Texture slider/spin sync ---

    def _on_tex_zoom_slider(self, value: int) -> None:
        real_val = value * 0.05
        self._fill_tool.texture_zoom = real_val
        self._tex_zoom_spin.blockSignals(True)
        self._tex_zoom_spin.setValue(real_val)
        self._tex_zoom_spin.blockSignals(False)

    def _on_tex_zoom_spin(self, value: float) -> None:
        self._fill_tool.texture_zoom = value
        self._tex_zoom_slider.blockSignals(True)
        self._tex_zoom_slider.setValue(max(1, round(value * 20)))
        self._tex_zoom_slider.blockSignals(False)

    def _on_tex_ox_slider(self, value: int) -> None:
        self._fill_tool.texture_offset_x = float(value)
        self._tex_offset_x_spin.blockSignals(True)
        self._tex_offset_x_spin.setValue(float(value))
        self._tex_offset_x_spin.blockSignals(False)

    def _on_tex_ox_spin(self, value: float) -> None:
        self._fill_tool.texture_offset_x = value
        self._tex_offset_x_slider.blockSignals(True)
        self._tex_offset_x_slider.setValue(int(value))
        self._tex_offset_x_slider.blockSignals(False)

    def _on_tex_oy_slider(self, value: int) -> None:
        self._fill_tool.texture_offset_y = float(value)
        self._tex_offset_y_spin.blockSignals(True)
        self._tex_offset_y_spin.setValue(float(value))
        self._tex_offset_y_spin.blockSignals(False)

    def _on_tex_oy_spin(self, value: float) -> None:
        self._fill_tool.texture_offset_y = value
        self._tex_offset_y_slider.blockSignals(True)
        self._tex_offset_y_slider.setValue(int(value))
        self._tex_offset_y_slider.blockSignals(False)

    def _on_tex_rot_slider(self, value: int) -> None:
        self._fill_tool.texture_rotation = float(value)
        self._tex_rotation_spin.blockSignals(True)
        self._tex_rotation_spin.setValue(value)
        self._tex_rotation_spin.blockSignals(False)
        self._sync_tex_rot_buttons(value)

    def _on_tex_rot_spin(self, value: int) -> None:
        self._fill_tool.texture_rotation = float(value)
        self._tex_rotation_slider.blockSignals(True)
        self._tex_rotation_slider.setValue(value)
        self._tex_rotation_slider.blockSignals(False)
        self._sync_tex_rot_buttons(value)

    # --- Edge width slider/spin sync ---

    def _on_edge_width_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._fill_tool.edge_width = real_val
        self._edge_width_spin.blockSignals(True)
        self._edge_width_spin.setValue(real_val)
        self._edge_width_spin.blockSignals(False)
        self._sync_edge_width_buttons(real_val)

    def _on_edge_width_spin(self, value: float) -> None:
        self._fill_tool.edge_width = value
        self._edge_width_slider.blockSignals(True)
        self._edge_width_slider.setValue(int(value * 2))
        self._edge_width_slider.blockSignals(False)
        self._sync_edge_width_buttons(value)

    def _set_edge_width(self, value: float) -> None:
        """Set edge width from preset button (syncs slider + spin)."""
        self._fill_tool.edge_width = value
        self._edge_width_slider.blockSignals(True)
        self._edge_width_slider.setValue(int(value * 2))
        self._edge_width_slider.blockSignals(False)
        self._edge_width_spin.blockSignals(True)
        self._edge_width_spin.setValue(value)
        self._edge_width_spin.blockSignals(False)
        self._sync_edge_width_buttons(value)

    def _sync_edge_width_buttons(self, value: float) -> None:
        """Highlight the preset button matching the current edge width value."""
        _PRESETS = (0.5, 1.0, 2.0, 3.0, 5.0)
        for i, preset in enumerate(_PRESETS):
            self._edge_width_buttons[i].setChecked(preset == value)

    def _on_edge_ol_width_slider(self, value: int) -> None:
        real_val = value / 10.0
        self._fill_tool.edge_outline_width = real_val
        self._edge_ol_width_spin.blockSignals(True)
        self._edge_ol_width_spin.setValue(real_val)
        self._edge_ol_width_spin.blockSignals(False)

    def _on_edge_ol_width_spin(self, value: float) -> None:
        self._fill_tool.edge_outline_width = value
        self._edge_ol_width_slider.blockSignals(True)
        self._edge_ol_width_slider.setValue(int(value * 10))
        self._edge_ol_width_slider.blockSignals(False)

    def _on_edge_outline_toggled(self, checked: bool) -> None:
        """Handle edge outline checkbox toggle."""
        self._fill_tool.edge_outline = checked
        self._edge_outline_row.setEnabled(checked)

    # --- Stipple slider/spin sync ---

    def _on_stipple_inset_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._fill_tool.stipple_inset = real_val
        self._stipple_inset_spin.blockSignals(True)
        self._stipple_inset_spin.setValue(real_val)
        self._stipple_inset_spin.blockSignals(False)

    def _on_stipple_inset_spin(self, value: float) -> None:
        self._fill_tool.stipple_inset = value
        self._stipple_inset_slider.blockSignals(True)
        self._stipple_inset_slider.setValue(int(value * 2))
        self._stipple_inset_slider.blockSignals(False)

    def _on_stipple_inset_falloff_slider(self, value: int) -> None:
        self._fill_tool.stipple_inset_falloff = value / 100.0
        self._stipple_inset_falloff_spin.blockSignals(True)
        self._stipple_inset_falloff_spin.setValue(value)
        self._stipple_inset_falloff_spin.blockSignals(False)

    def _on_stipple_inset_falloff_spin(self, value: int) -> None:
        self._fill_tool.stipple_inset_falloff = value / 100.0
        self._stipple_inset_falloff_slider.blockSignals(True)
        self._stipple_inset_falloff_slider.setValue(value)
        self._stipple_inset_falloff_slider.blockSignals(False)

    def _on_stipple_spread_slider(self, value: int) -> None:
        real_val = value / 2.0
        self._fill_tool.stipple_spread = real_val
        self._stipple_spread_spin.blockSignals(True)
        self._stipple_spread_spin.setValue(real_val)
        self._stipple_spread_spin.blockSignals(False)

    def _on_stipple_spread_spin(self, value: float) -> None:
        self._fill_tool.stipple_spread = value
        self._stipple_spread_slider.blockSignals(True)
        self._stipple_spread_slider.setValue(int(value * 2))
        self._stipple_spread_slider.blockSignals(False)

    def _on_stipple_falloff_slider(self, value: int) -> None:
        self._fill_tool.stipple_falloff = value / 100.0
        self._stipple_falloff_spin.blockSignals(True)
        self._stipple_falloff_spin.setValue(value)
        self._stipple_falloff_spin.blockSignals(False)

    def _on_stipple_falloff_spin(self, value: int) -> None:
        self._fill_tool.stipple_falloff = value / 100.0
        self._stipple_falloff_slider.blockSignals(True)
        self._stipple_falloff_slider.setValue(value)
        self._stipple_falloff_slider.blockSignals(False)

    def _on_stipple_jitter_slider(self, value: int) -> None:
        real_val = value / 100.0
        self._fill_tool.stipple_jitter = real_val
        self._stipple_jitter_spin.blockSignals(True)
        self._stipple_jitter_spin.setValue(real_val)
        self._stipple_jitter_spin.blockSignals(False)

    def _on_stipple_jitter_spin(self, value: float) -> None:
        self._fill_tool.stipple_jitter = value
        self._stipple_jitter_slider.blockSignals(True)
        self._stipple_jitter_slider.setValue(int(value * 100))
        self._stipple_jitter_slider.blockSignals(False)

    def _on_stipple_priority_changed(self, value: int) -> None:
        self._fill_tool.stipple_priority = value

    def _on_stipple_priority_up(self) -> None:
        cur = self._stipple_priority_spin.value()
        if cur < self._stipple_priority_spin.maximum():
            self._stipple_priority_spin.setValue(cur + 1)

    def _on_stipple_priority_down(self) -> None:
        cur = self._stipple_priority_spin.value()
        if cur > self._stipple_priority_spin.minimum():
            self._stipple_priority_spin.setValue(cur - 1)

    # --- Stipple texture browser ---

    def _refresh_stip_tex_browser(self) -> None:
        """Reload texture catalog and refresh stipple texture filter combos + grid."""
        if self._texture_catalog is None:
            self._texture_catalog = load_texture_catalog()
        self._refresh_stip_tex_filter_combos()
        self._rebuild_stip_tex_browser()

    def _refresh_stip_tex_filter_combos(self) -> None:
        """Update game and category filter combos for stipple textures."""
        self._stip_tex_game_combo.blockSignals(True)
        current_game = self._stip_tex_game_combo.currentText()
        self._stip_tex_game_combo.clear()
        self._stip_tex_game_combo.addItem("All")
        for g in self._texture_catalog.games():
            self._stip_tex_game_combo.addItem(g)
        idx = self._stip_tex_game_combo.findText(current_game)
        if idx >= 0:
            self._stip_tex_game_combo.setCurrentIndex(idx)
        self._stip_tex_game_combo.blockSignals(False)

        self._stip_tex_cat_combo.blockSignals(True)
        current_cat = self._stip_tex_cat_combo.currentText()
        self._stip_tex_cat_combo.clear()
        self._stip_tex_cat_combo.addItem("All")
        for cat in self._texture_catalog.categories():
            self._stip_tex_cat_combo.addItem(cat)
        idx = self._stip_tex_cat_combo.findText(current_cat)
        if idx >= 0:
            self._stip_tex_cat_combo.setCurrentIndex(idx)
        self._stip_tex_cat_combo.blockSignals(False)

    def _filtered_stip_tex(self) -> list[LibraryTexture]:
        """Return textures matching stipple texture browser filter."""
        if not self._texture_catalog:
            return []
        game = self._stip_tex_game_combo.currentText()
        category = self._stip_tex_cat_combo.currentText()
        search = self._stip_tex_search.text().strip().lower()
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

    def _rebuild_stip_tex_browser(self) -> None:
        """Rebuild stipple texture thumbnail grid from filtered results."""
        for btn in self._stip_tex_buttons.values():
            try:
                self._stip_tex_grid_layout.removeWidget(btn)
                btn.deleteLater()
            except RuntimeError:
                pass  # C++ object already deleted (parent widget destroyed)
        self._stip_tex_buttons.clear()

        filtered = self._filtered_stip_tex()
        cols = 3
        for i, tex in enumerate(filtered):
            btn = self._make_stip_tex_thumb(tex)
            row = i // cols
            col = i % cols
            self._stip_tex_grid_layout.addWidget(btn, row, col)
            self._stip_tex_buttons[tex.id] = btn
        self._update_stip_tex_selection()

    def _make_stip_tex_thumb(self, tex: LibraryTexture) -> QToolButton:
        """Create a thumbnail button for the stipple texture browser."""
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
        btn.clicked.connect(lambda checked=False, t=tex: self._on_stip_tex_clicked(t))
        return btn

    def _on_stip_tex_clicked(self, tex: LibraryTexture) -> None:
        """Select a texture from the stipple texture browser."""
        self._stip_selected_texture = tex
        self._fill_tool.stipple_texture_id = tex.id
        self._update_stip_tex_selection()
        if self._stip_tex_sidebar and self._stip_tex_sidebar.isVisible():
            self._stip_tex_sidebar.set_selected(tex.id)

    def _update_stip_tex_selection(self) -> None:
        """Update button borders to show selected stipple texture."""
        for tex_id, btn in self._stip_tex_buttons.items():
            if self._stip_selected_texture and tex_id == self._stip_selected_texture.id:
                btn.setStyleSheet(
                    "QToolButton { padding: 1px; border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 1px; }")

    def _on_stip_tex_filter_changed(self) -> None:
        """Rebuild stipple texture browser when filter changes."""
        self._rebuild_stip_tex_browser()
        self._sync_stip_tex_sidebar()

    # --- Stipple texture zoom/rotation ---

    def _on_stip_tex_zoom_slider(self, value: int) -> None:
        real_val = value * 0.05
        self._fill_tool.stipple_texture_zoom = real_val
        self._stip_tex_zoom_spin.blockSignals(True)
        self._stip_tex_zoom_spin.setValue(real_val)
        self._stip_tex_zoom_spin.blockSignals(False)

    def _on_stip_tex_zoom_spin(self, value: float) -> None:
        self._fill_tool.stipple_texture_zoom = value
        self._stip_tex_zoom_slider.blockSignals(True)
        self._stip_tex_zoom_slider.setValue(max(1, round(value * 20)))
        self._stip_tex_zoom_slider.blockSignals(False)

    def _on_stip_tex_rot_slider(self, value: int) -> None:
        self._fill_tool.stipple_texture_rotation = float(value)
        self._stip_tex_rot_spin.blockSignals(True)
        self._stip_tex_rot_spin.setValue(value)
        self._stip_tex_rot_spin.blockSignals(False)

    def _on_stip_tex_rot_spin(self, value: int) -> None:
        self._fill_tool.stipple_texture_rotation = float(value)
        self._stip_tex_rot_slider.blockSignals(True)
        self._stip_tex_rot_slider.setValue(value)
        self._stip_tex_rot_slider.blockSignals(False)

    # --- Stipple texture sidebar ---

    def _on_toggle_stip_tex_sidebar(self, checked: bool) -> None:
        """Toggle the expanded stipple texture browser sidebar."""
        if checked:
            self.dock._save_panel_width()
            if not self._stip_tex_sidebar:
                self._stip_tex_sidebar = TextureBrowserSidebar(self.dock.window())
                self._stip_tex_sidebar.texture_clicked.connect(self._on_stip_tex_sidebar_clicked)
                self._stip_tex_sidebar.closed.connect(self._on_stip_tex_sidebar_closed)
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea, self._stip_tex_sidebar
                )
                main_win.splitDockWidget(
                    self.dock, self._stip_tex_sidebar, Qt.Orientation.Horizontal
                )
            self._stip_tex_sidebar.show()
            self._sync_stip_tex_sidebar()
        else:
            if self._stip_tex_sidebar:
                self._stip_tex_sidebar.hide()
            self.dock._restore_panel_width()

    def _sync_stip_tex_sidebar(self) -> None:
        """Update stipple texture sidebar contents from current filter state."""
        if not self._stip_tex_sidebar or not self._stip_tex_sidebar.isVisible():
            return
        filtered = self._filtered_stip_tex()
        selected_id = (
            self._stip_selected_texture.id if self._stip_selected_texture else None
        )
        self._stip_tex_sidebar.set_textures(filtered, selected_id)

    def _on_stip_tex_sidebar_clicked(self, tex: LibraryTexture) -> None:
        """Handle texture selection from the stipple texture sidebar."""
        self._on_stip_tex_clicked(tex)

    def _on_stip_tex_sidebar_closed(self) -> None:
        """Handle stipple texture sidebar close button."""
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_stip_tex_expand_btn"):
                self._stip_tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # --- Texture browser ---

    def _refresh_texture_browser(self):
        """Reload texture catalog and refresh filter combos + grid."""
        self._texture_catalog = load_texture_catalog()
        self._refresh_texture_filter_combos()
        self._rebuild_texture_browser()

    def _refresh_texture_filter_combos(self):
        """Update the game and category filter combos for textures."""
        self._tex_game_combo.blockSignals(True)
        current_game = self._tex_game_combo.currentText()
        self._tex_game_combo.clear()
        self._tex_game_combo.addItem("All")
        for g in self._texture_catalog.games():
            self._tex_game_combo.addItem(g)
        idx = self._tex_game_combo.findText(current_game)
        if idx >= 0:
            self._tex_game_combo.setCurrentIndex(idx)
        self._tex_game_combo.blockSignals(False)

        self._tex_category_combo.blockSignals(True)
        current_cat = self._tex_category_combo.currentText()
        self._tex_category_combo.clear()
        self._tex_category_combo.addItem("All")
        for cat in self._texture_catalog.categories():
            self._tex_category_combo.addItem(cat)
        idx = self._tex_category_combo.findText(current_cat)
        if idx >= 0:
            self._tex_category_combo.setCurrentIndex(idx)
        self._tex_category_combo.blockSignals(False)

    def _filtered_browser_textures(self) -> list[LibraryTexture]:
        """Return textures matching current browser filter."""
        game = self._tex_game_combo.currentText()
        category = self._tex_category_combo.currentText()
        search = self._tex_search_edit.text().strip().lower()

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

    def _rebuild_texture_browser(self):
        """Rebuild texture thumbnail grid from filtered results."""
        for btn in self._texture_browser_buttons.values():
            self._tex_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._texture_browser_buttons.clear()

        filtered = self._filtered_browser_textures()
        cols = 3
        for i, tex in enumerate(filtered):
            btn = self._make_texture_thumb(tex)
            row = i // cols
            col = i % cols
            self._tex_grid_layout.addWidget(btn, row, col)
            self._texture_browser_buttons[tex.id] = btn

        self._update_texture_selection()

    def _make_texture_thumb(self, tex: LibraryTexture) -> QToolButton:
        """Create a 48x48 thumbnail button for the texture browser."""
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
        """Get or create a cached 48x48 thumbnail for a texture."""
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

    def _on_texture_clicked(self, tex: LibraryTexture):
        """Select a texture from the browser."""
        self._selected_browser_texture = tex
        self._fill_tool.current_texture_id = tex.id
        self._update_texture_selection()
        # Sync sidebar selection
        if self._texture_sidebar and self._texture_sidebar.isVisible():
            self._texture_sidebar.set_selected(tex.id)

    def _update_texture_selection(self):
        """Update button borders to show selected texture."""
        for tex_id, btn in self._texture_browser_buttons.items():
            if self._selected_browser_texture and tex_id == self._selected_browser_texture.id:
                btn.setStyleSheet(
                    "QToolButton { padding: 1px; border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 1px; }")

    def _on_texture_filter_changed(self):
        """Rebuild texture browser when filter changes."""
        self._rebuild_texture_browser()
        self._sync_texture_sidebar()

    def _on_open_texture_manager(self):
        """Open the Texture Manager dialog."""
        dialog = TextureManagerDialog(self.dock)
        dialog.catalog_changed.connect(self._on_texture_manager_changed)
        dialog.exec()

    def _on_texture_manager_changed(self):
        """Refresh texture browser when the manager changes the catalog."""
        self._texture_thumb_cache.clear()
        if self._texture_sidebar:
            self._texture_sidebar.invalidate_cache()
        if self._stip_tex_sidebar:
            self._stip_tex_sidebar.invalidate_cache()
        self._refresh_texture_browser()
        self._sync_texture_sidebar()
        self._refresh_stip_tex_browser()
        self._sync_stip_tex_sidebar()

    def refresh_texture_catalog(self) -> None:
        """Reload texture catalog (called on tool switch to pick up imports from other tools)."""
        if not hasattr(self, "_texture_catalog"):
            return
        self._refresh_texture_browser()
        self._sync_texture_sidebar()
        self._refresh_stip_tex_browser()
        self._sync_stip_tex_sidebar()

    def refresh_palette_catalog(self) -> None:
        """Reload palette combo (called when the palette editor reports changes)."""
        if not hasattr(self, "_palette_combo"):
            return
        self._refresh_palette_combo()

    def _on_tex_rot_preset(self, degrees: int):
        """Apply a rotation preset to texture rotation slider + spin."""
        self._fill_tool.texture_rotation = float(degrees)
        self._tex_rotation_slider.blockSignals(True)
        self._tex_rotation_slider.setValue(degrees)
        self._tex_rotation_slider.blockSignals(False)
        self._tex_rotation_spin.blockSignals(True)
        self._tex_rotation_spin.setValue(degrees)
        self._tex_rotation_spin.blockSignals(False)
        self._sync_tex_rot_buttons(degrees)

    def _sync_tex_rot_buttons(self, value: int) -> None:
        """Highlight the preset button matching the current texture rotation value."""
        _PRESETS = (0, 60, 90, 120, 180, 270)
        for i, preset in enumerate(_PRESETS):
            self._tex_rot_buttons[i].setChecked(preset == value)

    # --- Texture sidebar ---

    def _on_toggle_texture_sidebar(self, checked: bool):
        """Toggle the expanded texture browser sidebar."""
        if checked:
            self.dock._save_panel_width()
            if not self._texture_sidebar:
                self._texture_sidebar = TextureBrowserSidebar(self.dock.window())
                self._texture_sidebar.texture_clicked.connect(self._on_tex_sidebar_clicked)
                self._texture_sidebar.closed.connect(self._on_tex_sidebar_closed)
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea, self._texture_sidebar
                )
                main_win.splitDockWidget(
                    self.dock, self._texture_sidebar, Qt.Orientation.Horizontal
                )
            self._texture_sidebar.show()
            self._sync_texture_sidebar()
        else:
            if self._texture_sidebar:
                self._texture_sidebar.hide()
            self.dock._restore_panel_width()

    def _sync_texture_sidebar(self):
        """Update texture sidebar contents from current filter state."""
        if not self._texture_sidebar or not self._texture_sidebar.isVisible():
            return
        filtered = self._filtered_browser_textures()
        selected_id = (
            self._selected_browser_texture.id
            if self._selected_browser_texture
            else None
        )
        self._texture_sidebar.set_textures(filtered, selected_id)

    def _on_tex_sidebar_clicked(self, tex: LibraryTexture):
        """Handle texture selection from the sidebar."""
        self._on_texture_clicked(tex)

    def _on_tex_sidebar_closed(self):
        """Handle texture sidebar close button."""
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_tex_expand_btn"):
                self._tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass  # C++ object already deleted

    def close_sidebar(self):
        """Hide all texture sidebars and uncheck expand buttons."""
        if self._texture_sidebar:
            self._texture_sidebar.hide()
        if self._stip_tex_sidebar:
            self._stip_tex_sidebar.hide()
        try:
            if hasattr(self, "_tex_expand_btn"):
                self._tex_expand_btn.setChecked(False)
            if hasattr(self, "_stip_tex_expand_btn"):
                self._stip_tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass  # C++ object already deleted

    # --- Palette management ---

    def _refresh_palette_combo(self):
        """Refresh the palette combo box from disk."""
        self._palette_combo.blockSignals(True)
        current = self._palette_combo.currentText()
        self._palette_combo.clear()
        for name in list_palettes():
            self._palette_combo.addItem(name)
        # Restore selection
        idx = self._palette_combo.findText(current)
        if idx >= 0:
            self._palette_combo.setCurrentIndex(idx)
        self._palette_combo.blockSignals(False)

    def _on_palette_changed(self, name: str):
        """Load a palette and rebuild the color grid."""
        if not name:
            return
        try:
            self._current_palette = load_palette(name)
        except FileNotFoundError:
            self._current_palette = None
        self._selected_palette_idx = -1
        self._rebuild_color_grid()

    def _rebuild_color_grid(self):
        """Rebuild the color button grid from current palette."""
        # Clear existing buttons
        for btn in self._palette_color_buttons:
            self._color_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._palette_color_buttons.clear()

        if not self._current_palette:
            return

        for i, pc in enumerate(self._current_palette.colors):
            btn = QPushButton()
            btn.setFixedSize(36, 36)
            btn.setToolTip(pc.name)
            self._style_palette_btn(btn, pc.color, selected=False)
            btn.clicked.connect(
                lambda checked, idx=i: self._on_palette_color_clicked(idx)
            )
            row = i // PALETTE_GRID_COLS
            col = i % PALETTE_GRID_COLS
            self._color_grid_layout.addWidget(btn, row, col)
            self._palette_color_buttons.append(btn)

    def _style_palette_btn(self, btn: QPushButton, color_hex: str, selected: bool):
        """Style a palette color button."""
        border = "2px solid #00aaff" if selected else "1px solid #555"
        btn.setStyleSheet(
            f"background-color: {color_hex}; border: {border};"
        )

    def _on_palette_color_clicked(self, idx: int):
        """Select a palette color and set it as fill color."""
        if not self._current_palette or idx >= len(self._current_palette.colors):
            return

        # Deselect previous
        if 0 <= self._selected_palette_idx < len(self._palette_color_buttons):
            old_pc = self._current_palette.colors[self._selected_palette_idx]
            self._style_palette_btn(
                self._palette_color_buttons[self._selected_palette_idx],
                old_pc.color,
                selected=False,
            )

        # Select new
        self._selected_palette_idx = idx
        pc = self._current_palette.colors[idx]
        self._style_palette_btn(self._palette_color_buttons[idx], pc.color, selected=True)

        # Set fill color
        color = QColor(pc.color)
        self._fill_tool.current_color = color
        update_color_btn(self._fill_color_btn, color)

    # --- Radius helpers ---

    def _on_radius_btn_clicked(self, value: int) -> None:
        self._fill_tool.fill_radius = value
        self._radius_slider.blockSignals(True)
        self._radius_slider.setValue(value)
        self._radius_slider.blockSignals(False)
        self._radius_spin.blockSignals(True)
        self._radius_spin.setValue(value)
        self._radius_spin.blockSignals(False)
        self._sync_radius_buttons(value)

    def _on_radius_value_changed(self, value: int) -> None:
        self._fill_tool.fill_radius = value
        self._radius_slider.blockSignals(True)
        self._radius_slider.setValue(value)
        self._radius_slider.blockSignals(False)
        self._sync_radius_buttons(value)

    def _sync_radius_buttons(self, value: int) -> None:
        for i, preset in enumerate(self._RADIUS_PRESETS):
            self._radius_buttons[i].setChecked(preset == value)

    # --- Fill All ---

    def _on_fill_all(self) -> None:
        """Fill every hex on the map with the current color or texture."""
        from app.layers.fill_layer import FillLayer, HexTexture
        tool = self._fill_tool
        if tool is None:
            return
        main_win = self.dock.window()
        layer = main_win._project.layer_stack.active_layer
        if not isinstance(layer, FillLayer):
            return
        all_hexes = main_win._project.grid_config.get_all_hexes()
        if tool.paint_mode == "texture" and tool.current_texture_id:
            texture = HexTexture(
                texture_id=tool.current_texture_id,
                zoom=tool.texture_zoom,
                offset_x=tool.texture_offset_x,
                offset_y=tool.texture_offset_y,
                rotation=tool.texture_rotation,
            )
            cmd = FillAllCommand(layer, all_hexes, color=None, texture=texture)
        else:
            cmd = FillAllCommand(layer, all_hexes, color=tool.current_color, texture=None)
        main_win._command_stack.execute(cmd)
