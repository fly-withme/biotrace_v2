# Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Settings page reachable from the sidebar with data-export/delete controls and three animated scientific flowchart cards (Stress, Cognitive Load, Learning Curves) where each node is clickable to reveal its formula and reference.

**Architecture:** A new `SettingsView` (index 6 in the `QStackedWidget`) contains a `_DataManagementCard` and three `FlowchartCard` widgets. Each `FlowchartCard` wraps a `_FlowchartCanvas` (custom `QPainter` widget with a `QTimer`-driven animated dash-offset) and a `_DetailPanel` that appears when a node is clicked. All animation starts/stops in `SettingsView.showEvent`/`hideEvent`.

**Tech Stack:** PyQt6, qtawesome (Phosphor icons), pandas + openpyxl (Excel export), SQLite3 (data deletion).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `app/storage/export.py` | Edit | Extract `_measurements_df()` helper; add `export_all_sessions()` |
| `app/ui/widgets/flowchart_card.py` | Create | `NodeDef`, `_FlowchartCanvas`, `_DetailPanel`, `FlowchartCard` |
| `app/ui/views/settings_view.py` | Create | `_ExportWorker`, `_DataManagementCard`, `SettingsView` + node defs |
| `app/ui/main_window.py` | Edit | Wire settings button; add `SettingsView` at stack index 6; handle `data_cleared` |
| `tests/test_export_all.py` | Create | Tests for `export_all_sessions()` |

---

## Task 1: Refactor `export_excel` and add `export_all_sessions()`

**Files:**
- Modify: `app/storage/export.py`
- Create: `tests/test_export_all.py`

### Step 1a: Write the failing tests

- [ ] Create `tests/test_export_all.py`:

```python
"""Tests for SessionExporter.export_all_sessions().

Run with:
    pytest tests/test_export_all.py -v
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import pytest

from app.storage.database import DatabaseManager
from app.storage.session_repository import SessionRepository
from app.storage.calibration_repository import CalibrationRepository
from app.storage.export import SessionExporter


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(db_path=str(tmp_path / "test.db"))


@pytest.fixture()
def two_sessions(db: DatabaseManager) -> tuple[int, int]:
    """Two completed sessions; returns (sid1, sid2)."""
    repo = SessionRepository(db)
    cal = CalibrationRepository(db)

    s1 = repo.create_session(datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc))
    repo.end_session(s1, datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc))
    cal.save_hrv_samples_bulk(s1, [(1.0, 850.0, 32.5, 70.6, 0.0)])

    s2 = repo.create_session(datetime(2025, 1, 2, 10, 0, tzinfo=timezone.utc))
    repo.end_session(s2, datetime(2025, 1, 2, 10, 45, tzinfo=timezone.utc))

    return s1, s2


class TestExportAllSessions:
    def test_creates_file(self, db: DatabaseManager, two_sessions, tmp_path: Path) -> None:
        out = tmp_path / "all.xlsx"
        SessionExporter(db).export_all_sessions(out)
        assert out.exists()

    def test_summary_sheet_exists(self, db: DatabaseManager, two_sessions, tmp_path: Path) -> None:
        out = tmp_path / "all.xlsx"
        SessionExporter(db).export_all_sessions(out)
        wb = openpyxl.load_workbook(out)
        assert "Summary" in wb.sheetnames

    def test_summary_has_one_row_per_session(
        self, db: DatabaseManager, two_sessions, tmp_path: Path
    ) -> None:
        out = tmp_path / "all.xlsx"
        SessionExporter(db).export_all_sessions(out)
        wb = openpyxl.load_workbook(out)
        ws = wb["Summary"]
        # 1 header + 2 data rows
        assert ws.max_row == 3

    def test_summary_column_headers(
        self, db: DatabaseManager, two_sessions, tmp_path: Path
    ) -> None:
        out = tmp_path / "all.xlsx"
        SessionExporter(db).export_all_sessions(out)
        wb = openpyxl.load_workbook(out)
        ws = wb["Summary"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        assert "Session ID" in headers
        assert "Date" in headers
        assert "Duration (s)" in headers

    def test_has_sheet_per_session(
        self, db: DatabaseManager, two_sessions, tmp_path: Path
    ) -> None:
        s1, s2 = two_sessions
        out = tmp_path / "all.xlsx"
        SessionExporter(db).export_all_sessions(out)
        wb = openpyxl.load_workbook(out)
        assert f"Session {s1}" in wb.sheetnames
        assert f"Session {s2}" in wb.sheetnames

    def test_session_sheet_has_measurements_columns(
        self, db: DatabaseManager, two_sessions, tmp_path: Path
    ) -> None:
        s1, _ = two_sessions
        out = tmp_path / "all.xlsx"
        SessionExporter(db).export_all_sessions(out)
        wb = openpyxl.load_workbook(out)
        ws = wb[f"Session {s1}"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        assert "Time" in headers
        assert "BPM" in headers
        assert "RMSSD" in headers

    def test_empty_database_writes_summary_only(
        self, db: DatabaseManager, tmp_path: Path
    ) -> None:
        out = tmp_path / "empty.xlsx"
        SessionExporter(db).export_all_sessions(out)
        assert out.exists()
        wb = openpyxl.load_workbook(out)
        assert "Summary" in wb.sheetnames
        ws = wb["Summary"]
        # Header + 1 "no sessions" row
        assert ws.max_row == 2
```

- [ ] Run to confirm all fail:
```bash
pytest tests/test_export_all.py -v
```
Expected: `ERROR` — `export_all_sessions` does not exist yet.

### Step 1b: Refactor `export_excel` and add `export_all_sessions`

- [ ] Edit `app/storage/export.py`. Add the `_measurements_df` helper and `export_all_sessions` method. The full updated class body (replace everything after the `__init__`):

