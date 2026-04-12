"""TimelineChart — pyqtgraph-based session analysis chart.

Displays Stress (RMSSD) and Pupil Dilation (PDI) over the course of a session
on a unified ``% Change from Baseline`` Y axis.

Both series are normalised before plotting:

- **Stress (RMSSD)**: ``(rmssd − baseline_rmssd) / baseline_rmssd × 100``
  Positive values = RMSSD above baseline (lower stress).
  Negative values = RMSSD below baseline (higher stress).

- **Pupil Change**: stored as baseline-relative percent change directly.

A persistent grey playhead line tracks the current video position.
A hover hairline follows the mouse cursor.
"""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.analytics.performance_repository import z_scores_to_percentages
from app.storage.database import DatabaseManager
from app.ui.theme import (
    COLOR_BORDER,
    COLOR_FONT_MUTED,
    COLOR_PRIMARY,
    COLOR_WARNING,
    COLOR_CARD,
    FONT_SMALL,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TimelineChart(QWidget):
    """Interactive session analysis chart with Stress and Pupil Dilation series.

    Both series share a single Y axis scaled to ``% Change from Baseline``.

    Signals:
        timestamp_clicked (float): Emitted when the user clicks on the chart,
                                   in milliseconds from session start.
    """

    timestamp_clicked = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._stress_marker_timestamps_ms: list[float] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_session(self, db: DatabaseManager, session_id: int) -> None:
        """Query the database and plot readable scaled series for the session.

        Args:
            db: Database manager instance.
            session_id: ID of the session to load.
        """
        self.clear()

        conn = db.get_connection()

        # ── Calibration baseline for RMSSD normalisation ──────────────
        cal_row = conn.execute(
            "SELECT baseline_rmssd FROM calibrations "
            "WHERE session_id = ? AND baseline_rmssd IS NOT NULL ORDER BY id ASC LIMIT 1",
            (session_id,),
        ).fetchone()
        baseline_rmssd: float | None = float(cal_row[0]) if cal_row else None

        # ── Stress (RMSSD) as % change from baseline ──────────────────
        hrv_rows = conn.execute(
            "SELECT timestamp, rmssd FROM hrv_samples "
            "WHERE session_id = ? AND rmssd IS NOT NULL ORDER BY timestamp",
            (session_id,),
        ).fetchall()

        stress_x: list[float] = []
        stress_y: list[float] = []
        self._stress_marker_timestamps_ms = []

        if hrv_rows:
            rmssd_vals = [float(r["rmssd"]) for r in hrv_rows]
            # Fall back to session mean when no calibration baseline is available.
            ref = baseline_rmssd if (baseline_rmssd and baseline_rmssd > 0) else (
                float(np.mean(rmssd_vals)) if rmssd_vals else None
            )
            if ref and ref > 0:
                stress_x = [float(r["timestamp"]) for r in hrv_rows]
                stress_delta = [(v - ref) / ref * 100.0 for v in rmssd_vals]
                stress_y = self._to_readable_percentages(stress_delta, invert=True)
                self._stress_marker_timestamps_ms = [
                    float(r["timestamp"]) * 1000.0
                    for r, v in zip(hrv_rows, rmssd_vals)
                    if v < ref * 0.60
                ]

        # ── Pupil Dilation (PDI) as % change ─────────────────────────
        pupil_rows = conn.execute(
            "SELECT timestamp, pdi FROM pupil_samples "
            "WHERE session_id = ? AND pdi IS NOT NULL ORDER BY timestamp",
            (session_id,),
        ).fetchall()

        pupil_x: list[float] = []
        pupil_y: list[float] = []

        if pupil_rows:
            pupil_x = [float(r["timestamp"]) for r in pupil_rows]
            pupil_raw = [float(r["pdi"]) for r in pupil_rows]
            pupil_y = self._to_readable_percentages(pupil_raw)

        if not stress_x and not pupil_x:
            self._show_empty_state(True)
            return

        self._show_empty_state(False)

        if stress_x:
            self._stress_curve.setData(stress_x, stress_y)

        if pupil_x:
            self._pupil_curve.setData(pupil_x, pupil_y)

        self._plot_item.autoRange()
        logger.info(
            "TimelineChart loaded session %d: %d RMSSD points, %d PDI points",
            session_id, len(stress_x), len(pupil_x),
        )

    def set_series_visibility(self, name: str, visible: bool) -> None:
        """Toggle visibility of a specific series.

        Args:
            name: ``"STRESS"`` or ``"WORKLOAD"``.
            visible: Whether the series should be shown.
        """
        if name == "STRESS":
            self._stress_curve.setVisible(visible)
        elif name == "WORKLOAD":
            self._pupil_curve.setVisible(visible)

    def set_playhead_ms(self, position_ms: float) -> None:
        """Move the persistent playhead line to a video timestamp.

        Args:
            position_ms: Video position in milliseconds.
        """
        seconds = position_ms / 1000.0
        self._playhead_line.setPos(seconds)
        self._playhead_label.setText(f"{seconds:.1f}s")
        self._playhead_label.setPos(seconds, 98.0)

    def get_stress_marker_timestamps_ms(self) -> list[float]:
        """Return severe stress-event timestamps in milliseconds."""
        return self._stress_marker_timestamps_ms.copy()

    def clear(self) -> None:
        """Reset the chart to an empty state."""
        self._stress_curve.setData([], [])
        self._pupil_curve.setData([], [])
        self._playhead_line.setPos(0)
        self._playhead_label.setText("0.0s")
        self._playhead_label.setPos(0, 98.0)
        self._stress_marker_timestamps_ms = []
        self._show_empty_state(True)

    # ------------------------------------------------------------------
    # Internal Logic
    # ------------------------------------------------------------------

    def _show_empty_state(self, empty: bool) -> None:
        """Toggle between the chart and an 'empty' placeholder message."""
        if empty:
            self._empty_label.show()
            self._plot_widget.hide()
        else:
            self._empty_label.hide()
            self._plot_widget.show()

    def _on_mouse_clicked(self, event) -> None:
        """Handle clicks on the plot to emit the timestamp."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.scenePos()
            if self._plot_item.sceneBoundingRect().contains(pos):
                mouse_point = self._plot_item.vb.mapSceneToView(pos)
                timestamp_s = mouse_point.x()
                self.set_playhead_ms(max(0.0, timestamp_s * 1000.0))
                self.timestamp_clicked.emit(max(0.0, timestamp_s * 1000.0))

    @staticmethod
    def _to_readable_percentages(values: list[float], invert: bool = False) -> list[float]:
        """Convert percent-change or z-score-like values to 0-100 percentages."""
        if not values:
            return []

        finite = [float(value) for value in values if np.isfinite(value)]
        if not finite:
            return [50.0 for _ in values]

        if any(abs(value) > 5.0 for value in finite):
            lo = min(finite)
            hi = max(finite)
            if hi == lo:
                readable = [50.0 for _ in values]
            else:
                readable = [((float(value) - lo) / (hi - lo)) * 100.0 for value in values]
                if invert:
                    readable = [100.0 - value for value in readable]
        else:
            readable = z_scores_to_percentages([float(value) for value in values], invert=invert)

        return [float(max(0.0, min(100.0, value))) for value in readable]

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Empty State Label ──────────────────────────────────────────
        import PyQt6.QtWidgets as QtWidgets
        self._empty_label = QtWidgets.QLabel("No timeline data available for this session.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._empty_label.setStyleSheet(
            f"color: {COLOR_FONT_MUTED}; font-size: {FONT_SMALL}px;"
        )
        layout.addWidget(self._empty_label)

        # ── Plot Widget ────────────────────────────────────────────────
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground(COLOR_CARD)
        self._plot_widget.setAntialiasing(True)
        self._plot_widget.showGrid(x=True, y=True, alpha=0.2)

        # Disable all mouse-driven panning, zooming, and wheel scrolling.
        self._plot_widget.setMouseEnabled(x=False, y=False)

        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.setLabel("bottom", "Time", units="s", color=COLOR_FONT_MUTED)
        self._plot_item.setLabel(
            "left", "Relative Intensity (%)", color=COLOR_FONT_MUTED
        )

        # Add a zero-baseline reference line.
        zero_line = pg.InfiniteLine(
            angle=0, pos=0, movable=False,
            pen=pg.mkPen(color=COLOR_BORDER, width=1, style=Qt.PenStyle.DashLine),
        )
        self._plot_item.addItem(zero_line, ignoreBounds=True)

        # Style axes.
        for ax in ("left", "bottom"):
            axis = self._plot_item.getAxis(ax)
            axis.setPen(pg.mkPen(color=COLOR_BORDER, width=1))
            axis.setTextPen(pg.mkPen(color=COLOR_FONT_MUTED))

        # ── Data curves ────────────────────────────────────────────────
        self._stress_curve = self._plot_item.plot(
            pen=pg.mkPen(color=COLOR_PRIMARY, width=2.5),
            name="Stress (RMSSD %)",
        )
        self._pupil_curve = self._plot_item.plot(
            pen=pg.mkPen(color=COLOR_WARNING, width=2.5),
            name="Pupil Dilation (%)",
        )

        # ── Persistent playhead line (follows video position) ──────────
        self._playhead_line = pg.InfiniteLine(
            angle=90, pos=0, movable=False,
            pen=pg.mkPen(color="#AAAAAA", width=2),
        )
        self._plot_item.addItem(self._playhead_line, ignoreBounds=True)
        self._playhead_label = pg.TextItem(
            text="0.0s",
            color=COLOR_FONT_MUTED,
            anchor=(0, 1),
        )
        self._playhead_label.setPos(0, 98.0)
        font = self.font()
        font.setBold(True)
        self._playhead_label.setFont(font)
        self._plot_item.addItem(self._playhead_label, ignoreBounds=True)

        # ── Hover hairline (follows mouse) ─────────────────────────────
        self._v_line = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(color=COLOR_BORDER, width=1, style=Qt.PenStyle.DotLine),
        )
        self._plot_item.addItem(self._v_line, ignoreBounds=True)

        def _mouse_moved(evt):
            pos = evt[0]
            if self._plot_item.sceneBoundingRect().contains(pos):
                mouse_point = self._plot_item.vb.mapSceneToView(pos)
                self._v_line.setPos(mouse_point.x())

        self._proxy = pg.SignalProxy(
            self._plot_item.scene().sigMouseMoved, rateLimit=60, slot=_mouse_moved
        )
        self._plot_item.scene().sigMouseClicked.connect(self._on_mouse_clicked)

        layout.addWidget(self._plot_widget)
        self._show_empty_state(True)
