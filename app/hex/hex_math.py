"""Hex coordinate math based on Red Blob Games reference.

Uses axial coordinates (q, r) internally. Supports both pointy-top
and flat-top orientations.

Reference: https://www.redblobgames.com/grids/hexagons/implementation.html
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Hex:
    """Axial hex coordinate."""
    q: int
    r: int

    @property
    def s(self) -> int:
        return -self.q - self.r

    def __hash__(self):
        return hash((self.q, self.r))

    def __eq__(self, other):
        if isinstance(other, Hex):
            return self.q == other.q and self.r == other.r
        return NotImplemented


@dataclass
class FractionalHex:
    """Fractional hex coordinate for intermediate calculations."""
    q: float
    r: float
    s: float


@dataclass(frozen=True)
class Orientation:
    """Forward (hex->pixel) and backward (pixel->hex) matrices."""
    f0: float
    f1: float
    f2: float
    f3: float
    b0: float
    b1: float
    b2: float
    b3: float
    start_angle: float  # in multiples of 60 degrees


POINTY_TOP = Orientation(
    f0=math.sqrt(3.0), f1=math.sqrt(3.0) / 2.0, f2=0.0, f3=3.0 / 2.0,
    b0=math.sqrt(3.0) / 3.0, b1=-1.0 / 3.0, b2=0.0, b3=2.0 / 3.0,
    start_angle=0.5,
)

FLAT_TOP = Orientation(
    f0=3.0 / 2.0, f1=0.0, f2=math.sqrt(3.0) / 2.0, f3=math.sqrt(3.0),
    b0=2.0 / 3.0, b1=0.0, b2=-1.0 / 3.0, b3=math.sqrt(3.0) / 3.0,
    start_angle=0.0,
)


@dataclass
class Layout:
    """Describes how hex coordinates map to pixel coordinates."""
    orientation: Orientation
    size_x: float  # horizontal radius
    size_y: float  # vertical radius
    origin_x: float = 0.0
    origin_y: float = 0.0


def hex_to_pixel(layout: Layout, h: Hex) -> tuple[float, float]:
    """Convert hex coordinate to pixel center position."""
    o = layout.orientation
    x = (o.f0 * h.q + o.f1 * h.r) * layout.size_x + layout.origin_x
    y = (o.f2 * h.q + o.f3 * h.r) * layout.size_y + layout.origin_y
    return x, y


def pixel_to_hex(layout: Layout, x: float, y: float) -> Hex:
    """Convert pixel position to the nearest hex coordinate."""
    o = layout.orientation
    px = (x - layout.origin_x) / layout.size_x
    py = (y - layout.origin_y) / layout.size_y
    q = o.b0 * px + o.b1 * py
    r = o.b2 * px + o.b3 * py
    return hex_round(FractionalHex(q, r, -q - r))


def hex_round(fh: FractionalHex) -> Hex:
    """Round fractional hex to nearest integer hex."""
    qi = round(fh.q)
    ri = round(fh.r)
    si = round(fh.s)

    q_diff = abs(qi - fh.q)
    r_diff = abs(ri - fh.r)
    s_diff = abs(si - fh.s)

    if q_diff > r_diff and q_diff > s_diff:
        qi = -ri - si
    elif r_diff > s_diff:
        ri = -qi - si

    return Hex(qi, ri)


def hex_corner_offset(layout: Layout, corner: int) -> tuple[float, float]:
    """Get the pixel offset of a hex corner (0-5) from hex center."""
    angle = 2.0 * math.pi * (layout.orientation.start_angle + corner) / 6.0
    return layout.size_x * math.cos(angle), layout.size_y * math.sin(angle)


def hex_corners(layout: Layout, h: Hex) -> List[tuple[float, float]]:
    """Get all 6 corner pixel positions of a hex."""
    cx, cy = hex_to_pixel(layout, h)
    corners = []
    for i in range(6):
        ox, oy = hex_corner_offset(layout, i)
        corners.append((cx + ox, cy + oy))
    return corners


# Hex directions (axial): E, NE, NW, W, SW, SE
HEX_DIRECTIONS = [
    Hex(1, 0), Hex(1, -1), Hex(0, -1),
    Hex(-1, 0), Hex(-1, 1), Hex(0, 1),
]


def hex_neighbor(h: Hex, direction: int) -> Hex:
    """Get the neighboring hex in the given direction (0-5)."""
    d = HEX_DIRECTIONS[direction]
    return Hex(h.q + d.q, h.r + d.r)


def hex_edge_key(
    hex_a: Hex, hex_b: Hex,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return a canonical key for the edge shared by two adjacent hexes.

    The key is a tuple of two (q, r) tuples, always ordered so that
    the first is lexicographically smaller.
    """
    a = (hex_a.q, hex_a.r)
    b = (hex_b.q, hex_b.r)
    if a > b:
        a, b = b, a
    return (a, b)


