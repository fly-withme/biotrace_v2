# BioTrace — Learning Curve Import & Analysis Feature

## Goal

Allow users (professors, researchers) to upload historical LapSim Excel exports,
validate that the data belongs to a single participant doing a single exercise,
extract a chronological performance series, fit the Schmettow parametric learning
curve model, and display the result in a dedicated page accessible from the sidebar.

No new hardware or live-session changes are needed. This feature is purely
analytical — it reads Excel files and produces learning curve visualisations.

---

## Data Analysis: What the Excel Files Contain

The example files are exports from the **LapSim** surgical simulator
(Surgical Science AB, Göteborg). Key observations:

### Structure

| Property | Detail |
|----------|--------|
| Format | `.xlsx` (Excel Open XML) |
| Sheets | One sheet per exercise type (e.g., *Grasping*, *Cutting*, *Cholecystectomy Dissection*, *Lifting & Grasping*) |
| Participant ID | `Login` column (e.g., `"Alexander93"`, `"peng01"`) |
| Repetition ordering | `Start Time` column (ISO 8601, e.g., `"2017-02-09 11:53:31Z"`) |
| Exercise identity | Sheet name **+** `Task Name` + `Course Name` columns |

### Performance Columns Available

| Column | Type | Interpretation |
|--------|------|----------------|
| `Total Time (s)` | float | Time on task — **primary Schmettow metric** (decreases with learning) |
| `Score` | float | Simulator composite score (increases with learning) |
| `Status` | str | `"Pass"` / `"Failed"` |
| `Left Instrument Misses (%)` | float | Accuracy proxy — lower is better |
| `Right Instrument Misses (%)` | float | Accuracy proxy — lower is better |
| `Tissue Damage (#)` | int | Error / complication count |
| `Left Instrument Path Length (m)` | float | Instrument efficiency — shorter is better |

### Participant & Exercise Validation

- **File 1** (`Alexander Arendt`): 3 sheets, ~100–120 rows per sheet, multiple
  participants mixed together (`Login` values: `Alexander93`, `cogpp1`, …).
  Rows are not pre-filtered to one person.
- **File 2** (`YUMI_LAPSIM`): 1 sheet, 57 rows, single participant `peng01`,
  one exercise, all on the same day — a clean single-person training log.

The parser must handle both cases: multi-person multi-sheet files and
clean single-person exports.

### File 1 Header Quirk

The first file has spurious header rows before the actual column names appear
(metadata mixed into the first 5–6 rows). The parser must detect the real
header row (the one that contains `"Login"`) rather than reading row 0 directly.

---

## Schmettow Model — What We Already Have

`app/analytics/learning_curve.py` already implements:

```
errors(t) = scale × (1 − leff)^(t + pexp) + maxp
```

- `leff` — learning efficiency ∈ (0, 1). Higher = faster learning.
- `pexp` — prior experience in trial-equivalents.
- `maxp` — asymptotic error floor (irreducible residual).
- `scale` — trainable component magnitude.

The model is already fit-tested with unit tests. For the import feature we
**reuse this engine without modification**.

**Mapping LapSim metrics to the model:**

| LapSim metric | Direction | Pre-processing for model |
|---------------|-----------|--------------------------|
| `Total Time (s)` | Decreases ↓ | Use directly as `errors` input |
| `Score` | Increases ↑ | Invert: `pseudo_errors = score_max − score` |
| `Tissue Damage (#)` | Decreases ↓ | Use directly as `errors` input |

`Total Time (s)` is the preferred default — it is the metric used in Schmettow
et al. (2026) and shows the clearest learning signal in the example data.

---

## Architecture

```
ExcelImportPage (new QWidget, new sidebar entry)
  │
  ├─► LapSimParser (new, app/analytics/lapsim_parser.py)
  │     reads .xlsx, detects header row, extracts sheets
  │     validates: one participant, one exercise
  │     returns: ParsedDataset(participant, exercise, trials: list[TrialRecord])
  │
  ├─► MetricSelector widget
  │     user picks: Total Time | Score | Tissue Damage
  │     maps choice → error-direction array
  │
  ├─► existing fit_schmettow() in app/analytics/learning_curve.py
  │     no changes needed
  │
  ├─► existing LearningCurveChart widget (app/ui/widgets/learning_curve_chart.py)
  │     extended: accept time-domain data in addition to error counts
  │
  └─► ImportRepository (new, app/storage/import_repository.py)
        stores parsed datasets in SQLite for re-display without re-upload
```

