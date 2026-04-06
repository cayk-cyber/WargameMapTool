"""Texture library - import, catalog, and manage texture images in AppData."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field

from app.io.user_data import get_builtin_textures_dir, get_user_textures_dir

# In-memory catalog cache with version counter.
_cached_catalog: TextureCatalog | None = None
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
class LibraryTexture:
    """A single texture entry in the catalog."""

    id: str
    filename: str  # stored name in textures dir (e.g. "a1b2c3d4_grass.png")
    display_name: str
    category: str = "Uncategorized"
    game: str = ""
    builtin: bool = False  # True if from built-in textures dir (read-only)

    def file_path(self) -> str:
        """Return the full path to the texture file."""
        if self.builtin:
            builtin_dir = get_builtin_textures_dir()
            if builtin_dir:
                return os.path.join(builtin_dir, self.filename)
        return os.path.join(get_user_textures_dir(), self.filename)

    def exists(self) -> bool:
        """Check if the texture file exists on disk."""
        return os.path.isfile(self.file_path())


@dataclass
class TextureCatalog:
    """Collection of library textures with serialization."""

    textures: list[LibraryTexture] = field(default_factory=list)

    def serialize(self) -> dict:
        return {
            "textures": [
                {
                    "id": t.id,
                    "filename": t.filename,
                    "display_name": t.display_name,
                    "category": t.category,
                    "game": t.game,
                }
                for t in self.textures
            ]
        }

    @classmethod
    def deserialize(cls, data: dict) -> TextureCatalog:
        textures = []
        for entry in data.get("textures", []):
            textures.append(
                LibraryTexture(
                    id=entry["id"],
                    filename=entry["filename"],
                    display_name=entry.get("display_name", entry["filename"]),
                    category=entry.get("category", "Uncategorized"),
                    game=entry.get("game", ""),
                )
            )
        return cls(textures=textures)

    def find_by_id(self, texture_id: str) -> LibraryTexture | None:
        """Find a texture by its ID."""
        for texture in self.textures:
            if texture.id == texture_id:
                return texture
        return None

    def categories(self) -> list[str]:
        """Return sorted list of unique categories."""
        cats = set()
        for t in self.textures:
            cats.add(t.category)
        return sorted(cats)

    def games(self) -> list[str]:
        """Return sorted list of unique game names (excluding empty)."""
        games = set()
        for t in self.textures:
            if t.game:
                games.add(t.game)
        return sorted(games)


def _catalog_path() -> str:
    """Return path to catalog.json."""
    return os.path.join(get_user_textures_dir(), "catalog.json")


def load_catalog() -> TextureCatalog:
    """Load the texture catalog from disk, merging built-in and user textures.

    Results are cached in memory.  The cache is invalidated automatically
    by any mutation function (import, delete, rename, ...).
    """
    global _cached_catalog
    if _cached_catalog is not None:
        return _cached_catalog

    # Load user catalog
    user_path = _catalog_path()
    if os.path.isfile(user_path):
        with open(user_path, "r", encoding="utf-8") as f:
            user_catalog = TextureCatalog.deserialize(json.load(f))
    else:
        user_catalog = TextureCatalog()

    # Collect user IDs for shadowing
    user_ids = {t.id for t in user_catalog.textures}

    # Load built-in catalog(s): root + all subdirectory catalogs
    builtin_dir = get_builtin_textures_dir()
    if builtin_dir:
        for dirpath, _dirnames, filenames in os.walk(builtin_dir):
            if "catalog.json" not in filenames:
                continue
            cat_path = os.path.join(dirpath, "catalog.json")
            rel_dir = os.path.relpath(dirpath, builtin_dir).replace("\\", "/")
            with open(cat_path, "r", encoding="utf-8") as f:
                sub_catalog = TextureCatalog.deserialize(json.load(f))
            for t in sub_catalog.textures:
                if t.id in user_ids:
                    continue
                # Prepend subdir so file_path() resolves correctly
                if rel_dir != ".":
                    t.filename = f"{rel_dir}/{t.filename}"
                t.builtin = True
                user_catalog.textures.append(t)

    _cached_catalog = user_catalog
    return user_catalog


def save_catalog(catalog: TextureCatalog) -> None:
    """Save the user texture catalog to disk (excludes built-in textures)."""
    user_only = TextureCatalog(
        textures=[t for t in catalog.textures if not t.builtin],
    )
    path = _catalog_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(user_only.serialize(), f, indent=2, ensure_ascii=False)
    _invalidate_cache()


def import_texture(
    source_path: str,
    display_name: str,
    category: str = "Uncategorized",
    game: str = "",
) -> LibraryTexture:
    """Import an image file into the texture library.

    Copies the file to the textures directory with a UUID-prefixed name
    and adds it to the catalog.
    """
    catalog = load_catalog()

    texture_id = uuid.uuid4().hex[:8]
    ext = os.path.splitext(source_path)[1].lower()
    # L09: sanitize display_name to remove Windows-invalid filename characters
    _safe_display = display_name
    for _ch in r'<>:"/\|?*':
        _safe_display = _safe_display.replace(_ch, "_")
    stored_name = f"{texture_id}_{_safe_display}{ext}"
    stored_name = stored_name.replace(" ", "_")

    dest_path = os.path.join(get_user_textures_dir(), stored_name)
    shutil.copy2(source_path, dest_path)

    texture = LibraryTexture(
        id=texture_id,
        filename=stored_name,
        display_name=display_name,
        category=category,
        game=game,
    )
    catalog.textures.append(texture)
    save_catalog(catalog)
    return texture


def rename_texture(texture_id: str, new_name: str) -> None:
    """Rename a texture's display name."""
    catalog = load_catalog()
    texture = catalog.find_by_id(texture_id)
    if texture:
        texture.display_name = new_name
        save_catalog(catalog)


def set_texture_category(texture_id: str, category: str) -> None:
    """Set a texture's category."""
    catalog = load_catalog()
    texture = catalog.find_by_id(texture_id)
    if texture:
        texture.category = category
        save_catalog(catalog)


def set_texture_game(texture_id: str, game: str) -> None:
    """Set a texture's game."""
    catalog = load_catalog()
    texture = catalog.find_by_id(texture_id)
    if texture:
        texture.game = game
        save_catalog(catalog)


def delete_texture(texture_id: str) -> None:
    """Delete a texture from the catalog and remove its file.

    Built-in textures cannot be deleted.
    """
    catalog = load_catalog()
    texture = catalog.find_by_id(texture_id)
    if not texture or texture.builtin:
        return

    path = texture.file_path()
    if os.path.isfile(path):
        os.remove(path)

    catalog.textures = [t for t in catalog.textures if t.id != texture_id]
    save_catalog(catalog)
