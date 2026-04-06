"""Undo/Redo command stack."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.commands.command import Command


class CommandStack(QObject):
    stack_changed = Signal()

    def __init__(self, max_size: int = 20):
        super().__init__()
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._max_size = max_size

    def execute(self, cmd: Command) -> None:
        cmd.execute()
        self._undo_stack.append(cmd)
        self._redo_stack.clear()
        if len(self._undo_stack) > self._max_size:
            self._undo_stack.pop(0)
        self.stack_changed.emit()

    def undo(self) -> None:
        if self._undo_stack:
            cmd = self._undo_stack.pop()
            cmd.undo()
            self._redo_stack.append(cmd)
            self.stack_changed.emit()

    def redo(self) -> None:
        if self._redo_stack:
            cmd = self._redo_stack.pop()
            cmd.execute()
            self._undo_stack.append(cmd)
            if len(self._undo_stack) > self._max_size:  # L05: enforce max_size on redo too
                self._undo_stack.pop(0)
            self.stack_changed.emit()

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.stack_changed.emit()
