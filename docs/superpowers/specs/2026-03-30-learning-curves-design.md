# BioTrace — Learning Curves Feature Design

**Date:** 2026-03-30
**Status:** Approved
**Author:** Brainstorming session (Claude + user)
**Reference:** Schmettow, Chan, Groenier (2026). *Parametric learning curve models for simulation-based surgery training.*

---

## 1. Goal

Integrate the Schmettow parametric learning curve model into BioTrace so that:

1. The main Dashboard displays a trainee's full learning trajectory across all sessions.
2. The Post-Session view gives immediate, individualised "honest mentor" feedback on where the trainee sits relative to their predicted performance ceiling.
3. Error counting (wire touches on the laparoscopy box) is captured via a manual UI fallback now, with a hardware driver hook for Phase 6b.

---

## 2. Scope

### In scope (this sprint)
- `app/analytics/` package: `learning_curve.py` + `performance_repository.py`
- `app/ui/widgets/learning_curve_chart.py` — pyqtgraph chart widget
- `app/ui/widgets/error_input.py` — Live View manual error counter
- `app/hardware/error_counter.py` — hardware driver stub + QThread worker
- Extend `DashboardView` with learning curve card
- Extend `PostSessionView` with "Honest Mentor" strip
- Extend `LiveView` toolbar with error input widget
- Extend `SessionManager` to store `error_count` on session end
- New constants in `config.py`: `SCORE_MAX`, `LC_MIN_SESSIONS`
- Full unit tests for `learning_curve.py` and `performance_repository.py`

### Out of scope (future sprints)
- Multi-trainee / multi-level modelling (requires `users` table)
- Full Bayesian inference (Stan/PyMC) for parameter uncertainty
- Confidence intervals and R² diagnostics panel
- Hardware GPIO error detection (Phase 6b)
- Eye tracker integration (Phase 6b)

---

## 3. The Schmettow Model

### 3.1 Formula

Performance on trial `t` for a single trainee:

```
errors(t) = scale * (1 - leff)**(t + pexp) + maxp
```

| Parameter | Symbol | Domain | Meaning |
|-----------|--------|--------|---------|
| Learning efficiency | `leff` | (0, 1) | How rapidly errors decrease per trial. Higher = faster learning. |
| Previous experience | `pexp` | ℝ⁺ | Effective prior training expressed in trial-equivalents. Horizontal shift. |
| Maximum performance | `maxp` | ℝ⁺ | Asymptotic error floor. Irreducible minimum errors no matter how much training. |
| Scale | `scale` | ℝ⁺ | Magnitude of the trainable component. Population-level parameter. |

### 3.2 Unbounded Parameterisation for Fitting

To use `scipy.optimize.curve_fit` with Gaussian-friendly parameters:

```
leff_raw  → sigmoid(leff_raw)      maps ℝ → (0, 1)
pexp_raw  → exp(pexp_raw)          maps ℝ → ℝ⁺
maxp_raw  → exp(maxp_raw)          maps ℝ → ℝ⁺
scale_raw → exp(scale_raw)         maps ℝ → ℝ⁺
```

### 3.3 Performance Score Transform

The model is fitted on raw error counts (as the paper specifies). For display, errors are transformed into a Performance Score that increases with learning:

```
P(t) = Score_max - errors(t)
maxp_P  = Score_max - maxp_errors       ← trainee's predicted performance ceiling
Mastery% = (current_P / maxp_P) × 100
```

`Score_max` is set in `config.py` (default: `10`). Sessions where `error_count IS NULL` are excluded from the fit.

### 3.4 Minimum Data Requirement

A minimum of **5 completed sessions with non-null `error_count`** is required before fitting. Below this threshold the UI shows a placeholder: *"N more sessions needed to model your learning curve."*

---

## 4. Architecture

### 4.1 New Package: `app/analytics/`

```
app/analytics/
├── __init__.py
├── learning_curve.py           # Pure functions — no Qt, no DB
└── performance_repository.py  # DB queries only — no Qt, no fitting
```

This mirrors the existing `app/processing/` pattern: pure computation isolated from UI and hardware.

### 4.2 Data Flow

```
[Hardware box GPIO] ──► ErrorCounterWorker(QThread) ──signal──►
[Manual UI button]  ──► ErrorInputWidget signal      ──signal──► SessionManager._manual_error_count++
                                                                │
                                                       session.end_session()
                                                                │
                                                   sessions.error_count = _manual_error_count  (DB)
                                                                │
                                              PerformanceRepository.get_session_series()
                                                                │
                                                  learning_curve.fit_schmettow()   ← pure NumPy/SciPy
                                                                │
                                             LearningCurveChart.update(series, fit)
```

