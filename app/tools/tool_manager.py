"""Manages registered tools and the active tool."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.tools.base_tool import Tool


class ToolManager(QObject):
    tool_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._tools: dict[str, Tool] = {}
        self._active_tool: Tool | None = None

    def register_tool(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def set_active_tool(self, name: str) -> None:
        if name in self._tools:
            self._active_tool = self._tools[name]
            self.tool_changed.emit(name)

    @property
    def active_tool(self) -> Tool | None:
        return self._active_tool

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)