def hex_edge_vertices(
    layout: Layout, hex_coord: Hex, direction: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Get the two vertex positions of the edge in the given direction (0-5).

    Direction follows HEX_DIRECTIONS (E, NE, NW, W, SW, SE).
    Returns (vertex_a, vertex_b) as pixel coordinate tuples.
    """
    corners = hex_corners(layout, hex_coord)
    is_flat = layout.orientation.start_angle == 0.0
    if is_flat:
        ci = (-direction) % 6
    else:
        ci = (direction - 1) % 6
    return corners[ci], corners[(ci + 1) % 6]


def _point_to_segment_dist(
    px: float, py: float,
    ax: float, ay: float, bx: float, by: float,
) -> float:
    """Perpendicular distance from point (px, py) to segment (ax, ay)-(bx, by)."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def nearest_hex_edge(
    layout: Layout, hex_coord: Hex, world_x: float, world_y: float,
) -> tuple[int, float]:
    """Find the nearest edge of a hex to a world-space point.

    Returns (direction_index, distance).
    """
    best_dir = 0
    best_dist = float("inf")
    corners = hex_corners(layout, hex_coord)
    is_flat = layout.orientation.start_angle == 0.0

    for direction in range(6):
        if is_flat:
            ci = (-direction) % 6
        else:
            ci = (direction - 1) % 6
        ax, ay = corners[ci]
        bx, by = corners[(ci + 1) % 6]
        dist = _point_to_segment_dist(world_x, world_y, ax, ay, bx, by)
        if dist < best_dist:
            best_dist = dist
            best_dir = direction

    return best_dir, best_dist


def hex_distance(a: Hex, b: Hex) -> int:
    """Manhattan distance between two hexes."""
    return (abs(a.q - b.q) + abs(a.r - b.r) + abs(a.s - b.s)) // 2


def hex_in_grid(
    h: Hex, width: int, height: int,
    orientation: str = "pointy", first_row_offset: str = "even",
) -> bool:
    """Check if a hex is within a rectangular offset grid.

    For offset coordinates, we convert axial to offset and check bounds.
    orientation and first_row_offset must match the actual HexGridConfig.
    """
    col, row = axial_to_offset(h, first_row_offset=first_row_offset, orientation=orientation)
    return 0 <= col < width and 0 <= row < height


def offset_to_axial(
    col: int, row: int, first_row_offset: str = "even", orientation: str = "pointy",
) -> Hex:
    """Convert offset coordinates to axial.

    For pointy-top: uses odd-r / even-r offset (rows are shifted).
    For flat-top: uses odd-q / even-q offset (columns are shifted).
    """
    if orientation == "flat":
        q = col
        if first_row_offset == "odd":
            r = row - (col - (col & 1)) // 2
        else:
            r = row - (col + (col & 1)) // 2
    else:
        if first_row_offset == "odd":
            q = col - (row - (row & 1)) // 2
        else:
            q = col - (row + (row & 1)) // 2
        r = row
    return Hex(q, r)


def snap_to_grid(
    layout: Layout, world_x: float, world_y: float,
    width: int, height: int,
    orientation: str = "pointy",
    first_row_offset: str = "even",
) -> tuple[float, float]:
    """Snap a world point to the nearest hex center or hex corner.

    Collects the current hex center + 6 corners, plus neighbor centers
    and corners, and returns the closest candidate.
    """
    h = pixel_to_hex(layout, world_x, world_y)

    # Collect candidate snap points
    candidates: list[tuple[float, float]] = []

    # Current hex center + corners
    if hex_in_grid(h, width, height, orientation=orientation, first_row_offset=first_row_offset):
        candidates.append(hex_to_pixel(layout, h))
        candidates.extend(hex_corners(layout, h))

    # Neighbor hex centers + corners
    for d in range(6):
        nb = hex_neighbor(h, d)
        if hex_in_grid(nb, width, height, orientation=orientation, first_row_offset=first_row_offset):
            candidates.append(hex_to_pixel(layout, nb))
            candidates.extend(hex_corners(layout, nb))

    if not candidates:
        return (world_x, world_y)

    best_x, best_y = candidates[0]
    best_dist = (best_x - world_x) ** 2 + (best_y - world_y) ** 2
    for cx, cy in candidates[1:]:
        d = (cx - world_x) ** 2 + (cy - world_y) ** 2
        if d < best_dist:
            best_dist = d
            best_x, best_y = cx, cy

    return (best_x, best_y)


def axial_to_offset(
    h: Hex, first_row_offset: str = "even", orientation: str = "pointy",
) -> tuple[int, int]:
    """Convert axial coordinates to offset (col, row).

    For pointy-top: uses odd-r / even-r offset.
    For flat-top: uses odd-q / even-q offset.
    """
    if orientation == "flat":
        col = h.q
        if first_row_offset == "odd":
            row = h.r + (h.q - (h.q & 1)) // 2
        else:
            row = h.r + (h.q + (h.q & 1)) // 2
    else:
        if first_row_offset == "odd":
            col = h.q + (h.r - (h.r & 1)) // 2
        else:
            col = h.q + (h.r + (h.r & 1)) // 2
        row = h.r
    return col, row