```python
    def _fetch_session_data(self, session_id: int) -> dict:
        """Collect all data rows for a session into a dict."""
        session = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        hrv = self._conn.execute(
            "SELECT timestamp, rr_interval, bpm, rmssd, delta_rmssd FROM hrv_samples "
            "WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()

        pupil = self._conn.execute(
            "SELECT timestamp, left_diameter, right_diameter, pdi "
            "FROM pupil_samples WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()

        cli = self._conn.execute(
            "SELECT timestamp, cli FROM cli_samples "
            "WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()

        return {
            "session": dict(session) if session else {},
            "hrv": [dict(r) for r in hrv],
            "pupil": [dict(r) for r in pupil],
            "cli": [dict(r) for r in cli],
        }

    def _measurements_df(self, data: dict) -> pd.DataFrame:
        """Build the Measurements DataFrame from a session data dict.

        Merges HRV and pupil samples on timestamp (outer join), renames
        columns to human-readable labels, and returns NaN as None.

        Args:
            data: Dict returned by ``_fetch_session_data``.

        Returns:
            DataFrame with columns: Time, BPM, HRV, RMSSD, Delta RMSSD,
            Pupil Diameter, Delta Pupil Diameter.
        """
        hrv_df = pd.DataFrame(
            data["hrv"],
            columns=["timestamp", "rr_interval", "bpm", "rmssd", "delta_rmssd"],
        ) if data["hrv"] else pd.DataFrame(
            columns=["timestamp", "rr_interval", "bpm", "rmssd", "delta_rmssd"]
        )

        pupil_df = pd.DataFrame(
            data["pupil"],
            columns=["timestamp", "left_diameter", "right_diameter", "pdi"],
        ) if data["pupil"] else pd.DataFrame(
            columns=["timestamp", "left_diameter", "right_diameter", "pdi"]
        )

        if not pupil_df.empty:
            pupil_df["pupil_diameter"] = (
                pupil_df[["left_diameter", "right_diameter"]].mean(axis=1)
            )
        else:
            pupil_df["pupil_diameter"] = pd.Series(dtype=float)

        merged = pd.merge(
            hrv_df[["timestamp", "bpm", "rr_interval", "rmssd", "delta_rmssd"]],
            pupil_df[["timestamp", "pupil_diameter", "pdi"]],
            on="timestamp",
            how="outer",
        ).sort_values("timestamp").reset_index(drop=True)

        merged = merged.where(pd.notna(merged), other=None)

        return merged.rename(columns={
            "timestamp":        "Time",
            "bpm":              "BPM",
            "rr_interval":      "HRV",
            "rmssd":            "RMSSD",
            "delta_rmssd":      "Delta RMSSD",
            "pupil_diameter":   "Pupil Diameter",
            "pdi":              "Delta Pupil Diameter",
        })[["Time", "BPM", "HRV", "RMSSD", "Delta RMSSD",
            "Pupil Diameter", "Delta Pupil Diameter"]]

    def export_csv(self, session_id: int, path: str | Path) -> None:
        """Export session samples to a flat CSV file."""
        data = self._fetch_session_data(session_id)
        path = Path(path)

        combined: dict[float, dict] = {}
        for row in data["hrv"]:
            t = row["timestamp"]
            combined.setdefault(t, {})["rr_interval"] = row["rr_interval"]
            combined[t]["rmssd"] = row["rmssd"]
        for row in data["pupil"]:
            t = row["timestamp"]
            combined.setdefault(t, {})["left_diameter"] = row["left_diameter"]
            combined[t]["right_diameter"] = row["right_diameter"]
            combined[t]["pdi"] = row["pdi"]
        for row in data["cli"]:
            t = row["timestamp"]
            combined.setdefault(t, {})["cli"] = row["cli"]

        fieldnames = ["timestamp", "rr_interval", "rmssd",
                      "left_diameter", "right_diameter", "pdi", "cli"]
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for ts in sorted(combined):
                row = {"timestamp": ts}
                row.update(combined[ts])
                writer.writerow(row)

        logger.info("Session %d exported to CSV: %s", session_id, path)

    def export_json(self, session_id: int, path: str | Path) -> None:
        """Export all session data to a structured JSON file."""
        data = self._fetch_session_data(session_id)
        path = Path(path)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("Session %d exported to JSON: %s", session_id, path)

    def export_excel(self, session_id: int, path: str | Path) -> None:
        """Export all session data to a multi-sheet Excel (.xlsx) file.

        Sheets produced:
        - **Session Info** — session metadata.
        - **Measurements** — merged HRV + pupil data per timestamp.

        Args:
            session_id: The session to export.
            path: Destination ``.xlsx`` file path.
        """
        data = self._fetch_session_data(session_id)
        path = Path(path)
        session = data["session"]

        duration_s: int | None = None
        started_raw = session.get("started_at")
        ended_raw   = session.get("ended_at")
        if started_raw and ended_raw:
            from datetime import datetime as _dt
            try:
                duration_s = int(
                    (_dt.fromisoformat(str(ended_raw)) - _dt.fromisoformat(str(started_raw))
                     ).total_seconds()
                )
            except Exception:
                pass

        info_df = pd.DataFrame(
            [
                ("Session ID",     session.get("id")),
                ("Started at",     session.get("started_at")),
                ("Ended at",       session.get("ended_at")),
                ("Duration (s)",   duration_s),
                ("HRV samples",    len(data["hrv"])),
                ("Notes",          session.get("notes", "")),
                ("NASA-TLX score", session.get("nasa_tlx_score")),
            ],
            columns=["Field", "Value"],
        )

        measurements_df = self._measurements_df(data)

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            info_df.to_excel(writer, sheet_name="Session Info", index=False)
            measurements_df.to_excel(writer, sheet_name="Measurements", index=False)

        logger.info("Session %d exported to Excel: %s", session_id, path)

    def export_all_sessions(self, path: str | Path) -> None:
        """Export all completed sessions to a single multi-sheet Excel file.

        Sheets produced:
        - **Summary** — one row per session: ID, date, duration, NASA-TLX score,
          error count, notes.
        - **Session {id}** — per-session measurements for each completed session
          (same columns as the Measurements sheet in ``export_excel``).

        If no completed sessions exist, writes a Summary sheet with a single
        informational row.

        Args:
            path: Destination ``.xlsx`` file path (created or overwritten).
        """
        path = Path(path)
        sessions = self._conn.execute(
            "SELECT * FROM sessions WHERE ended_at IS NOT NULL ORDER BY started_at DESC"
        ).fetchall()

        summary_rows = []
        for s in sessions:
            from datetime import datetime as _dt
            try:
                duration_s: int | None = int(
                    (_dt.fromisoformat(str(s["ended_at"])) -
                     _dt.fromisoformat(str(s["started_at"]))).total_seconds()
                )
            except Exception:
                duration_s = None

            summary_rows.append({
                "Session ID":    s["id"],
                "Date":          str(s["started_at"]),
                "Duration (s)":  duration_s,
                "NASA-TLX Score": s["nasa_tlx_score"],
                "Error Count":   s["error_count"],
                "Notes":         s["notes"] or "",
            })

        if summary_rows:
            summary_df = pd.DataFrame(summary_rows)
        else:
            summary_df = pd.DataFrame([{"Session ID": "No sessions recorded"}])

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Summary", index=False)
            for s in sessions:
                sid = s["id"]
                sheet_name = f"Session {sid}"
                data = self._fetch_session_data(sid)
                mdf = self._measurements_df(data)
                mdf.to_excel(writer, sheet_name=sheet_name, index=False)

        logger.info("All sessions exported to Excel: %s", path)
```

