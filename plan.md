# BioTrace — Sprint Plan: Post-Session Dashboard Completion

## Sprint Goal

Complete the individual session dashboard (`PostSessionView`) so it is useful for
real post-hoc analysis. The sprint covers four concrete deliverables:

1. **Remove** the Schmettow learning-curve component from the view.
2. **Modernise** the Export Data button icon.
3. **Video playback** — show the recorded endoscopy footage for the session,
   with play / pause, a seek bar, and a current-time label.
4. **Session analysis chart** — a real pyqtgraph chart showing **Stress (RMSSD)**
   and **Cognitive Workload (CLI)** over session time, with a click-to-seek
   interaction that jumps the video player to the clicked timestamp.

---

## Architecture Overview

```
SessionManager.start_session()
    └─► VideoFeed.start_recording("recordings/session_{id}.mp4")
        ─► file path saved to sessions.video_path in DB on session end

PostSessionView.load_session(session_id)
    ├─► query hrv_samples + cli_samples from DB
    ├─► TimelineChart (pyqtgraph)   ← emits timestamp_clicked(float ms)
    └─► VideoPlayer widget          ← connected to timestamp_clicked → seek_to(ms)
```

**Key design rule:** `VideoPlayer` is a new, separate widget from `VideoFeed`.
`VideoFeed` handles live capture; `VideoPlayer` handles file playback.
They share no code.

---

## Database Change

Add `video_path TEXT` column to `sessions`:

```sql
ALTER TABLE sessions ADD COLUMN video_path TEXT;
-- NULL = no recording for this session (e.g., camera not connected)
```

The migration runs automatically inside `DatabaseManager._create_schema()`.
If the column already exists, `ALTER TABLE` raises `OperationalError` — catch and
ignore it so the app works on existing databases without manual migration.

---

## Issues / Implementation Steps

### Issue 1 — DB schema: add `video_path` column  
**File:** `app/storage/database.py`

- In `_create_schema()`, after the `CREATE TABLE sessions` block, add:
  ```python
  try:
      self._conn.execute("ALTER TABLE sessions ADD COLUMN video_path TEXT")
      self._conn.commit()
  except Exception:
      pass  # column already exists — safe to ignore
  ```
- This runs once on startup and is idempotent.

**Tests:** `tests/test_storage.py`
- New test: creating a session and then calling `session_repo.set_video_path(id, path)`
  persists the value and `session_repo.get_video_path(id)` returns it.

---

### Issue 2 — SessionRepository: persist video path  
**File:** `app/storage/session_repository.py`

Add two methods:

```python
def set_video_path(self, session_id: int, path: str) -> None:
    """Store the video recording file path for a session."""
    ...

def get_video_path(self, session_id: int) -> str | None:
    """Return the video file path for a session, or None if not recorded."""
    ...
```

---

### Issue 3 — Session recording: start on session start, not camera-mode switch  
**Files:** `app/ui/views/live_view.py`, `app/core/session.py`

**Current behaviour:** `_start_camera_recording()` is only called when the user
switches to Camera+Bio mode.

**New behaviour:** recording starts automatically when `session_started` fires,
regardless of which mode the view is in.

Steps:
1. In `LiveView._on_session_started(session_id)`, always call
   `_start_camera_recording(session_id)` after storing the session ID.
2. `_start_camera_recording()` no longer checks `_MODE_CAMERA` — it always
   attempts to start if a session is active.
3. In `LiveView._end_session()`, call `_stop_camera_recording()` then pass the
   recording path (if any) to `SessionManager` via a new method
   `session_manager.set_recording_path(path)`.
4. `SessionManager` stores the path and writes it to the DB using
   `SessionRepository.set_video_path()` before emitting `session_ended`.

**If camera is unavailable:** `VideoFeed.start_recording()` returns `False` →
`_recording_path` stays `None` → nothing is stored in the DB → post-session
view shows the "no recording" placeholder. No error is raised.

---

### Issue 4 — Remove Schmettow learning-curve block from PostSessionView  
**File:** `app/ui/views/post_session_view.py`

Remove entirely:
- `self._lc_chart = LearningCurveChart(...)` and all `_lc_*` instance attributes
- `_build_learning_curve_area()` method
- `_update_learning_curve_data()` method
- `_on_lc_fit_finished()` method
- `_on_lc_worker_finished()` method
- `_on_lc_thread_finished()` method
- `_update_mentor_tip()` method
- `_stop_learning_curve_worker()` method
- The `root.addWidget(self._build_learning_curve_area())` line in `_build_ui()`
- All imports that are only used by the removed code:
  `LearningCurveChart`, `LearningCurveWorker`, `get_session_series`,
  `SessionDataPoint`, `mastery_percent`, `get_mentor_message`, `SCORE_MAX`,
  `numpy`, `QThread` (check if still used elsewhere before removing).

Also remove the `cleanup()` method and its call site in `main_window.py`
if `_stop_learning_curve_worker` was the only thing it called.

---

### Issue 5 — Update export button icon  
**File:** `app/ui/views/post_session_view.py`

In `_build_header()`, change:

```python
# Before
export_btn.setIcon(get_icon("ph.arrow-line-up", color="#FFFFFF"))

# After
export_btn.setIcon(get_icon("ph.download-simple", color="#FFFFFF"))
```

`ph.download-simple` is a clean, universally recognised download/export icon
available in Phosphor Icons (already a project dependency via `qtawesome`).

---

### Issue 6 — New `VideoPlayer` widget  
**New file:** `app/ui/widgets/video_player.py`

