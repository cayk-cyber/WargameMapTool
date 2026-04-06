"""Shared helpers for tool options panel modules."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
)

# Maximum columns for the color grid
PALETTE_GRID_COLS = 4

# Widget types that should ignore mouse wheel when unfocused
SCROLL_GUARD_TYPES = (QSpinBox, QDoubleSpinBox, QSlider, QComboBox)


class NoScrollFilter(QObject):
    """Event filter that blocks wheel events on unfocused input widgets."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return False


def update_color_btn(btn: QPushButton, color: QColor) -> None:
    """Style a color button with the given QColor background."""
    btn.setStyleSheet(
        f"background-color: {color.name()}; border: 1px solid #555;"
    )


class AddColorDialog(QDialog):
    """Small dialog for adding a named color to a palette."""

    def __init__(self, initial_color: QColor, parent=None, initial_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add Color")
        self.setMinimumWidth(250)

        layout = QFormLayout(self)

        # Name input
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Color name...")
        if initial_name:
            self._name_edit.setText(initial_name)
        layout.addRow("Name:", self._name_edit)

        # Color button
        self._color = QColor(initial_color)
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(40, 25)
        self._update_btn_style()
        self._color_btn.clicked.connect(self._pick_color)
        layout.addRow("Color:", self._color_btn)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _update_btn_style(self):
        self._color_btn.setStyleSheet(
            f"background-color: {self._color.name()}; border: 1px solid #555;"
        )

    def _pick_color(self):
        color = QColorDialog.getColor(self._color, self, "Pick Color")
        if color.isValid():
            self._color = color
            self._update_btn_style()

    def _on_accept(self):
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Add Color", "Please enter a color name.")
            return
        self.accept()

    def color_name(self) -> str:
        return self._name_edit.text().strip()

    def color_value(self) -> QColor:
        return QColor(self._color)
