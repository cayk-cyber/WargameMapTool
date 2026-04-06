"""In-app documentation / wiki dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

# ---------------------------------------------------------------------------
# CSS applied to all pages
# ---------------------------------------------------------------------------
_CSS = """
body  { font-family: 'Segoe UI', sans-serif; font-size: 13px; margin: 10px 14px; }
h2    { font-size: 15px; margin-bottom: 2px; }
h3    { font-size: 12px; font-weight: bold; margin-top: 14px; margin-bottom: 3px; }
code  { font-family: Consolas, monospace; font-size: 12px; }
table { border-collapse: collapse; width: 100%; margin-top: 6px; }
th    { padding: 4px 8px; text-align: left; }
td    { padding: 3px 8px; vertical-align: top; }
ul    { margin-top: 3px; margin-bottom: 4px; padding-left: 18px; }
li    { margin-bottom: 2px; }
"""

# ---------------------------------------------------------------------------
# Page content  (key -> HTML string)
# ---------------------------------------------------------------------------

def _page(title: str, body: str) -> str:
    return f"<h2>{title}</h2>{body}"


_DOCS: dict[str, str] = {}

# ── Getting Started ──────────────────────────────────────────────────────────

_DOCS["overview"] = _page("Overview", """
<p><b>Wargame Map Tool</b> is a modular hex-map editor designed for board-wargames
(ASL, Next War, OST and similar). The workflow is layer-based: every kind of
content lives on its own layer and is edited with the matching tool.</p>

<h3>Basic Workflow</h3>
<ul>
  <li>Create a new map via <b>File &gt; New</b> or open an existing <code>.hexmap</code> file.</li>
  <li>The <b>Layer Panel</b> (left) shows all layers. Click a layer to make it active.</li>
  <li>The active layer determines the active tool — e.g. clicking an Asset layer
      switches to the Asset tool automatically.</li>
  <li>The <b>Tool Options Panel</b> (right) shows controls for the current tool.</li>
  <li>Paint, place, or draw on the canvas in the centre.</li>
  <li>Use <b>Ctrl+Z / Ctrl+Y</b> to undo and redo (up to 20 steps).</li>
  <li>Save as <code>.hexmap</code> (JSON) or export to PNG / PDF.</li>
</ul>

<h3>Coordinate System</h3>
<p>Hexes use <b>axial coordinates (q, r)</b> (Red Blob Games reference). Flat-Top
orientation is the default. World space is measured in screen pixels at 96 DPI.</p>

<h3>Layer Limit</h3>
<p>There is no hard limit on the number of layers. Each layer type can be added
multiple times.</p>
""")

_DOCS["new_map"] = _page("New Map Dialog", """
<p>Opened via <b>File &gt; New</b> (shortcut <code>Ctrl+N</code>). The same dialog
appears as <b>Map Settings</b> via <b>Edit &gt; Map Settings</b> — in that case the
Grid and Presets groups are read-only.</p>

<h3>Presets</h3>
<ul>
  <li><b>Preset combo</b> — select a previously saved grid preset.</li>
  <li><b>Load</b> — apply the selected preset to all fields below.</li>
  <li><b>Save</b> — save the current settings under a new or existing name.</li>
  <li><b>Delete</b> — remove the selected preset (built-in presets cannot be deleted).</li>
</ul>

<h3>Grid</h3>
<ul>
  <li><b>Hex Size</b> — physical size of one hex in millimetres (5–50 mm, default 19 mm).</li>
  <li><b>Columns</b> — number of hex columns (1–100).</li>
  <li><b>Rows</b> — number of hex rows (1–100).</li>
  <li><b>Orientation</b> — <i>Flat (Flat-Top)</i> or <i>Upright (Pointy-Top)</i>.</li>
  <li><b>First Row</b> — <i>Offset Down (Even)</i> or <i>Offset Up (Odd)</i>.</li>
</ul>

<h3>Lines</h3>
<ul>
  <li><b>Style</b> — <i>Full Lines</i> draws complete hex outlines; <i>Crossings Only</i>
      draws short marks at hex corners only.</li>
  <li><b>Line Width</b> — stroke width of grid lines in world pixels (0.5–10).</li>
  <li><b>Edge Color</b> — color of the hex grid lines.</li>
</ul>

<h3>Center Dots</h3>
<ul>
  <li><b>Show</b> — enables center dots.</li>
  <li><b>Size</b> — dot radius (1–10).</li>
  <li><b>Color</b> — dot fill color.</li>
  <li><b>Outline / Outline Width / Outline Color</b> — optional outline ring around each dot.</li>
</ul>

<h3>Coordinates</h3>
<ul>
  <li><b>Show</b> — enables coordinate labels inside hexes.</li>
  <li><b>Position</b> — <i>Top</i> or <i>Bottom</i> of the hex interior.</li>
  <li><b>Y-Offset</b> — fine-tune vertical position (−0.5 to +0.5).</li>
  <li><b>Format</b> — <i>0101</i>, <i>01.01</i>, <i>A1</i>, or <i>1,1</i>.</li>
  <li><b>Font Size</b> — label size as percentage of hex size (5–50 %).</li>
  <li><b>Start at 1</b> — when enabled, coordinates begin at 1 instead of 0.</li>
</ul>

<h3>Border / Edges</h3>
<ul>
  <li><b>Half Hexes (tileable)</b> — crops the outer ring to half-hexes so the map
      tiles seamlessly. Mutually exclusive with Show Border.</li>
  <li><b>Show Border</b> — draws a rectangular border around the hex grid.</li>
  <li><b>Color / Margin / Fill / Fill Color</b> — border line color, spacing from the
      outermost hexes, optional background fill for the border zone.</li>
</ul>

<h3>Megahexes</h3>
<ul>
  <li><b>Enable Megahexes</b> — overlays a second, larger hex grid.</li>
  <li><b>Radius</b> — size of one megahex in normal hexes (1–10).</li>
  <li><b>Mode</b> — <i>Hex Edges</i> draws along hex boundaries; <i>Geometric</i>
      draws the theoretical larger hex outline.</li>
  <li><b>Color / Width</b> — megahex line color and width.</li>
  <li><b>Offset Q / Offset R</b> — shift the megahex lattice by axial coordinates.</li>
</ul>

<h3>Fill Color (New Map only)</h3>
<p>Sets the initial background fill color applied to all hexes on the first Fill layer.</p>

<h3>Preview</h3>
<p>The right half of the dialog shows a live hex-grid preview that updates as you
change settings. The <b>size label</b> below it shows the map dimensions in hexes
and approximate millimetres.</p>
""")

_DOCS["navigation"] = _page("Canvas Navigation", """
<h3>Zoom</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td><code>Scroll Wheel</code></td><td>Zoom in / out, anchored at the mouse cursor position (range 5 % – 1000 %).</td></tr>
  <tr><td><code>Ctrl+0</code></td><td>Zoom to Fit — fits the entire map into the window.</td></tr>
</table>

<h3>Pan</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td><code>Middle Mouse Drag</code></td><td>Pan the canvas.</td></tr>
  <tr><td><code>Right Mouse Drag</code> (&gt;5 px)</td><td>Pan the canvas (threshold prevents accidental panning on right-click).</td></tr>
</table>

<h3>Layer Peek (Hold B)</h3>
<p>While the physical <code>B</code> key is held down, the layer directly below
the currently active layer is temporarily hidden. Release <code>B</code> to
restore it. Useful for quickly checking what is underneath the active layer.</p>
<p><i>Note: B also activates the Background tool when tapped briefly. Hold it to peek.</i></p>
""")

# ── Menus ────────────────────────────────────────────────────────────────────

_DOCS["menu_file"] = _page("File Menu", """
<table>
  <tr><th>Item</th><th>Shortcut</th><th>Description</th></tr>
  <tr><td><b>New</b></td><td><code>Ctrl+N</code></td>
      <td>Creates a new empty map. Opens the New Map dialog. Prompts to save unsaved changes first.</td></tr>
  <tr><td><b>Open…</b></td><td><code>Ctrl+O</code></td>
      <td>Opens a <code>.hexmap</code> file. Prompts to save unsaved changes first.</td></tr>
  <tr><td><b>Save</b></td><td><code>Ctrl+S</code></td>
      <td>Saves the current map. Opens Save As dialog if the map has never been saved.</td></tr>
  <tr><td><b>Save As…</b></td><td><code>Ctrl+Shift+S</code></td>
      <td>Saves the map to a new file path.</td></tr>
  <tr><td><b>Export…</b></td><td><code>Ctrl+Shift+E</code></td>
      <td>Opens the Export dialog for PNG, PDF or <code>.hexmap</code> export.</td></tr>
  <tr><td><b>Exit</b></td><td><code>Alt+F4</code></td>
      <td>Closes the application. Prompts to save unsaved changes.</td></tr>