- [ ] Run tests to confirm they pass:
```bash
pytest tests/test_export_all.py tests/test_export_excel.py -v
```
Expected: all pass.

- [ ] Commit:
```bash
git add app/storage/export.py tests/test_export_all.py
git commit -m "feat: add export_all_sessions() with _measurements_df refactor"
```

---

## Task 2: Create `FlowchartCard` widget

**Files:**
- Create: `app/ui/widgets/flowchart_card.py`

- [ ] Create `app/ui/widgets/flowchart_card.py` with the full content below:

```python
"""FlowchartCard — animated scientific pipeline flowchart widget for BioTrace.

Each card displays a horizontal row of icon nodes connected by animated
dotted lines (flowing-dots effect). Clicking a node expands an inline
detail panel showing the step's formula, description, and citation.

Architecture:
    FlowchartCard (QFrame#card)
      ├── _FlowchartCanvas   ← QPainter + QTimer, emits node_clicked(int)
      └── _DetailPanel       ← hidden QFrame, shown on node click
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import (
    CARD_PADDING,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_DANGER,
    COLOR_FONT,
    COLOR_FONT_MUTED,
    COLOR_PRIMARY,
    COLOR_PRIMARY_SUBTLE,
    COLOR_WARNING,
    COLOR_WARNING_BG,
    FONT_BODY,
    FONT_CAPTION,
    FONT_FAMILY,
    FONT_SMALL,
    ICON_SIZE_INLINE,
    RADIUS_MD,
    SPACE_1,
    SPACE_2,
    get_icon,
)

# ── Constants ─────────────────────────────────────────────────────────────
_NODE_SIZE   = 44   # px — icon background square
_ICON_SIZE   = 22   # px — icon inside the square
_LABEL_GAP   =  8   # px — gap between node bottom and label
_LABEL_HEIGHT = 18  # px
_NODE_CENTER_Y_RATIO = 0.42   # fraction of canvas height for node vertical centre
_DASH_PERIOD = 10.0           # wraps dash offset at this value


# ── NodeDef ───────────────────────────────────────────────────────────────

@dataclass
class NodeDef:
    """Definition for a single flowchart step.

    Attributes:
        icon: qtawesome icon name (e.g. ``"ph.heart-fill"``).
        label: Short label shown below the icon (≤12 chars works best).
        formula: Unicode math formula string shown in the detail panel.
        description: 1–2 sentence plain-English explanation.
        reference: Full citation string, or empty string if none.
        is_threshold: If True, renders with warning colours (threshold gate).
    """
    icon: str
    label: str
    formula: str
    description: str
    reference: str
    is_threshold: bool = False


# ── _FlowchartCanvas ──────────────────────────────────────────────────────

class _FlowchartCanvas(QWidget):
    """Custom-painted canvas showing nodes connected by animated dotted lines.

    Signals:
        node_clicked (int): Emitted with the 0-based index of the clicked node.
    """

    node_clicked = pyqtSignal(int)

    def __init__(self, nodes: list[NodeDef], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nodes = nodes
        self._dash_offset: float = 0.0
        self._pixmaps: list[QPixmap] = []

        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._timer = QTimer(self)
        self._timer.setInterval(25)   # ~40 fps
        self._timer.timeout.connect(self._tick)

        self._prerender_icons()

    # ------------------------------------------------------------------
    # Animation control
    # ------------------------------------------------------------------

    def start_animation(self) -> None:
        """Start the flowing-dots animation."""
        self._timer.start()

    def stop_animation(self) -> None:
        """Pause the animation (saves CPU when the page is hidden)."""
        self._timer.stop()

    def _tick(self) -> None:
        """Advance the dash offset and request a repaint."""
        self._dash_offset = (self._dash_offset + 1.0) % _DASH_PERIOD
        self.update()

    # ------------------------------------------------------------------
    # Icon pre-rendering
    # ------------------------------------------------------------------

    def _prerender_icons(self) -> None:
        """Render all node icons to QPixmap once at construction time.

        Falls back to ``ph.circle-fill`` if the requested icon name is not
        found in qtawesome, so the app never crashes on a missing icon.
        """
        self._pixmaps.clear()
        for nd in self._nodes:
            color = COLOR_WARNING if nd.is_threshold else COLOR_PRIMARY
            try:
                pm = get_icon(nd.icon, color=color, size=_ICON_SIZE).pixmap(
                    QSize(_ICON_SIZE, _ICON_SIZE)
                )
            except Exception:
                pm = get_icon("ph.circle-fill", color=color, size=_ICON_SIZE).pixmap(
                    QSize(_ICON_SIZE, _ICON_SIZE)
                )
            self._pixmaps.append(pm)

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _node_centers(self) -> list[tuple[int, int]]:
        """Return (cx, cy) for each node in the current widget size."""
        n = len(self._nodes)
        if n == 0:
            return []
        w = self.width()
        cy = int(self.height() * _NODE_CENTER_Y_RATIO)
        gap = w / n
        return [(int(gap * i + gap / 2), cy) for i in range(n)]

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        centers = self._node_centers()
        n = len(centers)
        half = _NODE_SIZE // 2

        # 1. Connector lines (animated dashes + arrowhead)
        dash_pen = QPen(QColor(COLOR_BORDER))
        dash_pen.setWidth(2)
        dash_pen.setStyle(Qt.PenStyle.CustomDashLine)
        dash_pen.setDashPattern([4.0, 6.0])
        dash_pen.setDashOffset(self._dash_offset)

        arrow_pen = QPen(QColor(COLOR_FONT_MUTED))
        arrow_pen.setWidth(2)

        for i in range(n - 1):
            cx1, cy1 = centers[i]
            cx2, cy2 = centers[i + 1]
            x1 = cx1 + half + 4
            x2 = cx2 - half - 4
            if x2 > x1:
                painter.setPen(dash_pen)
                painter.drawLine(x1, cy1, x2, cy1)

                # Arrowhead at destination end
                painter.setPen(arrow_pen)
                a = 5
                painter.drawLine(x2, cy1, x2 - a, cy1 - a)
                painter.drawLine(x2, cy1, x2 - a, cy1 + a)

        # 2. Node backgrounds + icons
        for i, (cx, cy) in enumerate(centers):
            nd = self._nodes[i]
            bg = QColor(COLOR_WARNING_BG if nd.is_threshold else COLOR_PRIMARY_SUBTLE)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(
                QRect(cx - half, cy - half, _NODE_SIZE, _NODE_SIZE),
                RADIUS_MD,
                RADIUS_MD,
            )

            pm = self._pixmaps[i]
            painter.drawPixmap(cx - pm.width() // 2, cy - pm.height() // 2, pm)

        # 3. Labels below nodes
        label_font = QFont(FONT_FAMILY)
        label_font.setPixelSize(FONT_CAPTION)
        painter.setFont(label_font)
        painter.setPen(QPen(QColor(COLOR_FONT_MUTED)))

        for i, (cx, cy) in enumerate(centers):
            label_y = cy + half + _LABEL_GAP
            painter.drawText(
                QRect(cx - 50, label_y, 100, _LABEL_HEIGHT),
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop,
                self._nodes[i].label,
            )

        painter.end()

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Emit node_clicked(i) when the user clicks inside a node rect."""
        pos = event.position()
        click_x, click_y = pos.x(), pos.y()
        half = _NODE_SIZE // 2

        for i, (cx, cy) in enumerate(self._node_centers()):
            if abs(click_x - cx) <= half and abs(click_y - cy) <= half:
                self.node_clicked.emit(i)
                return


# ── _DetailPanel ──────────────────────────────────────────────────────────

class _DetailPanel(QFrame):
    """Inline panel that appears below the canvas when a node is clicked.

    Shows the step name, formula (monospace block), plain-English
    description, and scientific reference.

    Signals:
        close_requested: Emitted when the user clicks the ✕ button.
    """

    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_PRIMARY_SUBTLE}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: {RADIUS_MD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        layout.setSpacing(SPACE_1)

        # ── Top row: step name + close button ────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(SPACE_1)

        self._step_lbl = QLabel()
        self._step_lbl.setStyleSheet(
            f"font-size: {FONT_BODY}px; font-weight: 700; color: {COLOR_FONT}; "
            f"background: transparent; border: none;"
        )
        top_row.addWidget(self._step_lbl)
        top_row.addStretch()

        close_btn = QPushButton()
        try:
            close_btn.setIcon(get_icon("ph.x-fill", color=COLOR_FONT_MUTED))
        except Exception:
            close_btn.setText("✕")
        close_btn.setIconSize(QSize(ICON_SIZE_INLINE, ICON_SIZE_INLINE))
        close_btn.setObjectName("secondary")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            f"QPushButton#secondary {{ background: transparent; border: none; color: {COLOR_FONT_MUTED}; }}"
            f"QPushButton#secondary:hover {{ background: {COLOR_BORDER}; }}"
        )
        close_btn.clicked.connect(self.close_requested)
        top_row.addWidget(close_btn)
        layout.addLayout(top_row)

        # ── Formula block (monospace) ────────────────────────────────
        formula_frame = QFrame()
        formula_frame.setStyleSheet(
            f"QFrame {{ background: {COLOR_CARD}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: {RADIUS_MD}px; }}"
        )
        ff_layout = QVBoxLayout(formula_frame)
        ff_layout.setContentsMargins(SPACE_2, SPACE_1, SPACE_2, SPACE_1)

        self._formula_lbl = QLabel()
        self._formula_lbl.setWordWrap(True)
        self._formula_lbl.setStyleSheet(
            f"font-family: 'Courier New', monospace; font-size: {FONT_BODY}px; "
            f"color: {COLOR_PRIMARY}; background: transparent; border: none;"
        )
        ff_layout.addWidget(self._formula_lbl)
        layout.addWidget(formula_frame)

        # ── Description ──────────────────────────────────────────────
        self._desc_lbl = QLabel()
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {FONT_BODY}px; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self._desc_lbl)

        # ── Reference ────────────────────────────────────────────────
        self._ref_lbl = QLabel()
        self._ref_lbl.setWordWrap(True)
        self._ref_lbl.setStyleSheet(
            f"color: {COLOR_FONT_MUTED}; font-size: {FONT_SMALL}px; "
            f"font-style: italic; background: transparent; border: none;"
        )
        layout.addWidget(self._ref_lbl)

        self.setVisible(False)

    def show_node(self, node: NodeDef) -> None:
        """Populate with node data and make the panel visible.

        Args:
            node: The :class:`NodeDef` whose details to display.
        """
        self._step_lbl.setText(node.label)
        self._formula_lbl.setText(node.formula)
        self._desc_lbl.setText(node.description)
        if node.reference:
            self._ref_lbl.setText(f"Reference: {node.reference}")
            self._ref_lbl.setVisible(True)
        else:
            self._ref_lbl.setVisible(False)
        self.setVisible(True)

    def hide_panel(self) -> None:
        """Hide the detail panel."""
        self.setVisible(False)


# ── FlowchartCard ─────────────────────────────────────────────────────────

class FlowchartCard(QFrame):
    """A titled card containing an animated flowchart and a click-to-reveal
    formula panel.

    Args:
        title: Card heading (e.g. ``"Stress"``).
        subtitle: Muted subtitle (e.g. ``"HRV · RMSSD · Δ from Baseline"``).
        nodes: Ordered list of :class:`NodeDef` objects.
        parent: Optional parent widget.
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        nodes: list[NodeDef],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._nodes = nodes
        self._active_index = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(SPACE_1)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("subheading")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setObjectName("muted")
        layout.addWidget(sub_lbl)

        layout.addSpacing(SPACE_2)

        self._canvas = _FlowchartCanvas(nodes)
        layout.addWidget(self._canvas)

        self._detail_panel = _DetailPanel()
        self._detail_panel.close_requested.connect(self._close_detail)
        layout.addWidget(self._detail_panel)

        self._canvas.node_clicked.connect(self._on_node_clicked)

    # ------------------------------------------------------------------
    # Animation control (delegated to canvas)
    # ------------------------------------------------------------------

    def start_animation(self) -> None:
        """Start the flowing-dots animation on the canvas."""
        self._canvas.start_animation()

    def stop_animation(self) -> None:
        """Stop the flowing-dots animation."""
        self._canvas.stop_animation()

    # ------------------------------------------------------------------
    # Node click handling
    # ------------------------------------------------------------------

    def _on_node_clicked(self, index: int) -> None:
        """Show the detail panel for the clicked node, or toggle it off."""
        if self._active_index == index:
            self._close_detail()
        else:
            self._active_index = index
            self._detail_panel.show_node(self._nodes[index])

    def _close_detail(self) -> None:
        """Hide the detail panel and reset active node tracking."""
        self._active_index = -1
        self._detail_panel.hide_panel()
```

