"""Tests for dashboard wall-contact aggregation."""

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.storage.database import DatabaseManager
from app.ui.views.dashboard_view import DashboardView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(db_path=str(tmp_path / "test.db"))


def test_dashboard_error_gauge_shows_average_errors_per_session(
    db: DatabaseManager, qapp: QApplication
) -> None:
    """The KPI should display average wall contacts per session."""
    conn = db.get_connection()
    start_a = datetime(2026, 1, 1, 10, 0, 0)
    start_b = datetime(2026, 1, 2, 10, 0, 0)

    conn.execute(
        "INSERT INTO sessions (started_at, ended_at, error_count) VALUES (?, ?, ?)",
        (start_a.isoformat(sep=" "), (start_a + timedelta(minutes=3)).isoformat(sep=" "), 6),
    )
    conn.execute(
        "INSERT INTO sessions (started_at, ended_at, error_count) VALUES (?, ?, ?)",
        (start_b.isoformat(sep=" "), (start_b + timedelta(minutes=1)).isoformat(sep=" "), 1),
    )
    conn.commit()

    view = DashboardView(db=db)
    view.show()
    qapp.processEvents()

    assert view._error_gauge is not None
    assert view._error_gauge._center_text == "3.5/session"

    view.close()


def test_dashboard_session_counter_uses_completed_sessions_only(
    db: DatabaseManager, qapp: QApplication
) -> None:
    """Dashboard session count should exclude abandoned sessions."""
    conn = db.get_connection()
    complete_start = datetime(2026, 1, 1, 10, 0, 0)
    incomplete_start = datetime(2026, 1, 2, 10, 0, 0)

    conn.execute(
        "INSERT INTO sessions (started_at, ended_at, error_count) VALUES (?, ?, ?)",
        (
            complete_start.isoformat(sep=" "),
            (complete_start + timedelta(minutes=2)).isoformat(sep=" "),
            1,
        ),
    )
    conn.execute(
        "INSERT INTO sessions (started_at) VALUES (?)",
        (incomplete_start.isoformat(sep=" "),),
    )
    conn.commit()

    view = DashboardView(db=db)
    view.show()
    qapp.processEvents()

    assert view._sessions_count_label is not None
    assert view._sessions_count_label.text() == "1"

    view.close()


def test_build_analysis_series_uses_z_score_percentages(
    db: DatabaseManager, qapp: QApplication
) -> None:
    """Stress and workload should be plotted on the same percentage scale."""
    conn = db.get_connection()
    start_a = datetime(2026, 1, 1, 10, 0, 0)
    start_b = datetime(2026, 1, 2, 10, 0, 0)

    conn.execute(
        "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, ?)",
        (1, start_a.isoformat(sep=" "), (start_a + timedelta(minutes=3)).isoformat(sep=" ")),
    )
    conn.execute(
        "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, ?)",
        (2, start_b.isoformat(sep=" "), (start_b + timedelta(minutes=3)).isoformat(sep=" ")),
    )
    conn.execute(
        "INSERT INTO hrv_samples (session_id, timestamp, rr_interval, rmssd) VALUES (1, 1, 800, 80.0)"
    )
    conn.execute(
        "INSERT INTO hrv_samples (session_id, timestamp, rr_interval, rmssd) VALUES (2, 1, 800, 120.0)"
    )
    conn.execute(
        "INSERT INTO cli_samples (session_id, timestamp, cli) VALUES (1, 1, 0.2)"
    )
    conn.execute(
        "INSERT INTO cli_samples (session_id, timestamp, cli) VALUES (2, 1, 0.8)"
    )
    conn.commit()

    view = DashboardView(db=db)
    view.show()
    qapp.processEvents()

    x_values, stress_values, workload_values, labels = view._build_analysis_series()

    assert x_values == [0.0, 1.0]
    assert labels == ["S1", "S2"]
    assert stress_values[0] > stress_values[1]
    assert workload_values[0] < workload_values[1]
    assert stress_values == pytest.approx([84.1344746, 15.8655254])
    assert workload_values == pytest.approx([15.8655254, 84.1344746])

    view.close()
