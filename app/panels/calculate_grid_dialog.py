"""Calculate Grid dialog – compute required hex grid size from real-world distances."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QClipboard, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

# Hex geometry factor: flat-to-flat / (2 * circumradius) = sqrt(3)/2
_SQRT3_HALF = math.sqrt(3) / 2   # ≈ 0.8660


class CalculateGridDialog(QDialog):
    """Interactive dialog to calculate the hex grid dimensions needed to
    represent a given real-world area at a given hex scale."""

    def __init__(self, orientation: str = "flat", parent=None):
        """
        Args:
            orientation: "flat" (flat-top) or "pointy" (pointy-top).
                         Defaults to "flat".  Pre-selects the orientation
                         combo so the result matches the current map.
        """
        super().__init__(parent)
        self.setWindowTitle("Calculate Grid Size")
        self.setMinimumWidth(400)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._build_ui(orientation)
        self._update_result()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self, orientation: str):
        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # ---- Map Scale group ----
        scale_group = QGroupBox("Map Scale")
        scale_form = QFormLayout(scale_group)

        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["km", "miles"])
        self._unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        scale_form.addRow("Unit:", self._unit_combo)

        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.01, 9999.0)
        self._scale_spin.setDecimals(2)
        self._scale_spin.setValue(12.0)
        self._scale_spin.setSuffix(" km/hex")
        self._scale_spin.setToolTip(
            "Real-world distance represented by one hex\n"
            "(measured center-to-center between adjacent hexes)"
        )
        self._scale_spin.valueChanged.connect(self._update_result)
        scale_form.addRow("Hex scale:", self._scale_spin)

        # Orientation combo – pre-selected from the current map config
        self._orient_combo = QComboBox()
        self._orient_combo.addItem("Flat-Top", "flat")
        self._orient_combo.addItem("Pointy-Top", "pointy")
        idx = 0 if orientation == "flat" else 1
        self._orient_combo.setCurrentIndex(idx)
        self._orient_combo.currentIndexChanged.connect(self._update_result)
        scale_form.addRow("Orientation:", self._orient_combo)

        outer.addWidget(scale_group)

        # ---- Distances group ----
        dist_group = QGroupBox("Real-World Distances (straight-line)")
        dist_form = QFormLayout(dist_group)

        self._ns_spin = QDoubleSpinBox()
        self._ns_spin.setRange(0.0, 999999.0)
        self._ns_spin.setDecimals(1)
        self._ns_spin.setValue(0.0)
        self._ns_spin.setSuffix(" km")
        self._ns_spin.setToolTip(
            "Straight-line distance of the map area in the North–South direction\n"
            "(e.g. from luftlinie.org)"
        )
        self._ns_spin.valueChanged.connect(self._update_result)
        dist_form.addRow("North–South:", self._ns_spin)

        self._ew_spin = QDoubleSpinBox()
        self._ew_spin.setRange(0.0, 999999.0)
        self._ew_spin.setDecimals(1)
        self._ew_spin.setValue(0.0)
        self._ew_spin.setSuffix(" km")
        self._ew_spin.setToolTip(
            "Straight-line distance of the map area in the East–West direction\n"
            "(e.g. from luftlinie.org)"
        )
        self._ew_spin.valueChanged.connect(self._update_result)
        dist_form.addRow("East–West:", self._ew_spin)

        outer.addWidget(dist_group)

        # ---- Result group ----
        result_group = QGroupBox("Result")
        result_vbox = QVBoxLayout(result_group)

        # Big size display
        self._size_lbl = QLabel("—")
        font = QFont()
        font.setPointSize(22)
        font.setBold(True)
        self._size_lbl.setFont(font)
        self._size_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result_vbox.addWidget(self._size_lbl)

        sub_lbl = QLabel("hexes wide × hexes high")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setStyleSheet("color: #999; font-size: 11px;")
        result_vbox.addWidget(sub_lbl)

        # Calculation detail
        self._detail_lbl = QLabel("")
        self._detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_lbl.setStyleSheet("color: #bbb; font-size: 11px;")
        self._detail_lbl.setWordWrap(True)
        result_vbox.addWidget(self._detail_lbl)

        outer.addWidget(result_group)

        # ---- Explanation (updated dynamically) ----
        self._note_lbl = QLabel()
        self._note_lbl.setStyleSheet("color: #888; font-size: 10px;")
        self._note_lbl.setWordWrap(True)
        self._note_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._note_lbl)

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._copy_btn = QPushButton("Copy to Clipboard")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._on_copy)
        btn_row.addWidget(self._copy_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        outer.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _on_unit_changed(self):
        unit = self._unit_combo.currentText()
        self._scale_spin.setSuffix(f" {unit}/hex")
        self._ns_spin.setSuffix(f" {unit}")
        self._ew_spin.setSuffix(f" {unit}")
        self._update_result()

    def _update_result(self):
        scale = self._scale_spin.value()
        ns = self._ns_spin.value()
        ew = self._ew_spin.value()
        unit = self._unit_combo.currentText()
        is_flat = self._orient_combo.currentData() == "flat"

        # For flat-top:   columns are staggered E-W → EW spacing = scale × √3/2
        #                  rows stack N-S          → NS spacing = scale
        # For pointy-top: rows are staggered N-S   → NS spacing = scale × √3/2
        #                  columns stack E-W        → EW spacing = scale
        if is_flat:
            ew_spacing = scale * _SQRT3_HALF
            ns_spacing = scale
            note = (
                "Flat-Top formula:\n"
                "E–W hexes = EW ÷ (scale × √3/2)  |  N–S hexes = NS ÷ scale\n"
                "The √3/2 ≈ 0.866 factor accounts for the staggered column spacing."
            )
        else:
            ew_spacing = scale
            ns_spacing = scale * _SQRT3_HALF
            note = (
                "Pointy-Top formula:\n"
                "E–W hexes = EW ÷ scale  |  N–S hexes = NS ÷ (scale × √3/2)\n"
                "The √3/2 ≈ 0.866 factor accounts for the staggered row spacing."
            )

        self._note_lbl.setText(note)

        if scale <= 0 or (ns <= 0 and ew <= 0):
            self._size_lbl.setText("—")
            self._detail_lbl.setText("")
            self._copy_btn.setEnabled(False)
            return

        ns_exact = ns / ns_spacing if ns > 0 else 0.0
        ew_exact = ew / ew_spacing if ew > 0 else 0.0

        ns_hexes = math.ceil(ns_exact) if ns > 0 else 0
        ew_hexes = math.ceil(ew_exact) if ew > 0 else 0

        self._size_lbl.setText(f"{ew_hexes} × {ns_hexes}")

        lines = []
        if ew > 0:
            lines.append(
                f"E–W:  {ew:.1f} {unit} ÷ {ew_spacing:.2f} {unit}/hex"
                f" = {ew_exact:.1f}  →  {ew_hexes} hexes wide"
            )
        if ns > 0:
            lines.append(
                f"N–S:  {ns:.1f} {unit} ÷ {ns_spacing:.2f} {unit}/hex"
                f" = {ns_exact:.1f}  →  {ns_hexes} hexes high"
            )
        self._detail_lbl.setText("\n".join(lines))
        self._copy_btn.setEnabled(True)

        self._last_result = (ew_hexes, ns_hexes)

    def _on_copy(self):
        ew, ns = self._last_result
        QApplication.clipboard().setText(f"{ew} × {ns}")
