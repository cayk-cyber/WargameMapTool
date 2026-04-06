"""Color palette management - save/load/delete named color palettes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from app.io.user_data import get_builtin_palettes_dir, get_palettes_dir

# Default palette colors (same as the old hardcoded quick colors)
_DEFAULT_COLORS = [
    ("Ground_Open", "#94ae5c"),
    ("Hill_1", "#c88256"),
    ("Hill_2", "#b9543e"),
    ("Hill_3", "#91413c"),
    ("Valley", "#567740"),
    ("Water", "#5ad7e2"),
    ("Bocage", "#3e5b2f"),
    ("Orchard", "#52622e"),
    ("Road_Mud", "#dccd7b"),
    ("Road_Asphalt", "#c6c6ce"),
    ("Grain", "#fff06f")
]

@dataclass
class PaletteColor:
    """A single named color entry in a palette."""

    name: str
    color: str  # hex string "#RRGGBB"


@dataclass
class ColorPalette:
    """A named collection of colors."""

    name: str
    colors: list[PaletteColor] = field(default_factory=list)

    def serialize(self) -> dict:
        return {
            "name": self.name,
            "colors": [{"name": c.name, "color": c.color} for c in self.colors],
        }

    @classmethod
    def deserialize(cls, data: dict) -> ColorPalette:
        colors = [
            PaletteColor(name=c["name"], color=c["color"])
            for c in data.get("colors", [])
        ]
        return cls(name=data.get("name", "Unnamed"), colors=colors)


def list_palettes() -> list[str]:
    """Return sorted list of palette names (without .json extension)."""
    names: set[str] = set()
    for d in (get_palettes_dir(), get_builtin_palettes_dir()):
        if d and os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    names.add(f[:-5])
    return sorted(names)


def _sanitize_name(name: str) -> str:
    """Strip path separators and dots to prevent directory traversal. L08"""
    return name.replace("/", "_").replace("\\", "_").replace("..", "_").strip()


def save_palette(palette: ColorPalette) -> None:
    """Save palette to disk. Overwrites existing."""
    path = os.path.join(get_palettes_dir(), f"{_sanitize_name(palette.name)}.json")
    data = palette.serialize()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_palette(name: str) -> ColorPalette:
    """Load palette by name. Checks user dir first, then built-in."""
    user_path = os.path.join(get_palettes_dir(), f"{name}.json")
    if os.path.exists(user_path):
        with open(user_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ColorPalette.deserialize(data)
    builtin_dir = get_builtin_palettes_dir()
    if builtin_dir:
        builtin_path = os.path.join(builtin_dir, f"{name}.json")
        if os.path.exists(builtin_path):
            with open(builtin_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ColorPalette.deserialize(data)
    raise FileNotFoundError(f"Palette '{name}' not found")


def delete_palette(name: str) -> None:
    """Delete a palette file from user dir."""
    path = os.path.join(get_palettes_dir(), f"{name}.json")
    if os.path.exists(path):
        os.remove(path)


def is_builtin_palette(name: str) -> bool:
    """Check if a palette exists only as a built-in (not in user dir)."""
    user_path = os.path.join(get_palettes_dir(), f"{name}.json")
    if os.path.exists(user_path):
        return False
    builtin_dir = get_builtin_palettes_dir()
    if builtin_dir:
        return os.path.exists(os.path.join(builtin_dir, f"{name}.json"))
    return False


def ensure_default_palette() -> None:
    """Create the 'Default' palette if it doesn't exist yet."""
    path = os.path.join(get_palettes_dir(), "Classic.json")
    if os.path.exists(path):
        return
    palette = ColorPalette(
        name="Classic",  # M07: was "ASL", causing ASL.json to be created instead of Default.json
        colors=[PaletteColor(name=n, color=c) for n, c in _DEFAULT_COLORS],
    )
    save_palette(palette)
