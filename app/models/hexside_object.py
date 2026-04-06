"""Hexside object data class - a line drawn along a hex edge."""

from __future__ import annotations

import random as _random
import uuid
from dataclasses import dataclass, field

from app.hex.hex_math import Hex


def _migrate_control_points(cp_data: list[float] | None) -> list[float]:
    """Migrate old 3-CP format to new 4-CP format."""
    if cp_data is None:
        return [0.0, 0.0, 0.0, 0.0]
    if len(cp_data) == 4:
        return list(cp_data)
    if len(cp_data) == 3:
        # Old format: CPs at t=0.25, 0.5, 0.75 → new: t=0, 1/3, 2/3, 1
        # L20: preserve all 3 values (previously cp_data[2] was silently dropped)
        return [0.0, cp_data[0], cp_data[1], cp_data[2]]
    return [0.0, 0.0, 0.0, 0.0]


@dataclass
class HexsideObject:
    """Represents a hexside (line drawn along the edge between two adjacent hexes)."""

    # Canonical edge identification (hex_a < hex_b lexicographically by (q, r))
    hex_a_q: int = 0
    hex_a_r: int = 0
    hex_b_q: int = 0
    hex_b_r: int = 0

    # Visual properties
    color: str = "#000000"
    width: float = 3.0  # Line width in world pixels
    outline: bool = False
    outline_color: str = "#000000"
    outline_width: float = 1.0
    # Outline texture (overrides outline_color when non-empty)
    outline_texture_id: str = ""
    outline_texture_zoom: float = 1.0
    outline_texture_rotation: float = 0.0

    # Shift: auto-perpendicular displacement toward matching adjacent hex fill
    shift_enabled: bool = False  # Only allowed when outline is False
    shift: float = 0.0  # Magnitude in world pixels (0.0 to 15.0), direction auto-detected

    # Random waviness
    random: bool = False
    random_seed: int = field(default_factory=lambda: _random.randint(0, 999999))
    random_amplitude: float = 3.0  # Smooth curve knot placement (world pixels)
    random_distance: float = 0.0  # Randomize subdivision point spacing (0=even, 1=max)
    random_jitter: float = 0.0  # High-frequency noise on top (world pixels)
    random_endpoint: float = 0.0  # Endpoint displacement when random is active (world pixels)
    random_offset: float = 0.0  # Constant perpendicular offset of inner control points

    # Control points: perpendicular offsets at fixed t-positions along the edge
    # 4 points at t=0 (start vertex), t=1/3, t=2/3, t=1 (end vertex)
    # Note: cp[0] and cp[3] are ignored in rendering; ep_a/ep_b are used for endpoints.
    control_points: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    # Endpoint 2D offsets from base vertex position (vertex ± random_endpoint displacement).
    # Allows fully free 2D movement in select mode and placement-time snapping.
    ep_a: list[float] = field(default_factory=lambda: [0.0, 0.0])  # offset at v1 end
    ep_b: list[float] = field(default_factory=lambda: [0.0, 0.0])  # offset at v2 end

    # Inner control point 2D offsets from the spine position at t≈1/3 and t≈2/3.
    # Replace the old scalar perpendicular offsets (control_points[1] and [2]) with
    # free 2D world-space offsets for full directional freedom.
    ip_a: list[float] = field(default_factory=lambda: [0.0, 0.0])  # inner point at t≈1/3
    ip_b: list[float] = field(default_factory=lambda: [0.0, 0.0])  # inner point at t≈2/3

    # Texture fill (None = solid color mode)
    texture_id: str | None = None
    texture_zoom: float = 1.0
    texture_rotation: float = 0.0

    # Taper: free ends narrow from full width to 0
    taper: bool = False
    taper_length: float = 0.5  # fraction of path (0.1–1.0)

    # Opacity (0.0 = transparent, 1.0 = opaque)
    opacity: float = 1.0          # main hexside line
    outline_opacity: float = 1.0  # outline only

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def cp_t_positions(self) -> list[float]:
        """Return t-positions for control points, randomized by distance.

        Endpoints (t=0, t=1) stay fixed; inner points shift when
        ``random`` is enabled and ``random_distance`` > 0.

        CP1 (i=1) stays in [0.05, 0.49]; CP2 (i=2) stays in [0.51, 0.95].
        Each inner CP is sampled independently using a per-CP seed.
        At distance=0 the points stay at their evenly-spaced base positions;
        at distance=1 they can reach the full range boundary.
        """
        n = len(self.control_points)
        if n <= 1:
            return [0.0]
        positions = [i / (n - 1) for i in range(n)]
        if self.random and self.random_distance > 0 and n > 2:
            for i in range(1, n - 1):
                rng_i = _random.Random(self.random_seed + 77777 + i * 11111)
                if i == 1:
                    target = rng_i.uniform(0.05, 0.49)
                else:
                    target = rng_i.uniform(0.51, 0.95)
                # Lerp between base position and random target based on distance slider
                positions[i] = positions[i] + self.random_distance * (target - positions[i])
        return positions

    def edge_key(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """Return the canonical edge key for this hexside."""
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
        if self.outline:
            data["outline"] = True
            data["outline_color"] = self.outline_color
            data["outline_width"] = self.outline_width
            if self.outline_texture_id:
                data["outline_texture_id"] = self.outline_texture_id
                if self.outline_texture_zoom != 1.0:
                    data["outline_texture_zoom"] = self.outline_texture_zoom
                if self.outline_texture_rotation != 0.0:
                    data["outline_texture_rotation"] = self.outline_texture_rotation
        if self.shift_enabled:
            data["shift_enabled"] = True
            if self.shift != 0.0:
                data["shift"] = self.shift
        # Always save random_seed so waviness is stable across save/load
        data["random_seed"] = self.random_seed
        if self.random:
            data["random"] = True
            data["random_amplitude"] = self.random_amplitude
            if self.random_distance != 0.0:
                data["random_distance"] = self.random_distance
            if self.random_jitter != 0.0:
                data["random_jitter"] = self.random_jitter
            if self.random_endpoint != 0.0:
                data["random_endpoint"] = self.random_endpoint
        if self.random_offset != 0.0:
            data["random_offset"] = self.random_offset
        # Only store control points if any are non-zero
        if any(cp != 0.0 for cp in self.control_points):
            data["control_points"] = list(self.control_points)
        if any(v != 0.0 for v in self.ep_a):
            data["ep_a"] = list(self.ep_a)
        if any(v != 0.0 for v in self.ep_b):
            data["ep_b"] = list(self.ep_b)
        if any(v != 0.0 for v in self.ip_a):
            data["ip_a"] = list(self.ip_a)
        if any(v != 0.0 for v in self.ip_b):
            data["ip_b"] = list(self.ip_b)
        if self.taper:
            data["taper"] = True
            if self.taper_length != 0.5:
                data["taper_length"] = self.taper_length
        if self.texture_id is not None:
            data["texture_id"] = self.texture_id
            if self.texture_zoom != 1.0:
                data["texture_zoom"] = self.texture_zoom
            if self.texture_rotation != 0.0:
                data["texture_rotation"] = self.texture_rotation
        if self.opacity != 1.0:
            data["opacity"] = self.opacity
        if self.outline_opacity != 1.0:
            data["outline_opacity"] = self.outline_opacity
        return data

    @classmethod
    def deserialize(cls, data: dict) -> HexsideObject:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            hex_a_q=data.get("hex_a_q", 0),
            hex_a_r=data.get("hex_a_r", 0),
            hex_b_q=data.get("hex_b_q", 0),
            hex_b_r=data.get("hex_b_r", 0),
            color=data.get("color", "#000000"),
            width=data.get("width", 3.0),
            outline=data.get("outline", False),
            outline_color=data.get("outline_color", "#000000"),
            outline_width=data.get("outline_width", 1.0),
            outline_texture_id=data.get("outline_texture_id", ""),
            outline_texture_zoom=data.get("outline_texture_zoom", 1.0),
            outline_texture_rotation=data.get("outline_texture_rotation", 0.0),
            shift_enabled=data.get("shift_enabled", False),
            shift=data.get("shift", 0.0),
            random=data.get("random", False),
            random_seed=data.get("random_seed", _random.randint(0, 999999)),
            random_amplitude=data.get("random_amplitude", 3.0),
            random_distance=data.get("random_distance", 0.0),
            random_jitter=data.get("random_jitter", 0.0),
            random_endpoint=data.get("random_endpoint", 0.0),
            random_offset=data.get("random_offset", 0.0),
            control_points=_migrate_control_points(data.get("control_points")),
            ep_a=(list(data.get("ep_a", []))[:2] + [0.0, 0.0])[:2],   # L21: ensure 2 elements
            ep_b=(list(data.get("ep_b", []))[:2] + [0.0, 0.0])[:2],
            ip_a=(list(data.get("ip_a", []))[:2] + [0.0, 0.0])[:2],
            ip_b=(list(data.get("ip_b", []))[:2] + [0.0, 0.0])[:2],
            taper=data.get("taper", False),
            taper_length=data.get("taper_length", 0.5),
            texture_id=data.get("texture_id"),
            texture_zoom=data.get("texture_zoom", 1.0),
            texture_rotation=data.get("texture_rotation", 0.0),
            opacity=data.get("opacity", 1.0),
            outline_opacity=data.get("outline_opacity", 1.0),
        )
