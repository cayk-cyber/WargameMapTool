"""Texture edit dialog – hue, saturation, brightness, and pixelize adjustments."""

from __future__ import annotations

import colorsys
import os
import tempfile

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.io.texture_library import LibraryTexture, import_texture


_PREVIEW_MAX = 180   # max dimension (px) for live preview thumbnails
_DEBOUNCE_MS = 350   # ms delay after last slider change before redrawing


# ---------------------------------------------------------------------------
# Image processing helpers
# ---------------------------------------------------------------------------

def _apply_pixelize(image: QImage, block_size: int) -> QImage:
    """Mosaic effect: scale down then back up with nearest-neighbour."""
    if block_size <= 1:
        return image
    w, h = image.width(), image.height()
    sw = max(1, w // block_size)
    sh = max(1, h // block_size)
    small = image.scaled(sw, sh,
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.FastTransformation)
    return small.scaled(w, h,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation)


def _apply_hsb(image: QImage, hue_shift: int, sat_delta: int,
               bright_delta: int) -> QImage:
    """Apply hue shift, saturation and brightness delta.

    hue_shift   : -180 .. 180  degrees
    sat_delta   : -100 .. 100  (multiplied onto saturation)
    bright_delta: -100 .. 100  (multiplied onto value/brightness)
    """
    src = image.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = src.width(), src.height()

    hue_norm = hue_shift / 360.0
    sat_factor = max(0.0, 1.0 + sat_delta / 100.0)
    bright_factor = max(0.0, 1.0 + bright_delta / 100.0)

    src_bytes = bytes(src.constBits())
    n = w * h
    result_bytes = bytearray(n * 4)

    for i in range(n):
        off = i * 4
        # ARGB32 little-endian memory layout: B G R A
        b = src_bytes[off]
        g = src_bytes[off + 1]
        r = src_bytes[off + 2]
        a = src_bytes[off + 3]

        hv, sv, vv = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        hv = (hv + hue_norm) % 1.0
        sv = max(0.0, min(1.0, sv * sat_factor))
        vv = max(0.0, min(1.0, vv * bright_factor))
        nr, ng, nb = colorsys.hsv_to_rgb(hv, sv, vv)

        result_bytes[off]     = int(nb * 255)
        result_bytes[off + 1] = int(ng * 255)
        result_bytes[off + 2] = int(nr * 255)
        result_bytes[off + 3] = a

    result = QImage(bytes(result_bytes), w, h, w * 4,
                    QImage.Format.Format_ARGB32)
    return result.copy()


def _apply_adjustments(image: QImage, hue_shift: int, sat_delta: int,
                       bright_delta: int, pixelize: int) -> QImage:
    result = image
    if hue_shift != 0 or sat_delta != 0 or bright_delta != 0:
        result = _apply_hsb(result, hue_shift, sat_delta, bright_delta)
    if pixelize > 1:
        result = _apply_pixelize(result, pixelize)
    return result


# ---------------------------------------------------------------------------
# HueSlider – custom widget with rainbow gradient track
# ---------------------------------------------------------------------------

class HueSlider(QWidget):
    """Horizontal slider with a full-spectrum hue gradient as the track.

    Value range: -180 .. 180 (degrees of hue shift).
    """

    valueChanged = Signal(int)

    _LO = -180
    _HI = 180

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self.setFixedHeight(30)
        self.setMinimumWidth(120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ------------------------------------------------------------------
    # Public API (matches QSlider interface used in the dialog)
    # ------------------------------------------------------------------

    def value(self) -> int:
        return self._value

    def setValue(self, v: int) -> None:
        v = max(self._LO, min(self._HI, int(v)))
        if v != self._value:
            self._value = v
            self.valueChanged.emit(v)
            self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def _track_rect(self):
        return self.rect().adjusted(8, 4, -8, -4)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tr = self._track_rect()

        # --- Rainbow gradient ---
        grad = QLinearGradient(tr.left(), 0, tr.right(), 0)
        steps = 36
        for i in range(steps + 1):
            t = i / steps
            hue = int(t * 360) % 360
            grad.setColorAt(t, QColor.fromHsv(hue, 230, 210))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(tr, 3, 3)

        # Track border
        painter.setPen(QPen(QColor("#3a3a3a"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(tr, 3, 3)

        # Center tick at value=0
        cx = tr.left() + tr.width() // 2
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.drawLine(cx, tr.top() + 3, cx, tr.bottom() - 3)

        # Cursor line
        span = self._HI - self._LO
        t = (self._value - self._LO) / span
        x = tr.left() + int(t * tr.width())

        # Outer black stroke for contrast on any background
        painter.setPen(QPen(QColor(0, 0, 0, 180), 3))
        painter.drawLine(x, tr.top() - 1, x, tr.bottom() + 1)
        # White inner line
        painter.setPen(QPen(QColor("white"), 1))
        painter.drawLine(x, tr.top() - 1, x, tr.bottom() + 1)

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_x(event.position().x())

    def _set_from_x(self, x: float) -> None:
        tr = self._track_rect()
        t = (x - tr.left()) / max(1, tr.width())
        t = max(0.0, min(1.0, t))
        self.setValue(round(self._LO + t * (self._HI - self._LO)))


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class TextureEditDialog(QDialog):
    """Adjust hue, saturation, brightness, and pixelize a texture,
    then save the result as a new entry in the user texture library."""

    def __init__(self, texture: LibraryTexture, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Texture – {texture.display_name}")
        self.setMinimumSize(720, 460)

        self._texture = texture

        self._original_full = QImage(texture.file_path())
        if self._original_full.isNull():
            fallback = QImage(64, 64, QImage.Format.Format_RGB32)
            fallback.fill(0xFF888888)
            self._original_full = fallback

        # Small version used for fast live preview
        self._original_preview = self._original_full.scaled(
            _PREVIEW_MAX, _PREVIEW_MAX,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Debounce timer so we don't re-render on every slider tick
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._do_update_preview)

        self._build_ui()
        self._do_update_preview()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)

        # ---- Preview row (original | edited) ----
        preview_group = QGroupBox("Preview")
        pv_row = QHBoxLayout(preview_group)

        orig_col = QVBoxLayout()
        orig_lbl = QLabel("Original:")
        orig_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        orig_col.addWidget(orig_lbl)
        self._orig_img = QLabel()
        self._orig_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._orig_img.setFixedSize(_PREVIEW_MAX, _PREVIEW_MAX)
        self._orig_img.setStyleSheet("border: 1px solid #555;")
        self._orig_img.setPixmap(
            QPixmap.fromImage(self._original_preview).scaled(
                _PREVIEW_MAX, _PREVIEW_MAX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )
        orig_col.addWidget(self._orig_img)
        pv_row.addLayout(orig_col)

        edited_col = QVBoxLayout()
        edited_lbl = QLabel("Edited:")
        edited_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edited_col.addWidget(edited_lbl)
        self._edited_img = QLabel()
        self._edited_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._edited_img.setFixedSize(_PREVIEW_MAX, _PREVIEW_MAX)
        self._edited_img.setStyleSheet("border: 1px solid #555;")
        edited_col.addWidget(self._edited_img)
        pv_row.addLayout(edited_col)

        outer.addWidget(preview_group)

        # ---- Controls row ----
        ctrl_row = QHBoxLayout()

        # Color adjustments
        color_group = QGroupBox("Color Adjustments")
        color_form = QFormLayout(color_group)

        self._hue_slider, hue_widget = self._make_hue_row()
        color_form.addRow("Hue:", hue_widget)

        self._sat_slider, sat_widget = self._make_slider(-100, 100, 0)
        color_form.addRow("Saturation:", sat_widget)

        self._bright_slider, bright_widget = self._make_slider(-100, 100, 0)
        color_form.addRow("Brightness:", bright_widget)

        ctrl_row.addWidget(color_group, stretch=3)

        # Mosaic / Pixelize
        mosaic_group = QGroupBox("Mosaic / Pixelize")
        mosaic_form = QFormLayout(mosaic_group)

        self._pix_slider, pix_widget = self._make_slider(1, 32, 1)
        mosaic_form.addRow("Block size:", pix_widget)

        ctrl_row.addWidget(mosaic_group, stretch=2)

        outer.addLayout(ctrl_row)

        # ---- Save row ----
        save_group = QGroupBox("Save as New Texture")
        save_form = QFormLayout(save_group)

        self._name_edit = QLineEdit(self._texture.display_name + " (edited)")
        save_form.addRow("Name:", self._name_edit)

        outer.addWidget(save_group)

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        save_btn = QPushButton("Save as New Texture")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        outer.addLayout(btn_row)

    def _make_hue_row(self):
        """Return (HueSlider, container_widget) with spinbox and reset button."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)

        hue = HueSlider()

        spinbox = QSpinBox()
        spinbox.setRange(HueSlider._LO, HueSlider._HI)
        spinbox.setValue(0)
        spinbox.setSuffix("°")
        spinbox.setFixedWidth(68)

        hue.valueChanged.connect(spinbox.setValue)
        spinbox.valueChanged.connect(hue.setValue)
        hue.valueChanged.connect(self._schedule_update)

        reset_btn = QPushButton("↺")
        reset_btn.setFixedSize(24, 24)
        reset_btn.setToolTip("Reset to 0°")
        reset_btn.clicked.connect(lambda: hue.setValue(0))

        row.addWidget(hue, stretch=1)
        row.addWidget(spinbox)
        row.addWidget(reset_btn)

        return hue, container

    def _make_slider(self, lo: int, hi: int, default: int):
        """Return (QSlider, container_widget) with spinbox and reset button."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(default)

        spinbox = QSpinBox()
        spinbox.setRange(lo, hi)
        spinbox.setValue(default)
        spinbox.setFixedWidth(60)

        slider.valueChanged.connect(spinbox.setValue)
        spinbox.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(self._schedule_update)

        reset_btn = QPushButton("↺")
        reset_btn.setFixedSize(24, 24)
        reset_btn.setToolTip("Reset to default")
        _def = default
        reset_btn.clicked.connect(lambda: slider.setValue(_def))

        row.addWidget(slider, stretch=1)
        row.addWidget(spinbox)
        row.addWidget(reset_btn)

        return slider, container

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _schedule_update(self):
        self._timer.start()

    def _do_update_preview(self):
        hue    = self._hue_slider.value()
        sat    = self._sat_slider.value()
        bright = self._bright_slider.value()
        pix    = self._pix_slider.value()

        result = _apply_adjustments(self._original_preview, hue, sat, bright, pix)
        pixmap = QPixmap.fromImage(result).scaled(
            _PREVIEW_MAX, _PREVIEW_MAX,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._edited_img.setPixmap(pixmap)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _on_save(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Save Texture", "Please enter a name.")
            return

        hue    = self._hue_slider.value()
        sat    = self._sat_slider.value()
        bright = self._bright_slider.value()
        pix    = self._pix_slider.value()

        tmp_path: str | None = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result_image = _apply_adjustments(
                self._original_full, hue, sat, bright, pix
            )

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name

            result_image.save(tmp_path)

            import_texture(
                tmp_path, name,
                category=self._texture.category,
                game=self._texture.game,
            )
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Save Texture",
                                 f"Failed to save texture:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        QMessageBox.information(
            self, "Save Texture",
            f"Texture '{name}' was saved to the library.",
        )
        self.accept()
