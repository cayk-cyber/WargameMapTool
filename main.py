"""Hex Map Editor - Entry Point."""

import os
import sys
import traceback

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from app.main_window import MainWindow
from app.version import LOADING_SCREEN


def _make_splash_pixmap(icon_path: str) -> QPixmap:
    """Load icon.ico; scale up to 256×256 minimum (same as companion apps)."""
    pm = QPixmap(icon_path)
    if not pm.isNull() and (pm.width() < 256 or pm.height() < 256):
        pm = pm.scaled(
            256, 256,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pm


def main():
    QImageReader.setAllocationLimit(512)

    app = QApplication(sys.argv)
    app.setApplicationName("Wargame Map Tool")

    app.setStyleSheet("""
        QScrollBar:vertical {
            background: #c0c0c0;
            width: 6px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #666666;
            min-height: 24px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical:hover {
            background: #888888;
        }
        QScrollBar::handle:vertical:pressed {
            background: #aaaaaa;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            background: none;
        }
        QScrollBar:horizontal {
            background: #c0c0c0;
            height: 6px;
            margin: 0px;
        }
        QScrollBar::handle:horizontal {
            background: #666666;
            min-width: 24px;
            border-radius: 5px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #888888;
        }
        QScrollBar::handle:horizontal:pressed {
            background: #aaaaaa;
        }
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {
            width: 0px;
        }
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {
            background: none;
        }
    """)

    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_path, "assets", "icon.ico")
    app.setWindowIcon(QIcon(icon_path))

    # Splash screen (only when LOADING_SCREEN = True in version.py)
    splash = None
    if LOADING_SCREEN:
        splash = QSplashScreen(_make_splash_pixmap(icon_path))
        splash.show()
        app.processEvents()
        loop = QEventLoop()
        QTimer.singleShot(2000, loop.quit)
        loop.exec()

    try:  # L15: show error dialog on startup crash instead of silent Python traceback
        window = MainWindow()
    except Exception:
        if splash:
            splash.close()
        msg = QMessageBox()
        msg.setWindowTitle("Startup Error")
        msg.setText("Failed to start WargameMapTool.")
        msg.setDetailedText(traceback.format_exc())
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.exec()
        sys.exit(1)
    window.showMaximized()
    if splash:
        splash.finish(window)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

# --- PyInstaller Build Commands ---
#
# Run from the project root directory (where main.py lives).
# Output lands in dist/WargameMapTool/  (onedir) or dist/WargameMapTool.exe (onefile).
#
# Option A: Unpacked folder (faster startup, recommended for distribution)
#
# One-liner (copy-paste ready):
#
#   pyinstaller --onedir --windowed --noconfirm --icon=assets/icon.ico --add-data "assets;assets" --hidden-import PySide6.QtPrintSupport --name WargameMapTool main.py
#
# Option B: Single EXE (slower startup due to extraction, easier to share)
#
#   pyinstaller --onefile --windowed --noconfirm --icon=assets/icon.ico --add-data "assets;assets" --hidden-import PySide6.QtPrintSupport --name WargameMapTool main.py
#
# Notes:
#   --add-data "assets;assets"  bundles the entire assets/ tree (icon, brushes,
#       palettes, textures, presets/grid|path|hexside|border|text, assets/assets/).
#       All user_data.py helpers read sys._MEIPASS + "assets/..." when frozen,
#       so no additional --add-data entries are needed.
#   --hidden-import PySide6.QtPrintSupport  prevents a runtime import error that
#       PySide6 sometimes triggers even when printing is not used directly.
#   numpy is detected automatically (used by brush_cache.py).
