"""Palette editor dialog - create, edit and delete color palettes."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.io.palette_manager import (
    ColorPalette,
    PaletteColor,
    delete_palette,
    ensure_default_palette,
    is_builtin_palette,
    list_palettes,
    load_palette,
    save_palette,
)
from app.panels.tool_options.helpers import PALETTE_GRID_COLS, AddColorDialog


class PaletteEditorDialog(QDialog):
    """Dialog for creating and editing color palettes."""

    catalog_changed = Signal()  # emitted after any add/rename/delete/edit operation

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Palette Editor")
        self.setMinimumWidth(420)

        self._current_palette: ColorPalette | None = None
        self._selected_idx: int = -1
        self._color_buttons: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # --- Palette selector ---
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Palette:"))
        self._palette_combo = QComboBox()
        sel_row.addWidget(self._palette_combo, stretch=1)

        new_btn = QPushButton("New")
        new_btn.setFixedWidth(50)
        new_btn.clicked.connect(self._on_new_palette)
        sel_row.addWidget(new_btn)

        rename_btn = QPushButton("Rename")
        rename_btn.setFixedWidth(60)
        rename_btn.clicked.connect(self._on_rename_palette)
        sel_row.addWidget(rename_btn)

        self._delete_palette_btn = QPushButton("Delete")
        self._delete_palette_btn.setFixedWidth(55)
        self._delete_palette_btn.clicked.connect(self._on_delete_palette)
        sel_row.addWidget(self._delete_palette_btn)
        layout.addLayout(sel_row)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep1)

        # --- Color grid ---
        self._color_grid_widget = QWidget()
        self._color_grid_layout = QGridLayout(self._color_grid_widget)
        self._color_grid_layout.setSpacing(3)
        self._color_grid_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._color_grid_widget)

        # --- Color edit buttons ---
        color_btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Color")
        add_btn.clicked.connect(self._on_add_color)
        color_btn_row.addWidget(add_btn)
        self._remove_color_btn = QPushButton("- Remove")
        self._remove_color_btn.clicked.connect(self._on_remove_color)
        color_btn_row.addWidget(self._remove_color_btn)
        self._edit_color_btn = QPushButton("Edit...")
        self._edit_color_btn.clicked.connect(self._on_edit_color)
        color_btn_row.addWidget(self._edit_color_btn)
        color_btn_row.addStretch()
        layout.addLayout(color_btn_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # --- Close button ---
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        # Initialize
        ensure_default_palette()
        self._refresh_combo()
        self._palette_combo.currentTextChanged.connect(self._on_palette_changed)
        if self._palette_combo.count() > 0:
            self._on_palette_changed(self._palette_combo.currentText())

    def _refresh_combo(self, select_name: str | None = None) -> None:
        self._palette_combo.blockSignals(True)
        current = select_name or self._palette_combo.currentText()
        self._palette_combo.clear()
        for name in list_palettes():
            self._palette_combo.addItem(name)
        idx = self._palette_combo.findText(current)
        if idx >= 0:
            self._palette_combo.setCurrentIndex(idx)
        elif self._palette_combo.count() > 0:
            self._palette_combo.setCurrentIndex(0)
        self._palette_combo.blockSignals(False)

    def _on_palette_changed(self, name: str) -> None:
        if not name:
            return
        try:
            self._current_palette = load_palette(name)
        except FileNotFoundError:
            self._current_palette = None
        self._selected_idx = -1
        self._rebuild_grid()
        self._delete_palette_btn.setEnabled(not is_builtin_palette(name))

    def _rebuild_grid(self) -> None:
        for btn in self._color_buttons:
            self._color_grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._color_buttons.clear()
        if not self._current_palette:
            return
        for i, pc in enumerate(self._current_palette.colors):
            btn = QPushButton()
            btn.setFixedSize(36, 36)
            btn.setToolTip(pc.name)
            self._style_btn(btn, pc.color, selected=False)
            btn.clicked.connect(lambda checked, idx=i: self._on_color_clicked(idx))
            row = i // PALETTE_GRID_COLS
            col = i % PALETTE_GRID_COLS
            self._color_grid_layout.addWidget(btn, row, col)
            self._color_buttons.append(btn)

    def _style_btn(self, btn: QPushButton, color_hex: str, selected: bool) -> None:
        border = "2px solid #00aaff" if selected else "1px solid #555"
        btn.setStyleSheet(f"background-color: {color_hex}; border: {border};")

    def _on_color_clicked(self, idx: int) -> None:
        if not self._current_palette or idx >= len(self._current_palette.colors):
            return
        if 0 <= self._selected_idx < len(self._color_buttons):
            old = self._current_palette.colors[self._selected_idx]
            self._style_btn(self._color_buttons[self._selected_idx], old.color, selected=False)
        self._selected_idx = idx
        pc = self._current_palette.colors[idx]
        self._style_btn(self._color_buttons[idx], pc.color, selected=True)

    def _on_new_palette(self) -> None:
        name, ok = QInputDialog.getText(self, "New Palette", "Palette name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        palette = ColorPalette(name=name, colors=[])
        save_palette(palette)
        self._refresh_combo(select_name=name)
        self._on_palette_changed(name)
        self.catalog_changed.emit()

    def _on_rename_palette(self) -> None:
        if not self._current_palette:
            return
        if is_builtin_palette(self._current_palette.name):
            QMessageBox.information(self, "Rename Palette", "Built-in palettes cannot be renamed.")
            return
        old_name = self._current_palette.name
        name, ok = QInputDialog.getText(self, "Rename Palette", "New name:", text=old_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        delete_palette(old_name)
        self._current_palette.name = name
        save_palette(self._current_palette)
        self._refresh_combo(select_name=name)
        self.catalog_changed.emit()

    def _on_delete_palette(self) -> None:
        name = self._palette_combo.currentText()
        if not name:
            return
        if self._palette_combo.count() <= 1:
            QMessageBox.warning(self, "Delete Palette", "Cannot delete the last palette.")
            return
        reply = QMessageBox.question(
            self, "Delete Palette", f"Delete palette '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_palette(name)
            self._current_palette = None
            self._refresh_combo()
            self._on_palette_changed(self._palette_combo.currentText())
            self.catalog_changed.emit()

    def _on_add_color(self) -> None:
        if not self._current_palette:
            return
        if is_builtin_palette(self._current_palette.name):
            QMessageBox.information(
                self, "Add Color",
                "Built-in palettes cannot be edited.\nCreate a new palette first.",
            )
            return
        dialog = AddColorDialog(QColor("#808080"), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._current_palette.colors.append(
                PaletteColor(name=dialog.color_name(), color=dialog.color_value().name())
            )
            save_palette(self._current_palette)
            self._selected_idx = -1
            self._rebuild_grid()
            self.catalog_changed.emit()

    def _on_remove_color(self) -> None:
        if not self._current_palette or self._selected_idx < 0:
            return
        if is_builtin_palette(self._current_palette.name):
            QMessageBox.information(self, "Remove Color", "Built-in palettes cannot be edited.")
            return
        if self._selected_idx >= len(self._current_palette.colors):
            return
        self._current_palette.colors.pop(self._selected_idx)
        self._selected_idx = -1
        save_palette(self._current_palette)
        self._rebuild_grid()
        self.catalog_changed.emit()

    def _on_edit_color(self) -> None:
        if not self._current_palette or self._selected_idx < 0:
            return
        if is_builtin_palette(self._current_palette.name):
            QMessageBox.information(self, "Edit Color", "Built-in palettes cannot be edited.")
            return
        if self._selected_idx >= len(self._current_palette.colors):
            return
        pc = self._current_palette.colors[self._selected_idx]
        dialog = AddColorDialog(QColor(pc.color), self, initial_name=pc.name)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pc.name = dialog.color_name()
            pc.color = dialog.color_value().name()
            save_palette(self._current_palette)
            prev_idx = self._selected_idx
            self._rebuild_grid()
            # Restore selection highlight
            if 0 <= prev_idx < len(self._color_buttons):
                self._on_color_clicked(prev_idx)
            self.catalog_changed.emit()
