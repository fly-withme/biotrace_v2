# BioTrace — Claude Context File

This file is the anchor for all AI-assisted development sessions on this project.
Read this file at the start of every session before writing any code.

---

## Project Summary

**BioTrace** is a local desktop application providing real-time physiological biofeedback
for doctors and medical students training on laparoscopy box trainers. It measures:

- **Stress** → HRV (RMSSD) from a heart rate sensor via microcontroller
- **Cognitive Load** → Pupil dilation index (PDI) from an eye tracker
- **Composite Score** → Cognitive Load Index (CLI), later enriched by NASA-TLX

A camera attached to the eye tracker provides a live video feed synced with all
biofeedback data for post-session analysis.

**Audience:** Medical professionals and researchers — not software engineers.
Code must be maximally readable, documented, and scientifically transparent.

---

## Tech Stack

| Component          | Tool                        |
|--------------------|-----------------------------|
| UI Framework       | PyQt6                       |
| Real-time charts   | pyqtgraph                   |
| Video              | OpenCV (opencv-python)      |
| Serial/USB comms   | pyserial                    |
| Database           | SQLite3 (Python stdlib)     |
| Numerics           | NumPy                       |
| Data wrangling     | Pandas                      |
| Testing            | pytest                      |

---

## UI Design Tokens

Full design system is in `design.md`. All constants are defined in `app/ui/theme.py`.
Never hardcode a color, pixel value, or font size in a widget file — always import from `theme.py`.

**Critical color rule:** `COLOR_PRIMARY (#3B579F)` is for buttons, icons, chart lines,
metric value text, and active nav indicators **only**. It must **never** be used as a
card or panel background. Use `COLOR_CARD (#FFFFFF)` for all card backgrounds.

Core tokens:
```python
COLOR_PRIMARY    = "#3B579F"   # buttons, icons, chart lines, metric values, active states
COLOR_BACKGROUND = "#F9FBFF"   # main window + sidebar background
COLOR_CARD       = "#FFFFFF"   # ALL card and panel backgrounds
COLOR_FONT       = "#142970"   # primary body text
COLOR_FONT_MUTED = "#6B7A9F"   # captions, secondary labels
COLOR_BORDER     = "#DDE3F0"   # card borders, dividers
FONT_FAMILY      = "Inter"
FONT_BODY        = 14          # base font size (px)
```

Spacing follows the **Rule of 8** — all values are multiples of 8px (see `design.md` §4).
Layout follows **Rule of Thirds** on a 12-column grid (see `design.md` §6).

---

## Directory Structure (abbreviated)

```
biotrace/
├── main.py                      # Entry point — creates QApplication, shows MainWindow
├── app/
│   ├── core/                    # Pure business logic (no Qt, no UI)
│   │   ├── session.py           # Session lifecycle
│   │   ├── metrics.py           # RMSSD, PDI, CLI formulas
│   │   ├── nasa_tlx.py          # NASA-TLX score
│   │   └── data_store.py        # In-session ring buffer
│   ├── hardware/                # Sensor drivers (one file per device)
│   │   ├── base_sensor.py       # Abstract base class all sensors inherit
│   │   ├── hrv_sensor.py        # Heart rate / HRV hardware driver
│   │   ├── eye_tracker.py       # Eye tracker hardware driver
│   │   ├── camera.py            # OpenCV camera wrapper
│   │   └── mock_sensors.py      # Simulated sensors for dev/testing
│   ├── processing/              # Real-time signal processing
│   │   ├── hrv_processor.py     # RR intervals → RMSSD
│   │   ├── pupil_processor.py   # Raw diameter → PDI, blink rejection
│   │   └── cli_processor.py     # RMSSD + PDI → CLI
│   ├── storage/                 # SQLite persistence
│   │   ├── database.py          # Schema creation, connection management
│   │   ├── session_repository.py
│   │   └── export.py            # CSV / JSON export
│   └── ui/
│       ├── theme.py             # ALL style constants live here
│       ├── main_window.py       # Root window and view navigation
│       ├── views/               # One file per page/screen
│       │   ├── dashboard_view.py
│       │   ├── calibration_view.py
│       │   ├── live_view.py
│       │   └── post_session_view.py
│       └── widgets/             # Reusable custom widgets
│           ├── metric_card.py
│           ├── live_chart.py
│           ├── video_feed.py
│           ├── session_table.py
│           └── nasa_tlx_widget.py
└── tests/
```

