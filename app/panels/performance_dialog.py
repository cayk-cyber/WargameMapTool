"""Performance settings dialog with sidebar navigation."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class PerformanceDialog(QDialog):
    """Non-modal dialog for configuring performance-related settings."""

    render_quality_changed = Signal(bool)    # True = quality mode
    sharp_lines_changed = Signal(bool)       # True = sharp line rendering
    draw_quality_changed = Signal(bool)      # True = 4× mask resolution
    edge_bleed_quality_changed = Signal(bool)  # True = quality mode
    cache_delay_changed = Signal(int)        # delay in ms
    zoom_settle_changed = Signal(int)        # delay in ms
    gfx_visible_changed = Signal(bool)       # True = effects visible

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Performance Settings")
        self.setMinimumSize(580, 520)
        self.resize(620, 580)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        body = QHBoxLayout()
        body.setSpacing(8)
        root.addLayout(body, stretch=1)

        # -- Sidebar --
        self._list = QListWidget()
        self._list.setFixedWidth(140)
        self._list.setSpacing(2)
        self._list.addItem("Timers")
        self._list.addItem("Render Quality")
        self._list.addItem("Visible GFX")
        self._list.currentRowChanged.connect(self._on_page_changed)
        body.addWidget(self._list)

        # -- Pages --
        self._stack = QStackedWidget()
        body.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._scrollable(self._build_cache_delay_page()))
        self._stack.addWidget(self._scrollable(self._build_render_quality_page()))
        self._stack.addWidget(self._scrollable(self._build_visible_gfx_page()))

        # -- Buttons --
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self._list.setCurrentRow(0)

    # -----------------------------------------------------------------
    # Page builders
    # -----------------------------------------------------------------

    def _build_cache_delay_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        # -- Cache Rebuild Delay --
        cd_sc = self._shortcut_label("Ctrl+Shift+D")
        layout.addWidget(cd_sc)

        group = QGroupBox("Cache Rebuild Delay")
        gl = QVBoxLayout(group)

        desc = QLabel(
            "How long to wait after an edit before rebuilding\n"
            "the layer cache. Longer delays feel smoother\n"
            "during rapid editing on large maps."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; margin-bottom: 6px;")
        gl.addWidget(desc)

        self._cd_radios: dict[int, QRadioButton] = {}
        for ms, label in [
            (0, "None  (always rebuild immediately)"),
            (50, "50 ms"),
            (100, "100 ms"),
            (200, "200 ms  (Default)"),
            (500, "500 ms"),
        ]:
            rb = QRadioButton(label)
            rb.setProperty("ms", ms)
            rb.toggled.connect(self._on_cd_toggled)
            gl.addWidget(rb)
            self._cd_radios[ms] = rb

        layout.addWidget(group)

        # -- Zoom Settle Delay --
        zs_sc = self._shortcut_label("Ctrl+Shift+Z")
        layout.addWidget(zs_sc)

        zs_group = QGroupBox("Zoom Settle Delay")
        zl = QVBoxLayout(zs_group)

        zs_desc = QLabel(
            "How long to wait after zooming before rebuilding\n"
            "the layer cache. Longer delays avoid repeated\n"
            "cache rebuilds during rapid zoom in/out."
        )
        zs_desc.setWordWrap(True)
        zs_desc.setStyleSheet("color: #888; margin-bottom: 6px;")
        zl.addWidget(zs_desc)

        self._zs_radios: dict[int, QRadioButton] = {}
        for ms, label in [
            (50, "50 ms"),
            (100, "100 ms"),
            (200, "200 ms  (Default)"),
            (300, "300 ms"),
            (500, "500 ms"),
            (1000, "1000 ms"),
        ]:
            rb = QRadioButton(label)
            rb.setProperty("ms", ms)
            rb.toggled.connect(self._on_zs_toggled)
            zl.addWidget(rb)
            self._zs_radios[ms] = rb

        layout.addWidget(zs_group)
        layout.addStretch()
        return page

    def _build_render_quality_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        shortcut_label = self._shortcut_label("Ctrl+Shift+Q")
        layout.addWidget(shortcut_label)

        group = QGroupBox("Texture Rendering")
        gl = QVBoxLayout(group)

        self._rq_performance = QRadioButton("Performance  (World-Resolution Cache)")
        self._rq_quality = QRadioButton("Quality  (Screen-Resolution Cache, sharp at zoom)")

        desc_perf = QLabel("Faster, slightly less sharp when zoomed in.")
        desc_perf.setStyleSheet("color: #888; margin-left: 20px; margin-bottom: 6px;")
        desc_qual = QLabel("Sharp at every zoom level, rebuilds caches on zoom changes.")
        desc_qual.setStyleSheet("color: #888; margin-left: 20px;")

        gl.addWidget(self._rq_performance)
        gl.addWidget(desc_perf)
        gl.addWidget(self._rq_quality)
        gl.addWidget(desc_qual)

        self._rq_performance.toggled.connect(self._on_rq_toggled)

        layout.addWidget(group)

        # -- Sharp Lines --
        sc_row = QHBoxLayout()
        sc_row.setSpacing(6)
        sc_row.addWidget(self._shortcut_label("Ctrl+Shift+L"))
        sc_row.addStretch()
        layout.addLayout(sc_row)

        sl_group = QGroupBox("Line Rendering  (Hexside, Path, Border)")
        sl_layout = QVBoxLayout(sl_group)

        self._sl_cb = QCheckBox("Sharp Lines  (Screen-Resolution Cache)")
        self._sl_cb.toggled.connect(self._on_sl_toggled)
        sl_layout.addWidget(self._sl_cb)

        sl_desc = QLabel(
            "When enabled, vector line layers (Hexside, Path,\n"
            "Freeform Path, Border) use a screen-resolution cache\n"
            "that stays sharp at every zoom level.\n\n"
            "Costs more memory and rebuilds on zoom changes.\n"
            "Disable for better performance on large maps."
        )
        sl_desc.setWordWrap(True)
        sl_desc.setStyleSheet("color: #888; margin-top: 6px;")
        sl_layout.addWidget(sl_desc)

        layout.addWidget(sl_group)

        # -- Draw Mask Quality --
        dm_sc = self._shortcut_label("Ctrl+Shift+W")
        layout.addWidget(dm_sc)

        dm_group = QGroupBox("Draw Mask  (Draw Layer)")
        dm_layout = QVBoxLayout(dm_group)

        self._dm_perf = QRadioButton("Performance  (1\u00d7 World-Resolution Mask)")
        self._dm_quality = QRadioButton("Quality  (2\u00d7 World-Resolution Mask)")

        dm_desc_perf = QLabel("Faster, uses less memory. Brush strokes may\nlook blocky when zoomed in.")
        dm_desc_perf.setStyleSheet("color: #888; margin-left: 20px; margin-bottom: 6px;")
        dm_desc_qual = QLabel("Sharp brush strokes at all zoom levels.\nUses ~4\u00d7 more memory per channel mask.")
        dm_desc_qual.setStyleSheet("color: #888; margin-left: 20px;")

        dm_layout.addWidget(self._dm_perf)
        dm_layout.addWidget(dm_desc_perf)
        dm_layout.addWidget(self._dm_quality)
        dm_layout.addWidget(dm_desc_qual)

        dm_note = QLabel(
            "Changing this rescales existing masks. New strokes\n"
            "painted in Quality mode will be sharp; previously\n"
            "painted strokes keep their original detail level."
        )
        dm_note.setWordWrap(True)
        dm_note.setStyleSheet("color: #888; font-style: italic; margin-top: 6px;")
        dm_layout.addWidget(dm_note)

        self._dm_perf.toggled.connect(self._on_dm_toggled)

        layout.addWidget(dm_group)

        # -- Edge Bleeding Quality --
        eb_sc = self._shortcut_label("Ctrl+Shift+B")
        layout.addWidget(eb_sc)

        eb_group = QGroupBox("Edge Bleeding  (Draw Layer)")
        eb_layout = QVBoxLayout(eb_group)

        self._eb_perf = QRadioButton("Performance  (Downsampled Distance Field)")
        self._eb_quality = QRadioButton("Quality  (Full-Resolution Distance Field)")

        eb_desc_perf = QLabel("Much faster, slightly softer transition edges.")
        eb_desc_perf.setStyleSheet("color: #888; margin-left: 20px; margin-bottom: 6px;")
        eb_desc_qual = QLabel("Sharp transitions, slower after each stroke.")
        eb_desc_qual.setStyleSheet("color: #888; margin-left: 20px;")

        eb_layout.addWidget(self._eb_perf)
        eb_layout.addWidget(eb_desc_perf)
        eb_layout.addWidget(self._eb_quality)
        eb_layout.addWidget(eb_desc_qual)

        eb_note = QLabel("Exports always use Quality mode regardless of this setting.")
        eb_note.setWordWrap(True)
        eb_note.setStyleSheet("color: #888; font-style: italic; margin-top: 6px;")
        eb_layout.addWidget(eb_note)

        self._eb_perf.toggled.connect(self._on_eb_toggled)

        layout.addWidget(eb_group)
        layout.addStretch()
        return page

    def _build_visible_gfx_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        shortcut_label = self._shortcut_label("Ctrl+E")
        layout.addWidget(shortcut_label)

        group = QGroupBox("Visible GFX")
        gl = QVBoxLayout(group)

        self._gfx_cb = QCheckBox("Show Shadow, Bevel, Structure && Edge Bleeding effects")
        self._gfx_cb.toggled.connect(self._on_gfx_toggled)
        gl.addWidget(self._gfx_cb)

        desc = QLabel(
            "When unchecked, Shadow, Bevel & Emboss, Structure, and\n"
            "Edge Bleeding (Draw Layer) effects are hidden on all layers.\n"
            "Outline (Draw Layer) is not affected. Useful to reduce lag\n"
            "when many layers have expensive effects enabled.\n\n"
            "Exports always include all effects regardless of this setting."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; margin-top: 6px;")
        gl.addWidget(desc)

        layout.addWidget(group)
        layout.addStretch()
        return page

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        """Wrap a page widget in a scroll area."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setWidget(page)
        return sa

    @staticmethod
    def _shortcut_label(shortcut: str) -> QLabel:
        lbl = QLabel(f"Shortcut:  {shortcut}")
        font = QFont()
        font.setBold(True)
        lbl.setFont(font)
        lbl.setStyleSheet(
            "background: #3a3a3a; color: #ccc; padding: 4px 8px;"
            "border-radius: 4px; margin-bottom: 4px;"
        )
        return lbl

    # -----------------------------------------------------------------
    # Public: set state from outside (main_window applies persisted values)
    # -----------------------------------------------------------------

    def set_cache_delay(self, ms: int) -> None:
        rb = self._cd_radios.get(ms)
        if rb:
            rb.blockSignals(True)
            rb.setChecked(True)
            rb.blockSignals(False)

    def set_render_quality(self, quality: bool) -> None:
        self._rq_quality.blockSignals(True)
        self._rq_performance.blockSignals(True)
        if quality:
            self._rq_quality.setChecked(True)
        else:
            self._rq_performance.setChecked(True)
        self._rq_quality.blockSignals(False)
        self._rq_performance.blockSignals(False)

    def set_zoom_settle(self, ms: int) -> None:
        rb = self._zs_radios.get(ms)
        if rb:
            rb.blockSignals(True)
            rb.setChecked(True)
            rb.blockSignals(False)

    def set_gfx_visible(self, visible: bool) -> None:
        self._gfx_cb.blockSignals(True)
        self._gfx_cb.setChecked(visible)
        self._gfx_cb.blockSignals(False)

    def set_sharp_lines(self, sharp: bool) -> None:
        self._sl_cb.blockSignals(True)
        self._sl_cb.setChecked(sharp)
        self._sl_cb.blockSignals(False)

    def set_draw_quality(self, quality: bool) -> None:
        self._dm_quality.blockSignals(True)
        self._dm_perf.blockSignals(True)
        if quality:
            self._dm_quality.setChecked(True)
        else:
            self._dm_perf.setChecked(True)
        self._dm_quality.blockSignals(False)
        self._dm_perf.blockSignals(False)

    def set_edge_bleed_quality(self, quality: bool) -> None:
        self._eb_quality.blockSignals(True)
        self._eb_perf.blockSignals(True)
        if quality:
            self._eb_quality.setChecked(True)
        else:
            self._eb_perf.setChecked(True)
        self._eb_quality.blockSignals(False)
        self._eb_perf.blockSignals(False)

    # -----------------------------------------------------------------
    # Internal slots
    # -----------------------------------------------------------------

    def _on_page_changed(self, row: int) -> None:
        self._stack.setCurrentIndex(row)

    def _on_cd_toggled(self, checked: bool) -> None:
        if not checked:
            return
        rb = self.sender()
        ms = rb.property("ms")
        self.cache_delay_changed.emit(ms)

    def _on_zs_toggled(self, checked: bool) -> None:
        if not checked:
            return
        rb = self.sender()
        ms = rb.property("ms")
        self.zoom_settle_changed.emit(ms)

    def _on_rq_toggled(self, perf_checked: bool) -> None:
        # perf_checked = True means Performance radio is checked → quality=False
        self.render_quality_changed.emit(not perf_checked)

    def _on_sl_toggled(self, checked: bool) -> None:
        self.sharp_lines_changed.emit(checked)

    def _on_dm_toggled(self, perf_checked: bool) -> None:
        self.draw_quality_changed.emit(not perf_checked)

    def _on_eb_toggled(self, perf_checked: bool) -> None:
        self.edge_bleed_quality_changed.emit(not perf_checked)

    def _on_gfx_toggled(self, checked: bool) -> None:
        self.gfx_visible_changed.emit(checked)