A self-contained playback widget for `.mp4` files recorded by `VideoFeed`.
Uses **OpenCV** (already a dependency) for frame reading and seeking,
driven by a `QTimer` at 30 fps.

**Public API:**

```python
class VideoPlayer(QWidget):
    timestamp_clicked = pyqtSignal(float)   # ms — for chart sync (future use)

    def load(self, file_path: str) -> None:
        """Open a video file. Shows placeholder if path is None or file missing."""

    def seek_to(self, position_ms: float) -> None:
        """Jump to the given position in milliseconds."""
```

**Layout (top to bottom):**
1. `QLabel` — frame display area (aspect-ratio-correct, dark background `#0A0F1E`)
2. Controls row:
   - Play/Pause `QToolButton` (icon: `ph.play-fill` / `ph.pause-fill`)
   - `QSlider` (horizontal, maps 0 → video duration in ms)
   - Time label `"MM:SS / MM:SS"` (current / total)

**Thread model:**
- `QTimer` (30 ms interval = ~33 fps) calls `_advance_frame()` in the UI thread.
- OpenCV `VideoCapture.read()` is fast enough for this at standard resolutions.
  If profiling shows UI jank, move to a QThread in a later sprint.
- `seek_to()` calls `cap.set(cv2.CAP_PROP_POS_MSEC, position_ms)` then reads
  one frame immediately so the display updates without waiting for the timer.

**Placeholder state:**
- When `load(None)` or the file doesn't exist: show a `QLabel` with
  `"No recording available for this session"` on a `#1A1F2E` background.
- No error is raised; the placeholder is the normal state for camera-off sessions.

---

### Issue 7 — `TimelineChart` widget: real pyqtgraph chart  
**New file:** `app/ui/widgets/timeline_chart.py`

Replaces the static placeholder in `PostSessionView._build_analysis_card()`.

**Data model:** Loaded from the database — two time series:
- `hrv_samples(timestamp, rmssd)` → **Stress** line (colour: `COLOR_DANGER`)
- `cli_samples(timestamp, cli)` → **Cognitive Workload** line (colour: `COLOR_PRIMARY`)

Both series share the same x-axis (seconds since session start, 0 → session duration).
RMSSD is plotted on the left y-axis (ms); CLI on the right y-axis (0.0–1.0).

**Interaction:**
- Single click anywhere on the chart emits `timestamp_clicked(float)` where the
  value is the clicked x position in **milliseconds** (for `VideoPlayer.seek_to()`).
- A vertical hairline cursor follows the mouse.
- Toggle buttons ("STRESS" / "COGNITIVE LOAD") above the chart show/hide each series.

**Public API:**

```python
class TimelineChart(pg.PlotWidget):
    timestamp_clicked = pyqtSignal(float)   # ms

    def load_session(self, db: DatabaseManager, session_id: int) -> None:
        """Query DB and plot both series for the given session."""
```

**Empty state:** if no samples exist, show `"No timeline data for this session"` as a
`TextItem` centred on the plot.

---

### Issue 8 — Assemble PostSessionView  
**File:** `app/ui/views/post_session_view.py`

After Issues 4–7 are done, wire everything together:

1. Replace `_build_analysis_card()` to instantiate and return `TimelineChart`.
2. Replace `_build_video_area()` to instantiate and return `VideoPlayer`.
3. In `load_session(session_id)`:
   - Call `self._timeline_chart.load_session(self._db, session_id)`.
   - Query `session_repo.get_video_path(session_id)`.
   - Call `self._video_player.load(video_path_or_none)`.
4. Connect signals: `self._timeline_chart.timestamp_clicked.connect(self._video_player.seek_to)`.
5. Update layout in `_build_ui()`:
   ```
   header
   metric cards  (3 cards: PERFORMANCE · TOTAL TIME · ERROR RATE)
   timeline chart  (stretch=2)
   video player    (stretch=3)
   ```

---

## File Change Summary

| File | Change |
|------|--------|
| `app/storage/database.py` | Add `video_path` column migration |
| `app/storage/session_repository.py` | Add `set_video_path()`, `get_video_path()` |
| `app/core/session.py` | Add `set_recording_path()`, write to DB on end |
| `app/ui/views/live_view.py` | Always start recording on session start |
| `app/ui/views/post_session_view.py` | Remove LC block; swap chart + video placeholders with real widgets; update export icon |
| `app/ui/widgets/video_player.py` | **New** — file playback widget |
| `app/ui/widgets/timeline_chart.py` | **New** — pyqtgraph timeline with click-to-seek |
| `tests/test_storage.py` | Tests for `video_path` persistence |
| `tests/test_video_player.py` | **New** — unit tests for placeholder / load states |
| `tests/test_timeline_chart.py` | **New** — unit tests for data loading and empty state |

---

## Acceptance Criteria

- [ ] Starting a session immediately starts recording; ending it saves `video_path` to DB.
- [ ] PostSessionView shows no learning curve block.
- [ ] Export button uses `ph.download-simple` icon.
- [ ] If `video_path` is NULL, VideoPlayer shows the "No recording" placeholder.
- [ ] If `video_path` exists, VideoPlayer plays the file; Play/Pause and scrub bar work.
- [ ] Clicking a point on the timeline chart seeks the video to that timestamp.
- [ ] Timeline chart shows RMSSD and CLI series from real DB data.
- [ ] App runs without errors when no camera is connected (graceful degradation).
- [ ] All existing tests still pass; new tests cover the new code paths.
