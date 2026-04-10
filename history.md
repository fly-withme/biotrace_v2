# BioTrace — Development History
#command for running the app: .venv/bin/python main.py
---

## 2026-03-30 — Learning Curves Integration (Phase 6c)

Implemented the Schmettow parametric learning curve model to provide longitudinal progress tracking and personalized biofeedback.

### Analytics & Scientific Modeling
- `app/analytics/learning_curve.py` — Implemented the **Schmettow model (2026)** using `scipy.optimize.curve_fit`.
  - Formula: `errors(t) = scale * (1 - leff)**(t + pexp) + maxp`.
  - Performance Score Transform: `P = SCORE_MAX - errors`.
  - Added `get_mentor_message()`: context-aware feedback based on mastery thresholds (40% / 80%).
- `app/analytics/performance_repository.py` — New repository for cross-session analytics. Aggregates error counts, RMSSD, and CLI means across all completed sessions.

### UI & UX Enhancements
- **Background Computation** — Created `app/ui/workers/analytics_worker.py`. Curve fitting now runs in a `QThread` to keep the UI responsive.
- **Dashboard Learning Curve Card** — Added a full-width `LearningCurveChart` below the session table. Shows actual performance dots, fitted curve, and a 3-session projection.
- **Post-Session "Honest Mentor"** — Replaced the static feedback with a dynamic strip:
  - `QProgressBar` visualizing mastery relative to the predicted ceiling.
  - Personalized mentor text based on the trainee's position on the curve.
- **Live View Error Counter** — Added `ErrorInputWidget` to the toolbar for manual recording of surgical errors during training.

### Hardware & Core Logic
- `app/hardware/error_counter.py` — Created a hardware driver stub following the `BaseSensor` contract, ready for Phase 6b GPIO integration.
- `app/core/session.py` — `SessionManager` now tracks error counts and persists them to the `sessions.error_count` column on session end.
- `app/utils/config.py` — Added `SCORE_MAX = 10` and `LC_MIN_SESSIONS = 5`.

### Tests & Quality
- `tests/test_learning_curve.py` — 13 new unit tests covering synthetic data fitting, parameter bounds, mentor logic, and edge cases.
- `tests/test_performance_repository.py` — Tests for chronological ordering and `has_error_data` filtering.
- `tests/test_session.py` — Verified error count resetting and persistence logic.
- ✅ **136/136 tests passed** (including OptimizeWarning suppression for cleaner output).

---

## 2026-03-29 — Fix: empty Excel export and missing session stats in Post-Session view

### Root causes
1. **Empty Excel export**: The recent-sessions sidebar listed ALL sessions including
   abandoned runs (app closed mid-session), which have 0 `hrv_samples` rows.
   Clicking one of these led to an export with no data.
2. **Post-Session view shows 0:00 / wrong date**: `PostSessionView.load_session()`
   only stored the session ID and used today's date as the title.  It never queried
   the database, so TOTAL TIME stayed at "0:00" and the title showed today instead
   of the session's actual date.

### Fix

- `app/storage/session_repository.py` — Added `get_completed_sessions()`:
  returns only sessions with `ended_at IS NOT NULL`, ordered newest-first.
  Abandoned/crashed sessions are excluded so users never see a session with no data.
- `app/ui/main_window.py` — `_populate_recent_sessions()` now calls
  `get_completed_sessions()` instead of `get_all_sessions()`.
- `app/ui/views/post_session_view.py` — `load_session()` now queries the DB:
  - Title updated to the session's actual `started_at` date (not today's date).
  - `_time_value_label` populated with real duration (`ended_at − started_at`).
  - Gracefully handles sessions not found in DB or missing `ended_at`.

### Tests
- `tests/test_storage.py` — 2 new tests in `TestSessionRepository`:
  - `get_completed_sessions()` excludes sessions without `ended_at`.
  - `get_completed_sessions()` orders results newest-first.

### Verification
- ✅ `pytest tests/` → **99/99 passed**

---

## 2026-03-29 — Removed mock eye tracker / pupil / CLI data

### Problem
`MockEyeTracker` was always started during calibration and live sessions, generating
fake pupil diameter, PDI, and CLI values even when no physical eye tracker was connected.
Users saw plausible-looking (but invented) Pupil Dilation and Cognitive Load numbers.

