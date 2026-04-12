"""Widget tests for LiveView wall-contact error counting."""

import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.core.session import SessionManager, SessionState
from app.storage.database import DatabaseManager
from app.ui.views.live_view import LiveView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(db_path=str(tmp_path / "test.db"))


@pytest.fixture()
def manager(db: DatabaseManager, qapp: QApplication) -> SessionManager:
    del qapp
    return SessionManager(db)


@pytest.fixture()
def view(manager: SessionManager, qapp: QApplication) -> LiveView:
    widget = LiveView()
    widget.bind_session_manager(manager)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


class TestLiveViewErrorCounter:
    def test_manual_error_buttons_update_session_manager_and_display(
        self, view: LiveView, manager: SessionManager, qapp: QApplication
    ) -> None:
        """The toolbar counter should drive SessionManager's wall-contact count."""
        manager._state = SessionState.RUNNING

        view._error_input._plus_btn.click()
        qapp.processEvents()

        assert manager._error_count == 1
        assert view._error_input._count_label.text() == "1"

        view._error_input._minus_btn.click()
        qapp.processEvents()

        assert manager._error_count == 0
        assert view._error_input._count_label.text() == "0"

    def test_error_count_signal_updates_toolbar_display(
        self, view: LiveView, manager: SessionManager, qapp: QApplication
    ) -> None:
        """LiveView should reflect externally updated wall-contact counts."""
        manager.error_count_updated.emit(4)
        qapp.processEvents()

        assert view._error_input._count_label.text() == "4"
