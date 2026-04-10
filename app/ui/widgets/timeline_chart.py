"""TimelineChart — pyqtgraph-based session analysis chart.

Displays Stress (RMSSD) and Cognitive Workload (CLI) over the course of a
session, with a dual Y-axis and click-to-seek interaction.
"""

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.storage.database import DatabaseManager
from app.ui.theme import (
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_FONT,
    COLOR_FONT_MUTED,
    COLOR_PRIMARY,
    COLOR_WARNING,
    COLOR_CARD,
    FONT_SMALL,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TimelineChart(QWidget):
    """Interactive session analysis chart with Stress and CLI series.

    Signals:
        timestamp_clicked (float): Emitted when the user clicks on the chart,
                                   representing milliseconds from session start.
    """

    timestamp_clicked = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._build_ui()

    def load_session(self, db: DatabaseManager, session_id: int) -> None:
        """Query the database and plot series for the given session.

        Args:
            db: Database manager instance.
            session_id: ID of the session to load.
        """
        self.clear()

        conn = db.get_connection()
        
        # ── Stress (RMSSD) ─────────────────────────────────────────────
        hrv_rows = conn.execute(
            "SELECT timestamp, rmssd FROM hrv_samples WHERE session_id = ? ORDER BY timestamp",
            (session_id,)
        ).fetchall()
        
        stress_x = [row["timestamp"] for row in hrv_rows if row["rmssd"] is not None]
        stress_y = [row["rmssd"] for row in hrv_rows if row["rmssd"] is not None]

        # ── Cognitive Workload (CLI) ───────────────────────────────────
        cli_rows = conn.execute(
            "SELECT timestamp, cli FROM cli_samples WHERE session_id = ? ORDER BY timestamp",
            (session_id,)
        ).fetchall()
        
        cli_x = [row["timestamp"] for row in cli_rows]
        cli_y = [row["cli"] for row in cli_rows]

        if not stress_x and not cli_x:
            self._show_empty_state(True)
            return

        self._show_empty_state(False)

        # Plot Stress (Left Axis)
        if stress_x:
            self._stress_curve.setData(stress_x, stress_y)

        # Plot CLI (Right Axis)
        if cli_x:
            self._cli_curve.setData(cli_x, cli_y)

        # Auto-scale
        self._plot_item.autoRange()
        logger.info("TimelineChart loaded session %d: %d Stress, %d CLI points",
                    session_id, len(stress_x), len(cli_x))

    def set_series_visibility(self, name: str, visible: bool) -> None:
        """Toggle visibility of a specific series."""
        if name == "STRESS":
            self._stress_curve.setVisible(visible)
        elif name == "WORKLOAD":
            self._cli_curve.setVisible(visible)

    def clear(self) -> None:
        """Reset the chart to an empty state."""
        self._stress_curve.setData([], [])
        self._cli_curve.setData([], [])
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
                # Emit in milliseconds
                self.timestamp_clicked.emit(max(0.0, timestamp_s * 1000.0))

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Empty State Label ──────────────────────────────────────
        import PyQt6.QtWidgets as QtWidgets
        self._empty_label = QtWidgets.QLabel("No timeline data available for this session.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._empty_label.setStyleSheet(
            f"color: {COLOR_FONT_MUTED}; font-size: {FONT_SMALL}px;"
        )
        layout.addWidget(self._empty_label)

        # ── Plot Widget ────────────────────────────────────────────
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground(COLOR_CARD)
        self._plot_widget.setAntialiasing(True)
        self._plot_widget.showGrid(x=True, y=True, alpha=0.2)
        
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.setLabel("bottom", "Time", units="s", color=COLOR_FONT_MUTED)
        self._plot_item.setLabel("left", "Stress (RMSSD)", units="ms", color=COLOR_PRIMARY)
        
        # Configure axes style
        for ax in ["left", "bottom"]:
            axis = self._plot_item.getAxis(ax)
            axis.setPen(pg.mkPen(color=COLOR_BORDER, width=1))
            axis.setTextPen(pg.mkPen(color=COLOR_FONT_MUTED))

        # Create Right Axis for CLI
        self._cli_view = pg.ViewBox()
        self._plot_item.scene().addItem(self._cli_view)
        self._plot_item.getAxis("right").linkToView(self._cli_view)
        self._cli_view.setXLink(self._plot_item.vb)
        self._plot_item.getAxis("right").setLabel("Cognitive Workload (CLI)", color=COLOR_WARNING)
        self._plot_item.showAxis("right")

        def update_views():
            self._cli_view.setGeometry(self._plot_item.vb.sceneBoundingRect())
            self._cli_view.linkedViewChanged(self._plot_item.vb, self._cli_view.XAxis)

        self._plot_item.vb.sigResized.connect(update_views)

        # Style right axis
        right_axis = self._plot_item.getAxis("right")
        right_axis.setPen(pg.mkPen(color=COLOR_BORDER, width=1))
        right_axis.setTextPen(pg.mkPen(color=COLOR_FONT_MUTED))

        # Create curves
        self._stress_curve = self._plot_item.plot(
            pen=pg.mkPen(color=COLOR_PRIMARY, width=2.5),
            name="Stress"
        )
        
        self._cli_curve = pg.PlotDataItem(
            pen=pg.mkPen(color=COLOR_WARNING, width=2.5),
            name="CLI"
        )
        self._cli_view.addItem(self._cli_curve)

        # Hairline cursor
        self._v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color=COLOR_BORDER, width=1))
        self._plot_item.addItem(self._v_line, ignoreBounds=True)

        def mouse_moved(evt):
            pos = evt[0]
            if self._plot_item.sceneBoundingRect().contains(pos):
                mouse_point = self._plot_item.vb.mapSceneToView(pos)
                self._v_line.setPos(mouse_point.x())

        self._proxy = pg.SignalProxy(self._plot_item.scene().sigMouseMoved, rateLimit=60, slot=mouse_moved)
        self._plot_item.scene().sigMouseClicked.connect(self._on_mouse_clicked)

        layout.addWidget(self._plot_widget)
        self._show_empty_state(True)
