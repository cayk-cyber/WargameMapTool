"""Ordered collection of layers with Qt signals."""

from __future__ import annotations

from typing import Iterator

from PySide6.QtCore import QObject, Signal


class LayerStack(QObject):
    layer_added = Signal(int)
    layer_removed = Signal(int)
    layer_moved = Signal(int, int)
    layers_changed = Signal()
    active_layer_changed = Signal()

    def __init__(self):
        super().__init__()
        self._layers: list = []
        self._active_index: int = -1

    @property
    def active_layer(self):
        if 0 <= self._active_index < len(self._layers):
            return self._layers[self._active_index]
        return None

    @property
    def active_index(self) -> int:
        return self._active_index

    @active_index.setter
    def active_index(self, index: int):
        if index != self._active_index:
            self._active_index = index
            self.active_layer_changed.emit()

    def add_layer(self, layer, index: int = -1) -> None:
        if index < 0:
            index = len(self._layers)
        self._layers.insert(index, layer)
        self._active_index = index
        self.layer_added.emit(index)
        self.layers_changed.emit()
        self.active_layer_changed.emit()

    def remove_layer(self, index: int):
        if 0 <= index < len(self._layers):
            layer = self._layers.pop(index)
            if self._active_index >= len(self._layers):
                self._active_index = len(self._layers) - 1
            self.layer_removed.emit(index)
            self.layers_changed.emit()
            self.active_layer_changed.emit()  # M01: notify listeners of active layer change
            return layer
        return None

    def move_layer(self, from_index: int, to_index: int) -> None:
        if from_index == to_index:
            return
        # M02: bounds check to prevent IndexError
        if not (0 <= from_index < len(self._layers)):
            return
        to_index = max(0, min(to_index, len(self._layers) - 1))
        layer = self._layers.pop(from_index)
        self._layers.insert(to_index, layer)
        if self._active_index == from_index:
            self._active_index = to_index
        self.layer_moved.emit(from_index, to_index)
        self.layers_changed.emit()

    def reorder_layers(self, new_order: list) -> None:
        """Replace layer list with a new ordering.

        *new_order* must contain exactly the same layer objects.
        """
        if len(new_order) != len(self._layers):
            return
        active = self.active_layer
        self._layers = list(new_order)
        if active in self._layers:
            self._active_index = self._layers.index(active)
        else:
            self._active_index = max(0, len(self._layers) - 1) if self._layers else -1
        for layer in self._layers:
            layer.mark_dirty()
        self.layers_changed.emit()

    def __iter__(self) -> Iterator:
        return iter(self._layers)

    def __len__(self) -> int:
        return len(self._layers)

    def __getitem__(self, index):
        return self._layers[index]