---

## Coding Standards

### General Rules
- **Python 3.11+** syntax throughout.
- **Type hints on every function signature** — parameters and return values.
- **Docstrings on every class and public method** using Google style.
- **No magic numbers** — all thresholds, weights, and constants go in `app/utils/config.py`.
- Line length: **100 characters**.
- Use `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE` for constants.

### OOP Rules
- Every class has a single, clearly stated responsibility (Single Responsibility Principle).
- Prefer **composition over inheritance**, except for sensor drivers (which inherit `BaseSensor`).
- Qt widgets inherit from the appropriate Qt base class (`QWidget`, `QFrame`, etc.).

### Qt-Specific Rules
- **Never do computation in a UI thread.** Hardware reading and signal processing run in
  `QThread` workers. Results are sent to the UI via Qt signals — never by direct method calls.
- **Never import from `app/ui/` inside `app/core/` or `app/processing/`.** The core
  business logic must remain framework-agnostic.
- Connect signals to slots with the syntax:
  `sender.signal_name.connect(receiver.slot_method)`

### Documentation Standard for Scientific Code

For every formula implementation, include a docstring block in this format:

```python
def compute_rmssd(rr_intervals: np.ndarray) -> float:
    """Compute the Root Mean Square of Successive Differences (RMSSD).

    RMSSD is a time-domain HRV metric reflecting parasympathetic nervous
    system activity. Higher values indicate lower physiological stress.

    Formula:
        RMSSD = sqrt( mean( (RR[i+1] - RR[i])^2 ) )

    Args:
        rr_intervals: Array of successive RR intervals in milliseconds.
                      Minimum 2 values required.

    Returns:
        RMSSD value in milliseconds. Returns 0.0 if fewer than 2 intervals
        are provided.

    References:
        Task Force of ESC and NASPE (1996). Heart rate variability: standards
        of measurement. Circulation, 93(5), 1043-1065.
    """
```

---

## Key Algorithms (Reference)

### RMSSD
```
RMSSD = sqrt( mean( (RR[i+1] - RR[i])^2 ) )
```
- Sliding 30-second window, updated every 1 second.
- Higher RMSSD = lower stress.

### Pupil Dilation Index (PDI)
```
PDI = (current_diameter - baseline_diameter) / baseline_diameter
```
- Baseline from calibration phase (60-second resting average).
- Blink artifacts rejected when diameter drop velocity exceeds threshold.

### Cognitive Load Index (CLI)
```
CLI = w1 * norm(1 / RMSSD) + w2 * norm(PDI)
```
- Both inputs normalized 0–1 against session min/max.
- Default weights: `w1 = 0.5`, `w2 = 0.5` (set in `config.py`).
- Range: 0.0 (no load) to 1.0 (maximum load).

---

## Hardware Interface Contract

All sensor classes **must** inherit `BaseSensor` and implement:

```python
class BaseSensor(QObject):
    def start(self) -> None: ...   # begin streaming
    def stop(self) -> None: ...    # stop and clean up
    # Each subclass defines its own data signal, e.g.:
    # raw_data_received = pyqtSignal(float)
```

To swap a sensor: create a new class inheriting `BaseSensor`, implement `start()`/`stop()`,
and emit the same signal name. The rest of the system requires zero changes.

---

## What NOT to Do

- Do not hardcode serial port names (e.g., `/dev/ttyUSB0`) — use `config.py`.
- Do not put formulas or computations inside Qt widget files.
- Do not use global variables — pass dependencies via constructors.
- Do not use `time.sleep()` in the UI thread — use `QTimer` instead.
- Do not use `print()` for debugging — use the logger from `app/utils/logger.py`.
- Do not skip the `mock_sensors.py` path — always ensure the app runs without hardware connected.

---

## Current Development Phase

See `plan.md` for the full roadmap. Always check which phase is currently active
before implementing new features to ensure work is sequenced correctly.