**Rule:** No computation in UI thread. `fit_schmettow()` is called before chart construction, not inside the widget.

### 4.3 File Inventory

| File | Action | Notes |
|------|--------|-------|
| `app/analytics/__init__.py` | NEW | Empty package marker |
| `app/analytics/learning_curve.py` | NEW | Schmettow fit, predict, score transform |
| `app/analytics/performance_repository.py` | NEW | `get_session_series()` DB query |
| `app/hardware/error_counter.py` | NEW | Hardware stub + `ErrorCounterWorker` |
| `app/ui/widgets/learning_curve_chart.py` | NEW | pyqtgraph widget |
| `app/ui/widgets/error_input.py` | NEW | `+`/`−` error counter widget |
| `app/ui/views/dashboard_view.py` | EXTEND | Add `LearningCurveChart` card |
| `app/ui/views/post_session_view.py` | EXTEND | Add "Honest Mentor" strip |
| `app/ui/views/live_view.py` | EXTEND | Add `ErrorInputWidget` to toolbar |
| `app/core/session.py` | EXTEND | Track `_manual_error_count`; write to DB on end |
| `app/utils/config.py` | EXTEND | `SCORE_MAX = 10`, `LC_MIN_SESSIONS = 5` |
| `tests/test_learning_curve.py` | NEW | Unit tests for fitting and score transform |
| `tests/test_performance_repository.py` | NEW | DB integration tests |

---

## 5. Component Specifications

### 5.1 `learning_curve.py`

```python
@dataclass
class SessionDataPoint:
    trial: int           # ordinal session number (1-based)
    error_count: int
    performance_score: float   # Score_max - error_count

@dataclass
class SchmettowFit:
    leff: float          # ∈ (0,1)
    pexp: float          # ≥ 0
    maxp: float          # ≥ 0 (in error domain)
    scale: float         # > 0
    maxp_performance: float    # Score_max - maxp  (display ceiling)
    r_squared: float           # hook for Phase 7 diagnostics
    predicted_errors: np.ndarray
    predicted_performance: np.ndarray

def fit_schmettow(
    trial_numbers: np.ndarray,
    error_counts: np.ndarray,
    score_max: float = SCORE_MAX,
) -> SchmettowFit | None: ...
# Returns None if < LC_MIN_SESSIONS points or scipy diverges

def predict_at_trial(fit: SchmettowFit, trial: int) -> float: ...
# Returns predicted performance score at a future trial

def mastery_percent(fit: SchmettowFit, current_performance: float) -> float: ...
# (current_P / maxp_P) * 100, clamped 0–100
```

### 5.2 `performance_repository.py`

```python
@dataclass
class SessionPerformance:
    session_number: int
    session_id: int
    started_at: datetime
    error_count: int        # 0 if NULL in DB
    duration_seconds: float
    avg_rmssd: float | None
    avg_cli: float | None

def get_session_series(db: DatabaseManager) -> list[SessionPerformance]: ...
# All completed sessions (ended_at IS NOT NULL) ordered by started_at
# Numbered 1..N; error_count NULL → 0, flagged separately
```

### 5.3 `LearningCurveChart` widget

- Inherits `QWidget`; wraps a `pyqtgraph.PlotWidget`
- Public method: `update_data(series: list[SessionDataPoint], fit: SchmettowFit | None) -> None`
- Scatter: `(trial, P)` — `COLOR_PRIMARY` dots, size 8px
- Solid line: fitted curve in `COLOR_PRIMARY`
- Dashed line: 3-trial projection in `COLOR_FONT_MUTED`
- Horizontal dashed ceiling: `maxp_P` in `COLOR_DANGER` with label
- Header bar above chart: `Mastery: XX%  ·  leff: X.XX  ·  pexp: X.X`
- Placeholder state: centered `QLabel` when fit is `None`
- `show_position_marker: bool = False` — when True, highlights the last data point in `COLOR_PRIMARY` with a vertical tick (used in PostSessionView)

### 5.4 `ErrorInputWidget`

- `QWidget` with `−` `QPushButton`, count `QLabel`, `+` `QPushButton`
- Buttons: 44×44 px (Rule of 8), pill style
- Signal: `error_count_changed(int)`
- `reset()` method: resets count to 0 (called by `SessionManager` on session start)
- Hardware hook: `increment_from_hardware()` slot — same path as manual press