</table>
""")

_DOCS["menu_edit"] = _page("Edit Menu", """
<table>
  <tr><th>Item</th><th>Shortcut</th><th>Description</th></tr>
  <tr><td><b>Undo</b></td><td><code>Ctrl+Z</code></td>
      <td>Undoes the last action. Up to 20 undo steps are stored.</td></tr>
  <tr><td><b>Redo</b></td><td><code>Ctrl+Y</code></td>
      <td>Re-applies the last undone action.</td></tr>
  <tr><td><b>Map Settings…</b></td><td><code>Ctrl+,</code></td>
      <td>Opens the New Map dialog in settings mode — Grid and Presets are locked, all other
          options (lines, dots, coords, border, megahexes) can be changed.</td></tr>
  <tr><td><b>Edit Palettes…</b></td><td><code>Ctrl+P</code></td>
      <td>Opens the Palette Editor to manage named color sets used in the Fill tool.</td></tr>
  <tr><td><b>Calculate Grid…</b></td><td><code>Ctrl+Shift+C</code></td>
      <td>Helper dialog that calculates the required grid dimensions (columns × rows) for
          a real-world area at a given hex scale.</td></tr>
  <tr><td><b>Render Layer to Image…</b></td><td><code>Ctrl+Shift+R</code></td>
      <td>Renders the active layer to a PNG image and replaces it with an Image layer.
          See <a href="page:dlg_render_layer">Render Layer to Image</a>.</td></tr>
</table>
""")

_DOCS["menu_view"] = _page("View Menu", """
<table>
  <tr><th>Item</th><th>Shortcut</th><th>Description</th></tr>
  <tr><td><b>Zoom to Fit</b></td><td><code>Ctrl+0</code></td>
      <td>Scales and centres the view so the entire map is visible.</td></tr>
  <tr><td><b>Show Grid</b></td><td><code>Ctrl+Shift+G</code></td>
      <td>Toggles visibility of the hex grid overlay (lines, dots, coords, megahexes).</td></tr>
  <tr><td><b>Show Center Dots</b></td><td><code>Ctrl+D</code></td>
      <td>Toggles center dots independently of the grid.</td></tr>
  <tr><td><b>Show Coordinates</b></td><td><code>Ctrl+K</code></td>
      <td>Toggles hex coordinate labels.</td></tr>
  <tr><td><b>Show Megahexes</b></td><td><code>Ctrl+G</code></td>
      <td>Toggles the megahex overlay.</td></tr>
  <tr><td><b>Show Minimap</b></td><td><code>Ctrl+M</code></td>
      <td>Shows or hides the minimap in the bottom-left of the canvas.</td></tr>
  <tr><td><b>Set Background Color…</b></td><td><code>Ctrl+B</code></td>
      <td>Changes the canvas background color (the area outside and around the map). Default is <code>#2b2b2b</code>. Saved with the project.</td></tr>
  <tr><td><b>Global Lighting…</b></td><td><code>Ctrl+L</code></td>
      <td>Opens the Global Lighting dialog (non-modal). Controls a shared light direction
          and intensity that affects layer effects such as Bevel &amp; Emboss.</td></tr>
</table>

<h3>Performance Dialog</h3>
<p><b>View &gt; Performance...</b> opens a settings dialog with three pages:</p>

<h4>Cache Delay  (<code>Ctrl+Shift+D</code> to cycle)</h4>
<p>Controls how long the editor waits after an edit before rebuilding the full layer
pixmap cache. During the delay, the canvas renders directly with viewport culling
(fast, bounded by screen resolution). The cache is rebuilt once editing pauses.</p>
<ul>
  <li><b>None</b> — always rebuild immediately (best for small maps).</li>
  <li><b>50 ms / 100 ms</b> — short delay (good for small to medium maps).</li>
  <li><b>200 ms</b> (default) — balanced (good for large maps, 30&times;30+).</li>
  <li><b>500 ms</b> — long delay (best for very large maps or heavy effects).</li>
</ul>

<h4>Zoom Settle Delay  (<code>Ctrl+Shift+Z</code> to cycle)</h4>
<p>Controls how long the editor waits after zooming before rebuilding the layer
cache. During the delay the canvas uses the existing (possibly stale) cache.
The cache is rebuilt once zooming stops.</p>
<ul>
  <li><b>50 ms / 100 ms</b> — short delay (responsive, but may rebuild frequently).</li>
  <li><b>200 ms</b> (default) — balanced.</li>
  <li><b>500 ms / 1000 ms</b> — long delay (best for heavy maps with many layers).</li>
</ul>

<h4>Render Quality  (<code>Ctrl+Shift+Q</code> to toggle)</h4>
<ul>
  <li><b>Performance</b> — uses world-resolution layer caches (faster, slightly less
      sharp when zoomed in).</li>
  <li><b>Quality</b> — uses screen-resolution layer caches (sharp at every zoom level,
      but rebuilds caches on zoom changes). This is the recommended setting.</li>
</ul>

<h4>Visible GFX  (<code>Ctrl+E</code> to toggle)</h4>
<p>Toggle visibility of layer-level visual effects across all layers at once.
When unchecked, <b>Shadow</b>, <b>Bevel &amp; Emboss</b>, and <b>Structure</b>
effects are suppressed — the underlying layer content is still drawn normally.
<b>Outline</b> (Draw Layer only) is not affected.</p>
<p>This is useful when working with many layers that have expensive effects enabled,
as it can significantly reduce rendering time and eliminate lag.</p>
<p>Exports always include all effects regardless of this setting.</p>
<p>All settings are persisted in application settings across sessions.</p>
""")

_DOCS["menu_help"] = _page("Help Menu", """
<table>
  <tr><th>Item</th><th>Shortcut</th><th>Description</th></tr>
  <tr><td><b>Documentation…</b></td><td><code>F2</code></td>
      <td>Opens this documentation window.</td></tr>
  <tr><td><b>Shortcuts…</b></td><td><code>F1</code></td>
      <td>Opens the Shortcuts reference dialog listing all keyboard shortcuts and
          mouse gestures.</td></tr>
</table>
""")

# ── UI Panels ────────────────────────────────────────────────────────────────

_DOCS["panel_layers"] = _page("Layer Panel", """
<p>The <b>Layer Panel</b> sits on the left side of the main window. It lists all
layers from top (rendered last / on top) to bottom (rendered first / behind).</p>

<h3>Layer List</h3>
<ul>
  <li>Click a layer to make it <b>active</b>. The matching tool is automatically selected.</li>
  <li>The <b>eye icon</b> toggles layer visibility.</li>
  <li>The <b>opacity slider</b> on each row sets the layer's global opacity (0–100 %).</li>
  <li><b>Double-click</b> a layer name to rename it.</li>
  <li>Layers can be <b>reordered</b> by dragging.</li>
</ul>

<h3>Toolbar Buttons (below the list)</h3>
<ul>
  <li><b>Add Layer</b> — opens a dropdown to choose the layer type to add.</li>
  <li><b>Remove Layer</b> — removes the currently selected layer (with confirmation).</li>
  <li><b>Move Up / Move Down</b> — reorder the active layer.</li>
</ul>

<h3>Layer Types (icons)</h3>
<p>Each layer type has a distinct icon in the list: Image (B), Fill (F), Asset (A),
Text (T), Hexside (H), Border (O), Path (P), Freeform Path (R), Sketch (S), Draw (D).</p>
""")

_DOCS["panel_options"] = _page("Tool Options Panel", """
<p>The <b>Tool Options Panel</b> is the docked panel on the right side of the window.
It shows controls specific to the currently active tool / layer type.</p>

<h3>General Behaviour</h3>
<ul>
  <li>The panel updates automatically when a different layer is activated.</li>
  <li>Controls in the panel apply to <i>newly created</i> objects (Place/Draw mode)
      and to the <i>selected</i> object (Select mode).</li>
  <li>Some tools have a sidebar (Asset Browser, Texture Browser, Preset list) that
      slides in from the right when opened.</li>
  <li>The panel is scrollable when its content exceeds the window height.</li>
</ul>
""")

_DOCS["panel_minimap"] = _page("Minimap", """
<p>The <b>Minimap</b> is a small overview thumbnail displayed in the bottom-left
corner of the canvas.</p>
<ul>
  <li>Shows the full map at a reduced scale.</li>
  <li>The red rectangle indicates the currently visible viewport area.</li>
  <li>Click or drag inside the minimap to <b>navigate</b> to that position.</li>
  <li>Toggle via <b>View &gt; Show Minimap</b> (<code>Ctrl+M</code>).</li>
</ul>
""")

# ── Layer Types ──────────────────────────────────────────────────────────────

_DOCS["layer_background"] = _page("Background (Image) Layer", """
<p>Displays a single background image (PNG, JPG, BMP) behind all other layers.
Ideal for scanned maps, satellite photos, or reference images.</p>
<p><b>Hotkey:</b> <code>B</code></p>

<h3>Tool Options – Image</h3>
<ul>
  <li><b>Load Image…</b> — select an image file from disk.</li>
  <li><b>Cut at Edges</b> checkbox — clips the image to the hex grid boundary.</li>
  <li><b>Edit Image…</b> — opens the full-featured
      <a href="page:dlg_edit_image">Edit Image Dialog</a> for painting,
      posterizing, colour-selecting, and creating transparent coastline overlays.
      Edits are committed to the layer only when you click <b>Apply</b>.</li>
</ul>

<h3>Tool Options – Zoom</h3>
<ul>
  <li><b>Zoom slider / spinbox</b> — scale the image (1–500 %).</li>
</ul>

