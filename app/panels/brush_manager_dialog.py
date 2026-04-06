"""Brush Manager dialog - import, rename, delete, and categorize brush PNGs."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.io.brush_library import (
    BrushCatalog,
    LibraryBrush,
    delete_brush,
    import_brush,
    load_catalog,
    save_catalog,
)

_THUMB_SIZE = 64
_GRID_COLS = 4
_DARK_BG = QColor("#2b2b2b")


class BrushManagerDialog(QDialog):
    """Full brush library manager dialog."""

    catalog_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Brush Manager")
        self.setMinimumSize(480, 480)

        self._catalog: BrushCatalog = load_catalog()
        self._selected_brush: LibraryBrush | None = None
        self._thumb_cache: dict[str, QPixmap] = {}
        self._brush_buttons: dict[str, QToolButton] = {}

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Action buttons ---
        action_layout = QHBoxLayout()

        import_btn = QPushButton("Import...")
        import_btn.clicked.connect(self._on_import)
        action_layout.addWidget(import_btn)

        self._rename_btn = QPushButton("Rename")
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self._on_rename)
        action_layout.addWidget(self._rename_btn)

        self._category_btn = QPushButton("Set Category")
        self._category_btn.setEnabled(False)
        self._category_btn.clicked.connect(self._on_set_category)
        action_layout.addWidget(self._category_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        action_layout.addWidget(self._delete_btn)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # --- Filter row ---
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Category:"))
        self._category_combo = QComboBox()
        self._category_combo.setMinimumWidth(100)
        self._category_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._category_combo)

        filter_layout.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filter by name...")
        self._search_edit.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._search_edit, stretch=1)

        layout.addLayout(filter_layout)

        # --- Thumbnail grid (scrollable) ---
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setMinimumHeight(200)

        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(6)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._grid_container)
        layout.addWidget(self._scroll, stretch=1)

        # --- Preview area ---
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)

        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(160, 160)
        self._preview_label.setMaximumHeight(160)
        self._preview_label.setStyleSheet("background: #2b2b2b;")
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        preview_layout.addWidget(self._preview_label)

        self._info_label = QLabel("No brush selected")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self._info_label)

        layout.addWidget(preview_group)

        # --- Close button ---
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _refresh(self):
        """Reload catalog and rebuild UI."""
        self._catalog = load_catalog()
        self._refresh_filter_combo()
        self._rebuild_grid()
        self._update_preview()

    def _refresh_filter_combo(self):
        """Update category filter combo."""
        self._category_combo.blockSignals(True)
        current_cat = self._category_combo.currentText()
        self._category_combo.clear()
        self._category_combo.addItem("All")
        for cat in self._catalog.categories():
            self._category_combo.addItem(cat)
        idx = self._category_combo.findText(current_cat)
        if idx >= 0:
            self._category_combo.setCurrentIndex(idx)
        self._category_combo.blockSignals(False)

    def _filtered_brushes(self) -> list[LibraryBrush]:
        """Return brushes matching current filter."""
        category = self._category_combo.currentText()
        search = self._search_edit.text().strip().lower()

        result = []
        for brush in self._catalog.brushes:
            if category != "All" and brush.category != category:
                continue
            if search and search not in brush.display_name.lower():
                continue
            result.append(brush)
        return result

    def _rebuild_grid(self):
        """Rebuild the thumbnail grid from filtered brushes."""
        for btn in self._brush_buttons.values():
            self._grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._brush_buttons.clear()

        filtered = self._filtered_brushes()
        for i, brush in enumerate(filtered):
            btn = self._make_thumb_button(brush)
            row = i // _GRID_COLS
            col = i % _GRID_COLS
            self._grid_layout.addWidget(btn, row, col)
            self._brush_buttons[brush.id] = btn

        self._update_selection_highlight()

    def _make_thumb_button(self, brush: LibraryBrush) -> QToolButton:
        """Create a thumbnail button for a brush."""
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(_THUMB_SIZE + 16, _THUMB_SIZE + 30)
        builtin_str = "  [Built-in]" if brush.builtin else ""
        btn.setToolTip(f"{brush.display_name}\n{brush.category}{builtin_str}")

        pixmap = self._get_thumbnail(brush)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))

        btn.setText(brush.display_name[:10])
        btn.setStyleSheet("QToolButton { padding: 2px; }")
        btn.clicked.connect(lambda checked=False, b=brush: self._on_brush_clicked(b))
        return btn

    def _get_thumbnail(self, brush: LibraryBrush) -> QPixmap | None:
        """Get or create a cached dark-background thumbnail for a brush."""
        if brush.id in self._thumb_cache:
            return self._thumb_cache[brush.id]

        if not brush.exists():
            return None

        src = QPixmap(brush.file_path())
        if src.isNull():
            return None

        src = src.scaled(
            _THUMB_SIZE, _THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        result = QPixmap(_THUMB_SIZE, _THUMB_SIZE)
        result.fill(_DARK_BG)
        p = QPainter(result)
        x = (_THUMB_SIZE - src.width()) // 2
        y = (_THUMB_SIZE - src.height()) // 2
        p.drawPixmap(x, y, src)
        p.end()

        self._thumb_cache[brush.id] = result
        return result

    def _on_brush_clicked(self, brush: LibraryBrush):
        """Select a brush."""
        self._selected_brush = brush
        self._update_selection_highlight()
        self._update_preview()
        editable = not brush.builtin
        self._rename_btn.setEnabled(editable)
        self._category_btn.setEnabled(editable)
        self._delete_btn.setEnabled(editable)

    def _update_selection_highlight(self):
        """Update button borders to show selection."""
        for brush_id, btn in self._brush_buttons.items():
            if self._selected_brush and brush_id == self._selected_brush.id:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 2px; }")

    def _update_preview(self):
        """Update the preview area."""
        if not self._selected_brush or not self._selected_brush.exists():
            self._preview_label.clear()
            self._info_label.setText("No brush selected")
            return

        src = QPixmap(self._selected_brush.file_path())
        if src.isNull():
            self._preview_label.clear()
            self._info_label.setText("Cannot load image")
            return

        preview_size = 150
        src = src.scaled(
            preview_size, preview_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        bg = QPixmap(preview_size, preview_size)
        bg.fill(_DARK_BG)
        p = QPainter(bg)
        px = (preview_size - src.width()) // 2
        py = (preview_size - src.height()) // 2
        p.drawPixmap(px, py, src)
        p.end()

        self._preview_label.setPixmap(bg)
        builtin_str = "  |  [Built-in]" if self._selected_brush.builtin else ""
        self._info_label.setText(
            f"{self._selected_brush.display_name}  |  "
            f"{self._selected_brush.category}{builtin_str}"
        )

    def _on_filter_changed(self):
        """Rebuild grid when filter changes."""
        self._rebuild_grid()

    def _on_import(self):
        """Import one or more PNG brush files."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Brushes", "",
            "Images (*.png *.jpg *.jpeg);;All Files (*)",
        )
        if not paths:
            return

        categories = self._catalog.categories()
        default_cat = categories[0] if categories else "Uncategorized"

        last_brush = None
        for path in paths:
            base_name = os.path.splitext(os.path.basename(path))[0]
            if len(paths) == 1:
                # Single file: ask for name + category
                dialog = _ImportBrushDialog(base_name, categories, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                last_brush = import_brush(
                    path, dialog.brush_name(), dialog.brush_category()
                )
            else:
                # Batch: use filename, ask once for category
                last_brush = import_brush(path, base_name, default_cat)

        if last_brush:
            self._selected_brush = last_brush

        self._thumb_cache.clear()
        self._refresh()
        self.catalog_changed.emit()

    def _on_rename(self):
        """Rename the selected brush."""
        if not self._selected_brush:
            return

        name, ok = QInputDialog.getText(
            self, "Rename Brush", "New name:",
            text=self._selected_brush.display_name,
        )
        if not ok or not name.strip():
            return

        # Update catalog in-place
        catalog = load_catalog()
        brush = catalog.find_by_id(self._selected_brush.id)
        if brush:
            brush.display_name = name.strip()
            save_catalog(catalog)
            self._selected_brush.display_name = name.strip()

        self._thumb_cache.pop(self._selected_brush.id, None)
        self._refresh()
        self.catalog_changed.emit()

    def _on_set_category(self):
        """Set category for the selected brush."""
        if not self._selected_brush:
            return

        categories = self._catalog.categories()
        items = categories + ["-- New Category --"]

        current_idx = 0
        if self._selected_brush.category in items:
            current_idx = items.index(self._selected_brush.category)

        chosen, ok = QInputDialog.getItem(
            self, "Set Category", "Category:",
            items, current_idx, False,
        )
        if not ok:
            return

        if chosen == "-- New Category --":
            cat_name, ok2 = QInputDialog.getText(
                self, "New Category", "Category name:",
            )
            if not ok2 or not cat_name.strip():
                return
            chosen = cat_name.strip()

        # Update catalog in-place
        catalog = load_catalog()
        brush = catalog.find_by_id(self._selected_brush.id)
        if brush:
            brush.category = chosen
            save_catalog(catalog)
            self._selected_brush.category = chosen

        self._refresh()
        self.catalog_changed.emit()

    def _on_delete(self):
        """Delete the selected brush."""
        if not self._selected_brush:
            return
        if self._selected_brush.builtin:
            QMessageBox.information(
                self, "Built-in Brush",
                "Built-in brushes cannot be deleted.",
            )
            return

        reply = QMessageBox.question(
            self, "Delete Brush",
            f"Delete '{self._selected_brush.display_name}'?\n"
            "This will permanently remove the file.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._thumb_cache.pop(self._selected_brush.id, None)
            delete_brush(self._selected_brush.id)
            self._selected_brush = None
            self._rename_btn.setEnabled(False)
            self._category_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._refresh()
            self.catalog_changed.emit()


class _ImportBrushDialog(QDialog):
    """Dialog for importing a single brush with name and category."""

    def __init__(self, filename: str, categories: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Brush")
        self.setMinimumWidth(280)

        layout = QFormLayout(self)

        self._name_edit = QLineEdit(filename)
        layout.addRow("Name:", self._name_edit)

        self._category_combo = QComboBox()
        self._category_combo.setEditable(True)
        self._category_combo.addItems(categories)
        if categories:
            self._category_combo.setCurrentIndex(0)
        else:
            self._category_combo.setCurrentText("Uncategorized")
        layout.addRow("Category:", self._category_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _on_accept(self):
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Import Brush", "Please enter a name.")
            return
        self.accept()

    def brush_name(self) -> str:
        return self._name_edit.text().strip()

    def brush_category(self) -> str:
        text = self._category_combo.currentText().strip()
        return text if text else "Uncategorized"
