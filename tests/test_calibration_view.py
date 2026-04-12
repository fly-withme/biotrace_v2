import pytest
from PyQt6.QtWidgets import QApplication

from app.ui.views.calibration_view import CalibrationView


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_space_advances_from_pupil_step_when_eye_tracker_disabled(monkeypatch, qapp) -> None:
    monkeypatch.setattr("app.ui.views.calibration_view.USE_EYE_TRACKER", False)

    view = CalibrationView()
    view.reset()

    assert view._step == "pupil_alignment"
    assert view._content_stack.currentIndex() == 0

    view._on_space_pressed()

    assert view._step == "breathing"
    assert view._content_stack.currentIndex() == 1
    assert view._step_label.text() == "STEP 2 OF 2  ·  BREATHING CALIBRATION"


def test_space_does_not_advance_before_eye_is_ready(monkeypatch, qapp) -> None:
    monkeypatch.setattr("app.ui.views.calibration_view.USE_EYE_TRACKER", False)
    view = CalibrationView()
    view._step = "pupil_alignment"
    view._eye_ready = False

    view._on_space_pressed()

    assert view._step == "pupil_alignment"
    assert view._pupil_status_label.text() == "Align your eye before continuing"