<h3>Tool Options – Opacity</h3>
<ul>
  <li><b>Opacity slider / spinbox</b> — overall opacity of the image layer (0–100 %).</li>
</ul>

<h3>Tool Options – Position</h3>
<ul>
  <li><b>Lock Position &amp; Zoom</b> checkbox — prevents mouse dragging and zoom
      changes. Enable to avoid accidental moves.</li>
  <li><b>Reset Position</b> — resets offset to (0, 0).</li>
  <li><b>Align Corner to Grid</b> — four buttons (<b>↖ TL</b>, <b>↗ TR</b>,
      <b>↙ BL</b>, <b>↘ BR</b>) snap the corresponding image corner to the
      matching grid corner.</li>
  <li><b>Copy Transform</b> — copies the current position, zoom, and opacity to
      the clipboard.</li>
  <li><b>Paste Transform</b> — applies a previously copied transform to this layer.</li>
</ul>

<h3>Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Drag</td><td>Reposition the image (when not locked).</td></tr>
</table>

<h3>Saving Edits</h3>
<p>When a project is saved after image edits have been applied, the edited pixels
are automatically written as a PNG file (<code>&lt;layer_id&gt;_bg_edit.png</code>)
next to the <code>.hexmap</code> project file and re-loaded automatically on the
next open.</p>
""")

_DOCS["layer_fill"] = _page("Fill Layer", """
<p>Paints hex cells with solid colors, textures, custom dot colors, or hex-edge
fills. Multiple Fill layers can be stacked for visual effects.</p>
<p><b>Hotkey:</b> <code>F</code></p>

<h3>Tool Options – Mode</h3>
<p>Select one of four target modes:</p>
<ul>
  <li><b>Hex</b> — paints full hex cells (color or texture).</li>
  <li><b>Dot Color</b> — overrides the center-dot color for individual hexes.</li>
  <li><b>Hex Edge</b> — fills specific half-edges of a hex (e.g. for coastlines).</li>
  <li><b>Coord Color</b> — overrides the coordinate label color for individual hexes.</li>
</ul>

<h3>Tool Options – Paint Mode (Hex mode only)</h3>
<p>Toggle between <b>Color</b> and <b>Texture</b>.</p>

<h3>Tool Options – Color</h3>
<ul>
  <li><b>Color button</b> — opens the color picker.</li>
  <li><b>Palette dropdown</b> — select a named palette; the color buttons below
      show palette colors for quick selection.</li>
</ul>

<h3>Tool Options – Texture</h3>
<ul>
  <li><b>Game / Category / Search</b> — filter the texture thumbnail grid.</li>
  <li><b>Manager…</b> — opens the <a href="page:dlg_textures">Texture Manager</a>.</li>
  <li><b>Expand</b> — opens a larger texture browser sidebar.</li>
  <li><b>Zoom</b> — scale the texture tile inside the hex.</li>
  <li><b>Offset X / Offset Y</b> — shift the texture tile position in pixels.</li>
  <li><b>Rotation</b> — rotate the texture tile. Preset buttons for common angles
      (0°, 60°, 90°, 120°, 180°, 270°).</li>
</ul>

<h3>Tool Options – Edge Width (Hex Edge mode only)</h3>
<ul>
  <li><b>Width slider / spinbox</b> — edge fill thickness. Preset buttons
      (0.5, 1, 2, 3, 5).</li>
  <li><b>Outline</b> checkbox — enables an outline around the edge fill.</li>
  <li><b>Outline Color / Width</b> — outline appearance.</li>
</ul>

<h3>Tool Options – Radius</h3>
<ul>
  <li><b>Radius slider / spinbox</b> — 0 = single hex; 1+ = paints all hexes
      within that hex-distance radius. Preset buttons (0, 1, 2, 3, 5, 10).</li>
</ul>

<h3>Tool Options – Fill All</h3>
<ul>
  <li><b>Fill Everything</b> button — fills every hex on the map with the current
      color or texture in one action.</li>
</ul>

<h3>Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click / Drag</td><td>Fill hex(es) with the current color/texture.</td></tr>
  <tr><td>Right Click / Drag</td><td>Clear fill from hex(es).</td></tr>
</table>
""")

_DOCS["layer_asset"] = _page("Asset Layer", """
<p>Places, scales, and rotates PNG/JPG image assets (counters, unit symbols, icons)
anywhere on the map. Supports a non-destructive erase mask to hide parts of the
layer.</p>
<p><b>Hotkey:</b> <code>A</code></p>

<h3>Modes</h3>
<p>Switch with the <b>Place / Select / Erase</b> buttons at the top of the panel.</p>

<h3>Place Mode — Assets</h3>
<ul>
  <li><b>Asset Browser</b> — grid of thumbnails, filterable by Game, Category,
      and a Search box. Click a thumbnail to select it as the pending asset.
      The <b>Expand</b> button opens a larger sidebar browser.</li>
</ul>

<h3>Place Mode — Placement</h3>
<ul>
  <li><b>Snap to Hex</b> — snaps the asset center to the nearest hex center.</li>
  <li><b>Rasterize</b> — snaps to a radial grid of edge midpoints or corners
      relative to the nearest hex. Sub-options:
    <ul>
      <li><b>Mode</b> — Edge or Corner snap points.</li>
      <li><b>Fixed Position</b> checkbox + <b>%</b> spinbox — locks the snap
          distance to a fixed percentage along the radial line.</li>
    </ul>
  </li>
  <li><b>Radius</b> — places the asset simultaneously on all hexes within the
      given radius (requires Snap to Hex).</li>
</ul>

<h3>Place Mode — Scale</h3>
<ul>
  <li><b>Scale slider / spinbox</b> — uniform scale factor (0.05–10).</li>
  <li><b>Random Size</b> checkbox — randomises scale between <b>Min</b> and <b>Max</b>
      for each placement.</li>
</ul>

<h3>Place Mode — Rotation</h3>
<ul>
  <li><b>Rotation slider / spinbox</b> — rotation in degrees.</li>
  <li><b>Random Rotation</b> checkbox — randomises rotation 0–360° per placement.</li>
  <li><b>Preset buttons</b> — two rows of 30° steps
      (0°, 30°, 60°, 90°, 120°, 150° and 180°, 210°, 240°, 270°, 300°, 330°).</li>
</ul>

<h3>Place Mode — Randomize Assets</h3>
<ul>
  <li><b>Randomize Assets</b> checkbox — each placement picks a random asset
      from the current selection pool.</li>
</ul>

<h3>Place Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click</td><td>Place the selected asset.</td></tr>
  <tr><td>Right Click</td><td>Delete the asset under the cursor.</td></tr>
  <tr><td><code>Ctrl</code> + Left Drag (up/down)</td><td>Adjust placement scale on the fly.</td></tr>
  <tr><td><code>Alt</code> + Left Drag (left/right)</td><td>Adjust placement rotation on the fly.</td></tr>
</table>

<h3>Select Mode</h3>
<p>Click an asset to select it. The Tool Options panel shows its properties:</p>
<ul>
  <li><b>Position X / Y</b> — exact world-pixel coordinates.</li>
  <li><b>Scale</b> — current scale factor.</li>
  <li><b>Rotation</b> — current rotation in degrees.</li>
</ul>
<h3>Select Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click (body)</td><td>Select asset / start move drag.</td></tr>
  <tr><td>Drag body</td><td>Move asset.</td></tr>
  <tr><td>Drag corner handle (white square)</td><td>Scale asset from corner.</td></tr>
  <tr><td>Drag green circle handle</td><td>Rotate asset.</td></tr>
  <tr><td><code>Delete</code></td><td>Remove selected asset.</td></tr>
  <tr><td><code>Escape</code></td><td>Deselect.</td></tr>
</table>

<h3>Erase Mode</h3>
<p>Paints a non-destructive mask over the asset layer using a circular brush.
The mask is per-layer and global (not per-asset). Supports undo/redo.</p>
<ul>
  <li><b>Size slider / spinbox</b> — erase brush diameter (5–300 px).</li>
  <li><b>Clear Mask</b> button — removes the entire erase mask, restoring all assets.</li>
</ul>
<h3>Erase Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Drag</td><td>Erase (paint the mask).</td></tr>
  <tr><td><code>Ctrl</code> + Left Drag (up/down)</td><td>Adjust erase brush size.</td></tr>
</table>

<h3>Shadow</h3>
<p>Layer-level drop shadow applied to all assets on the layer:</p>
<ul>
  <li><b>Enable</b> checkbox</li>
  <li><b>Type</b> — Outer or Inner shadow.</li>
  <li><b>Color / Opacity / Angle / Distance / Spread / Size</b> — standard shadow parameters.</li>
</ul>

<h3>Auto-Text</h3>
<p>Automatically prompts for a text label after each single-asset placement:</p>
<ul>
  <li><b>Enable</b> checkbox</li>
  <li><b>Preset</b> — text style preset to use for the label.</li>
  <li><b>Target Layer</b> — the Text layer to place the label on.</li>
  <li><b>Y-Offset</b> — vertical offset of the label relative to the asset center.</li>
</ul>
""")

_DOCS["layer_text"] = _page("Text Layer", """
<p>Places freely positioned text annotations. Each text object is independent and
can be styled, rotated, and scaled individually.</p>
<p><b>Hotkey:</b> <code>T</code></p>

