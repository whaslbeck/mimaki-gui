# Mimaki ME-500 GUI — Application Specification

## 1. Project Overview

A desktop GUI application for operators of the **Mimaki ME-500** engraving/milling machine. The application allows importing one or more G-code files, arranging and transforming them on a virtual work surface, and transmitting the resulting HPGL job to the machine over a serial connection.

---

## 2. Technology Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| GUI framework | PyQt6 or PySide6 (platform-neutral, Linux primary) |
| Serial communication | `pyserial` |
| Project persistence | JSON |
| Config persistence | JSON (user-level config file) |

The application must run on **Linux** (primary), macOS, and Windows without modification.

---

## 3. Machine Specifications

| Parameter | Value |
|---|---|
| Model | Mimaki ME-500 |
| Work area | 483 mm × 305 mm |
| Machine origin | Bottom-left (0, 0) |
| Protocol | HPGL + Mimaki extensions |
| Serial defaults | 9600 baud, 8N1, no flow control |

### HPGL Command Set Used

| Command | Description |
|---|---|
| `IN;` | Initialize / reset plotter |
| `PU[x,y];` | Pen Up — move to coordinates |
| `PD[x,y];` | Pen Down — cut/engrave to coordinates |
| `!PZ<pd>[,<pu>];` | **Mimaki extension.** Set Z depth for PD (and optionally PU) mode. Unit: 0.01 mm. Example: `!PZ-200,500;` sets cutting depth to −2.00 mm, travel height to +5.00 mm. |

**Coordinate unit in HPGL:** 0.01 mm (multiply G-code mm values by 100).

Multiple PD moves can be chained: `PD x1,y1,x2,y2,...;`

---

## 4. Application Architecture

```
mimaki-gui/
├── main.py                  # Entry point
├── app/
│   ├── gui/
│   │   ├── main_window.py   # Main window, menu, toolbar
│   │   ├── canvas.py        # Work surface canvas widget
│   │   ├── object_panel.py  # Per-object property panel
│   │   ├── send_panel.py    # Job transmission panel
│   │   └── dialogs/         # Settings, zone editor, etc.
│   ├── model/
│   │   ├── gcode_object.py  # Parsed G-code object + transforms
│   │   ├── project.py       # Project (collection of objects + zones)
│   │   └── zone.py          # Forbidden zone
│   ├── io/
│   │   ├── gcode_parser.py  # G-code → internal move list
│   │   ├── hpgl_writer.py   # Move list → HPGL bytes
│   │   └── serial_sender.py # Throttled serial transmission
│   └── config.py            # User configuration persistence
```

---

## 5. GUI Layout

```
┌─────────────────────────────────────────────────────────┐
│  Menu bar:  File  Edit  View  Machine  Help             │
├─────────────────────────────────────────────────────────┤
│  Toolbar:  [Open] [Save] [Send] [Pause] [Stop]  ...     │
├───────────────────────────────┬─────────────────────────┤
│                               │  Object List            │
│                               │  ─────────────────────  │
│   Canvas (work surface)       │  [Selected object       │
│                               │   properties panel]     │
│                               │  ─────────────────────  │
│                               │  Speed Settings         │
│                               │  ─────────────────────  │
│                               │  Estimated Duration     │
├───────────────────────────────┴─────────────────────────┤
│  Transmission Panel  (log + progress)                   │
└─────────────────────────────────────────────────────────┘
```

---

## 6. Canvas (Work Surface)

- Renders the full ME-500 work area (483 × 305 mm) scaled to fit the widget.
- **Grid** (optional, toggleable via View menu / `Ctrl+G`):
  - Grid spacing configurable (default: 10 mm).
  - Grid origin configurable (default: 0, 0).
