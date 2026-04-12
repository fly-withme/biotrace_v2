# Learning Curves in BioTrace — Import Page

This document explains how the learning curve feature on the **Import** page works:
what data it expects, how the math works under the hood, and what each visual element
in the chart means.

---

## 1. What the Import page does

The Import page (`app/ui/views/excel_import_view.py`) lets a researcher load a
**LapSim Excel export** (`.xlsx`) and instantly see a participant's learning curve
for a chosen exercise.

The complete flow from file to chart:

```
.xlsx file
    │
    ▼
LapSimParser          ← reads & validates the Excel sheet
    │
    ▼
compute_performance_series  ← combines speed + accuracy into one error score
    │
    ▼
fit_schmettow (background thread)  ← fits the 3-parameter Schmettow model
    │
    ▼
LearningCurveChart    ← draws dots, fitted curve, projection, and ceiling
```

---

## 2. The Excel file format (LapSim export)

BioTrace expects a standard `.xlsx` export from a Surgical Science LapSim simulator.

| Column | Used for |
|---|---|
| `Login` | Identifies the participant |
| `Firstname` / `Lastname` | Display name (optional) |
| `Task Name` | Identifies the exercise (one sheet = one exercise) |
| `Start Time` | Sorts attempts chronologically |
| `Total Time (s)` | Speed metric — lower is better |
| `Tissue Damage (#)` | Accuracy metric — lower is better |
| `Score` | Optional; not used in the composite metric |
| `Status` | Pass / Failed — all attempts included in analysis |

LapSim sometimes places metadata in the first few rows. The parser scans the first
20 rows automatically to find the real header row (the one that contains `Login`).

**Minimum requirement:** A participant needs at least **5 sessions** for the model
to be fitted. Sessions below this threshold are shown in the participant dropdown
only if they meet that threshold.

---

## 3. The composite performance score

Raw LapSim data has two separate metrics — time and tissue damage. To feed a single
number into the learning curve model, BioTrace combines them into one **error score**
(`app/analytics/lapsim_metrics.py`, `compute_performance_series`):

```
norm_speed = (time  − min_time)  / (max_time  − min_time)    → [0, 1]
norm_acc   = (dmg   − min_dmg)   / (max_dmg   − min_dmg)     → [0, 1]

error_score = (0.5 × norm_speed + 0.5 × norm_acc) × 100
```

Key properties:
- **Range:** 0 – 100. Higher = worse performance (it is an *error*, not a score).
- **Session 0 vs session N:** the very best and worst attempts in the dataset define
  the 0–1 scale, so the metric is always relative to this participant's own range.
- **Equal weighting:** speed and accuracy each contribute 50 %.
- **Degenerate case:** if all values in one dimension are the same (e.g., tissue
  damage is always 0), that component collapses to 0 and only the other drives the fit.

---

## 4. The Schmettow model

The actual curve fitting happens in `app/analytics/learning_curve.py`.

BioTrace uses a **3-parameter Schmettow model**:

```
errors(t) = scale × (1 − leff)^t + maxp
```

| Parameter | Meaning | Range |
|---|---|---|
| `leff` | **Learning efficiency** — how fast the trainee improves per session | 0 – 1 (higher = faster) |
| `maxp` | **Error floor** — the irreducible minimum error the trainee asymptotes toward | ≥ 0 |
| `scale` | **Trainable component** — the initial size of the improvable gap | > 0 |

Fitting is done with `scipy.optimize.curve_fit` (non-linear least squares).
Parameters are internally transformed through sigmoid / exp to keep them in their
valid ranges during optimisation, then converted back before storing the result.

The fit also computes an **R² value** (coefficient of determination) to indicate
goodness of fit:

```
R² = 1 − (sum of squared residuals) / (total sum of squares)
```

R² close to 1.0 means the model matches the data well. R² near 0 means the data
does not follow a Schmettow-shaped trajectory.

### Minimum data requirement

`LC_MIN_SESSIONS = 5` (defined in `app/utils/config.py`). Fewer than 5 valid sessions
returns `None` from `fit_schmettow` and the chart shows a placeholder message.

---

## 5. Derived metrics shown in the UI

### Performance score
For display purposes the *error score* is inverted back to a *performance score*:

```
performance_score = SCORE_MAX − error_score      (SCORE_MAX = 100)
```

Higher is better. The y-axis of the chart is labelled "Performance (Time + Tissue Damage)".

### Mastery percentage

```
mastery_pct = (current_performance / maxp_performance) × 100
```

Where `maxp_performance = SCORE_MAX − maxp` is the model's predicted performance ceiling.
Clamped to [0, 100].

### Mentor message (shown on the dashboard card)

| Mastery % | Message |
|---|---|
| ≥ 80 % | "You're approaching your performance ceiling. Excellent consistency." |
| 40 – 79 % | "You're still X% from your potential. Keep grinding." |
| < 40 % | "Early stage. Each session matters most now — your curve is steepest here." |

---

## 6. The chart

The chart widget is `app/ui/widgets/learning_curve_chart.py` (uses `pyqtgraph`).

| Element | Visual | Meaning |
|---|---|---|
| **Blue dots** | `●` scatter | Actual performance score for each session |
| **Solid blue line** | `——` | Fitted Schmettow curve through the data |
| **Dashed grey line** | `- - -` | 3-session forward projection (where you are heading) |
| **Dashed red line** | `- - -` | Performance ceiling predicted by the model (`maxp_performance`) |
| Red label | "Your potential" | Marks the asymptote the trainee is converging toward |

The x-axis is the **session number** (chronological, 1-based). The y-axis is the
**performance score** (0 – 100, higher = better).

If there are fewer than 5 sessions, or if the model fails to converge, the chart
area is replaced by a plain-text placeholder explaining what is missing.

---

## 7. Threading

Curve fitting runs on a `QThread` (`app/ui/workers/analytics_worker.py`,
`LearningCurveWorker`) so the UI never freezes during the optimisation. The result
is sent back to the main thread via a Qt signal (`finished`) and then handed to
`LearningCurveChart.update_data()`.

---

## 8. File map (quick reference)

| File | Responsibility |
|---|---|
| `app/ui/views/excel_import_view.py` | Import page — UI, file selection, wiring |
| `app/analytics/lapsim_parser.py` | Read & validate LapSim `.xlsx` files |
| `app/analytics/lapsim_metrics.py` | Composite error score (time + tissue damage) |
| `app/analytics/learning_curve.py` | Schmettow model, mastery %, mentor message |
| `app/ui/widgets/learning_curve_chart.py` | pyqtgraph chart widget |
| `app/ui/workers/analytics_worker.py` | Background thread for curve fitting |
| `app/utils/config.py` | Constants: `SCORE_MAX = 100`, `LC_MIN_SESSIONS = 5` |
| `tests/test_learning_curve.py` | Unit tests for the model functions |
