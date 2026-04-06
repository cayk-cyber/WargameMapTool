"""Shortcuts reference dialog – lists all keyboard shortcuts and mouse gestures."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Data: (shortcut_text, description)
# ---------------------------------------------------------------------------

_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Canvas Navigation", [
        ("Scroll Wheel",            "Zoom in / out (anchored at cursor)"),
        ("Middle Mouse Drag",       "Pan canvas"),
        ("Right Mouse Drag (>5px)", "Pan canvas"),
        ("Ctrl+0",                  "Zoom to Fit"),
    ]),
    ("Hold B (physical key)", [
        ("Hold B",    "Temporarily hide layer directly below the active layer"),
        ("Release B", "Restore hidden layer"),
    ]),
    ("File", [
        ("Ctrl+N",       "New Map"),
        ("Ctrl+O",       "Open"),
        ("Ctrl+S",       "Save"),
        ("Ctrl+Shift+S", "Save As"),
        ("Ctrl+Shift+E", "Export"),
        ("Alt+F4",       "Exit"),
    ]),
    ("Edit", [
        ("Ctrl+Z",       "Undo"),
        ("Ctrl+Y",       "Redo"),
        ("Ctrl+,",       "Map Settings"),
        ("Ctrl+P",       "Edit Palettes"),
        ("Ctrl+Shift+C", "Calculate Grid"),
        ("Ctrl+Shift+R", "Render Layer to Image"),
    ]),
    ("View", [
        ("Ctrl+Shift+G", "Show / Hide Grid"),
        ("Ctrl+D",       "Show / Hide Center Dots"),
        ("Ctrl+K",       "Show / Hide Coordinates"),
        ("Ctrl+G",       "Show / Hide Megahexes"),
        ("Ctrl+M",       "Show / Hide Minimap"),
        ("Ctrl+B",       "Set Background Color"),
        ("Ctrl+L",       "Global Lighting"),
        ("Ctrl+E",       "Toggle Visible GFX (Shadow, Bevel, Structure)"),
        ("Ctrl+Shift+Q", "Toggle Render Quality (Performance / Quality)"),
        ("Ctrl+Shift+D", "Cycle Cache Rebuild Delay"),
        ("Ctrl+Shift+Z", "Cycle Zoom Settle Delay"),
    ]),
    ("Help", [
        ("F1", "Open Shortcuts Reference"),
        ("F2", "Open Documentation"),
    ]),
    ("Tool Activation (single key)", [
        ("B", "Background (Image) Tool"),
        ("D", "Draw Tool"),
        ("F", "Fill Tool"),
        ("A", "Asset Tool"),
        ("T", "Text Tool"),
        ("H", "Hexside Tool"),
        ("O", "Border Tool"),
        ("P", "Path Tool (Center-to-Center)"),
        ("R", "Path Tool (Freeform)"),
        ("S", "Sketch Tool"),
    ]),
    ("Background Tool", [
        ("Left Drag",  "Move background image"),
    ]),
    ("Fill Tool", [
        ("Left Click / Drag",  "Fill hex(es) in brush radius"),
        ("Right Click / Drag", "Clear hex(es) in brush radius"),
    ]),
    ("Asset Tool – Place Mode", [
        ("Left Click",                        "Place asset"),
        ("Right Click",                       "Delete asset under cursor"),
        ("Ctrl + Left Drag (up / down)",      "Adjust placement scale"),
        ("Alt + Left Drag (left / right)",    "Adjust placement rotation"),
    ]),
    ("Asset Tool – Select Mode", [
        ("Left Click",               "Select asset"),
        ("Drag body",                "Move asset"),
        ("Drag corner handle",       "Scale asset"),
        ("Drag green circle handle", "Rotate asset"),
        ("Delete",                   "Remove selected asset"),
        ("Escape",                   "Deselect"),
    ]),
    ("Asset Tool – Erase Mode", [
        ("Left Drag",                    "Erase (paint mask)"),
        ("Ctrl + Left Drag (up / down)", "Adjust erase brush size"),
    ]),
    ("Text Tool – Place Mode", [
        ("Left Click",  "Open text input dialog and place text"),
        ("Right Click", "Delete text under cursor"),
    ]),
    ("Text Tool – Select Mode", [
        ("Left Click",               "Select text"),
        ("Double Click",             "Edit text content"),
        ("Drag body",                "Move text"),
        ("Drag corner handle",       "Scale text (font size)"),
        ("Drag green circle handle", "Rotate text"),
        ("F4",                       "Edit text content"),
        ("Delete",                   "Remove selected text"),
        ("Escape",                   "Deselect"),
    ]),
    ("Hexside Tool – Place Mode", [
        ("Left Drag",  "Paint hexside edges"),
        ("Right Click","Delete hexside under cursor"),
    ]),
    ("Hexside Tool – Select Mode", [
        ("Left Click",               "Select hexside"),
        ("Drag control point",       "Move control point / endpoint"),
        ("Delete",                   "Remove selected hexside"),
        ("Escape",                   "Deselect"),
    ]),
    ("Border Tool – Place Mode", [
        ("Left Drag",   "Paint border edges"),
        ("Right Click", "Delete border under cursor"),
    ]),
    ("Border Tool – Select Mode", [
        ("Left Click", "Select border"),
        ("Delete",     "Remove selected border"),
        ("Escape",     "Deselect"),
    ]),
    ("Path Tool (Center) – Place Mode", [
        ("Left Drag",   "Paint center-to-center paths"),
        ("Right Click", "Delete path under cursor"),
    ]),
    ("Path Tool (Center) – Select Mode", [
        ("Left Click",         "Select path"),
        ("Drag control point", "Move control point / endpoint"),
        ("Delete",             "Remove selected path"),
        ("Escape",             "Deselect"),
    ]),
    ("Freeform Path Tool – Draw Mode", [
        ("Left Drag",                    "Draw freeform path"),
        ("Shift + Left Click",           "Add waypoint to straight-line polyline"),
        ("Left Click (during polyline)", "Add final point and commit polyline"),
        ("Enter / Return",              "Commit pending polyline"),
        ("Escape (during polyline)",     "Cancel pending polyline"),
        ("Right Click (during polyline)","Cancel pending polyline"),
        ("Right Click",                  "Delete path under cursor"),
    ]),
    ("Freeform Path Tool – Select Mode", [
        ("Left Click",   "Select path"),
        ("Drag waypoint","Move waypoint"),
        ("Delete",       "Remove selected path"),
        ("Escape",       "Deselect"),
    ]),
    ("Sketch Tool – Draw Mode", [
        ("Left Drag",   "Draw shape"),
        ("Right Click", "Delete shape under cursor"),
    ]),
    ("Sketch Tool – Select Mode", [
        ("Left Click",               "Select object"),
        ("Drag body",                "Move object"),
        ("Drag corner handle",       "Resize object"),
        ("Drag green circle handle", "Rotate object"),
        ("Ctrl+C",                   "Copy selected object"),
        ("Ctrl+V",                   "Paste copied object (+10 px offset)"),
        ("Delete",                   "Remove selected object"),
        ("Escape",                   "Deselect"),
    ]),
    ("Draw Tool", [
        ("Left Drag",                    "Paint brush stroke"),
        ("Shift + Left Click",           "Draw straight line from last stroke endpoint"),
        ("Ctrl + Left Drag (up / down)", "Adjust brush size"),
        ("Alt + Left Drag (up / down)",  "Adjust brush hardness"),
        ("Shift + Left Drag (up / down)","Adjust brush flow"),
        ("E",                            "Toggle draw / erase mode"),
    ]),
    ("Edit Image Dialog – Navigation", [
        ("Scroll Wheel",                  "Zoom in / out"),
        ("Right-click Drag",              "Pan the canvas"),
    ]),
    ("Edit Image Dialog – Paint Brush / Eraser", [
        ("Left Click / Drag",             "Paint or erase pixels"),
        ("Ctrl + Left Drag (up / down)",  "Adjust brush size"),
        ("Ctrl+Z",                        "Undo last operation"),
    ]),
]


def _make_key_label(text: str) -> QLabel:
    lbl = QLabel(text)
    font = QFont("Consolas", 9)
    lbl.setFont(font)
    lbl.setStyleSheet("border: 1px solid palette(mid); border-radius: 3px; padding: 1px 5px;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return lbl


def _make_desc_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    return lbl


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts & Mouse Gestures")
        self.setMinimumWidth(620)
        self.resize(680, 700)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root_layout.addWidget(scroll)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(10)
        scroll.setWidget(container)

        for section_title, rows in _SECTIONS:
            group = QGroupBox(section_title)
            gl = QGridLayout(group)
            gl.setContentsMargins(8, 6, 8, 6)
            gl.setHorizontalSpacing(12)
            gl.setVerticalSpacing(4)
            gl.setColumnStretch(0, 0)
            gl.setColumnStretch(1, 1)
            for row_idx, (shortcut, description) in enumerate(rows):
                gl.addWidget(_make_key_label(shortcut),  row_idx, 0)
                gl.addWidget(_make_desc_label(description), row_idx, 1)
            container_layout.addWidget(group)

        container_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root_layout.addWidget(buttons)
