"""Module-level texture image cache to avoid repeated disk loads."""

from __future__ import annotations

from PySide6.QtGui import QImage

from app.io.texture_library import load_catalog

# texture_id -> QImage  (None sentinel means "known missing, don't re-check disk")
_cache: dict[str, QImage | None] = {}


def get_texture_image(texture_id: str) -> QImage | None:
    """Load a texture image by catalog ID, with caching.

    Returns None if the texture is not found or cannot be loaded.
    """
    if texture_id in _cache:
        return _cache[texture_id]  # may be None sentinel (L18: cache misses too)

    catalog = load_catalog()
    texture = catalog.find_by_id(texture_id)
    if texture is None or not texture.exists():
        _cache[texture_id] = None  # L18: cache the miss to avoid repeated disk reads
        return None

    image = QImage(texture.file_path())
    if image.isNull():
        _cache[texture_id] = None  # L18: cache unreadable files too
        return None

    _cache[texture_id] = image
    return image


def invalidate(texture_id: str | None = None) -> None:
    """Clear cached image(s).

    If texture_id is given, removes only that entry.
    If None, clears the entire cache.
    """
    if texture_id is None:
        _cache.clear()
    else:
        _cache.pop(texture_id, None)