<h3>Modes</h3>
<p>Switch with the <b>Place / Select</b> buttons.</p>

<h3>Place Mode</h3>
<p>Left-click on the canvas to open an input dialog. Type the text, click OK, and
the text is placed at the clicked position using the current style settings.
Right-click deletes the text object under the cursor.</p>

<h3>Tool Options – Presets</h3>
<ul>
  <li><b>Preview</b> — shows a live preview of the current text style.</li>
  <li><b>Preset combo</b> — select a saved text style.</li>
  <li><b>Expand</b> — opens a preset browser sidebar.</li>
  <li><b>Load</b> — apply the selected preset to all style fields.</li>
  <li><b>Save / Del</b> buttons — manage user presets. Built-in presets (from
      the <code>assets/presets/text/</code> folder) cannot be deleted.</li>
</ul>

<h3>Tool Options – Text</h3>
<ul>
  <li><b>Content</b> — text to place (editable inline).</li>
  <li><b>Font</b> — font family combobox.</li>
  <li><b>Size</b> — font size in points.</li>
  <li><b>B / I / U</b> checkboxes — Bold, Italic, Underline.</li>
</ul>

<h3>Tool Options – Style</h3>
<ul>
  <li><b>Color</b> button — text color.</li>
  <li><b>Align</b> combo — Left / Center / Right.</li>
  <li><b>Opacity</b> — text opacity (0–100 %).</li>
  <li><b>Rotation</b> — rotation in degrees. Preset buttons
      (0°, 45°, 90°, 180°, 270°).</li>
</ul>

<h3>Tool Options – Outline</h3>
<ul>
  <li><b>Enable Outline</b> checkbox</li>
  <li><b>Color</b> button — outline color.</li>
  <li><b>Width</b> — outline thickness.</li>
</ul>

<h3>Tool Options – Rendering</h3>
<ul>
  <li><b>Draw over Grid</b> checkbox — renders the text <i>above</i> the hex grid
      overlay instead of below it.</li>
</ul>

<h3>Tool Options – Shadow</h3>
<ul>
  <li><b>Enable Shadow</b> checkbox</li>
  <li><b>Type</b> — Outer or Inner shadow.</li>
  <li><b>Color / Opacity / Angle / Distance / Spread / Size</b> — standard
      shadow parameters.</li>
</ul>

<h3>Select Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click (body)</td><td>Select text / start move.</td></tr>
  <tr><td>Double Click</td><td>Open text edit dialog.</td></tr>
  <tr><td>Drag corner handle</td><td>Scale font size.</td></tr>
  <tr><td>Drag green circle handle</td><td>Rotate.</td></tr>
  <tr><td><code>F2</code></td><td>Edit text content.</td></tr>
  <tr><td><code>Delete</code></td><td>Remove selected text.</td></tr>
  <tr><td><code>Escape</code></td><td>Deselect.</td></tr>
</table>
""")

_DOCS["layer_hexside"] = _page("Hexside Layer", """
<p>Draws styled lines along individual hex edges. Used for roads, rivers, borders,
cliff edges, and other hex-side features.</p>
<p><b>Hotkey:</b> <code>H</code></p>

<h3>Modes</h3>
<p><b>Place / Select</b> buttons.</p>

<h3>Place Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Drag</td><td>Paint hexside edges along the path.</td></tr>
  <tr><td>Right Click</td><td>Delete the hexside under the cursor.</td></tr>
</table>

<h3>Tool Options – Presets</h3>
<ul>
  <li><b>Preview</b> — shows a live preview of the current hexside style.</li>
  <li><b>Preset combo</b> — select a saved hexside style.</li>
  <li><b>Expand</b> — opens a preset browser sidebar.</li>
  <li><b>Load / Save / Del</b> — manage presets. Built-in presets are read-only.</li>
</ul>

<h3>Tool Options – Paint Mode</h3>
<p>Toggle between <b>Color</b> and <b>Texture</b>.</p>

<h3>Tool Options – Color</h3>
<ul>
  <li><b>Color button</b> — line color.</li>
  <li><b>Palette dropdown</b> — select a palette for quick color selection.</li>
</ul>

<h3>Tool Options – Texture</h3>
<ul>
  <li><b>Game / Category / Search</b> — filter the texture thumbnail grid.</li>
  <li><b>Manager…</b> — opens the <a href="page:dlg_textures">Texture Manager</a>.</li>
  <li><b>Expand</b> — opens a larger texture browser sidebar.</li>
  <li><b>Zoom</b> — scale the texture along the hexside.</li>
  <li><b>Rotation</b> — rotate the texture. Preset buttons for common angles.</li>
</ul>

<h3>Tool Options – Width &amp; Opacity</h3>
<ul>
  <li><b>Width slider / spinbox</b> — line thickness.</li>
  <li><b>Opacity slider / spinbox</b> — line opacity (0–100 %).</li>
</ul>

<h3>Tool Options – Outline</h3>
<ul>
  <li><b>Enable Outline</b> checkbox</li>
  <li><b>Paint Mode</b> — toggle between <b>Color</b> and <b>Texture</b> for the outline.</li>
  <li><b>Color</b> button — outline color. Includes a palette dropdown.</li>
  <li><b>Texture</b> section (when Texture mode selected) — Game / Category / Search
      filter with thumbnail grid, <b>Manager…</b> and <b>Expand</b> buttons,
      <b>Zoom</b> and <b>Rotation</b> sliders with preset buttons
      (0°, 60°, 90°, 120°, 180°, 270°).</li>
  <li><b>Width</b> — outline thickness.</li>
  <li><b>Opacity</b> — outline opacity (0–100 %).</li>
</ul>

<h3>Tool Options – Shift</h3>
<ul>
  <li><b>Enable Auto-Shift</b> checkbox — perpendicular offset of the line from
      the hex edge centre.</li>
  <li><b>Shift slider / spinbox</b> — amount of perpendicular offset.</li>
</ul>

<h3>Tool Options – Random</h3>
<ul>
  <li><b>Enable Random</b> checkbox — adds procedural waviness to the line.</li>
  <li><b>Amplitude</b> — strength of the waviness.</li>
  <li><b>Offset</b> — perpendicular displacement offset.</li>
  <li><b>Distance</b> — controls the frequency of the waviness.</li>
  <li><b>Endpoints</b> — randomly offsets line endpoints.</li>
  <li><b>Jitter</b> — adds additional micro-variation to the line.</li>
</ul>

<h3>Tool Options – Taper</h3>
<ul>
  <li><b>Taper Free Ends</b> checkbox — when enabled, hexside endpoints that are not
      connected to another hexside will automatically narrow from full width to zero,
      creating a natural fade-out. Connected endpoints stay at full width.</li>
  <li><b>Length</b> — fraction of the hexside path over which the taper occurs
      (0.1 = short taper at the tip, 1.0 = taper along the entire line).
      Both the main line and its outline are tapered together.</li>
</ul>

<h3>Tool Options – Shadow</h3>
<ul>
  <li><b>Enable Shadow</b> checkbox</li>
  <li><b>Type</b> — Outer or Inner shadow.</li>
  <li><b>Color / Opacity / Angle / Distance / Spread / Size</b> — standard
      shadow parameters.</li>
</ul>

<h3>Tool Options – Bevel &amp; Emboss</h3>
<p>Adds 3D relief effects to the hexside lines. Shares a common <b>Angle</b>
slider for both sub-effects.</p>
<ul>
  <li><b>Angle</b> slider — light direction (0–360°). Affects both Bevel and
      Structure.</li>
</ul>
<p><b>Enable Bevel</b> checkbox — adds a bevel (highlight + shadow) edge effect:</p>
<ul>
  <li><b>Type</b> — Inner or Outer bevel.</li>
  <li><b>Size</b> — bevel width.</li>
  <li><b>Depth</b> — intensity of the bevel effect.</li>
  <li><b>Highlight</b> — colour and opacity of the lit edge.</li>
  <li><b>Shadow</b> — colour and opacity of the shaded edge.</li>
</ul>
<p><b>Enable Structure</b> checkbox — overlays a bump-mapped texture:</p>
<ul>
  <li><b>Texture</b> combo — select a texture from the texture library.</li>
  <li><b>Scale</b> — texture tile scale (0.1–10.0).</li>
  <li><b>Depth</b> — strength of the bump-map relief (0–100).</li>
  <li><b>Invert</b> checkbox — inverts the bump-map direction.</li>
</ul>

<h3>Select Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click</td><td>Select hexside.</td></tr>
  <tr><td>Drag endpoint (circle handle)</td><td>Move the endpoint or control point.</td></tr>
  <tr><td><code>Delete</code></td><td>Remove selected hexside.</td></tr>
  <tr><td><code>Escape</code></td><td>Deselect.</td></tr>
</table>
""")

_DOCS["layer_border"] = _page("Border Layer", """
<p>Draws thick decorative lines along hex edges, typically used for zone borders,
territory boundaries, or map edges.</p>
<p><b>Hotkey:</b> <code>O</code></p>

<h3>Modes</h3>
<p><b>Place / Select</b> buttons.</p>

