"""Module-level brush stamp cache with programmatic round-brush generation."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtGui import QColor, QImage

from app.io.brush_library import load_catalog

# Built-in brush IDs that are generated programmatically from a hardness value
# instead of being loaded from their PNG file.
_ROUND_BRUSH_IDS = {"round_soft", "round_hard"}

# Extra diameter added to round-brush stamps (= 2 px extra radius each side).
# The fringe ensures that even the very edge of a hard-brush stamp slightly
# overlaps neighbouring stamps, eliminating the scalloped/beaded artefact that
# would otherwise appear at the nominal brush radius.
_ROUND_FRINGE_PX: int = 4

# Gaussian sigma range for the soft-zone (fringe beyond the hard inner zone).
# At hardness=0: sigma = _SIGMA_SOFT (wide, gentle falloff)
# At hardness=1: sigma = _SIGMA_HARD (very narrow, almost-instant dropoff → crisp edge)
_SIGMA_SOFT: float = 0.40
_SIGMA_HARD: float = 0.15

# Cache key: (brush_id, nominal_size_px, hardness_level 0-20)
_cache: dict[tuple[str, int, int], QImage] = {}
_MAX_CACHE_ENTRIES = 256  # L19: cap memory usage (256 stamps ≈ a few MB)


def get_stamp_draw_size(brush_id: str, brush_size: float) -> float:
    """Return the world-space draw diameter for a brush stamp.

    Round brushes add a fringe beyond the nominal radius so that adjacent
    stamps always overlap → no scalloping at the nominal brush edge.
    PNG brushes draw at exactly brush_size.
    """
    if brush_id in _ROUND_BRUSH_IDS:
        return brush_size + _ROUND_FRINGE_PX
    return brush_size


def get_brush_stamp(
    brush_id: str, size_px: int, hardness: float
) -> QImage | None:
    """Return a cached brush stamp at the given pixel size.

    For built-in round brushes (round_soft, round_hard) the stamp is
    generated mathematically from the hardness value:
      0.0 = pure gradient from center to edge (maximum softness)
      1.0 = nearly hard circular edge (very narrow transition zone)

    For all other brushes the PNG is loaded as-is; hardness is ignored.

    Returns a QImage in ARGB32_Premultiplied format (white pixels, varying alpha).
    """
    hardness_level = max(0, min(20, round(hardness * 20)))
    size_px = max(1, size_px)
    key = (brush_id, size_px, hardness_level)

    if key in _cache:
        return _cache[key]

    if brush_id in _ROUND_BRUSH_IDS:
        stamp = _generate_round_brush(size_px, hardness)
    else:
        stamp = _load_png_brush(brush_id, size_px)

    if stamp is not None:
        if len(_cache) >= _MAX_CACHE_ENTRIES:  # L19: evict oldest entry to cap memory
            _cache.pop(next(iter(_cache)))
        _cache[key] = stamp
    return stamp


def _generate_round_brush(nominal_px: int, hardness: float) -> QImage:
    """Generate a round brush stamp with pixel-perfect Gaussian falloff.

    The returned image is (nominal_px + _ROUND_FRINGE_PX) × (…) pixels.
    It should be drawn at world size get_stamp_draw_size(id, nominal_px).

    Peak alpha is always 1.0 (fully opaque centre).
    Hardness controls only the width of the soft transition zone:
      0.0 = Gaussian spans the full stamp radius (maximum softness)
      1.0 = hard edge at nominal radius + 2 px anti-alias fringe only

    With CompositionMode_Lighten (MAX) a single stroke never exceeds 1.0.
    Multiple strokes accumulate via SourceOver in the composite.

    Alpha is computed pixel-by-pixel (not via QRadialGradient) for a
    mathematically exact profile — no gradient-stop approximation artefacts.
    """
    stamp_px = nominal_px + _ROUND_FRINGE_PX
    nominal_r = nominal_px / 2.0
    stamp_r = stamp_px / 2.0
    cx = cy = stamp_px / 2.0

    # Build coordinate grids vectorized — avoids per-pixel Python loop
    xs = np.arange(stamp_px, dtype=np.float32) - cx
    ys = np.arange(stamp_px, dtype=np.float32) - cy
    xx, yy = np.meshgrid(xs, ys)  # shape: (stamp_px, stamp_px)
    dist = np.hypot(xx, yy)  # absolute distance from centre

    if hardness >= 1.0:
        # Perfect hard circle at nominal radius with 1px anti-aliasing.
        # Signed-distance-field technique: alpha = clamp(nominal_r + 0.5 - dist).
        alpha_f = np.clip(nominal_r + 0.5 - dist, 0.0, 1.0).astype(np.float32)
    else:
        t = dist / stamp_r  # normalized distance from centre

        # Inner zone: flat peak up to inner_frac of stamp radius
        inner_frac = hardness * (nominal_r / stamp_r)
        inner_frac = max(0.0, min(0.998, inner_frac))

        # Sigma interpolates between hard (sharp fringe) and soft (wide fringe)
        sigma = _SIGMA_HARD + (1.0 - hardness) * (_SIGMA_SOFT - _SIGMA_HARD)

        # Compute alpha for each pixel
        alpha_f = np.zeros(t.shape, dtype=np.float32)

        inside_mask = t < 1.0
        hard_mask = inside_mask & (t <= inner_frac)
        soft_mask = inside_mask & ~hard_mask

        # Hard inner zone: fully opaque
        alpha_f[hard_mask] = 1.0

        # Soft fringe: Gaussian falloff
        if inner_frac < 0.998:
            t_norm = (t[soft_mask] - inner_frac) / (1.0 - inner_frac)
            alpha_f[soft_mask] = np.exp(-0.5 * (t_norm / sigma) ** 2)

    # Convert to uint8 alpha channel
    alpha_u8 = np.clip(np.round(alpha_f * 255), 0, 255).astype(np.uint8)

    # Build ARGB32_Premultiplied pixel values: R=G=B=A (white stamp)
    # Pack as uint32 in row-major order for QImage
    a32 = alpha_u8.astype(np.uint32)
    pixels = (a32 << 24) | (a32 << 16) | (a32 << 8) | a32  # shape: (stamp_px, stamp_px)

    # Write pixels into QImage via scanline bytes
    img = QImage(stamp_px, stamp_px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))

    # pixels is in row-major (y, x) order — copy row by row using tobytes()
    pixels_c = np.ascontiguousarray(pixels)
    for row in range(stamp_px):
        row_bytes = pixels_c[row].tobytes()
        bits = img.scanLine(row)
        bits[:len(row_bytes)] = row_bytes

    return img


def _load_png_brush(brush_id: str, size_px: int) -> QImage | None:
    """Load a brush from the library PNG, scaled to size_px."""
    catalog = load_catalog()
    brush = catalog.find_by_id(brush_id)
    if brush is None or not brush.exists():
        return None

    raw = QImage(brush.file_path())
    if raw.isNull():
        return None

    scaled = raw.scaled(size_px, size_px)
    return scaled.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def invalidate(brush_id: str | None = None) -> None:
    """Clear cached stamp(s).

    If brush_id is given, removes only entries for that brush.
    If None, clears the entire cache.
    """
    if brush_id is None:
        _cache.clear()
    else:
        keys_to_remove = [k for k in _cache if k[0] == brush_id]
        for k in keys_to_remove:
            del _cache[k]
