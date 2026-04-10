# Settings Page — Design Spec
**Date:** 2026-04-09  
**Status:** Approved  

---

## Overview

A new Settings page accessible from the existing sidebar "Settings" button (currently wired to nothing). The page has two sections:

1. **Data Management** — export all sessions to Excel, delete all data.
2. **How It Works** — three animated flowchart cards explaining the scientific pipeline behind Stress, Cognitive Load, and Learning Curves. Nodes are clickable and expand an inline formula panel.

---

## 1. Navigation

**File:** `app/ui/main_window.py`

- The sidebar `settings_btn` already exists but has no `clicked` handler. Wire it to `lambda: self.navigate_to(6)`.
- Add `SettingsView` as index **6** in the `QStackedWidget`.
- The sidebar remains visible on index 6 (unlike Calibration/Live). Add 6 to the visible-sidebar set.
- Add `"Settings"` to the `view_names` list in `navigate_to()`.
- `settings_btn` must become checkable (`setCheckable(True)`) and participate in the checked-state logic in `navigate_to()`. Because it is not in `_nav_buttons`, handle it separately: store a reference `self._settings_btn` and check/uncheck it alongside the main nav loop.

---

## 2. SettingsView widget

**File:** `app/ui/views/settings_view.py` (new file)

```
SettingsView(QWidget)
  └── QScrollArea (full-page, frameless)
        └── content QWidget
              ├── Page heading: "Settings"
              ├── _DataManagementCard  (QFrame#card)
              └── _HowItWorksSection   (QWidget)
                    ├── Section heading: "How It Works"
                    ├── Section subtitle (muted)
                    └── QHBoxLayout
                          ├── _FlowchartCard  — Stress
                          ├── _FlowchartCard  — Cognitive Load
                          └── _FlowchartCard  — Learning Curves
```

The `SettingsView` receives a `DatabaseManager` instance via its constructor (same dependency-injection pattern used by `DashboardView`).

---

## 3. Data Management Card

**Contained in:** `_DataManagementCard(QFrame)` (inner class of `settings_view.py`)

### 3a. Export All Sessions

- Button label: "Export All Sessions", icon: `ph.file-xls-fill`
- On click: opens a `QFileDialog.getSaveFileName` with filter `"Excel Files (*.xlsx)"`.
- If the user confirms a path, calls `SessionExporter.export_all_sessions(path)` inside a `QThread` worker. While running, button becomes disabled and shows "Exporting…".
- On success: button re-enables; a brief green inline status label shows "Exported successfully".
- On failure: inline red status label shows the error message.

### 3b. Delete All Data

- **Phase 1 (default state):** Button "Delete All Data", icon `ph.trash-fill`, styled as a danger button (`COLOR_DANGER` background).
- On click: the card expands to show an **inline confirmation banner** — a `QFrame` with `COLOR_DANGER_BG` background:
  - Text: "This will permanently delete all {N} sessions and cannot be undone."
  - Two buttons: "Cancel" (secondary) and "Confirm Delete" (danger/primary).
- **Cancel:** collapses the banner, returns to Phase 1.
- **Confirm Delete:** executes `conn.execute("DELETE FROM sessions")` + `conn.commit()`, then calls `main_window.navigate_to(0)` and `main_window._populate_recent_sessions()`. The `SettingsView` emits a `data_cleared` signal that `MainWindow` connects to a refresh handler.

---

## 4. SessionExporter — export_all_sessions()

**File:** `app/storage/export.py`

New method `export_all_sessions(path: str | Path) -> None`:

- Fetches all completed sessions via `SessionRepository.get_completed_sessions()`.
- Writes a multi-sheet Excel file using `openpyxl` via `pd.ExcelWriter`:
  - **Sheet "Summary"**: one row per session — Session ID, Date, Duration (s), NASA-TLX Score, HRV sample count, notes.
  - **Sheet "Session {id}"** for each session: same columns as the existing `export_excel()` Measurements sheet (Time, BPM, HRV, RMSSD, Delta RMSSD, Pupil Diameter, Delta Pupil Diameter).
- If there are zero sessions, writes an Excel with just the Summary sheet and a single row saying "No sessions recorded."

---

## 5. How It Works — FlowchartCard

**File:** `app/ui/widgets/flowchart_card.py` (new file)

### 5a. FlowchartCard(QFrame)

```
FlowchartCard
  ├── Title label  (e.g. "Stress")
  ├── Subtitle label (muted, e.g. "HRV · RMSSD · Δ from Baseline")
  ├── _FlowchartCanvas (QWidget)  ← custom painter, animated
  └── _DetailPanel (QFrame, hidden by default)
```

Constructor signature:
```python
FlowchartCard(title: str, subtitle: str, nodes: list[NodeDef], parent=None)
```

### 5b. NodeDef (dataclass)

```python
@dataclass
class NodeDef:
    icon: str          # qtawesome name, e.g. "ph.heartbeat-fill"
    label: str         # short label shown below icon
    formula: str       # Unicode math formula string (shown in detail panel)
    description: str   # 1–2 sentence plain-English explanation
    reference: str     # "Author (Year). Title. Journal, vol(issue), pp."
    is_threshold: bool = False  # if True, render with funnel icon variant
```

### 5c. _FlowchartCanvas(QWidget) — painting & animation

**Layout:** Nodes are evenly spaced horizontally across the widget width. Each node is:
- A 48×48 rounded-rect background (`COLOR_PRIMARY_SUBTLE`) with the `qtawesome` icon centred inside (24 px, `COLOR_PRIMARY`).
- Threshold-gate nodes use `COLOR_WARNING_BG` background + `COLOR_WARNING` icon.
- A short label (`FONT_CAPTION`, `COLOR_FONT_MUTED`) centred below.