- [ ] Commit:
```bash
git add app/ui/widgets/flowchart_card.py
git commit -m "feat: add FlowchartCard widget with animated nodes and detail panel"
```

---

## Task 3: Create `SettingsView`

**Files:**
- Create: `app/ui/views/settings_view.py`

- [ ] Create `app/ui/views/settings_view.py` with the full content below:

```python
"""Settings view for BioTrace.

Contains two sections:
1. Data Management — export all sessions to Excel, delete all data.
2. How It Works — three animated flowchart cards explaining the scientific
   pipeline behind Stress, Cognitive Load, and Learning Curves.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from app.storage.database import DatabaseManager
from app.ui.theme import (
    CARD_PADDING,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_DANGER_BG,
    COLOR_FONT,
    COLOR_FONT_MUTED,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    CONTENT_PADDING_H,
    CONTENT_PADDING_V,
    FONT_BODY,
    FONT_SMALL,
    GRID_GUTTER,
    ICON_SIZE_DEFAULT,
    RADIUS_MD,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_4,
    get_icon,
)
from app.ui.widgets.flowchart_card import FlowchartCard, NodeDef
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Node definitions ──────────────────────────────────────────────────────

STRESS_NODES: list[NodeDef] = [
    NodeDef(
        icon="ph.heart-fill",
        label="Heart Sensor",
        formula="Signal(t): ECG sampled at 250 Hz",
        description=(
            "Raw electrical heart signal from the HRV sensor connected via USB. "
            "Each R-peak in the ECG marks one heartbeat."
        ),
        reference="",
    ),
    NodeDef(
        icon="ph.calculator-fill",
        label="RMSSD",
        formula="RMSSD = √( mean( (RR[i+1] − RR[i])² ) )",
        description=(
            "Root Mean Square of Successive Differences. Computed over a 30-second "
            "sliding window updated every second. Higher RMSSD = lower physiological stress."
        ),
        reference=(
            "Task Force of ESC & NASPE (1996). Heart rate variability: standards of "
            "measurement, physiological interpretation, and clinical use. "
            "Circulation, 93(5), 1043–1065."
        ),
    ),
    NodeDef(
        icon="ph.arrows-down-up-fill",
        label="Δ Baseline",
        formula=(
            "ΔRMSSD = RMSSD_t − RMSSD_baseline\n"
            "Threshold: stress flagged if ΔRMSSD < −15 ms"
        ),
        description=(
            "Change in RMSSD relative to the resting baseline recorded during "
            "calibration. A sustained negative delta signals increased stress."
        ),
        reference=(
            "Shaffer, F. & Ginsberg, J. P. (2017). An overview of heart rate "
            "variability metrics and norms. Frontiers in Public Health, 5, 258."
        ),
        is_threshold=True,
    ),
    NodeDef(
        icon="ph.gauge-fill",
        label="Stress Score",
        formula="Score = norm(1 / RMSSD),  range 0–1",
        description=(
            "RMSSD is inverted (higher RMSSD = less stress) then normalised to 0–1 "
            "against session min/max. Feeds into the Cognitive Load Index as w₁."
        ),
        reference=(
            "Thayer, J. F. et al. (2012). A meta-analysis of heart rate variability "
            "and neuroimaging studies. Neuroscience & Biobehavioral Reviews, 36(2), 747–756."
        ),
    ),
]

COGNITIVE_LOAD_NODES: list[NodeDef] = [
    NodeDef(
        icon="ph.eye-fill",
        label="Eye Camera",
        formula="d(t): pupil diameter in pixels at 30 Hz",
        description=(
            "Raw pupil diameter captured by the PuRe algorithm from the USB eye-tracker "
            "camera. Blink artefacts are rejected when Δd/Δt exceeds a velocity threshold."
        ),
        reference=(
            "Peavler, W. S. (1974). Pupil size, information overload, and performance "
            "differences. Journal of Experimental Psychology, 103(6), 1140–1148."
        ),
    ),
    NodeDef(
        icon="ph.drop-fill",
        label="PDI",
        formula="PDI = (d_t − d_baseline) / d_baseline",
        description=(
            "Pupil Dilation Index — the normalised change from the 60-second resting "
            "baseline recorded during calibration. Positive PDI = dilated pupil = higher load."
        ),
        reference=(
            "Beatty, J. (1982). Task-evoked pupillary responses, processing load, and "
            "the structure of processing resources. Psychological Bulletin, 91(2), 276–292. "
            "Kahneman, D. & Beatty, J. (1966). Pupil diameter and load on memory. "
            "Science, 154(3756), 1583–1585."
        ),
    ),
    NodeDef(
        icon="ph.funnel-fill",
        label="Threshold",
        formula="Load flagged if PDI > 0.15  (15% above baseline)",
        description=(
            "When PDI exceeds 15% above the resting baseline, cognitive load is flagged. "
            "The threshold is configurable in config.py."
        ),
        reference=(
            "Beatty, J. (1982). Task-evoked pupillary responses, processing load, and "
            "the structure of processing resources. Psychological Bulletin, 91(2), 276–292."
        ),
        is_threshold=True,
    ),
    NodeDef(
        icon="ph.brain-fill",
        label="CLI",
        formula="CLI = 0.5 · norm(1/RMSSD) + 0.5 · norm(PDI)",
        description=(
            "Cognitive Load Index — composite of stress (HRV component) and cognitive "
            "load (pupil component). Both inputs are normalised 0–1. Range: 0 (no load) "
            "to 1 (maximum load). Weights configurable in config.py."
        ),
        reference="",
    ),
]

LEARNING_CURVE_NODES: list[NodeDef] = [
    NodeDef(
        icon="ph.clipboard-text-fill",
        label="Session Data",
        formula="y₁, y₂, …, yₙ  (time, score, or errors per trial)",
        description=(
            "Raw performance metric recorded after each trial. "
            "Supported metrics: Total Time (s), Score, or Tissue Damage count."
        ),
        reference="",
    ),
    NodeDef(
        icon="ph.list-bullets-fill",
        label="Trial Sequence",
        formula="Trial order: t = 1, 2, …, N  (chronological)",
        description=(
            "Trials are sorted by date/time to form a chronological learning sequence. "
            "Each trial is one attempt at the laparoscopic exercise."
        ),
        reference=(
            "Wright, T. P. (1936). Factors affecting the cost of airplanes. "
            "Journal of the Aeronautical Sciences, 3(4), 122–128."
        ),
    ),
    NodeDef(
        icon="ph.chart-line-up-fill",
        label="Model Fit",
        formula="ŷ(t) = α · t^β   (NLS fit)",
        description=(
            "Schmettow power-law model fitted via non-linear least squares. "
            "α = starting performance level; β = learning rate. "
            "Requires a minimum of 5 trials."
        ),
        reference=(
            "Schmettow, M. (2014). Heterogeneity in the Stroop effect: "
            "Differences among individuals, groups, and studies. "
            "Proceedings of the Human Factors and Ergonomics Society Annual Meeting, "
            "58(1), 1677–1681."
        ),
    ),
    NodeDef(
        icon="ph.trend-up-fill",
        label="Curve",
        formula="β < 0: improving   β = 0: no change   β > 0: degrading",
        description=(
            "The fitted curve visualises the individual learning trajectory. "
            "A steeper (more negative) β indicates faster skill acquisition."
        ),
        reference=(
            "Schmettow, M. (2014). Proceedings of the HFES Annual Meeting, "
            "58(1), 1677–1681."
        ),
    ),
]


# ── Export worker ─────────────────────────────────────────────────────────

class _ExportWorker(QThread):
    """Background thread that runs export_all_sessions() off the UI thread.

    Signals:
        finished: Emitted on successful completion.
        error (str): Emitted with the error message on failure.
    """

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, path: str) -> None:
        super().__init__()
        self._db = db
        self._path = path

    def run(self) -> None:
        """Execute the export."""
        from app.storage.export import SessionExporter
        try:
            SessionExporter(self._db).export_all_sessions(self._path)
            self.finished.emit()
        except Exception as exc:  # noqa: BLE001
            logger.error("Export failed: %s", exc)
            self.error.emit(str(exc))


# ── _DataManagementCard ───────────────────────────────────────────────────

class _DataManagementCard(QFrame):
    """Card containing Export All and Delete All controls.

    Signals:
        data_cleared: Emitted after all sessions have been deleted.
    """

    data_cleared = pyqtSignal()

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._db = db
        self._export_worker: _ExportWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(SPACE_2)

        # ── Heading ──────────────────────────────────────────────────
        heading = QLabel("Data Management")
        heading.setObjectName("subheading")
        layout.addWidget(heading)

        # ── Export row ───────────────────────────────────────────────
        export_row = QHBoxLayout()
        self._export_btn = QPushButton("  Export All Sessions")
        try:
            self._export_btn.setIcon(
                get_icon("ph.file-spreadsheet-fill", color="#FFFFFF")
            )
        except Exception:
            self._export_btn.setIcon(get_icon("ph.export-fill", color="#FFFFFF"))
        self._export_btn.setIconSize(QSize(ICON_SIZE_DEFAULT, ICON_SIZE_DEFAULT))
        self._export_btn.clicked.connect(self._on_export)
        export_row.addWidget(self._export_btn)

        self._export_status = QLabel()
        self._export_status.setVisible(False)
        export_row.addWidget(self._export_status)
        export_row.addStretch()
        layout.addLayout(export_row)

        export_desc = QLabel("Download all sessions as a multi-sheet Excel (.xlsx) file.")
        export_desc.setObjectName("muted")
        layout.addWidget(export_desc)

        # ── Divider ──────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        # ── Delete row ───────────────────────────────────────────────
        delete_row = QHBoxLayout()
        self._delete_btn = QPushButton("  Delete All Data")
        try:
            self._delete_btn.setIcon(get_icon("ph.trash-fill", color="#FFFFFF"))
        except Exception:
            pass
        self._delete_btn.setIconSize(QSize(ICON_SIZE_DEFAULT, ICON_SIZE_DEFAULT))
        self._delete_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_DANGER}; color: #FFFFFF; "
            f"border-radius: {RADIUS_MD}px; padding: 10px 16px; }}"
            f"QPushButton:hover {{ background-color: #DC2626; }}"
        )
        self._delete_btn.clicked.connect(self._show_confirm)
        delete_row.addWidget(self._delete_btn)
        delete_row.addStretch()
        layout.addLayout(delete_row)

        delete_desc = QLabel("Permanently delete all session data. This cannot be undone.")
        delete_desc.setObjectName("muted")
        layout.addWidget(delete_desc)

        # ── Confirmation banner (hidden by default) ───────────────────
        self._confirm_banner = QFrame()
        self._confirm_banner.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_DANGER_BG}; "
            f"border: 1px solid {COLOR_DANGER}; border-radius: {RADIUS_MD}px; }}"
        )
        banner_layout = QHBoxLayout(self._confirm_banner)
        banner_layout.setContentsMargins(SPACE_2, SPACE_1, SPACE_2, SPACE_1)

        self._confirm_label = QLabel()
        self._confirm_label.setWordWrap(True)
        self._confirm_label.setStyleSheet(
            f"color: {COLOR_DANGER}; font-size: {FONT_BODY}px; "
            f"background: transparent; border: none;"
        )
        banner_layout.addWidget(self._confirm_label, stretch=1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self._hide_confirm)
        banner_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton("Confirm Delete")
        confirm_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_DANGER}; color: #FFFFFF; "
            f"border-radius: {RADIUS_MD}px; padding: 10px 16px; }}"
            f"QPushButton:hover {{ background-color: #DC2626; }}"
        )
        confirm_btn.clicked.connect(self._on_confirm_delete)
        banner_layout.addWidget(confirm_btn)

        self._confirm_banner.setVisible(False)
        layout.addWidget(self._confirm_banner)

    def _show_confirm(self) -> None:
        """Show the inline confirmation banner with session count."""
        from app.storage.session_repository import SessionRepository
        n = len(SessionRepository(self._db).get_all_sessions())
        self._confirm_label.setText(
            f"This will permanently delete all {n} session(s) and cannot be undone."
        )
        self._confirm_banner.setVisible(True)

    def _hide_confirm(self) -> None:
        """Collapse the confirmation banner."""
        self._confirm_banner.setVisible(False)

    def _on_confirm_delete(self) -> None:
        """Execute the delete and emit data_cleared."""
        conn = self._db.get_connection()
        conn.execute("DELETE FROM sessions")
        conn.commit()
        self._confirm_banner.setVisible(False)
        logger.info("All session data deleted by user.")
        self.data_cleared.emit()

    def _on_export(self) -> None:
        """Open a save dialog and start the background export thread."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export All Sessions",
            "biotrace_export.xlsx",
            "Excel Files (*.xlsx)",
        )
        if not path:
            return

        self._export_btn.setEnabled(False)
        self._export_btn.setText("  Exporting…")
        self._export_status.setVisible(False)

        self._export_worker = _ExportWorker(self._db, path)
        self._export_worker.finished.connect(self._on_export_done)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

    def _on_export_done(self) -> None:
        """Re-enable the button and show a success status label."""
        self._export_btn.setEnabled(True)
        self._export_btn.setText("  Export All Sessions")
        self._export_status.setText("Exported successfully")
        self._export_status.setStyleSheet(
            f"color: {COLOR_SUCCESS}; font-size: {FONT_SMALL}px;"
        )
        self._export_status.setVisible(True)
        self._export_worker = None

    def _on_export_error(self, message: str) -> None:
        """Re-enable the button and show an error status label."""
        self._export_btn.setEnabled(True)
        self._export_btn.setText("  Export All Sessions")
        self._export_status.setText(f"Export failed: {message}")
        self._export_status.setStyleSheet(
            f"color: {COLOR_DANGER}; font-size: {FONT_SMALL}px;"
        )
        self._export_status.setVisible(True)
        self._export_worker = None


# ── SettingsView ──────────────────────────────────────────────────────────

class SettingsView(QWidget):
    """Root settings page widget.

    Sections:
    - Data Management card (export + delete).
    - How It Works section with three animated flowchart cards.

    Signals:
        data_cleared: Forwarded from _DataManagementCard after deletion.

    Args:
        db: Shared database manager (dependency injected from MainWindow).
        parent: Optional parent widget.
    """

    data_cleared = pyqtSignal()

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flowchart_cards: list[FlowchartCard] = []
        self._build_ui(db)

    def _build_ui(self, db: DatabaseManager) -> None:
        """Construct all child widgets."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            CONTENT_PADDING_H, CONTENT_PADDING_V,
            CONTENT_PADDING_H, CONTENT_PADDING_V,
        )
        layout.setSpacing(SPACE_4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── Page heading ─────────────────────────────────────────────
        heading = QLabel("Settings")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        # ── Data Management card ─────────────────────────────────────
        data_card = _DataManagementCard(db)
        data_card.data_cleared.connect(self.data_cleared)
        layout.addWidget(data_card)

        # ── How It Works section ─────────────────────────────────────
        how_heading = QLabel("How It Works")
        how_heading.setObjectName("subheading")
        layout.addWidget(how_heading)

        how_sub = QLabel(
            "Click any step in the flowcharts below to see the formula and "
            "scientific reference."
        )
        how_sub.setObjectName("muted")
        how_sub.setWordWrap(True)
        layout.addWidget(how_sub)

        # Three cards side by side
        cards_row = QHBoxLayout()
        cards_row.setSpacing(GRID_GUTTER)

        stress_card = FlowchartCard(
            "Stress",
            "HRV · RMSSD · Δ from Baseline",
            STRESS_NODES,
        )
        cload_card = FlowchartCard(
            "Cognitive Load",
            "Pupil · PDI · CLI",
            COGNITIVE_LOAD_NODES,
        )
        lcurve_card = FlowchartCard(
            "Learning Curves",
            "Schmettow Power-Law Model",
            LEARNING_CURVE_NODES,
        )

        for card in (stress_card, cload_card, lcurve_card):
            cards_row.addWidget(card)
            self._flowchart_cards.append(card)

        layout.addLayout(cards_row)

    # ------------------------------------------------------------------
    # Animation lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        """Start all flowchart animations when the page becomes visible."""
        super().showEvent(event)
        for card in self._flowchart_cards:
            card.start_animation()

    def hideEvent(self, event) -> None:  # noqa: N802
        """Stop all flowchart animations when the page is hidden."""
        super().hideEvent(event)
        for card in self._flowchart_cards:
            card.stop_animation()
```

