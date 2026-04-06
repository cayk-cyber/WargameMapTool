"""Main application window."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStatusBar,
)

from app.canvas.canvas_widget import CanvasWidget
from app.commands.command_stack import CommandStack
from app.io.export import export_hexmap, export_pdf, export_png, render_layer_to_image
from app.io.export_svg import export_svg
from app.panels.export_dialog import ExportDialog
from app.panels.palette_editor_dialog import PaletteEditorDialog
from app.panels.calculate_grid_dialog import CalculateGridDialog
from app.panels.shortcuts_dialog import ShortcutsDialog
from app.panels.documentation_dialog import DocumentationDialog
from app.panels.performance_dialog import PerformanceDialog
from app.io.project_io import load_project, save_project
from app.layers.base_layer import Layer
from app.layers.asset_layer import AssetLayer
from app.layers.background_layer import BackgroundImageLayer
from app.layers.border_layer import BorderLayer
from app.layers.draw_layer import DrawLayer
from app.layers.fill_layer import FillLayer, set_fill_quality_mode
from app.layers.freeform_path_layer import FreeformPathLayer
from app.layers.hexside_layer import HexsideLayer
from app.layers.path_layer import PathLayer
from app.layers.sketch_layer import SketchLayer
from app.layers.text_layer import TextLayer
from app.models.project import Project
from app.panels.layer_panel import LayerPanel
from app.panels.new_map_dialog import NewMapDialog
from app.panels.tool_options_panel import ToolOptionsPanel
from app.tools.asset_tool import AssetTool
from app.tools.background_tool import BackgroundTool
from app.tools.border_tool import BorderTool
from app.tools.draw_tool import DrawTool
from app.tools.fill_tool import FillTool
from app.tools.freeform_path_tool import FreeformPathTool
from app.tools.hexside_tool import HexsideTool
from app.tools.path_tool import PathTool
from app.tools.sketch_tool import SketchTool
from app.tools.text_tool import TextTool
from app.tools.tool_manager import ToolManager
from app.io.user_data import load_app_settings, save_app_settings
from app.version import VERSION

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Wargame Map Tool {VERSION}")
        self.resize(1400, 900)

        # Core objects
        self._project = Project()
        self._command_stack = CommandStack(max_size=20)
        self._tool_manager = ToolManager()
        self._global_lighting_dlg = None

        # Canvas
        self._canvas = CanvasWidget(self._project)
        self._canvas.set_tool_manager(self._tool_manager)
        self.setCentralWidget(self._canvas)

        # Register tools
        self._bg_tool = BackgroundTool(self._project, self._command_stack)
        self._fill_tool = FillTool(self._project, self._command_stack)
        self._asset_tool = AssetTool(self._project, self._command_stack)
        self._text_tool = TextTool(self._project, self._command_stack)
        self._hexside_tool = HexsideTool(self._project, self._command_stack)
        self._border_tool = BorderTool(self._project, self._command_stack)
        self._draw_tool = DrawTool(self._project, self._command_stack)
        self._path_tool = PathTool(self._project, self._command_stack)
        self._freeform_path_tool = FreeformPathTool(self._project, self._command_stack)
        self._sketch_tool = SketchTool(self._project, self._command_stack)

        self._tool_manager.register_tool(self._bg_tool)
        self._tool_manager.register_tool(self._fill_tool)
        self._tool_manager.register_tool(self._asset_tool)
        self._tool_manager.register_tool(self._text_tool)
        self._tool_manager.register_tool(self._hexside_tool)
        self._tool_manager.register_tool(self._border_tool)
        self._tool_manager.register_tool(self._draw_tool)
        self._tool_manager.register_tool(self._path_tool)
        self._tool_manager.register_tool(self._freeform_path_tool)
        self._tool_manager.register_tool(self._sketch_tool)

        # Panels
        self._layer_panel = LayerPanel(self._project.layer_stack, self)
        self._layer_panel.layer_add_requested.connect(self._on_add_layer)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._layer_panel)

        self._tool_options_panel = ToolOptionsPanel(self._tool_manager, self)
        self._tool_options_panel.connect_layer_stack(self._project.layer_stack)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._tool_options_panel)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        # Menus
        self._create_menus()

        # Wire signals
        self._command_stack.stack_changed.connect(self._canvas.update)
        self._command_stack.stack_changed.connect(self._update_undo_redo)
        self._command_stack.stack_changed.connect(self._mark_dirty)
        self._project.layer_stack.layers_changed.connect(self._canvas.update)
        self._project.layer_stack.layers_changed.connect(self._layer_panel._refresh_list)
        self._project.layer_stack.layers_changed.connect(self._mark_dirty)

        # Auto-switch tool when active layer changes
        self._project.layer_stack.active_layer_changed.connect(
            self._on_active_layer_changed
        )

        # Reset tool settings when a NEW layer is added by the user
        self._suppress_new_layer_reset: bool = False
        self._new_layer_just_added: bool = False
        self._project.layer_stack.layer_added.connect(self._on_layer_added)

        # Setup minimap (needs canvas + project)
        self._layer_panel.setup_minimap(self._project, self._canvas)
        self._command_stack.stack_changed.connect(
            self._layer_panel._minimap._schedule_render
        )

        # Default state: one layer of each type (bottom-to-top render order)
        self._suppress_new_layer_reset = True
        self._project.layer_stack.add_layer(BackgroundImageLayer("Image"))

        terrain_layer = FillLayer("Terrain")
        default_color = QColor("#c3d89b")
        for h in self._project.grid_config.get_all_hexes():
            terrain_layer.set_fill(h, default_color)
        self._project.layer_stack.add_layer(terrain_layer)

        self._project.layer_stack.add_layer(HexsideLayer("Hexsides"))
        self._project.layer_stack.add_layer(BorderLayer("Borders"))
        self._project.layer_stack.add_layer(PathLayer("Paths"))
        self._project.layer_stack.add_layer(FreeformPathLayer("Freeform Paths"))
        self._project.layer_stack.add_layer(DrawLayer("Draw"))
        self._project.layer_stack.add_layer(TextLayer("Text"))
        self._project.layer_stack.add_layer(SketchLayer("Sketches"))
        self._project.layer_stack.add_layer(AssetLayer("Assets"))
        self._suppress_new_layer_reset = False

        # Sync tool to match the active layer at startup
        self._on_active_layer_changed()

        # Initial state is clean (default layers don't count as unsaved changes)
        self._project.dirty = False

    def _create_menus(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        new_action = QAction("&New", self)
        new_action.setShortcut(QKeySequence("Ctrl+N"))
        new_action.triggered.connect(self._on_new)
        file_menu.addAction(new_action)

        open_action = QAction("&Open...", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self._on_save)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save &As...", self)
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(self._on_save_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        export_action = QAction("&Export...", self)
        export_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        self._undo_action = QAction("&Undo", self)
        self._undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self._undo_action.triggered.connect(self._command_stack.undo)
        self._undo_action.setEnabled(False)
        edit_menu.addAction(self._undo_action)

        self._redo_action = QAction("&Redo", self)
        self._redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        self._redo_action.triggered.connect(self._command_stack.redo)
        self._redo_action.setEnabled(False)
        edit_menu.addAction(self._redo_action)

        edit_menu.addSeparator()

        settings_action = QAction("Map &Settings...", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._on_map_settings)
        edit_menu.addAction(settings_action)

        palettes_action = QAction("Edit &Palettes...", self)
        palettes_action.setShortcut(QKeySequence("Ctrl+P"))
        palettes_action.triggered.connect(self._on_edit_palettes)
        edit_menu.addAction(palettes_action)

        edit_menu.addSeparator()

        calc_grid_action = QAction("&Calculate Grid...", self)
        calc_grid_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        calc_grid_action.setToolTip(
            "Calculate the required hex grid size for a real-world area"
        )
        calc_grid_action.triggered.connect(self._on_calculate_grid)
        edit_menu.addAction(calc_grid_action)

        edit_menu.addSeparator()

        render_layer_action = QAction("&Render Layer to Image...", self)
        render_layer_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        render_layer_action.setToolTip(
            "Render the active layer to a PNG image and replace it with an Image layer"
        )
        render_layer_action.triggered.connect(self._on_render_layer_to_image)
        edit_menu.addAction(render_layer_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        zoom_fit_action = QAction("Zoom to &Fit", self)
        zoom_fit_action.setShortcut(QKeySequence("Ctrl+0"))
        zoom_fit_action.triggered.connect(self._canvas.zoom_to_fit)
        view_menu.addAction(zoom_fit_action)

        view_menu.addSeparator()

        self._toggle_grid_action = QAction("Show &Grid", self)
        self._toggle_grid_action.setCheckable(True)
        self._toggle_grid_action.setChecked(self._project.grid_config.show_grid)
        self._toggle_grid_action.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self._toggle_grid_action.triggered.connect(self._toggle_grid)
        view_menu.addAction(self._toggle_grid_action)

        self._toggle_grid_dots_action = QAction("Show Center &Dots", self)
        self._toggle_grid_dots_action.setCheckable(True)
        self._toggle_grid_dots_action.setChecked(self._project.grid_config.show_center_dots)
        self._toggle_grid_dots_action.setShortcut(QKeySequence("Ctrl+D"))
        self._toggle_grid_dots_action.triggered.connect(self._toggle_center_dots)
        view_menu.addAction(self._toggle_grid_dots_action)

        self._toggle_grid_coords_action = QAction("Show &Coordinates", self)
        self._toggle_grid_coords_action.setCheckable(True)
        self._toggle_grid_coords_action.setChecked(self._project.grid_config.show_coordinates)
        self._toggle_grid_coords_action.setShortcut(QKeySequence("Ctrl+K"))
        self._toggle_grid_coords_action.triggered.connect(self._toggle_coordinates)
        view_menu.addAction(self._toggle_grid_coords_action)

        self._toggle_megahexes_action = QAction("Show Mega&hexes", self)
        self._toggle_megahexes_action.setCheckable(True)
        self._toggle_megahexes_action.setChecked(self._project.grid_config.megahex_enabled)
        self._toggle_megahexes_action.setEnabled(self._project.grid_config.megahex_enabled)
        self._toggle_megahexes_action.setShortcut(QKeySequence("Ctrl+G"))
        self._toggle_megahexes_action.triggered.connect(self._toggle_megahexes)
        view_menu.addAction(self._toggle_megahexes_action)

        view_menu.addSeparator()

        self._toggle_minimap_action = QAction("Show &Minimap", self)
        self._toggle_minimap_action.setCheckable(True)
        self._toggle_minimap_action.setChecked(True)
        self._toggle_minimap_action.setShortcut(QKeySequence("Ctrl+M"))
        self._toggle_minimap_action.triggered.connect(self._toggle_minimap)
        view_menu.addAction(self._toggle_minimap_action)

        view_menu.addSeparator()

        bg_color_action = QAction("Set Background &Color...", self)
        bg_color_action.setShortcut(QKeySequence("Ctrl+B"))
        bg_color_action.triggered.connect(self._on_set_bg_color)
        view_menu.addAction(bg_color_action)

        global_lighting_action = QAction("Global &Lighting...", self)
        global_lighting_action.setShortcut(QKeySequence("Ctrl+L"))
        global_lighting_action.triggered.connect(self._on_global_lighting)
        view_menu.addAction(global_lighting_action)

        view_menu.addSeparator()

        perf_action = QAction("&Performance...", self)
        perf_action.triggered.connect(self._on_performance)
        view_menu.addAction(perf_action)
        self._perf_dlg: PerformanceDialog | None = None

        # Hidden shortcut actions for quick toggling without opening dialog
        _sc_rq = QAction(self)
        _sc_rq.setShortcut(QKeySequence("Ctrl+Shift+Q"))
        _sc_rq.triggered.connect(self._on_shortcut_toggle_render_quality)
        self.addAction(_sc_rq)

        _sc_cd = QAction(self)
        _sc_cd.setShortcut(QKeySequence("Ctrl+Shift+D"))
        _sc_cd.triggered.connect(self._on_shortcut_cycle_cache_delay)
        self.addAction(_sc_cd)

        _sc_zs = QAction(self)
        _sc_zs.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        _sc_zs.triggered.connect(self._on_shortcut_cycle_zoom_settle)
        self.addAction(_sc_zs)

        _sc_gfx = QAction(self)
        _sc_gfx.setShortcut(QKeySequence("Ctrl+E"))
        _sc_gfx.triggered.connect(self._on_shortcut_toggle_gfx_visible)
        self.addAction(_sc_gfx)

        # Apply persisted settings (defaults)
        _settings = load_app_settings()

        self._render_quality: bool = _settings.get("render_quality", "performance") == "quality"
        set_fill_quality_mode(self._render_quality)

        self._cd_values = [0, 50, 100, 200, 500]
        self._cache_delay: int = _settings.get("cache_rebuild_delay", 200)
        if self._cache_delay not in self._cd_values:
            self._cache_delay = 200
        self._canvas.set_cache_rebuild_delay(self._cache_delay)

        self._zs_values = [50, 100, 200, 300, 500, 1000]
        self._zoom_settle: int = _settings.get("zoom_settle_delay", 200)
        if self._zoom_settle not in self._zs_values:
            self._zoom_settle = 200
        self._canvas.set_zoom_settle_delay(self._zoom_settle)

        self._gfx_visible: bool = _settings.get("gfx_visible", True)
        Layer._gfx_effects_enabled = self._gfx_visible

        # Help menu
        help_menu = menubar.addMenu("&Help")

        docs_action = QAction("&Documentation...", self)
        docs_action.setShortcut(QKeySequence("F2"))
        docs_action.triggered.connect(self._on_documentation)
        help_menu.addAction(docs_action)

        help_menu.addSeparator()

        shortcuts_action = QAction("&Shortcuts...", self)
        shortcuts_action.setShortcut(QKeySequence("F1"))
        shortcuts_action.triggered.connect(self._on_shortcuts)
        help_menu.addAction(shortcuts_action)

    # --- File operations ---

    def _on_new(self):
        if not self._check_unsaved_changes():
            return
        dialog = NewMapDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        config = dialog.get_config()
        fill_color = dialog.get_fill_color()
        self._apply_new_project(config, fill_color=fill_color)

    def _disconnect_project_signals(self) -> None:
        """Disconnect all signals from the current project's layer stack."""
        ls = self._project.layer_stack
        try:
            ls.layers_changed.disconnect(self._canvas.update)
        except RuntimeError:
            pass
        try:
            ls.layers_changed.disconnect(self._layer_panel._refresh_list)
        except RuntimeError:
            pass
        try:
            ls.layers_changed.disconnect(self._mark_dirty)
        except RuntimeError:
            pass
        try:
            ls.active_layer_changed.disconnect(self._on_active_layer_changed)
        except RuntimeError:
            pass
        try:
            ls.layer_added.disconnect(self._on_layer_added)
        except RuntimeError:
            pass

    def _apply_new_project(self, config=None, fill_color: QColor | None = None):
        # Disconnect old project signals to avoid dangling connections
        self._disconnect_project_signals()
        # Clear stale tool callbacks that reference the about-to-be-deleted UI widgets
        self._draw_tool._params_changed_cb = None
        self._bg_tool._on_offset_changed = None
        if self._global_lighting_dlg:
            self._global_lighting_dlg.close()
            self._global_lighting_dlg = None
        self._project = Project()
        if config is not None:
            self._project.grid_config = config
        self._canvas._project = self._project
        self._canvas.reset_caches()
        self._layer_panel._layer_stack = self._project.layer_stack
        self._tool_options_panel.invalidate_cache()
        # Rebuild current tool's options panel after cache was cleared
        active_tool = self._tool_manager.active_tool
        if active_tool:
            self._tool_options_panel._on_tool_changed(active_tool.name)
        self._project.layer_stack.layers_changed.connect(self._canvas.update)
        self._project.layer_stack.layers_changed.connect(self._layer_panel._refresh_list)
        self._project.layer_stack.layers_changed.connect(self._mark_dirty)
        self._project.layer_stack.active_layer_changed.connect(
            self._on_active_layer_changed
        )
        self._project.layer_stack.layer_added.connect(self._on_layer_added)
        self._tool_options_panel.connect_layer_stack(self._project.layer_stack)
        self._bg_tool._project = self._project
        self._fill_tool._project = self._project
        self._asset_tool._project = self._project
        self._text_tool._project = self._project
        self._hexside_tool._project = self._project
        self._border_tool._project = self._project
        self._draw_tool._project = self._project
        self._path_tool._project = self._project
        self._freeform_path_tool._project = self._project
        self._sketch_tool._project = self._project
        self._command_stack.clear()

        # Create initial layers for new map
        if fill_color is not None:
            self._suppress_new_layer_reset = True
            terrain = FillLayer("Terrain")
            for h in self._project.grid_config.get_all_hexes():
                terrain.set_fill(h, fill_color)
            self._project.layer_stack.add_layer(terrain)
            self._suppress_new_layer_reset = False

        self._layer_panel._refresh_list()
        self._layer_panel.update_minimap_project(self._project)
        self._canvas.zoom_to_fit()
        self._toggle_megahexes_action.setChecked(self._project.grid_config.megahex_enabled)
        self._toggle_megahexes_action.setEnabled(self._project.grid_config.megahex_enabled)
        self._toggle_grid_action.setChecked(self._project.grid_config.show_grid)
        self._toggle_grid_dots_action.setChecked(self._project.grid_config.show_center_dots)
        self._toggle_grid_coords_action.setChecked(self._project.grid_config.show_coordinates)
        self.setWindowTitle(f"Wargame Map Tool {VERSION}")
        self._on_active_layer_changed()
        self._project.dirty = False

    def _on_open(self):
        if not self._check_unsaved_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "Hex Map Files (*.hexmap);;All Files (*)"
        )
        if not path:
            return
        try:
            project = load_project(path)
            # Disconnect old project signals to avoid dangling connections
            self._disconnect_project_signals()
            # Clear stale tool callbacks that reference the about-to-be-deleted UI widgets
            self._draw_tool._params_changed_cb = None
            self._bg_tool._on_offset_changed = None
            if self._global_lighting_dlg:
                self._global_lighting_dlg.close()
                self._global_lighting_dlg = None
            self._project = project
            self._canvas._project = project
            self._layer_panel._layer_stack = project.layer_stack
            self._tool_options_panel.invalidate_cache()
            # Rebuild current tool's options panel after cache was cleared
            active_tool = self._tool_manager.active_tool
            if active_tool:
                self._tool_options_panel._on_tool_changed(active_tool.name)
            project.layer_stack.layers_changed.connect(self._canvas.update)
            project.layer_stack.layers_changed.connect(self._layer_panel._refresh_list)
            project.layer_stack.layers_changed.connect(self._mark_dirty)
            project.layer_stack.active_layer_changed.connect(
                self._on_active_layer_changed
            )
            project.layer_stack.layer_added.connect(self._on_layer_added)
            self._tool_options_panel.connect_layer_stack(project.layer_stack)
            self._bg_tool._project = project
            self._fill_tool._project = project
            self._asset_tool._project = project
            self._text_tool._project = project
            self._hexside_tool._project = project
            self._border_tool._project = project
            self._draw_tool._project = project
            self._path_tool._project = project
            self._freeform_path_tool._project = project
            self._sketch_tool._project = project
            self._command_stack.clear()
            self._layer_panel._refresh_list()
            self._layer_panel.update_minimap_project(project)
            self._canvas.zoom_to_fit()
            self._toggle_megahexes_action.setChecked(project.grid_config.megahex_enabled)
            self._toggle_megahexes_action.setEnabled(project.grid_config.megahex_enabled)
            self._toggle_grid_action.setChecked(project.grid_config.show_grid)
            self._toggle_grid_dots_action.setChecked(project.grid_config.show_center_dots)
            self._toggle_grid_coords_action.setChecked(project.grid_config.show_coordinates)
            self.setWindowTitle(f"Wargame Map Tool {VERSION} – {os.path.basename(path)}")
            self._on_active_layer_changed()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{e}")

    def _on_save(self):
        if self._project.file_path:
            self._save_to(self._project.file_path)
        else:
            self._on_save_as()

    def _on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "", "Hex Map Files (*.hexmap);;All Files (*)"
        )
        if path:
            self._save_to(path)

    def _save_to(self, path: str):
        try:
            save_project(self._project, path)
            self.setWindowTitle(f"Wargame Map Tool {VERSION} – {os.path.basename(path)}")
            self._status_bar.showMessage(f"Saved: {os.path.basename(path)}", 3000)
            self._show_save_toast()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save:\n{e}")

    def _show_save_toast(self) -> None:
        """Briefly show a 'Saved' overlay on the canvas."""
        self._show_toast("Saved", "rgba(40, 180, 80, 210)")

    def _show_setting_toast(self, text: str) -> None:
        """Briefly show an orange setting-change overlay on the canvas."""
        self._show_toast(text, "rgba(220, 140, 20, 220)")

    def _show_toast(self, text: str, bg_color: str) -> None:
        """Show a brief toast notification on the canvas."""
        toast = QLabel(text, self._canvas)
        toast.setStyleSheet(
            f"background-color: {bg_color};"
            "color: white;"
            "font-weight: bold;"
            "font-size: 14px;"
            "border-radius: 6px;"
            "padding: 5px 16px;"
        )
        toast.adjustSize()
        toast.move((self._canvas.width() - toast.width()) // 2, 18)
        toast.show()
        toast.raise_()
        QTimer.singleShot(1400, toast.deleteLater)

    def _get_project_name(self) -> str:
        """Derive project name from file path or return 'Untitled'."""
        if self._project.file_path:
            return os.path.splitext(os.path.basename(self._project.file_path))[0]
        return "Untitled"

    def _on_export(self):
        project_name = self._get_project_name()
        # Build layer list top-to-bottom (reversed stack order, matching layer panel)
        layers = [
            (layer.id, layer.name)
            for layer in reversed(list(self._project.layer_stack))
        ]
        dialog = ExportDialog(self._project.grid_config, project_name, layers, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        settings = dialog.get_settings()
        default_name = dialog.get_default_basename()

        # Build file filter from selected formats
        filters = []
        if "png" in settings.formats:
            filters.append("PNG Images (*.png)")
        if "pdf" in settings.formats:
            filters.append("PDF Files (*.pdf)")
        if "svg" in settings.formats:
            filters.append("SVG Images (*.svg)")
        if "hexmap" in settings.formats:
            filters.append("Hex Map Files (*.hexmap)")
        # Use "All Files" as the dialog filter — the base name determines the path
        file_filter = "All Files (*)"

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Map", default_name, file_filter
        )
        if not path:
            return

        # Strip any known extension to get the base path
        base, ext = os.path.splitext(path)
        if ext.lower() in (".png", ".pdf", ".svg", ".hexmap"):
            path_base = base
        else:
            path_base = path

        progress = QProgressDialog("Exporting map, please wait…", None, 0, 0, self)
        progress.setWindowTitle("Exporting")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        exported: list[str] = []
        failed = False

        if "png" in settings.formats:
            png_path = path_base + ".png"
            if export_png(self._project, png_path, settings):
                exported.append(png_path)
            else:
                failed = True

        if "pdf" in settings.formats:
            pdf_path = path_base + ".pdf"
            if export_pdf(self._project, pdf_path, settings):
                exported.append(pdf_path)
            else:
                failed = True

        if "svg" in settings.formats:
            svg_path = path_base + ".svg"
            if export_svg(self._project, svg_path, settings):
                exported.append(svg_path)
            else:
                failed = True

        if "hexmap" in settings.formats:
            hexmap_path = path_base + ".hexmap"
            if export_hexmap(self._project, hexmap_path):
                exported.append(hexmap_path)
            else:
                failed = True

        progress.close()

        if exported:
            file_list = "\n".join(exported)
            self._status_bar.showMessage(f"Exported {len(exported)} file(s)", 5000)
            QMessageBox.information(
                self, "Export Successful",
                f"Map exported successfully:\n\n{file_list}",
            )
        if failed and not exported:
            QMessageBox.warning(self, "Export", "Export failed or map is empty.")

    # --- Edit operations ---

    def _update_undo_redo(self):
        self._undo_action.setEnabled(self._command_stack.can_undo)
        self._redo_action.setEnabled(self._command_stack.can_redo)

    def _on_map_settings(self):
        dialog = NewMapDialog(self, settings_only=True)
        dialog._apply_config(self._project.grid_config)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_config = dialog.get_config()
        config = self._project.grid_config

        # Copy visual fields only (not layout: hex_size, width, height, orientation, first_row_offset)
        config.line_width = new_config.line_width
        config.edge_color = new_config.edge_color
        config.grid_style = new_config.grid_style
        config.show_center_dots = new_config.show_center_dots
        config.center_dot_size = new_config.center_dot_size
        config.center_dot_color = new_config.center_dot_color
        config.center_dot_outline = new_config.center_dot_outline
        config.center_dot_outline_width = new_config.center_dot_outline_width
        config.center_dot_outline_color = new_config.center_dot_outline_color
        config.show_coordinates = new_config.show_coordinates
        config.coord_position = new_config.coord_position
        config.coord_format = new_config.coord_format
        config.coord_offset_y = new_config.coord_offset_y
        config.coord_font_scale = new_config.coord_font_scale
        config.coord_start_one = new_config.coord_start_one
        config.show_border = new_config.show_border
        config.border_color = new_config.border_color
        config.border_margin = new_config.border_margin
        config.border_fill = new_config.border_fill
        config.border_fill_color = new_config.border_fill_color
        config.half_hexes = new_config.half_hexes
        config.megahex_enabled = new_config.megahex_enabled
        config.megahex_radius = new_config.megahex_radius
        config.megahex_mode = new_config.megahex_mode
        config.megahex_color = new_config.megahex_color
        config.megahex_width = new_config.megahex_width
        config.megahex_offset_q = new_config.megahex_offset_q
        config.megahex_offset_r = new_config.megahex_offset_r
        self._toggle_megahexes_action.setChecked(config.megahex_enabled)
        self._toggle_megahexes_action.setEnabled(config.megahex_enabled)

        # Invalidate all layer caches (bounds may have changed)
        for layer in self._project.layer_stack:
            layer.mark_dirty()

        self._canvas.zoom_to_fit()

    def _on_edit_palettes(self):
        dialog = PaletteEditorDialog(self)
        dialog.catalog_changed.connect(self._tool_options_panel.refresh_palette_catalog)
        dialog.exec()

    def _on_calculate_grid(self):
        dialog = CalculateGridDialog(parent=self)
        dialog.exec()

    def _on_render_layer_to_image(self):
        """Render the active layer to a PNG, then replace it with an Image layer."""
        stack = self._project.layer_stack
        layer = stack.active_layer
        if layer is None:
            QMessageBox.warning(self, "Render Layer", "No layer selected.")
            return
        if isinstance(layer, BackgroundImageLayer):
            QMessageBox.warning(
                self, "Render Layer",
                "Image layers cannot be rendered — they are already images.",
            )
            return

        layer_index = stack.active_index
        default_name = f"{layer.name}.png"

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Rendered Layer", default_name, "PNG Images (*.png)"
        )
        if not path:
            return

        progress = QProgressDialog("Rendering layer, please wait…", None, 0, 0, self)
        progress.setWindowTitle("Rendering")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        ok = render_layer_to_image(self._project, layer.id, path)

        progress.close()

        if not ok:
            QMessageBox.warning(
                self, "Render Layer",
                "Layer is empty or could not be rendered.",
            )
            return

        # 1. Create a new Image layer above the rendered layer
        bounds = self._project.grid_config.get_effective_bounds()
        new_layer = BackgroundImageLayer(f"{layer.name} (rendered)")
        if not new_layer.load_image(path):
            QMessageBox.warning(
                self, "Render Layer",
                "Rendered image could not be loaded.",
            )
            return
        new_layer.offset_x = bounds.x()
        new_layer.offset_y = bounds.y()
        new_layer.scale = 1.0

        insert_index = layer_index + 1
        stack.add_layer(new_layer, insert_index)

        # 2. Hide the original layer
        layer.visible = False

        # 3. Refresh UI
        stack.layers_changed.emit()
        self._on_active_layer_changed()

        self._status_bar.showMessage(
            f"Layer '{layer.name}' rendered to image: {path}", 5000
        )

    def _on_documentation(self):
        dialog = DocumentationDialog(self)
        dialog.exec()

    def _on_shortcuts(self):
        dialog = ShortcutsDialog(self)
        dialog.exec()

    # --- View operations ---

    def _toggle_grid(self, checked: bool):
        self._project.grid_config.show_grid = checked
        self._canvas.update()

    def _toggle_center_dots(self, checked: bool):
        self._project.grid_config.show_center_dots = checked
        self._canvas.update()

    def _toggle_coordinates(self, checked: bool):
        self._project.grid_config.show_coordinates = checked
        self._canvas.update()

    def _toggle_megahexes(self, checked: bool):
        self._project.grid_config.megahex_enabled = checked
        self._toggle_megahexes_action.setEnabled(checked)
        self._canvas.update()

    def _toggle_minimap(self, checked: bool):
        self._layer_panel.set_minimap_visible(checked)

    def _on_set_bg_color(self):
        current = self._project.grid_config.canvas_bg_color
        color = QColorDialog.getColor(current, self, "Canvas Background Color")
        if color.isValid():
            self._project.grid_config.canvas_bg_color = color
            self._canvas.update()

    def _on_global_lighting(self) -> None:
        from app.panels.global_lighting_dialog import GlobalLightingDialog
        if self._global_lighting_dlg and self._global_lighting_dlg.isVisible():
            self._global_lighting_dlg.raise_()
            self._global_lighting_dlg.activateWindow()
            return
        self._global_lighting_dlg = GlobalLightingDialog(self._project, self._canvas, self)
        self._global_lighting_dlg.show()

    def _on_performance(self) -> None:
        if self._perf_dlg is not None and self._perf_dlg.isVisible():
            self._perf_dlg.raise_()
            self._perf_dlg.activateWindow()
            return
        dlg = PerformanceDialog(self)
        dlg.set_render_quality(self._render_quality)
        dlg.set_cache_delay(self._cache_delay)
        dlg.set_zoom_settle(self._zoom_settle)
        dlg.set_gfx_visible(self._gfx_visible)
        dlg.render_quality_changed.connect(self._apply_render_quality)
        dlg.cache_delay_changed.connect(self._apply_cache_delay)
        dlg.zoom_settle_changed.connect(self._apply_zoom_settle)
        dlg.gfx_visible_changed.connect(self._apply_gfx_visible)
        self._perf_dlg = dlg
        dlg.show()

    # -- Apply helpers (shared between dialog and keyboard shortcuts) --

    def _apply_render_quality(self, quality: bool) -> None:
        self._render_quality = quality
        set_fill_quality_mode(quality)
        for layer in self._project.layer_stack._layers:
            if isinstance(layer, FillLayer):
                layer.mark_dirty()
        self._canvas.update()
        settings = load_app_settings()
        settings["render_quality"] = "quality" if quality else "performance"
        save_app_settings(settings)
        label = "Quality" if quality else "Performance"
        self._show_setting_toast(f"Render Quality: {label}")
        if self._perf_dlg and self._perf_dlg.isVisible():
            self._perf_dlg.set_render_quality(quality)

    def _apply_cache_delay(self, ms: int) -> None:
        self._cache_delay = ms
        self._canvas.set_cache_rebuild_delay(ms)
        settings = load_app_settings()
        settings["cache_rebuild_delay"] = ms
        save_app_settings(settings)
        label = "None" if ms == 0 else f"{ms} ms"
        self._show_setting_toast(f"Cache Delay: {label}")
        if self._perf_dlg and self._perf_dlg.isVisible():
            self._perf_dlg.set_cache_delay(ms)

    def _apply_zoom_settle(self, ms: int) -> None:
        self._zoom_settle = ms
        self._canvas.set_zoom_settle_delay(ms)
        settings = load_app_settings()
        settings["zoom_settle_delay"] = ms
        save_app_settings(settings)
        label = f"{ms} ms"
        self._show_setting_toast(f"Zoom Settle: {label}")
        if self._perf_dlg and self._perf_dlg.isVisible():
            self._perf_dlg.set_zoom_settle(ms)

    def _apply_gfx_visible(self, visible: bool) -> None:
        self._gfx_visible = visible
        Layer._gfx_effects_enabled = visible
        for layer in self._project.layer_stack:
            layer.mark_dirty()
            if hasattr(layer, '_effects_cache_pixmap'):
                layer._effects_cache_pixmap = None
        self._canvas.update()
        settings = load_app_settings()
        settings["gfx_visible"] = visible
        save_app_settings(settings)
        label = "ON" if visible else "OFF"
        self._show_setting_toast(f"Visible GFX: {label}")
        if self._perf_dlg and self._perf_dlg.isVisible():
            self._perf_dlg.set_gfx_visible(visible)

    # -- Keyboard shortcut handlers --

    def _on_shortcut_toggle_render_quality(self) -> None:
        self._apply_render_quality(not self._render_quality)

    def _on_shortcut_cycle_cache_delay(self) -> None:
        try:
            idx = self._cd_values.index(self._cache_delay)
        except ValueError:
            idx = 3
        ms = self._cd_values[(idx + 1) % len(self._cd_values)]
        self._apply_cache_delay(ms)

    def _on_shortcut_cycle_zoom_settle(self) -> None:
        try:
            idx = self._zs_values.index(self._zoom_settle)
        except ValueError:
            idx = 2
        ms = self._zs_values[(idx + 1) % len(self._zs_values)]
        self._apply_zoom_settle(ms)

    def _on_shortcut_toggle_gfx_visible(self) -> None:
        self._apply_gfx_visible(not self._gfx_visible)

    # --- Layer operations ---

    def _on_add_layer(self, layer_type: str, layer_name: str):
        # Insert above the active layer (or at top if none selected)
        active_idx = self._project.layer_stack.active_index
        insert_idx = active_idx + 1 if active_idx >= 0 else 0
        if layer_type == "Fill":
            layer = FillLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Asset":
            layer = AssetLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Text":
            layer = TextLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Hexside":
            layer = HexsideLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Border":
            layer = BorderLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Draw":
            layer = DrawLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Path (Center)":
            layer = PathLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Path (Freeform)":
            layer = FreeformPathLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Sketch":
            layer = SketchLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        elif layer_type == "Image":
            layer = BackgroundImageLayer(layer_name)
            self._project.layer_stack.add_layer(layer, insert_idx)
        self._on_active_layer_changed()

    def _on_layer_added(self, index: int) -> None:
        """Reset tool settings when a new layer is added by the user."""
        if self._suppress_new_layer_reset:
            return
        try:
            layer = self._project.layer_stack[index]
        except (IndexError, KeyError):
            return
        tool = self._tool_for_layer(layer)
        if tool is None:
            return
        tool.reset_to_defaults()
        self._tool_options_panel.invalidate_tool_cache(tool.name)
        self._new_layer_just_added = True

    def _tool_for_layer(self, layer):
        """Return the tool instance that corresponds to a given layer type."""
        if isinstance(layer, FillLayer):
            return self._fill_tool
        if isinstance(layer, AssetLayer):
            return self._asset_tool
        if isinstance(layer, TextLayer):
            return self._text_tool
        if isinstance(layer, HexsideLayer):
            return self._hexside_tool
        if isinstance(layer, BorderLayer):
            return self._border_tool
        if isinstance(layer, DrawLayer):
            return self._draw_tool
        if isinstance(layer, PathLayer):
            return self._path_tool
        if isinstance(layer, FreeformPathLayer):
            return self._freeform_path_tool
        if isinstance(layer, SketchLayer):
            return self._sketch_tool
        if isinstance(layer, BackgroundImageLayer):
            return self._bg_tool
        return None

    def _on_active_layer_changed(self):
        """Auto-switch tool to match the active layer type."""
        layer = self._project.layer_stack.active_layer
        if layer is None:
            return

        if isinstance(layer, FillLayer):
            tool_name = "Fill"
        elif isinstance(layer, AssetLayer):
            tool_name = "Asset"
        elif isinstance(layer, TextLayer):
            tool_name = "Text"
        elif isinstance(layer, HexsideLayer):
            tool_name = "Hexside"
        elif isinstance(layer, BorderLayer):
            tool_name = "Border"
        elif isinstance(layer, DrawLayer):
            tool_name = "Draw"
        elif isinstance(layer, PathLayer):
            tool_name = "Path (Center)"
        elif isinstance(layer, FreeformPathLayer):
            tool_name = "Path (Freeform)"
        elif isinstance(layer, SketchLayer):
            tool_name = "Sketch"
        else:
            tool_name = "Background"

        # If a new layer was just created, always force a full options rebuild
        # (even if it's the same tool type) so defaults are shown in the UI.
        force_rebuild = self._new_layer_just_added
        self._new_layer_just_added = False
        if not force_rebuild and self._tool_manager.active_tool and self._tool_manager.active_tool.name == tool_name:
            return
        self._tool_manager.set_active_tool(tool_name)

    def _mark_dirty(self) -> None:
        """Mark the project as having unsaved changes."""
        self._project.dirty = True

    def _check_unsaved_changes(self) -> bool:
        """Check for unsaved changes. Returns True if safe to proceed."""
        if not self._project.dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved changes. Do you want to save first?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Save:
            self._on_save()
            return not self._project.dirty
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        return False

    def closeEvent(self, event):
        if self._check_unsaved_changes():
            super().closeEvent(event)
        else:
            event.ignore()

    def showEvent(self, event):
        super().showEvent(event)
        self._canvas.zoom_to_fit()
