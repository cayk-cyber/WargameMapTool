"""Tool options dock widget - framework shell that dispatches to tool-specific builders."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDockWidget,
    QFrame,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.panels.tool_options.helpers import (
    SCROLL_GUARD_TYPES,
    NoScrollFilter,
)
from app.panels.tool_options.background_options import BackgroundOptions
from app.panels.tool_options.border_options import BorderOptions
from app.panels.tool_options.draw_options import DrawOptions
from app.panels.tool_options.fill_options import FillOptions
from app.panels.tool_options.text_options import TextOptions
from app.panels.tool_options.hexside_options import HexsideOptions
from app.panels.tool_options.path_options import PathOptions
from app.panels.tool_options.freeform_path_options import FreeformPathOptions
from app.panels.tool_options.asset_options import AssetOptions
from app.panels.tool_options.sketch_options import SketchOptions
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


class ToolOptionsPanel(QDockWidget):
    def __init__(self, tool_manager: ToolManager, parent=None):
        super().__init__("Tool Options", parent)
        self._tool_manager = tool_manager
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(320)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)

        self._options_widget: QWidget | None = None
        self._saved_width: int = 0  # saved before sidebar opens
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Cache widgets per tool type to avoid expensive rebuilds
        self._cached_widgets: dict[str, QWidget] = {}

        # Track catalog versions per builder so we only refresh when
        # the underlying catalog has actually changed (import/delete/rename).
        # Key = builder cache_key, value = (texture_ver, asset_ver)
        self._seen_texture_version: dict[str, int] = {}
        self._seen_asset_version: dict[str, int] = {}

        self._no_scroll_filter = NoScrollFilter(self)

        # Wrap container in a scroll area so tall tool options don't overflow
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setWidget(self._container)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidget(self._scroll_area)

        # Tool-specific option builders
        self._bg_options = BackgroundOptions(self)
        self._border_options = BorderOptions(self)
        self._draw_options = DrawOptions(self)
        self._fill_options = FillOptions(self)
        self._text_options = TextOptions(self)
        self._hexside_options = HexsideOptions(self)
        self._path_options = PathOptions(self)
        self._freeform_path_options = FreeformPathOptions(self)
        self._asset_options = AssetOptions(self)
        self._sketch_options = SketchOptions(self)

        tool_manager.tool_changed.connect(self._on_tool_changed)

    # --- Sidebar width management ---

    def _save_panel_width(self) -> None:
        """Save current panel width before a sidebar opens."""
        self._saved_width = self.width()

    def _restore_panel_width(self) -> None:
        """Restore panel width after a sidebar closes.

        Only resizes if the panel was actually compressed by the sidebar opening.
        Resets _saved_width to 0 immediately to prevent double-calls from
        the closed-signal + setChecked(False) toggle pattern.
        """
        if self._saved_width > 0:
            saved = self._saved_width
            self._saved_width = 0  # prevent double-call
            if self.width() < saved:
                main_win = self.window()
                if hasattr(main_win, "resizeDocks"):
                    main_win.resizeDocks(
                        [self], [saved], Qt.Orientation.Horizontal,
                    )

    def invalidate_cache(self) -> None:
        """Clear cached widgets (call after New/Open project)."""
        self._close_sidebar()
        for w in self._cached_widgets.values():
            w.hide()
            self._layout.removeWidget(w)
            w.deleteLater()
        self._cached_widgets.clear()
        self._seen_texture_version.clear()
        self._seen_asset_version.clear()
        self._options_widget = None

    def invalidate_tool_cache(self, name: str) -> None:
        """Remove one tool's cached widget so it is rebuilt from scratch next time."""
        w = self._cached_widgets.pop(name, None)
        if w is None:
            return
        if w is self._options_widget:
            self._options_widget = None
        w.hide()
        self._layout.removeWidget(w)
        w.deleteLater()
        self._seen_texture_version.pop(name, None)
        self._seen_asset_version.pop(name, None)

    def connect_layer_stack(self, layer_stack) -> None:
        """Connect to layer stack signals for active layer sync."""
        layer_stack.active_layer_changed.connect(self._on_active_layer_changed)

    def _on_active_layer_changed(self) -> None:
        """Sync options when active layer changes (same tool, different layer)."""
        tool = self._tool_manager.active_tool
        if isinstance(tool, BackgroundTool) and "Background" in self._cached_widgets:
            self._bg_options.sync_from_layer()
        # Sync Draw and Asset tools when the active layer changes
        elif isinstance(tool, DrawTool) and "Draw" in self._cached_widgets:
            self._draw_options._rebuild_channel_list()
            self._draw_options.sync_effects_from_layer()
        elif isinstance(tool, AssetTool) and "Asset" in self._cached_widgets:
            self._asset_options._refresh_auto_text_layer_combo()
            self._asset_options.sync_shadow_from_layer()
        elif isinstance(tool, SketchTool) and "Sketch" in self._cached_widgets:
            self._sketch_options.sync_shadow_from_layer()
        elif isinstance(tool, TextTool) and "Text" in self._cached_widgets:
            self._text_options.sync_shadow_from_layer()
        elif isinstance(tool, BorderTool) and "Border" in self._cached_widgets:
            self._border_options.sync_shadow_from_layer()

    def _refresh_catalogs_if_dirty(self, cache_key: str, builder) -> None:
        """Only call refresh_*_catalog() on a builder if the underlying data changed."""
        from app.io.texture_library import get_catalog_version as tex_ver
        from app.io.asset_library import get_catalog_version as asset_ver

        if hasattr(builder, "refresh_texture_catalog"):
            cur = tex_ver()
            if self._seen_texture_version.get(cache_key) != cur:
                self._seen_texture_version[cache_key] = cur
                builder.refresh_texture_catalog()

        if hasattr(builder, "refresh_asset_catalog"):
            cur = asset_ver()
            if self._seen_asset_version.get(cache_key) != cur:
                self._seen_asset_version[cache_key] = cur
                builder.refresh_asset_catalog()

        # Palette refresh is cheap (no I/O, no thumbnails), keep unconditional
        if hasattr(builder, "refresh_palette_catalog"):
            builder.refresh_palette_catalog()

    def _on_tool_changed(self, tool_name: str):
        self._close_sidebar()

        # Hide current options widget
        if self._options_widget:
            self._options_widget.hide()
            self._options_widget = None

        tool = self._tool_manager.active_tool
        if tool is None:
            return

        cache_key = tool.name

        # Reuse cached widget or create new one
        if cache_key in self._cached_widgets:
            self._options_widget = self._cached_widgets[cache_key]
            self._options_widget.show()
            # Sync layer-level options with current active layer
            if isinstance(tool, BackgroundTool):
                self._bg_options.sync_from_layer()
            elif isinstance(tool, DrawTool):
                self._draw_options.sync_effects_from_layer()
            elif isinstance(tool, TextTool):
                self._text_options.sync_shadow_from_layer()
            elif isinstance(tool, BorderTool):
                self._border_options.sync_shadow_from_layer()
            elif isinstance(tool, AssetTool):
                self._asset_options.sync_shadow_from_layer()
            elif isinstance(tool, SketchTool):
                self._sketch_options.sync_shadow_from_layer()
            builder = self._builder_for_tool(tool)
            if builder is not None:
                self._refresh_catalogs_if_dirty(cache_key, builder)
        else:
            if isinstance(tool, BackgroundTool):
                self._options_widget = self._bg_options.create(tool)
            elif isinstance(tool, BorderTool):
                self._options_widget = self._border_options.create(tool)
            elif isinstance(tool, DrawTool):
                self._options_widget = self._draw_options.create(tool)
            elif isinstance(tool, FillTool):
                self._options_widget = self._fill_options.create(tool)
            elif isinstance(tool, AssetTool):
                self._options_widget = self._asset_options.create(tool)
            elif isinstance(tool, TextTool):
                self._options_widget = self._text_options.create(tool)
            elif isinstance(tool, HexsideTool):
                self._options_widget = self._hexside_options.create(tool)
            elif isinstance(tool, PathTool):
                self._options_widget = self._path_options.create(tool)
            elif isinstance(tool, FreeformPathTool):
                self._options_widget = self._freeform_path_options.create(tool)
            elif isinstance(tool, SketchTool):
                self._options_widget = self._sketch_options.create(tool)

            if self._options_widget:
                self._layout.insertWidget(0, self._options_widget)
                self._guard_scroll_widgets(self._options_widget)
                self._cached_widgets[cache_key] = self._options_widget
                # Record current catalog versions so next switch skips refresh
                from app.io.texture_library import get_catalog_version as tex_ver
                from app.io.asset_library import get_catalog_version as asset_ver
                self._seen_texture_version[cache_key] = tex_ver()
                self._seen_asset_version[cache_key] = asset_ver()

    def _guard_scroll_widgets(self, parent: QWidget):
        """Install no-scroll filter on all spinboxes, sliders, and combos."""
        for child in parent.findChildren(QWidget):
            if isinstance(child, SCROLL_GUARD_TYPES):
                child.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                child.installEventFilter(self._no_scroll_filter)
            if isinstance(child, QAbstractSpinBox):
                child.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

    def _close_sidebar(self):
        """Hide the sidebar and reset toggle button."""
        self._bg_options.close_sidebar()
        self._asset_options.close_sidebar()
        self._border_options.close_sidebar()
        self._draw_options.close_sidebar()
        self._fill_options.close_sidebar()
        self._hexside_options.close_sidebar()
        self._path_options.close_sidebar()
        self._freeform_path_options.close_sidebar()
        self._sketch_options.close_sidebar()

    def _builder_for_tool(self, tool):
        """Return the options-builder instance for the given tool, or None."""
        if isinstance(tool, BackgroundTool):    return self._bg_options
        if isinstance(tool, BorderTool):        return self._border_options
        if isinstance(tool, DrawTool):          return self._draw_options
        if isinstance(tool, FillTool):          return self._fill_options
        if isinstance(tool, AssetTool):         return self._asset_options
        if isinstance(tool, TextTool):          return self._text_options
        if isinstance(tool, HexsideTool):       return self._hexside_options
        if isinstance(tool, PathTool):          return self._path_options
        if isinstance(tool, FreeformPathTool):  return self._freeform_path_options
        if isinstance(tool, SketchTool):        return self._sketch_options
        return None

    def refresh_palette_catalog(self) -> None:
        """Refresh palette combos in all cached tool options panels.

        Called when the PaletteEditorDialog reports changes so that every
        tool-options panel that shows a palette selector is updated immediately,
        regardless of which tool is currently active.
        """
        all_builders = [
            self._fill_options, self._border_options, self._draw_options,
            self._hexside_options, self._path_options, self._freeform_path_options,
        ]
        for builder in all_builders:
            if hasattr(builder, "refresh_palette_catalog"):
                builder.refresh_palette_catalog()