### Fix

- `app/utils/config.py` — Added `USE_EYE_TRACKER: bool = False`. Set to `True` only when a real eye tracker is physically connected.
- `app/core/session.py` — Imported `USE_EYE_TRACKER`; wrapped all four `_eye_tracker.start()` / `_eye_tracker.stop()` calls in `if USE_EYE_TRACKER:` guards (in `start_calibration`, `end_calibration`, `start_session`, `end_session`).
- `app/ui/views/sensors_view.py` — Changed eye tracker card `mock_value` from `"3.6 mm  PDI"` to `"—"` (no longer shows fake data in the sensors page).

### Tests
- `tests/test_session.py` — 2 new tests in `TestEyeTrackerDisabled`:
  - `start_session()` does not call `eye_tracker.start()` when `USE_EYE_TRACKER=False`.
  - `start_calibration()` does not call `eye_tracker.start()` when `USE_EYE_TRACKER=False`.

### Verification
- ✅ `pytest tests/` → **97/97 passed**

---

## 2026-03-29 — HRV Sensor Status Badge, Live BPM Card & Export CTA

### Sensor connected indicator in Live View toolbar

- `app/hardware/mock_sensors.py` — Added `connection_status_changed(bool, str)` signal to `MockHRVSensor` (emits `True` on `start()`, `False` on `stop()`), matching `PicoECGSensor`'s interface so both sensors are interchangeable.
- `app/core/session.py` — Added two new public signals:
  - `bpm_updated(float, float)` — forwards instantaneous BPM from `HRVProcessor` to the UI on every beat, regardless of session state.
  - `hrv_connection_changed(bool, str)` — forwards the HRV sensor's `connection_status_changed` directly.
  - Added `_forward_bpm` slot wired to `hrv_proc.hrv_updated`.
- `app/ui/views/live_view.py` — Added a 28 × 28 px circular heartbeat icon badge next to "LIVE SESSION" in the toolbar:
  - **Disconnected**: gray background + gray icon.
  - **Connected**: green (`#22C55E`) background + white icon.
- Tests: `tests/test_session.py` — 4 new tests covering `bpm_updated` forwarding and `hrv_connection_changed` forwarding.

### Real-time HEART RATE card in Biofeedback mode

- `app/ui/views/live_view.py` — Added a fifth `MetricCard` ("HEART RATE · bpm") in the bottom row, between PUPIL DILATION and HRV (RMSSD). Receives `bpm_updated` signal and updates live.

### Bug fix: stale HRV values after sensor disconnect

- `app/ui/views/live_view.py` — `_on_hrv_connection_changed` now calls `.reset()` on `_bpm_card`, `_rmssd_card`, and `_stress_card` when `connected=False`. Cards immediately show "—" when the cable is pulled instead of freezing on the last value.

### Export to Excel CTA in Post-Session view

- `requirements.txt` — Added `openpyxl>=3.1.0`.
- `app/storage/export.py` — Added `SessionExporter.export_excel(session_id, path)`:
  - Writes a 4-sheet `.xlsx`: **Session Info** · **HRV** (timestamp, rr_interval, bpm, rmssd, delta_rmssd) · **Pupil** · **CLI**.
  - `_fetch_session_data()` updated to also fetch `bpm` and `delta_rmssd` from `hrv_samples`.
- `app/ui/views/post_session_view.py`:
  - Now accepts `db: DatabaseManager` and owns a `SessionExporter`.
  - Green **"Export Data"** button added to the header; opens a native save-file dialog pre-filled with `session_<id>.xlsx`.
- `app/ui/main_window.py` — passes `db=self._db` to `PostSessionView`.
- Tests: `tests/test_export_excel.py` — 7 new tests (sheets present, row counts, BPM values, empty-session edge case).

### Removed mock HRV placeholder value

- `app/ui/views/sensors_view.py` — Replaced hardcoded `mock_value="842 ms  RR"` with `"—"` on the HRV sensor card.

### Verification
- ✅ `pytest tests/` → **91/91 passed**

---

## 2026-03-29 — Bug fix: T-wave double-counting → inflated BPM