- **Coordinate display**: Current cursor position in mm shown in the status bar.
- **Zoom & Pan**: Mouse wheel to zoom, middle-button drag to pan.
- **Axis orientation**: Y-axis increases upward (matches machine coordinate system). Canvas renders accordingly (flip Y for screen drawing).
- All objects, bounding boxes, pivot points, and forbidden zones are drawn on the canvas.
- **Colour scheme** (all configurable in settings):
  | Element | Default colour |
  |---|---|
  | Travel moves (pen up) | Blue |
  | Machining moves (pen down) | Red |
  | Bounding box | Green (dashed) |
  | Pivot point marker | Orange cross |
  | Selected object highlight | Yellow outline |
  | Forbidden zones | Semi-transparent red fill |

---

## 7. G-Code Import & Parsing

### Import

- **File → Open** (`Ctrl+O`) opens a file dialog (filter: `*.gcode *.nc *.tap *.txt *, *`).
- Multiple files may be selected in one dialog; each becomes a separate object.
- Additional files can be imported at any time into an existing project.

### Parser Rules

Only the following are processed; all other G-code commands are ignored:

| G-code token | Meaning |
|---|---|
| `G0` / `G00` | Rapid move (no effect beyond axis values; pen state determined by Z) |
| `G1` / `G01` | Linear move (no effect beyond axis values; pen state determined by Z) |
| `X<value>` | Set current X (mm) |
| `Y<value>` | Set current Y (mm) |
| `Z<value>` | Set current Z (mm) |
| `(<comment>)` | Comment — stored and displayed as tooltip |

**Pen state rule:** `Z < 0` → pen down (machining); `Z ≥ 0` → pen up (travel). This mirrors the HPGL output logic.

**Comments:** Lines (or inline sections) matching `(...)` are captured with their source line number and stored on the nearest subsequent move. They are shown as a tooltip when the user hovers over that move's segment on the canvas.

**Coordinate system:** G-code units are millimetres. Internal representation is also in millimetres (floating point). HPGL conversion multiplies by 100.

### Internal Move Structure

```python
@dataclass
class Move:
    line_nr: int        # Source line number
    source: str         # Original G-code line
    from_pos: Pos       # Start position (mm)
    to_pos: Pos         # End position (mm)
    xy_move: bool
    z_move: bool
    pen_down: bool      # to_pos.Z < 0
    comment: str        # comment text, may be empty
```

---

## 8. Object Model

Each imported G-code file is one **GcodeObject** with:

- **Original moves**: immutable parsed move list.
- **Transform**: position offset, scale factor, rotation angle, pivot point (all in mm / degrees).
- **Computed moves**: original moves with transform applied (recalculated on every transform change).
- **Bounding box**: derived from computed moves (min/max X and Y of all positions).

### Transform Parameters

| Parameter | Default | Unit |
|---|---|---|
| Position (offset) | (0, 0) | mm |
| Scale | 1.0 | factor |
| Rotation | 0.0 | degrees |
| Pivot point | Object centroid | mm (absolute) |

### Object List Panel

- Lists all objects by filename (editable label).
- Checkbox to toggle visibility per object.
- Buttons: Duplicate, Delete, Move Up/Down (render order).
- Click to select; selected object is highlighted on canvas and shown in property panel.

---

## 9. Object Manipulation

All manipulations operate on the selected object and are undoable (`Ctrl+Z` / `Ctrl+Y`).

### 9.1 Position

- **Interactive drag** on canvas (snap to grid when grid is active and `Ctrl` is not held, or vice versa — configurable).
- **Manual input**: coordinate fields in the property panel (absolute mm or delta).
- **Snap modes**: free, snap-to-grid, or typed coordinates.

### 9.2 Scale

- **Property panel fields**: width (mm), height (mm), or scale factor.
- Lock aspect ratio toggle (default: locked).
- **Snap**: free or lock to grid dimensions.
- **Reset**: button to restore scale to 1.0.

### 9.3 Rotation