### 5.5 "Honest Mentor" Strip (PostSessionView)

A compact card added between the metric summary and the export button:

```
YOUR POTENTIAL
[●──────────────────────────────────────] maxp_P = 9.1 pts
 ↑ Session 4 · P = 6.2 · Mastery: 68%

"You're still 32% from your potential. Keep grinding."
```

- Strip: styled `QProgressBar`, value = `mastery_percent`, range 0–100
- Mentor text generated by `_mentor_message(mastery_pct: float) -> str`:
  - ≥ 80%: *"You're approaching your performance ceiling. Excellent consistency."*
  - 40–79%: *"You're still X% from your potential. Keep grinding."*
  - < 40%: *"Early stage. Each session matters most now — your curve is steepest here."*
- If fit is `None` (< 5 sessions): *"Complete N more sessions to unlock your learning curve."*

---

## 6. Database

No new tables required. The existing `sessions.error_count INTEGER` column (added in Phase 6a migration) is the sole storage for this feature. `PerformanceRepository` reads it with a JOIN to `hrv_samples` and `cli_samples` for contextual metrics.

---

## 7. Configuration (`config.py` additions)

```python
# Learning Curves
SCORE_MAX: int = 10          # Maximum possible performance score per session
LC_MIN_SESSIONS: int = 5     # Minimum sessions with error data before curve is fitted
```

---

## 8. Testing

### `tests/test_learning_curve.py`
- Fit returns `None` for < 5 points
- Fit returns valid `SchmettowFit` for synthetic data matching the known formula
- `leff` is within (0, 1)
- `maxp` and `pexp` are ≥ 0
- `predict_at_trial` returns a value ≤ `maxp_P`
- `mastery_percent` clamps to [0, 100]
- Performance score transform is correctly inverted
- Divergent fit (all-zero errors) returns `None`

### `tests/test_performance_repository.py`
- Returns sessions ordered by `started_at`
- Excludes sessions with `ended_at IS NULL`
- `error_count NULL` → treated as 0, excluded from fit data
- Session numbering is 1-based and contiguous

---

## 9. Sprint GitHub Issues

See Section 10 for the full issue set, formatted as User Stories.

---

## 10. Project Roadmap Position

```
Phase 6a  ✅  PicoECG integration (DONE)
Phase 6b  🔲  Eye tracker + hardware error counting
Phase 6c  🔲  Learning Curves (THIS SPRINT)  ← current
Phase 7   🔲  Polish, packaging, PyInstaller
Phase 8   🔲  Multi-trainee support + full Bayesian diagnostics
```

---

## 11. Definition of Done (Sprint)

- [ ] `fit_schmettow()` passes all unit tests with synthetic Schmettow data
- [ ] Dashboard shows learning curve card (or placeholder) on first load
- [ ] Post-session view shows Honest Mentor strip with correct mastery %
- [ ] Live View toolbar shows error counter; count persists to DB on session end
- [ ] Hardware error counter stub is wired but inactive (ready for Phase 6b)
- [ ] All existing 99 tests still pass
- [ ] All new tests pass (target: ≥ 115 total)
- [ ] No computation inside any Qt widget method
- [ ] `Score_max` and `LC_MIN_SESSIONS` are constants in `config.py` only
- [ ] Scientific docstring on `fit_schmettow()` citing Schmettow et al. (2026)

---

## 12. GitHub Issues — Sprint Backlog

---

### Issue 1 — `[ANALYTICS]` Add Schmettow learning curve fitting module

**Type:** Feature | **Label:** analytics, core, scientific

**User Story:**
As a researcher reviewing training outcomes, I want the system to fit a parametric Schmettow learning curve to a trainee's error data so that I can report interpretable parameters (leff, pexp, maxp) rather than raw trends.

**Context:**
The Schmettow model (2026) decomposes performance into learning efficiency, previous experience, and maximum performance. These parameters answer three research questions that simple linear or power-law models cannot: trainee selection (maxp), training efficiency (leff), and transfer effects (pexp).

