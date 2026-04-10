"""Real-time RMSSD processor for BioTrace.

Subscribes to raw RR-interval data from any sensor that emits
``raw_rr_interval_received(rr_ms: float, timestamp_s: float)``, maintains a
sliding-window buffer, and emits a computed ``rmssd_updated`` signal every
time a new interval arrives.

Usage::

    hrv_sensor = MockHRVSensor()
    processor = HRVProcessor()
    hrv_sensor.raw_rr_interval_received.connect(processor.on_rr_interval)
    processor.rmssd_updated.connect(live_view.on_rmssd_updated)
    processor.rmssd_updated.connect(data_store.on_rmssd_updated)
"""

from collections import deque

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from app.core.metrics import compute_rmssd
from app.utils.config import RMSSD_WINDOW_SECONDS, HRV_MIN_RR_MS
from app.utils.logger import get_logger

logger = get_logger(__name__)


class HRVProcessor(QObject):
    """Maintains a sliding RR-interval window and emits RMSSD updates.

    Attributes:
        window_seconds: Duration of the sliding analysis window in seconds.

    Signals:
        rmssd_updated (float, float):
            Emitted with ``(rmssd_ms, timestamp_s)`` after each new RR interval.
            Kept for backward compatibility with existing LiveView connections.
        hrv_updated (float, float, float, float, float):
            Emitted with ``(rr_ms, bpm, rmssd_ms, delta_rmssd_ms, timestamp_s)``
            after each new RR interval.  Carries the full per-beat HRV picture
            needed by the storage layer (Phase 6a-3).
    """

    rmssd_updated = pyqtSignal(float, float)               # (rmssd_ms, timestamp_s)
    hrv_updated   = pyqtSignal(float, float, float, float, float)  # (rr_ms, bpm, rmssd_ms, delta_rmssd_ms, timestamp_s)

    def __init__(
        self,
        window_seconds: int = RMSSD_WINDOW_SECONDS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.window_seconds: int = window_seconds

        # Circular buffers — (timestamp_s, rr_ms) pairs.
        self._timestamps: deque[float] = deque()
        self._rr_intervals: deque[float] = deque()

        # Previous RMSSD value used to compute delta_rmssd.
        self._prev_rmssd: float = 0.0

    @pyqtSlot(float, float)
    def on_rr_interval(self, rr_ms: float, timestamp_s: float) -> None:
        """Receive a new RR interval, update the sliding window, emit metrics.

        Applies a physiological plausibility filter first: intervals below
        ``HRV_MIN_RR_MS`` (implying heart rates above ~180 BPM) are silently
        discarded as T-wave artefacts or noise.

        Computes and emits:
        - ``rmssd_updated`` for backward compatibility.
        - ``hrv_updated`` carrying rr_ms, instantaneous BPM, RMSSD, and
          delta RMSSD (change since previous emission).

        Args:
            rr_ms: New RR interval in milliseconds.
            timestamp_s: Unix timestamp (seconds) when the beat was detected.
        """
        if rr_ms < HRV_MIN_RR_MS:
            logger.debug("RR interval %.1f ms rejected (< %.1f ms minimum).", rr_ms, HRV_MIN_RR_MS)
            return

        self._timestamps.append(timestamp_s)
        self._rr_intervals.append(rr_ms)

        # Evict samples older than window_seconds.
        cutoff = timestamp_s - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
            self._rr_intervals.popleft()

        rr_array = np.array(self._rr_intervals, dtype=float)
        rmssd = compute_rmssd(rr_array)

        bpm         = 60_000.0 / rr_ms
        delta_rmssd = rmssd - self._prev_rmssd
        self._prev_rmssd = rmssd

        self.rmssd_updated.emit(rmssd, timestamp_s)
        self.hrv_updated.emit(rr_ms, bpm, rmssd, delta_rmssd, timestamp_s)

    def reset(self) -> None:
        """Clear all buffered data (call at session start/end)."""
        self._timestamps.clear()
        self._rr_intervals.clear()
        self._prev_rmssd = 0.0
        logger.info("HRVProcessor reset.")