<h3>Place Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Drag</td><td>Paint border edges.</td></tr>
  <tr><td>Right Click</td><td>Delete border edge under cursor.</td></tr>
</table>

<h3>Tool Options – Presets</h3>
<ul>
  <li><b>Preview</b> — shows a live preview of the current border style.</li>
  <li><b>Preset combo</b> — select a saved border style.</li>
  <li><b>Expand</b> — opens a preset browser sidebar.</li>
  <li><b>Load / Save / Del</b> — manage presets. Built-in presets are read-only.</li>
</ul>

<h3>Tool Options – Color</h3>
<ul>
  <li><b>Color button</b> — border line color.</li>
  <li><b>Palette dropdown</b> — select a palette for quick color selection.</li>
</ul>

<h3>Tool Options – Width</h3>
<ul>
  <li><b>Width slider / spinbox</b> — border line thickness.</li>
</ul>

<h3>Tool Options – Line Type</h3>
<ul>
  <li><b>Type combo</b> — Solid / Dotted / Dashed.</li>
  <li><b>Element Size</b> — length of each dash or dot diameter (Dashed / Dotted only).</li>
  <li><b>Gap Size</b> — space between elements (Dashed / Dotted only).</li>
  <li><b>Cap</b> combo — Flat / Round / Square line end caps.</li>
</ul>

<h3>Tool Options – Outline</h3>
<ul>
  <li><b>Enable Outline</b> checkbox</li>
  <li><b>Color</b> button — outline color.</li>
  <li><b>Width</b> — outline thickness.</li>
</ul>

<h3>Tool Options – Offset</h3>
<ul>
  <li><b>Offset slider / spinbox</b> — shift the border line toward the inside or
      outside of the hex boundary.</li>
</ul>

<h3>Tool Options – Shadow</h3>
<ul>
  <li><b>Enable Shadow</b> checkbox</li>
  <li><b>Type</b> — Outer or Inner shadow.</li>
  <li><b>Color / Opacity / Angle / Distance / Spread / Size</b> — standard
      shadow parameters.</li>
</ul>

<h3>Select Mode</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click</td><td>Select border.</td></tr>
  <tr><td><code>Delete</code></td><td>Remove selected border.</td></tr>
  <tr><td><code>Escape</code></td><td>Deselect.</td></tr>
</table>
""")

_DOCS["layer_path"] = _page("Path Layer (Center-to-Center)", """
<p>Draws lines connecting hex centers. Used for roads, supply lines, movement
paths, rail lines, etc. Each path connects exactly two hex centers.</p>
<p><b>Hotkey:</b> <code>P</code></p>

<h3>Modes</h3>
<p><b>Place / Select</b> buttons.</p>

<h3>Place Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click / Drag</td><td>Paint paths between hex centers.</td></tr>
  <tr><td>Right Click</td><td>Delete the path under the cursor.</td></tr>
</table>

<h3>Tool Options – Presets</h3>
<ul>
  <li><b>Preview</b> — shows a live preview of the current path style.</li>
  <li><b>Preset combo</b> — select a saved path style (shared pool with Freeform Path).</li>
  <li><b>Expand</b> — opens a preset browser sidebar.</li>
  <li><b>Load / Save / Del</b> — manage presets. Built-in presets are read-only.</li>
</ul>

<h3>Tool Options – Paint Mode</h3>
<p>Toggle between <b>Color</b> and <b>Texture</b>.</p>

<h3>Tool Options – Color</h3>
<ul>
  <li><b>Color button</b> — foreground line color.</li>
  <li><b>Palette dropdown</b> — select a palette for quick color selection.</li>
</ul>

<h3>Tool Options – Texture</h3>
<ul>
  <li><b>Game / Category / Search</b> — filter the texture thumbnail grid.</li>
  <li><b>Manager…</b> — opens the <a href="page:dlg_textures">Texture Manager</a>.</li>
  <li><b>Expand</b> — opens a larger texture browser sidebar.</li>
  <li><b>Zoom</b> — scale the texture along the path.</li>
  <li><b>Rotation</b> — rotate the texture. Preset buttons for common angles.</li>
</ul>

<h3>Tool Options – Mainpath</h3>
<ul>
  <li><b>Width</b> slider / spinbox — foreground line thickness.</li>
  <li><b>Opacity</b> slider — foreground line opacity (0–100 %).</li>
  <li><b>Type</b> combo — Solid / Dashed / Dotted.</li>
  <li><b>Dash / Gap</b> — visible when Dashed or Dotted.</li>
  <li><b>Cap</b> combo — Flat / Round / Square line end caps.</li>
</ul>

<h3>Tool Options – Background Path</h3>
<ul>
  <li><b>Enable Background Path</b> checkbox — adds a second, wider line behind
      the foreground line.</li>
  <li><b>Paint Mode</b> — toggle between <b>Color</b> and <b>Texture</b>.</li>
  <li><b>Color</b> button — background path color. Includes palette dropdown.</li>
  <li><b>Texture</b> section (when Texture mode selected) — Game / Category / Search
      filter with thumbnail grid, <b>Manager…</b> and <b>Expand</b> buttons,
      <b>Zoom</b> and <b>Rotation</b> sliders with preset buttons.</li>
  <li><b>Width</b> — background path thickness.</li>
  <li><b>Type</b> — Solid / Dashed / Dotted.</li>
  <li><b>Dash / Gap</b> — visible when Dashed or Dotted.</li>
  <li><b>Cap</b> combo — Flat / Round / Square.</li>
  <li><b>Opacity</b> — background path opacity (0–100 %).</li>
</ul>

<h3>Tool Options – Random</h3>
<ul>
  <li><b>Enable Random</b> checkbox — adds procedural waviness to the path.</li>
  <li><b>Amplitude</b> — strength of the waviness.</li>
  <li><b>Offset</b> — perpendicular displacement offset.</li>
  <li><b>Distance</b> — controls the frequency of the waviness.</li>
  <li><b>Endpoint</b> — randomly offsets path endpoints from the exact hex center.</li>
  <li><b>Jitter</b> — adds additional micro-variation.</li>
</ul>

<h3>Tool Options – Shadow</h3>
<ul>
  <li><b>Enable Shadow</b> checkbox</li>
  <li><b>Type</b> — Outer or Inner shadow.</li>
  <li><b>Color / Opacity / Angle / Distance / Spread / Size</b> — standard
      shadow parameters.</li>
</ul>

<h3>Select Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click</td><td>Select path.</td></tr>
  <tr><td>Drag endpoint handle</td><td>Move the path endpoint (syncs connected paths).</td></tr>
  <tr><td>Drag inner control point</td><td>Bend the path curve.</td></tr>
  <tr><td><code>Delete</code></td><td>Remove selected path.</td></tr>
  <tr><td><code>Escape</code></td><td>Deselect.</td></tr>
</table>
""")

_DOCS["layer_freeform"] = _page("Freeform Path Layer", """
<p>Draws hand-drawn, freely placed paths with automatic Catmull-Rom smoothing.
Unlike the Center path tool, freeform paths are not tied to hex centers.</p>
<p><b>Hotkey:</b> <code>R</code></p>

<h3>Modes</h3>
<p><b>Draw / Select</b> buttons.</p>

<h3>Draw Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Drag</td><td>Draw a freehand path. Points are sampled every 2 px.</td></tr>
  <tr><td><code>Shift</code> + Left Click</td><td>Add a waypoint to a straight-line polyline.</td></tr>
  <tr><td>Left Click (during polyline)</td><td>Add a final point and commit the polyline.</td></tr>
  <tr><td>Right Click (during polyline)</td><td>Cancel the pending polyline.</td></tr>
  <tr><td>Right Click</td><td>Delete the path under the cursor.</td></tr>
</table>

<h3>Draw Mode — Keyboard</h3>
<table>
  <tr><th>Key</th><th>Action</th></tr>
  <tr><td><code>Enter / Return</code></td><td>Commit the pending polyline.</td></tr>
  <tr><td><code>Escape</code></td><td>Cancel the pending polyline.</td></tr>
</table>

<p>On mouse release (freehand), <b>Douglas-Peucker simplification</b> is applied automatically.
The <b>Smoothness</b> slider controls how aggressively points are removed
(higher = smoother, fewer waypoints). Shift+Click polylines are not simplified.</p>

<p>While placing Shift+Click points, a <b>dashed preview line</b> follows the mouse
from the last placed point to the current cursor position, showing where the
next segment will go.</p>

<h3>Tool Options – Presets</h3>
<ul>
  <li><b>Preview</b> — shows a live preview of the current path style.</li>
  <li><b>Preset combo</b> — select a saved path style (shared pool with Center Path).</li>
  <li><b>Expand</b> — opens a preset browser sidebar.</li>
  <li><b>Load / Save / Del</b> — manage presets. Built-in presets are read-only.</li>
</ul>

<h3>Tool Options – Smoothness</h3>
<ul>
  <li><b>Smoothness slider / spinbox</b> — controls the Douglas-Peucker epsilon
      (simplification tolerance). Range 0–1.</li>
</ul>

<h3>Tool Options – Paint Mode</h3>
<p>Toggle between <b>Color</b> and <b>Texture</b>.</p>