- [ ] Commit:
```bash
git add app/ui/views/settings_view.py
git commit -m "feat: add SettingsView with data management and flowchart cards"
```

---

## Task 4: Wire `MainWindow`

**Files:**
- Modify: `app/ui/main_window.py`

- [ ] **Step 4a** — Add the `SettingsView` import at the top of `app/ui/main_window.py`, alongside the other view imports:

```python
from app.ui.views.settings_view import SettingsView
```

- [ ] **Step 4b** — In `_build_ui`, after the `_excel_import_view` line, add:

```python
self._settings_view = SettingsView(db=self._db)
self._stack.addWidget(self._settings_view)   # 6
```

- [ ] **Step 4c** — In `__init__`, after the `_excel_import_view.close_requested` wiring, add:

```python
# Settings: data cleared → refresh dashboard + sidebar, navigate home
self._settings_view.data_cleared.connect(self._on_data_cleared)
```

- [ ] **Step 4d** — Add the `_on_data_cleared` method to `MainWindow` (place it near `_on_session_ended`):

```python
def _on_data_cleared(self) -> None:
    """Refresh all data-dependent views after the user deletes all sessions."""
    self._dashboard_view.refresh()
    self._populate_recent_sessions()
    self.navigate_to(0)
    logger.info("All data cleared — navigated to Dashboard.")
```

