# Wargame Map Tool

A modular hex map editor for hex-and-counter wargames. Build custom hex maps with a flexible layer-based system — no fixed modes, just combine layers as needed.

## Features

- **Hex Grid** — Flat-top or pointy-top orientation, configurable size (up to 100×100 hexes), optional half-hex clipping, megahex overlay etc.
- **Background Layer** — Import and position reference images with built-in image editing (paint, posterize, color select, outline extraction)
- **Fill Layer** — Solid color or texture fills per hex, with automatic hex-edge shading
- **Asset Layer** — Place, scale, rotate, and flip image assets; per-layer erase mask; asset library with drag & drop
- **Text Layer** — Fully styled text labels (font, size, color, outline, rotation, alignment)
- **Hexside Layer** — Edge decorations with Catmull-Rom splines, control points, outline, auto-connect, and random waviness
- **Path Layers** — Center-to-center paths and freeform freehand paths with foreground/background strokes, dashed/dotted line types, texture support, and control point editing
- **Border Layer** — Hex edge borders with solid, dotted, or lined styles and offset control
- **Sketch Layer** — Vector shapes (line, rectangle, polygon, ellipse, freehand) with fill, stroke, rotation, drop shadow, and optional draw-over-grid
- **Draw Layer** — Freeform brush painting with multiple channels, color/texture modes, custom PNG brush stamps, eraser, and layer-level outline & shadow effects
- **Export** — PNG (configurable DPI), PDF (vector), and `.hexmap` project files

## Requirements

- Python 3.13+
- PySide6 6.10+
- NumPy
- Windows 10/11

## Installing Python and Related Packages

### Installing Python 3

Download the Python installer for Windows at https://www.python.org/downloads/windows/

OR

`choco install python3` (if you use chocolatey)

### Installing Python Packages

* pip install pyside6
* pip install numpy
* pip install pyinstaller

## Building a Standalone Executable

Run from the project root directory (where `main.py` lives).

**Option A — Unpacked folder** (faster startup, recommended for distribution):

```bash
pyinstaller --onedir --windowed --noconfirm --icon=assets/icon.ico \
  --add-data "assets;assets" --hidden-import PySide6.QtPrintSupport \
  --name WargameMapTool main.py
```

**Option B — Single EXE** (slower startup due to extraction, easier to share):

```bash
pyinstaller --onefile --windowed --noconfirm --icon=assets/icon.ico \
  --add-data "assets;assets" --hidden-import PySide6.QtPrintSupport \
  --name WargameMapTool main.py
```

Output lands in `dist/WargameMapTool/` (onedir) or `dist/WargameMapTool.exe` (onefile).

## License

This project is covered by the GNU GENERAL PUBLIC LICENSE Version 3. See LICENSE for details.