<h3>Tool Options – Color</h3>
<ul>
  <li><b>Color button</b> — foreground line color.</li>
  <li><b>Palette dropdown</b> — select a palette for quick color selection.</li>
</ul>

<h3>Tool Options – Texture</h3>
<ul>
  <li><b>Game / Category / Search</b> — filter the texture thumbnail grid.</li>
  <li><b>Manager…</b> — opens the <a href="page:dlg_textures">Texture Manager</a>.</li>
  <li><b>Expand</b> — opens a larger texture browser sidebar.</li>
  <li><b>Zoom</b> — scale the texture along the path.</li>
  <li><b>Rotation</b> — rotate the texture. Preset buttons for common angles.</li>
</ul>

<h3>Tool Options – Mainpath</h3>
<ul>
  <li><b>Width</b> slider / spinbox — foreground line thickness.</li>
  <li><b>Opacity</b> slider — foreground line opacity (0–100 %).</li>
  <li><b>Type</b> combo — Solid / Dashed / Dotted.</li>
  <li><b>Dash / Gap</b> — visible when Dashed or Dotted.</li>
  <li><b>Cap</b> combo — Flat / Round / Square line end caps.</li>
</ul>

<h3>Tool Options – Background Path</h3>
<ul>
  <li><b>Enable Background Path</b> checkbox — adds a second, wider line behind
      the foreground line.</li>
  <li><b>Paint Mode</b> — toggle between <b>Color</b> and <b>Texture</b>.</li>
  <li><b>Color</b> button — background path color. Includes palette dropdown.</li>
  <li><b>Texture</b> section (when Texture mode selected) — Game / Category / Search
      filter with thumbnail grid, <b>Manager…</b> and <b>Expand</b> buttons,
      <b>Zoom</b> and <b>Rotation</b> sliders with preset buttons.</li>
  <li><b>Width / Type / Dash / Gap / Cap</b> — same options as foreground.</li>
  <li><b>Opacity</b> — background path opacity (0–100 %).</li>
</ul>

<h3>Tool Options – Shadow</h3>
<ul>
  <li><b>Enable Shadow</b> checkbox</li>
  <li><b>Type</b> — Outer or Inner shadow.</li>
  <li><b>Color / Opacity / Angle / Distance / Spread / Size</b> — standard
      shadow parameters.</li>
</ul>

<h3>Select Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click</td><td>Select path; waypoint handles appear.</td></tr>
  <tr><td>Drag waypoint handle</td><td>Move individual waypoint.</td></tr>
  <tr><td><code>Delete</code></td><td>Remove selected path.</td></tr>
  <tr><td><code>Escape</code></td><td>Deselect.</td></tr>
</table>
""")

_DOCS["layer_sketch"] = _page("Sketch Layer", """
<p>Draws geometric shapes (rectangles, ellipses, polygons, lines, freehand) as
administrative overlays — e.g. attack arrows, objective markers, area highlights.</p>
<p><b>Hotkey:</b> <code>S</code></p>

<h3>Tool Options – Mode</h3>
<ul>
  <li><b>Draw / Select</b> buttons — switch between drawing new shapes and
      selecting existing ones.</li>
  <li><b>Draw over Grid</b> checkbox — renders the object above the hex grid overlay.</li>
</ul>

<h3>Tool Options – Shape</h3>
<p><b>Type</b> combo — choose from: <b>Line</b>, <b>Rectangle</b>, <b>Polygon</b>,
<b>Ellipse</b>, <b>Freehand</b>.</p>
<ul>
  <li><b>Polygon</b> — additional <b>Sides</b> spinbox (3–12).</li>
  <li><b>Freehand</b> — additional <b>Close Path</b> checkbox (closes the path).</li>
  <li><b>Ellipse</b> — additional <b>Perfect Circle</b> checkbox (constrains
      the shape to a perfect circle).</li>
  <li><b>Snap to Grid</b> checkbox — snaps shape points to the nearest hex center
      or hex corner.</li>
</ul>

<h3>Tool Options – Stroke</h3>
<ul>
  <li><b>Color</b> button — stroke color.</li>
  <li><b>Width</b> slider / spinbox — stroke thickness.</li>
  <li><b>Type</b> combo — Solid / Dashed / Dotted.</li>
  <li><b>Dash / Gap</b> — visible when Dashed or Dotted.</li>
  <li><b>Cap</b> combo — Flat / Round / Square line end caps.</li>
</ul>

<h3>Tool Options – Fill</h3>
<ul>
  <li><b>Enable Fill</b> checkbox</li>
  <li><b>Type</b> — toggle between <b>Color</b> and <b>Texture</b>.</li>
  <li><b>Color</b> — fill color picker (Color mode).</li>
  <li><b>Texture</b> — Game / Category / Search filter with thumbnail grid,
      <b>Zoom</b> and <b>Rotation</b> spinboxes, rotation preset buttons
      (Texture mode).</li>
  <li><b>Opacity</b> — fill opacity (0–100 %).</li>
</ul>

<h3>Tool Options – Shadow</h3>
<ul>
  <li><b>Enable Shadow</b> checkbox</li>
  <li><b>Type</b> — Outer or Inner.</li>
  <li><b>Color / Opacity / Angle / Distance / Spread / Size</b> — standard
      shadow parameters.</li>
</ul>

<h3>Tool Options – Rotation</h3>
<ul>
  <li><b>Rotation slider / spinbox</b> — pre-set rotation for newly drawn shapes.</li>
  <li><b>Preset buttons</b> — 0°, 45°, 90°, 180°, 270°.</li>
</ul>

<h3>Draw Mode — Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Drag</td><td>Draw the shape (drag defines bounding box / path).</td></tr>
  <tr><td>Right Click</td><td>Delete shape under cursor.</td></tr>
</table>

<h3>Select Mode — Mouse Gestures &amp; Keys</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click (body)</td><td>Select object.</td></tr>
  <tr><td>Drag body</td><td>Move object.</td></tr>
  <tr><td>Drag corner handle</td><td>Resize object.</td></tr>
  <tr><td>Drag green circle handle</td><td>Rotate object.</td></tr>
  <tr><td><code>Ctrl+C</code></td><td>Copy selected object.</td></tr>
  <tr><td><code>Ctrl+V</code></td><td>Paste copied object (+10 px offset).</td></tr>
  <tr><td><code>Delete</code></td><td>Remove selected object.</td></tr>
  <tr><td><code>Escape</code></td><td>Deselect.</td></tr>
</table>
""")

_DOCS["layer_draw"] = _page("Draw Layer", """
<p>Freeform brush painting — similar to a raster paint tool. Uses a
<b>channel-mask</b> system: each channel has its own color or texture and a
painted alpha mask.</p>
<p><b>Hotkey:</b> <code>D</code></p>

<h3>Tool Options – Mode</h3>
<ul>
  <li><b>Draw</b> — paint brush strokes onto the active channel.</li>
  <li><b>Fill</b> — flood-fill the active channel with color/texture.
      The <b>Expand</b> slider (visible in Fill mode) controls how many pixels
      the fill area is expanded outward.</li>
  <li><b>Erase</b> — erase painted regions from the active channel.
      Also toggleable via the <code>E</code> key.</li>
</ul>

<h3>Tool Options – Channels</h3>
<p>A list of named channels within the layer:</p>
<ul>
  <li><b>Visible</b> checkbox — toggle channel visibility.</li>
  <li><b>Double-click name</b> — rename the channel.</li>
  <li><b>Add</b> button — add a new channel.</li>
  <li><b>Del</b> button — remove the selected channel (<code>Delete</code> key also works).</li>
  <li><b>Up / Down</b> buttons — reorder channels (top channel renders on top).</li>
  <li><b>Expand</b> — opens a larger channel sidebar.</li>
</ul>

<h3>Tool Options – Brush</h3>
<ul>
  <li><b>Brush selector</b> — thumbnail grid of brush shapes. Includes built-in
      brushes (from <code>assets/brushes/</code>) and user brushes
      (PNG files in <code>%APPDATA%\\WargameMapTool\\brushes\\</code>).</li>
  <li><b>Manager…</b> — opens the brush manager.</li>
  <li><b>Expand</b> — opens a larger brush browser sidebar.</li>
  <li><b>Size</b> slider / spinbox — brush diameter in world pixels (0.1–500).
      Also adjustable via <code>Ctrl</code> + Left Drag (up = larger).</li>
  <li><b>Random</b> checkbox — randomises the brush size per stroke between
      <b>Min</b> and <b>Max</b>. The current random size is shown in the
      Size spinbox after each click.</li>
  <li><b>Hardness</b> slider / spinbox — edge softness. 1.0 = hard edge,
      0.0 = fully soft (Gaussian fade).
      Also adjustable via <code>Alt</code> + Left Drag.</li>
  <li><b>Flow</b> slider / spinbox — paint accumulation per stamp (0.01–1.0).
      Also adjustable via <code>Shift</code> + Left Drag.</li>
</ul>

<h3>Tool Options – Channel Content</h3>
<p>Toggle between <b>Color</b> and <b>Texture</b> mode for the active channel.</p>

<h3>Tool Options – Color</h3>
<ul>
  <li><b>Color button</b> — channel fill color.</li>
  <li><b>Palette dropdown</b> — select a palette for quick color selection.</li>
  <li><b>Opacity</b> — channel opacity (0–100 %).</li>
