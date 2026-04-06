"""Border style preset management - save/load/delete named border presets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.io.user_data import get_border_presets_dir, get_builtin_presets_dir


@dataclass
class BorderPreset:
    """A named collection of border tool settings."""

    name: str
    color: str = "#000000"
    width: float = 3.0
    line_type: str = "solid"
    element_size: float = 4.0
    gap_size: float = 4.0
    dash_cap: str = "round"
    outline: bool = False
    outline_color: str = "#000000"
    outline_width: float = 1.0
    offset: float = 0.0

    def serialize(self) -> dict:
        return {
            "name": self.name,
            "color": self.color,
            "width": self.width,
            "line_type": self.line_type,
            "element_size": self.element_size,
            "gap_size": self.gap_size,
            "dash_cap": self.dash_cap,
            "outline": self.outline,
            "outline_color": self.outline_color,
            "outline_width": self.outline_width,
            "offset": self.offset,
        }

    @classmethod
    def deserialize(cls, data: dict) -> BorderPreset:
        return cls(
            name=data.get("name", "Unnamed"),
            color=data.get("color", "#000000"),
            width=data.get("width", 3.0),
            line_type={"lined": "dashed"}.get(
                data.get("line_type", "solid"),
                data.get("line_type", "solid"),
            ),
            element_size=data.get("element_size", 4.0),
            gap_size=data.get("gap_size", 4.0),
            dash_cap=data.get("dash_cap", "round"),
            outline=data.get("outline", False),
            outline_color=data.get("outline_color", "#000000"),
            outline_width=data.get("outline_width", 1.0),
            offset=data.get("offset", 0.0),
        )


def list_border_presets() -> list[str]:
    """Return sorted list of border preset names (without .json extension)."""
    names: set[str] = set()
    for d in (get_border_presets_dir(), get_builtin_presets_dir("border")):
        if d and os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    names.add(f[:-5])
    return sorted(names)


def save_border_preset(preset: BorderPreset) -> None:
    """Save border preset to disk. Overwrites existing."""
    path = os.path.join(get_border_presets_dir(), f"{preset.name}.json")
    data = preset.serialize()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_border_preset(name: str) -> BorderPreset:
    """Load border preset by name. Checks user dir first, then built-in."""
    user_path = os.path.join(get_border_presets_dir(), f"{name}.json")
    if os.path.exists(user_path):
        with open(user_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BorderPreset.deserialize(data)
    builtin_dir = get_builtin_presets_dir("border")
    if builtin_dir:
        builtin_path = os.path.join(builtin_dir, f"{name}.json")
        if os.path.exists(builtin_path):
            with open(builtin_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return BorderPreset.deserialize(data)
    raise FileNotFoundError(f"Border preset '{name}' not found")


def delete_border_preset(name: str) -> bool:
    """Delete a border preset file from user dir. Returns False if built-in only."""
    path = os.path.join(get_border_presets_dir(), f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def is_builtin_border_preset(name: str) -> bool:
    """Check if a preset exists only as a built-in (not in user dir)."""
    user_path = os.path.join(get_border_presets_dir(), f"{name}.json")
    if os.path.exists(user_path):
        return False
    builtin_dir = get_builtin_presets_dir("border")
    if builtin_dir:
        return os.path.exists(os.path.join(builtin_dir, f"{name}.json"))
    return False
