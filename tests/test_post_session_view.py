"""Widget tests for the post-session dashboard header actions."""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.storage.calibration_repository import CalibrationRepository
from app.storage.database import DatabaseManager
from app.storage.session_repository import SessionRepository
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
    def test_export_button_is_positioned_left_of_start_session(
        self, view: PostSessionView, qapp: QApplication
    ) -> None:
        """The header should place Export before the primary Start Session CTA."""
        assert view._start_session_btn is not None
        assert view._export_btn is not None

        qapp.processEvents()

        assert view._start_session_btn.text() == "Start Session"
        assert view._export_btn.text().strip() == "Export Data"
        assert view._export_btn.x() < view._start_session_btn.x()
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

    def test_delete_session_button_removes_session_after_confirmation(
        self, view: PostSessionView, db: DatabaseManager, monkeypatch
    ) -> None:
        """Delete action should remove the session and emit the deletion signal."""
        repo = SessionRepository(db)
        sid = repo.create_session(datetime.now(tz=timezone.utc))
        repo.end_session(sid, datetime.now(tz=timezone.utc))
        view.load_session(sid)

        deleted: list[int] = []
        view.session_deleted.connect(deleted.append)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )

        view._delete_session_btn.click()

        assert deleted == [sid]
        assert repo.get_session(sid) is None

    def test_load_session_passes_stress_markers_to_video_player(
        self, view: PostSessionView, db: DatabaseManager
    ) -> None:
        """Loading a session should expose severe RMSSD drops as video markers."""
        repo = SessionRepository(db)
        cal_repo = CalibrationRepository(db)
        sid = repo.create_session(datetime.now(tz=timezone.utc))
        repo.end_session(sid, datetime.now(tz=timezone.utc))
        cal_repo.save_calibration(sid, 100.0, 0.0, 60)
        cal_repo.save_hrv_samples_bulk(
            sid,
            [
                (0.0, 800.0, 90.0, 75.0, 0.0),
                (1.0, 800.0, 50.0, 75.0, 0.0),
            ],
        )

        view.load_session(sid)

        assert view._video_player._stress_markers_ms == [1000.0]
