# BioTrace — Pupil Dilation Integration Plan

## 1. Code Review of `app/processing/test_pupil.py`

### What the colleague built

The script opens a USB camera with OpenCV, runs the **PuRe** pupil-detection
algorithm (`pypupilext.PuRe`), collects a 3-second baseline, then streams
`percent_change = (diameter − baseline) / baseline × 100` to a CSV file.

**PuRe** (Santini et al., 2018, *Computer Vision and Image Understanding*)
is a well-validated, real-time pupil-detection algorithm. Using it here is
the correct scientific choice.

---

### What is good

| Feature | Assessment |
|---------|------------|
| `PuRe` detector | Correct algorithm for the task. Well-cited in eye-tracking literature. |
| Confidence threshold `valid(0.35)` | Filters low-quality detections. Appropriate starting value. |
| ROI optimisation | Checks the last known pupil location first; falls back to full frame. Reduces CPU load and false positives. |
| EMA smoothing on centre position (`α = 0.3`) | Reduces jitter in position tracking. |
| 10-sample rolling mean on `percent_change` | Equivalent to a simple moving average filter. Good noise reduction. |
| ±40 % outlier clamp | Physiologically motivated range filter. A change > 40 % is almost certainly an artefact. |
| Last-known-position hold (0.5 s) | Gracefully handles brief blinks without losing the pupil. |

---

### Issues that must be fixed before integration

#### Issue A — Units: pixels, not millimetres

`pupil.diameter()` returns diameter in **pixels** (image coordinates).
The existing `PupilProcessor`, `compute_pdi()`, and the `pupil_samples`
database table all use the variable name `*_mm`, suggesting millimetres.

**However:** PDI is a dimensionless ratio —
`PDI = (d − d_baseline) / d_baseline`.
As long as the *same* camera measures both the baseline and the live diameter,
pixels and millimetres produce the same ratio. The unit cancels.

**Fix:** Keep the pixel values throughout. Rename internal variables and
DB column comments from `_mm` to `_px` (or document the unit as "camera units").
Do not attempt a pixel → mm conversion — that would require a known physical
reference object in the camera frame, which we don't have.

#### Issue B — Script architecture, not a class

The code is a top-level script with a `while True` loop and `cv2.imshow()`.
It must be refactored into a `QThread`-based driver class that emits Qt signals,
following the `BaseSensor` contract used by `HRVSensor` and `MockEyeTracker`.
The `cv2.imshow()` and CSV writing must be removed entirely.

#### Issue C — Blink velocity threshold unit mismatch

`PUPIL_BLINK_VELOCITY_THRESHOLD = 2.0` in `config.py` was sized for mm/sample.
In pixels, a blink drop is typically 20–80 px/sample depending on camera
magnification. A new constant `PUPIL_BLINK_VELOCITY_THRESHOLD_PX` must be
added.

The colleague's ±40 % outlier clamp is a cleaner, unit-independent approach and
should be added as a second guard in `PupilProcessor` alongside the velocity filter.

#### Issue D — Monocular camera (one eye, not two)

The script detects a single pupil. The existing signal contract is:
`raw_pupil_received(left_diameter, right_diameter, timestamp_s)`.

For a single-eye tracker, emit the detected diameter as `left_diameter`
and `0.0` as `right_diameter`. Update `average_pupil_diameter()` to treat
`0.0` as "unavailable" (same as `None`) so the average is not halved.

#### Issue E — Baseline duration mismatch

The script collects 3 seconds of baseline. BioTrace uses a 60-second calibration
phase (`CALIBRATION_DURATION_SECONDS = 60`). The colleague's baseline is *not*
used in integration — our existing calibration phase governs baseline collection.
No change needed to the calibration logic; this is just a context note.

#### Issue F — `pypupilext` not in requirements

`pypupilext` must be added to `requirements.txt`. It is available on PyPI
(`pip install pypupilext`). It depends on OpenCV, which is already present.

---

### Hardware clarification

The eye-tracker camera is a **standard USB camera** connected directly to the
laptop. OpenCV accesses it by index (`cv2.VideoCapture(N)`). The Pi Pico is
**not** involved in pupil tracking — it handles only the ECG/HRV signal via
serial. A new config constant `EYE_TRACKER_CAMERA_INDEX` (default `0`) tells
the driver which camera to open.

