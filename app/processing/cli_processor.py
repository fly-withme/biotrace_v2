"""Composite Cognitive Load Index (CLI) processor for BioTrace.

Subscribes to processed RMSSD and PDI signals, tracks session-wide min/max
for normalization, and emits a combined CLI value in [0, 1].

Usage::

    hrv_proc = HRVProcessor()
    pupil_proc = PupilProcessor(baseline_px=100.0)
    cli_proc = CLIProcessor()

    hrv_proc.rmssd_updated.connect(cli_proc.on_rmssd_updated)
    pupil_proc.pdi_updated.connect(cli_proc.on_pdi_updated)
    cli_proc.cli_updated.connect(live_view.on_cli_updated)
"""

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from app.core.metrics import compute_cli
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Sentinel: not yet seen any data.
_UNSET = float("inf")


class CLIProcessor(QObject):
    """Combines RMSSD and PDI into the Cognitive Load Index.

    Maintains session-wide running min/max for both inputs so that the CLI
    is always normalized against the full observed physiological range.

    Signals:
        cli_updated (float, float):
            Emitted with ``(cli, timestamp_s)`` when both RMSSD and PDI are
            available.  CLI is in the range [0.0, 1.0].
    """

    cli_updated = pyqtSignal(float, float)  # (cli, timestamp_s)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rmssd: float | None = None
        self._rmssd_ts: float = 0.0
        self._pdi: float | None = None
        self._pdi_ts: float = 0.0

        # Running extremes for normalization.
        self._rmssd_min: float = _UNSET
        self._rmssd_max: float = -_UNSET
        self._pdi_min: float = _UNSET
        self._pdi_max: float = -_UNSET

    @pyqtSlot(float, float)
    def on_rmssd_updated(self, rmssd: float, timestamp_s: float) -> None:
        """Receive a new RMSSD value and attempt to compute CLI.

        Args:
            rmssd: Current rolling RMSSD in milliseconds.
            timestamp_s: Unix timestamp of the RMSSD computation.
        """
        self._rmssd = rmssd
        self._rmssd_ts = timestamp_s

        if rmssd > 0.0:
            self._rmssd_min = min(self._rmssd_min, rmssd)
            self._rmssd_max = max(self._rmssd_max, rmssd)

        self._try_emit()

    @pyqtSlot(float, float)
    def on_pdi_updated(self, pdi: float, timestamp_s: float) -> None:
        """Receive a new PDI value and attempt to compute CLI.

        Args:
            pdi: Current Pupil Dilation Index (dimensionless).
            timestamp_s: Unix timestamp of the PDI computation.
        """
        self._pdi = pdi
        self._pdi_ts = timestamp_s

        self._pdi_min = min(self._pdi_min, pdi)
        self._pdi_max = max(self._pdi_max, pdi)

        self._try_emit()

    def _try_emit(self) -> None:
        """Compute and emit CLI if both inputs are available."""
        if self._rmssd is None or self._pdi is None:
            return

        if (
            self._rmssd_min == _UNSET
            or self._rmssd_max == -_UNSET
            or self._pdi_min == _UNSET
            or self._pdi_max == -_UNSET
        ):
            return  # Not enough data yet for normalization

        cli = compute_cli(
            rmssd=self._rmssd,
            pdi=self._pdi,
            rmssd_min=self._rmssd_min,
            rmssd_max=self._rmssd_max,
            pdi_min=self._pdi_min,
            pdi_max=self._pdi_max,
        )

        # Use the most recent timestamp from either input.
        timestamp = max(self._rmssd_ts, self._pdi_ts)
        self.cli_updated.emit(cli, timestamp)

    def reset(self) -> None:
        """Clear all state between sessions."""
        self._rmssd = None
        self._pdi = None
        self._rmssd_min = _UNSET
        self._rmssd_max = -_UNSET
        self._pdi_min = _UNSET
        self._pdi_max = -_UNSET
        logger.info("CLIProcessor reset.")
