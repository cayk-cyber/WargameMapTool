"""Asset Manager dialog - import, rename, delete, categorize assets."""

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

from app.io.asset_library import (
    AssetCatalog,
    LibraryAsset,
    delete_asset,
    import_asset,
    load_catalog,
    rename_asset,
    set_asset_category,
    set_asset_game,
)

_THUMB_SIZE = 64
_GRID_COLS = 4


class AssetManagerDialog(QDialog):
    """Full asset library manager dialog."""

    catalog_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Asset Manager")
        self.setMinimumSize(520, 500)

        self._catalog: AssetCatalog = load_catalog()
        self._selected_asset: LibraryAsset | None = None
        self._thumb_cache: dict[str, QPixmap] = {}
        self._asset_buttons: dict[str, QPushButton] = {}

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

        self._info_label = QLabel("No asset selected")
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

    def _filtered_assets(self) -> list[LibraryAsset]:
        """Return assets matching current filter."""
        game = self._game_combo.currentText()
        category = self._category_combo.currentText()
        search = self._search_edit.text().strip().lower()

        result = []
        for asset in self._catalog.assets:
            if game != "All" and asset.game != game:
                continue
            if category != "All" and asset.category != category:
                continue
            if search and search not in asset.display_name.lower():
                continue
            result.append(asset)
        return result

    def _rebuild_grid(self):
        """Rebuild the thumbnail grid from filtered assets."""
        # Clear existing
        for btn in self._asset_buttons.values():
            self._grid_layout.removeWidget(btn)
            btn.deleteLater()
        self._asset_buttons.clear()

        filtered = self._filtered_assets()
        for i, asset in enumerate(filtered):
            btn = self._make_thumb_button(asset)
            row = i // _GRID_COLS
            col = i % _GRID_COLS
            self._grid_layout.addWidget(btn, row, col)
            self._asset_buttons[asset.id] = btn

        # Update selection highlight
        self._update_selection_highlight()

    def _make_thumb_button(self, asset: LibraryAsset) -> QToolButton:
        """Create a thumbnail button for an asset."""
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setFixedSize(_THUMB_SIZE + 16, _THUMB_SIZE + 30)
        game_info = f"  ({asset.game})" if asset.game else ""
        btn.setToolTip(f"{asset.display_name}{game_info}\n{asset.category}")

        pixmap = self._get_thumbnail(asset)
        if pixmap:
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))

        btn.setText(asset.display_name[:10])
        btn.setStyleSheet(
            "QToolButton { padding: 2px; }"
        )
        btn.clicked.connect(lambda checked=False, a=asset: self._on_asset_clicked(a))
        return btn

    def _get_thumbnail(self, asset: LibraryAsset) -> QPixmap | None:
        """Get or create a cached thumbnail for an asset."""
        if asset.id in self._thumb_cache:
            return self._thumb_cache[asset.id]

        if not asset.exists():
            return None

        image = QImage(asset.file_path())
        if image.isNull():
            return None

        scaled = image.scaled(
            _THUMB_SIZE, _THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        self._thumb_cache[asset.id] = pixmap
        return pixmap

    def _on_asset_clicked(self, asset: LibraryAsset):
        """Select an asset."""
        self._selected_asset = asset
        self._update_selection_highlight()
        self._update_preview()
        editable = not asset.builtin
        self._rename_btn.setEnabled(editable)
        self._game_btn.setEnabled(editable)
        self._category_btn.setEnabled(editable)
        self._delete_btn.setEnabled(editable)

    def _update_selection_highlight(self):
        """Update button borders to show selection."""
        for asset_id, btn in self._asset_buttons.items():
            if self._selected_asset and asset_id == self._selected_asset.id:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; "
                    "border: 2px solid #00aaff; }"
                )
            else:
                btn.setStyleSheet(
                    "QToolButton { padding: 2px; }"
                )

    def _update_preview(self):
        """Update the preview area."""
        if not self._selected_asset or not self._selected_asset.exists():
            self._preview_label.clear()
            self._info_label.setText("No asset selected")
            return

        image = QImage(self._selected_asset.file_path())
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
        game_str = self._selected_asset.game or "—"
        builtin_str = "  |  [Built-in]" if self._selected_asset.builtin else ""
        self._info_label.setText(
            f"{self._selected_asset.display_name}  |  "
            f"{game_str}  |  "
            f"{self._selected_asset.category}  |  "
            f"{image.width()}x{image.height()} px{builtin_str}"
        )

    def _on_filter_changed(self):
        """Rebuild grid when filter changes."""
        self._rebuild_grid()

    def _on_import(self):
        """Import one or more image files."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Assets", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;All Files (*)",
        )
        if not paths:
            return

        if len(paths) == 1:
            # Single file: full dialog with name editing
            base_name = os.path.splitext(os.path.basename(paths[0]))[0]
            catalog = load_catalog()
            dialog = ImportAssetDialog(
                base_name, catalog.games(), catalog.categories(), self
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            asset = import_asset(
                paths[0], dialog.asset_name(),
                dialog.asset_category(), dialog.asset_game(),
            )
            self._selected_asset = asset
        else:
            # Multiple files: batch dialog for shared game/category
            filenames = [os.path.basename(p) for p in paths]
            catalog = load_catalog()
            dialog = BatchImportDialog(
                filenames, catalog.games(), catalog.categories(), self
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            game = dialog.asset_game()
            category = dialog.asset_category()
            for path in paths:
                base_name = os.path.splitext(os.path.basename(path))[0]
                asset = import_asset(path, base_name, category, game)
                self._selected_asset = asset

        self._thumb_cache.clear()
        self._refresh()
        self.catalog_changed.emit()

    def _on_rename(self):
        """Rename the selected asset."""
        if not self._selected_asset:
            return

        name, ok = QInputDialog.getText(
            self, "Rename Asset", "New name:",
            text=self._selected_asset.display_name,
        )
        if ok and name.strip():
            rename_asset(self._selected_asset.id, name.strip())
            self._selected_asset.display_name = name.strip()
            self._thumb_cache.pop(self._selected_asset.id, None)
            self._refresh()
            self.catalog_changed.emit()

    def _on_set_game(self):
        """Set game for the selected asset."""
        if not self._selected_asset:
            return

        games = self._catalog.games()
        current = self._selected_asset.game

        # Editable combo in a QInputDialog doesn't support free text well,
        # so use getItem with editable=True
        items = games if games else []
        current_idx = items.index(current) if current in items else -1

        chosen, ok = QInputDialog.getItem(
            self, "Set Game", "Game:",
            items, max(0, current_idx), True,
        )
        if not ok:
            return

        set_asset_game(self._selected_asset.id, chosen.strip())
        self._selected_asset.game = chosen.strip()
        self._refresh()
        self.catalog_changed.emit()

    def _on_set_category(self):
        """Set category for the selected asset."""
        if not self._selected_asset:
            return

        categories = self._catalog.categories()
        items = categories + ["-- New Category --"]

        # Pre-select current category
        current_idx = 0
        if self._selected_asset.category in items:
            current_idx = items.index(self._selected_asset.category)

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

        set_asset_category(self._selected_asset.id, chosen)
        self._selected_asset.category = chosen
        self._refresh()
        self.catalog_changed.emit()

    def _on_delete(self):
        """Delete the selected asset."""
        if not self._selected_asset:
            return
        if self._selected_asset.builtin:
            QMessageBox.information(
                self, "Built-in Asset",
                "Built-in assets cannot be deleted.",
            )
            return

        reply = QMessageBox.question(
            self, "Delete Asset",
            f"Delete '{self._selected_asset.display_name}'?\n"
            "This will permanently remove the file.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._thumb_cache.pop(self._selected_asset.id, None)
            delete_asset(self._selected_asset.id)
            self._selected_asset = None
            self._rename_btn.setEnabled(False)
            self._game_btn.setEnabled(False)
            self._category_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._refresh()
            self.catalog_changed.emit()


class ImportAssetDialog(QDialog):
    """Dialog for importing an asset with name, game, and category."""

    def __init__(
        self,
        filename: str,
        games: list[str],
        categories: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Import Asset")
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
            QMessageBox.warning(self, "Import Asset", "Please enter a name.")
            return
        self.accept()

    def asset_name(self) -> str:
        return self._name_edit.text().strip()

    def asset_game(self) -> str:
        return self._game_combo.currentText().strip()

    def asset_category(self) -> str:
        text = self._category_combo.currentText().strip()
        return text if text else "Uncategorized"


class BatchImportDialog(QDialog):
    """Dialog for batch importing multiple assets with shared game and category."""

    def __init__(
        self,
        filenames: list[str],
        games: list[str],
        categories: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Batch Import Assets")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        # File list
        file_label = QLabel(f"{len(filenames)} files selected:")
        layout.addWidget(file_label)

        file_list = QLabel("\n".join(filenames[:20]))
        file_list.setStyleSheet("color: #888; font-size: 11px;")
        if len(filenames) > 20:
            file_list.setText(
                "\n".join(filenames[:20]) + f"\n... and {len(filenames) - 20} more"
            )
        layout.addWidget(file_list)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Game + Category form
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

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def asset_game(self) -> str:
        return self._game_combo.currentText().strip()

    def asset_category(self) -> str:
        text = self._category_combo.currentText().strip()
        return text if text else "Uncategorized"
