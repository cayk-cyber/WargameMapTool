"""Text object data class."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QColor, QTransform


@dataclass
class TextObject:
    text: str = "Text"
    x: float = 0.0
    y: float = 0.0
    font_family: str = "Arial"
    font_size: float = 12.0  # World-space points
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str = "#000000"
    alignment: str = "left"  # "left", "center", "right"
    opacity: float = 1.0
    rotation: float = 0.0  # Degrees
    outline: bool = False
    outline_color: str = "#ffffff"
    outline_width: float = 1.0
    over_grid: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def make_font(self) -> QFont:
        """Create a QFont from the object's font settings."""
        font = QFont(self.font_family, int(self.font_size))
        font.setPointSizeF(self.font_size)
        font.setBold(self.bold)
        font.setItalic(self.italic)
        font.setUnderline(self.underline)
        return font

    def _local_text_rect(self) -> QRectF:
        """Get the text bounding rect in local (unrotated) coordinates at origin."""
        font = self.make_font()
        fm = QFontMetricsF(font)
        rect = fm.boundingRect(self.text) if self.text else QRectF(0, 0, 10, fm.height())
        # QFontMetrics returns rect relative to baseline; normalize
        w = fm.horizontalAdvance(self.text) if self.text else 10.0
        h = fm.height()
        # Alignment offset (x-axis)
        if self.alignment == "center":
            x_off = -w / 2
        elif self.alignment == "right":
            x_off = -w
        else:
            x_off = 0.0
        y_off = -fm.ascent()
        return QRectF(x_off, y_off, w, h)

    def bounding_rect(self) -> QRectF:
        """Get the world-space bounding rect, accounting for rotation."""
        local = self._local_text_rect()
        if self.outline:
            # Expand for outline width
            ow = self.outline_width
            local = local.adjusted(-ow, -ow, ow, ow)
        if self.rotation != 0.0:
            transform = QTransform()
            transform.rotate(self.rotation)
            rotated = transform.mapRect(local)
        else:
            rotated = local
        return QRectF(
            self.x + rotated.x(),
            self.y + rotated.y(),
            rotated.width(),
            rotated.height(),
        )

    def contains_point(self, world_x: float, world_y: float) -> bool:
        """Check if a world-space point is inside the bounding rect."""
        return self.bounding_rect().contains(QPointF(world_x, world_y))

    def paint(self, painter: QPainter) -> None:
        """Render this text object. Caller should have set world transform."""
        if not self.text:
            return
        font = self.make_font()
        local = self._local_text_rect()

        painter.save()
        painter.translate(self.x, self.y)
        if self.rotation != 0.0:
            painter.rotate(self.rotation)
        painter.setOpacity(self.opacity)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        baseline = QPointF(local.x(), local.y() + QFontMetricsF(font).ascent())

        if self.outline:
            path = QPainterPath()
            path.addText(baseline, font, self.text)
            pen = QPen(QColor(self.outline_color), self.outline_width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(QColor(self.color))
            painter.drawPath(path)
        else:
            # Path-based rendering for crisp vector text at all zoom levels
            path = QPainterPath()
            path.addText(baseline, font, self.text)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.color))
            painter.drawPath(path)

        painter.restore()

    def serialize(self) -> dict:
        data = {
            "id": self.id,
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "color": self.color,
            "alignment": self.alignment,
            "opacity": self.opacity,
            "rotation": self.rotation,
        }
        if self.bold:
            data["bold"] = True
        if self.italic:
            data["italic"] = True
        if self.underline:
            data["underline"] = True
        if self.outline:
            data["outline"] = True
            data["outline_color"] = self.outline_color
            data["outline_width"] = self.outline_width
        if self.over_grid:
            data["over_grid"] = True
        return data

    @classmethod
    def deserialize(cls, data: dict) -> TextObject:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            text=data.get("text", "Text"),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            font_family=data.get("font_family", "Arial"),
            font_size=data.get("font_size", 12.0),
            bold=data.get("bold", False),
            italic=data.get("italic", False),
            underline=data.get("underline", False),
            color=data.get("color", "#000000"),
            alignment=data.get("alignment", "left"),
            opacity=data.get("opacity", 1.0),
            rotation=data.get("rotation", 0.0),
            outline=data.get("outline", False),
            outline_color=data.get("outline_color", "#ffffff"),
            outline_width=data.get("outline_width", 1.0),
            over_grid=data.get("over_grid", False),
        )