### New database tables

```sql
CREATE TABLE IF NOT EXISTS imported_datasets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    filename        TEXT NOT NULL,
    participant     TEXT NOT NULL,   -- Login value from LapSim
    exercise        TEXT NOT NULL,   -- Task Name from LapSim
    trial_count     INTEGER NOT NULL,
    metric_used     TEXT NOT NULL    -- "Total Time (s)" | "Score" | "Tissue Damage (#)"
);

CREATE TABLE IF NOT EXISTS imported_trials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id      INTEGER NOT NULL REFERENCES imported_datasets(id) ON DELETE CASCADE,
    trial_number    INTEGER NOT NULL,   -- 1-based chronological sequence
    start_time      TEXT,               -- ISO 8601 from LapSim
    raw_value       REAL NOT NULL,      -- value of the chosen metric
    score           REAL,               -- original Score column (always stored)
    total_time_s    REAL,               -- always stored regardless of chosen metric
    tissue_damage   INTEGER             -- always stored
);
```

Storing all three core columns regardless of the chosen metric lets users
switch the displayed metric without re-importing the file.

---

## Implementation Issues

Work these in order. Issues 1–2 are prerequisites for everything else.

---

### Issue LC-1 — `LapSimParser`: read and validate Excel exports
**New file:** `app/analytics/lapsim_parser.py`

**Responsibilities:**
1. Accept a file path (`.xlsx`).
2. Use `openpyxl` (already in requirements) to list sheets.
3. For each sheet, detect the real header row by scanning for the cell
   containing `"Login"` (handles the spurious-rows quirk in File 1).
4. Load the sheet as a `pandas.DataFrame` starting from that header row.
5. Expose:
   - `list_sheets(path) → list[str]` — returns all sheet names
   - `parse(path, sheet_name) → ParsedDataset` — returns validated dataset

**`ParsedDataset` dataclass:**
```python
@dataclass
class TrialRecord:
    trial_number: int       # 1-based, assigned by chronological sort
    start_time: str         # raw ISO string from LapSim
    total_time_s: float | None
    score: float | None
    tissue_damage: int | None
    status: str | None      # "Pass" / "Failed"

@dataclass
class ParsedDataset:
    participant: str        # Login value
    exercise: str           # Task Name
    course: str             # Course Name
    source_file: str        # original filename
    trials: list[TrialRecord]
    warnings: list[str]     # non-fatal issues found during parsing
```

**Validation rules (raise `ValueError` with a clear message if violated):**
- The sheet must contain columns `Login`, `Start Time`, `Task Name`.
- After loading, check unique values of `Login`:
  - If more than one unique `Login` found, raise `ValueError` with:
    `"Multiple participants found: {names}. Filter to one participant before importing."`
- Check unique values of `Task Name`:
  - If more than one unique task found, raise `ValueError` with:
    `"Multiple exercises found: {names}. Select a single exercise sheet."`

**Warnings (non-fatal, added to `ParsedDataset.warnings`):**
- `Total Time (s)` column missing → warn, time-based metric unavailable.
- Fewer than `LC_MIN_SESSIONS` (5) trials → warn, model fit may be unstable.
- Any `Status == "Failed"` rows present → inform user (do not discard them;
  failed attempts are valid learning data points).

**Trial ordering:**
- Sort rows by `Start Time` ascending.
- Assign `trial_number` as 1, 2, 3, … after sorting.

**Tests:** `tests/test_lapsim_parser.py`
- Parse File 2 (YUMI) → 57 trials, participant `"peng01"`, no errors.
- Parse File 1, sheet "Grasping", with multiple Login values → `ValueError`.
- Parse File 1, sheet "Grasping", filtered to one Login → success.
- Missing `Total Time (s)` column → warning in `parsed.warnings`, no crash.
- Rows are sorted by `Start Time`, not by row order.

---

### Issue LC-2 — `ImportRepository`: persist parsed datasets
**New file:** `app/storage/import_repository.py`

```python
class ImportRepository:
    def save_dataset(self, dataset: ParsedDataset, metric_used: str) -> int:
        """Persist a parsed dataset and return its new ID."""

    def get_all_datasets(self) -> list[dict]:
        """Return summary rows (id, participant, exercise, trial_count, imported_at)."""

    def get_trials(self, dataset_id: int) -> list[dict]:
        """Return trial rows for a dataset, ordered by trial_number."""

    def delete_dataset(self, dataset_id: int) -> None:
        """Delete a dataset and all its trials (CASCADE handled by FK)."""
```

