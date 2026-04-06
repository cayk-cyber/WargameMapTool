"""User data directory management (AppData on Windows)."""

from __future__ import annotations

import json
import os
import sys

_APP_NAME = "WargameMapTool"


def get_app_data_dir() -> str:
    """Return the app data directory, creating it if needed.

    Windows: %APPDATA%/WargameMapTool/
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = os.path.join(appdata, _APP_NAME)
    else:
        base = os.path.join(os.path.expanduser("~"), f".{_APP_NAME}")
    os.makedirs(base, exist_ok=True)
    return base


def get_presets_dir() -> str:
    """Return the presets directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "presets")
    os.makedirs(path, exist_ok=True)
    return path


def get_user_assets_dir() -> str:
    """Return the user assets directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "assets")
    os.makedirs(path, exist_ok=True)
    return path


def get_palettes_dir() -> str:
    """Return the color palettes directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "palettes")
    os.makedirs(path, exist_ok=True)
    return path


def get_user_textures_dir() -> str:
    """Return the user textures directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "textures")
    os.makedirs(path, exist_ok=True)
    return path


def get_text_presets_dir() -> str:
    """Return the text presets directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "text_presets")
    os.makedirs(path, exist_ok=True)
    return path


def get_hexside_presets_dir() -> str:
    """Return the hexside presets directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "hexside_presets")
    os.makedirs(path, exist_ok=True)
    return path


def get_border_presets_dir() -> str:
    """Return the border presets directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "border_presets")
    os.makedirs(path, exist_ok=True)
    return path


def get_path_presets_dir() -> str:
    """Return the path presets directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "path_presets")
    os.makedirs(path, exist_ok=True)
    return path


def get_builtin_textures_dir() -> str | None:
    """Return path to built-in textures directory, or None if not found."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        app_io_dir = os.path.dirname(os.path.abspath(__file__))  # app/io/
        base = os.path.dirname(os.path.dirname(app_io_dir))  # project root
    builtin_dir = os.path.join(base, "assets", "textures")
    if os.path.isdir(builtin_dir):
        return builtin_dir
    return None


def get_builtin_assets_dir() -> str | None:
    """Return path to built-in assets directory, or None if not found."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        app_io_dir = os.path.dirname(os.path.abspath(__file__))  # app/io/
        base = os.path.dirname(os.path.dirname(app_io_dir))  # project root
    builtin_dir = os.path.join(base, "assets", "assets")
    if os.path.isdir(builtin_dir):
        return builtin_dir
    return None


def get_user_brushes_dir() -> str:
    """Return the user brushes directory, creating it if needed."""
    path = os.path.join(get_app_data_dir(), "brushes")
    os.makedirs(path, exist_ok=True)
    return path


def get_builtin_brushes_dir() -> str | None:
    """Return path to built-in brushes directory, or None if not found."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        app_io_dir = os.path.dirname(os.path.abspath(__file__))  # app/io/
        base = os.path.dirname(os.path.dirname(app_io_dir))  # project root
    builtin_dir = os.path.join(base, "assets", "brushes")
    if os.path.isdir(builtin_dir):
        return builtin_dir
    return None


def get_builtin_palettes_dir() -> str | None:
    """Return path to built-in palettes directory, or None if not found."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        app_io_dir = os.path.dirname(os.path.abspath(__file__))  # app/io/
        base = os.path.dirname(os.path.dirname(app_io_dir))  # project root
    builtin_dir = os.path.join(base, "assets", "palettes")
    if os.path.isdir(builtin_dir):
        return builtin_dir
    return None


def _app_settings_path() -> str:
    return os.path.join(get_app_data_dir(), "app_settings.json")


def load_app_settings() -> dict:
    """Load persistent application settings from AppData."""
    path = _app_settings_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_app_settings(settings: dict) -> None:
    """Persist application settings to AppData."""
    path = _app_settings_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_builtin_presets_dir(preset_type: str) -> str | None:
    """Return built-in presets dir for a type ('grid','path','hexside','text').

    Returns None if the directory does not exist.
    """
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        app_io_dir = os.path.dirname(os.path.abspath(__file__))  # app/io/
        base = os.path.dirname(os.path.dirname(app_io_dir))  # project root
    builtin_dir = os.path.join(base, "assets", "presets", preset_type)
    if os.path.isdir(builtin_dir):
        return builtin_dir
    return None
