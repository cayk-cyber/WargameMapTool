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
    falloff_width: float = 20.0
    falloff_amount: float = 1.0
    falloff_random: float = 0.0
    teeth_count: int = 4
    teeth_size: float = 8.0
    teeth_color: str = "#000000"
    teeth_opacity: float = 1.0

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
        data["falloff_width"] = self.falloff_width
        data["falloff_amount"] = self.falloff_amount
        if self.falloff_random > 0:
            data["falloff_random"] = self.falloff_random
        data["teeth_count"] = self.teeth_count
        data["teeth_size"] = self.teeth_size
        data["teeth_color"] = self.teeth_color
        if self.teeth_opacity != 1.0:
            data["teeth_opacity"] = self.teeth_opacity
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
            falloff_width=data.get("falloff_width", 20.0),
            falloff_amount=data.get("falloff_amount", 1.0),
            falloff_random=data.get("falloff_random", 0.0),
            teeth_count=data.get("teeth_count", 4),
            teeth_size=data.get("teeth_size", 8.0),
            teeth_color=data.get("teeth_color", "#000000"),
            teeth_opacity=data.get("teeth_opacity", 1.0),
        )


def _sanitize_name(name: str) -> str:
    """Strip path separators and dots to prevent directory traversal."""
    return name.replace("/", "_").replace("\\", "_").replace("..", "_").strip()


def _resolve_preset_path(name: str, *dirs: str | None) -> str | None:
    """Find a preset JSON file, tolerating whitespace in filenames."""
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        exact = os.path.join(d, f"{name}.json")
        if os.path.exists(exact):
            return exact
        for f in os.listdir(d):
            if f.endswith(".json") and f[:-5].strip() == name:
                return os.path.join(d, f)
    return None


def list_hexside_presets() -> list[str]:
    """Return sorted list of hexside preset names (without .json extension)."""
    names: set[str] = set()
    for d in (get_hexside_presets_dir(), get_builtin_presets_dir("hexside")):
        if d and os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    names.add(f[:-5].strip())
    return sorted(names)


def save_hexside_preset(preset: HexsidePreset) -> None:
    """Save hexside preset to disk. Overwrites existing."""
    name = _sanitize_name(preset.name)
    path = os.path.join(get_hexside_presets_dir(), f"{name}.json")
    data = preset.serialize()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_hexside_preset(name: str) -> HexsidePreset:
    """Load hexside preset by name. Checks user dir first, then built-in."""
    name = _sanitize_name(name)
    path = _resolve_preset_path(name, get_hexside_presets_dir(), get_builtin_presets_dir("hexside"))
    if path:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return HexsidePreset.deserialize(data)
    raise FileNotFoundError(f"Hexside preset '{name}' not found")


def delete_hexside_preset(name: str) -> bool:
    """Delete a hexside preset file from user dir. Returns False if built-in only."""
    name = _sanitize_name(name)
    path = _resolve_preset_path(name, get_hexside_presets_dir())
    if path:
        os.remove(path)
        return True
    return False


def is_builtin_hexside_preset(name: str) -> bool:
    """Check if a preset exists only as a built-in (not in user dir)."""
    name = _sanitize_name(name)
    if _resolve_preset_path(name, get_hexside_presets_dir()):
        return False
    return _resolve_preset_path(name, get_builtin_presets_dir("hexside")) is not None