---

## 2. Integration Architecture

```
EyeTrackerSensor (new QThread worker)
  USB camera → PuRe detector → diameter_px
  emits raw_pupil_received(diameter_px, 0.0, timestamp_s)
         ↓
PupilProcessor (existing — minor updates)
  blink velocity filter (pixel threshold)
  ±40 % outlier clamp  (new)
  PDI = (d − baseline) / baseline
  emits pdi_updated(pdi, timestamp_s)
         ↓
         ├─► CLIProcessor (existing, unchanged)
         │     combines RMSSD + PDI → CLI
         │     emits cli_updated(cli, timestamp_s)
         │
         └─► DataStore (existing)
               pupil_samples written per sample
               cli_samples written per sample

Calibration phase (existing, unchanged)
  MockEyeTracker / EyeTrackerSensor runs for 60 s
  baseline_pupil_px = mean of all accepted diameters during calibration
  → PupilProcessor.set_baseline(baseline_pupil_px)
  → CalibrationRepository saves baseline_pupil_px as baseline_pupil_mm column
    (column name retained; unit is now pixels but the ratio computation is identical)

LiveView (existing, no new cards needed)
  PUPIL DILATION card ← pdi_updated (already wired for mock data)
  COGNITIVE WORKLOAD  ← cli_updated  (already wired for mock data)

SessionRepository / DataStore (existing)
  pupil_samples.left_diameter  ← diameter_px
  pupil_samples.pdi            ← PDI value

Dashboard (existing, no change)
  avg CLI per session is already computed from cli_samples

Individual session dashboard (existing, no change)
  TimelineChart will plot pdi from pupil_samples once Issue 7 (plan.md) is done
```

---

## 3. Where Pupil Data Belongs in the UI

No new cards or UI components are needed. The data fits naturally into
existing slots:

| UI location | Signal / data | Status |
|-------------|---------------|--------|
| Live View — PUPIL DILATION card | `pdi_updated` | Already wired; just needs real data |
| Live View — COGNITIVE WORKLOAD card | `cli_updated` | Already wired; just needs real data |
| Post-session timeline chart | `pupil_samples.pdi` from DB | Covered by plan.md Issue 7 |
| Dashboard session table — avg CLI | `cli_samples` average | Already computed on session end |
| Calibration view | baseline collection | Already implemented; no change |

---

## 4. Implementation Issues

Work these in order. Issues 1–2 are prerequisites for the rest.

---

### Issue P-1 — Add `pypupilext` dependency and config constants
**Files:** `requirements.txt`, `app/utils/config.py`

- Add to `requirements.txt`:
  ```
  pypupilext
  ```
- Add to `config.py`:
  ```python
  # Eye tracker — USB camera (separate from endoscopy camera)
  EYE_TRACKER_CAMERA_INDEX: int = 0

  # Pupil blink rejection: max drop in pixels per sample.
  # Tune after testing on real hardware. Start at 20.
  PUPIL_BLINK_VELOCITY_THRESHOLD_PX: float = 20.0

  # Pupil outlier clamp: discard if |PDI| > this fraction.
  # 0.40 = 40 % change from baseline — physiological upper bound.
  PUPIL_PDI_OUTLIER_CLAMP: float = 0.40
  ```

---

### Issue P-2 — Fix `average_pupil_diameter()` for monocular input
**File:** `app/core/metrics.py`

Update the filter to treat `0.0` as "unavailable" (same as `None`):

```python
def average_pupil_diameter(
    left: float | None, right: float | None
) -> float | None:
    values = [v for v in (left, right) if v is not None and v > 0.0]
    return float(np.mean(values)) if values else None
```

Update the docstring to say "pixels (camera units)" rather than "millimetres".
Also update the `pupil_samples` schema comments in `database.py` to say
"camera units (pixels)" instead of "millimetres".

**Tests:** Add two cases to `tests/test_metrics.py`:
- `average_pupil_diameter(120.0, 0.0)` returns `120.0` (not `60.0`)
- `average_pupil_diameter(0.0, 0.0)` returns `None`