Add the two new tables to `DatabaseManager._create_schema()` using
`CREATE TABLE IF NOT EXISTS` (safe to run on existing databases).

---

### Issue LC-3 — Metric normalisation for Schmettow input
**New file:** `app/analytics/lapsim_metrics.py`

The existing `fit_schmettow()` expects an **error-direction array** (high at
trial 1, decreasing over time). Different LapSim metrics need different
pre-processing:

```python
def extract_metric_series(
    trials: list[TrialRecord],
    metric: str,               # "Total Time (s)" | "Score" | "Tissue Damage (#)"
    score_max: float = 100.0,  # only used when metric == "Score"
) -> tuple[np.ndarray, np.ndarray]:
    """Return (trial_numbers, error_direction_values) ready for fit_schmettow().

    For "Total Time (s)":   values returned as-is (already decreasing).
    For "Score":            pseudo_errors = score_max − score (inverted).
    For "Tissue Damage (#)": values returned as-is (already decreasing).

    Trials with None for the chosen metric are dropped with a warning.
    Returns (trial_numbers, values) as parallel arrays.
    """
```

`score_max` for Score inversion: use the maximum observed score in the dataset
(not a hardcoded constant), so the model adapts to any simulator's scale.

---

### Issue LC-4 — `ExcelImportPage`: the new UI page
**New file:** `app/ui/views/excel_import_view.py`

This page is added to the sidebar between Dashboard and Calibration.

**Layout (top to bottom):**

```
┌─────────────────────────────────────────────────────────────┐
│  LEARNING CURVE IMPORT                     [← Back]         │
│  Import historical LapSim data to visualise learning curves  │
├──────────────────────────┬──────────────────────────────────┤
│  1. Upload File          │  3. Results                      │
│  ┌────────────────────┐  │  ┌────────────────────────────┐  │
│  │  Drag & drop .xlsx │  │  │  LearningCurveChart        │  │
│  │  or click to browse│  │  │  (existing widget)         │  │
│  └────────────────────┘  │  │                            │  │
│                          │  │  R² = 0.87                 │  │
│  2. Configure            │  │  leff = 0.42               │  │
│  Sheet:  [Grasping ▾]    │  │  Ceiling: 42 s             │  │
│  Metric: [Total Time ▾]  │  └────────────────────────────┘  │
│  Participant: Alexander93│  ┌────────────────────────────┐  │
│  Exercise: Grasping      │  │  Fit Parameters Table      │  │
│  Trials: 47              │  │  (leff, pexp, maxp, R²)    │  │
│  ⚠ 2 warnings            │  └────────────────────────────┘  │
│  [  Import & Fit  ]      │  [  Save to History  ]           │
└──────────────────────────┴──────────────────────────────────┘
```

**Interaction flow:**

1. User clicks the upload area → native file dialog (`.xlsx` filter).
2. App calls `lapsim_parser.list_sheets(path)` → populates the Sheet dropdown.
3. User selects a sheet → app calls `lapsim_parser.parse(path, sheet)`:
   - If `ValueError` → show error panel (red background, clear message).
   - If success → show participant name, exercise, trial count, any warnings.
4. User selects Metric from dropdown (`Total Time (s)` pre-selected).
5. User clicks **Import & Fit**:
   - `extract_metric_series()` builds the arrays.
   - `fit_schmettow()` runs (in a `QThread` via `LearningCurveWorker`).
   - `LearningCurveChart` updates with result.
   - Fit parameters table updates.
6. User clicks **Save to History** → `ImportRepository.save_dataset()` persists.

**Error states:**
- No file selected → "Upload & Fit" button disabled.
- Parse error → red card with error message, no fit attempted.
- Fewer than 5 trials → yellow warning, fit attempted anyway (may return `None`).
- Fit returns `None` → "Could not fit model — too few trials or flat data."

**Signals:**
```python
class ExcelImportView(QWidget):
    close_requested = pyqtSignal()   # → navigate to Dashboard
```

---

### Issue LC-5 — Extend `LearningCurveChart` for time-domain data
**File:** `app/ui/widgets/learning_curve_chart.py`

The existing chart was built for `performance_score` (0–`SCORE_MAX`, higher is
better). For Time on Task (seconds, lower is better) the y-axis direction and
labels must adapt.

Add a `metric_label: str` parameter to `update_data()`:

