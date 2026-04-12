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


def test_space_advances_even_when_eye_is_not_ready(monkeypatch, qapp) -> None:
    monkeypatch.setattr("app.ui.views.calibration_view.USE_EYE_TRACKER", False)
    view = CalibrationView()
    view._step = "pupil_alignment"
    view._eye_ready = False

    view._on_space_pressed()

    assert view._step == "breathing"
    assert view._content_stack.currentIndex() == 1


def test_next_button_advances_from_pupil_step(monkeypatch, qapp) -> None:
    monkeypatch.setattr("app.ui.views.calibration_view.USE_EYE_TRACKER", False)

    view = CalibrationView()
    view.reset()

    view._next_btn.click()

    assert view._step == "breathing"
    assert view._content_stack.currentIndex() == 1


def test_back_button_emits_close_requested(monkeypatch, qapp) -> None:
    monkeypatch.setattr("app.ui.views.calibration_view.USE_EYE_TRACKER", False)

    view = CalibrationView()
    closed = []
    view.close_requested.connect(lambda: closed.append(True))

    view._on_close()

    assert closed == [True]


def test_skip_from_pupil_step_starts_breathing_baseline_instead_of_proceeding(
    monkeypatch, qapp
) -> None:
    monkeypatch.setattr("app.ui.views.calibration_view.USE_EYE_TRACKER", False)

    view = CalibrationView()
    view.reset()

    started = []
    proceeded = []
    monkeypatch.setattr(view, "_start_prestart_countdown", lambda: started.append(True))
    view.proceed_to_live.connect(lambda: proceeded.append(True))

    view._on_skip_calibration()

    assert view._step == "breathing"
    assert started == [True]
    assert proceeded == []


def test_skip_during_active_recording_ends_calibration_and_proceeds(
    monkeypatch, qapp
) -> None:
    monkeypatch.setattr("app.ui.views.calibration_view.USE_EYE_TRACKER", False)

    class _FakeSessionManager:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def end_calibration(self, duration_seconds: int):
            self.calls.append(duration_seconds)
            return (42.0, 123.0)

    view = CalibrationView()
    view.reset()
    view._session_manager = _FakeSessionManager()
    view._step = "breathing"
    view._recording = True
    view._baseline_remaining = 10

    proceeded = []
    view.proceed_to_live.connect(lambda: proceeded.append(True))

    view._on_skip_calibration()

    assert view._session_manager.calls == [50]  # 60 - 10
    assert view._computed_rmssd == pytest.approx(42.0)
    assert view._computed_pupil == pytest.approx(123.0)
    assert proceeded == [True]
