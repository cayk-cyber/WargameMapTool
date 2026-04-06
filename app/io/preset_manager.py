"""Grid config preset management - save/load/delete presets."""

from __future__ import annotations

import json
import os

from app.hex.hex_grid_config import HexGridConfig
from app.io.user_data import get_builtin_presets_dir, get_presets_dir


def list_presets() -> list[str]:
    """Return sorted list of preset names (without .json extension)."""
    names: set[str] = set()
    for d in (get_presets_dir(), get_builtin_presets_dir("grid")):
        if d and os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    names.add(f[:-5])
    return sorted(names)


def save_preset(name: str, config: HexGridConfig) -> None:
    """Save config as preset. Overwrites existing."""
    path = os.path.join(get_presets_dir(), f"{name}.json")
    data = config.serialize()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_preset(name: str) -> HexGridConfig:
    """Load preset by name. Checks user dir first, then built-in."""
    user_path = os.path.join(get_presets_dir(), f"{name}.json")
    if os.path.exists(user_path):
        with open(user_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return HexGridConfig.deserialize(data)
    builtin_dir = get_builtin_presets_dir("grid")
    if builtin_dir:
        builtin_path = os.path.join(builtin_dir, f"{name}.json")
        if os.path.exists(builtin_path):
            with open(builtin_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return HexGridConfig.deserialize(data)
    raise FileNotFoundError(f"Preset '{name}' not found")


def delete_preset(name: str) -> bool:
    """Delete a preset file from user dir. Returns False if built-in only."""
    path = os.path.join(get_presets_dir(), f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def is_builtin_preset(name: str) -> bool:
    """Check if a preset exists only as a built-in (not in user dir)."""
    user_path = os.path.join(get_presets_dir(), f"{name}.json")
    if os.path.exists(user_path):
        return False
    builtin_dir = get_builtin_presets_dir("grid")
    if builtin_dir:
        return os.path.exists(os.path.join(builtin_dir, f"{name}.json"))
    return False
