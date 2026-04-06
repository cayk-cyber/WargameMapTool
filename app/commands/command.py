"""Abstract command base class and CompoundCommand for undo/redo."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Command(ABC):
    @abstractmethod
    def execute(self) -> None:
        pass

    @abstractmethod
    def undo(self) -> None:
        pass

    @property
    def description(self) -> str:
        return "Unknown"


class CompoundCommand(Command):
    """Groups multiple commands into a single undo step."""

    def __init__(self, description: str = "Multiple changes"):
        self._commands: list[Command] = []
        self._description = description

    def add(self, cmd: Command) -> None:
        self._commands.append(cmd)

    @property
    def is_empty(self) -> bool:
        return len(self._commands) == 0

    def execute(self) -> None:
        executed = []
        try:
            for cmd in self._commands:
                cmd.execute()
                executed.append(cmd)
        except Exception:
            # L06: roll back already-executed sub-commands on failure
            for cmd in reversed(executed):
                try:
                    cmd.undo()
                except Exception:
                    pass
            raise

    def undo(self) -> None:
        for cmd in reversed(self._commands):
            cmd.undo()

    @property
    def description(self) -> str:
        return self._description