**Technical Requirements:**
1. Create `app/analytics/__init__.py` and `app/analytics/learning_curve.py`
2. Implement `fit_schmettow(trial_numbers, error_counts) -> SchmettowFit | None` using `scipy.optimize.curve_fit` with unbounded parameterisation (sigmoid for leff, exp for pexp/maxp/scale)
3. Implement `predict_at_trial(fit, trial) -> float`
4. Implement `mastery_percent(fit, current_performance) -> float` clamped to [0, 100]
5. Performance Score transform: `P = SCORE_MAX - errors` applied to all outputs
6. Return `None` if fewer than `LC_MIN_SESSIONS` points or if scipy fit diverges
7. Full Google-style docstring on `fit_schmettow` citing Schmettow et al. (2026)
8. Add `SCORE_MAX = 10` and `LC_MIN_SESSIONS = 5` to `app/utils/config.py`

**Definition of Done:**
- `tests/test_learning_curve.py` covers: insufficient data → None, valid synthetic fit, parameter bounds, `mastery_percent` clamping, divergent input → None
- No Qt imports anywhere in this file
- Docstring includes formula, parameter table, and reference

**Acceptance Criteria:**
- Given 5 sessions with error counts [8, 6, 5, 4, 3], `fit_schmettow` returns a `SchmettowFit` with `leff ∈ (0,1)` and `maxp ≥ 0`
- Given 4 sessions, returns `None`
- `predict_at_trial(fit, N+3)` returns a value ≤ `fit.maxp_performance`

---

### Issue 2 — `[STORAGE]` Add PerformanceRepository for cross-session analytics queries

**Type:** Feature | **Label:** storage, analytics

**User Story:**
As the analytics layer, I need a clean DB interface that returns per-session performance data (error count, duration, mean RMSSD, mean CLI) ordered by trial number so that the learning curve module can operate on plain dataclasses without touching SQL.

**Context:**
The existing `SessionRepository` handles session CRUD. Cross-session analytics queries (aggregates across all sessions) belong in a separate repository to preserve Single Responsibility.

**Technical Requirements:**
1. Create `app/analytics/performance_repository.py`
2. Implement `get_session_series(db: DatabaseManager) -> list[SessionPerformance]`
   - Only completed sessions (`ended_at IS NOT NULL`)
   - Ordered ascending by `started_at`
   - Numbered 1..N (trial number)
   - `error_count NULL` → stored as `0` in dataclass, flagged with `has_error_data: bool = False`
   - `avg_rmssd`: mean of all `hrv_samples.rmssd` for the session (None if no samples)
   - `avg_cli`: mean of all `cli_samples.cli` for the session (None if no samples)

**Definition of Done:**
- `tests/test_performance_repository.py` covers: ordering, NULL error_count handling, exclusion of incomplete sessions, 1-based numbering
- No fitting or computation logic in this file — queries only

**Acceptance Criteria:**
- Abandoned sessions (no `ended_at`) are excluded
- `has_error_data = False` for sessions with `NULL error_count`
- Sessions are numbered starting at 1 in chronological order

---

### Issue 3 — `[HARDWARE]` Add ErrorCounter driver stub with manual fallback signal

**Type:** Feature | **Label:** hardware, phase-6b-ready

**User Story:**
As a developer wiring Phase 6b hardware, I want an `ErrorCounter` driver that already follows the `BaseSensor` contract so that the hardware box GPIO can be connected later without changing any other file.

**Context:**
The training box has a wire-touch sensor that will be connected to a GPIO pin in Phase 6b. For this sprint, only the manual UI fallback is active. The stub ensures the signal contract is locked in now.

**Technical Requirements:**
1. Create `app/hardware/error_counter.py`
2. `ErrorCounter(BaseSensor)` with signal `error_detected = pyqtSignal()` emitted on each touch
3. `start()` / `stop()` raise `NotImplementedError` with a clear message: *"Hardware error counter not yet implemented. Use ErrorInputWidget for manual counting."*
4. `ErrorCounterWorker(QThread)` stub — body is a `pass` with a TODO comment referencing Phase 6b
5. `SessionManager` imports `ErrorCounter` and connects `error_detected` to `_on_hardware_error()` slot (which increments `_manual_error_count`)

**Definition of Done:**
- `ErrorCounter` instantiates without error
- Signal contract matches: `error_detected = pyqtSignal()`
- `SessionManager._on_hardware_error()` slot exists and increments the counter

**Acceptance Criteria:**
- `ErrorCounter().start()` raises `NotImplementedError`
- `ErrorCounter` can be instantiated and its signal connected without any hardware present

---

### Issue 4 — `[UI]` Add ErrorInputWidget to Live View toolbar

**Type:** Feature | **Label:** ui, live-view