```python
def update_data(
    self,
    data_points: list[SessionDataPoint],
    fit: SchmettowFit | None,
    metric_label: str = "Performance Score",
    y_axis_inverted: bool = False,   # True for time-based metrics
) -> None:
```

When `y_axis_inverted=True`:
- Y-axis label shows the metric name (e.g., `"Total Time (s)"`)
- Lower values are "better" — the curve trends downward left-to-right.
- The "ceiling" annotation becomes "floor" (asymptotic minimum time).

For `SessionDataPoint` compatibility: the `performance_score` field will carry
the raw metric value (e.g., 67.3 seconds). `error_count` carries the
error-direction value used for fitting. Both are populated by
`extract_metric_series()`.

---

### Issue LC-6 — Add "Learning Curves" entry to sidebar
**File:** `app/ui/main_window.py`

1. Instantiate `ExcelImportView(db=self._db)` and add to the `QStackedWidget`.
2. Add a sidebar entry with icon `ph.chart-line-up` (Phosphor) and label
   `"Learning Curves"` above the Calibration entry.
3. Wire `excel_import_view.close_requested` → `navigate_to(0)`.
4. Update all `navigate_to()` index constants (a named enum or dict is cleaner
   than raw integers — if constants are already named, update them).

---

### Issue LC-7 — History sub-view in `ExcelImportPage`
**File:** `app/ui/views/excel_import_view.py`

Add a second tab or collapsible section **"Saved Datasets"**:
- Table showing `participant`, `exercise`, `trial_count`, `imported_at`.
- Clicking a row reloads that dataset into the chart (re-reads from DB,
  re-runs `fit_schmettow()`).
- A **Delete** button per row calls `ImportRepository.delete_dataset()`.

This allows the professor to return to previously imported datasets without
re-uploading the file.

---

### Issue LC-8 — Tests
**New files:** `tests/test_lapsim_parser.py`, `tests/test_import_repository.py`,
`tests/test_lapsim_metrics.py`

| Test | Description |
|------|-------------|
| `test_parse_yumi_clean` | YUMI file → 57 trials, participant `"peng01"`, no errors |
| `test_parse_sorts_by_time` | Rows out of order by Start Time → sorted correctly |
| `test_parse_multi_participant_raises` | Multiple Login values → `ValueError` |
| `test_parse_missing_total_time` | Sheet without `Total Time (s)` → warning, no crash |
| `test_parse_header_detection` | Alexander file (messy headers) → header row auto-detected |
| `test_metric_total_time_passthrough` | `extract_metric_series` returns raw values for time |
| `test_metric_score_inversion` | Score 80 with max 100 → pseudo_error 20 |
| `test_import_repository_roundtrip` | Save + retrieve → same participant, trial count, values |
| `test_import_repository_delete` | Delete removes dataset and all trials |

---

## File Change Summary

| File | Status | Change |
|------|--------|--------|
| `app/analytics/lapsim_parser.py` | **New** | Excel parser + validation |
| `app/analytics/lapsim_metrics.py` | **New** | Metric normalisation for Schmettow |
| `app/storage/import_repository.py` | **New** | Persist imported datasets |
| `app/storage/database.py` | **Update** | Add `imported_datasets` + `imported_trials` tables |
| `app/ui/views/excel_import_view.py` | **New** | Full import + chart page |
| `app/ui/widgets/learning_curve_chart.py` | **Update** | Add `metric_label` + `y_axis_inverted` |
| `app/ui/main_window.py` | **Update** | Add sidebar entry + navigation |
| `tests/test_lapsim_parser.py` | **New** | Parser tests |
| `tests/test_import_repository.py` | **New** | Repository tests |
| `tests/test_lapsim_metrics.py` | **New** | Metric extraction tests |

No changes to the live-session pipeline, `SessionManager`, or any existing views.

---

## Acceptance Criteria

- [ ] Uploading the Alexander Arendt file → sheet picker shows 3 sheets.
- [ ] Selecting "Grasping" with multiple Login values → clear error message.
- [ ] Uploading the YUMI file → auto-detects `"peng01"`, 57 trials, no error.
- [ ] Selecting `Total Time (s)` → Schmettow curve fit displayed with R² shown.
- [ ] Selecting `Score` → fit still works (inverted direction, curve goes up).
- [ ] **Save to History** → dataset appears in Saved Datasets table.
- [ ] Clicking saved dataset row → chart reloads without file re-upload.
- [ ] App runs without error when no file is loaded (empty state page).
- [ ] All new tests pass; all existing 136 tests still pass.
