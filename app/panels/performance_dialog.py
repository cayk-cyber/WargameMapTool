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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class PerformanceDialog(QDialog):
    """Non-modal dialog for configuring performance-related settings."""

    render_quality_changed = Signal(bool)    # True = quality mode
    cache_delay_changed = Signal(int)        # delay in ms
    zoom_settle_changed = Signal(int)        # delay in ms
    gfx_visible_changed = Signal(bool)       # True = effects visible

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Performance Settings")
        self.setMinimumSize(580, 420)
        self.resize(620, 480)

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

        self._stack.addWidget(self._build_cache_delay_page())
        self._stack.addWidget(self._build_render_quality_page())
        self._stack.addWidget(self._build_visible_gfx_page())

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

        # -- Shortcuts --
        sc_row = QHBoxLayout()
        sc_row.setSpacing(6)
        sc_row.addWidget(self._shortcut_label("Ctrl+Shift+D  (Cache)"))
        sc_row.addWidget(self._shortcut_label("Ctrl+Shift+Z  (Zoom)"))
        sc_row.addStretch()
        layout.addLayout(sc_row)

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

        group = QGroupBox("Render Quality")
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

        self._gfx_cb = QCheckBox("Show Shadow, Bevel && Structure effects")
        self._gfx_cb.toggled.connect(self._on_gfx_toggled)
        gl.addWidget(self._gfx_cb)

        desc = QLabel(
            "When unchecked, Shadow, Bevel & Emboss, and Structure\n"
            "effects are hidden on all layers. Outline (Draw Layer)\n"
            "is not affected. Useful to reduce lag when many layers\n"
            "have expensive effects enabled.\n\n"
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

    def _on_gfx_toggled(self, checked: bool) -> None:
        self.gfx_visible_changed.emit(checked)
