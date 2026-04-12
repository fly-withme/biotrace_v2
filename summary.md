# BioTrace Dashboard Build Summary

## 1) How We Built the Dashboard

### Architecture
- We built the app as a **PyQt6 desktop application** with a central `MainWindow` and a `QStackedWidget` page flow: **Dashboard -> Calibration -> Live -> Post-Session**.
- The `MainWindow` owns shared infrastructure:
  - `DatabaseManager` (SQLite schema + persistence)
  - `SessionManager` (sensor lifecycle, calibration, session state machine, signal wiring)
- The dashboard is data-backed, not mocked: session metrics are queried from SQLite (`sessions`, `hrv_samples`, `pupil_samples`, `cli_samples`, `calibrations`).

### Real-time data flow
1. Hardware sensors emit raw data.
2. Processing modules compute clean physiological metrics.
3. `SessionManager` forwards signals to `LiveView` and stores samples in-memory (`DataStore`).
4. On session end, samples are bulk-written to SQLite and auto-exported to Excel.

### Dashboard analytics
- Cross-session metrics are computed in `performance_repository.py`.
- Dashboard trends are normalized for comparability:
  - **Stress trend** from RMSSD (inverted z-score percentile)
  - **Workload trend** from CLI (z-score percentile)

---

## 2) How We Built the HRV Sensor and Processing

### Hardware and acquisition (Pi Pico ECG)
- We use a **Raspberry Pi Pico ECG stream** over USB serial.
- ECG samples are parsed from `Yeda...` lines and processed with real-time R-peak detection.

### R-peak detection algorithm
- **Sample rate:** `150 Hz`
- **Adaptive amplitude window:** `150 samples` (~1 s)
- **Threshold factor:** `0.65 * adaptive amplitude`
- **Refractory period:** `90 samples` (~600 ms)
- **DC drift removal:** EMA baseline subtraction (`alpha=0.002`)
- RR interval formula:
  - `RR_ms = (sample_index_diff / 150) * 1000`

### HRV computation
- RR intervals are passed to `HRVProcessor`.
- **Physiology filter:** reject `RR < 500 ms` (noise/artifacts/highly implausible beats for this context).
- **RMSSD window:** rolling `30 s`.
- RMSSD formula:
  - `RMSSD = sqrt(mean((RR[i+1] - RR[i])^2))`

### HRV change and thresholds
- During calibration, baseline RMSSD is recorded.
- During live session, displayed HRV change is:
  - `RMSSD_change_% = ((RMSSD_t - RMSSD_baseline) / RMSSD_baseline) * 100`
- Stress interpretation thresholds:
  - Low stress region: `>= -10%`
  - Transitional region: `-10% to -40%`
  - High stress region: `< -40%`
- Dashboard stress-event counting threshold:
  - Event if `RMSSD < 0.60 * baseline` (drop > 40%).

---

## 3) How We Built the Eye Tracker and Programmed Pupil Dilation (Most Important)

### Eye tracker implementation
- The eye tracker uses a dedicated USB camera and runs in a background worker thread.
- Primary detector: **PuRe** (`pypupilext`), confidence-gated.
- If PuRe is unavailable, we use an OpenCV fallback contour/ellipse pipeline.

### Detection pipeline
1. Capture frame from eye camera.
2. Convert to grayscale.
3. Try **ROI-based detection** around last valid center (faster/more stable).
4. If ROI fails, run full-frame detection.
5. Smooth center with EMA (`alpha=0.3`).
6. Brief losses/blinks are tolerated with a hold window (`0.5 s`).
7. Emit measured pupil diameter in pixels.

### Calibration baseline (critical)
- Baseline is acquired during calibration (`60 s`):
  - collect raw pupil diameters
  - compute baseline as mean pupil diameter in px
- This baseline is stored and reused in live processing.

### Pupil dilation programming and measurement
- Raw pupil samples go through `PupilProcessor`:
  1. Average left/right diameters (ignoring missing/zero eye values).
  2. **Blink artifact rejection by velocity**:
     - reject sample if `|diameter_t - diameter_(t-1)| > 20 px/sample`
  3. Compute pupil change from baseline:
     - `Pupil_change_% = ((diameter_t - baseline_diameter) / baseline_diameter) * 100`
  4. **Outlier clamp threshold**:
     - reject if `|Pupil_change_%| > 40%`
  5. Emit accepted change as live PDI signal.

### Pupil-change thresholding (WIV/threshold logic)
- Workload gauge is driven by absolute pupil change magnitude:
  - `Workload_% = min(100, abs(Pupil_change_%) / 20 * 100)`
- So `20%` pupil change corresponds to a full-scale workload gauge.
- If no calibration baseline exists, runtime fallback baseline is bootstrapped from first valid sample.

---

## 4) Cognitive Load and Performance Data

### Cognitive load
- Two related signals exist:
  - **Live workload gauge:** directly from pupil change magnitude (fast operator feedback)
  - **CLI series (stored):** normalized session-wise from running min/max of PDI (`0..1`)
- Configured CLI alert thresholds:
  - Low boundary: `0.33`
  - High boundary: `0.66`

### Performance data (cross-session)
- For each completed session, we aggregate:
  - session duration
  - session error count
  - average RMSSD
  - average CLI
- Performance model in dashboard:
  - normalize `duration` and `error_count`
  - `performance_error = (0.5*norm(duration) + 0.5*norm(error_count)) * 100`
  - `performance_score = 100 - performance_error`
- Interpretation:
  - Lower time + lower errors -> lower performance error -> higher performance score.

---

## 5) One-Slide Executive Summary
- We built a real-time PyQt dashboard around a strict sensor -> processor -> storage -> analytics pipeline.
- HRV is measured from Pico ECG using adaptive-threshold R-peak detection and rolling RMSSD.
- Eye tracking is camera-based (PuRe + fallback), with explicit blink rejection and baseline-relative pupil change.
- The key cognitive-load driver is **pupil dilation change** with clear thresholds (`20%` full-scale workload, `40%` outlier rejection).
- Session and cross-session performance combine physiological data and task outcomes (duration + errors) into interpretable scores.
