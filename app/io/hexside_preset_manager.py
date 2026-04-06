"""Hexside style preset management - save/load/delete named hexside presets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.io.user_data import get_builtin_presets_dir, get_hexside_presets_dir


@dataclass
class HexsidePreset:
    """A named collection of hexside tool settings."""

    name: str
    paint_mode: str = "color"
    color: str = "#000000"
    width: float = 3.0
    outline: bool = False
    outline_color: str = "#000000"
    outline_width: float = 1.0
    outline_texture_id: str = ""
    outline_texture_zoom: float = 1.0
    outline_texture_rotation: float = 0.0
    shift_enabled: bool = False
    shift: float = 0.0
    random: bool = False
    random_amplitude: float = 3.0
    random_distance: float = 0.0
    random_endpoint: float = 0.0
    random_jitter: float = 0.0
    random_offset: float = 0.0
    taper: bool = False
    taper_length: float = 0.5
    texture_id: str | None = None
    texture_zoom: float = 1.0
    texture_rotation: float = 0.0
    opacity: float = 1.0
    outline_opacity: float = 1.0

    def serialize(self) -> dict:
        data = {
            "name": self.name,
            "paint_mode": self.paint_mode,
            "color": self.color,
            "width": self.width,
            "outline": self.outline,
            "outline_color": self.outline_color,
            "outline_width": self.outline_width,
            "outline_texture_id": self.outline_texture_id,
            "outline_texture_zoom": self.outline_texture_zoom,
            "outline_texture_rotation": self.outline_texture_rotation,
            "shift_enabled": self.shift_enabled,
            "shift": self.shift,
            "random": self.random,
            "random_amplitude": self.random_amplitude,
            "random_distance": self.random_distance,
            "random_endpoint": self.random_endpoint,
            "random_jitter": self.random_jitter,
            "random_offset": self.random_offset,
        }
        if self.taper:
            data["taper"] = True
            if self.taper_length != 0.5:
                data["taper_length"] = self.taper_length
        if self.texture_id is not None:
            data["texture_id"] = self.texture_id
            data["texture_zoom"] = self.texture_zoom
            data["texture_rotation"] = self.texture_rotation
        if self.opacity != 1.0:
            data["opacity"] = self.opacity
        if self.outline_opacity != 1.0:
            data["outline_opacity"] = self.outline_opacity
        return data

    @classmethod
    def deserialize(cls, data: dict) -> HexsidePreset:
        return cls(
            name=data.get("name", "Unnamed"),
            paint_mode=data.get("paint_mode", "color"),
            color=data.get("color", "#000000"),
            width=data.get("width", 3.0),
            outline=data.get("outline", False),
            outline_color=data.get("outline_color", "#000000"),
            outline_width=data.get("outline_width", 1.0),
            outline_texture_id=data.get("outline_texture_id", ""),
            outline_texture_zoom=data.get("outline_texture_zoom", 1.0),
            outline_texture_rotation=data.get("outline_texture_rotation", 0.0),
            shift_enabled=data.get("shift_enabled", False),
            shift=data.get("shift", 0.0),
            random=data.get("random", False),
            random_amplitude=data.get("random_amplitude", 3.0),
            random_distance=data.get("random_distance", 0.0),
            random_endpoint=data.get("random_endpoint", 0.0),
            random_jitter=data.get("random_jitter", 0.0),
            random_offset=data.get("random_offset", 0.0),
            taper=data.get("taper", False),
            taper_length=data.get("taper_length", 0.5),
            texture_id=data.get("texture_id"),
            texture_zoom=data.get("texture_zoom", 1.0),
            texture_rotation=data.get("texture_rotation", 0.0),
            opacity=data.get("opacity", 1.0),
            outline_opacity=data.get("outline_opacity", 1.0),
        )


def list_hexside_presets() -> list[str]:
    """Return sorted list of hexside preset names (without .json extension)."""
    names: set[str] = set()
    for d in (get_hexside_presets_dir(), get_builtin_presets_dir("hexside")):
        if d and os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    names.add(f[:-5])
    return sorted(names)


def save_hexside_preset(preset: HexsidePreset) -> None:
    """Save hexside preset to disk. Overwrites existing."""
    path = os.path.join(get_hexside_presets_dir(), f"{preset.name}.json")
    data = preset.serialize()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_hexside_preset(name: str) -> HexsidePreset:
    """Load hexside preset by name. Checks user dir first, then built-in."""
    user_path = os.path.join(get_hexside_presets_dir(), f"{name}.json")
    if os.path.exists(user_path):
        with open(user_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return HexsidePreset.deserialize(data)
    builtin_dir = get_builtin_presets_dir("hexside")
    if builtin_dir:
        builtin_path = os.path.join(builtin_dir, f"{name}.json")
        if os.path.exists(builtin_path):
            with open(builtin_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return HexsidePreset.deserialize(data)
    raise FileNotFoundError(f"Hexside preset '{name}' not found")


def delete_hexside_preset(name: str) -> bool:
    """Delete a hexside preset file from user dir. Returns False if built-in only."""
    path = os.path.join(get_hexside_presets_dir(), f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def is_builtin_hexside_preset(name: str) -> bool:
    """Check if a preset exists only as a built-in (not in user dir)."""
    user_path = os.path.join(get_hexside_presets_dir(), f"{name}.json")
    if os.path.exists(user_path):
        return False
    builtin_dir = get_builtin_presets_dir("hexside")
    if builtin_dir:
        return os.path.exists(os.path.join(builtin_dir, f"{name}.json"))
    return False
