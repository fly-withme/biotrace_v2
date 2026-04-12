"""Real-time pupil dilation processor for BioTrace.

Subscribes to raw pupil diameter data, rejects blink artifacts, computes
the pupil percent change relative to the calibration baseline, and
emits the processed result.

Usage::

    eye_tracker = MockEyeTracker()
    processor = PupilProcessor(baseline_mm=4.5)
    eye_tracker.raw_pupil_received.connect(processor.on_pupil_sample)
    processor.pdi_updated.connect(live_view.on_pdi_updated)
"""

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from app.core.metrics import average_pupil_diameter, compute_pupil_pct_change
from app.utils.config import (
    PUPIL_BLINK_VELOCITY_THRESHOLD_PX,
    PUPIL_MAX_ABS_PCT_CHANGE,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PupilProcessor(QObject):
    """Processes raw pupil diameter streams into blink-cleaned percent change values.

    Blink detection uses a velocity threshold: if the diameter drops faster
    than ``PUPIL_BLINK_VELOCITY_THRESHOLD_PX`` per sample the sample is discarded.

    Signals:
        pdi_updated (float, float):
            Emitted with ``(pdi, timestamp_s)`` for each accepted sample.
            Blink frames do not produce an emission.
    """

    pdi_updated = pyqtSignal(float, float)  # (pdi, timestamp_s)

    def __init__(
        self,
        baseline_px: float = 0.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.baseline_px: float = baseline_px
        self._prev_diameter: float | None = None
        self._sample_count: int = 0   # total accepted samples (for detection-rate log)

    def set_baseline(self, baseline_px: float) -> None:
        """Update the calibration baseline diameter.

        Args:
            baseline_px: Resting pupil diameter in pixels from calibration.
        """
        self.baseline_px = baseline_px
        logger.info("PupilProcessor baseline set to %.3f px.", baseline_px)

    @pyqtSlot(float, float, float)
    def on_pupil_sample(
        self, left_px: float, right_px: float, timestamp_s: float
    ) -> None:
        """Receive a raw pupil measurement, reject blinks, emit % change.

        Args:
            left_px: Left eye pupil diameter in pixels.
            right_px: Right eye pupil diameter in pixels.
            timestamp_s: Unix timestamp of the measurement.
        """
        diameter = average_pupil_diameter(left_px, right_px)
        if diameter is None:
            return

        # Blink artifact rejection: discard if velocity exceeds threshold.
        if self._prev_diameter is not None:
            velocity = abs(diameter - self._prev_diameter)
            if velocity > PUPIL_BLINK_VELOCITY_THRESHOLD_PX:
                logger.debug(
                    "Blink artifact rejected: velocity=%.3f px/sample", velocity
                )
                self._prev_diameter = None  # reset; next sample treated as fresh
                return

        self._prev_diameter = diameter

        self._sample_count += 1
        if self._sample_count % 150 == 0:   # log every ~5 s at 30 fps
            logger.info(
                "PupilProcessor: %d samples accepted so far (baseline=%.2f px).",
                self._sample_count, self.baseline_px,
            )

        if self.baseline_px <= 0.0:
            # No calibration baseline yet — emit raw diameter so the live view
            # shows that the sensor is working.  The card unit is "px" so this
            # is still meaningful to the user.
            self.pdi_updated.emit(diameter, timestamp_s)
            return

        pupil_pct_change = compute_pupil_pct_change(diameter, self.baseline_px)
        if pupil_pct_change is None:
            return

        # Physiological outlier clamp: discard if change exceeds max absolute %.
        if abs(pupil_pct_change) > PUPIL_MAX_ABS_PCT_CHANGE:
            logger.debug("Pupil %% change outlier rejected: pct=%.3f", pupil_pct_change)
            return

        self.pdi_updated.emit(pupil_pct_change, timestamp_s)

    def reset(self) -> None:
        """Clear state between sessions."""
        self._prev_diameter = None
        self._sample_count = 0
        logger.info("PupilProcessor reset.")
