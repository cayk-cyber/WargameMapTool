"""Asset library - import, catalog, and manage image assets in AppData."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field

from app.io.user_data import get_builtin_assets_dir, get_user_assets_dir

_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# In-memory catalog cache with version counter.
# Version is incremented on every mutation (import, delete, rename, ...).
# Callers can use get_catalog_version() to detect changes cheaply.
_cached_catalog: AssetCatalog | None = None
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
class LibraryAsset:
    """A single asset entry in the catalog."""

    id: str
    filename: str  # stored name in assets dir
    display_name: str
    category: str = "Uncategorized"
    game: str = ""
    builtin: bool = False  # runtime only, not serialized

    def file_path(self) -> str:
        """Return the full path to the asset file."""
        if self.builtin:
            builtin_dir = get_builtin_assets_dir()
            if builtin_dir:
                return os.path.join(builtin_dir, self.filename)
        return os.path.join(get_user_assets_dir(), self.filename)

    def exists(self) -> bool:
        """Check if the asset file exists on disk."""
        return os.path.isfile(self.file_path())


@dataclass
class AssetCatalog:
    """Collection of library assets with serialization."""

    assets: list[LibraryAsset] = field(default_factory=list)

    def serialize(self) -> dict:
        return {
            "assets": [
                {
                    "id": a.id,
                    "filename": a.filename,
                    "display_name": a.display_name,
                    "category": a.category,
                    "game": a.game,
                }
                for a in self.assets
            ]
        }

    @classmethod
    def deserialize(cls, data: dict) -> AssetCatalog:
        assets = []
        for entry in data.get("assets", []):
            assets.append(
                LibraryAsset(
                    id=entry["id"],
                    filename=entry["filename"],
                    display_name=entry.get("display_name", entry["filename"]),
                    category=entry.get("category", "Uncategorized"),
                    game=entry.get("game", ""),
                )
            )
        return cls(assets=assets)

    def find_by_id(self, asset_id: str) -> LibraryAsset | None:
        """Find an asset by its ID."""
        for asset in self.assets:
            if asset.id == asset_id:
                return asset
        return None

    def categories(self) -> list[str]:
        """Return sorted list of unique categories."""
        cats = set()
        for a in self.assets:
            cats.add(a.category)
        return sorted(cats)

    def games(self) -> list[str]:
        """Return sorted list of unique game names (excluding empty)."""
        games = set()
        for a in self.assets:
            if a.game:
                games.add(a.game)
        return sorted(games)


def _catalog_path() -> str:
    """Return path to catalog.json."""
    return os.path.join(get_user_assets_dir(), "catalog.json")


def _parse_asset_filename(filename: str) -> tuple[str, str, str] | None:
    """Parse a filename with convention game_category_displayname.ext.

    Returns (game, category, display_name) or None if filename doesn't match.
    """
    base = os.path.splitext(filename)[0]
    parts = base.split("_", 2)
    if len(parts) < 3:
        return None
    game, category, raw_name = parts
    display_name = raw_name.replace("_", " ")
    return (game, category, display_name)


def _scan_builtin_assets() -> list[LibraryAsset]:
    """Scan the built-in assets directory for asset files (recursively)."""
    builtin_dir = get_builtin_assets_dir()
    if not builtin_dir:
        return []

    assets: list[LibraryAsset] = []
    for dirpath, _dirnames, filenames in os.walk(builtin_dir):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _ASSET_EXTENSIONS:
                continue
            parsed = _parse_asset_filename(fname)
            if parsed is None:
                continue
            game, category, display_name = parsed
            # Use relative path so subdirectory assets get unique, stable IDs
            rel_path = os.path.relpath(os.path.join(dirpath, fname), builtin_dir)
            rel_path = rel_path.replace("\\", "/")
            asset_id = hashlib.sha256(rel_path.encode()).hexdigest()[:8]
            assets.append(LibraryAsset(
                id=asset_id,
                filename=rel_path,
                display_name=display_name,
                category=category,
                game=game,
                builtin=True,
            ))
    return assets


def load_catalog() -> AssetCatalog:
    """Load the asset catalog from disk, merged with built-in assets.

    Results are cached in memory.  The cache is invalidated automatically
    by any mutation function (import, delete, rename, ...).
    """
    global _cached_catalog
    if _cached_catalog is not None:
        return _cached_catalog

    path = _catalog_path()
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        catalog = AssetCatalog.deserialize(data)
    else:
        catalog = AssetCatalog()

    # Merge built-in assets
    builtin = _scan_builtin_assets()
    existing_ids = {a.id for a in catalog.assets}
    for asset in builtin:
        if asset.id not in existing_ids:
            catalog.assets.append(asset)

    _cached_catalog = catalog
    return catalog


def save_catalog(catalog: AssetCatalog) -> None:
    """Save the asset catalog to disk (only user assets, not built-in)."""
    # Filter out built-in assets before saving
    user_only = AssetCatalog(
        assets=[a for a in catalog.assets if not a.builtin]
    )
    path = _catalog_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(user_only.serialize(), f, indent=2, ensure_ascii=False)
    _invalidate_cache()


def _sanitize_part(text: str) -> str:
    """Sanitize a string for use in the filename convention (no underscores)."""
    text = text.strip()
    # Remove chars that aren't alphanumeric, space, or dash
    text = re.sub(r"[^\w\s-]", "", text)
    # Replace spaces with underscores
    text = text.replace(" ", "_")
    # Collapse multiple underscores
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "Unknown"


def import_asset(
    source_path: str,
    display_name: str,
    category: str = "Uncategorized",
    game: str = "",
) -> LibraryAsset:
    """Import an image file into the asset library.

    Copies the file to the assets directory using the naming convention
    game_category_name.ext and adds it to the catalog.
    """
    catalog = load_catalog()

    asset_id = uuid.uuid4().hex[:8]
    ext = os.path.splitext(source_path)[1].lower()

    # Build filename with convention: game_category_name.ext
    game_part = _sanitize_part(game) if game else "General"
    cat_part = _sanitize_part(category)
    name_part = _sanitize_part(display_name)
    stored_name = f"{game_part}_{cat_part}_{name_part}{ext}"

    # Handle collision: append _2, _3 etc.
    dest_dir = get_user_assets_dir()
    dest_path = os.path.join(dest_dir, stored_name)
    if os.path.exists(dest_path):
        counter = 2
        while True:
            stored_name = f"{game_part}_{cat_part}_{name_part}_{counter}{ext}"
            dest_path = os.path.join(dest_dir, stored_name)
            if not os.path.exists(dest_path):
                break
            counter += 1

    try:
        shutil.copy2(source_path, dest_path)
    except OSError as exc:
        raise OSError(f"Failed to copy asset to library: {exc}") from exc

    asset = LibraryAsset(
        id=asset_id,
        filename=stored_name,
        display_name=display_name,
        category=category,
        game=game,
    )
    # Only update the catalog after the file was successfully copied
    catalog.assets.append(asset)
    save_catalog(catalog)
    return asset


def rename_asset(asset_id: str, new_name: str) -> None:
    """Rename an asset's display name."""
    catalog = load_catalog()
    asset = catalog.find_by_id(asset_id)
    if asset:
        asset.display_name = new_name
        save_catalog(catalog)


def set_asset_category(asset_id: str, category: str) -> None:
    """Set an asset's category."""
    catalog = load_catalog()
    asset = catalog.find_by_id(asset_id)
    if asset:
        asset.category = category
        save_catalog(catalog)


def set_asset_game(asset_id: str, game: str) -> None:
    """Set an asset's game."""
    catalog = load_catalog()
    asset = catalog.find_by_id(asset_id)
    if asset:
        asset.game = game
        save_catalog(catalog)


def delete_asset(asset_id: str) -> None:
    """Delete an asset from the catalog and remove its file."""
    catalog = load_catalog()
    asset = catalog.find_by_id(asset_id)
    if not asset or asset.builtin:
        return

    # Remove file
    path = asset.file_path()
    if os.path.isfile(path):
        os.remove(path)

    # Remove from catalog
    catalog.assets = [a for a in catalog.assets if a.id != asset_id]
    save_catalog(catalog)


def is_builtin_asset(asset_id: str) -> bool:
    """Check if an asset is a built-in asset."""
    catalog = load_catalog()
    asset = catalog.find_by_id(asset_id)
    return asset.builtin if asset else False
