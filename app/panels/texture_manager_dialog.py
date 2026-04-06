"""Texture Manager dialog - import, rename, delete, categorize textures."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
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

from app.io.texture_library import (
    TextureCatalog,
    LibraryTexture,
    delete_texture,
    import_texture,
    load_catalog,
    rename_texture,
    set_texture_category,
    set_texture_game,
)
from app.panels.texture_edit_dialog import TextureEditDialog

_THUMB_SIZE = 64
_GRID_COLS = 4


class TextureManagerDialog(QDialog):
    """Full texture library manager dialog."""

    catalog_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Texture Manager")
        self.setMinimumSize(520, 500)

        self._catalog: TextureCatalog = load_catalog()
        self._selected_texture: LibraryTexture | None = None
        self._thumb_cache: dict[str, QPixmap] = {}
        self._texture_buttons: dict[str, QPushButton] = {}

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

        self._game_btn = QPushButton("Set Game")
        self._game_btn.setEnabled(False)
        self._game_btn.clicked.connect(self._on_set_game)
        action_layout.addWidget(self._game_btn)

        self._category_btn = QPushButton("Set Category")
        self._category_btn.setEnabled(False)
        self._category_btn.clicked.connect(self._on_set_category)
        action_layout.addWidget(self._category_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        action_layout.addWidget(self._delete_btn)

        self._edit_btn = QPushButton("Edit Texture...")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit_texture)
        action_layout.addWidget(self._edit_btn)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # --- Filter row ---
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Game:"))
        self._game_combo = QComboBox()
        self._game_combo.setMinimumWidth(80)
        self._game_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._game_combo)

        filter_layout.addWidget(QLabel("Category:"))
        self._category_combo = QComboBox()
        self._category_combo.setMinimumWidth(80)
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
        self._preview_label.setMinimumSize(200, 200)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        preview_layout.addWidget(self._preview_label)

        self._info_label = QLabel("No texture selected")
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
        self._refresh_filter_combos()
        self._rebuild_grid()
        self._update_preview()

    def _refresh_filter_combos(self):
        """Update game and category filter combos."""
        self._game_combo.blockSignals(True)
        current_game = self._game_combo.currentText()
        self._game_combo.clear()
        self._game_combo.addItem("All")
        for g in self._catalog.games():
            self._game_combo.addItem(g)
        idx = self._game_combo.findText(current_game)
        if idx >= 0:
            self._game_combo.setCurrentIndex(idx)
        self._game_combo.blockSignals(False)

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

    def _filtered_textures(self) -> list[LibraryTexture]:
        """Return textures matching current filter."""
        game = self._game_combo.currentText()
        category = self._category_combo.currentText()
        search = self._search_edit.text().strip().lower()

        result = []
        for texture in self._catalog.textures:
            if game != "All" and texture.game != game:
                continue
            if category != "All" and texture.category != category:
                continue
            if search and search not in texture.display_name.lower():
                continue
            result.append(texture)
        return result

    def _rebuild_grid(self):
        """Rebuild the thumbnail grid from filtered textures."""
        for btn in self._texture_buttons.values():
            self._grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._texture_buttons.clear()

        filtered = self._filtered_textures()
        for i, texture in enumerate(filtered):
            btn = self._make_thumb_button(texture)
            row = i // _GRID_COLS
            col = i % _GRID_COLS
            self._grid_layout.addWidget(btn, row, col)
            self._texture_buttons[texture.id] = btn

        self._update_selection_highlight()

    def _make_thumb_button(self, texture: LibraryTexture) -> QToolButton:
        """Create a thumbnail button for a texture."""
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(_THUMB_SIZE + 16, _THUMB_SIZE + 30)
        game_info = f"  ({texture.game})" if texture.game else ""
        btn.setToolTip(f"{texture.display_name}{game_info}\n{texture.category}")

        pixmap = self._get_thumbnail(texture)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))

        btn.setText(texture.display_name[:10])
        btn.setStyleSheet("QToolButton { padding: 2px; }")
        btn.clicked.connect(
            lambda checked=False, t=texture: self._on_texture_clicked(t)
        )
        return btn

    def _get_thumbnail(self, texture: LibraryTexture) -> QPixmap | None:
        """Get or create a cached thumbnail for a texture."""
        if texture.id in self._thumb_cache:
            return self._thumb_cache[texture.id]

        if not texture.exists():
            return None

        image = QImage(texture.file_path())
        if image.isNull():
            return None

        scaled = image.scaled(
            _THUMB_SIZE, _THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        self._thumb_cache[texture.id] = pixmap
        return pixmap

    def _on_texture_clicked(self, texture: LibraryTexture):
        """Select a texture."""
        self._selected_texture = texture
        self._update_selection_highlight()
        self._update_preview()
        is_editable = not texture.builtin
        self._rename_btn.setEnabled(is_editable)
        self._game_btn.setEnabled(is_editable)
        self._category_btn.setEnabled(is_editable)
        self._delete_btn.setEnabled(is_editable)
        self._edit_btn.setEnabled(True)  # available for all textures (saves as new)

    def _update_selection_highlight(self):
        """Update button borders to show selection."""
        for texture_id, btn in self._texture_buttons.items():
            if self._selected_texture and texture_id == self._selected_texture.id:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; "
                    "border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet("QToolButton { padding: 2px; }")

    def _update_preview(self):
        """Update the preview area."""
        if not self._selected_texture or not self._selected_texture.exists():
            self._preview_label.clear()
            self._info_label.setText("No texture selected")
            return

        image = QImage(self._selected_texture.file_path())
        if image.isNull():
            self._preview_label.clear()
            self._info_label.setText("Cannot load image")
            return

        scaled = image.scaled(
            200, 200,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(QPixmap.fromImage(scaled))
        game_str = self._selected_texture.game or "\u2014"
        self._info_label.setText(
            f"{self._selected_texture.display_name}  |  "
            f"{game_str}  |  "
            f"{self._selected_texture.category}  |  "
            f"{image.width()}x{image.height()} px"
        )

    def _on_filter_changed(self):
        """Rebuild grid when filter changes."""
        self._rebuild_grid()

    def _on_import(self):
        """Import one or more texture files."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Textures", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;All Files (*)",
        )
        if not paths:
            return

        if len(paths) == 1:
            base_name = os.path.splitext(os.path.basename(paths[0]))[0]
            catalog = load_catalog()
            dialog = ImportTextureDialog(
                base_name, catalog.games(), catalog.categories(), self
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            texture = import_texture(
                paths[0], dialog.texture_name(),
                dialog.texture_category(), dialog.texture_game(),
            )
            self._selected_texture = texture
        else:
            filenames = [os.path.basename(p) for p in paths]
            catalog = load_catalog()
            dialog = BatchImportTextureDialog(
                filenames, catalog.games(), catalog.categories(), self
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            game = dialog.texture_game()
            category = dialog.texture_category()
            for path in paths:
                base_name = os.path.splitext(os.path.basename(path))[0]
                texture = import_texture(path, base_name, category, game)
                self._selected_texture = texture

        self._thumb_cache.clear()
        self._refresh()
        self.catalog_changed.emit()

    def _on_rename(self):
        """Rename the selected texture."""
        if not self._selected_texture:
            return

        name, ok = QInputDialog.getText(
            self, "Rename Texture", "New name:",
            text=self._selected_texture.display_name,
        )
        if ok and name.strip():
            rename_texture(self._selected_texture.id, name.strip())
            self._selected_texture.display_name = name.strip()
            self._thumb_cache.pop(self._selected_texture.id, None)
            self._refresh()
            self.catalog_changed.emit()

    def _on_set_game(self):
        """Set game for the selected texture."""
        if not self._selected_texture:
            return

        games = self._catalog.games()
        current = self._selected_texture.game
        items = games if games else []
        current_idx = items.index(current) if current in items else -1

        chosen, ok = QInputDialog.getItem(
            self, "Set Game", "Game:",
            items, max(0, current_idx), True,
        )
        if not ok:
            return

        set_texture_game(self._selected_texture.id, chosen.strip())
        self._selected_texture.game = chosen.strip()
        self._refresh()
        self.catalog_changed.emit()

    def _on_set_category(self):
        """Set category for the selected texture."""
        if not self._selected_texture:
            return

        categories = self._catalog.categories()
        items = categories + ["-- New Category --"]
        current_idx = 0
        if self._selected_texture.category in items:
            current_idx = items.index(self._selected_texture.category)

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

        set_texture_category(self._selected_texture.id, chosen)
        self._selected_texture.category = chosen
        self._refresh()
        self.catalog_changed.emit()

    def _on_edit_texture(self):
        """Open the texture edit dialog for the selected texture."""
        if not self._selected_texture:
            return
        dialog = TextureEditDialog(self._selected_texture, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._thumb_cache.clear()
            self._refresh()
            self.catalog_changed.emit()

    def _on_delete(self):
        """Delete the selected texture."""
        if not self._selected_texture:
            return

        reply = QMessageBox.question(
            self, "Delete Texture",
            f"Delete '{self._selected_texture.display_name}'?\n"
            "This will permanently remove the file.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._thumb_cache.pop(self._selected_texture.id, None)
            delete_texture(self._selected_texture.id)
            self._selected_texture = None
            self._rename_btn.setEnabled(False)
            self._game_btn.setEnabled(False)
            self._category_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._edit_btn.setEnabled(False)
            self._refresh()
            self.catalog_changed.emit()


class ImportTextureDialog(QDialog):
    """Dialog for importing a texture with name, game, and category."""

    def __init__(
        self,
        filename: str,
        games: list[str],
        categories: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Import Texture")
        self.setMinimumWidth(300)

        layout = QFormLayout(self)

        self._name_edit = QLineEdit(filename)
        layout.addRow("Name:", self._name_edit)

        self._game_combo = QComboBox()
        self._game_combo.setEditable(True)
        self._game_combo.addItems(games)
        self._game_combo.setCurrentText("")
        layout.addRow("Game:", self._game_combo)

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
            QMessageBox.warning(self, "Import Texture", "Please enter a name.")
            return
        self.accept()

    def texture_name(self) -> str:
        return self._name_edit.text().strip()

    def texture_game(self) -> str:
        return self._game_combo.currentText().strip()

    def texture_category(self) -> str:
        text = self._category_combo.currentText().strip()
        return text if text else "Uncategorized"


class BatchImportTextureDialog(QDialog):
    """Dialog for batch importing multiple textures with shared game and category."""

    def __init__(
        self,
        filenames: list[str],
        games: list[str],
        categories: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Batch Import Textures")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        file_label = QLabel(f"{len(filenames)} files selected:")
        layout.addWidget(file_label)

        file_list = QLabel("\n".join(filenames[:20]))
        file_list.setStyleSheet("color: #888; font-size: 11px;")
        if len(filenames) > 20:
            file_list.setText(
                "\n".join(filenames[:20]) + f"\n... and {len(filenames) - 20} more"
            )
        layout.addWidget(file_list)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        form = QFormLayout()

        self._game_combo = QComboBox()
        self._game_combo.setEditable(True)
        self._game_combo.addItems(games)
        self._game_combo.setCurrentText("")
        form.addRow("Game:", self._game_combo)

        self._category_combo = QComboBox()
        self._category_combo.setEditable(True)
        self._category_combo.addItems(categories)
        if categories:
            self._category_combo.setCurrentIndex(0)
        else:
            self._category_combo.setCurrentText("Uncategorized")
        form.addRow("Category:", self._category_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def texture_game(self) -> str:
        return self._game_combo.currentText().strip()

    def texture_category(self) -> str:
        text = self._category_combo.currentText().strip()
        return text if text else "Uncategorized"
