"""Mock sensor drivers for development and testing without hardware.

These sensors emit simulated (randomised) data at realistic rates using
``QTimer``, so the full signal/slot pipeline can be exercised without any
physical devices attached.

Usage::

    from app.hardware.mock_sensors import MockHRVSensor, MockEyeTracker
    hrv = MockHRVSensor()
    hrv.raw_rr_interval_received.connect(my_processor.on_rr_interval)
    hrv.start()
    # … later …
    hrv.stop()
"""

import random
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.hardware.base_sensor import BaseSensor
from app.utils.config import (
    MOCK_EMIT_INTERVAL_MS,
    MOCK_PUPIL_INTERVAL_MS,
    MOCK_RR_MAX_MS,
    MOCK_RR_MIN_MS,
    MOCK_PUPIL_MIN_PX,
    MOCK_PUPIL_MAX_PX,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MockHRVSensor(BaseSensor):
    """Simulated HRV / heart rate sensor.

    Emits synthetic RR intervals drawn from a uniform distribution at
    ``MOCK_EMIT_INTERVAL_MS`` intervals.

    Signals:
        raw_rr_interval_received (float, float):
            Emitted with ``(rr_interval_ms, timestamp_s)`` on each tick.
            ``timestamp_s`` is seconds since the Unix epoch.
        connection_status_changed (bool, str):
            Mirrors the :class:`PicoECGSensor` contract so the rest of the
            system can treat mock and real sensors identically.
            Emits ``(True, "Mock connected")`` on ``start()`` and
            ``(False, "Mock disconnected")`` on ``stop()``.
    """

    raw_rr_interval_received  = pyqtSignal(float, float)  # (rr_ms, timestamp_s)
    connection_status_changed = pyqtSignal(bool, str)     # (connected, message)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(MOCK_EMIT_INTERVAL_MS)
        self._timer.timeout.connect(self._emit_sample)

    def start(self) -> None:
        """Begin emitting mock RR intervals."""
        if self._running:
            logger.warning("MockHRVSensor.start() called while already running.")
            return
        self._running = True
        self._timer.start()
        self.connection_status_changed.emit(True, "Mock connected")
        logger.info("MockHRVSensor started (interval=%d ms).", MOCK_EMIT_INTERVAL_MS)

    def stop(self) -> None:
        """Stop emitting mock data."""
        self._running = False
        self._timer.stop()
        self.connection_status_changed.emit(False, "Mock disconnected")
        logger.info("MockHRVSensor stopped.")

    def _emit_sample(self) -> None:
        """Generate and emit one mock RR interval."""
        rr_ms = random.uniform(MOCK_RR_MIN_MS, MOCK_RR_MAX_MS)
        timestamp = time.time()
        self.raw_rr_interval_received.emit(rr_ms, timestamp)


class MockEyeTracker(BaseSensor):
    """Simulated eye tracker / pupil diameter sensor.

    Emits synthetic pupil diameters for left and right eyes at
    ``MOCK_PUPIL_INTERVAL_MS`` intervals.  A slow sinusoidal drift is added
    to make the trace look physiologically plausible.

    Signals:
        raw_pupil_received (float, float, float):
            Emitted with ``(left_diameter_px, right_diameter_px, timestamp_s)``
            on each tick.
        connection_status_changed (bool, str):
            Emits ``(True, "Mock connected")`` on ``start()`` and
            ``(False, "Mock disconnected")`` on ``stop()``.
    """

    raw_pupil_received = pyqtSignal(float, float, float)  # (left_mm, right_mm, ts)
    connection_status_changed = pyqtSignal(bool, str)     # (connected, message)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(MOCK_PUPIL_INTERVAL_MS)
        self._timer.timeout.connect(self._emit_sample)
        self._t: float = 0.0  # phase counter for sinusoidal drift

    def start(self) -> None:
        """Begin emitting mock pupil measurements."""
        if self._running:
            logger.warning("MockEyeTracker.start() called while already running.")
            return
        self._running = True
        self._t = 0.0
        self._timer.start()
        self.connection_status_changed.emit(True, "Mock connected")
        logger.info("MockEyeTracker started (interval=%d ms).", MOCK_PUPIL_INTERVAL_MS)

    def stop(self) -> None:
        """Stop emitting mock data."""
        self._running = False
        self._timer.stop()
        self.connection_status_changed.emit(False, "Mock disconnected")
        logger.info("MockEyeTracker stopped.")

    def _emit_sample(self) -> None:
        """Generate and emit one mock pupil measurement."""
        import math

        mid = (MOCK_PUPIL_MIN_PX + MOCK_PUPIL_MAX_PX) / 2.0
        amp = (MOCK_PUPIL_MAX_PX - MOCK_PUPIL_MIN_PX) / 4.0

        # Slow sinusoidal drift + small random noise.
        drift = amp * math.sin(self._t * 0.05)
        noise = random.gauss(0, 0.5)

        diameter_px = mid + drift + noise

        # Clamp to realistic range.
        diameter_px = max(MOCK_PUPIL_MIN_PX, min(MOCK_PUPIL_MAX_PX, diameter_px))

        timestamp = time.time()
        self._t += 1.0
        # Emit monocular diameter (left=diameter, right=0.0)
        self.raw_pupil_received.emit(float(diameter_px), 0.0, timestamp)