- [ ] **Step 4e** — In `_build_sidebar`, find the existing `settings_btn` block (around line 261) and replace it:

```python
# Replace:
settings_btn = QPushButton("  Settings")
settings_btn.setIcon(get_icon("ph.gear-six-fill", color=COLOR_FONT))
settings_btn.setIconSize(QSize(ICON_SIZE_NAV, ICON_SIZE_NAV))
settings_btn.setObjectName("nav_button")
layout.addWidget(settings_btn)

# With:
settings_btn = QPushButton("  Settings")
settings_btn.setIcon(get_icon("ph.gear-six-fill", color=COLOR_FONT))
settings_btn.setIconSize(QSize(ICON_SIZE_NAV, ICON_SIZE_NAV))
settings_btn.setObjectName("nav_button")
settings_btn.setCheckable(True)
settings_btn.clicked.connect(lambda: self.navigate_to(6))
layout.addWidget(settings_btn)
self._settings_btn = settings_btn
```

- [ ] **Step 4f** — In `navigate_to`, add the settings button checked-state logic. Find the loop that updates `_nav_buttons` and add one line after it:

```python
# After the existing loop:
for btn in self._nav_buttons:
    btn.setChecked(btn.property("target_index") == index)

# Add:
if hasattr(self, "_settings_btn"):
    self._settings_btn.setChecked(index == 6)
```

