"""Save and load .hexmap project files."""

from __future__ import annotations

import json
import os

from app.hex.hex_grid_config import HexGridConfig
from app.io.user_data import get_builtin_assets_dir
from app.layers.asset_layer import AssetLayer
from app.layers.background_layer import BackgroundImageLayer
from app.layers.border_layer import BorderLayer
from app.layers.draw_layer import DrawLayer
from app.layers.fill_layer import FillLayer
from app.layers.freeform_path_layer import FreeformPathLayer
from app.layers.hexside_layer import HexsideLayer
from app.layers.path_layer import PathLayer
from app.layers.sketch_layer import SketchLayer
from app.layers.text_layer import TextLayer
from app.models.project import Project


LAYER_TYPES = {
    "fill": FillLayer,
    "asset": AssetLayer,
    "background": BackgroundImageLayer,
    "border": BorderLayer,
    "draw": DrawLayer,
    "text": TextLayer,
    "hexside": HexsideLayer,
    "path": PathLayer,
    "freeform_path": FreeformPathLayer,
    "sketch": SketchLayer,
}

# Prefix for built-in asset references (stable across PyInstaller sessions)
_BUILTIN_PREFIX = "builtin:"


def _is_under(path: str, parent: str) -> bool:
    """Check if *path* is inside *parent* directory (case-insensitive on Windows)."""
    try:
        np = os.path.normcase(os.path.normpath(path))
        pp = os.path.normcase(os.path.normpath(parent))
        return np.startswith(pp + os.sep) or np == pp
    except (ValueError, TypeError):
        return False


def save_project(project: Project, file_path: str) -> None:
    project_dir = os.path.dirname(os.path.abspath(file_path))
    builtin_dir = get_builtin_assets_dir()

    # Pass project_dir to background layers so they can save edited PNGs
    for layer in project.layer_stack:
        if isinstance(layer, BackgroundImageLayer):
            layer.project_dir = project_dir

    layer_dicts = []
    for layer in project.layer_stack:
        d = layer.serialize()
        # Relativize file paths for portability
        if d.get("type") == "asset":
            for obj in d.get("objects", []):
                img = obj.get("image", "")
                if not img:
                    continue
                # Built-in assets: store as "builtin:<relative>" so the path
                # survives PyInstaller temp-dir changes between sessions.
                if builtin_dir and _is_under(img, builtin_dir):
                    rel = os.path.relpath(img, builtin_dir).replace("\\", "/")
                    obj["image"] = _BUILTIN_PREFIX + rel
                elif os.path.isabs(img):
                    try:
                        obj["image"] = os.path.relpath(img, project_dir)
                    except ValueError:
                        pass  # different drive on Windows
        elif d.get("type") == "background":
            img = d.get("image_path", "")
            if img and os.path.isabs(img):
                try:
                    d["image_path"] = os.path.relpath(img, project_dir)
                except ValueError:
                    pass
        layer_dicts.append(d)

    data = {
        "version": 1,
        "grid": project.grid_config.serialize(),
        "layers": layer_dicts,
    }

    # Atomic write: use a temp file then replace to avoid corrupting the
    # project file if the process is interrupted during writing.
    tmp_path = file_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, file_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    project.file_path = file_path
    project.dirty = False


def _resolve_asset_image(img: str, base_dir: str, builtin_dir: str | None) -> str:
    """Resolve an asset image path from a project file.

    Handles three cases:
    1. ``builtin:rel/path.png`` — resolve against current built-in assets dir.
    2. Relative path — resolve against project base_dir.
    3. Absolute path that no longer exists — attempt to recover old _MEI* paths
       by looking for ``assets/assets/`` in the path and re-rooting.
    """
    # Case 1: explicit builtin reference
    if img.startswith(_BUILTIN_PREFIX):
        rel = img[len(_BUILTIN_PREFIX):]
        if builtin_dir:
            return os.path.normpath(os.path.join(builtin_dir, rel))
        return img  # can't resolve, keep as-is

    # Case 2: relative path
    if not os.path.isabs(img):
        return os.path.normpath(os.path.join(base_dir, img))

    # Case 3: absolute path — if it already exists, keep it
    if os.path.isfile(img):
        return img

    # Backward compat: try to recover old PyInstaller _MEI* paths.
    # They look like: C:\...\Temp\_MEIxxxxx\assets\assets\game\file.png
    if builtin_dir:
        for marker in ("/assets/assets/", "\\assets\\assets\\"):
            idx = img.find(marker)
            if idx >= 0:
                rel = img[idx + len(marker):]
                candidate = os.path.join(builtin_dir, rel)
                if os.path.isfile(candidate):
                    return candidate

    return img  # give up, keep original


def load_project(file_path: str) -> Project:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    project = Project()
    project.grid_config = HexGridConfig.deserialize(data.get("grid", {}))

    base_dir = os.path.dirname(os.path.abspath(file_path))
    builtin_dir = get_builtin_assets_dir()

    for layer_data in data.get("layers", []):
        if not isinstance(layer_data, dict):
            continue
        layer_type = layer_data.get("type", "")
        cls = LAYER_TYPES.get(layer_type)
        if cls is None:
            continue

        # Resolve image paths
        if layer_type == "asset":
            for obj in layer_data.get("objects", []):
                img = obj.get("image", "")
                if img:
                    obj["image"] = _resolve_asset_image(img, base_dir, builtin_dir)
        elif layer_type == "background":
            img = layer_data.get("image_path", "")
            if img and not os.path.isabs(img):
                layer_data["image_path"] = os.path.normpath(
                    os.path.join(base_dir, img)
                )
            edit_img = layer_data.get("edited_image_path", "")
            if edit_img and not os.path.isabs(edit_img):
                layer_data["edited_image_path"] = os.path.normpath(
                    os.path.join(base_dir, edit_img)
                )

        layer = cls.deserialize(layer_data)
        project.layer_stack.add_layer(layer)

    project.file_path = file_path
    project.dirty = False
    return project