### Problem
Detected BPM was roughly 2× the true heart rate. The ECG T-wave (which follows each R-peak ~200–440 ms later) was being counted as an additional R-peak because the refractory period (300 ms) was shorter than the QT interval (350–440 ms).

### Fix — three layers of protection

| Layer | Before | After | Reasoning |
|---|---|---|---|
| `PICO_RPEAK_REFRACTORY_SAMPLES` | 45 (300 ms) | **60 (400 ms)** | T-waves arrive within 440 ms of R; now inside refractory window |
| `PICO_RPEAK_THRESHOLD_FACTOR` | 0.6 | **0.65** | T-waves are 25–50 % of R amplitude; 65 % threshold keeps safe margin |
| `HRV_MIN_RR_MS = 333.0` (new constant) | — | **333 ms** | Any interval implying > 180 BPM is discarded in `HRVProcessor` |

#### Updated Files
- `app/utils/config.py` — updated `PICO_RPEAK_REFRACTORY_SAMPLES`, `PICO_RPEAK_THRESHOLD_FACTOR`; added `HRV_MIN_RR_MS`.
- `app/processing/hrv_processor.py` — early-return in `on_rr_interval` rejects `rr_ms < HRV_MIN_RR_MS` before it enters the sliding window or emits any signal.

#### Tests
- `tests/test_processors.py` — 4 new tests in `TestHRVProcessorRRFilter`:
  - Intervals below minimum are silently rejected.
  - Interval exactly at minimum boundary is accepted.
  - Normal 800 ms / 75 BPM interval passes through unchanged.
  - Rejected interval does not pollute the RMSSD sliding window.

#### Verification
- ✅ `pytest tests/` → **95/95 passed**

---

## 2026-03-29 — Phase 6a: Pico ECG Integration & Auto Port Detection

### Step 6a-5b — Automatic USB Serial Port Detection

**Problem:** Users had to manually edit `config.py` to set the correct serial port path
for the Pi Pico, and the path changes whenever a different USB port is used.

**Solution:** `find_pico_port()` scans all connected serial ports at startup and returns
the first matching Pi Pico device path — no manual configuration needed.

#### New / Updated Files
- `app/hardware/pico_ecg_sensor.py`:
  - Added `find_pico_port() -> str | None` — scans `serial.tools.list_ports.comports()` and matches by:
    1. USB vendor ID: `0x2E8A` (Raspberry Pi Foundation) or `0x239A` (Adafruit CircuitPython)
    2. Fallback: case-insensitive description substring match (`"circuitpython"`, `"pico"`, `"usbmodem"`) for macOS CDC drivers that don't report a VID
  - `PicoECGSensor.__init__` signature changed from `port: str = PICO_ECG_PORT` to `port: str | None = None` — auto-detects when `None`, falls back to `PICO_ECG_PORT` config if nothing found
- `app/core/session.py` — passes `port=None` when constructing `PicoECGSensor` so auto-detection is always used
- `app/ui/views/sensors_view.py` — removed hardcoded mock HRV value `"842 ms  RR"`; replaced with `"—"` (no data yet)

#### Tests
- `tests/test_pico_port_detection.py` — 7 new unit tests (all serial port calls monkeypatched):
  - Returns `None` when no ports connected
  - Detects official Pico by VID `0x2E8A`
  - Detects Adafruit CircuitPython by VID `0x239A`
  - Prefers first match when multiple Picos present
  - Ignores unrecognised devices (e.g. FTDI)
  - Falls back to description match when VID is `None`
  - Description match is case-insensitive

#### Verification
- ✅ `pytest tests/` → **80/80 passed**

---

Logo-Icon und Logo-Schriftzug in der Sidebar wurden auf das Theme-Blau #142970 umgestellt.

## 2026-03-26 — Sensors Page & Sidebar Nav Update