- [ ] **Step 4g** — In `navigate_to`, extend the `view_names` list to include `"Settings"` at index 6:

```python
# Replace:
view_names = ["Dashboard", "Sensors", "Calibration", "Live Session", "Post-Session", "Learning Curves"]

# With:
view_names = ["Dashboard", "Sensors", "Calibration", "Live Session", "Post-Session", "Learning Curves", "Settings"]
```

- [ ] **Step 4h** — In `navigate_to`, extend the sidebar-refresh guard for import page to also handle settings:

```python
# The existing guard is:
if index == 5:
    self._excel_import_view.refresh_history()

# Leave it as-is — no refresh needed for Settings at index 6.
```

- [ ] **Step 4i** — Verify index 6 is NOT in the full-width set (sidebar should stay visible on Settings). Confirm this line reads:

```python
self._sidebar.setVisible(index not in (2, 3))
```

Calibration (2) and Live Session (3) hide the sidebar. Settings (6) does not — it is already excluded, so no change needed here.

- [ ] Commit:
```bash
git add app/ui/main_window.py
git commit -m "feat: wire settings page into sidebar and main window stack"
```

---

## Task 5: Smoke-test the full flow

- [ ] Launch the app and verify:
  1. Clicking "Settings" in the sidebar navigates to the Settings page and the button highlights.
  2. Clicking a different nav button (Dashboard, Sensors, Learning Curves) un-highlights Settings.
  3. The three flowchart cards are visible. The dotted lines between nodes are moving.
  4. Clicking a node expands the detail panel with the correct formula and reference.
  5. Clicking the same node again (or the ✕ button) closes the detail panel.
  6. Clicking "Export All Sessions" opens a file dialog. After saving, the status label shows "Exported successfully" and the file exists on disk.
  7. Clicking "Delete All Data" shows the confirmation banner with the session count. Clicking "Cancel" collapses it. Clicking "Confirm Delete" deletes all data, navigates to Dashboard, and the sidebar recent-sessions area shows "No recent sessions".