- **Interactive**: drag the rotation handle shown at the top of the bounding box on the canvas.
- **Snap**: free, or snap to 45° increments (hold `Ctrl`).
- **Manual input**: degree field in property panel.
- **Reset**: button to restore rotation to 0°.
- Rotation is always around the **pivot point**.

### 9.4 Pivot Point

- Displayed as an orange cross on the canvas.
- **Interactive drag** on canvas (same snap rules as position).
- **Manual input**: coordinate fields in property panel.
- **Reset**: button to restore to object centroid.

### 9.5 Clone / Array

Accessible via **Edit → Clone…** or the object context menu (`Ctrl+D`).

**Dialog inputs:**

| Field | Default | Description |
|---|---|---|
| Number of clones | 1 | How many additional copies to create |
| Gap between objects | 2.0 mm | Minimum clearance between bounding boxes |
| Snap gap to grid | yes | Round gap to nearest grid step when grid is active |

**Auto-placement algorithm:**

1. The original object stays in place.
2. Clones are placed one at a time using a **row-by-row left-to-right, bottom-to-top** strategy, starting from the top-left of the work area and advancing by `bbox_width + gap` per step.
3. Before placing each clone, the candidate bounding box is checked against:
   - All existing objects (including previously placed clones in this operation).
   - All forbidden zones.
   - The work area boundary (483 × 305 mm).
4. If a candidate position overlaps any of the above, the placer advances to the next candidate position.
5. If not all clones can be placed without overlap, the available ones are placed and a warning dialog reports how many could not be placed. The user may then manually reposition the unplaced copies (they are added at an offset from the original, flagged with a warning indicator on the canvas).

All clones inherit the same transform (scale, rotation) as the original. Each clone is an independent `GcodeObject` and can be individually modified after creation. Cloning is a single undoable action.

---

## 10. Forbidden Zones

- Interactive tool to define rectangular areas on the work surface where no object may be placed (e.g. clamp locations).
- **Draw**: activate zone tool from toolbar or menu, click-drag to define rectangle.
- **Edit**: select zone → drag corners or move.
- **Snap**: free, snap-to-grid, or type coordinates.
- **Delete**: select zone → `Delete` key or context menu.
- Zones are saved in the project file.
- **Collision detection**: if any object's bounding box overlaps a forbidden zone, a visual warning (orange highlight) is shown. Transmission is blocked with a warning dialog if overlap exists.

---

## 11. Speed Settings & Duration Estimation

Speed settings are **informational only** — they are not transmitted to the machine and must be set manually on the machine itself.

| Parameter | Default | Unit |
|---|---|---|
| XY travel speed | 5000 | mm/min |
| XY machining speed | 1000 | mm/min |
| Z travel speed | 1000 | mm/min |
| Z machining speed | 500 | mm/min |

- Displayed in the right-hand panel.
- **Estimated duration** is recalculated whenever speeds or objects change:
  - Sum over all moves: `distance / speed` (using appropriate speed per move type).
  - Displayed as `HH:MM:SS` estimate.

---

## 12. HPGL Output Generation

HPGL is generated from the **computed (transformed) move list** of all visible objects, in render order.

### Output Header

```
IN;PU;
```

### Per-Move Logic

```
for each move in all_objects_moves (in order):
    if Z changed:
        close any open PD sequence
        emit !PZ<z_pd>[,<z_pu>];
    if XY changed:
        if pen_down:
            emit PD or append to current PD chain
        else:
            close PD chain if open
            emit PU x,y;
```

Chain multiple consecutive PD moves: `PDx1,y1,x2,y2,...;`

### Coordinate Conversion

```
hpgl_x = round(mm_x * 100)
hpgl_y = round(mm_y * 100)
hpgl_z = round(mm_z * 100)
```

### Bounds Preview (Send Limits)

A separate function generates HPGL that drives the tool around the bounding box of all selected objects at a safe Z height, for operator preview on the machine before cutting:

```
IN;PU;!PZ500;PU0,0;PU x1,y1;PD x2,y1;PD x2,y2;PD x1,y2;PD x1,y1;PU0,0;
```

---

## 13. Serial Communication & Job Transmission

### Port Settings

- Configurable: port name, baud rate (default 9600), data bits (default 8), parity (default N), stop bits (default 1).
- Stored in user config.
- Accessible via **Machine → Serial Settings…**

### Transmission Panel

A docked panel (bottom of window) shows:
- Connection status (connected / disconnected indicator).
- Scrolling log of transmitted HPGL lines (last N lines, configurable).
- Progress bar (moves sent / total moves).
- Estimated remaining time.
- **[Connect]**, **[Send]**, **[Pause]**, **[Stop]** buttons (also on toolbar with hotkeys).

### Scope of Transmission

Before or instead of sending the full project, the operator can restrict what gets transmitted:

- **Send all objects** (default): all visible objects in render order.
- **Send selected object only**: right-click an object in the object list → **Send this object** (`Ctrl+F5`). Only that object's moves are transmitted; a fresh `IN;PU;` header is prepended.

Both modes support the start-point options described below.

### Send Job

- **Machine → Send** (`F5`): Transmit the current scope (all or selected) starting from the very first move.
- **Machine → Send from…** (`Shift+F5`): Opens the **Start Point** dialog (see below).

### Start Point Dialog

The dialog lets the operator choose exactly where in the job to begin transmission. This is useful when resuming after an interruption or when parts of the job have already been cut.

Three mutually exclusive modes:

**1. From beginning** (default)
The job starts at move 0 of the first object in scope.

**2. From object**
A drop-down lists all objects in transmission scope. The job starts at the first move of the chosen object. Objects before the selected one are skipped entirely.

**3. From Z-layer**
The job is filtered to start at the first move whose cutting depth (`to_pos.Z`) is ≤ a specified threshold. Use case: a multi-pass G-code has already been partially cut (e.g. passes at Z=−1 mm and Z=−2 mm are done); the operator enters `−2` mm to resume from the −2 mm layer onwards.

- A drop-down (or editable combo) shows all distinct negative Z values found in the object(s) in scope, sorted shallow-to-deep (e.g. −0.5, −1.0, −1.5, −2.0).
- The operator selects or types a threshold. All moves with `to_pos.Z > threshold` (i.e. shallower passes and travel moves) are skipped.
- If **From object** and **From Z-layer** are combined, the Z filter is applied only within the selected object; objects before it are skipped, objects after it are included in full.

**Canvas preview:** The canvas highlights the first move that will be transmitted (animated marker) when the dialog is open, so the operator can visually verify the chosen start point before confirming.

The generated HPGL stream always begins with `IN;PU;` followed by an appropriate `!PZ` command reflecting the Z state at the chosen start point.

### Buffer Management Strategy

The Mimaki has a large internal buffer. To allow **Pause/Stop to take effect quickly**, the sender must keep the machine's buffer close to empty:

1. HPGL is split into individual command units (one move per unit).
2. The sender estimates the execution time of each unit using the configured speed settings.
3. After transmitting a unit, the sender waits `estimated_duration * throttle_factor` before sending the next (default `throttle_factor = 0.8`).
4. This ensures the machine buffer holds at most ~1–2 seconds of work at any time.

**Pause:** Stops transmitting. The machine will finish its buffer (≤ ~1–2 s) and halt.

**Stop:** Sends `PU;IN;` to reset the machine after the buffer drains.

### ZI Synchronisation (Experimental / Optional)

The HPGL command `ZI` (Output Identification) can be sent; the ME-500 should respond with `ME-500` only after it has processed all prior commands. If implemented, this replaces time-based throttling with a round-trip handshake:

1. Send a batch of moves.
2. Send `ZI`.
3. Wait for `ME-500` response.
4. Send next batch.