**User Story:**
As a trainer supervising a live session, I want to tap a `+` button in the Live View toolbar each time the trainee touches the wire so that the error count is captured without interrupting the session flow.

**Context:**
Error count is the primary input to the Schmettow learning curve. Accurate per-session counts require real-time input. The widget must be unobtrusive but reachable within one tap during a live session.

**Technical Requirements:**
1. Create `app/ui/widgets/error_input.py` — `ErrorInputWidget(QWidget)`
2. `−` and `+` `QPushButton`s at 44×44 px (Rule of 8), pill style using theme constants
3. Count `QLabel` between the buttons, font `FONT_HEADING_2`, `COLOR_PRIMARY`
4. Signal: `error_count_changed = pyqtSignal(int)`
5. `reset()` method: resets count to 0
6. `increment_from_hardware()` slot: same as pressing `+` (Phase 6b hook)
7. Floor: count cannot go below 0
8. Integrate into `live_view.py` toolbar row (right side, next to END SESSION)
9. On `SessionManager.session_started`: call `error_input.reset()`
10. On `SessionManager.session_ended`: read `error_input.count` and write to `sessions.error_count`

**Definition of Done:**
- Widget renders without hardware
- `+` / `−` buttons update label correctly with floor at 0
- Count is written to `sessions.error_count` column after `end_session()`
- Existing tests still pass

**Acceptance Criteria:**
- Pressing `−` when count = 0 has no effect (count stays 0)
- `reset()` sets display to 0
- `error_count_changed` is emitted on every increment or decrement

---

### Issue 5 — `[UI]` Build LearningCurveChart pyqtgraph widget

**Type:** Feature | **Label:** ui, widgets, analytics

**User Story:**
As a trainee reviewing my progress, I want to see my learning curve plotted with a fitted growth line and a 3-session projection so that I understand my trajectory and how close I am to my performance ceiling.

**Context:**
The Schmettow model outputs parameters that are only meaningful to researchers. The chart translates these into an immediately legible visual: a rising curve, a dashed projection, and a labeled ceiling line.

**Technical Requirements:**
1. Create `app/ui/widgets/learning_curve_chart.py` — `LearningCurveChart(QWidget)`
2. Internal `pyqtgraph.PlotWidget` with background `COLOR_CARD`, axes styled to theme
3. Public method: `update_data(series: list[SessionDataPoint], fit: SchmettowFit | None) -> None`
4. Scatter: `(trial, performance_score)` — `COLOR_PRIMARY` dots, size 8 px
5. Solid line: fitted curve (P-space) — `COLOR_PRIMARY`
6. Dashed line: 3-trial projection — `COLOR_FONT_MUTED`, dash style
7. Horizontal dashed ceiling: `fit.maxp_performance` — `COLOR_DANGER`, with label *"Your ceiling"*
8. Header `QLabel` above plot: `"Mastery: XX%  ·  leff: X.XX  ·  pexp: X.X"`
9. Placeholder state (fit is None): centered label *"N more sessions needed to model your curve"*
10. `show_position_marker: bool = False` constructor param — when True, highlights last scatter point with a vertical tick line (for PostSessionView)
11. No computation inside the widget — all fitting done before calling `update_data`

**Definition of Done:**
- Widget renders in both data and placeholder states
- Ceiling line is visible and labeled
- Header readout updates correctly
- No `fit_schmettow` call inside the widget

**Acceptance Criteria:**
- With fit=None, placeholder text is shown
- With valid fit, all four visual elements render (scatter, solid line, dashed projection, ceiling)
- `show_position_marker=True` highlights the rightmost data point

---

### Issue 6 — `[UI]` Add learning curve card to Dashboard

**Type:** Feature | **Label:** ui, dashboard

**User Story:**
As a medical educator reviewing training cohort progress, I want to see the full learning curve card on the main dashboard so that I have a longitudinal view of the trainee's skill acquisition at a glance.

**Context:**
The dashboard is the first screen after login. Adding the learning curve here makes it a primary metric alongside session history, reinforcing that longitudinal progress — not just individual session scores — is the goal of the training programme.

**Technical Requirements:**
1. In `dashboard_view.py`, instantiate `PerformanceRepository` and `LearningCurveChart`
2. In `refresh()`: call `get_session_series()`, filter to sessions with `has_error_data=True`, call `fit_schmettow()`, pass result to `chart.update_data()`
3. Place `LearningCurveChart` in a `COLOR_CARD` `QFrame` card below the session table
4. Card uses `CARD_PADDING` and `RADIUS_LG` (from `theme.py`) — no hardcoded values
5. `refresh()` must be called on: app start, session end, return from post-session view