```bash
python main.py
```

- [ ] Run all tests to confirm nothing regressed:
```bash
pytest tests/ -v
```
Expected: all tests pass.

- [ ] Commit if any minor fixes were needed:
```bash
git add -p
git commit -m "fix: address smoke-test issues in settings page"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Export all sessions (Excel, multi-sheet) — Task 1
- ✅ Delete all data with confirmation — Task 3 (`_DataManagementCard`)
- ✅ Animated flowing-dots connector lines — Task 2 (`_FlowchartCanvas`)
- ✅ Fixed icon nodes — Task 2 (pre-rendered pixmaps)
- ✅ Click node → show formula + reference — Task 2 (`_DetailPanel`)
- ✅ Click same node → close panel — Task 2 (`FlowchartCard._on_node_clicked`)
- ✅ Delta/threshold nodes styled differently (warning colours) — Task 2
- ✅ Scientific references on every formula-bearing node — Task 3 (node defs)
- ✅ Sidebar button wired + highlighted — Task 4
- ✅ Animations start/stop with page visibility — Task 3 (`showEvent`/`hideEvent`)

**Potential icon name issues:** `ph.arrows-down-up-fill`, `ph.drop-fill`, `ph.list-bullets-fill`, `ph.trend-up-fill`, and `ph.file-spreadsheet-fill` may not exist in the installed qtawesome version. All are wrapped in try/except blocks that fall back to `ph.circle-fill` (canvas icons) or silently skip icon setting (buttons), so the app will not crash. Verify and replace with correct names if icons appear as circles.
