import pytest
from PyQt6.QtWidgets import QApplication

from app.core.session import SessionManager
from app.storage.database import DatabaseManager
from app.ui.views.live_view import LiveView


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def db(tmp_path) -> DatabaseManager:
    return DatabaseManager(db_path=str(tmp_path / "test_live_view.db"))


@pytest.fixture()
def manager(db: DatabaseManager, qapp) -> SessionManager:
    return SessionManager(db)


class TestLiveView:
    def test_bind_session_manager_restores_pupil_percentage_mode(
        self, qapp, manager: SessionManager
    ) -> None:
        view = LiveView()
        manager.set_pupil_baseline(120.0)

        view.bind_session_manager(manager)

        assert view._has_pupil_baseline is True
        assert view._pupil_card._unit == "%"

    def test_bind_session_manager_restores_rmssd_percentage_mode(
        self, qapp, manager: SessionManager
    ) -> None:
        view = LiveView()
        manager._baseline_rmssd = 50.0

        view.bind_session_manager(manager)

        assert view._rmssd_card._unit == "%"

    def test_bind_session_manager_keeps_raw_units_without_baselines(
        self, qapp, manager: SessionManager
    ) -> None:
        view = LiveView()

        view.bind_session_manager(manager)

        assert view._pupil_card._unit == "px"
        assert view._rmssd_card._unit == "ms"

    def test_session_start_keeps_pupil_percentage_mode_when_baseline_exists(
        self, qapp, manager: SessionManager, monkeypatch
    ) -> None:
        view = LiveView()
        manager.set_pupil_baseline(120.0)
        view.bind_session_manager(manager)

        monkeypatch.setattr(view._video_feed, "start", lambda *args, **kwargs: None)
        monkeypatch.setattr(view, "_start_camera_recording", lambda: None)

        view._on_session_started(1)

        assert view._has_pupil_baseline is True
        assert view._pupil_card._unit == "%"

    def test_rmssd_updates_feed_hrv_series(
        self, qapp
    ) -> None:
        view = LiveView()

        view.on_rmssd_updated(50.0, 100.0)

        assert "HRV" in view._timeline_chart._curves
        assert "STRESS" not in view._timeline_chart._curves
        assert list(view._timeline_chart._timestamps["HRV"]) == [100.0]
        assert list(view._timeline_chart._values["HRV"]) == [pytest.approx(0.5)]

    def test_rmssd_card_displays_percentage_change_from_baseline(
        self, qapp, manager: SessionManager
    ) -> None:
        view = LiveView()
        manager._baseline_rmssd = 40.0
        view.bind_session_manager(manager)

        view.on_rmssd_updated(50.0, 100.0)

        assert view._rmssd_card._raw_value == pytest.approx(25.0)
        assert view._rmssd_card._unit == "%"
        assert view._stress_gauge._center_text == "25%"
        assert view._cam_stress_value.text() == "25%"

    def test_rmssd_card_displays_raw_ms_without_baseline(
        self, qapp
    ) -> None:
        view = LiveView()

        view.on_rmssd_updated(50.0, 100.0)

        assert view._rmssd_card._raw_value == pytest.approx(50.0)
        assert view._rmssd_card._unit == "ms"

    def test_stress_gauge_stays_unavailable_without_baseline(
        self, qapp
    ) -> None:
        view = LiveView()

        view.on_rmssd_updated(80.0, 100.0)

        assert view._stress_gauge._center_text == "—"
        assert view._cam_stress_value.text() == "—"

    def test_rmssd_timeline_uses_running_z_score_normalization(
        self, qapp
    ) -> None:
        view = LiveView()

        view.on_rmssd_updated(50.0, 100.0)
        view.on_rmssd_updated(70.0, 101.0)

        assert list(view._timeline_chart._timestamps["HRV"]) == [100.0, 101.0]
        assert list(view._timeline_chart._values["HRV"]) == [
            pytest.approx(0.5),
            pytest.approx(1.0),
        ]

    def test_cognitive_load_gauge_uses_pupil_change_percentage(
        self, qapp, manager: SessionManager
    ) -> None:
        view = LiveView()
        manager.set_pupil_baseline(120.0)
        view.bind_session_manager(manager)

        view.on_pdi_updated(10.0, 100.0)
        assert view._workload_gauge._center_text == "50%"
        assert view._cam_workload_value.text() == "50%"

        view.on_pdi_updated(30.0, 100.15)
        assert view._workload_gauge._center_text == "100%"
        assert list(view._timeline_chart._timestamps["PUPIL"]) == [100.0, 100.15]
        assert "THRESHOLD" not in view._timeline_chart._timestamps

    def test_cognitive_load_gauge_uses_magnitude_for_negative_pupil_change(
        self, qapp, manager: SessionManager
    ) -> None:
        view = LiveView()
        manager.set_pupil_baseline(120.0)
        view.bind_session_manager(manager)

        view.on_pdi_updated(-5.0, 100.0)

        assert view._workload_gauge._center_text == "25%"
        assert view._workload_gauge._value == pytest.approx(0.25)

    def test_pupil_card_shows_magnitude_for_negative_pupil_change(
        self, qapp, manager: SessionManager
    ) -> None:
        view = LiveView()
        manager.set_pupil_baseline(120.0)
        view.bind_session_manager(manager)

        view.on_pdi_updated(-7.0, 100.0)

        assert view._pupil_card._raw_value == pytest.approx(7.0)
        assert view._pupil_card._unit == "%"

    def test_pupil_card_displays_percentage_change_when_baseline_exists(
        self, qapp, manager: SessionManager
    ) -> None:
        view = LiveView()
        manager.set_pupil_baseline(120.0)
        view.bind_session_manager(manager)

        view.on_pdi_updated(12.0, 100.0)

        assert view._pupil_card._raw_value == pytest.approx(12.0)
        assert view._pupil_card._unit == "%"

    def test_pupil_card_without_baseline_bootstraps_runtime_percent_for_load_gauge(
        self, qapp
    ) -> None:
        view = LiveView()

        view.on_pdi_updated(100.0, 100.0)
        view.on_pdi_updated(120.0, 100.1)

        assert view._pupil_card._raw_value == pytest.approx(120.0)
        assert view._pupil_card._unit == "px"
        assert view._workload_gauge._center_text == "20%"

    def test_error_rate_card_updates_from_wall_contacts(
        self, qapp, manager: SessionManager, monkeypatch
    ) -> None:
        view = LiveView()
        view.bind_session_manager(manager)

        monkeypatch.setattr(view._video_feed, "start", lambda *args, **kwargs: None)
        monkeypatch.setattr(view, "_start_camera_recording", lambda: None)

        view._on_session_started(1)
        view._elapsed_seconds = 30
        view.on_error_count_updated(2)

        assert view._error_rate_card._name == "ERROR RATE"
        assert view._error_rate_card._unit == "/min"
        assert view._error_rate_card._raw_value == pytest.approx(4.0)
