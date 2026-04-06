"""Border object data class - a styled line drawn along a hex edge."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.hex.hex_math import Hex


@dataclass
class BorderObject:
    """Represents a border line drawn along the edge between two adjacent hexes.

    Supports solid, dotted, and dashed line types with optional outline
    and perpendicular offset from the hexside center.
    """

    # Canonical edge identification (hex_a < hex_b lexicographically by (q, r))
    hex_a_q: int = 0
    hex_a_r: int = 0
    hex_b_q: int = 0
    hex_b_r: int = 0

    # Visual properties
    color: str = "#000000"
    width: float = 3.0  # Line width in world pixels

    # Line type: "solid", "dotted", "dashed"
    line_type: str = "solid"
    element_size: float = 4.0  # Dot diameter (dotted) or dash length (dashed)
    gap_size: float = 4.0  # Spacing between dots/dashes
    dash_cap: str = "round"  # "flat", "round", "square" (for dashed lines)

    # Outline
    outline: bool = False
    outline_color: str = "#000000"
    outline_width: float = 1.0

    # Offset: perpendicular shift from hexside center
    # 0 = centered, negative = toward hex_a, positive = toward hex_b
    offset: float = 0.0

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def edge_key(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """Return the canonical edge key for this border."""
        return ((self.hex_a_q, self.hex_a_r), (self.hex_b_q, self.hex_b_r))

    def hex_a(self) -> Hex:
        return Hex(self.hex_a_q, self.hex_a_r)

    def hex_b(self) -> Hex:
        return Hex(self.hex_b_q, self.hex_b_r)

    def serialize(self) -> dict:
        data = {
            "id": self.id,
            "hex_a_q": self.hex_a_q,
            "hex_a_r": self.hex_a_r,
            "hex_b_q": self.hex_b_q,
            "hex_b_r": self.hex_b_r,
            "color": self.color,
            "width": self.width,
        }
        if self.line_type != "solid":
            data["line_type"] = self.line_type
            data["element_size"] = self.element_size
            data["gap_size"] = self.gap_size
            if self.dash_cap != "round":
                data["dash_cap"] = self.dash_cap
        if self.outline:
            data["outline"] = True
            data["outline_color"] = self.outline_color
            data["outline_width"] = self.outline_width
        if self.offset != 0.0:
            data["offset"] = self.offset
        return data

    @classmethod
    def deserialize(cls, data: dict) -> BorderObject:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            hex_a_q=data.get("hex_a_q", 0),
            hex_a_r=data.get("hex_a_r", 0),
            hex_b_q=data.get("hex_b_q", 0),
            hex_b_r=data.get("hex_b_r", 0),
            color=data.get("color", "#000000"),
            width=data.get("width", 3.0),
            line_type={"lined": "dashed"}.get(
                data.get("line_type", "solid"),
                data.get("line_type", "solid"),
            ),
            element_size=data.get("element_size", 4.0),
            gap_size=data.get("gap_size", 4.0),
            dash_cap=data.get("dash_cap", "round"),
            outline=data.get("outline", False),
            outline_color=data.get("outline_color", "#000000"),
            outline_width=data.get("outline_width", 1.0),
            offset=data.get("offset", 0.0),
        )
