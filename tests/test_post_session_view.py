"""Widget tests for the post-session dashboard header actions."""

import os
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
