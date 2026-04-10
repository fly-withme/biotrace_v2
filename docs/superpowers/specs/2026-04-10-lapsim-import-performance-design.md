# LapSim Import — Performance Curve Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the Import page so users can select an exercise sheet and a participant, see the actual composite performance curve, and see the Schmettow-fitted estimated performance curve.

**Architecture:** Extend three existing files — `TrialRecord`, `lapsim_metrics.py`, and `ExcelImportView`. The Schmettow model, `LearningCurveChart`, and `LearningCurveWorker` are reused unchanged.

**Tech Stack:** PyQt6, pandas, openpyxl, scipy (Schmettow fit already in place)

---

## Data Model (`lapsim_parser.py`)

`TrialRecord` gains two new optional fields:
- `left_instrument_time_s: Optional[float]`
- `right_instrument_time_s: Optional[float]`

`parse()` extracts these columns when present.

`total_time_s` fallback: if "Total Time (s)" is absent (e.g. Grasping sheet), compute `max(left_instrument_time_s, right_instrument_time_s)`. This fixes the Grasping sheet where `total_time_s` was always `None`.

---

## Performance Metric (`lapsim_metrics.py`)

New function: `compute_performance_series(trials: List[TrialRecord]) -> tuple[np.ndarray, np.ndarray, float]`

Returns `(trial_numbers, error_values, score_max=100.0)`.

**Composite error formula:**
1. Speed raw = `total_time_s` per trial (already uses the fallback above)
2. Accuracy raw = `tissue_damage` per trial (default 0 if missing)
3. Only trials with valid speed AND valid accuracy are included
4. Normalize speed: `norm_speed = (speed - min_speed) / (max_speed - min_speed)` — result in [0, 1], higher = slower = worse
5. Normalize accuracy: `norm_acc = (damage - min_damage) / (max_damage - min_damage)` — result in [0, 1], higher = more damage = worse. If all damage values are equal (e.g. all zero), `norm_acc = 0`.
6. Composite error = `(0.5 × norm_speed + 0.5 × norm_acc) × 100` — range [0, 100], decreasing over trials = learning
7. `score_max = 100.0`

This error series is fed directly to `fit_schmettow()` unchanged.

---

## UI (`excel_import_view.py`)

### Controls row (top)

Replace the single drop-zone row with a three-element row:

```
[ Drop Zone / file path ]  [ Exercise ▼ ]  [ Participant ▼ ]
```

- **Exercise dropdown**: hidden until file loaded; populated from sheet names
- **Participant dropdown**: hidden until exercise selected; populated from logins in the selected sheet
- Selecting exercise → clear and repopulate Participant dropdown → auto-select first participant → trigger fit
- Selecting participant → trigger fit

### Fit trigger

`_on_fit_requested()`:
1. Call `compute_performance_series(dataset.trials)`
2. If fewer than 5 trials → show warning banner, no fit
3. Build `SessionDataPoint` list from `(trial_nums, error_values)`
4. Dispatch `LearningCurveWorker(trial_nums, error_values, score_max=100.0)`

### Chart

`_on_fit_finished()`: call `chart.update_data(data_points, fit, metric_label="Performance (Time + Tissue Damage)", y_axis_inverted=True)`

Stats footer: `Participant: X  •  Exercise: Y  •  Learning Efficiency: Z  •  R²: W`

If fit is `None` (diverged or < 5 sessions): show muted message "Not enough data to fit learning curve (min. 5 sessions)."

---

## Error / Edge Cases

| Situation | Behaviour |
|-----------|-----------|
| Sheet has no "Total Time (s)" AND no instrument time columns | Show error: "No time data found in this sheet." |
| All tissue damage values = 0 | `norm_acc = 0` for all trials; speed drives composite alone |
| All speed values identical | `norm_speed = 0`; accuracy drives composite alone |
| Both normalizations collapse | Composite = 0 for all trials → fit returns `None` → show "Not enough variation to fit model." |
| Fewer than 5 valid trials | Show warning banner, no fit attempted |
| Participant has data in sheet but all rows filtered out | Show error: "No valid data for this participant in this exercise." |

---

## Files Changed

| File | Change |
|------|--------|
| `app/analytics/lapsim_parser.py` | Add fields to `TrialRecord`; extract in `parse()`; add `total_time_s` fallback |
| `app/analytics/lapsim_metrics.py` | Add `compute_performance_series()` |
| `app/ui/views/excel_import_view.py` | Add Exercise dropdown; wire selection chain; use `compute_performance_series` |

**No other files change.** `learning_curve.py`, `LearningCurveChart`, `LearningCurveWorker`, database, and storage are untouched.
