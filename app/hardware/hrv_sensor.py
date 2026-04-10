"""Stub hardware drivers for the real HRV sensor and eye tracker.

These files define the class interface that must be filled in once the physical
devices are available (Phase 6 of the roadmap). Until then, use
:class:`app.hardware.mock_sensors.MockHRVSensor` instead.

The class inherits :class:`~app.hardware.base_sensor.BaseSensor` and declares
the same signal as the mock, so the rest of the system is completely unaffected
when the real driver replaces the mock.
"""

from PyQt6.QtCore import QObject, pyqtSignal

from app.hardware.base_sensor import BaseSensor
from app.utils.logger import get_logger

logger = get_logger(__name__)


class HRVSensor(BaseSensor):
    """Real HRV sensor driver (serial / USB microcontroller).

    .. note::
        Not yet implemented. Use :class:`~app.hardware.mock_sensors.MockHRVSensor`
        during development.

    Signals:
        raw_rr_interval_received (float, float):
            Emitted with ``(rr_interval_ms, timestamp_s)`` for each R-R beat.
    """

    raw_rr_interval_received = pyqtSignal(float, float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # TODO (Phase 6): initialise serial port from config.HRV_SENSOR_PORT

    def start(self) -> None:
        """Open serial connection and begin parsing RR intervals."""
        raise NotImplementedError(
            "HRVSensor is not implemented yet. Use MockHRVSensor for development."
        )

    def stop(self) -> None:
        """Close serial connection."""
        raise NotImplementedError(
            "HRVSensor is not implemented yet. Use MockHRVSensor for development."
        )