### New File
- `app/ui/views/sensors_view.py` — new "Device Setup" management page

  **`SensorCard(QFrame)`** — reusable device card widget:
  - 40 px Phosphor icon + sensor name + type/port label
  - Amber "Simulated" status badge (becomes green "Test passed" after test)
  - Signal quality bar (`QProgressBar`, 6 px pill, primary-coloured fill)
  - "Last Value" display (pre-populated with realistic mock values)
  - "Test Signal" button → animates bar 0 → 100 → settles to mock quality value, flips badge to green for 2 s

  **`SensorsView(QWidget)`** — page layout:
  - X close button (top-right) → emits `close_requested` → Dashboard
  - "DEVICE SETUP" small-caps title + subtitle (matches calibration page aesthetic)
  - Three `SensorCard`s side-by-side: **HRV Sensor** (`ph.heartbeat-fill`, 82 % quality), **Eye Tracker** (`ph.eye-fill`, 68 %), **Camera** (`ph.camera-fill`, 95 %)
  - Amber info banner below cards: explains mock mode and how to switch to real hardware

### Updated Files
- `app/ui/main_window.py`:
  - Stack indices shifted: `0=Dashboard · 1=Sensors · 2=Calibration · 3=Live · 4=Post-Session`
  - Added `ph.broadcast-fill` "Sensors" nav item above "Calibration" in sidebar
  - Wired `sensors_view.close_requested` → `navigate_to(0)`
  - Updated all `navigate_to()` calls: Calibration=2, Live=3, Post-Session=4
  - `navigate_to()` calibration reset guard updated from `index==1` → `index==2`
  - `view_names` list updated to include "Sensors"

### Verification
- ✅ All 5 views navigate cleanly with zero errors

## 2026-03-26 — Phase: Icon Library Update (Phosphor Icons)

### Updated Files
- `requirements.txt` — Added `qtawesome` to the project dependencies.
- `app/ui/theme.py` — Integrated `qtawesome` and added a `get_icon(name, color, size)` helper function for consistent icon rendering throughout the app.
- `app/ui/main_window.py` — Replaced all sidebar emojis (Logo, Dashboard, Calibration, Settings, Log Out, Recent Sessions) with Phosphor icons (`ph.*`).
- `app/ui/views/dashboard_view.py` — Added icons to "New Session" and "Export" buttons; removed character-based icons.
- `app/ui/views/calibration_view.py` — Completely updated the wizard with Phosphor icons for navigation (back/next), status indicators, notes, and completion checks.
- `app/ui/views/live_view.py` — Updated toolbar with icons for "Video + Data", "Data Only", and "Start/End Session" buttons.
- `app/ui/views/post_session_view.py` — Updated "Export", "Save Session", and timeline placeholder with Phosphor icons.
- `app/ui/widgets/metric_card.py` — Added the left accent bar as specified in the design system, which dynamically updates its color based on CLI/alert state.

---

## 2026-03-26 — User Flow Implementation & Calibration/Live Redesign

### User Flow Enforced
The application now follows the exact intended flow:
1. **Dashboard** → user clicks "New Session" → Calibration opens
2. **Calibration** → user clicks "Start" (breathing baseline, 60 s) → clicks "Start Session" → Live Dashboard
3. **Live Dashboard** → user clicks "END SESSION" (red, top-right toolbar) → Individual Session Dashboard
4. **Post-Session** → user clicks "← Back to Dashboard" → Dashboard

### `app/ui/views/calibration_view.py` — Complete Rewrite
- Removed the 3-step wizard UI entirely
- New `BreathingOrb(QWidget)`: animated 3D sphere using `QPainter` + `QRadialGradient`, pulsing via `QPropertyAnimation` on a custom `orb_radius` pyqtProperty (inhale 4 s → exhale 4 s, chained via `finished` signals)
- Centered, minimal layout: "BASELINE CALIBRATION" small-caps title → orb → "Breath in  •  Breath out" → 5-dot progress indicator → status label → CTA button
- 5 dots fill one-by-one as the 60-second baseline progresses (one dot per 12 seconds)
- CTA button:
  - Before recording: dark navy pill ("▶ Start") — calls `session_manager.start_calibration()`
  - After recording complete: primary blue pill ("▶ Start Session") — emits `proceed_to_live`
- X close button (top-right): emits new `close_requested` signal → MainWindow navigates back to Dashboard
- `reset()` restores all state for re-use across multiple sessions

### `app/ui/views/live_view.py` — Toolbar Redesign + Layout Update
- **Removed** the "Start Session" toggle button entirely — session always starts externally from calibration
- **New toolbar** (matches design images):
  - Left: `●` red dot + "LIVE SESSION" label (letter-spaced, small caps)
  - Centre: segmented tab control — "Biofeedback" tab (default, data-only) + "Camera + Bio" tab
  - Right: `MM:SS` timer · "PAUSE" button (visual, Phase 5) · "END SESSION" red button