**Connector lines:** Between each pair of adjacent nodes, draw a dashed line using `QPainter`:
```python
pen = QPen(QColor(COLOR_BORDER))
pen.setWidth(2)
pen.setStyle(Qt.PenStyle.CustomDashLine)
pen.setDashPattern([4, 6])          # 4px dash, 6px gap
pen.setDashOffset(self._dash_offset)
painter.setPen(pen)
painter.drawLine(node_right, cy, next_node_left, cy)
```
A `QTimer` (25 ms interval, ~40 fps) increments `_dash_offset` by 1.0 each tick, wrapping at 10 (dash period). This produces the flowing-dots effect. Timers start when the `SettingsView` is shown and stop when hidden (override `showEvent`/`hideEvent`).

**Click detection:** `mousePressEvent` checks if the click falls within any node's bounding rect. If yes, emits `node_clicked(index: int)`.

### 5d. _DetailPanel(QFrame)

Hidden by default. When a node is clicked, the panel becomes visible and populates with:
- **Step name** (bold, `FONT_SUBTITLE`)
- **Formula block** (monospace font or `QLabel` with `font-family: "Courier New"`, `COLOR_PRIMARY`, slight `COLOR_PRIMARY_SUBTLE` background)
- **Description** (body text, `COLOR_FONT`)
- **Reference** (italic, `FONT_SMALL`, `COLOR_FONT_MUTED`)
- A small ✕ close button (top-right of panel)

Clicking the same node again, or the ✕, hides the panel. Clicking a different node swaps the content without hiding.

The panel does **not** animate in (no slide) — it appears instantly to keep the implementation simple and avoid layout reflow jitter.

---

## 6. Node Definitions

### 6a. Stress (HRV / RMSSD)

| # | Icon | Label | Formula | Reference |
|---|---|---|---|---|
| 1 | `ph.heart-fill` | Heart Sensor | Raw ECG signal sampled at 250 Hz | — |
| 2 | `ph.wave-sine-fill` | RR Intervals | RR[i] = time between consecutive R-peaks (ms) | Task Force ESC & NASPE (1996) |
| 3 | `ph.math-operations-fill` | RMSSD | RMSSD = √( mean( (RR[i+1] − RR[i])² ) ) | Shaffer & Ginsberg (2017). *Front. Public Health* |
| 4 | `ph.arrows-vertical-fill` | Δ Baseline | ΔRMSSD = RMSSD_t − RMSSD_baseline | Thayer et al. (2012). *Neurosci. Biobehav. Rev.* |
| 5 | `ph.funnel-fill` | Threshold | Stress flagged if ΔRMSSD < −15 ms (default) | Task Force ESC & NASPE (1996) |
| 6 | `ph.gauge-fill` | Stress Score | Normalised score 0–1: norm(1 / RMSSD) | — |

### 6b. Cognitive Load (PDI / CLI)

| # | Icon | Label | Formula | Reference |
|---|---|---|---|---|
| 1 | `ph.eye-fill` | Eye Camera | Raw pupil diameter in pixels at 30 Hz | — |
| 2 | `ph.drop-fill` | Pupil Diameter | Diameter (px) after blink-artefact rejection | Beatty (1982). *Psychol. Bull.* |
| 3 | `ph.prohibit-fill` | Blink Filter | Drop if Δdiameter/Δt > threshold (blink artefact) | Peavler (1974). *J. Exp. Psychol.* |
| 4 | `ph.arrows-out-fill` | PDI | PDI = (d_t − d_baseline) / d_baseline | Kahneman & Beatty (1966). *Science* |
| 5 | `ph.funnel-fill` | Threshold | Load flagged if PDI > 0.15 (default) | Beatty (1982). *Psychol. Bull.* |
| 6 | `ph.brain-fill` | CLI | CLI = w₁·norm(1/RMSSD) + w₂·norm(PDI), w₁=w₂=0.5 | — |

### 6c. Learning Curves (Schmettow)

| # | Icon | Label | Formula | Reference |
|---|---|---|---|---|
| 1 | `ph.clipboard-text-fill` | Session Results | Raw performance metric per trial (time, score, errors) | — |
| 2 | `ph.list-numbers-fill` | Trial Sequence | Ordered sequence y₁, y₂, …, yₙ | Wright (1936). *J. Aeronaut. Sci.* |
| 3 | `ph.function-fill` | Schmettow Fit | ŷ(t) = α · t^β ; fit via NLS (non-linear least squares) | Schmettow (2014). *HFES Annual Meeting* |
| 4 | `ph.trend-up-fill` | Learning Curve | α = starting performance, β = learning rate (negative = improving) | Schmettow (2014). *HFES Annual Meeting* |

---

## 7. File Checklist

| File | Action |
|---|---|
| `app/ui/views/settings_view.py` | **New** — `SettingsView`, `_DataManagementCard`, `_HowItWorksSection` |
| `app/ui/widgets/flowchart_card.py` | **New** — `FlowchartCard`, `_FlowchartCanvas`, `_DetailPanel`, `NodeDef` |
| `app/storage/export.py` | **Edit** — add `export_all_sessions()` method |
| `app/ui/main_window.py` | **Edit** — wire settings button, add SettingsView to stack at index 6 |

---

## 8. Out of Scope

- Threshold values are not user-configurable in this sprint (they come from `config.py`).
- No user accounts / login — the "Log Out" button remains non-functional.
- No animation easing on the detail panel (instant show/hide).
- No export progress bar (just button disabled state).