</ul>

<h3>Tool Options – Texture</h3>
<ul>
  <li><b>Game / Category / Search</b> — filter the texture thumbnail grid.</li>
  <li><b>Manager…</b> — opens the <a href="page:dlg_textures">Texture Manager</a>.</li>
  <li><b>Expand</b> — opens a larger texture browser sidebar.</li>
  <li><b>Zoom</b> — scale the texture (0.1–5.0×).</li>
  <li><b>Rotation</b> — rotate the texture (0–359°).</li>
  <li><b>Opacity</b> — channel opacity (0–100 %).</li>
</ul>

<h3>Tool Options – Outline</h3>
<ul>
  <li><b>Enable Outline</b> checkbox</li>
  <li><b>Color</b> button — outline color.</li>
  <li><b>Width</b> — outline thickness.</li>
</ul>

<h3>Tool Options – Shadow</h3>
<ul>
  <li><b>Enable Shadow</b> checkbox</li>
  <li><b>Type</b> — Outer or Inner shadow.</li>
  <li><b>Color / Opacity / Angle / Distance / Spread / Size</b> — standard
      shadow parameters.</li>
</ul>

<h3>Tool Options – Bevel &amp; Emboss</h3>
<p>Adds 3D relief effects to the painted regions. Shares a common <b>Angle</b>
slider for both sub-effects.</p>
<ul>
  <li><b>Angle</b> slider — light direction (0–360°). Affects both Bevel and
      Structure.</li>
</ul>
<p><b>Enable Bevel</b> checkbox — adds a bevel (highlight + shadow) edge effect:</p>
<ul>
  <li><b>Type</b> — Inner or Outer bevel.</li>
  <li><b>Size</b> — bevel width.</li>
  <li><b>Depth</b> — intensity of the bevel effect (0–1).</li>
  <li><b>Highlight</b> — colour and opacity of the lit edge.</li>
  <li><b>Shadow</b> — colour and opacity of the shaded edge.</li>
</ul>
<p><b>Enable Structure</b> checkbox — overlays a bump-mapped texture on painted
regions:</p>
<ul>
  <li><b>Texture</b> combo — select a texture from the texture library.</li>
  <li><b>Scale</b> — texture tile scale (0.1–10.0).</li>
  <li><b>Depth</b> — strength of the bump-map relief (0–100).</li>
  <li><b>Invert</b> checkbox — inverts the bump-map direction.</li>
</ul>

<h3>Mouse Gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Drag</td><td>Paint brush strokes onto the active channel.</td></tr>
  <tr><td><code>Shift</code> + Left Click</td><td>Draw straight line from last stroke endpoint.</td></tr>
  <tr><td><code>Ctrl</code> + Left Drag (up/down)</td><td>Adjust brush size.</td></tr>
  <tr><td><code>Alt</code> + Left Drag (up/down)</td><td>Adjust hardness.</td></tr>
  <tr><td><code>Shift</code> + Left Drag (up/down)</td><td>Adjust flow.</td></tr>
  <tr><td><code>E</code></td><td>Toggle draw / erase mode.</td></tr>
</table>
""")

# ── Dialogs ──────────────────────────────────────────────────────────────────

_DOCS["dlg_settings"] = _page("Map Settings Dialog", """
<p>Opened via <b>Edit &gt; Map Settings</b> (<code>Ctrl+,</code>). Uses the same
interface as the New Map dialog, but the <b>Grid</b> and <b>Presets</b> groups
are disabled — only visual settings can be changed on an existing map.</p>
<p>Changes take effect immediately when you click <b>Apply</b>. The canvas
and all layers repaint to reflect the new settings.</p>
<p>See the <b>New Map Dialog</b> page for a full description of all controls.</p>
""")

_DOCS["dlg_export"] = _page("Export Dialog", """
<p>Opened via <b>File &gt; Export…</b> (<code>Ctrl+Shift+E</code>).</p>

<h3>Format</h3>
<ul>
  <li><b>PNG (raster image)</b> — exports a pixel image.</li>
  <li><b>PDF (vector)</b> — exports a vector PDF. The page size exactly matches the map.</li>
  <li><b>Hexmap (project file)</b> — saves a copy of the project as a standalone
      <code>.hexmap</code> JSON file without altering the current save path.</li>
</ul>

<h3>Content (PNG and PDF only)</h3>
<ul>
  <li><b>Show Grid</b> — include the hex grid lines in the export.</li>
  <li><b>Show Center Dots</b> — include center dots.</li>
  <li><b>Show Coordinates</b> — include coordinate labels.</li>
</ul>

<h3>Resolution (PNG only)</h3>
<ul>
  <li><b>DPI</b> dropdown — 72, 96, 150, or 300 DPI. Higher DPI = larger file,
      sharper result for printing.</li>
  <li><b>Estimated size label</b> — shows the pixel dimensions of the resulting image.</li>
</ul>

<h3>Export Button</h3>
<p>Opens a save-file dialog. The default filename encodes the map name, dimensions,
hex size, and DPI (e.g. <code>MyMap_20x15_19mm_150dpi.png</code>).</p>
""")

_DOCS["dlg_assets"] = _page("Asset Manager Dialog", """
<p>Opened via the <b>Manage…</b> button inside the Asset tool's browser, or via
the main menu. Lets you import and organise image assets (PNG, JPG).</p>

<h3>Structure</h3>
<p>Assets are organised in a two-level hierarchy: <b>Game &gt; Category</b>.</p>
<ul>
  <li><b>Game combo</b> — select or create a game library.</li>
  <li><b>New Game</b> button — enter a name to create a new game entry.</li>
  <li><b>Category combo</b> — select or create a category within the game.</li>
  <li><b>New Category</b> button — creates a new category.</li>
</ul>

<h3>Asset List</h3>
<ul>
  <li>Displays thumbnails of all assets in the selected category.</li>
  <li><b>Import</b> button — opens a file dialog to add PNG/JPG files to the
      current category. Files are copied into the user data folder.</li>
  <li><b>Delete</b> button — removes the selected asset (user-imported assets only;
      built-in assets cannot be deleted).</li>
</ul>
""")

_DOCS["dlg_textures"] = _page("Texture Manager Dialog", """
<p>Opened via the <b>Manage…</b> button inside any texture browser. Manages the
texture library used by Fill Layer (Texture Fill), Path textures, Sketch fill
textures, and Draw Layer channel textures.</p>

<h3>Texture List</h3>
<ul>
  <li>Shows all imported textures as thumbnails with their names.</li>
  <li><b>Import</b> button — adds PNG/JPG files. Textures are copied to
      <code>%APPDATA%\\WargameMapTool\\textures\\</code>.</li>
  <li><b>Delete</b> button — removes a user-imported texture.</li>
  <li><b>Rename</b> — double-click a texture name to rename it.</li>
</ul>

<h3>Preview</h3>
<p>Clicking a texture thumbnail shows a larger preview on the right side of the dialog.</p>
""")

_DOCS["dlg_palettes"] = _page("Palette Editor Dialog", """
<p>Opened via <b>Edit &gt; Edit Palettes…</b> (<code>Ctrl+P</code>). Manages
named color palettes that appear in the Fill tool's color selector.</p>

<h3>Palette List</h3>
<ul>
  <li><b>New Palette</b> button — create a palette with a given name.</li>
  <li><b>Rename</b> — double-click a palette name to rename it.</li>
  <li><b>Delete</b> button — remove the selected palette.</li>
</ul>

<h3>Color List</h3>
<p>Shows the colors in the selected palette:</p>
<ul>
  <li><b>Add Color</b> button — opens a color picker to add a new color.</li>
  <li><b>Remove</b> button — removes the selected color.</li>
  <li><b>Reorder</b> — drag color swatches to change their order.</li>
</ul>

<h3>Usage</h3>
<p>Palettes appear as a dropdown in the Fill tool options. Selecting a palette
shows its colors as quick-pick buttons alongside the main color picker.</p>
""")

_DOCS["dlg_calcgrid"] = _page("Calculate Grid Dialog", """
<p>Opened via <b>Edit &gt; Calculate Grid…</b> (<code>Ctrl+Shift+C</code>).
A helper tool that works out the required grid size (columns × rows) for a
real-world map area at a given hex scale.</p>

<h3>Inputs</h3>
<ul>
  <li><b>Area Width</b> — real-world width of the map area.</li>
  <li><b>Area Height</b> — real-world height of the map area.</li>
  <li><b>Unit</b> — kilometres or miles.</li>
  <li><b>Hex Scale</b> — how many km (or miles) one hex represents.</li>
  <li><b>Hex Size</b> — physical hex size on paper in mm (carried over from the
      current map settings).</li>
</ul>

<h3>Output</h3>
<ul>
  <li><b>Columns / Rows</b> — the calculated grid dimensions.</li>
  <li><b>Paper size</b> — approximate print dimensions in mm.</li>
</ul>

<p>Click <b>Apply to Map</b> to set the calculated dimensions directly on the
current map (opens Map Settings with the values pre-filled).</p>
""")

_DOCS["dlg_edit_image"] = _page("Edit Image Dialog", """
<p>A standalone image editor that opens when you click <b>Edit Image…</b> in the
Background Layer tool options. Edits are made on a <i>working copy</i> — nothing
is written to the layer until you click <b>Apply</b>.</p>

