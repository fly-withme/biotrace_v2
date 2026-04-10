"""Real-time pupil dilation processor for BioTrace.

Subscribes to raw pupil diameter data, rejects blink artifacts, computes
the Pupil Dilation Index (PDI) relative to the calibration baseline, and
emits the processed result.

Usage::

    eye_tracker = MockEyeTracker()
    processor = PupilProcessor(baseline_mm=4.5)
    eye_tracker.raw_pupil_received.connect(processor.on_pupil_sample)
    processor.pdi_updated.connect(live_view.on_pdi_updated)
"""

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from app.core.metrics import average_pupil_diameter, compute_pdi
from app.utils.config import (
    PUPIL_BLINK_VELOCITY_THRESHOLD_PX,
    PUPIL_PDI_OUTLIER_CLAMP
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PupilProcessor(QObject):
    """Processes raw pupil diameter streams into blink-cleaned PDI values.

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
        """Receive a raw pupil measurement, reject blinks, emit PDI.

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

        if self.baseline_px <= 0.0:
            # Baseline not yet set (pre-calibration); skip PDI computation.
            return

        pdi = compute_pdi(diameter, self.baseline_px)
        
        # Physiological outlier clamp: discard if change > 40 % from baseline.
        if abs(pdi) > PUPIL_PDI_OUTLIER_CLAMP:
            logger.debug("PDI outlier rejected: pdi=%.3f", pdi)
            return

        self.pdi_updated.emit(pdi, timestamp_s)

    def reset(self) -> None:
        """Clear state between sessions."""
        self._prev_diameter = None
        logger.info("PupilProcessor reset.")
