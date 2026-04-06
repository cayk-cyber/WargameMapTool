"""Layer panel - list of layers with controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.layers.asset_layer import AssetLayer
from app.layers.background_layer import BackgroundImageLayer
from app.layers.base_layer import Layer
from app.layers.border_layer import BorderLayer
from app.layers.draw_layer import DrawLayer
from app.layers.fill_layer import FillLayer
from app.layers.freeform_path_layer import FreeformPathLayer
from app.layers.hexside_layer import HexsideLayer
from app.layers.layer_stack import LayerStack
from app.layers.path_layer import PathLayer
from app.layers.sketch_layer import SketchLayer
from app.layers.text_layer import TextLayer


def _layer_type_label(layer: Layer) -> str:
    """Return a short type label for display."""
    if isinstance(layer, FillLayer):
        return "Fill"
    if isinstance(layer, AssetLayer):
        return "Asset"
    if isinstance(layer, BackgroundImageLayer):
        return "Image"
    if isinstance(layer, BorderLayer):
        return "Border"
    if isinstance(layer, DrawLayer):
        return "Draw"
    if isinstance(layer, TextLayer):
        return "Text"
    if isinstance(layer, HexsideLayer):
        return "Hexside"
    if isinstance(layer, PathLayer):
        return "Path (Center)"
    if isinstance(layer, FreeformPathLayer):
        return "Path (Freeform)"
    if isinstance(layer, SketchLayer):
        return "Sketch"
    return "Layer"


class LayerPanel(QDockWidget):
    layer_add_requested = Signal(str, str)  # (layer_type, layer_name)

    def __init__(self, layer_stack: LayerStack, parent=None):
        super().__init__("Layers", parent)
        self._layer_stack = layer_stack
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(200)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        # Layer list
        self._list_widget = QListWidget()
        self._list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        self._list_widget.itemChanged.connect(self._on_item_changed)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list_widget.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self._list_widget)

        # Available layer types
        self._layer_types = ["Asset", "Border", "Draw", "Fill", "Hexside", "Image", "Path (Center)", "Path (Freeform)", "Sketch", "Text"]

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(1)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        add_btn = QPushButton("Add")
        add_btn.setToolTip("Add a new layer")
        add_btn.clicked.connect(self._on_add_clicked)
        btn_layout.addWidget(add_btn)

        remove_btn = QPushButton("Del")
        remove_btn.setToolTip("Remove selected layer")
        remove_btn.clicked.connect(self._on_remove_clicked)
        btn_layout.addWidget(remove_btn)

        up_btn = QPushButton("Up")
        up_btn.setToolTip("Move layer up")
        up_btn.clicked.connect(self._on_move_up)
        btn_layout.addWidget(up_btn)

        down_btn = QPushButton("Down")
        down_btn.setToolTip("Move layer down")
        down_btn.clicked.connect(self._on_move_down)
        btn_layout.addWidget(down_btn)

        layout.addLayout(btn_layout)

        # Minimap placeholder (created later via setup_minimap)
        self._minimap: MinimapWidget | None = None
        self._minimap_container = layout

        self.setWidget(container)

        # Connect signals
        self._layer_stack.layers_changed.connect(self._refresh_list)
        self._layer_stack.active_layer_changed.connect(self._sync_selection)

        self._refreshing = False

    def setup_minimap(self, project, canvas):
        """Create the minimap widget. Call after canvas is available."""
        from app.panels.minimap_widget import MinimapWidget
        self._minimap = MinimapWidget(project, canvas, self)
        self._minimap.navigate_requested.connect(canvas.center_on_world)
        canvas.viewport_changed.connect(self._minimap.update)
        self._minimap_container.addWidget(self._minimap)
        self._minimap.setVisible(True)

    def set_minimap_visible(self, visible: bool):
        """Show or hide the minimap."""
        if self._minimap:
            self._minimap.setVisible(visible)
            if visible:
                self._minimap._mark_dirty()

    def update_minimap_project(self, project):
        """Update minimap project reference after new/open."""
        if self._minimap:
            self._minimap.set_project(project)

    def add_layer_type(self, name: str):
        """Add a layer type to the available types."""
        if name not in self._layer_types:
            self._layer_types.append(name)

    def _stack_to_row(self, stack_idx: int) -> int:
        """Convert layer stack index to list row (reversed display)."""
        return len(self._layer_stack) - 1 - stack_idx

    def _row_to_stack(self, row: int) -> int:
        """Convert list row to layer stack index (reversed display)."""
        return len(self._layer_stack) - 1 - row

    def _refresh_list(self):
        self._refreshing = True
        self._list_widget.clear()
        # Display in reverse: top of list = top of render (last in stack)
        layers = list(self._layer_stack)
        for row, layer in enumerate(reversed(layers)):
            stack_idx = len(layers) - 1 - row
            item = QListWidgetItem()
            type_label = _layer_type_label(layer)
            item.setText(f"[{type_label}] {layer.name}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, stack_idx)
            self._list_widget.addItem(item)

        if self._layer_stack.active_index >= 0:
            self._list_widget.setCurrentRow(
                self._stack_to_row(self._layer_stack.active_index)
            )
        self._refreshing = False

    def _sync_selection(self):
        if not self._refreshing:
            idx = self._layer_stack.active_index
            if 0 <= idx < len(self._layer_stack):
                self._list_widget.setCurrentRow(self._stack_to_row(idx))

    def _on_selection_changed(self, row: int):
        if not self._refreshing and row >= 0:
            self._layer_stack.active_index = self._row_to_stack(row)

    def _on_item_changed(self, item: QListWidgetItem):
        if self._refreshing:
            return
        layer_idx = item.data(Qt.ItemDataRole.UserRole)
        if layer_idx is not None and layer_idx < len(self._layer_stack):
            layer = self._layer_stack[layer_idx]
            checked = item.checkState() == Qt.CheckState.Checked
            if layer.visible != checked:
                layer.visible = checked
                self._layer_stack.layers_changed.emit()

    def _on_item_double_clicked(self, item: QListWidgetItem):
        layer_idx = item.data(Qt.ItemDataRole.UserRole)
        if layer_idx is None or layer_idx >= len(self._layer_stack):
            return
        layer = self._layer_stack[layer_idx]
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Rename Layer", "Layer name:", text=layer.name,
        )
        if ok and name.strip():
            layer.name = name.strip()
            self._layer_stack.layers_changed.emit()

    def _on_add_clicked(self):
        dialog = _AddLayerDialog(self._layer_types, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.layer_add_requested.emit(dialog.layer_type(), dialog.layer_name())

    def _on_remove_clicked(self):
        idx = self._layer_stack.active_index
        if idx < 0:
            return
        layer = self._layer_stack[idx]
        reply = QMessageBox.question(
            self, "Remove Layer",
            f"Remove layer '{layer.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._layer_stack.remove_layer(idx)

    def _on_move_up(self):
        """Move layer up in display = higher stack index (rendered later = on top)."""
        idx = self._layer_stack.active_index
        if idx < len(self._layer_stack) - 1:
            self._layer_stack.move_layer(idx, idx + 1)

    def _on_move_down(self):
        """Move layer down in display = lower stack index (rendered earlier = below)."""
        idx = self._layer_stack.active_index
        if idx > 0:
            self._layer_stack.move_layer(idx, idx - 1)

    def _on_rows_moved(self):
        """Sync layer stack after drag-and-drop reorder in QListWidget."""
        if self._refreshing:
            return
        count = self._list_widget.count()
        if count != len(self._layer_stack):
            return
        # Read new desired order from list items (each stores old stack_idx)
        # Row 0 = top of display = highest stack index, so reverse
        new_order = []
        for row in range(count):
            item = self._list_widget.item(row)
            old_stack_idx = item.data(Qt.ItemDataRole.UserRole)
            new_order.append(self._layer_stack[old_stack_idx])
        new_order.reverse()  # row 0 -> last in stack, row N -> first in stack
        self._layer_stack.reorder_layers(new_order)


class _AddLayerDialog(QDialog):
    """Dialog for adding a new layer with name and type."""

    def __init__(self, layer_types: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Layer")
        self.setMinimumWidth(280)

        layout = QFormLayout(self)

        self._type_combo = QComboBox()
        self._type_combo.addItems(layer_types)
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        layout.addRow("Type:", self._type_combo)

        self._name_edit = QLineEdit()
        layout.addRow("Name:", self._name_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        # Set default name based on initial type
        self._on_type_changed(self._type_combo.currentText())

    def _on_type_changed(self, type_name: str):
        self._name_edit.setPlaceholderText(type_name)

    def _on_accept(self):
        if not self._name_edit.text().strip() and not self._name_edit.placeholderText():
            QMessageBox.warning(self, "Add Layer", "Please enter a layer name.")
            return
        self.accept()

    def layer_type(self) -> str:
        return self._type_combo.currentText()

    def layer_name(self) -> str:
        name = self._name_edit.text().strip()
        return name if name else self._type_combo.currentText()