- **Default mode is now Biofeedback (Mode B / data-only)** — matches design where "Biofeedback" tab is active
- Mode B layout updated: top row = CORE STATE SYNTHESIS (Cognitive Workload + Physical Stress gauge cards, 40 %) + SYNCHRONIZED STATE TIMELINE chart (60 %); bottom row = 4 metric cards (Pupil Dilation · HRV RMSSD · Task Speed · Accuracy)
- Mode A (Camera + Bio): full-screen camera feed + dark overlay bar at bottom with compact metric labels and timer
- `_set_mode()` updates segmented tab styles (active = filled primary, inactive = outlined) and starts/stops camera feed
- Timer format changed from `HH:MM:SS` to `MM:SS` for sessions under an hour
- `_end_session()` (replaces `_toggle_session`) simply calls `session_manager.end_session()`

### `app/ui/main_window.py` — Routing & Signal Wiring
- `_on_session_ended()` now navigates to `PostSessionView` (index 3) and calls `_post_session_view.load_session(session_id)` — previously it stayed on Dashboard
- Wired `calibration_view.close_requested` → `navigate_to(0)` (back to Dashboard)
- Wired `post_session_view.back_to_dashboard` → `navigate_to(0)`
- Fixed pre-existing broken icon name: `ph.heart-pulse-fill` → `ph.heartbeat-fill`

### `app/ui/views/post_session_view.py` — Load Session & Navigation
- Added `back_to_dashboard = pyqtSignal()` and "←" back button in header
- Added `load_session(session_id)` method: stores the session ID, updates the header title to "Session DD.M.YYYY" (matches individual session dashboard design)
- `_title_label` is now a stored reference (previously was a local variable, preventing later updates)

### Verification
- ✅ All 4 views construct and navigate cleanly with zero errors

---

## 2026-03-26 — Phase: Apply Design System from design.md

### Updated Files
- `app/ui/theme.py` — Completely rewrote the global tokens and stylesheets according to `design.md`. Applied the "Rule of 8" for spacing/padding, the new color palette, typographic scales (`Inter`), and new component-specific style definitions.
- `app/ui/**/*.py` — Refactored all UI components (widgets, views, main window) to use the new exact theme constant names. Migrated font size unit from `pt` to `px` to adhere strictly to the pixel-perfect design specifications.

---

## 2026-03-26 — Phase: Navigation UI Update

### Updated Files
- `app/ui/main_window.py` — Updated the sidebar Information Architecture (IA) to follow a more app-like design:
  - Top: Maintained Logo and Logo Text.
  - Main Navigation: Display only Dashboard and Calibration.
  - Recent Sessions: Added a dynamic "RECENT SESSIONS" area displaying the latest 5 sessions, querying `SessionRepository`.
  - Bottom Navigation: Added "Settings" and "Log Out" buttons.
  - Updated `_on_session_ended` handler to ensure the recent sessions list refreshes automatically upon session completion.

---

## 2026-03-26 — Phase 3: Live View Widgets & Full Wiring

### New Widgets
- `app/ui/widgets/metric_card.py` — animated `MetricCard` (QPropertyAnimation on value, CLI colour-coding)
- `app/ui/widgets/live_chart.py` — `LiveChart` pyqtgraph scrolling chart, multi-series, themed
- `app/ui/widgets/video_feed.py` — `VideoFeed` (OpenCV in `QThread` → `QPixmap` → `QLabel`)
- `app/ui/widgets/session_table.py` — `SessionTable` sortable widget, emits `session_selected`

### Updated Files
- `app/ui/views/live_view.py` — full Phase 3 rewrite: `MetricCard`, `LiveChart`, `VideoFeed` all wired; `bind_session_manager()` for DI; Mode A/B fully functional; all signal slots implemented
- `app/ui/views/dashboard_view.py` — accepts `DatabaseManager`, uses real `SessionTable`, `refresh()` slot
- `app/ui/main_window.py` — owns `DatabaseManager` + `SessionManager`; injects into views; `session_ended → dashboard.refresh()`