---

### Issue P-3 — Update `PupilProcessor` for pixel threshold + outlier clamp
**File:** `app/processing/pupil_processor.py`

Two changes:

1. Import `PUPIL_BLINK_VELOCITY_THRESHOLD_PX` and `PUPIL_PDI_OUTLIER_CLAMP`
   instead of `PUPIL_BLINK_VELOCITY_THRESHOLD`.
   Use `PUPIL_BLINK_VELOCITY_THRESHOLD_PX` in the velocity check.

2. After computing `pdi`, add the outlier clamp before emitting:
   ```python
   from app.utils.config import PUPIL_PDI_OUTLIER_CLAMP
   ...
   pdi = compute_pdi(diameter, self.baseline_mm)
   if abs(pdi) > PUPIL_PDI_OUTLIER_CLAMP:
       logger.debug("PDI outlier rejected: pdi=%.3f", pdi)
       return
   self.pdi_updated.emit(pdi, timestamp_s)
   ```

**Tests:** `tests/test_processors.py`
- Sample with `|PDI| > 0.40` is rejected and not emitted.
- Sample with `|PDI| = 0.40` (boundary) is accepted.
- Velocity rejection still works with the new threshold name.

---

### Issue P-4 — Implement `EyeTrackerSensor` (replaces the stub)
**File:** `app/hardware/eye_tracker.py`

Full replacement of the current `NotImplementedError` stub. Model it on
`app/hardware/pico_ecg_sensor.py` for the QThread + signal pattern.

```python
class _PupilWorker(QThread):
    """Background thread: camera capture + PuRe detection."""
    raw_pupil_received        = pyqtSignal(float, float, float)
    connection_status_changed = pyqtSignal(bool, str)

    def run(self) -> None:
        import pypupilext as pp
        cap = cv2.VideoCapture(EYE_TRACKER_CAMERA_INDEX)
        if not cap.isOpened():
            self.connection_status_changed.emit(False, "Eye tracker camera not found")
            return
        self.connection_status_changed.emit(True, "Eye tracker connected")
        detector = pp.PuRe()
        last_good_center = None
        last_good_time = 0.0
        roi_size = 160
        alpha = 0.3
        smoothed_center = None
        HOLD_TIME = 0.5
        ...
        # port the detection loop from test_pupil.py here
        # emit: self.raw_pupil_received.emit(diameter_px, 0.0, time.time())
        # no cv2.imshow(), no CSV writing

    def stop(self) -> None: ...


class EyeTrackerSensor(BaseSensor):
    raw_pupil_received        = pyqtSignal(float, float, float)
    connection_status_changed = pyqtSignal(bool, str)

    def start(self) -> None:
        self._worker = _PupilWorker()
        self._worker.raw_pupil_received.connect(self.raw_pupil_received)
        self._worker.connection_status_changed.connect(self.connection_status_changed)
        self._worker.start()

    def stop(self) -> None:
        if self._worker: self._worker.stop()
```

Key implementation notes from `test_pupil.py` to preserve:
- ROI optimisation (try last known position first)
- EMA smoothing on centre position (`α = 0.3`)
- Confidence threshold `valid(0.35)`
- Last-known-position hold (0.5 s) for brief blinks
- Do **not** port the ±40 % filter here — it now lives in `PupilProcessor`

---

### Issue P-5 — Wire `EyeTrackerSensor` into `SessionManager`
**File:** `app/core/session.py`

`USE_EYE_TRACKER = True` already controls whether the eye tracker starts.
The only change: replace the import of `EyeTracker` (the old stub) with
`EyeTrackerSensor` from `app.hardware.eye_tracker`.

The rest of the wiring (signals → `PupilProcessor` → `CLIProcessor`) is already
in place and does not change.

Also wire `connection_status_changed` from `EyeTrackerSensor` to
`SessionManager.eye_connection_changed` (same pattern as HRV sensor).

---

### Issue P-6 — Enable `USE_EYE_TRACKER` in `config.py`
**File:** `app/utils/config.py`

