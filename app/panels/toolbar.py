"""Main toolbar with tool buttons."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QToolBar

from app.tools.tool_manager import ToolManager


class MainToolBar(QToolBar):
    def __init__(self, tool_manager: ToolManager, parent=None):
        super().__init__("Tools", parent)
        self._tool_manager = tool_manager
        self._actions: dict[str, QAction] = {}
        self._action_group = QActionGroup(self)

        self.setMovable(False)

    def add_tool_button(self, name: str, shortcut: str | None = None) -> QAction:
        action = QAction(name, self)
        action.setCheckable(True)
        action.setData(name)

        if shortcut:
            action.setShortcut(shortcut)
            action.setToolTip(f"{name} ({shortcut})")
        else:
            action.setToolTip(name)

        action.triggered.connect(lambda checked, n=name: self._on_tool_selected(n))

        self._action_group.addAction(action)
        self.addAction(action)
        self._actions[name] = action

        return action

    def _on_tool_selected(self, name: str):
        self._tool_manager.set_active_tool(name)

    def set_active_tool(self, name: str):
        if name in self._actions:
            self._actions[name].setChecked(True)

    def restrict_to_tool(self, allowed_name: str | None) -> None:
        """Enable only the tool matching the active layer, disable all others.

        Pass *None* to re-enable every button (e.g. when no layer is active).
        """
        for name, action in self._actions.items():
            action.setEnabled(allowed_name is None or name == allowed_name)
