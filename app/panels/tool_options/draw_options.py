"""Draw tool options builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
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
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.commands.draw_commands import (
    DrawAddChannelCommand,
    DrawEditChannelCommand,
    DrawMoveChannelCommand,
    DrawRemoveChannelCommand,
    EditDrawLayerEffectsCommand,
)
from app.io.brush_library import (
    BrushCatalog,
    LibraryBrush,
    load_catalog as load_brush_catalog,
)
from app.panels.brush_manager_dialog import BrushManagerDialog
from app.panels.texture_manager_dialog import TextureManagerDialog
from app.panels.tool_options.sidebar_widgets import BrushBrowserSidebar, ChannelBrowserSidebar, TextureBrowserSidebar
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
from app.layers.draw_layer import DrawLayer
from app.models.draw_object import DrawChannel
from app.panels.tool_options.helpers import PALETTE_GRID_COLS, update_color_btn
from app.tools.draw_tool import DrawTool

if TYPE_CHECKING:
    from app.panels.tool_options.dock_widget import ToolOptionsPanel

_BRUSH_THUMB = 48
_BRUSH_COLS = 3
_TEX_THUMB = 48
_TEX_COLS = 3


class DrawOptions:
    """Builds and manages the draw tool options UI."""

    def __init__(self, dock: ToolOptionsPanel) -> None:
        self.dock = dock
        self._tool: DrawTool | None = None
        self._brush_catalog: BrushCatalog | None = None
        self._brush_buttons: dict[str, QToolButton] = {}
        self._brush_thumb_cache: dict[str, QPixmap] = {}
        self._texture_catalog: TextureCatalog | None = None
        self._texture_buttons: dict[str, QToolButton] = {}
        self._texture_thumb_cache: dict[str, QPixmap] = {}
        self._brush_sidebar = None
        self._texture_sidebar: TextureBrowserSidebar | None = None
        self._channel_sidebar: ChannelBrowserSidebar | None = None
        self._d_selected_palette_idx: int = -1
        self._d_current_palette: ColorPalette | None = None
        self._d_palette_color_buttons: list[QPushButton] = []
        self._channel_list: QListWidget | None = None
        self._ch_mode_group: QButtonGroup | None = None
        self._updating_ui: bool = False

    def create(self, tool: DrawTool) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        self._tool = tool
        self._brush_buttons = {}
        self._texture_buttons = {}
        self._updating_ui = False

        self._brush_catalog = load_brush_catalog()
        self._texture_catalog = load_texture_catalog()

        # ===== Mode group (Draw / Erase) =====
        mode_group = QGroupBox("Mode")
        mode_gl = QVBoxLayout(mode_group)
        mode_gl.setContentsMargins(6, 4, 6, 4)

        de_row = QHBoxLayout()
        draw_btn = QPushButton("Draw")
        draw_btn.setCheckable(True)
        draw_btn.setChecked(tool.mode == "draw")
        fill_btn = QPushButton("Fill")
        fill_btn.setCheckable(True)
        fill_btn.setChecked(tool.mode == "fill")
        fill_btn.setToolTip(
            "Click to flood-fill the enclosed area in the active channel mask"
        )
        erase_btn = QPushButton("Erase")
        erase_btn.setCheckable(True)
        erase_btn.setChecked(tool.mode == "erase")
        self._de_group = QButtonGroup(widget)
        self._de_group.setExclusive(True)
        self._de_group.addButton(draw_btn, 0)
        self._de_group.addButton(fill_btn, 1)
        self._de_group.addButton(erase_btn, 2)
        self._de_group.idToggled.connect(self._on_de_mode_changed)
        de_row.addWidget(draw_btn)
        de_row.addWidget(fill_btn)
        de_row.addWidget(erase_btn)
        de_row.addStretch()
        mode_gl.addLayout(de_row)

        # Fill expand row (only visible in fill mode)
        self._expand_row_widget = QWidget()
        expand_row = QHBoxLayout(self._expand_row_widget)
        expand_row.setContentsMargins(0, 0, 0, 0)
        expand_row.addWidget(QLabel("Expand:"))
        self._fill_expand_slider = QSlider(Qt.Orientation.Horizontal)
        self._fill_expand_slider.setRange(0, 10)
        self._fill_expand_slider.setValue(tool.fill_expand_px)
        self._fill_expand_slider.setToolTip(
            "Expand the filled area into the surrounding walls by this many pixels "
            "to close hairline gaps at the boundary"
        )
        self._fill_expand_slider.valueChanged.connect(self._on_fill_expand_changed)
        expand_row.addWidget(self._fill_expand_slider, stretch=1)
        self._fill_expand_lbl = QLabel(f"{tool.fill_expand_px} px")
        self._fill_expand_lbl.setFixedWidth(32)
        expand_row.addWidget(self._fill_expand_lbl)
        self._expand_row_widget.setVisible(tool.mode == "fill")
        mode_gl.addWidget(self._expand_row_widget)

        layout.addWidget(mode_group)

        # ===== Channels group =====
        channels_group = QGroupBox("Channels")
        ch_gl = QVBoxLayout(channels_group)
        ch_gl.setContentsMargins(6, 4, 6, 4)

        self._channel_list = QListWidget()
        self._channel_list.setMaximumHeight(200)
        self._channel_list.setMinimumHeight(80)
        self._channel_list.currentRowChanged.connect(self._on_channel_row_changed)
        self._channel_list.itemDoubleClicked.connect(self._on_channel_item_double_clicked)
        ch_gl.addWidget(self._channel_list)

        self._ch_visible_cb = QCheckBox("Visible")
        self._ch_visible_cb.setChecked(True)
        self._ch_visible_cb.toggled.connect(self._on_channel_visible_changed)
        ch_gl.addWidget(self._ch_visible_cb)

        ch_move_row = QHBoxLayout()
        ch_move_row.setSpacing(4)
        up_ch_btn = QPushButton("Up")
        up_ch_btn.setToolTip("Move channel up")
        up_ch_btn.clicked.connect(self._on_move_channel_up)
        dn_ch_btn = QPushButton("Down")
        dn_ch_btn.setToolTip("Move channel down")
        dn_ch_btn.clicked.connect(self._on_move_channel_down)
        ch_move_row.addWidget(up_ch_btn, 1)
        ch_move_row.addWidget(dn_ch_btn, 1)
        ch_gl.addLayout(ch_move_row)

        ch_addrm_row = QHBoxLayout()
        ch_addrm_row.setSpacing(4)
        add_ch_btn = QPushButton("Add")
        add_ch_btn.setToolTip("Add channel")
        add_ch_btn.clicked.connect(self._on_add_channel)
        rm_ch_btn = QPushButton("Del")
        rm_ch_btn.setToolTip("Remove active channel")
        rm_ch_btn.clicked.connect(self._on_remove_channel)
        ch_addrm_row.addWidget(add_ch_btn, 1)
        ch_addrm_row.addWidget(rm_ch_btn, 1)
        ch_gl.addLayout(ch_addrm_row)

        self._ch_expand_btn = QPushButton("Expand")
        self._ch_expand_btn.setCheckable(True)
        self._ch_expand_btn.clicked.connect(self._on_toggle_channel_sidebar)
        ch_gl.addWidget(self._ch_expand_btn)

        layout.addWidget(channels_group)

        # ===== Brush group =====
        brush_group = QGroupBox("Brush")
        brush_gl = QVBoxLayout(brush_group)
        brush_gl.setContentsMargins(6, 4, 6, 4)

        self._brush_scroll = QScrollArea()
        self._brush_scroll.setWidgetResizable(True)
        self._brush_scroll.setMinimumHeight(80)
        self._brush_scroll.setMaximumHeight(200)
        self._brush_grid_container = QWidget()
        self._brush_grid = QGridLayout(self._brush_grid_container)
        self._brush_grid.setSpacing(4)
        self._brush_grid.setContentsMargins(2, 2, 2, 2)
        self._brush_scroll.setWidget(self._brush_grid_container)
        brush_gl.addWidget(self._brush_scroll)

        mgr_row = QHBoxLayout()
        manager_btn = QPushButton("Manager...")
        manager_btn.clicked.connect(self._on_open_brush_manager)
        mgr_row.addWidget(manager_btn)
        self._expand_btn = QPushButton("Expand")
        self._expand_btn.setCheckable(True)
        self._expand_btn.clicked.connect(self._on_toggle_sidebar)
        mgr_row.addWidget(self._expand_btn)
        brush_gl.addLayout(mgr_row)

        # Size
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Size:"))
        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        # Slider stores brush_size * 10  (range 1..5000 = 0.1..500.0 px)
        self._size_slider.setRange(1, 5000)
        self._size_slider.setValue(max(1, round(tool.brush_size * 10)))
        self._size_slider.valueChanged.connect(self._on_size_slider)
        size_row.addWidget(self._size_slider, 1)
        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(0.1, 500.0)
        self._size_spin.setSingleStep(0.1)
        self._size_spin.setDecimals(1)
        self._size_spin.setValue(tool.brush_size)
        self._size_spin.valueChanged.connect(self._on_size_spin)
        size_row.addWidget(self._size_spin)
        brush_gl.addLayout(size_row)

        # Random brush size
        self._random_size_cb = QCheckBox("Random")
        self._random_size_cb.setChecked(tool.random_brush_size)
        self._random_size_cb.toggled.connect(self._on_random_size_toggled)
        brush_gl.addWidget(self._random_size_cb)

        self._random_size_details = QWidget()
        rsd_layout = QVBoxLayout(self._random_size_details)
        rsd_layout.setContentsMargins(12, 0, 0, 0)
        rsd_layout.setSpacing(2)

        min_row = QHBoxLayout()
        min_row.addWidget(QLabel("Min:"))
        self._rnd_min_slider = QSlider(Qt.Orientation.Horizontal)
        self._rnd_min_slider.setRange(1, 5000)
        self._rnd_min_slider.setValue(max(1, round(tool.random_brush_min * 10)))
        self._rnd_min_slider.valueChanged.connect(self._on_rnd_min_slider)
        min_row.addWidget(self._rnd_min_slider, 1)
        self._rnd_min_spin = QDoubleSpinBox()
        self._rnd_min_spin.setRange(0.1, 500.0)
        self._rnd_min_spin.setSingleStep(0.1)
        self._rnd_min_spin.setDecimals(1)
        self._rnd_min_spin.setValue(tool.random_brush_min)
        self._rnd_min_spin.valueChanged.connect(self._on_rnd_min_spin)
        min_row.addWidget(self._rnd_min_spin)
        rsd_layout.addLayout(min_row)

        max_row = QHBoxLayout()
        max_row.addWidget(QLabel("Max:"))
        self._rnd_max_slider = QSlider(Qt.Orientation.Horizontal)
        self._rnd_max_slider.setRange(1, 5000)
        self._rnd_max_slider.setValue(max(1, round(tool.random_brush_max * 10)))
        self._rnd_max_slider.valueChanged.connect(self._on_rnd_max_slider)
        max_row.addWidget(self._rnd_max_slider, 1)
        self._rnd_max_spin = QDoubleSpinBox()
        self._rnd_max_spin.setRange(0.1, 500.0)
        self._rnd_max_spin.setSingleStep(0.1)
        self._rnd_max_spin.setDecimals(1)
        self._rnd_max_spin.setValue(tool.random_brush_max)
        self._rnd_max_spin.valueChanged.connect(self._on_rnd_max_spin)
        max_row.addWidget(self._rnd_max_spin)
        rsd_layout.addLayout(max_row)

        self._random_size_details.setVisible(tool.random_brush_size)
        brush_gl.addWidget(self._random_size_details)
        self._size_slider.setEnabled(not tool.random_brush_size)
        self._size_spin.setEnabled(not tool.random_brush_size)

        # Hardness
        hard_row = QHBoxLayout()
        hard_row.addWidget(QLabel("Hardness:"))
        self._hard_slider = QSlider(Qt.Orientation.Horizontal)
        self._hard_slider.setRange(0, 100)
        self._hard_slider.setValue(int(tool.hardness * 100))
        self._hard_slider.valueChanged.connect(self._on_hard_slider)
        hard_row.addWidget(self._hard_slider, 1)
        self._hard_spin = QDoubleSpinBox()
        self._hard_spin.setRange(0.0, 1.0)
        self._hard_spin.setSingleStep(0.05)
        self._hard_spin.setDecimals(2)
        self._hard_spin.setValue(tool.hardness)
        self._hard_spin.valueChanged.connect(self._on_hard_spin)
        hard_row.addWidget(self._hard_spin)
        brush_gl.addLayout(hard_row)

        # Flow (accumulation rate per stamp)
        flow_row = QHBoxLayout()
        flow_row.addWidget(QLabel("Flow:"))
        self._flow_slider = QSlider(Qt.Orientation.Horizontal)
        self._flow_slider.setRange(1, 100)
        self._flow_slider.setValue(max(1, int(tool.flow * 100)))
        self._flow_slider.valueChanged.connect(self._on_flow_slider)
        flow_row.addWidget(self._flow_slider, 1)
        self._flow_spin = QDoubleSpinBox()
        self._flow_spin.setRange(0.01, 1.0)
        self._flow_spin.setSingleStep(0.05)
        self._flow_spin.setDecimals(2)
        self._flow_spin.setValue(tool.flow)
        self._flow_spin.valueChanged.connect(self._on_flow_spin)
        flow_row.addWidget(self._flow_spin)
        brush_gl.addLayout(flow_row)

        layout.addWidget(brush_group)

        # ===== Channel Content group (Color / Texture toggle) =====
        ch_content_group = QGroupBox("Channel Content")
        ch_content_gl = QVBoxLayout(ch_content_group)
        ch_content_gl.setContentsMargins(6, 4, 6, 4)

        ct_row = QHBoxLayout()
        ch_color_btn = QPushButton("Color")
        ch_color_btn.setCheckable(True)
        ch_tex_btn = QPushButton("Texture")
        ch_tex_btn.setCheckable(True)
        self._ch_mode_group = QButtonGroup(widget)
        self._ch_mode_group.setExclusive(True)
        self._ch_mode_group.addButton(ch_color_btn, 0)
        self._ch_mode_group.addButton(ch_tex_btn, 1)
        self._ch_mode_group.idToggled.connect(self._on_ch_mode_changed)
        ct_row.addWidget(ch_color_btn)
        ct_row.addWidget(ch_tex_btn)
        ct_row.addStretch()
        ch_content_gl.addLayout(ct_row)

        layout.addWidget(ch_content_group)

        # ===== Color group =====
        # Always shown; contains color picker (hidden in texture mode) + opacity.
        self._color_group = QGroupBox("Color")
        color_gl = QVBoxLayout(self._color_group)
        color_gl.setContentsMargins(6, 4, 6, 4)

        # Color picker + palette — hidden when channel is in texture mode.
        self._color_content_widget = QWidget()
        ccw_layout = QVBoxLayout(self._color_content_widget)
        ccw_layout.setContentsMargins(0, 0, 0, 0)
        ccw_layout.setSpacing(4)

        cc_row = QHBoxLayout()
        cc_row.addWidget(QLabel("Color:"))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(40, 25)
        update_color_btn(self._color_btn, QColor("#000000"))
        self._color_btn.clicked.connect(self._on_color_pick)
        cc_row.addWidget(self._color_btn)
        cc_row.addStretch()
        ccw_layout.addLayout(cc_row)

        pal_sep = QFrame()
        pal_sep.setFrameShape(QFrame.Shape.HLine)
        pal_sep.setFrameShadow(QFrame.Shadow.Sunken)
        ccw_layout.addWidget(pal_sep)

        self._d_palette_combo = QComboBox()
        ccw_layout.addWidget(self._d_palette_combo)

        self._d_color_grid_widget = QWidget()
        self._d_color_grid_layout = QGridLayout(self._d_color_grid_widget)
        self._d_color_grid_layout.setSpacing(3)
        self._d_color_grid_layout.setContentsMargins(0, 0, 0, 0)
        ccw_layout.addWidget(self._d_color_grid_widget)

        # Opacity — shown in Color mode (inside _color_content_widget)
        col_op_sep = QFrame()
        col_op_sep.setFrameShape(QFrame.Shape.HLine)
        col_op_sep.setFrameShadow(QFrame.Shadow.Sunken)
        ccw_layout.addWidget(col_op_sep)

        col_op_row = QHBoxLayout()
        col_op_row.addWidget(QLabel("Opacity:"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.valueChanged.connect(self._on_opacity_slider)
        col_op_row.addWidget(self._opacity_slider, 1)
        self._opacity_spin = QDoubleSpinBox()
        self._opacity_spin.setRange(0.0, 1.0)
        self._opacity_spin.setSingleStep(0.05)
        self._opacity_spin.setDecimals(2)
        self._opacity_spin.setValue(1.0)
        self._opacity_spin.valueChanged.connect(self._on_opacity_spin)
        col_op_row.addWidget(self._opacity_spin)
        ccw_layout.addLayout(col_op_row)

        color_gl.addWidget(self._color_content_widget)

        layout.addWidget(self._color_group)

        # Initialize palette system
        self._d_selected_palette_idx = -1
        self._d_current_palette = None
        self._d_palette_color_buttons = []
        ensure_default_palette()
        self._d_refresh_palette_combo()
        self._d_palette_combo.currentTextChanged.connect(self._d_on_palette_changed)
        idx = self._d_palette_combo.findText("Default")
        if idx >= 0:
            self._d_palette_combo.setCurrentIndex(idx)
        else:
            self._d_on_palette_changed(self._d_palette_combo.currentText())

        # ===== Texture group =====
        self._texture_group = QGroupBox("Texture")
        tex_gl = QVBoxLayout(self._texture_group)
        tex_gl.setContentsMargins(6, 4, 6, 4)

        # Game filter
        tex_game_row = QHBoxLayout()
        tex_game_row.addWidget(QLabel("Game:"))
        self._tex_game_combo = QComboBox()
        self._tex_game_combo.setMinimumWidth(80)
        self._tex_game_combo.currentTextChanged.connect(self._on_texture_filter_changed)
        tex_game_row.addWidget(self._tex_game_combo, stretch=1)
        tex_gl.addLayout(tex_game_row)

        # Category filter
        tex_cat_row = QHBoxLayout()
        tex_cat_row.addWidget(QLabel("Category:"))
        self._tex_category_combo = QComboBox()
        self._tex_category_combo.setMinimumWidth(80)
        self._tex_category_combo.currentTextChanged.connect(self._on_texture_filter_changed)
        tex_cat_row.addWidget(self._tex_category_combo, stretch=1)
        tex_gl.addLayout(tex_cat_row)

        # Search filter
        tex_search_row = QHBoxLayout()
        tex_search_row.addWidget(QLabel("Search:"))
        self._tex_search_edit = QLineEdit()
        self._tex_search_edit.setPlaceholderText("Filter by name...")
        self._tex_search_edit.textChanged.connect(self._on_texture_filter_changed)
        tex_search_row.addWidget(self._tex_search_edit, stretch=1)
        tex_gl.addLayout(tex_search_row)

        self._tex_scroll = QScrollArea()
        self._tex_scroll.setWidgetResizable(True)
        self._tex_scroll.setMinimumHeight(80)
        self._tex_scroll.setMaximumHeight(200)
        self._tex_grid_container = QWidget()
        self._tex_grid = QGridLayout(self._tex_grid_container)
        self._tex_grid.setSpacing(4)
        self._tex_grid.setContentsMargins(2, 2, 2, 2)
        self._tex_scroll.setWidget(self._tex_grid_container)
        tex_gl.addWidget(self._tex_scroll)

        tex_mgr_row = QHBoxLayout()
        tex_manager_btn = QPushButton("Manager...")
        tex_manager_btn.clicked.connect(self._on_open_texture_manager)
        tex_mgr_row.addWidget(tex_manager_btn)
        self._tex_expand_btn = QPushButton("Expand")
        self._tex_expand_btn.setCheckable(True)
        self._tex_expand_btn.clicked.connect(self._on_toggle_texture_sidebar)
        tex_mgr_row.addWidget(self._tex_expand_btn)
        tex_gl.addLayout(tex_mgr_row)

        tz_row = QHBoxLayout()
        tz_row.addWidget(QLabel("Zoom:"))
        self._tex_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._tex_zoom_slider.setRange(10, 500)
        self._tex_zoom_slider.setValue(100)
        self._tex_zoom_slider.valueChanged.connect(self._on_tex_zoom_slider)
        tz_row.addWidget(self._tex_zoom_slider, 1)
        self._tex_zoom_spin = QDoubleSpinBox()
        self._tex_zoom_spin.setRange(0.1, 5.0)
        self._tex_zoom_spin.setSingleStep(0.1)
        self._tex_zoom_spin.setDecimals(2)
        self._tex_zoom_spin.setValue(1.0)
        self._tex_zoom_spin.valueChanged.connect(self._on_tex_zoom_spin)
        tz_row.addWidget(self._tex_zoom_spin)
        tex_gl.addLayout(tz_row)

        tr_row = QHBoxLayout()
        tr_row.addWidget(QLabel("Rotation:"))
        self._tex_rot_slider = QSlider(Qt.Orientation.Horizontal)
        self._tex_rot_slider.setRange(0, 359)
        self._tex_rot_slider.setValue(0)
        self._tex_rot_slider.valueChanged.connect(self._on_tex_rot_slider)
        tr_row.addWidget(self._tex_rot_slider, 1)
        self._tex_rot_spin = QDoubleSpinBox()
        self._tex_rot_spin.setRange(0.0, 359.0)
        self._tex_rot_spin.setSingleStep(1.0)
        self._tex_rot_spin.setDecimals(0)
        self._tex_rot_spin.setSuffix("\u00b0")
        self._tex_rot_spin.setValue(0.0)
        self._tex_rot_spin.valueChanged.connect(self._on_tex_rot_spin)
        tr_row.addWidget(self._tex_rot_spin)
        tex_gl.addLayout(tr_row)

        # Opacity — shown in Texture mode
        tex_op_sep = QFrame()
        tex_op_sep.setFrameShape(QFrame.Shape.HLine)
        tex_op_sep.setFrameShadow(QFrame.Shadow.Sunken)
        tex_gl.addWidget(tex_op_sep)

        tex_op_row = QHBoxLayout()
        tex_op_row.addWidget(QLabel("Opacity:"))
        self._tex_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._tex_opacity_slider.setRange(0, 100)
        self._tex_opacity_slider.setValue(100)
        self._tex_opacity_slider.valueChanged.connect(self._on_tex_opacity_slider)
        tex_op_row.addWidget(self._tex_opacity_slider, 1)
        self._tex_opacity_spin = QDoubleSpinBox()
        self._tex_opacity_spin.setRange(0.0, 1.0)
        self._tex_opacity_spin.setSingleStep(0.05)
        self._tex_opacity_spin.setDecimals(2)
        self._tex_opacity_spin.setValue(1.0)
        self._tex_opacity_spin.valueChanged.connect(self._on_tex_opacity_spin)
        tex_op_row.addWidget(self._tex_opacity_spin)
        tex_gl.addLayout(tex_op_row)

        layout.addWidget(self._texture_group)

        # ===== Outline group (layer-level) =====
        outline_group = QGroupBox("Outline")
        outline_gl = QVBoxLayout(outline_group)
        outline_gl.setContentsMargins(6, 4, 6, 4)

        layer = self._get_draw_layer()

        self._outline_cb = QCheckBox("Enable Outline")
        self._outline_cb.setChecked(layer.outline_enabled if layer else False)
        self._outline_cb.toggled.connect(self._on_outline_toggled)
        outline_gl.addWidget(self._outline_cb)

        self._outline_container = QWidget()
        oc_layout = QVBoxLayout(self._outline_container)
        oc_layout.setContentsMargins(0, 0, 0, 0)

        oc_row = QHBoxLayout()
        oc_row.addWidget(QLabel("Color:"))
        self._outline_color_btn = QPushButton()
        self._outline_color_btn.setFixedSize(40, 25)
        update_color_btn(
            self._outline_color_btn,
            QColor(layer.outline_color if layer else "#000000"),
        )
        self._outline_color_btn.clicked.connect(self._on_outline_color)
        oc_row.addWidget(self._outline_color_btn)
        oc_row.addStretch()
        oc_layout.addLayout(oc_row)

        ow_row = QHBoxLayout()
        ow_row.addWidget(QLabel("Width:"))
        self._outline_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._outline_width_slider.setRange(1, 40)
        self._outline_width_slider.setValue(
            int((layer.outline_width if layer else 2.0) * 2)
        )
        self._outline_width_slider.valueChanged.connect(self._on_outline_width_slider)
        ow_row.addWidget(self._outline_width_slider, 1)
        self._outline_width_spin = QDoubleSpinBox()
        self._outline_width_spin.setRange(0.5, 20.0)
        self._outline_width_spin.setSingleStep(0.5)
        self._outline_width_spin.setDecimals(1)
        self._outline_width_spin.setValue(layer.outline_width if layer else 2.0)
        self._outline_width_spin.valueChanged.connect(self._on_outline_width_spin)
        ow_row.addWidget(self._outline_width_spin)
        oc_layout.addLayout(ow_row)

        outline_gl.addWidget(self._outline_container)
        self._outline_container.setEnabled(
            layer.outline_enabled if layer else False
        )

        layout.addWidget(outline_group)

        # ===== Shadow group (layer-level) =====
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

        so_row = QHBoxLayout()
        so_row.addWidget(QLabel("Opacity:"))
        self._shadow_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._shadow_opacity_slider.setRange(0, 100)
        self._shadow_opacity_slider.setValue(
            int((layer.shadow_opacity if layer else 0.5) * 100)
        )
        self._shadow_opacity_slider.valueChanged.connect(
            self._on_shadow_opacity_slider
        )
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
        self._shadow_angle_spin.setSuffix("\u00b0")
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
        self._shadow_container.setEnabled(
            layer.shadow_enabled if layer else False
        )

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
        self._bevel_angle_slider.setValue(
            int(layer.bevel_angle if layer else 120))
        self._bevel_angle_slider.valueChanged.connect(
            self._on_bevel_angle_slider)
        ba_row.addWidget(self._bevel_angle_slider, 1)
        self._bevel_angle_spin = QSpinBox()
        self._bevel_angle_spin.setRange(0, 360)
        self._bevel_angle_spin.setSuffix("\u00b0")
        self._bevel_angle_spin.setFixedWidth(60)
        self._bevel_angle_spin.setValue(
            int(layer.bevel_angle if layer else 120))
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
            "Outer" if (layer and layer.bevel_type == "outer") else "Inner")
        self._bevel_type_combo.currentTextChanged.connect(
            self._on_bevel_type)
        bt_row.addWidget(self._bevel_type_combo, 1)
        bc_layout.addLayout(bt_row)

        bs_row = QHBoxLayout()
        bs_row.addWidget(QLabel("Size:"))
        self._bevel_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._bevel_size_slider.setRange(1, 40)
        self._bevel_size_slider.setValue(
            int((layer.bevel_size if layer else 3.0) * 2))
        self._bevel_size_slider.valueChanged.connect(
            self._on_bevel_size_slider)
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
        self._bevel_depth_slider.setValue(
            int((layer.bevel_depth if layer else 0.5) * 100))
        self._bevel_depth_slider.valueChanged.connect(
            self._on_bevel_depth_slider)
        bd_row.addWidget(self._bevel_depth_slider, 1)
        self._bevel_depth_spin = QDoubleSpinBox()
        self._bevel_depth_spin.setRange(0.0, 1.0)
        self._bevel_depth_spin.setSingleStep(0.05)
        self._bevel_depth_spin.setDecimals(2)
        self._bevel_depth_spin.setFixedWidth(60)
        self._bevel_depth_spin.setValue(
            layer.bevel_depth if layer else 0.5)
        self._bevel_depth_spin.valueChanged.connect(
            self._on_bevel_depth_spin)
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
        self._bevel_hl_opacity_spin.valueChanged.connect(
            self._on_bevel_hl_opacity)
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
        self._bevel_sh_opacity_spin.valueChanged.connect(
            self._on_bevel_sh_opacity)
        bsh_row.addWidget(self._bevel_sh_opacity_spin)
        bsh_row.addStretch()
        bc_layout.addLayout(bsh_row)

        bevel_gl.addWidget(self._bevel_container)
        self._bevel_container.setEnabled(
            layer.bevel_enabled if layer else False)

        # --- Structure sub-section ---
        self._struct_cb = QCheckBox("Enable Structure")
        self._struct_cb.setChecked(
            layer.structure_enabled if layer else False)
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
        self._struct_tex_combo.currentIndexChanged.connect(
            self._on_struct_tex_changed)
        stx_row.addWidget(self._struct_tex_combo, 1)
        stc_layout.addLayout(stx_row)

        sts_row = QHBoxLayout()
        sts_row.addWidget(QLabel("Scale:"))
        self._struct_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._struct_scale_slider.setRange(10, 1000)
        self._struct_scale_slider.setValue(
            int((layer.structure_scale if layer else 1.0) * 100))
        self._struct_scale_slider.valueChanged.connect(
            self._on_struct_scale_slider)
        sts_row.addWidget(self._struct_scale_slider, 1)
        self._struct_scale_spin = QDoubleSpinBox()
        self._struct_scale_spin.setRange(0.1, 10.0)
        self._struct_scale_spin.setSingleStep(0.1)
        self._struct_scale_spin.setDecimals(2)
        self._struct_scale_spin.setFixedWidth(60)
        self._struct_scale_spin.setValue(
            layer.structure_scale if layer else 1.0)
        self._struct_scale_spin.valueChanged.connect(
            self._on_struct_scale_spin)
        sts_row.addWidget(self._struct_scale_spin)
        stc_layout.addLayout(sts_row)

        std_row = QHBoxLayout()
        std_row.addWidget(QLabel("Depth:"))
        self._struct_depth_slider = QSlider(Qt.Orientation.Horizontal)
        self._struct_depth_slider.setRange(0, 100)
        self._struct_depth_slider.setValue(
            int(layer.structure_depth if layer else 50))
        self._struct_depth_slider.valueChanged.connect(
            self._on_struct_depth_slider)
        std_row.addWidget(self._struct_depth_slider, 1)
        self._struct_depth_spin = QSpinBox()
        self._struct_depth_spin.setRange(0, 100)
        self._struct_depth_spin.setFixedWidth(60)
        self._struct_depth_spin.setValue(
            int(layer.structure_depth if layer else 50))
        self._struct_depth_spin.valueChanged.connect(
            self._on_struct_depth_spin)
        std_row.addWidget(self._struct_depth_spin)
        stc_layout.addLayout(std_row)

        self._struct_invert_cb = QCheckBox("Invert")
        self._struct_invert_cb.setChecked(
            layer.structure_invert if layer else False)
        self._struct_invert_cb.toggled.connect(self._on_struct_invert)
        stc_layout.addWidget(self._struct_invert_cb)

        bevel_gl.addWidget(self._struct_container)
        self._struct_container.setEnabled(
            layer.structure_enabled if layer else False)
        layout.addWidget(bevel_group)

        layout.addStretch()

        # Populate grids
        self._rebuild_brush_grid()
        self._refresh_texture_filter_combos()
        self._rebuild_texture_grid()

        # Populate channel list and sync content widgets
        self._rebuild_channel_list()
        self._update_channel_content()

        # Register callback so the panel stays in sync when channels are
        # added/removed silently (e.g. auto-create on first paint).
        layer = self._get_draw_layer()
        if layer:
            layer._channels_changed_cb = self._rebuild_channel_list

        # Register callback so sliders stay in sync during drag-to-adjust.
        tool._params_changed_cb = self._sync_brush_params_from_tool

        # Connect command stack signal so channel UI refreshes after Ctrl+Z
        # of a DrawEditChannelCommand (e.g. rename, color change).
        tool._command_stack.stack_changed.connect(self._on_stack_changed)
        self._stack_connected = True

        return widget

    def close_sidebar(self) -> None:
        """Hide all sidebars and reset toggle buttons."""
        if self._brush_sidebar:
            self._brush_sidebar.hide()
        if self._texture_sidebar:
            self._texture_sidebar.hide()
        if self._channel_sidebar:
            self._channel_sidebar.hide()
        try:
            if hasattr(self, "_expand_btn"):
                self._expand_btn.setChecked(False)
            if hasattr(self, "_tex_expand_btn"):
                self._tex_expand_btn.setChecked(False)
            if hasattr(self, "_ch_expand_btn"):
                self._ch_expand_btn.setChecked(False)
        except RuntimeError:
            pass
        # L11: clear layer/tool callbacks so stale widgets don't receive events after switch
        layer = self._get_draw_layer()
        if layer is not None:
            layer._channels_changed_cb = None
        if self._tool is not None:
            self._tool._params_changed_cb = None
            if getattr(self, "_stack_connected", False):
                self._tool._command_stack.stack_changed.disconnect(self._on_stack_changed)
                self._stack_connected = False

    def _on_stack_changed(self) -> None:
        """Refresh channel UI after an undo/redo that affects channel data."""
        if not self._tool:
            return
        # Only refresh if the draw tool is still the active tool context
        # (i.e. the options panel still holds a reference to this tool).
        layer = self._get_draw_layer()
        if layer is None:
            return
        self._rebuild_channel_list()
        self._update_channel_content()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_draw_layer(self) -> DrawLayer | None:
        if not self._tool:
            return None
        layer = self._tool._project.layer_stack.active_layer
        if isinstance(layer, DrawLayer):
            return layer
        return None

    def _get_active_channel(self) -> DrawChannel | None:
        if not self._tool:
            return None
        layer = self._get_draw_layer()
        if not layer:
            return None
        if self._tool.active_channel_id:
            ch = layer.find_channel(self._tool.active_channel_id)
            if ch is not None:
                return ch
        if layer.channels:
            self._tool.active_channel_id = layer.channels[0].id
            return layer.channels[0]
        return None

    def _apply_channel_edit(self, **changes: object) -> None:
        """Apply a channel property change via undoable command."""
        ch = self._get_active_channel()
        layer = self._get_draw_layer()
        if not ch or not layer or not self._tool:
            return
        cmd = DrawEditChannelCommand(layer, ch, **changes)
        self._tool._command_stack.execute(cmd)
        self._rebuild_channel_list()
        self._update_channel_content()

    def _apply_layer_effect(self, **changes: object) -> None:
        """Apply a layer-level effect change via undoable command."""
        layer = self._get_draw_layer()
        if not layer or not self._tool:
            return
        cmd = EditDrawLayerEffectsCommand(layer, **changes)
        self._tool._command_stack.execute(cmd)

    def sync_effects_from_layer(self) -> None:
        """Sync all layer-level effect widgets (outline, shadow, bevel, structure) from the active DrawLayer."""
        layer = self._get_draw_layer()
        if not layer:
            return

        # --- Outline ---
        self._outline_cb.blockSignals(True)
        self._outline_cb.setChecked(layer.outline_enabled)
        self._outline_cb.blockSignals(False)
        self._outline_container.setEnabled(layer.outline_enabled)
        update_color_btn(self._outline_color_btn, QColor(layer.outline_color))
        self._outline_width_slider.blockSignals(True)
        self._outline_width_slider.setValue(int(layer.outline_width * 2))
        self._outline_width_slider.blockSignals(False)
        self._outline_width_spin.blockSignals(True)
        self._outline_width_spin.setValue(layer.outline_width)
        self._outline_width_spin.blockSignals(False)

        # --- Shadow ---
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

        # --- Bevel & Emboss ---
        self._bevel_angle_slider.blockSignals(True)
        self._bevel_angle_slider.setValue(int(layer.bevel_angle))
        self._bevel_angle_slider.blockSignals(False)
        self._bevel_angle_spin.blockSignals(True)
        self._bevel_angle_spin.setValue(int(layer.bevel_angle))
        self._bevel_angle_spin.blockSignals(False)
        self._bevel_cb.blockSignals(True)
        self._bevel_cb.setChecked(layer.bevel_enabled)
        self._bevel_cb.blockSignals(False)
        self._bevel_container.setEnabled(layer.bevel_enabled)
        self._bevel_type_combo.blockSignals(True)
        self._bevel_type_combo.setCurrentText(
            "Outer" if layer.bevel_type == "outer" else "Inner"
        )
        self._bevel_type_combo.blockSignals(False)
        self._bevel_size_slider.blockSignals(True)
        self._bevel_size_slider.setValue(int(layer.bevel_size * 2))
        self._bevel_size_slider.blockSignals(False)
        self._bevel_size_spin.blockSignals(True)
        self._bevel_size_spin.setValue(layer.bevel_size)
        self._bevel_size_spin.blockSignals(False)
        self._bevel_depth_slider.blockSignals(True)
        self._bevel_depth_slider.setValue(int(layer.bevel_depth * 100))
        self._bevel_depth_slider.blockSignals(False)
        self._bevel_depth_spin.blockSignals(True)
        self._bevel_depth_spin.setValue(layer.bevel_depth)
        self._bevel_depth_spin.blockSignals(False)
        update_color_btn(self._bevel_hl_color_btn, QColor(layer.bevel_highlight_color))
        self._bevel_hl_opacity_spin.blockSignals(True)
        self._bevel_hl_opacity_spin.setValue(layer.bevel_highlight_opacity)
        self._bevel_hl_opacity_spin.blockSignals(False)
        update_color_btn(self._bevel_sh_color_btn, QColor(layer.bevel_shadow_color))
        self._bevel_sh_opacity_spin.blockSignals(True)
        self._bevel_sh_opacity_spin.setValue(layer.bevel_shadow_opacity)
        self._bevel_sh_opacity_spin.blockSignals(False)

        # --- Structure ---
        self._struct_cb.blockSignals(True)
        self._struct_cb.setChecked(layer.structure_enabled)
        self._struct_cb.blockSignals(False)
        self._struct_container.setEnabled(layer.structure_enabled)
        self._refresh_struct_tex_combo(layer)
        self._struct_scale_slider.blockSignals(True)
        self._struct_scale_slider.setValue(int(layer.structure_scale * 100))
        self._struct_scale_slider.blockSignals(False)
        self._struct_scale_spin.blockSignals(True)
        self._struct_scale_spin.setValue(layer.structure_scale)
        self._struct_scale_spin.blockSignals(False)
        self._struct_depth_slider.blockSignals(True)
        self._struct_depth_slider.setValue(int(layer.structure_depth))
        self._struct_depth_slider.blockSignals(False)
        self._struct_depth_spin.blockSignals(True)
        self._struct_depth_spin.setValue(int(layer.structure_depth))
        self._struct_depth_spin.blockSignals(False)
        self._struct_invert_cb.blockSignals(True)
        self._struct_invert_cb.setChecked(layer.structure_invert)
        self._struct_invert_cb.blockSignals(False)

    def _make_channel_icon(self, channel: DrawChannel) -> QIcon:
        """Create a 16×16 colored icon for a channel list item."""
        pix = QPixmap(16, 16)
        if channel.texture_id:
            pix.fill(QColor("#666666"))
            p = QPainter(pix)
            p.setPen(QColor("#ffffff"))
            p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "T")
            p.end()
        else:
            pix.fill(QColor(channel.color))
        return QIcon(pix)

    # -------------------------------------------------------------------------
    # Channel list
    # -------------------------------------------------------------------------

    def _rebuild_channel_list(self) -> None:
        """Repopulate the channel QListWidget from the active layer."""
        if self._channel_list is None:
            return
        layer = self._get_draw_layer()
        self._channel_list.blockSignals(True)
        self._channel_list.clear()
        if layer:
            active_id = self._tool.active_channel_id if self._tool else None
            active_row = 0
            for i, ch in enumerate(layer.channels):
                item = QListWidgetItem(self._make_channel_icon(ch), ch.name)
                if not ch.visible:
                    item.setForeground(QColor("#888888"))
                self._channel_list.addItem(item)
                if ch.id == active_id:
                    active_row = i
            if layer.channels:
                self._channel_list.setCurrentRow(active_row)
        self._channel_list.blockSignals(False)
        # Sync visible checkbox
        ch = self._get_active_channel()
        if hasattr(self, "_ch_visible_cb"):
            self._ch_visible_cb.blockSignals(True)
            self._ch_visible_cb.setChecked(ch.visible if ch else True)
            self._ch_visible_cb.blockSignals(False)
        # Sync expanded sidebar
        self._sync_channel_sidebar()

    def _update_channel_content(self) -> None:
        """Sync all channel-specific controls with the active channel's data."""
        if self._updating_ui:
            return
        self._updating_ui = True
        try:
            # Detect stale list (e.g. after auto-create of first channel)
            layer = self._get_draw_layer()
            if (layer and self._channel_list is not None
                    and self._channel_list.count() != len(layer.channels)):
                self._updating_ui = False
                self._rebuild_channel_list()
                self._updating_ui = True

            ch = self._get_active_channel()
            is_texture = bool(ch.texture_id) if ch else False

            # Mode toggle buttons
            if self._ch_mode_group:
                b0 = self._ch_mode_group.button(0)
                b1 = self._ch_mode_group.button(1)
                if b0 and b1:
                    b0.blockSignals(True)
                    b1.blockSignals(True)
                    b0.setChecked(not is_texture)
                    b1.setChecked(is_texture)
                    b0.blockSignals(False)
                    b1.blockSignals(False)

            # Color/Texture group visibility; disable when no channel is active
            if hasattr(self, "_color_group"):
                self._color_group.setVisible(not is_texture)
                self._color_group.setEnabled(ch is not None)
            if hasattr(self, "_texture_group"):
                self._texture_group.setVisible(is_texture)
                self._texture_group.setEnabled(ch is not None)

            if ch is None:
                return

            # Color button
            if hasattr(self, "_color_btn"):
                update_color_btn(self._color_btn, QColor(ch.color))

            # Opacity (color mode widget)
            if hasattr(self, "_opacity_slider"):
                self._opacity_slider.blockSignals(True)
                self._opacity_slider.setValue(int(ch.opacity * 100))
                self._opacity_slider.blockSignals(False)
            if hasattr(self, "_opacity_spin"):
                self._opacity_spin.blockSignals(True)
                self._opacity_spin.setValue(ch.opacity)
                self._opacity_spin.blockSignals(False)
            # Opacity (texture mode widget)
            if hasattr(self, "_tex_opacity_slider"):
                self._tex_opacity_slider.blockSignals(True)
                self._tex_opacity_slider.setValue(int(ch.opacity * 100))
                self._tex_opacity_slider.blockSignals(False)
            if hasattr(self, "_tex_opacity_spin"):
                self._tex_opacity_spin.blockSignals(True)
                self._tex_opacity_spin.setValue(ch.opacity)
                self._tex_opacity_spin.blockSignals(False)

            # Texture controls
            if hasattr(self, "_tex_zoom_slider"):
                self._tex_zoom_slider.blockSignals(True)
                self._tex_zoom_slider.setValue(int(ch.texture_zoom * 100))
                self._tex_zoom_slider.blockSignals(False)
            if hasattr(self, "_tex_zoom_spin"):
                self._tex_zoom_spin.blockSignals(True)
                self._tex_zoom_spin.setValue(ch.texture_zoom)
                self._tex_zoom_spin.blockSignals(False)
            if hasattr(self, "_tex_rot_slider"):
                self._tex_rot_slider.blockSignals(True)
                self._tex_rot_slider.setValue(int(ch.texture_rotation))
                self._tex_rot_slider.blockSignals(False)
            if hasattr(self, "_tex_rot_spin"):
                self._tex_rot_spin.blockSignals(True)
                self._tex_rot_spin.setValue(ch.texture_rotation)
                self._tex_rot_spin.blockSignals(False)

            # Texture selection highlight
            self._update_texture_selection()

            # Visible checkbox
            if hasattr(self, "_ch_visible_cb"):
                self._ch_visible_cb.blockSignals(True)
                self._ch_visible_cb.setChecked(ch.visible)
                self._ch_visible_cb.blockSignals(False)

            self._update_can_paint()
        finally:
            self._updating_ui = False

    def _on_channel_row_changed(self, row: int) -> None:
        if self._updating_ui:
            return
        layer = self._get_draw_layer()
        if not layer or row < 0 or row >= len(layer.channels):
            return
        ch = layer.channels[row]
        if self._tool:
            self._tool.active_channel_id = ch.id
        self._update_channel_content()

    def _on_channel_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Double-click → rename channel."""
        row = self._channel_list.row(item)
        layer = self._get_draw_layer()
        if not layer or row < 0 or row >= len(layer.channels):
            return
        ch = layer.channels[row]
        name, ok = QInputDialog.getText(
            self.dock.window(), "Rename Channel", "Name:", text=ch.name
        )
        if ok and name.strip():
            self._apply_channel_edit(name=name.strip())

    def _on_add_channel(self) -> None:
        layer = self._get_draw_layer()
        if not layer or not self._tool:
            return

        # New channel inherits the current content type (Color or Texture).
        is_texture_mode = (
            self._ch_mode_group is not None
            and self._ch_mode_group.button(1) is not None
            and self._ch_mode_group.button(1).isChecked()
        )
        active = self._get_active_channel()
        if is_texture_mode and active and active.texture_id:
            new_ch = DrawChannel(
                name=f"Channel {len(layer.channels) + 1}",
                color="#000000",
                texture_id=active.texture_id,
                texture_zoom=active.texture_zoom,
                texture_rotation=active.texture_rotation,
            )
        else:
            new_ch = DrawChannel(
                name=f"Channel {len(layer.channels) + 1}",
                color=active.color if active else "#000000",
            )

        # Insert ABOVE (before) the currently active channel.
        insert_idx = layer.index_of(active) if active else 0
        insert_idx = max(0, insert_idx)
        cmd = DrawAddChannelCommand(layer, new_ch, index=insert_idx)
        self._tool._command_stack.execute(cmd)
        self._tool.active_channel_id = new_ch.id
        self._rebuild_channel_list()
        self._update_channel_content()

        # _update_channel_content derives the mode from texture_id.  When the
        # user was already in Texture mode but the new channel has no texture
        # yet, the toggle would snap back to "Color".  Force it to stay on
        # Texture so the user can immediately pick a texture for the new channel.
        if is_texture_mode and not new_ch.texture_id:
            if self._ch_mode_group:
                b0 = self._ch_mode_group.button(0)
                b1 = self._ch_mode_group.button(1)
                if b0 and b1:
                    b0.blockSignals(True)
                    b1.blockSignals(True)
                    b0.setChecked(False)
                    b1.setChecked(True)
                    b0.blockSignals(False)
                    b1.blockSignals(False)
            if hasattr(self, "_color_group"):
                self._color_group.setVisible(False)
            if hasattr(self, "_texture_group"):
                self._texture_group.setVisible(True)

    def _on_remove_channel(self) -> None:
        ch = self._get_active_channel()
        layer = self._get_draw_layer()
        if not ch or not layer or not self._tool:
            return
        if len(layer.channels) <= 1:
            return  # keep at least one channel
        idx = layer.index_of(ch)
        cmd = DrawRemoveChannelCommand(layer, ch)
        self._tool._command_stack.execute(cmd)
        # Select adjacent channel
        new_idx = max(0, idx - 1)
        if layer.channels:
            self._tool.active_channel_id = layer.channels[new_idx].id
        else:
            self._tool.active_channel_id = None
        self._rebuild_channel_list()
        self._update_channel_content()

    def _on_move_channel_up(self) -> None:
        ch = self._get_active_channel()
        layer = self._get_draw_layer()
        if not ch or not layer or not self._tool:
            return
        idx = layer.index_of(ch)
        if idx <= 0:
            return
        cmd = DrawMoveChannelCommand(layer, ch, idx - 1)
        self._tool._command_stack.execute(cmd)
        self._rebuild_channel_list()

    def _on_move_channel_down(self) -> None:
        ch = self._get_active_channel()
        layer = self._get_draw_layer()
        if not ch or not layer or not self._tool:
            return
        idx = layer.index_of(ch)
        if idx >= len(layer.channels) - 1:
            return
        cmd = DrawMoveChannelCommand(layer, ch, idx + 1)
        self._tool._command_stack.execute(cmd)
        self._rebuild_channel_list()

    def _on_channel_visible_changed(self, checked: bool) -> None:
        self._apply_channel_edit(visible=checked)

    def _on_channel_rows_moved(
        self,
        _src_parent,
        src_row: int,
        _src_end: int,
        _dst_parent,
        dst_row: int,
    ) -> None:
        """Called after the user drag-drops a channel row in the list."""
        if self._updating_ui:
            return
        layer = self._get_draw_layer()
        if not layer or not self._tool:
            return
        # Qt inserts before dst_row; adjust target index for the data model.
        target = dst_row if dst_row <= src_row else dst_row - 1
        if src_row == target or src_row < 0 or target < 0:
            return
        if src_row >= len(layer.channels) or target >= len(layer.channels):
            return
        ch = layer.channels[src_row]
        cmd = DrawMoveChannelCommand(layer, ch, target)
        self._tool._command_stack.execute(cmd)
        # Rebuild to keep UI and data in sync (drag-drop already moved the row
        # visually, so we need to reset to the canonical data order).
        self._rebuild_channel_list()

    def _on_sidebar_rows_moved(self, src_row: int, target: int) -> None:
        """Called after the user drag-drops a channel in the expanded sidebar."""
        if self._updating_ui:
            return
        layer = self._get_draw_layer()
        if not layer or not self._tool:
            return
        if src_row == target or src_row < 0 or target < 0:
            return
        if src_row >= len(layer.channels) or target >= len(layer.channels):
            return
        ch = layer.channels[src_row]
        cmd = DrawMoveChannelCommand(layer, ch, target)
        self._tool._command_stack.execute(cmd)
        # _rebuild_channel_list is triggered via _channels_changed_cb;
        # also sync the sidebar to canonical data order.
        self._sync_channel_sidebar()

    # Channel sidebar (Expand)

    def _on_toggle_channel_sidebar(self, checked: bool) -> None:
        if checked:
            if not self._channel_sidebar:
                self._channel_sidebar = ChannelBrowserSidebar(self.dock.window())
                self._channel_sidebar.channel_clicked.connect(self._on_ch_sidebar_channel_clicked)
                self._channel_sidebar.add_clicked.connect(self._on_add_channel)
                self._channel_sidebar.remove_clicked.connect(self._on_remove_channel)
                self._channel_sidebar.move_up_clicked.connect(self._on_move_channel_up)
                self._channel_sidebar.move_down_clicked.connect(self._on_move_channel_down)
                self._channel_sidebar.rows_moved.connect(self._on_sidebar_rows_moved)
                self._channel_sidebar.visible_toggled.connect(self._on_channel_visible_changed)
                self._channel_sidebar.rename_requested.connect(self._on_ch_sidebar_rename)
                self._channel_sidebar.closed.connect(self._on_channel_sidebar_closed)
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea, self._channel_sidebar
                )
                main_win.splitDockWidget(
                    self.dock, self._channel_sidebar, Qt.Orientation.Horizontal
                )
            self._channel_sidebar.show()
            self._sync_channel_sidebar()
        else:
            if self._channel_sidebar:
                self._channel_sidebar.hide()

    def _sync_channel_sidebar(self) -> None:
        if not self._channel_sidebar or not self._channel_sidebar.isVisible():
            return
        layer = self._get_draw_layer()
        channels = layer.channels if layer else []
        active_id = self._tool.active_channel_id if self._tool else None
        self._channel_sidebar.set_channels(channels, active_id)

    def _on_channel_sidebar_closed(self) -> None:
        try:
            if hasattr(self, "_ch_expand_btn"):
                self._ch_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    def _on_ch_sidebar_channel_clicked(self, channel_id: str) -> None:
        """Sidebar row clicked — switch active channel."""
        if not self._tool:
            return
        layer = self._get_draw_layer()
        if not layer:
            return
        ch = layer.find_channel(channel_id)
        if ch is None:
            return
        self._tool.active_channel_id = channel_id
        self._rebuild_channel_list()
        self._update_channel_content()

    def _on_ch_sidebar_rename(self, row: int) -> None:
        """Sidebar double-click — rename channel."""
        layer = self._get_draw_layer()
        if not layer or row < 0 or row >= len(layer.channels):
            return
        ch = layer.channels[row]
        name, ok = QInputDialog.getText(
            self.dock.window(), "Rename Channel", "Name:", text=ch.name
        )
        if ok and name.strip():
            # Temporarily set active to the renamed channel
            old_id = self._tool.active_channel_id if self._tool else None
            if self._tool:
                self._tool.active_channel_id = ch.id
            self._apply_channel_edit(name=name.strip())
            if self._tool and old_id and old_id != ch.id:
                self._tool.active_channel_id = old_id

    # -------------------------------------------------------------------------
    # Channel content mode toggle (Color / Texture)
    # -------------------------------------------------------------------------

    def _update_can_paint(self) -> None:
        """Block painting when no channel is selected, or texture mode without texture."""
        if not self._tool or not self._ch_mode_group:
            return
        layer = self._get_draw_layer()
        if not layer or not layer.channels:
            self._tool._can_paint = False
            return
        ch = self._get_active_channel()
        if ch is None:
            self._tool._can_paint = False
            return
        tex_btn = self._ch_mode_group.button(1)
        if tex_btn is not None and tex_btn.isChecked():
            self._tool._can_paint = bool(ch.texture_id)
        else:
            self._tool._can_paint = True

    def _on_ch_mode_changed(self, btn_id: int, checked: bool) -> None:
        if not checked or not self._tool or self._updating_ui:
            return
        if btn_id == 0:
            # Color mode: clear texture assignment from channel
            ch = self._get_active_channel()
            if ch and ch.texture_id:
                self._apply_channel_edit(texture_id="")
                # _apply_channel_edit → _update_channel_content handles visibility
            else:
                self._color_group.setVisible(True)
                self._texture_group.setVisible(False)
        else:
            # Texture mode: show texture group; texture is set when user clicks one
            self._color_group.setVisible(False)
            self._texture_group.setVisible(True)
        self._update_can_paint()

    # -------------------------------------------------------------------------
    # Mode (Draw / Erase)
    # -------------------------------------------------------------------------

    def _on_de_mode_changed(self, btn_id: int, checked: bool) -> None:
        if not checked or not self._tool:
            return
        mode = {0: "draw", 1: "fill", 2: "erase"}.get(btn_id, "draw")
        self._tool.mode = mode
        self._expand_row_widget.setVisible(mode == "fill")

    def _on_fill_expand_changed(self, v: int) -> None:
        self._fill_expand_lbl.setText(f"{v} px")
        if self._tool:
            self._tool.fill_expand_px = v

    # -------------------------------------------------------------------------
    # Brush
    # -------------------------------------------------------------------------

    def _rebuild_brush_grid(self) -> None:
        for btn in self._brush_buttons.values():
            self._brush_grid.removeWidget(btn)
            btn.deleteLater()
        self._brush_buttons.clear()
        if not self._brush_catalog:
            return
        for i, brush in enumerate(self._brush_catalog.brushes):
            btn = self._make_brush_thumb(brush)
            row = i // _BRUSH_COLS
            col = i % _BRUSH_COLS
            self._brush_grid.addWidget(btn, row, col)
            self._brush_buttons[brush.id] = btn
        self._update_brush_selection()

    def _make_brush_thumb(self, brush: LibraryBrush) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(_BRUSH_THUMB + 12, _BRUSH_THUMB + 20)
        btn.setToolTip(f"{brush.display_name}\n{brush.category}")
        pixmap = self._get_brush_thumb(brush)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(_BRUSH_THUMB, _BRUSH_THUMB))
        btn.setText(brush.display_name[:8])
        btn.clicked.connect(
            lambda checked=False, b=brush: self._on_brush_clicked(b)
        )
        return btn

    def _get_brush_thumb(self, brush: LibraryBrush) -> QPixmap | None:
        if brush.id in self._brush_thumb_cache:
            return self._brush_thumb_cache[brush.id]
        if not brush.exists():
            return None
        src = QPixmap(brush.file_path())
        if src.isNull():
            return None
        src = src.scaled(
            _BRUSH_THUMB, _BRUSH_THUMB,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        result = QPixmap(_BRUSH_THUMB, _BRUSH_THUMB)
        result.fill(QColor("#2b2b2b"))
        p = QPainter(result)
        x = (_BRUSH_THUMB - src.width()) // 2
        y = (_BRUSH_THUMB - src.height()) // 2
        p.drawPixmap(x, y, src)
        p.end()
        self._brush_thumb_cache[brush.id] = result
        return result

    def _on_brush_clicked(self, brush: LibraryBrush) -> None:
        if self._tool:
            self._tool.brush_id = brush.id
        self._update_brush_selection()

    def _update_brush_selection(self) -> None:
        selected_id = self._tool.brush_id if self._tool else ""
        for bid, btn in self._brush_buttons.items():
            if bid == selected_id:
                btn.setStyleSheet("QToolButton { border: 2px solid #4488ff; }")
            else:
                btn.setStyleSheet("")

    # Brush Manager / Sidebar

    def _on_open_brush_manager(self) -> None:
        dialog = BrushManagerDialog(self.dock.window())
        dialog.catalog_changed.connect(self._on_brush_manager_changed)
        dialog.exec()

    def _on_brush_manager_changed(self) -> None:
        self._brush_catalog = load_brush_catalog()
        self._brush_thumb_cache.clear()
        self._rebuild_brush_grid()
        if self._brush_sidebar and self._brush_sidebar.isVisible():
            self._brush_sidebar.invalidate_cache()
            self._sync_brush_sidebar()

    def _on_toggle_sidebar(self, checked: bool) -> None:
        if checked:
            self.dock._save_panel_width()
            if not self._brush_sidebar:
                self._brush_sidebar = BrushBrowserSidebar(self.dock.window())
                self._brush_sidebar.brush_clicked.connect(
                    self._on_sidebar_brush_clicked
                )
                self._brush_sidebar.closed.connect(self._on_sidebar_closed)
                main_win = self.dock.window()
                main_win.addDockWidget(
                    Qt.DockWidgetArea.LeftDockWidgetArea, self._brush_sidebar
                )
                main_win.splitDockWidget(
                    self.dock, self._brush_sidebar, Qt.Orientation.Horizontal
                )
            self._brush_sidebar.show()
            self._sync_brush_sidebar()
        else:
            if self._brush_sidebar:
                self._brush_sidebar.hide()
            self.dock._restore_panel_width()

    def _sync_brush_sidebar(self) -> None:
        if not self._brush_sidebar or not self._brush_sidebar.isVisible():
            return
        brushes = self._brush_catalog.brushes if self._brush_catalog else []
        selected_id = self._tool.brush_id if self._tool else None
        self._brush_sidebar.set_brushes(brushes, selected_id)

    def _on_sidebar_brush_clicked(self, brush: LibraryBrush) -> None:
        self._on_brush_clicked(brush)

    def _on_sidebar_closed(self) -> None:
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_expand_btn"):
                self._expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # Texture Manager / Sidebar

    def _on_open_texture_manager(self) -> None:
        dialog = TextureManagerDialog(self.dock.window())
        dialog.catalog_changed.connect(self._on_texture_manager_changed)
        dialog.exec()

    def _on_texture_manager_changed(self) -> None:
        self._texture_catalog = load_texture_catalog()
        self._texture_thumb_cache.clear()
        if self._texture_sidebar:
            self._texture_sidebar.invalidate_cache()
        self._refresh_texture_filter_combos()
        self._rebuild_texture_grid()
        if self._texture_sidebar and self._texture_sidebar.isVisible():
            self._sync_texture_sidebar()

    def refresh_texture_catalog(self) -> None:
        """Reload texture catalog (called on tool switch to pick up imports from other tools)."""
        if not hasattr(self, "_texture_catalog"):
            return
        self._texture_catalog = load_texture_catalog()
        self._refresh_texture_filter_combos()
        self._rebuild_texture_grid()
        if self._texture_sidebar and self._texture_sidebar.isVisible():
            self._sync_texture_sidebar()

    def refresh_palette_catalog(self) -> None:
        """Reload palette combo (called when the palette editor reports changes)."""
        if not hasattr(self, "_d_palette_combo"):
            return
        self._d_refresh_palette_combo()

    def _on_toggle_texture_sidebar(self, checked: bool) -> None:
        if checked:
            self.dock._save_panel_width()
            if not self._texture_sidebar:
                self._texture_sidebar = TextureBrowserSidebar(self.dock.window())
                self._texture_sidebar.texture_clicked.connect(
                    self._on_sidebar_texture_clicked
                )
                self._texture_sidebar.closed.connect(self._on_texture_sidebar_closed)
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

    def _sync_texture_sidebar(self) -> None:
        if not self._texture_sidebar or not self._texture_sidebar.isVisible():
            return
        textures = self._filtered_browser_textures()
        ch = self._get_active_channel()
        selected_id = ch.texture_id if ch else None
        self._texture_sidebar.set_textures(textures, selected_id)

    def _on_sidebar_texture_clicked(self, tex: LibraryTexture) -> None:
        self._on_texture_clicked(tex)

    def _on_texture_sidebar_closed(self) -> None:
        self.dock._restore_panel_width()
        try:
            if hasattr(self, "_tex_expand_btn"):
                self._tex_expand_btn.setChecked(False)
        except RuntimeError:
            pass

    # -------------------------------------------------------------------------
    # Size / Hardness / Flow
    # -------------------------------------------------------------------------

    def _on_size_slider(self, val: int) -> None:
        if not self._tool:
            return
        size = val / 10.0
        self._tool.brush_size = size
        self._size_spin.blockSignals(True)
        self._size_spin.setValue(size)
        self._size_spin.blockSignals(False)

    def _on_size_spin(self, val: float) -> None:
        if not self._tool:
            return
        self._tool.brush_size = val
        self._size_slider.blockSignals(True)
        self._size_slider.setValue(max(1, round(val * 10)))
        self._size_slider.blockSignals(False)

    def _on_random_size_toggled(self, checked: bool) -> None:
        if not self._tool:
            return
        self._tool.random_brush_size = checked
        self._random_size_details.setVisible(checked)
        self._size_slider.setEnabled(not checked)
        self._size_spin.setEnabled(not checked)

    def _on_rnd_min_slider(self, val: int) -> None:
        if not self._tool:
            return
        v = val / 10.0
        self._tool.random_brush_min = v
        self._rnd_min_spin.blockSignals(True)
        self._rnd_min_spin.setValue(v)
        self._rnd_min_spin.blockSignals(False)

    def _on_rnd_min_spin(self, val: float) -> None:
        if not self._tool:
            return
        self._tool.random_brush_min = val
        self._rnd_min_slider.blockSignals(True)
        self._rnd_min_slider.setValue(max(1, round(val * 10)))
        self._rnd_min_slider.blockSignals(False)

    def _on_rnd_max_slider(self, val: int) -> None:
        if not self._tool:
            return
        v = val / 10.0
        self._tool.random_brush_max = v
        self._rnd_max_spin.blockSignals(True)
        self._rnd_max_spin.setValue(v)
        self._rnd_max_spin.blockSignals(False)

    def _on_rnd_max_spin(self, val: float) -> None:
        if not self._tool:
            return
        self._tool.random_brush_max = val
        self._rnd_max_slider.blockSignals(True)
        self._rnd_max_slider.setValue(max(1, round(val * 10)))
        self._rnd_max_slider.blockSignals(False)

    def _on_hard_slider(self, val: int) -> None:
        if not self._tool:
            return
        h = val / 100.0
        self._tool.hardness = h
        self._hard_spin.blockSignals(True)
        self._hard_spin.setValue(h)
        self._hard_spin.blockSignals(False)

    def _on_hard_spin(self, val: float) -> None:
        if not self._tool:
            return
        self._tool.hardness = val
        self._hard_slider.blockSignals(True)
        self._hard_slider.setValue(int(val * 100))
        self._hard_slider.blockSignals(False)

    def _on_flow_slider(self, val: int) -> None:
        if not self._tool:
            return
        f = max(0.01, val / 100.0)
        self._tool.flow = f
        self._flow_spin.blockSignals(True)
        self._flow_spin.setValue(f)
        self._flow_spin.blockSignals(False)

    def _on_flow_spin(self, val: float) -> None:
        if not self._tool:
            return
        self._tool.flow = val
        self._flow_slider.blockSignals(True)
        self._flow_slider.setValue(max(1, int(val * 100)))
        self._flow_slider.blockSignals(False)

    def _sync_brush_params_from_tool(self) -> None:
        """Sync brush size/hardness/flow UI from tool (called during drag-to-adjust)."""
        if not self._tool:
            return
        self._size_slider.blockSignals(True)
        self._size_spin.blockSignals(True)
        self._size_slider.setValue(max(1, min(5000, round(self._tool.brush_size * 10))))
        self._size_spin.setValue(self._tool.brush_size)
        self._size_slider.blockSignals(False)
        self._size_spin.blockSignals(False)

        self._hard_slider.blockSignals(True)
        self._hard_spin.blockSignals(True)
        self._hard_slider.setValue(int(self._tool.hardness * 100))
        self._hard_spin.setValue(self._tool.hardness)
        self._hard_slider.blockSignals(False)
        self._hard_spin.blockSignals(False)

        self._flow_slider.blockSignals(True)
        self._flow_spin.blockSignals(True)
        self._flow_slider.setValue(max(1, int(self._tool.flow * 100)))
        self._flow_spin.setValue(self._tool.flow)
        self._flow_slider.blockSignals(False)
        self._flow_spin.blockSignals(False)

    # -------------------------------------------------------------------------
    # Color (active channel)
    # -------------------------------------------------------------------------

    def _on_color_pick(self) -> None:
        ch = self._get_active_channel()
        if ch is None:
            return
        color = QColorDialog.getColor(
            QColor(ch.color),
            self.dock.window(), "Channel Color",
        )
        if color.isValid():
            self._apply_channel_edit(color=color.name())
            update_color_btn(self._color_btn, color)

    def _on_opacity_slider(self, val: int) -> None:
        if self._updating_ui:
            return
        o = val / 100.0
        self._opacity_spin.blockSignals(True)
        self._opacity_spin.setValue(o)
        self._opacity_spin.blockSignals(False)
        self._tex_opacity_slider.blockSignals(True)
        self._tex_opacity_slider.setValue(val)
        self._tex_opacity_slider.blockSignals(False)
        self._tex_opacity_spin.blockSignals(True)
        self._tex_opacity_spin.setValue(o)
        self._tex_opacity_spin.blockSignals(False)
        self._apply_channel_edit(opacity=o)

    def _on_opacity_spin(self, val: float) -> None:
        if self._updating_ui:
            return
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(int(val * 100))
        self._opacity_slider.blockSignals(False)
        self._tex_opacity_slider.blockSignals(True)
        self._tex_opacity_slider.setValue(int(val * 100))
        self._tex_opacity_slider.blockSignals(False)
        self._tex_opacity_spin.blockSignals(True)
        self._tex_opacity_spin.setValue(val)
        self._tex_opacity_spin.blockSignals(False)
        self._apply_channel_edit(opacity=val)

    def _on_tex_opacity_slider(self, val: int) -> None:
        if self._updating_ui:
            return
        o = val / 100.0
        self._tex_opacity_spin.blockSignals(True)
        self._tex_opacity_spin.setValue(o)
        self._tex_opacity_spin.blockSignals(False)
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(val)
        self._opacity_slider.blockSignals(False)
        self._opacity_spin.blockSignals(True)
        self._opacity_spin.setValue(o)
        self._opacity_spin.blockSignals(False)
        self._apply_channel_edit(opacity=o)

    def _on_tex_opacity_spin(self, val: float) -> None:
        if self._updating_ui:
            return
        self._tex_opacity_slider.blockSignals(True)
        self._tex_opacity_slider.setValue(int(val * 100))
        self._tex_opacity_slider.blockSignals(False)
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(int(val * 100))
        self._opacity_slider.blockSignals(False)
        self._opacity_spin.blockSignals(True)
        self._opacity_spin.setValue(val)
        self._opacity_spin.blockSignals(False)
        self._apply_channel_edit(opacity=val)

    # -------------------------------------------------------------------------
    # Texture (active channel)
    # -------------------------------------------------------------------------

    def _refresh_texture_filter_combos(self) -> None:
        """Populate Game/Category combos from the current catalog."""
        if not self._texture_catalog:
            return
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

    def _filtered_browser_textures(self) -> list:
        """Return textures matching the current Game/Category/Search filters."""
        if not self._texture_catalog:
            return []
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

    def _on_texture_filter_changed(self) -> None:
        """Rebuild texture grid and sidebar when any filter changes."""
        self._rebuild_texture_grid()
        if self._texture_sidebar and self._texture_sidebar.isVisible():
            self._sync_texture_sidebar()

    def _rebuild_texture_grid(self) -> None:
        for btn in self._texture_buttons.values():
            self._tex_grid.removeWidget(btn)
            btn.deleteLater()
        self._texture_buttons.clear()
        if not self._texture_catalog:
            return
        for i, tex in enumerate(self._filtered_browser_textures()):
            btn = self._make_tex_thumb(tex)
            row = i // _TEX_COLS
            col = i % _TEX_COLS
            self._tex_grid.addWidget(btn, row, col)
            self._texture_buttons[tex.id] = btn
        self._update_texture_selection()

    def _make_tex_thumb(self, tex: LibraryTexture) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(_TEX_THUMB + 12, _TEX_THUMB + 20)
        btn.setToolTip(f"{tex.display_name}\n{tex.category}")
        pixmap = self._get_tex_thumb(tex)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(_TEX_THUMB, _TEX_THUMB))
        btn.setText(tex.display_name[:8])
        btn.clicked.connect(
            lambda checked=False, t=tex: self._on_texture_clicked(t)
        )
        return btn

    def _get_tex_thumb(self, tex: LibraryTexture) -> QPixmap | None:
        if tex.id in self._texture_thumb_cache:
            return self._texture_thumb_cache[tex.id]
        if not tex.exists():
            return None
        pixmap = QPixmap(tex.file_path())
        if pixmap.isNull():
            return None
        pixmap = pixmap.scaled(
            _TEX_THUMB, _TEX_THUMB,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._texture_thumb_cache[tex.id] = pixmap
        return pixmap

    def _on_texture_clicked(self, tex: LibraryTexture) -> None:
        self._apply_channel_edit(texture_id=tex.id)
        # _apply_channel_edit → _update_channel_content will switch to Texture mode
        self._sync_texture_sidebar()

    def _update_texture_selection(self) -> None:
        ch = self._get_active_channel()
        selected_id = ch.texture_id if ch else ""
        for tid, btn in self._texture_buttons.items():
            if tid == selected_id:
                btn.setStyleSheet("QToolButton { border: 2px solid #4488ff; }")
            else:
                btn.setStyleSheet("")

    def _on_tex_zoom_slider(self, val: int) -> None:
        if self._updating_ui:
            return
        z = val / 100.0
        self._tex_zoom_spin.blockSignals(True)
        self._tex_zoom_spin.setValue(z)
        self._tex_zoom_spin.blockSignals(False)
        self._apply_channel_edit(texture_zoom=z)

    def _on_tex_zoom_spin(self, val: float) -> None:
        if self._updating_ui:
            return
        self._tex_zoom_slider.blockSignals(True)
        self._tex_zoom_slider.setValue(int(val * 100))
        self._tex_zoom_slider.blockSignals(False)
        self._apply_channel_edit(texture_zoom=val)

    def _on_tex_rot_slider(self, val: int) -> None:
        if self._updating_ui:
            return
        self._tex_rot_spin.blockSignals(True)
        self._tex_rot_spin.setValue(float(val))
        self._tex_rot_spin.blockSignals(False)
        self._apply_channel_edit(texture_rotation=float(val))

    def _on_tex_rot_spin(self, val: float) -> None:
        if self._updating_ui:
            return
        self._tex_rot_slider.blockSignals(True)
        self._tex_rot_slider.setValue(int(val))
        self._tex_rot_slider.blockSignals(False)
        self._apply_channel_edit(texture_rotation=val)

    # -------------------------------------------------------------------------
    # Outline (layer-level)
    # -------------------------------------------------------------------------

    def _on_outline_toggled(self, checked: bool) -> None:
        self._outline_container.setEnabled(checked)
        self._apply_layer_effect(outline_enabled=checked)

    def _on_outline_color(self) -> None:
        layer = self._get_draw_layer()
        if not layer:
            return
        color = QColorDialog.getColor(
            QColor(layer.outline_color),
            self.dock.window(), "Outline Color",
        )
        if color.isValid():
            update_color_btn(self._outline_color_btn, color)
            self._apply_layer_effect(outline_color=color.name())

    def _on_outline_width_slider(self, val: int) -> None:
        w = val / 2.0
        self._outline_width_spin.blockSignals(True)
        self._outline_width_spin.setValue(w)
        self._outline_width_spin.blockSignals(False)
        self._apply_layer_effect(outline_width=w)

    def _on_outline_width_spin(self, val: float) -> None:
        self._outline_width_slider.blockSignals(True)
        self._outline_width_slider.setValue(int(val * 2))
        self._outline_width_slider.blockSignals(False)
        self._apply_layer_effect(outline_width=val)

    # -------------------------------------------------------------------------
    # Shadow (layer-level)
    # -------------------------------------------------------------------------

    def _on_shadow_toggled(self, checked: bool) -> None:
        self._shadow_container.setEnabled(checked)
        self._apply_layer_effect(shadow_enabled=checked)

    def _on_shadow_type(self, text: str) -> None:
        self._apply_layer_effect(
            shadow_type="inner" if text == "Inner" else "outer"
        )

    def _on_shadow_color(self) -> None:
        layer = self._get_draw_layer()
        if not layer:
            return
        color = QColorDialog.getColor(
            QColor(layer.shadow_color),
            self.dock.window(), "Shadow Color",
        )
        if color.isValid():
            update_color_btn(self._shadow_color_btn, color)
            self._apply_layer_effect(shadow_color=color.name())

    def _on_shadow_opacity_slider(self, val: int) -> None:
        o = val / 100.0
        self._shadow_opacity_spin.blockSignals(True)
        self._shadow_opacity_spin.setValue(o)
        self._shadow_opacity_spin.blockSignals(False)
        self._apply_layer_effect(shadow_opacity=o)

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
        self._apply_layer_effect(
            bevel_type="inner" if text == "Inner" else "outer")

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
        layer = self._get_draw_layer()
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
        layer = self._get_draw_layer()
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

    # -------------------------------------------------------------------------
    # Palette
    # -------------------------------------------------------------------------

    def _d_refresh_palette_combo(self) -> None:
        self._d_palette_combo.blockSignals(True)
        current = self._d_palette_combo.currentText()
        self._d_palette_combo.clear()
        for name in list_palettes():
            self._d_palette_combo.addItem(name)
        idx = self._d_palette_combo.findText(current)
        if idx >= 0:
            self._d_palette_combo.setCurrentIndex(idx)
        self._d_palette_combo.blockSignals(False)

    def _d_on_palette_changed(self, name: str) -> None:
        if not name:
            return
        try:
            self._d_current_palette = load_palette(name)
        except FileNotFoundError:
            self._d_current_palette = None
        self._d_selected_palette_idx = -1
        self._d_rebuild_color_grid()

    def _d_rebuild_color_grid(self) -> None:
        for btn in self._d_palette_color_buttons:
            self._d_color_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._d_palette_color_buttons.clear()
        if not self._d_current_palette:
            return
        for i, pc in enumerate(self._d_current_palette.colors):
            btn = QPushButton()
            btn.setFixedSize(36, 36)
            btn.setToolTip(pc.name)
            self._d_style_palette_btn(btn, pc.color, selected=False)
            btn.clicked.connect(
                lambda checked=False, idx=i: self._d_on_palette_color_clicked(idx)
            )
            row = i // PALETTE_GRID_COLS
            col = i % PALETTE_GRID_COLS
            self._d_color_grid_layout.addWidget(btn, row, col)
            self._d_palette_color_buttons.append(btn)

    def _d_on_palette_color_clicked(self, idx: int) -> None:
        if not self._d_current_palette or idx >= len(self._d_current_palette.colors):
            return
        # Deselect previous
        if 0 <= self._d_selected_palette_idx < len(self._d_palette_color_buttons):
            old_pc = self._d_current_palette.colors[self._d_selected_palette_idx]
            self._d_style_palette_btn(
                self._d_palette_color_buttons[self._d_selected_palette_idx],
                old_pc.color, selected=False,
            )
        # Select new
        self._d_selected_palette_idx = idx
        pc = self._d_current_palette.colors[idx]
        self._d_style_palette_btn(
            self._d_palette_color_buttons[idx], pc.color, selected=True,
        )
        # Apply to active channel
        self._apply_channel_edit(color=QColor(pc.color).name())
        if hasattr(self, "_color_btn"):
            update_color_btn(self._color_btn, QColor(pc.color))

    def _d_style_palette_btn(
        self, btn: QPushButton, color_hex: str, selected: bool
    ) -> None:
        border = "2px solid #00aaff" if selected else "1px solid #555"
        btn.setStyleSheet(
            f"background-color: {color_hex}; border: {border};"
        )
