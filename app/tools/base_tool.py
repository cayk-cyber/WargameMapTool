"""Abstract base class for all tools."""

from __future__ import annotations

from abc import ABC, abstractmethod

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QWidget

from app.hex.hex_math import Hex, Layout


class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def cursor(self) -> Qt.CursorShape:
        return Qt.CursorShape.ArrowCursor

    def mouse_press(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        pass

    def mouse_move(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> bool | None:
        """Handle mouse move.  Return True/None to request repaint, False to skip."""
        return None

    def mouse_release(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        pass

    def mouse_double_click(self, event: QMouseEvent, world_pos: QPointF, hex_coord: Hex) -> None:
        pass

    def key_press(self, event: QKeyEvent) -> None:
        pass

    def key_release(self, event: QKeyEvent) -> None:
        pass

    def paint_overlay(
        self,
        painter: QPainter,
        viewport_rect: QRectF,
        layout: Layout,
        hover_hex: Hex | None,
    ) -> None:
        pass

    def get_options_widget(self) -> QWidget | None:
        return None