```python
# Set to True when the eye-tracker USB camera is physically connected.
USE_EYE_TRACKER: bool = True   # was False
```

This is the single switch that activates the real sensor throughout the system.
When `False`, `MockEyeTracker` is used (existing behaviour).

---

### Issue P-7 — Update `MockEyeTracker` to emit pixel-range values
**File:** `app/hardware/mock_sensors.py`

The mock currently emits values in `[MOCK_PUPIL_MIN_MM, MOCK_PUPIL_MAX_MM]`
(3.0 – 7.0). These should be renamed to `MOCK_PUPIL_MIN_PX` and
`MOCK_PUPIL_MAX_PX` and set to realistic pixel values (e.g., 80–160 px) so
that mock sessions produce PDI values in the same physiological range as real
hardware.

Update `config.py`:
```python
MOCK_PUPIL_MIN_PX: float = 80.0    # replaces MOCK_PUPIL_MIN_MM
MOCK_PUPIL_MAX_PX: float = 160.0   # replaces MOCK_PUPIL_MAX_MM
```

Update `MockEyeTracker` to use the new constants and emit `(diameter_px, 0.0, ts)`.

---

## 5. File Change Summary

| File | Change |
|------|--------|
| `requirements.txt` | Add `pypupilext` |
| `app/utils/config.py` | Add `EYE_TRACKER_CAMERA_INDEX`, `PUPIL_BLINK_VELOCITY_THRESHOLD_PX`, `PUPIL_PDI_OUTLIER_CLAMP`; rename mock pupil constants; set `USE_EYE_TRACKER = True` |
| `app/core/metrics.py` | Fix `average_pupil_diameter` to treat `0.0` as unavailable; update docstring units |
| `app/storage/database.py` | Update `pupil_samples` column comments: "mm" → "camera units (px)" |
| `app/processing/pupil_processor.py` | Use pixel threshold; add `PUPIL_PDI_OUTLIER_CLAMP` guard |
| `app/hardware/eye_tracker.py` | Full replacement: implement `_PupilWorker` + `EyeTrackerSensor` |
| `app/hardware/mock_sensors.py` | Update `MockEyeTracker` to pixel-range constants |
| `tests/test_metrics.py` | New tests for monocular `average_pupil_diameter` |
| `tests/test_processors.py` | New tests for PDI outlier clamp |

The `test_pupil.py` script in `app/processing/` is a development artefact
and should be moved to a `docs/` folder or deleted once the integration is
verified on real hardware.

---

## 6. Testing on Real Hardware

Once the integration is complete, verify with the following checklist:

- [ ] `EyeTrackerSensor` starts without error when the USB camera is connected.
- [ ] PUPIL DILATION card in Live View updates in real-time during a session.
- [ ] Calibration phase collects `baseline_pupil_px` and stores it to DB.
- [ ] PDI values after calibration are near `0.0` at rest and increase under load.
- [ ] Disconnecting the camera mid-session shows the "disconnected" badge and
      zeroes the pupil card (same pattern as HRV sensor).
- [ ] `cli_samples` table is populated with non-zero CLI values during a session
      (confirms RMSSD + PDI are both reaching `CLIProcessor`).
- [ ] `PUPIL_BLINK_VELOCITY_THRESHOLD_PX` may need tuning — log rejected samples
      during a test session and adjust if too many good samples are being dropped.

---

## 7. Open Questions for the Colleague

1. **Camera distance and optics:** How far is the camera from the eye, and does
   the setup change between sessions? If constant, a one-time pixel → mm
   calibration factor could be added later for scientific reporting.

2. **Lighting:** PuRe works best with near-infrared illumination. Under visible
   light the confidence threshold may need to be lowered from `0.35` to `0.25`.
   Test and adjust `valid(0.35)` after the first hardware session.

3. **Camera index:** Confirm whether the eye-tracker camera appears as index `0`
   or a higher index on the target laptop. Set `EYE_TRACKER_CAMERA_INDEX`
   accordingly in `config.py`.

4. **Frame rate:** The script doesn't cap the frame rate. Add a `QThread.msleep(33)`
   (≈ 30 Hz) in the worker loop to avoid saturating a CPU core.
