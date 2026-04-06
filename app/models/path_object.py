"""Path object data class - a line drawn between adjacent hex centers."""

from __future__ import annotations

import random as _random
import uuid
from dataclasses import dataclass, field

from app.hex.hex_math import Hex


@dataclass
class PathObject:
    """Represents a path segment connecting two adjacent hex centers."""

    # Canonical segment identification (hex_a < hex_b lexicographically by (q, r))
    hex_a_q: int = 0
    hex_a_r: int = 0
    hex_b_q: int = 0
    hex_b_r: int = 0

    # Foreground path
    color: str = "#000000"
    width: float = 3.0
    line_type: str = "solid"  # "solid", "dashed", "dotted"
    dash_length: float = 6.0
    gap_length: float = 4.0
    dash_cap: str = "flat"  # "flat", "round", "square"

    # Foreground texture (overrides color when non-empty)
    texture_id: str = ""  # Empty = solid color, non-empty = use texture
    texture_zoom: float = 1.0
    texture_rotation: float = 0.0

    # Background path (drawn underneath as wider second layer)
    bg_enabled: bool = False
    bg_color: str = "#000000"
    bg_width: float = 6.0
    bg_line_type: str = "solid"
    bg_dash_length: float = 6.0
    bg_gap_length: float = 4.0
    bg_dash_cap: str = "flat"  # "flat", "round", "square"

    # Background texture (overrides bg_color when non-empty)
    bg_texture_id: str = ""
    bg_texture_zoom: float = 1.0
    bg_texture_rotation: float = 0.0

    # Random waviness
    random: bool = False
    random_seed: int = field(default_factory=lambda: _random.randint(0, 999999))
    random_amplitude: float = 2.0  # Lower default than hexside (smoother curves)
    random_distance: float = 0.0  # Randomize subdivision point spacing (0=even, 1=max)
    random_endpoint: float = 0.0  # Endpoint displacement in world pixels
    random_jitter: float = 0.0  # Width jitter (0 = off, 1 = max)
    random_offset: float = 0.0  # Constant perpendicular offset of inner control points

    # Control points: perpendicular offsets at fixed t-positions along the segment
    # 4 points at t=0 (start center), t=1/3, t=2/3, t=1 (end center)
    # Note: cp[0] and cp[3] are ignored in rendering; ep_a/ep_b are used for endpoints.
    control_points: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    # Endpoint 2D offsets from base endpoint position (hex center ± random_endpoint displacement).
    # Allows fully free 2D movement in select mode and placement-time snapping.
    ep_a: list[float] = field(default_factory=lambda: [0.0, 0.0])  # offset at hex_a end
    ep_b: list[float] = field(default_factory=lambda: [0.0, 0.0])  # offset at hex_b end

    # Inner control point 2D offsets from the spine position at t≈1/3 and t≈2/3.
    # Replace the old scalar perpendicular offsets (control_points[1] and [2]) with
    # free 2D world-space offsets for full directional freedom.
    ip_a: list[float] = field(default_factory=lambda: [0.0, 0.0])  # inner point at t≈1/3
    ip_b: list[float] = field(default_factory=lambda: [0.0, 0.0])  # inner point at t≈2/3

    # Opacity (0.0 = transparent, 1.0 = opaque)
    opacity: float = 1.0      # foreground / main path
    bg_opacity: float = 1.0   # background path

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
        """Return the canonical key for this path segment."""
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
            if self.line_type == "dashed":
                data["dash_length"] = self.dash_length
            data["gap_length"] = self.gap_length
            if self.dash_cap != "flat":
                data["dash_cap"] = self.dash_cap
        if self.texture_id:
            data["texture_id"] = self.texture_id
            if self.texture_zoom != 1.0:
                data["texture_zoom"] = self.texture_zoom
            if self.texture_rotation != 0.0:
                data["texture_rotation"] = self.texture_rotation
        if self.bg_enabled:
            data["bg_enabled"] = True
            data["bg_color"] = self.bg_color
            data["bg_width"] = self.bg_width
            if self.bg_line_type != "solid":
                data["bg_line_type"] = self.bg_line_type
                if self.bg_line_type == "dashed":
                    data["bg_dash_length"] = self.bg_dash_length
                data["bg_gap_length"] = self.bg_gap_length
                if self.bg_dash_cap != "flat":
                    data["bg_dash_cap"] = self.bg_dash_cap
            if self.bg_texture_id:
                data["bg_texture_id"] = self.bg_texture_id
                if self.bg_texture_zoom != 1.0:
                    data["bg_texture_zoom"] = self.bg_texture_zoom
                if self.bg_texture_rotation != 0.0:
                    data["bg_texture_rotation"] = self.bg_texture_rotation
        data["random_seed"] = self.random_seed
        if self.random:
            data["random"] = True
            data["random_amplitude"] = self.random_amplitude
            if self.random_distance != 0.0:
                data["random_distance"] = self.random_distance
            if self.random_endpoint != 0.0:
                data["random_endpoint"] = self.random_endpoint
            if self.random_jitter != 0.0:
                data["random_jitter"] = self.random_jitter
        if self.random_offset != 0.0:
            data["random_offset"] = self.random_offset
        if self.opacity != 1.0:
            data["opacity"] = self.opacity
        if self.bg_opacity != 1.0:
            data["bg_opacity"] = self.bg_opacity
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
        return data

    @classmethod
    def deserialize(cls, data: dict) -> PathObject:
        cp_data = data.get("control_points")
        if cp_data is None:
            control_points = [0.0, 0.0, 0.0, 0.0]
        elif len(cp_data) == 4:
            control_points = list(cp_data)
        else:
            control_points = [0.0, 0.0, 0.0, 0.0]

        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            hex_a_q=data.get("hex_a_q", 0),
            hex_a_r=data.get("hex_a_r", 0),
            hex_b_q=data.get("hex_b_q", 0),
            hex_b_r=data.get("hex_b_r", 0),
            color=data.get("color", "#000000"),
            width=data.get("width", 3.0),
            line_type=data.get("line_type", "solid"),
            dash_length=data.get("dash_length", 6.0),
            gap_length=data.get("gap_length", 4.0),
            dash_cap=data.get("dash_cap", "flat"),
            texture_id=data.get("texture_id", ""),
            texture_zoom=data.get("texture_zoom", 1.0),
            texture_rotation=data.get("texture_rotation", 0.0),
            bg_enabled=data.get("bg_enabled", False),
            bg_color=data.get("bg_color", "#000000"),
            bg_width=data.get("bg_width", 6.0),
            bg_line_type=data.get("bg_line_type", "solid"),
            bg_dash_length=data.get("bg_dash_length", 6.0),
            bg_gap_length=data.get("bg_gap_length", 4.0),
            bg_dash_cap=data.get("bg_dash_cap", "flat"),
            bg_texture_id=data.get("bg_texture_id", ""),
            bg_texture_zoom=data.get("bg_texture_zoom", 1.0),
            bg_texture_rotation=data.get("bg_texture_rotation", 0.0),
            random=data.get("random", False),
            random_seed=data.get("random_seed", _random.randint(0, 999999)),
            random_amplitude=data.get("random_amplitude", 2.0),
            random_distance=data.get("random_distance", 0.0),
            random_endpoint=data.get("random_endpoint", 0.0),
            random_jitter=data.get("random_jitter", 0.0),
            random_offset=data.get("random_offset", 0.0),
            opacity=data.get("opacity", 1.0),
            bg_opacity=data.get("bg_opacity", 1.0),
            control_points=control_points,
            ep_a=list(data.get("ep_a", [0.0, 0.0])),
            ep_b=list(data.get("ep_b", [0.0, 0.0])),
            ip_a=list(data.get("ip_a", [0.0, 0.0])),
            ip_b=list(data.get("ip_b", [0.0, 0.0])),
        )