This feature is **not verified** and should be implemented behind a checkbox in Serial Settings: **"Use ZI synchronisation (experimental)"**.

---

## 14. Project File Format (JSON)

File extension: `.mimaki`

```json
{
  "version": 1,
  "objects": [
    {
      "id": "uuid",
      "label": "part_a",
      "source_file": "/path/to/file.gcode",
      "visible": true,
      "transform": {
        "offset_x": 10.0,
        "offset_y": 20.0,
        "scale": 1.5,
        "rotation_deg": 45.0,
        "pivot_x": 15.0,
        "pivot_y": 25.0
      }
    }
  ],
  "forbidden_zones": [
    {
      "id": "uuid",
      "x": 50.0, "y": 50.0,
      "width": 30.0, "height": 20.0,
      "label": "Clamp 1"
    }
  ],
  "speeds": {
    "xy_travel_mm_min": 5000,
    "xy_machining_mm_min": 1000,
    "z_travel_mm_min": 1000,
    "z_machining_mm_min": 500
  },
  "grid": {
    "visible": true,
    "spacing_mm": 10.0,
    "origin_x": 0.0,
    "origin_y": 0.0
  }
}
```

- **File → Save** (`Ctrl+S`): save to current file.
- **File → Save As…** (`Ctrl+Shift+S`): save with new name.
- **File → Open Project** (`Ctrl+Shift+O`): open a `.mimaki` file. Source G-code files are referenced by path; if a file is missing, the user is prompted to locate it.

---

## 15. Application Configuration (User Config)

Stored in a platform-appropriate user config directory (e.g. `~/.config/mimaki-gui/config.json` on Linux).

```json
{
  "recent_files": ["path1.mimaki", "path2.mimaki"],
  "last_import_dir": "/home/user/gcode",
  "last_project_dir": "/home/user/projects",
  "serial": {
    "port": "/dev/ttyUSB0",
    "baud": 9600,
    "bytesize": 8,
    "parity": "N",
    "stopbits": 1,
    "use_zi_sync": false
  },
  "ui": {
    "canvas_bg_color": "#F5F5F0",
    "travel_color": "#0055CC",
    "machining_color": "#CC2200",
    "bbox_color": "#228800",
    "pivot_color": "#FF8800",
    "zone_color": "#CC000060",
    "transmission_log_lines": 200
  },
  "throttle_factor": 0.8
}
```

---

## 16. Keyboard Shortcuts

| Key | Action |
|---|---|
| `Ctrl+O` | Import G-code file(s) |
| `Ctrl+Shift+O` | Open project |
| `Ctrl+S` | Save project |
| `Ctrl+Shift+S` | Save project as… |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Redo |
| `Ctrl+G` | Toggle grid |
| `Delete` | Delete selected object or zone |
| `Escape` | Deselect / cancel current tool |
| `F5` | Send job to machine |
| `Shift+F5` | Send from… (choose start move) |
| `F6` | Pause transmission |
| `F7` | Stop transmission |
| `Ctrl+B` | Send bounds preview to machine |
| `Ctrl++` / `Ctrl+-` | Zoom in / out |
| `Ctrl+0` | Fit work area to window |
| `Ctrl+A` | Select all objects |
| `Ctrl+D` | Clone selected object (opens Clone dialog) |
| `Ctrl+F5` | Send selected object only |

---

## 17. Reference: G-code → HPGL Conversion Module

A reference implementation in Go is provided in `INSTRUCTIONS-DRAFT.txt`. The Python implementation must replicate the same logic:

- `ZFactor = 100` (mm → HPGL Z units)
- `XYFactor = 100` (mm → HPGL XY units)
- Pen state: `Z < 0` → pen down
- Chain consecutive PD moves
- Emit `!PZ` before position moves when Z changes
- Track min/max bounds across all moves

The Python parser additionally must:
- Capture `(comment)` tokens and attach them to the following move.
- Return warnings for unparseable numeric values without aborting.