### Tests
- `tests/test_processors.py` — 12 new unit tests for `HRVProcessor`, `PupilProcessor`, `CLIProcessor`

### Verification
- ✅ `pytest tests/` → **31/31 passed**
- ✅ App smoke-test → DB created, dashboard loads, LiveView bound — zero warnings

---

## 2026-03-26 — Phase 1: Foundation

### Project Setup
- Read `plan.md` and `claude.md` to understand architecture, stack, and coding standards
- Created `requirements.txt` (PyQt6, pyqtgraph, opencv-python, pyserial, numpy, pandas, pytest)
- Created Python virtual environment (`.venv`) and installed all dependencies
- Created all package `__init__.py` files for `app/`, `app/core/`, `app/hardware/`, `app/processing/`, `app/storage/`, `app/ui/`, `app/ui/views/`, `app/ui/widgets/`, `app/utils/`, `tests/`

### Utils
- `app/utils/logger.py` — application-wide logging (console DEBUG, file INFO)
- `app/utils/config.py` — all runtime constants (ports, thresholds, weights, mock settings, DB path)

### UI — Theme & Navigation
- `app/ui/theme.py` — full design token system (colours, fonts, spacing) + global Qt stylesheet
- `app/ui/main_window.py` — root `QMainWindow` with sidebar navigation and `QStackedWidget` for 4 views

### UI — Views (polished skeletons)
- `app/ui/views/dashboard_view.py` — summary cards, session history table, export button
- `app/ui/views/calibration_view.py` — 3-step wizard with step indicator, live 60s baseline countdown
- `app/ui/views/live_view.py` — Mode A/B toggle, session timer, CLI gauge with colour-coded thresholds
- `app/ui/views/post_session_view.py` — timeline placeholder, full 6-dimension NASA-TLX slider form

### Core Business Logic
- `app/core/metrics.py` — `compute_rmssd()`, `compute_pdi()`, `compute_cli()`, `normalize()` (pure functions, scientific docstrings)
- `app/core/nasa_tlx.py` — `NASATLXRatings`, `NASATLXWeights` dataclasses, `compute_weighted_tlx()`, `compute_raw_tlx()`
- `app/core/data_store.py` — in-session ring-buffer (`deque`) for HRV, pupil, and CLI samples
- `app/core/session.py` — `SessionManager`: wires sensors → processors → DB, manages lifecycle (start/end)

### Hardware Layer
- `app/hardware/base_sensor.py` — abstract `BaseSensor(QObject)` with `start()`/`stop()` contract
- `app/hardware/mock_sensors.py` — `MockHRVSensor` and `MockEyeTracker` (QTimer-driven, realistic noise/drift)
- `app/hardware/hrv_sensor.py` — real HRV driver stub (raises `NotImplementedError`, Phase 6)
- `app/hardware/eye_tracker.py` — real eye tracker stub (raises `NotImplementedError`, Phase 6)

### Signal Processing Pipeline
- `app/processing/hrv_processor.py` — sliding 30s window RMSSD, emits `rmssd_updated` signal
- `app/processing/pupil_processor.py` — blink artifact rejection, PDI computation, emits `pdi_updated`
- `app/processing/cli_processor.py` — fuses RMSSD + PDI into CLI with session-wide min/max normalization

### Storage Layer
- `app/storage/database.py` — `DatabaseManager`: opens SQLite, creates schema (sessions, hrv_samples, pupil_samples, cli_samples), manages connection
- `app/storage/session_repository.py` — CRUD for sessions table (create, end, save NASA-TLX, get all, delete)
- `app/storage/export.py` — `SessionExporter`: CSV (flat merged) and JSON (structured) export

### Entry Point
- `main.py` — creates `QApplication`, sets Inter font, shows `MainWindow`

### Tests
- `tests/test_metrics.py` — 19 unit tests for RMSSD, PDI, normalize, CLI (edge cases + randomised property tests)

### Verification
- ✅ `pytest tests/test_metrics.py` → **19/19 passed**
- ✅ App smoke-test → `MainWindow` initialises with zero Qt warnings
- Fixed: removed unsupported `font-variant-numeric` CSS property
- Fixed: `QLayout::addChildLayout` warning in `post_session_view.py` (duplicate layout add)
