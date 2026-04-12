"""Widget tests for the post-session dashboard header actions."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.storage.database import DatabaseManager
from app.ui.views.post_session_view import PostSessionView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(db_path=str(tmp_path / "test.db"))


@pytest.fixture()
def view(db: DatabaseManager, qapp: QApplication) -> PostSessionView:
    widget = PostSessionView(db=db)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


class TestPostSessionViewHeader:
    def test_start_session_button_is_positioned_left_of_export(
        self, view: PostSessionView, qapp: QApplication
    ) -> None:
        """The header should place Start Session before a ghost Export action."""
        assert view._start_session_btn is not None
        assert view._export_btn is not None

        qapp.processEvents()

        assert view._start_session_btn.text() == "Start Session"
        assert view._export_btn.text().strip() == "Export Data"
        assert view._start_session_btn.x() < view._export_btn.x()
        assert view._export_btn.objectName() == "secondary"

    def test_start_session_button_emits_new_session_requested(
        self, view: PostSessionView
    ) -> None:
        """Clicking the header CTA should request the standard new-session flow."""
        received: list[bool] = []
        view.new_session_requested.connect(lambda: received.append(True))

        assert view._start_session_btn is not None
        view._start_session_btn.click()

        assert received == [True]


class TestPostSessionMetrics:
    def test_metric_cards_show_duration_errors_max_stress_and_max_cli(
        self, view: PostSessionView, db: DatabaseManager
    ) -> None:
        conn = db.get_connection()
        started_at = datetime(2026, 4, 12, 20, 0, 0, tzinfo=timezone.utc)
        ended_at = started_at + timedelta(minutes=2, seconds=5)  # 125 s

        cur = conn.execute(
            "INSERT INTO sessions (started_at, ended_at, error_count) VALUES (?, ?, ?)",
            (started_at.isoformat(sep=" "), ended_at.isoformat(sep=" "), 3),
        )
        sid = int(cur.lastrowid)

        conn.execute(
            "INSERT INTO calibrations (session_id, recorded_at, duration_seconds, baseline_rmssd, baseline_pupil_mm) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, started_at.isoformat(sep=" "), 30, 50.0, 120.0),
        )
        conn.executemany(
            "INSERT INTO hrv_samples (session_id, timestamp, rr_interval, rmssd) VALUES (?, ?, ?, ?)",
            [
                (sid, 1.0, 800.0, 50.0),
                (sid, 2.0, 800.0, 35.0),  # max stress = (50-35)/50 = 30%
                (sid, 3.0, 800.0, 45.0),
            ],
        )
        conn.executemany(
            "INSERT INTO cli_samples (session_id, timestamp, cli) VALUES (?, ?, ?)",
            [
                (sid, 1.0, 0.25),
                (sid, 2.0, 0.80),  # max CLI = 80%
                (sid, 3.0, 0.50),
            ],
        )
        conn.commit()

        view.load_session(sid)

        assert view._duration_gauge is not None
        assert view._errors_gauge is not None
        assert view._max_stress_gauge is not None
        assert view._max_cli_gauge is not None

        assert view._duration_gauge._center_text == "2:05"
        assert view._errors_gauge._center_text == "3"
        assert view._max_stress_gauge._center_text == "30%"
        assert view._max_cli_gauge._center_text == "80%"
