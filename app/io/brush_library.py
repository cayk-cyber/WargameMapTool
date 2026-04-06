"""Brush library - import, catalog, and manage brush stamp PNGs in AppData."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field

from app.io.user_data import get_builtin_brushes_dir, get_user_brushes_dir

# In-memory catalog cache with version counter.
_cached_catalog: BrushCatalog | None = None
_catalog_version: int = 0


def get_catalog_version() -> int:
    """Return the current catalog version (incremented on every mutation)."""
    return _catalog_version


def _invalidate_cache() -> None:
    """Mark the cached catalog as stale so the next load_catalog() re-reads disk."""
    global _cached_catalog, _catalog_version
    _cached_catalog = None
    _catalog_version += 1


@dataclass
class LibraryBrush:
    """A single brush entry in the catalog."""

    id: str
    filename: str  # stored name in brushes dir
    display_name: str
    category: str = "Uncategorized"
    builtin: bool = False  # True if from built-in brushes dir (read-only)

    def file_path(self) -> str:
        """Return the full path to the brush file."""
        if self.builtin:
            builtin_dir = get_builtin_brushes_dir()
            if builtin_dir:
                return os.path.join(builtin_dir, self.filename)
        return os.path.join(get_user_brushes_dir(), self.filename)

    def exists(self) -> bool:
        """Check if the brush file exists on disk."""
        return os.path.isfile(self.file_path())


@dataclass
class BrushCatalog:
    """Collection of library brushes with serialization."""

    brushes: list[LibraryBrush] = field(default_factory=list)

    def serialize(self) -> dict:
        return {
            "brushes": [
                {
                    "id": b.id,
                    "filename": b.filename,
                    "display_name": b.display_name,
                    "category": b.category,
                }
                for b in self.brushes
            ]
        }

    @classmethod
    def deserialize(cls, data: dict) -> BrushCatalog:
        brushes = []
        for entry in data.get("brushes", []):
            brushes.append(
                LibraryBrush(
                    id=entry["id"],
                    filename=entry["filename"],
                    display_name=entry.get("display_name", entry["filename"]),
                    category=entry.get("category", "Uncategorized"),
                )
            )
        return cls(brushes=brushes)

    def find_by_id(self, brush_id: str) -> LibraryBrush | None:
        """Find a brush by its ID."""
        for brush in self.brushes:
            if brush.id == brush_id:
                return brush
        return None

    def categories(self) -> list[str]:
        """Return sorted list of unique categories."""
        cats = set()
        for b in self.brushes:
            cats.add(b.category)
        return sorted(cats)


def _catalog_path() -> str:
    """Return path to user catalog.json."""
    return os.path.join(get_user_brushes_dir(), "catalog.json")


def load_catalog() -> BrushCatalog:
    """Load the brush catalog from disk, merging built-in and user brushes.

    Results are cached in memory.  The cache is invalidated automatically
    by any mutation function (import, delete).
    """
    global _cached_catalog
    if _cached_catalog is not None:
        return _cached_catalog

    # Load user catalog
    user_path = _catalog_path()
    if os.path.isfile(user_path):
        with open(user_path, "r", encoding="utf-8") as f:
            user_catalog = BrushCatalog.deserialize(json.load(f))
    else:
        user_catalog = BrushCatalog()

    # Collect user IDs for shadowing
    user_ids = {b.id for b in user_catalog.brushes}

    # Load built-in catalog
    builtin_dir = get_builtin_brushes_dir()
    if builtin_dir:
        builtin_catalog_path = os.path.join(builtin_dir, "catalog.json")
        if os.path.isfile(builtin_catalog_path):
            with open(builtin_catalog_path, "r", encoding="utf-8") as f:
                builtin_catalog = BrushCatalog.deserialize(json.load(f))
            for b in builtin_catalog.brushes:
                if b.id not in user_ids:
                    b.builtin = True
                    user_catalog.brushes.append(b)

    _cached_catalog = user_catalog
    return user_catalog


def save_catalog(catalog: BrushCatalog) -> None:
    """Save the user brush catalog to disk (excludes built-in brushes)."""
    user_only = BrushCatalog(
        brushes=[b for b in catalog.brushes if not b.builtin],
    )
    path = _catalog_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(user_only.serialize(), f, indent=2, ensure_ascii=False)
    _invalidate_cache()


def import_brush(
    source_path: str,
    display_name: str,
    category: str = "Uncategorized",
) -> LibraryBrush:
    """Import a PNG file into the brush library.

    Copies the file to the brushes directory with a UUID-prefixed name
    and adds it to the catalog.
    """
    catalog = load_catalog()

    brush_id = uuid.uuid4().hex[:8]
    ext = os.path.splitext(source_path)[1].lower()
    stored_name = f"{brush_id}_{display_name}{ext}"
    stored_name = stored_name.replace(" ", "_")

    dest_path = os.path.join(get_user_brushes_dir(), stored_name)
    shutil.copy2(source_path, dest_path)

    brush = LibraryBrush(
        id=brush_id,
        filename=stored_name,
        display_name=display_name,
        category=category,
    )
    catalog.brushes.append(brush)
    save_catalog(catalog)
    return brush


def delete_brush(brush_id: str) -> None:
    """Delete a brush from the catalog and remove its file.

    Built-in brushes cannot be deleted.
    """
    catalog = load_catalog()
    brush = catalog.find_by_id(brush_id)
    if not brush or brush.builtin:
        return

    path = brush.file_path()
    if os.path.isfile(path):
        os.remove(path)

    catalog.brushes = [b for b in catalog.brushes if b.id != brush_id]
    save_catalog(catalog)


def is_builtin_brush(brush_id: str) -> bool:
    """Check if a brush ID belongs to a built-in brush."""
    catalog = load_catalog()
    brush = catalog.find_by_id(brush_id)
    return brush is not None and brush.builtin