**Definition of Done:**
- Dashboard shows chart on first load (or placeholder if < 5 sessions)
- Chart updates automatically after each new session
- Card styling matches existing dashboard cards exactly

**Acceptance Criteria:**
- With 0–4 sessions: placeholder shown with correct "N more sessions needed" count
- With ≥ 5 sessions having error data: fitted curve is displayed
- Dashboard loads in < 500 ms with 50 sessions in DB

---

### Issue 7 — `[UI]` Add "Honest Mentor" strip to Post-Session view

**Type:** Feature | **Label:** ui, post-session, ux

**User Story:**
As a trainee just finishing a session, I want to immediately see where I stand on my learning curve and hear a direct, honest assessment of my progress so that I stay motivated and calibrated about how much further I have to go.

**Context:**
The post-session moment is the highest-impact feedback window. A vague "good session" is useless. The Schmettow model provides the data to be specific: *"You are 32% from your ceiling. Your learning rate is above average."*

**Technical Requirements:**
1. In `post_session_view.py`, after loading session data, compute `mastery_percent` and generate mentor text
2. Strip UI: `QProgressBar` (pill, `COLOR_PRIMARY` fill, `COLOR_BORDER` track, height 12px) with value = `mastery_percent`
3. Labels: session number, current P score, mastery %
4. Right anchor label: `"Ceiling: X.X pts"`
5. Mentor text `QLabel` below strip, `FONT_BODY`, `COLOR_FONT`
6. Mentor text logic in `_mentor_message(mastery_pct: float) -> str` (pure function, no Qt):
   - ≥ 80%: *"You're approaching your performance ceiling. Excellent consistency."*
   - 40–79%: *"You're still {100-mastery_pct:.0f}% from your potential. Keep grinding."*
   - < 40%: *"Early stage. Each session matters most now — your curve is steepest here."*
7. If fit is None: *"Complete {LC_MIN_SESSIONS - N} more sessions to unlock your learning curve."*
8. Reuses `LearningCurveChart` with `show_position_marker=True` for the mini chart

**Definition of Done:**
- Strip renders with correct value after every session end
- Mentor text is dynamically correct for all three ranges
- Placeholder shown correctly when < 5 sessions
- `_mentor_message` is a pure function with unit tests

**Acceptance Criteria:**
- `mastery_percent = 85` → ceiling message shown
- `mastery_percent = 55` → "45% from your potential" message shown
- `mastery_percent = 20` → early-stage message shown
- Fit None → placeholder with correct session count

---

### Issue 8 — `[TESTS]` Full test coverage for learning curves sprint

**Type:** Testing | **Label:** tests, quality

**User Story:**
As a researcher publishing results from BioTrace, I need the analytics pipeline to have comprehensive unit tests so that I can trust the model implementation matches the Schmettow paper.

**Context:**
The learning curve fitting is scientific code. Errors in `fit_schmettow` would silently produce wrong leff/maxp values, leading to incorrect conclusions about trainee progress. Full test coverage is non-negotiable.

**Technical Requirements:**
1. `tests/test_learning_curve.py`:
   - Synthetic data: generate ground-truth Schmettow curve, add noise, verify fit recovers parameters within 20% tolerance
   - `fit_schmettow` returns `None` for < 5 points
   - `fit_schmettow` returns `None` for all-zero errors (degenerate input)
   - `leff ∈ (0, 1)` always
   - `maxp ≥ 0`, `pexp ≥ 0` always
   - `mastery_percent` clamps to [0, 100] for out-of-range inputs
   - `predict_at_trial` returns a value ≤ `fit.maxp_performance`
   - Performance score transform is exactly `SCORE_MAX - errors`
   - `_mentor_message` pure function: all three branches tested
2. `tests/test_performance_repository.py`:
   - Abandoned sessions excluded
   - Trial numbering is 1-based and contiguous
   - NULL error_count → `has_error_data = False`
   - Results ordered by `started_at` ascending
3. All existing 99 tests must still pass

**Definition of Done:**
- `pytest tests/` passes with ≥ 115 tests total
- No test imports from `app/ui/` (analytics tests are framework-agnostic)

**Acceptance Criteria:**
- Zero test failures after sprint completion
- Test file for `learning_curve.py` has ≥ 10 test functions
