"""Path style preset management - save/load/delete named path presets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.io.user_data import get_builtin_presets_dir, get_path_presets_dir


@dataclass
class PathPreset:
    """A named collection of path tool settings."""

    name: str
    color: str = "#000000"
    width: float = 3.0
    line_type: str = "solid"
    dash_length: float = 6.0
    gap_length: float = 4.0
    dash_cap: str = "flat"
    texture_id: str = ""
    texture_zoom: float = 1.0
    texture_rotation: float = 0.0
    bg_enabled: bool = False
    bg_color: str = "#000000"
    bg_width: float = 6.0
    bg_line_type: str = "solid"
    bg_dash_length: float = 6.0
    bg_gap_length: float = 4.0
    bg_dash_cap: str = "flat"
    bg_texture_id: str = ""
    bg_texture_zoom: float = 1.0
    bg_texture_rotation: float = 0.0
    opacity: float = 1.0
    bg_opacity: float = 1.0
    random: bool = False
    random_amplitude: float = 2.0
    random_distance: float = 0.0
    random_endpoint: float = 0.0
    random_offset: float = 0.0
    random_jitter: float = 0.0  # M08: width jitter matching PathObject.random_jitter
    smoothness: float = 0.5  # Freeform path only (shared presets)

    def serialize(self) -> dict:
        data = {
            "name": self.name,
            "color": self.color,
            "width": self.width,
            "line_type": self.line_type,
            "dash_length": self.dash_length,
            "gap_length": self.gap_length,
            "dash_cap": self.dash_cap,
            "texture_id": self.texture_id,
            "texture_zoom": self.texture_zoom,
            "texture_rotation": self.texture_rotation,
            "bg_enabled": self.bg_enabled,
            "bg_color": self.bg_color,
            "bg_width": self.bg_width,
            "bg_line_type": self.bg_line_type,
            "bg_dash_length": self.bg_dash_length,
            "bg_gap_length": self.bg_gap_length,
            "bg_dash_cap": self.bg_dash_cap,
            "bg_texture_id": self.bg_texture_id,
            "bg_texture_zoom": self.bg_texture_zoom,
            "bg_texture_rotation": self.bg_texture_rotation,
            "opacity": self.opacity,
            "bg_opacity": self.bg_opacity,
            "random": self.random,
            "random_amplitude": self.random_amplitude,
            "random_distance": self.random_distance,
            "random_endpoint": self.random_endpoint,
            "random_offset": self.random_offset,
            "random_jitter": self.random_jitter,
            "smoothness": self.smoothness,
        }
        return data

    @classmethod
    def deserialize(cls, data: dict) -> PathPreset:
        return cls(
            name=data.get("name", "Unnamed"),
            color=data.get("color", "#000000"),
            width=data.get("width", 3.0),
            line_type=data.get("line_type", "solid"),
            dash_length=data.get("dash_length", 6.0),
            gap_length=data.get("gap_length", 4.0),
            dash_cap=data.get("dash_cap", "flat"),
            texture_id=data.get("texture_id", ""),
            texture_zoom=data.get("texture_zoom", 1.0),
            texture_rotation=data.get("texture_rotation", 0.0),
            bg_enabled=data.get("bg_enabled", False),
            bg_color=data.get("bg_color", "#000000"),
            bg_width=data.get("bg_width", 6.0),
            bg_line_type=data.get("bg_line_type", "solid"),
            bg_dash_length=data.get("bg_dash_length", 6.0),
            bg_gap_length=data.get("bg_gap_length", 4.0),
            bg_dash_cap=data.get("bg_dash_cap", "flat"),
            bg_texture_id=data.get("bg_texture_id", ""),
            bg_texture_zoom=data.get("bg_texture_zoom", 1.0),
            bg_texture_rotation=data.get("bg_texture_rotation", 0.0),
            opacity=data.get("opacity", 1.0),
            bg_opacity=data.get("bg_opacity", 1.0),
            random=data.get("random", False),
            random_amplitude=data.get("random_amplitude", 2.0),
            random_distance=data.get("random_distance", 0.0),
            random_endpoint=data.get("random_endpoint", 0.0),
            random_offset=data.get("random_offset", 0.0),
            random_jitter=data.get("random_jitter", 0.0),
            smoothness=data.get("smoothness", 0.5),
        )


def list_path_presets() -> list[str]:
    """Return sorted list of path preset names (without .json extension)."""
    names: set[str] = set()
    for d in (get_path_presets_dir(), get_builtin_presets_dir("path")):
        if d and os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    names.add(f[:-5])
    return sorted(names)


def save_path_preset(preset: PathPreset) -> None:
    """Save path preset to disk. Overwrites existing."""
    path = os.path.join(get_path_presets_dir(), f"{preset.name}.json")
    data = preset.serialize()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_path_preset(name: str) -> PathPreset:
    """Load path preset by name. Checks user dir first, then built-in."""
    user_path = os.path.join(get_path_presets_dir(), f"{name}.json")
    if os.path.exists(user_path):
        with open(user_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PathPreset.deserialize(data)
    builtin_dir = get_builtin_presets_dir("path")
    if builtin_dir:
        builtin_path = os.path.join(builtin_dir, f"{name}.json")
        if os.path.exists(builtin_path):
            with open(builtin_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PathPreset.deserialize(data)
    raise FileNotFoundError(f"Path preset '{name}' not found")


def delete_path_preset(name: str) -> bool:
    """Delete a path preset file from user dir. Returns False if built-in only."""
    path = os.path.join(get_path_presets_dir(), f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def is_builtin_path_preset(name: str) -> bool:
    """Check if a preset exists only as a built-in (not in user dir)."""
    user_path = os.path.join(get_path_presets_dir(), f"{name}.json")
    if os.path.exists(user_path):
        return False
    builtin_dir = get_builtin_presets_dir("path")
    if builtin_dir:
        return os.path.exists(os.path.join(builtin_dir, f"{name}.json"))
    return False