<p><b>Typical coastline workflow:</b>
Load a satellite/road-map screenshot → Posterize to 4 levels → Select Color on
the water → Invert Selection → Delete Selected Pixels (land becomes transparent)
→ Add Black Outline → Apply.</p>

<h3>Navigation (always available)</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Scroll Wheel</td><td>Zoom in / out, centred on the cursor.</td></tr>
  <tr><td>Right-click Drag</td><td>Pan the canvas.</td></tr>
  <tr><td>Fit button</td><td>Zoom to fit the image in the window.</td></tr>
  <tr><td>− / + buttons</td><td>Step zoom out / in.</td></tr>
</table>

<h3>Paint Brush / Eraser gestures</h3>
<table>
  <tr><th>Input</th><th>Action</th></tr>
  <tr><td>Left Click / Drag</td><td>Paint or erase pixels (depending on active tool).</td></tr>
  <tr><td><code>Ctrl</code> + Left Drag (up / down)</td><td>Adjust brush size (up = larger, down = smaller).</td></tr>
  <tr><td><code>Ctrl+Z</code></td><td>Undo last operation (up to 10 steps).</td></tr>
</table>

<h3>Active Tool</h3>
<p>Click a tool button to activate it; click the same button again to return to
navigate-only mode.</p>
<ul>
  <li><b>Paint Brush</b> — left-click / drag to paint with the selected color.
      The cursor is replaced by a circle showing the exact brush radius.
      If a selection is active, paint is restricted to selected pixels only.</li>
  <li><b>Eraser</b> — left-click / drag to erase pixels (set them to fully
      transparent). Uses the same brush radius as the Paint Brush.
      If a selection is active, only selected pixels are erased.</li>
  <li><b>Select Color</b> — left-click a pixel to select all pixels of the same
      RGB color (within non-transparent areas). The selection is shown as a
      semi-transparent blue overlay.</li>
</ul>

<h3>Paint Brush / Eraser settings</h3>
<ul>
  <li><b>Color</b> — opens a color picker for the paint color (Paint Brush only).</li>
  <li><b>Brush Size</b> — radius in image pixels (1–200). Use the slider,
      the spinbox, or <code>Ctrl</code> + Left Drag (drag up to increase,
      down to decrease).</li>
</ul>

<h3>Filters</h3>
<ul>
  <li><b>Apply Posterize</b> — reduces the number of distinct color levels per
      channel. <b>Levels</b> (2–16): lower values produce fewer colors.
      Level 4 works well for isolating map areas.</li>
</ul>

<h3>Selection</h3>
<ul>
  <li><b>Invert</b> — inverts the current selection within non-transparent pixels.
      Use after Select Color on water to select land instead.</li>
  <li><b>Deselect</b> — clears the selection (enabled only when a selection
      exists).</li>
  <li><b>Delete Selected Pixels → transparent</b> — sets all selected pixels
      to fully transparent (alpha = 0). Useful for removing land or water areas
      to create a coastline overlay.</li>
  <li><b>Fill Selection with Color</b> — fills all selected pixels with the
      current Paint Brush color. The selection remains active so you can
      undo, change color, and fill again.</li>
</ul>

<h3>Outline</h3>
<ul>
  <li><b>Add Black Outline</b> — draws a black border around all non-transparent
      pixels. <b>W</b> (1–10 px) controls the outline thickness.</li>
</ul>

<h3>Undo</h3>
<ul>
  <li><b>↩ Undo</b> button or <code>Ctrl+Z</code> — undoes the last destructive
      operation (paint stroke, posterize, delete, fill, or outline). Up to 10 steps.</li>
</ul>

<h3>Export / Apply / Cancel</h3>
<ul>
  <li><b>Export Image…</b> — saves the current working-copy image to a PNG file
      on disk without closing the dialog.</li>
  <li><b>Cancel</b> — discards all edits and closes the dialog.</li>
  <li><b>Apply to New Layer</b> — creates a <i>new</i> Image layer above the
      current one with the edited image, leaving the original layer unchanged.</li>
  <li><b>Apply</b> — commits the edited image to the current Background Layer.
      This creates one undo step in the main project undo stack (<code>Ctrl+Z</code>
      in the main window reverses it).</li>
</ul>
""")

_DOCS["dlg_render_layer"] = _page("Render Layer to Image", """
<p>Opened via <b>Edit &gt; Render Layer to Image…</b> (<code>Ctrl+Shift+R</code>).
Renders the active layer to a PNG image file and replaces it with an Image layer
containing the rendered result.</p>

<h3>How It Works</h3>
<ul>
  <li>Select any non-Image layer in the Layer Panel.</li>
  <li>Choose <b>Edit &gt; Render Layer to Image…</b> (or press <code>Ctrl+Shift+R</code>).</li>
  <li>A save dialog opens — pick a location for the exported PNG.</li>
  <li>The layer is rendered at full resolution. A new Image layer with the rendered
      content is inserted above the original, and the original layer is removed.</li>
</ul>

<h3>Notes</h3>
<ul>
  <li>Image layers cannot be rendered (they are already images).</li>
  <li>Empty layers produce a warning and no output.</li>
  <li>The rendered Image layer preserves the correct position and zoom to match the
      original layer's visual appearance.</li>
</ul>
""")

# ---------------------------------------------------------------------------
# Tree structure: (category_label, [(page_key, item_label), ...])
# ---------------------------------------------------------------------------
_TREE: list[tuple[str, list[tuple[str, str]]]] = [
    ("Getting Started", [
        ("overview",   "Overview"),
        ("new_map",    "New Map Dialog"),
        ("navigation", "Canvas & Navigation"),
    ]),
    ("Menus", [
        ("menu_file",  "File Menu"),
        ("menu_edit",  "Edit Menu"),
        ("menu_view",  "View Menu"),
        ("menu_help",  "Help Menu"),
    ]),
    ("UI Panels", [
        ("panel_layers",  "Layer Panel"),
        ("panel_options", "Tool Options Panel"),
        ("panel_minimap", "Minimap"),
    ]),
    ("Layer Types", [
        ("layer_background", "Background (Image) Layer"),
        ("layer_fill",       "Fill Layer"),
        ("layer_asset",      "Asset Layer"),
        ("layer_text",       "Text Layer"),
        ("layer_hexside",    "Hexside Layer"),
        ("layer_border",     "Border Layer"),
        ("layer_path",       "Path Layer (Center-to-Center)"),
        ("layer_freeform",   "Freeform Path Layer"),
        ("layer_sketch",     "Sketch Layer"),
        ("layer_draw",       "Draw Layer"),
    ]),
    ("Dialogs", [
        ("dlg_settings",      "Map Settings"),
        ("dlg_export",        "Export"),
        ("dlg_assets",        "Asset Manager"),
        ("dlg_textures",      "Texture Manager"),
        ("dlg_palettes",      "Palette Editor"),
        ("dlg_calcgrid",      "Calculate Grid"),
        ("dlg_render_layer",  "Render Layer to Image"),
        ("dlg_edit_image",    "Edit Image Dialog"),
    ]),
]


# ---------------------------------------------------------------------------
# Dialog class
# ---------------------------------------------------------------------------

class DocumentationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Documentation")
        self.resize(1000, 720)
        self.setMinimumSize(700, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        # ── Left: tree ───────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(210)
        self._tree.setMaximumWidth(300)
        self._tree.setStyleSheet("QTreeWidget::item { padding: 3px 4px; }")

        self._key_map: dict[QTreeWidgetItem, str] = {}

        for category, pages in _TREE:
            cat_item = QTreeWidgetItem(self._tree, [category])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            cat_item.setForeground(0, cat_item.foreground(0))
            for key, label in pages:
                page_item = QTreeWidgetItem(cat_item, [f"  {label}"])
                self._key_map[page_item] = key

        self._tree.expandAll()
        self._tree.currentItemChanged.connect(self._on_item_changed)
        splitter.addWidget(self._tree)

        # ── Right: browser ───────────────────────────────────────────────
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.document().setDefaultStyleSheet(_CSS)
        self._browser.anchorClicked.connect(self._on_link_clicked)
        splitter.addWidget(self._browser)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 750])

        # ── Buttons ──────────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Select first item
        first_cat = self._tree.topLevelItem(0)
        if first_cat and first_cat.childCount():
            self._tree.setCurrentItem(first_cat.child(0))

    def _on_item_changed(self, current: QTreeWidgetItem, _) -> None:
        if current is None:
            return
        key = self._key_map.get(current)
        if key and key in _DOCS:
            self._browser.setHtml(_DOCS[key])
            self._browser.verticalScrollBar().setValue(0)

    def show_page(self, key: str) -> None:
        """Programmatically navigate to a page by key."""
        for item, k in self._key_map.items():
            if k == key:
                self._tree.setCurrentItem(item)
                break

    def _on_link_clicked(self, url) -> None:
        """Handle internal page: links (e.g. <a href='page:dlg_edit_image'>)."""
        s = url.toString()
        if s.startswith("page:"):
            self.show_page(s[5:])
