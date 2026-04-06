"""Sidebar dock widgets for expanded asset/texture/preset browsing."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.io.asset_library import LibraryAsset
from app.io.brush_library import LibraryBrush
from app.io.border_preset_manager import (
    BorderPreset,
    list_border_presets,
    load_border_preset,
)
from app.io.hexside_preset_manager import (
    HexsidePreset,
    list_hexside_presets,
    load_hexside_preset,
)
from app.io.path_preset_manager import (
    PathPreset,
    list_path_presets,
    load_path_preset,
)
from app.io.text_preset_manager import (
    TextPreset,
    list_text_presets,
    load_text_preset,
)
from app.io.texture_cache import get_texture_image
from app.io.texture_library import LibraryTexture

SIDEBAR_THUMB = 80
SIDEBAR_COLS = 3
_BRUSH_DARK_BG = QColor("#2b2b2b")


class BrushBrowserSidebar(QDockWidget):
    """Expanded brush browser sidebar for selecting brushes from the library."""

    brush_clicked = Signal(object)  # emits LibraryBrush
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__("Brush Browser", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(320)

        self._thumb_cache: dict[str, QPixmap] = {}
        self._buttons: dict[str, QToolButton] = {}
        self._selected_id: str | None = None

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(6)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._grid_container)
        layout.addWidget(self._scroll)

        self.setWidget(container)

    def set_brushes(
        self, brushes: list[LibraryBrush], selected_id: str | None = None
    ):
        """Update the displayed brushes."""
        self._selected_id = selected_id

        for btn in self._buttons.values():
            self._grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        for i, brush in enumerate(brushes):
            btn = self._make_thumb(brush)
            row = i // SIDEBAR_COLS
            col = i % SIDEBAR_COLS
            self._grid_layout.addWidget(btn, row, col)
            self._buttons[brush.id] = btn

        self._update_selection()

    def set_selected(self, brush_id: str | None):
        """Update selection highlight."""
        self._selected_id = brush_id
        self._update_selection()

    def invalidate_cache(self):
        """Clear thumbnail cache (call after catalog changes)."""
        self._thumb_cache.clear()

    def _make_thumb(self, brush: LibraryBrush) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(SIDEBAR_THUMB + 16, SIDEBAR_THUMB + 28)
        btn.setToolTip(f"{brush.display_name}\n{brush.category}")

        pixmap = self._get_thumb(brush)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(SIDEBAR_THUMB, SIDEBAR_THUMB))

        btn.setText(brush.display_name[:12])
        btn.setStyleSheet("QToolButton { padding: 2px; }")
        btn.clicked.connect(
            lambda checked=False, b=brush: self._on_clicked(b)
        )
        return btn

    def _get_thumb(self, brush: LibraryBrush) -> QPixmap | None:
        if brush.id in self._thumb_cache:
            return self._thumb_cache[brush.id]

        if not brush.exists():
            return None

        src = QPixmap(brush.file_path())
        if src.isNull():
            return None

        src = src.scaled(
            SIDEBAR_THUMB, SIDEBAR_THUMB,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        result = QPixmap(SIDEBAR_THUMB, SIDEBAR_THUMB)
        result.fill(_BRUSH_DARK_BG)
        p = QPainter(result)
        x = (SIDEBAR_THUMB - src.width()) // 2
        y = (SIDEBAR_THUMB - src.height()) // 2
        p.drawPixmap(x, y, src)
        p.end()

        self._thumb_cache[brush.id] = result
        return result

    def _on_clicked(self, brush: LibraryBrush):
        self._selected_id = brush.id
        self._update_selection()
        self.brush_clicked.emit(brush)

    def _update_selection(self):
        for brush_id, btn in self._buttons.items():
            if self._selected_id and brush_id == self._selected_id:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; "
                    "border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 2px; }")

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class AssetBrowserSidebar(QDockWidget):
    """Expanded asset browser sidebar for better asset overview."""

    asset_clicked = Signal(object)  # emits LibraryAsset
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__("Asset Browser", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(350)

        self._thumb_cache: dict[str, QPixmap] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._selected_id: str | None = None
        self._multi_selected_ids: set[str] = set()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(6)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._grid_container)
        layout.addWidget(self._scroll)

        self.setWidget(container)

    def invalidate_cache(self) -> None:
        """Clear the thumbnail cache so stale images are not shown after catalog changes."""
        self._thumb_cache.clear()

    def set_assets(
        self, assets: list[LibraryAsset], selected_id: str | None = None
    ):
        """Update the displayed assets."""
        self._selected_id = selected_id

        for btn in self._buttons.values():
            self._grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        for i, asset in enumerate(assets):
            btn = self._make_thumb(asset)
            row = i // SIDEBAR_COLS
            col = i % SIDEBAR_COLS
            self._grid_layout.addWidget(btn, row, col)
            self._buttons[asset.id] = btn

        self._update_selection()

    def set_selected(self, asset_id: str | None):
        """Update selection highlight (single-select mode)."""
        self._selected_id = asset_id
        self._multi_selected_ids.clear()
        self._update_selection()

    def set_multi_selected(self, ids: set[str]):
        """Update selection highlights for multi-select mode (randomize)."""
        self._selected_id = None
        self._multi_selected_ids = set(ids)
        self._update_selection()

    def _make_thumb(self, asset: LibraryAsset) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(SIDEBAR_THUMB + 16, SIDEBAR_THUMB + 28)
        game_info = f"  ({asset.game})" if asset.game else ""
        btn.setToolTip(f"{asset.display_name}{game_info}\n{asset.category}")

        pixmap = self._get_thumb(asset)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(SIDEBAR_THUMB, SIDEBAR_THUMB))

        btn.setText(asset.display_name[:12])
        btn.setStyleSheet(
            "QToolButton { padding: 2px; }"
        )
        btn.clicked.connect(
            lambda checked=False, a=asset: self._on_clicked(a)
        )
        return btn

    def _get_thumb(self, asset: LibraryAsset) -> QPixmap | None:
        if asset.id in self._thumb_cache:
            return self._thumb_cache[asset.id]

        if not asset.exists():
            return None

        image = QImage(asset.file_path())
        if image.isNull():
            return None

        scaled = image.scaled(
            SIDEBAR_THUMB,
            SIDEBAR_THUMB,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        self._thumb_cache[asset.id] = pixmap
        return pixmap

    def _on_clicked(self, asset: LibraryAsset):
        self._selected_id = asset.id
        self._update_selection()
        self.asset_clicked.emit(asset)

    def _update_selection(self):
        for asset_id, btn in self._buttons.items():
            if self._multi_selected_ids and asset_id in self._multi_selected_ids:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; "
                    "border: 2px solid #00cc44; }"
                )
            elif self._selected_id and asset_id == self._selected_id:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; "
                    "border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; }"
                )

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class TextureBrowserSidebar(QDockWidget):
    """Expanded texture browser sidebar for better texture overview."""

    texture_clicked = Signal(object)  # emits LibraryTexture
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__("Texture Browser", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(350)

        self._thumb_cache: dict[str, QPixmap] = {}
        self._buttons: dict[str, QToolButton] = {}
        self._selected_id: str | None = None

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(6)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._grid_container)
        layout.addWidget(self._scroll)

        self.setWidget(container)

    def invalidate_cache(self) -> None:
        """Clear the thumbnail cache so stale images are not shown after catalog changes."""
        self._thumb_cache.clear()

    def set_textures(
        self, textures: list[LibraryTexture], selected_id: str | None = None
    ):
        """Update the displayed textures."""
        self._selected_id = selected_id

        for btn in self._buttons.values():
            self._grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        for i, tex in enumerate(textures):
            btn = self._make_thumb(tex)
            row = i // SIDEBAR_COLS
            col = i % SIDEBAR_COLS
            self._grid_layout.addWidget(btn, row, col)
            self._buttons[tex.id] = btn

        self._update_selection()

    def set_selected(self, tex_id: str | None):
        """Update selection highlight."""
        self._selected_id = tex_id
        self._update_selection()

    def _make_thumb(self, tex: LibraryTexture) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(SIDEBAR_THUMB + 16, SIDEBAR_THUMB + 28)
        game_info = f"  ({tex.game})" if tex.game else ""
        btn.setToolTip(f"{tex.display_name}{game_info}\n{tex.category}")

        pixmap = self._get_thumb(tex)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(SIDEBAR_THUMB, SIDEBAR_THUMB))

        btn.setText(tex.display_name[:12])
        btn.setStyleSheet("QToolButton { padding: 2px; }")
        btn.clicked.connect(
            lambda checked=False, t=tex: self._on_clicked(t)
        )
        return btn

    def _get_thumb(self, tex: LibraryTexture) -> QPixmap | None:
        if tex.id in self._thumb_cache:
            return self._thumb_cache[tex.id]

        if not tex.exists():
            return None

        image = QImage(tex.file_path())
        if image.isNull():
            return None

        scaled = image.scaled(
            SIDEBAR_THUMB,
            SIDEBAR_THUMB,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        self._thumb_cache[tex.id] = pixmap
        return pixmap

    def _on_clicked(self, tex: LibraryTexture):
        self._selected_id = tex.id
        self._update_selection()
        self.texture_clicked.emit(tex)

    def _update_selection(self):
        for tex_id, btn in self._buttons.items():
            if self._selected_id and tex_id == self._selected_id:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; "
                    "border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 2px; }")

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Hexside preset preview rendering (shared by sidebar + tool options)
# ---------------------------------------------------------------------------

def render_hexside_preview(preset: HexsidePreset, w: int, h: int) -> QPixmap:
    """Render a preview pixmap for a hexside preset showing its line style."""
    pm = QPixmap(w, h)
    pm.fill(QColor("#d0d0d0"))

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = 16
    y_center = h / 2.0

    # Draw outline first (if enabled)
    if preset.outline:
        total_w = preset.width + preset.outline_width * 2
        ol_pen = QPen(QColor(preset.outline_color), total_w)
        ol_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(ol_pen)
        painter.drawLine(
            QPointF(margin, y_center), QPointF(w - margin, y_center),
        )

    # Draw main line
    if preset.paint_mode == "texture" and preset.texture_id:
        pen = QPen(QColor(preset.color), preset.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(margin, y_center), QPointF(w - margin, y_center),
        )
        painter.setPen(QColor("#333333"))
        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, 0, w, h),
            Qt.AlignmentFlag.AlignCenter,
            f"[Texture: {preset.texture_id[:8]}]",
        )
    else:
        pen = QPen(QColor(preset.color), preset.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(margin, y_center), QPointF(w - margin, y_center),
        )

    painter.end()
    return pm


# ---------------------------------------------------------------------------
# Hexside preset sidebar
# ---------------------------------------------------------------------------

_PRESET_CARD_HEIGHT = 60
_PRESET_PREVIEW_HEIGHT = 30


class HexsidePresetSidebar(QDockWidget):
    """Expanded sidebar showing all hexside presets with rendered previews."""

    preset_clicked = Signal(str)  # emits preset name
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__("Hexside Presets", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(310)

        self._buttons: dict[str, QPushButton] = {}
        self._selected_name: str | None = None

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setSpacing(4)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._list_container)
        layout.addWidget(self._scroll)

        self.setWidget(container)

    def set_presets(self, names: list[str], selected: str | None = None) -> None:
        """Rebuild the preset list from the given names."""
        self._selected_name = selected

        for btn in self._buttons.values():
            self._list_layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        # Remove old stretch
        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for name in names:
            btn = self._make_card(name)
            self._list_layout.addWidget(btn)
            self._buttons[name] = btn

        self._list_layout.addStretch()
        self._update_selection()

    def set_selected(self, name: str | None) -> None:
        """Update selection highlight."""
        self._selected_name = name
        self._update_selection()

    def _make_card(self, name: str) -> QPushButton:
        """Create a preset card button with name + rendered preview."""
        btn = QPushButton()
        btn.setFixedHeight(_PRESET_CARD_HEIGHT)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # Build card content as a widget inside the button
        card = QWidget(btn)
        card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 4, 6, 4)
        card_layout.setSpacing(2)

        # Name label
        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; background: transparent;")
        name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        card_layout.addWidget(name_label)

        # Rendered preview
        preview_label = QLabel()
        preview_label.setFixedHeight(_PRESET_PREVIEW_HEIGHT)
        preview_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        try:
            preset = load_hexside_preset(name)
            pm = render_hexside_preview(preset, 240, _PRESET_PREVIEW_HEIGHT)
            preview_label.setPixmap(pm)
        except Exception:
            preview_label.setText("(error)")
        preview_label.setStyleSheet("background: transparent;")
        card_layout.addWidget(preview_label)

        btn.setStyleSheet("QPushButton { text-align: left; padding: 0px; }")
        btn.clicked.connect(lambda checked=False, n=name: self._on_clicked(n))

        # Resize card widget to match button size
        btn.resizeEvent = lambda e, c=card: c.setGeometry(
            0, 0, e.size().width(), e.size().height()
        )

        return btn

    def _on_clicked(self, name: str) -> None:
        self._selected_name = name
        self._update_selection()
        self.preset_clicked.emit(name)

    def _update_selection(self) -> None:
        for name, btn in self._buttons.items():
            if self._selected_name and name == self._selected_name:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 0px; "
                    "border: 2px solid #00aaff; background: #2a3a4a; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 0px; }"
                )

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Path preset preview rendering (shared by sidebar + tool options)
# ---------------------------------------------------------------------------

_PREVIEW_CAP_MAP = {
    "flat": Qt.PenCapStyle.FlatCap,
    "round": Qt.PenCapStyle.RoundCap,
    "square": Qt.PenCapStyle.SquareCap,
}


def _make_preview_pen(
    color: str, width: float, line_type: str,
    dash_length: float, gap_length: float,
    texture_id: str = "", texture_zoom: float = 1.0,
    texture_rotation: float = 0.0,
    dash_cap: str = "round",
) -> QPen:
    """Create a QPen with the specified path line type for preview rendering."""
    if texture_id:
        img = get_texture_image(texture_id)
        if img is not None:
            brush = QBrush(QPixmap.fromImage(img))
            brush_xf = QTransform()
            if texture_rotation != 0.0:
                brush_xf.rotate(texture_rotation)
            if texture_zoom != 1.0:
                brush_xf.scale(texture_zoom, texture_zoom)
            brush.setTransform(brush_xf)
            pen = QPen(brush, width)
        else:
            pen = QPen(QColor(color), width)
    else:
        pen = QPen(QColor(color), width)
    cap = _PREVIEW_CAP_MAP.get(dash_cap, Qt.PenCapStyle.RoundCap)
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    if line_type == "dashed":
        pw = max(width, 0.5)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([dash_length / pw, gap_length / pw])
    elif line_type == "dotted":
        pw = max(width, 0.5)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([0.1, gap_length / pw])

    return pen


def render_path_preview(preset: "PathPreset", w: int, h: int) -> QPixmap:
    """Render a preview pixmap for a path preset showing its line style."""
    pm = QPixmap(w, h)
    pm.fill(QColor("#d0d0d0"))

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = 16
    y_center = h / 2.0

    # Draw background path first (if enabled)
    if preset.bg_enabled:
        bg_pen = _make_preview_pen(
            preset.bg_color, preset.bg_width, preset.bg_line_type,
            preset.bg_dash_length, preset.bg_gap_length,
            dash_cap=preset.bg_dash_cap,
        )
        painter.setPen(bg_pen)
        painter.drawLine(
            QPointF(margin, y_center), QPointF(w - margin, y_center),
        )

    # Draw foreground path
    fg_pen = _make_preview_pen(
        preset.color, preset.width, preset.line_type,
        preset.dash_length, preset.gap_length,
        preset.texture_id, preset.texture_zoom, preset.texture_rotation,
        preset.dash_cap,
    )
    painter.setPen(fg_pen)
    painter.drawLine(
        QPointF(margin, y_center), QPointF(w - margin, y_center),
    )

    painter.end()
    return pm


# ---------------------------------------------------------------------------
# Path preset sidebar
# ---------------------------------------------------------------------------

class PathPresetSidebar(QDockWidget):
    """Expanded sidebar showing all path presets with rendered previews."""

    preset_clicked = Signal(str)  # emits preset name
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__("Path Presets", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(310)

        self._buttons: dict[str, QPushButton] = {}
        self._selected_name: str | None = None

        container = QWidget()
        sb_layout = QVBoxLayout(container)
        sb_layout.setContentsMargins(4, 4, 4, 4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setSpacing(4)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._list_container)
        sb_layout.addWidget(self._scroll)

        self.setWidget(container)

    def set_presets(self, names: list[str], selected: str | None = None) -> None:
        """Rebuild the preset list from the given names."""
        self._selected_name = selected

        for btn in self._buttons.values():
            self._list_layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for name in names:
            btn = self._make_card(name)
            self._list_layout.addWidget(btn)
            self._buttons[name] = btn

        self._list_layout.addStretch()
        self._update_selection()

    def set_selected(self, name: str | None) -> None:
        """Update selection highlight."""
        self._selected_name = name
        self._update_selection()

    def _make_card(self, name: str) -> QPushButton:
        """Create a preset card button with name + rendered preview."""
        btn = QPushButton()
        btn.setFixedHeight(_PRESET_CARD_HEIGHT)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        card = QWidget(btn)
        card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 4, 6, 4)
        card_layout.setSpacing(2)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; background: transparent;")
        name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        card_layout.addWidget(name_label)

        preview_label = QLabel()
        preview_label.setFixedHeight(_PRESET_PREVIEW_HEIGHT)
        preview_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        try:
            preset = load_path_preset(name)
            pm = render_path_preview(preset, 240, _PRESET_PREVIEW_HEIGHT)
            preview_label.setPixmap(pm)
        except Exception:
            preview_label.setText("(error)")
        preview_label.setStyleSheet("background: transparent;")
        card_layout.addWidget(preview_label)

        btn.setStyleSheet("QPushButton { text-align: left; padding: 0px; }")
        btn.clicked.connect(lambda checked=False, n=name: self._on_clicked(n))

        btn.resizeEvent = lambda e, c=card: c.setGeometry(
            0, 0, e.size().width(), e.size().height()
        )

        return btn

    def _on_clicked(self, name: str) -> None:
        self._selected_name = name
        self._update_selection()
        self.preset_clicked.emit(name)

    def _update_selection(self) -> None:
        for pname, btn in self._buttons.items():
            if self._selected_name and pname == self._selected_name:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 0px; "
                    "border: 2px solid #00aaff; background: #2a3a4a; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 0px; }"
                )

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Border preset preview rendering (shared by sidebar + tool options)
# ---------------------------------------------------------------------------

def render_border_preview(preset: BorderPreset, w: int, h: int) -> QPixmap:
    """Render a preview pixmap for a border preset showing its line style."""
    from app.layers.border_layer import BorderLayer, _CAP_MAP

    pm = QPixmap(w, h)
    pm.fill(QColor("#d0d0d0"))

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = 16
    y_center = h / 2.0

    # Draw outline first (if enabled) - per-element for non-solid
    if preset.outline:
        if preset.line_type == "dotted":
            main_pw = max(preset.element_size, 0.5)
            total_pw = main_pw + preset.outline_width * 2
            ol_pen = QPen(QColor(preset.outline_color), total_pw)
            ol_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            ol_pen.setStyle(Qt.PenStyle.CustomDashLine)
            ol_pen.setDashPattern([0.1, preset.gap_size / total_pw])
        elif preset.line_type == "dashed":
            total_w = preset.width + preset.outline_width * 2
            ol_pen = QPen(QColor(preset.outline_color), total_w)
            cap = _CAP_MAP.get(preset.dash_cap, Qt.PenCapStyle.RoundCap)
            ol_pen.setCapStyle(cap)
            ol_pen.setStyle(Qt.PenStyle.CustomDashLine)
            pw = max(total_w, 0.5)
            ol_pen.setDashPattern([preset.element_size / pw, preset.gap_size / pw])
        else:
            total_w = preset.width + preset.outline_width * 2
            ol_pen = QPen(QColor(preset.outline_color), total_w)
            ol_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(ol_pen)
        painter.drawLine(
            QPointF(margin, y_center), QPointF(w - margin, y_center),
        )

    # Draw main line with line_type
    pen = BorderLayer._make_pen(
        preset.color, preset.width, preset.line_type,
        preset.element_size, preset.gap_size, preset.dash_cap,
    )
    painter.setPen(pen)
    painter.drawLine(
        QPointF(margin, y_center), QPointF(w - margin, y_center),
    )

    painter.end()
    return pm


# ---------------------------------------------------------------------------
# Border preset sidebar
# ---------------------------------------------------------------------------

class BorderPresetSidebar(QDockWidget):
    """Expanded sidebar showing all border presets with rendered previews."""

    preset_clicked = Signal(str)  # emits preset name
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__("Border Presets", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(310)

        self._buttons: dict[str, QPushButton] = {}
        self._selected_name: str | None = None

        container = QWidget()
        sb_layout = QVBoxLayout(container)
        sb_layout.setContentsMargins(4, 4, 4, 4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setSpacing(4)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._list_container)
        sb_layout.addWidget(self._scroll)

        self.setWidget(container)

    def set_presets(self, names: list[str], selected: str | None = None) -> None:
        """Rebuild the preset list from the given names."""
        self._selected_name = selected

        for btn in self._buttons.values():
            self._list_layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for name in names:
            btn = self._make_card(name)
            self._list_layout.addWidget(btn)
            self._buttons[name] = btn

        self._list_layout.addStretch()
        self._update_selection()

    def set_selected(self, name: str | None) -> None:
        """Update selection highlight."""
        self._selected_name = name
        self._update_selection()

    def _make_card(self, name: str) -> QPushButton:
        """Create a preset card button with name + rendered preview."""
        btn = QPushButton()
        btn.setFixedHeight(_PRESET_CARD_HEIGHT)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        card = QWidget(btn)
        card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 4, 6, 4)
        card_layout.setSpacing(2)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; background: transparent;")
        name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        card_layout.addWidget(name_label)

        preview_label = QLabel()
        preview_label.setFixedHeight(_PRESET_PREVIEW_HEIGHT)
        preview_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        try:
            preset = load_border_preset(name)
            pm = render_border_preview(preset, 240, _PRESET_PREVIEW_HEIGHT)
            preview_label.setPixmap(pm)
        except Exception:
            preview_label.setText("(error)")
        preview_label.setStyleSheet("background: transparent;")
        card_layout.addWidget(preview_label)

        btn.setStyleSheet("QPushButton { text-align: left; padding: 0px; }")
        btn.clicked.connect(lambda checked=False, n=name: self._on_clicked(n))

        btn.resizeEvent = lambda e, c=card: c.setGeometry(
            0, 0, e.size().width(), e.size().height()
        )

        return btn

    def _on_clicked(self, name: str) -> None:
        self._selected_name = name
        self._update_selection()
        self.preset_clicked.emit(name)

    def _update_selection(self) -> None:
        for pname, btn in self._buttons.items():
            if self._selected_name and pname == self._selected_name:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 0px; "
                    "border: 2px solid #00aaff; background: #2a3a4a; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 0px; }"
                )

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Text preset preview rendering (shared by sidebar + tool options)
# ---------------------------------------------------------------------------

def render_text_preset_preview_pm(preset, w: int, h: int):
    """Render a preview pixmap for a text preset showing its font and style."""
    from PySide6.QtGui import QFont, QFontMetrics, QPainterPath, QPen

    pm = QPixmap(w, h)
    pm.fill(QColor("#d0d0d0"))

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    font = QFont(preset.font_family)
    font.setBold(preset.bold)
    font.setItalic(preset.italic)

    fm = QFontMetrics(font)
    max_h = h - 6
    size = preset.font_size
    if fm.height() > max_h and fm.height() > 0:
        size = preset.font_size * max_h / fm.height()
    font.setPointSizeF(max(size, 6.0))
    fm = QFontMetrics(font)

    sample = preset.name or "Text"
    x = max(4.0, (w - fm.horizontalAdvance(sample)) / 2.0)
    y = (h + fm.ascent() - fm.descent()) / 2.0

    painter.setOpacity(preset.opacity)
    if preset.outline:
        path = QPainterPath()
        path.addText(x, y, font, sample)
        pen = QPen(QColor(preset.outline_color), preset.outline_width * 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QColor(preset.color))
        painter.drawPath(path)
    else:
        path = QPainterPath()
        path.addText(x, y, font, sample)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(preset.color))
        painter.drawPath(path)

    painter.end()
    return pm


# ---------------------------------------------------------------------------
# Text preset sidebar
# ---------------------------------------------------------------------------

class TextPresetSidebar(QDockWidget):
    """Expanded sidebar showing all text presets with rendered previews."""

    preset_clicked = Signal(str)  # emits preset name
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__("Text Presets", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(310)

        self._buttons: dict[str, QPushButton] = {}
        self._selected_name: str | None = None

        container = QWidget()
        sb_layout = QVBoxLayout(container)
        sb_layout.setContentsMargins(4, 4, 4, 4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setSpacing(4)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._list_container)
        sb_layout.addWidget(self._scroll)

        self.setWidget(container)

    def set_presets(self, names: list[str], selected: str | None = None) -> None:
        """Rebuild the preset list from the given names."""
        self._selected_name = selected

        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons.clear()

        for name in names:
            btn = self._make_card(name)
            self._list_layout.addWidget(btn)
            self._buttons[name] = btn

        self._list_layout.addStretch()
        self._update_selection()

    def set_selected(self, name: str | None) -> None:
        """Update selection highlight."""
        self._selected_name = name
        self._update_selection()

    def _make_card(self, name: str) -> QPushButton:
        """Create a preset card button with name + rendered text preview."""
        btn = QPushButton()
        btn.setFixedHeight(_PRESET_CARD_HEIGHT)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        card = QWidget(btn)
        card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 4, 6, 4)
        card_layout.setSpacing(2)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; background: transparent;")
        name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        card_layout.addWidget(name_label)

        preview_label = QLabel()
        preview_label.setFixedHeight(_PRESET_PREVIEW_HEIGHT)
        preview_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        try:
            preset = load_text_preset(name)
            pm = render_text_preset_preview_pm(preset, 240, _PRESET_PREVIEW_HEIGHT)
            preview_label.setPixmap(pm)
        except Exception:
            preview_label.setText("(error)")
        preview_label.setStyleSheet("background: transparent;")
        card_layout.addWidget(preview_label)

        btn.setStyleSheet("QPushButton { text-align: left; padding: 0px; }")
        btn.clicked.connect(lambda checked=False, n=name: self._on_clicked(n))

        btn.resizeEvent = lambda e, c=card: c.setGeometry(
            0, 0, e.size().width(), e.size().height()
        )

        return btn

    def _on_clicked(self, name: str) -> None:
        self._selected_name = name
        self._update_selection()
        self.preset_clicked.emit(name)

    def _update_selection(self) -> None:
        for pname, btn in self._buttons.items():
            if self._selected_name and pname == self._selected_name:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 0px; "
                    "border: 2px solid #00aaff; background: #2a3a4a; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 0px; }"
                )

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class ChannelBrowserSidebar(QDockWidget):
    """Expanded channel browser sidebar for the draw tool."""

    channel_clicked = Signal(str)    # channel id
    add_clicked = Signal()
    remove_clicked = Signal()
    move_up_clicked = Signal()
    move_down_clicked = Signal()
    rows_moved = Signal(int, int)    # src_row, dst_row (after Qt adjust)
    visible_toggled = Signal(bool)
    rename_requested = Signal(int)   # row index
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__("Channels", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(200)

        self._active_id: str | None = None
        self._channel_ids: list[str] = []

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._list = QListWidget()
        self._list.setMinimumHeight(200)
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemDoubleClicked.connect(self._on_double_clicked)
        self._list.model().rowsMoved.connect(self._on_rows_moved)

        _orig_kp = self._list.keyPressEvent
        def _list_key_press(event):
            if event.key() == Qt.Key.Key_Delete:
                self.remove_clicked.emit()
            else:
                _orig_kp(event)
        self._list.keyPressEvent = _list_key_press

        layout.addWidget(self._list)

        self.setWidget(container)

    def set_channels(self, channels, active_id: str | None) -> None:
        """Rebuild the list from DrawChannel objects."""
        self._active_id = active_id
        self._channel_ids = [ch.id for ch in channels]

        self._list.blockSignals(True)
        self._list.clear()
        active_row = 0
        for i, ch in enumerate(channels):
            icon = self._make_icon(ch.color, getattr(ch, "texture_id", ""))
            item = QListWidgetItem(icon, ch.name)
            if not ch.visible:
                item.setForeground(QColor("#888888"))
            self._list.addItem(item)
            if ch.id == active_id:
                active_row = i
        if channels:
            self._list.setCurrentRow(active_row)
        self._list.blockSignals(False)

    @staticmethod
    def _make_icon(color_hex: str, texture_id: str) -> QIcon:
        """Create a 20×20 colour swatch icon (or ‘T’ for texture channels)."""
        pix = QPixmap(20, 20)
        if texture_id:
            pix.fill(QColor("#666666"))
            p = QPainter(pix)
            p.setPen(QColor("#ffffff"))
            p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "T")
            p.end()
        else:
            pix.fill(QColor(color_hex))
        return QIcon(pix)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._channel_ids):
            self.channel_clicked.emit(self._channel_ids[row])

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if row >= 0:
            self.rename_requested.emit(row)

    def _on_rows_moved(
        self,
        _src_parent,
        src_row: int,
        _src_end: int,
        _dst_parent,
        dst_row: int,
    ) -> None:
        """Called by Qt model after internal drag-drop reorder."""
        # Qt uses insert-before semantics: adjust to actual target index.
        target = dst_row if dst_row <= src_row else dst_row - 1
        if target == src_row:
            return
        # Keep _channel_ids in sync with the new visual order.
        if 0 <= src_row < len(self._channel_ids) and 0 <= target < len(self._channel_ids):
            ch_id = self._channel_ids.pop(src_row)
            self._channel_ids.insert(target, ch_id)
        self.rows_moved.emit(src_row, target)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
