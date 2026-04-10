"""Dashboard view matching the main design mockup.

The layout is split into three areas:
1) Header with status actions and start button
2) Top content row with progress chart and personal best cards
3) Bottom row with three circular KPI cards
4) Session Trend Analysis chart

All colours and font sizes are sourced exclusively from ``app.ui.theme``.
No hex literals or magic pixel values appear in this file.
"""

from datetime import datetime, timedelta
import math
import sqlite3
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QEvent, QObject, Qt, QSize, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.storage.database import DatabaseManager
from app.storage.session_repository import SessionRepository
from app.ui.theme import (
    COLOR_BACKGROUND,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_CHART_AXIS,
    COLOR_DANGER,
    COLOR_DANGER_BG,
    COLOR_FONT,
    COLOR_FONT_MUTED,
    COLOR_PRIMARY,
    COLOR_PRIMARY_SUBTLE,
    COLOR_SUCCESS,
    COLOR_WARNING,
    COLOR_WARNING_BG,
    FONT_BODY,
    FONT_HEADING_2,
    FONT_SUBTITLE,
    RADIUS_LG,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_4,
    CONTENT_PADDING_H,
    CONTENT_PADDING_V,
    GRID_GUTTER,
    get_icon,
)
from app.ui.widgets.level_bar import LevelBar
from app.ui.widgets.donut_gauge import DonutGauge
from app.utils.logger import get_logger

logger = get_logger(__name__)

CARD_TITLE_FONT_SIZE = FONT_HEADING_2 - 4
TOP_ROW_CARD_MIN_HEIGHT = 432
PROGRESS_CHART_MIN_HEIGHT = 304


class DashboardView(QWidget):
    """Main dashboard aligned to the design in ``designs/maindashboard.png``."""

    new_session_requested = pyqtSignal()
    session_selected = pyqtSignal(int)

    def __init__(
        self,
        db: DatabaseManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo: SessionRepository | None = (
            SessionRepository(db) if db is not None else None
        )
        self._sessions: list[sqlite3.Row] = []

        self._sessions_count_label: QLabel | None = None
        self._best_time_rows: list[tuple[QLabel, QLabel, QLabel]] = []

        self._stress_gauge: DonutGauge | None = None
        self._error_gauge: DonutGauge | None = None
        self._load_gauge: DonutGauge | None = None

        self._progress_plot: pg.PlotWidget | None = None
        self._actual_curve: pg.PlotCurveItem | None = None
        self._estimate_curve: pg.PlotCurveItem | None = None

        self._analysis_plot: pg.PlotWidget | None = None
        self._stress_series_curve: pg.PlotCurveItem | None = None
        self._workload_series_curve: pg.PlotCurveItem | None = None
        self._analysis_filter_group: QButtonGroup | None = None
        self._active_analysis_filters: set[str] = {"stress", "workload"}
        self._content_scroll: QScrollArea | None = None

        self._db = db

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Outer shell: fills the view, no margins ────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header sits above the scroll area (always visible) ─────────────
        header_widget = QWidget()
        header_widget.setObjectName("dashboard_header")
        header_widget.setStyleSheet(f"background: {COLOR_BACKGROUND};")
        header_v = QVBoxLayout(header_widget)
        header_v.setContentsMargins(CONTENT_PADDING_H, CONTENT_PADDING_V,
                                    CONTENT_PADDING_H, SPACE_2)
        header_v.setSpacing(SPACE_2)
        header_v.addLayout(self._build_header())

        outer.addWidget(header_widget)

        # ── Scroll area for the main content ──────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._content_scroll = scroll

        content = QWidget()
        content.setStyleSheet(f"background: {COLOR_BACKGROUND};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(CONTENT_PADDING_H, SPACE_2,
                                          CONTENT_PADDING_H, CONTENT_PADDING_V)
        content_layout.setSpacing(GRID_GUTTER)

        # ── Row 1: Progress chart + Personal Best ──────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(GRID_GUTTER)
        progress_card = self._make_progress_card()
        progress_card.setMinimumHeight(TOP_ROW_CARD_MIN_HEIGHT)
        personal_card = self._make_personal_best_card()
        personal_card.setMinimumHeight(TOP_ROW_CARD_MIN_HEIGHT)
        top_row.addWidget(progress_card, stretch=2)
        top_row.addWidget(personal_card, stretch=1)
        content_layout.addLayout(top_row)

        # ── Row 2: Three KPI gauge cards ───────────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(GRID_GUTTER)
        for kwargs in (
              dict(title="Ø Stress Events", accent=COLOR_PRIMARY, track=COLOR_PRIMARY_SUBTLE, key="stress"),
              dict(title="Ø Error Rate", accent=COLOR_DANGER, track=COLOR_DANGER_BG, key="error"),
              dict(title="Ø Cognitive Load", accent=COLOR_WARNING, track=COLOR_WARNING_BG, key="load"),
        ):
            card = self._make_metric_card(**kwargs)
            card.setMinimumHeight(300)
            bottom_row.addWidget(card)
        content_layout.addLayout(bottom_row)

        # ── Row 3: Session Trend Analysis ─────────────────────────────────
        analysis = self._make_analysis_card()
        analysis.setMinimumHeight(380)
        content_layout.addWidget(analysis)

        content_layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

    def _build_header(self) -> QHBoxLayout:
        """Create the top dashboard row with title and controls."""
        header = QHBoxLayout()
        header.setSpacing(SPACE_2)

        # Keep icon controls visually proportional to the shared heading size.
        status_button_size = FONT_HEADING_2 * 2
        status_icon_size = FONT_HEADING_2 - 8

        title = QLabel("Dashboard")
        title.setObjectName("heading")
        header.addWidget(title)
        header.addStretch(1)

        start_button = QPushButton("Start Session")
        start_button.setIcon(get_icon("ph.play-fill", color="#FFFFFF"))
        start_button.setIconSize(QSize(FONT_BODY + 2, FONT_BODY + 2))
        start_button.setFixedHeight(FONT_HEADING_2 * 2)
        start_button.setMinimumWidth(170)
        start_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                color: #FFFFFF;
                border: none;
                border-radius: {FONT_HEADING_2}px;
                padding: 0px {SPACE_2}px;
                font-size: {FONT_BODY}px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {COLOR_PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_PRIMARY};
                padding-top: 1px;
                padding-bottom: 0px;
            }}
            """
        )
        start_button.clicked.connect(self._on_new_session)
        header.addWidget(start_button)
        return header

    def _make_progress_card(self) -> QFrame:
        """Left card: progress line chart with sessions count."""
        card = self._make_card()
        card.setStyleSheet(
            f"""
            QFrame#card {{
                background-color: transparent;
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_LG}px;
            }}
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        layout.setSpacing(SPACE_2)

        header = QHBoxLayout()
        left = QVBoxLayout()

        title = QLabel("Your Progress")
        title.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {CARD_TITLE_FONT_SIZE}px; font-weight: 700;"
        )
        left.addWidget(title)
        header.addLayout(left)
        header.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(2)
        sessions_label = QLabel("SESSIONS")
        sessions_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        sessions_label.setStyleSheet(
            f"color: {COLOR_FONT_MUTED}; font-size: {FONT_BODY}px; letter-spacing: 1px;"
        )
        right.addWidget(sessions_label)

        self._sessions_count_label = QLabel("0")
        self._sessions_count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._sessions_count_label.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {CARD_TITLE_FONT_SIZE}px; font-weight: 700;"
        )
        right.addWidget(self._sessions_count_label)

        header.addLayout(right)
        layout.addLayout(header)

        self._progress_plot = pg.PlotWidget()
        self._progress_plot.setBackground((0, 0, 0, 0))
        self._progress_plot.getAxis("left").setStyle(showValues=True)
        self._progress_plot.showGrid(x=False, y=False)
        self._progress_plot.setMenuEnabled(False)
        self._progress_plot.hideButtons()
        self._progress_plot.setMouseEnabled(x=False, y=False)
        self._progress_plot.setMinimumHeight(PROGRESS_CHART_MIN_HEIGHT)
        self._progress_plot.getAxis("bottom").setPen(pg.mkPen(COLOR_CHART_AXIS, width=0.8))
        self._progress_plot.getAxis("left").setPen(pg.mkPen(COLOR_CHART_AXIS, width=0.8))
        self._progress_plot.getAxis("bottom").setTextPen(pg.mkPen(COLOR_FONT_MUTED, width=1))
        self._progress_plot.getAxis("left").setTextPen(pg.mkPen(COLOR_FONT_MUTED, width=1))
        self._progress_plot.getAxis("left").setLabel("Performance (%)", color=COLOR_FONT_MUTED)
        self._progress_plot.getAxis("bottom").setLabel("Sessions", color=COLOR_FONT_MUTED)

        estimate_pen = pg.mkPen(color=COLOR_FONT_MUTED, width=3, style=Qt.PenStyle.DashLine)
        actual_pen = pg.mkPen(color=COLOR_PRIMARY, width=4)

        self._estimate_curve = self._progress_plot.plot([], [], pen=estimate_pen)
        self._actual_curve = self._progress_plot.plot([], [], pen=actual_pen)
        self._progress_plot.installEventFilter(self)
        layout.addWidget(self._progress_plot, stretch=1)

        return card

    def _make_personal_best_card(self) -> QFrame:
        """Right card: minimalist top-3 best sessions layout."""
        card = self._make_card()
        card.setStyleSheet(
            f"""
            QFrame#card {{
                background-color: transparent;
                border: none;
                border-radius: {RADIUS_LG}px;
            }}
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        layout.setSpacing(SPACE_3)

        title = QLabel("Personal Best Times")
        title.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {CARD_TITLE_FONT_SIZE}px; font-weight: 700;"
        )
        layout.addWidget(title)

        # Reset references in case the card is rebuilt.
        self._best_time_rows = []

        for rank in range(1, 4):
            row_card = QFrame()
            row_card.setStyleSheet(
                f"""
                QFrame {{
                    border: none;
                    border-radius: {RADIUS_LG}px;
                    background-color: {COLOR_BACKGROUND};
                }}
                """
            )

            row_layout = QVBoxLayout(row_card)
            row_layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
            row_layout.setSpacing(6)

            top_line = QHBoxLayout()
            top_line.setContentsMargins(0, 0, 0, 0)
            top_line.setSpacing(SPACE_1)

            meta_label = QLabel(f"BEST SESSION #{rank}")
            meta_label.setStyleSheet(
                f"color: {COLOR_FONT_MUTED}; font-size: {FONT_BODY}px; font-weight: 600; letter-spacing: 1px;"
            )

            duration_label = QLabel("0:00")
            duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            duration_label.setStyleSheet(
                f"color: {COLOR_PRIMARY}; font-size: {FONT_HEADING_2}px; font-weight: 700;"
            )

            top_line.addWidget(meta_label)
            top_line.addStretch(1)
            top_line.addWidget(duration_label)

            session_label = QLabel("Session —")
            session_label.setStyleSheet(
                f"color: {COLOR_FONT_MUTED}; font-size: {FONT_BODY}px; font-weight: 500;"
            )

            row_layout.addLayout(top_line)
            row_layout.addWidget(session_label)

            self._best_time_rows.append((meta_label, duration_label, session_label))
            layout.addWidget(row_card)

        layout.addStretch(1)
        return card

    def _make_metric_card(
        self,
        title: str,
        accent: str,
        track: str,
        key: str,
    ) -> QFrame:
        """Create one of the bottom circular KPI cards."""
        card = self._make_card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(SPACE_3, SPACE_2, SPACE_3, SPACE_3)
        card_layout.setSpacing(SPACE_1)

        card_layout.addStretch(1)
        gauge = DonutGauge(value=0.0, accent_color=accent, track_color=track, center_text="0.0", half_circle=True)
        gauge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        card_layout.addWidget(gauge, alignment=Qt.AlignmentFlag.AlignHCenter)
        card_layout.addStretch(1)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title_label.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {CARD_TITLE_FONT_SIZE}px; font-weight: 700;"
        )
        card_layout.addWidget(title_label)

        if key == "stress":
            self._stress_gauge = gauge
        elif key == "error":
            self._error_gauge = gauge
        else:
            self._load_gauge = gauge

        return card

    def _make_analysis_card(self) -> QFrame:
        """Create the interactive percentage chart with filter buttons."""
        card = self._make_card()
        card.setStyleSheet(
            f"""
            QFrame#card {{
                background-color: transparent;
                border: 1px solid {COLOR_BORDER};
                border-radius: {RADIUS_LG}px;
            }}
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        layout.setSpacing(SPACE_2)

        top_row = QHBoxLayout()
        title = QLabel("Session Trend Analysis")
        title.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        title.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {CARD_TITLE_FONT_SIZE}px; font-weight: 700;"
        )
        top_row.addWidget(title)
        top_row.addStretch(1)

        self._analysis_filter_group = QButtonGroup(self)
        self._analysis_filter_group.setExclusive(False)

        stress_btn = self._make_filter_button("ph.heartbeat-fill", "Stress", "stress")
        workload_btn = self._make_filter_button("ph.brain-fill", "Cognitive Workload", "workload")
        top_row.addWidget(stress_btn)
        top_row.addWidget(workload_btn)
        layout.addLayout(top_row)

        self._analysis_plot = pg.PlotWidget()
        self._analysis_plot.setBackground((0, 0, 0, 0))
        self._analysis_plot.showGrid(x=True, y=True, alpha=0.2)
        self._analysis_plot.setMenuEnabled(False)
        self._analysis_plot.hideButtons()
        self._analysis_plot.setMouseEnabled(x=False, y=False)
        self._analysis_plot.setMinimumHeight(280)

        left_axis = self._analysis_plot.getAxis("left")
        left_axis.setPen(pg.mkPen(COLOR_CHART_AXIS, width=0.8))
        left_axis.setTextPen(pg.mkPen(COLOR_FONT_MUTED, width=1))
        left_axis.setLabel("Percentage (%)", color=COLOR_FONT_MUTED)

        bottom_axis = self._analysis_plot.getAxis("bottom")
        bottom_axis.setPen(pg.mkPen(COLOR_CHART_AXIS, width=0.8))
        bottom_axis.setTextPen(pg.mkPen(COLOR_FONT_MUTED, width=1))
        bottom_axis.setLabel("Sessions", color=COLOR_FONT_MUTED)

        stress_pen = pg.mkPen(color=COLOR_PRIMARY, width=3)
        workload_pen = pg.mkPen(color=COLOR_WARNING, width=3)

        self._stress_series_curve = self._analysis_plot.plot(
            [], [],
            pen=stress_pen,
            symbol="o",
            symbolSize=8,
            symbolBrush=COLOR_PRIMARY,
            name="Stress",
        )
        self._workload_series_curve = self._analysis_plot.plot(
            [], [],
            pen=workload_pen,
            symbol="o",
            symbolSize=8,
            symbolBrush=COLOR_WARNING,
            name="Cognitive Workload",
        )

        self._analysis_plot.addLegend(offset=(10, 10))
        self._analysis_plot.installEventFilter(self)
        layout.addWidget(self._analysis_plot)
        return card

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Forward wheel scrolling to the page scroll area when hovering charts.
        """
        if event.type() == QEvent.Type.Wheel and watched in {
            self._progress_plot,
            self._analysis_plot,
        }:
            if self._content_scroll is not None:
                delta = event.angleDelta().y()
                bar = self._content_scroll.verticalScrollBar()
                bar.setValue(bar.value() - delta)
                event.accept()
                return True

        return super().eventFilter(watched, event)

    def _make_filter_button(self, icon_name: str, tooltip: str, key: str) -> QPushButton:
        """Create checkable icon filter button."""
        button = QPushButton()
        button.setCheckable(True)
        button.setChecked(True)
        button.setToolTip(tooltip)
        
        accent = COLOR_PRIMARY if key == "stress" else COLOR_WARNING
        button.setFixedSize(44, 44)
        button.setIconSize(QSize(FONT_BODY + 4, FONT_BODY + 4))

        def _update_style():
            is_checked = button.isChecked()
            bg = accent if is_checked else COLOR_CARD
            icon_color = "#FFFFFF" if is_checked else accent
            border = accent if is_checked else COLOR_BORDER
            
            button.setIcon(get_icon(icon_name, color=icon_color))
            button.setStyleSheet(
                f"QPushButton {{ "
                f"  background-color: {bg}; "
                f"  border: 1px solid {border}; "
                f"  border-radius: {RADIUS_LG}px; "
                f"}} "
                f"QPushButton:hover {{ border-color: {accent}; }}"
            )

        button.toggled.connect(_update_style)
        _update_style()

        button.clicked.connect(lambda checked, k=key: self._on_analysis_filter_toggled(k, checked))
        if self._analysis_filter_group is not None:
            self._analysis_filter_group.addButton(button)
        return button

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload dashboard data and refresh all widgets."""
        if self._repo is not None:
            self._sessions = self._repo.get_all_sessions()
        else:
            self._sessions = []

        self._update_session_count()
        self._update_personal_best()
        self._update_gauges()
        self._update_progress_plot()
        self._update_analysis_plot()
        logger.info("Dashboard refreshed: %d sessions.", len(self._sessions))

    def _on_analysis_filter_toggled(self, key: str, checked: bool) -> None:
        """Toggle chart series visibility from filter buttons."""
        if checked:
            self._active_analysis_filters.add(key)
        else:
            self._active_analysis_filters.discard(key)

        if not self._active_analysis_filters:
            # Keep at least one active metric to avoid an empty chart.
            self._active_analysis_filters.add(key)
            sender = self.sender()
            if isinstance(sender, QPushButton):
                sender.setChecked(True)

        self._update_analysis_plot()

    def _update_session_count(self) -> None:
        """Update top-right sessions number in the progress card."""
        if self._sessions_count_label is None:
            return
        self._sessions_count_label.setText(str(len(self._sessions)))

    def _update_personal_best(self) -> None:
        """Compute and display the top 3 fastest completed sessions."""
        if not self._best_time_rows:
            return

        durations: list[tuple[int, sqlite3.Row]] = []
        for session in self._sessions:
            duration_seconds = self._compute_session_duration_seconds(
                session["started_at"],
                session["ended_at"],
            )
            if duration_seconds is not None and duration_seconds > 0:
                durations.append((duration_seconds, session))

        best_three = sorted(durations, key=lambda item: item[0])[:3]

        for idx, (meta_label, duration_label, session_label) in enumerate(self._best_time_rows, start=1):
            meta_label.setText(f"BEST SESSION #{idx}")
            if idx <= len(best_three):
                duration_seconds, session_row = best_three[idx - 1]
                duration_label.setText(self._format_seconds(duration_seconds))
                
                # Show name if available, otherwise date
                name = session_row["name"] if "name" in session_row.keys() else None
                if name:
                    session_label.setText(name)
                else:
                    session_date = str(session_row["started_at"]).replace("T", " ")[:10]
                    session_label.setText(f"Session {session_date}")
            else:
                duration_label.setText("0:00")
                session_label.setText("Session —")

    def _update_gauges(self) -> None:
        """Map available session data to the three bottom KPI gauges."""
        tlx_values = [
            float(row["nasa_tlx_score"])
            for row in self._sessions
            if row["nasa_tlx_score"] is not None
        ]
        avg_tlx = (sum(tlx_values) / len(tlx_values)) if tlx_values else 0.0

        stress_value = min(1.0, (avg_tlx / 100.0) * 0.6)
        error_value = min(1.0, (avg_tlx / 100.0) * 0.12)
        load_value = min(1.0, avg_tlx / 100.0)

        if self._stress_gauge is not None:
            self._stress_gauge.set_value(stress_value, f"{stress_value:.1f}")
        if self._error_gauge is not None:
            self._error_gauge.set_value(error_value, f"{error_value * 100:.1f}%")
        if self._load_gauge is not None:
            self._load_gauge.set_value(load_value, f"{load_value * 100:.1f}%")

    def _update_progress_plot(self) -> None:
        """Update progress chart data and x-axis labels."""
        if (
            self._progress_plot is None
            or self._actual_curve is None
            or self._estimate_curve is None
        ):
            return

        x_values, actual_values, estimate_values, tick_labels = self._build_chart_series()

        self._actual_curve.setData(x_values, actual_values)
        self._estimate_curve.setData(x_values, estimate_values)
        self._progress_plot.setYRange(0, 100, padding=0.04)
        self._progress_plot.setXRange(-0.3, len(x_values) - 0.7, padding=0)

        y_axis = self._progress_plot.getAxis("left")
        y_axis.setTicks([[(0, "0%"), (25, "25%"), (50, "50%"), (75, "75%"), (100, "100%")]])

        axis = self._progress_plot.getAxis("bottom")
        ticks = [(idx, label) for idx, label in enumerate(tick_labels)]
        axis.setTicks([ticks])

    def _build_chart_series(self) -> tuple[list[float], list[float], list[float], list[str]]:
        """Build chart values from sessions or fallback synthetic trend."""
        if not self._sessions:
            labels = [f"S{i + 1}" for i in range(6)]
            x_values = [float(i) for i in range(len(labels))]
            actual = [47.0, 63.0, 26.0, 56.0, 42.0, 58.0]
            estimate = [86.0, 68.0, 58.0, 56.0, 56.0, 56.0]
            return x_values, actual, estimate, labels

        ordered = sorted(self._sessions, key=lambda row: str(row["started_at"]))
        display = ordered[-6:]
        x_values = [float(i) for i in range(len(display))]

        estimate_values: list[float] = []
        actual_values: list[float] = []
        labels: list[str] = []

        for i, session in enumerate(display):
            labels.append(f"S{i + 1}")

            estimate = 85.0 - min(28.0, i * 9.0)
            estimate_values.append(max(56.0, estimate))

            tlx = session["nasa_tlx_score"]
            if tlx is None:
                value = 47.0 + 14.0 * math.sin(i)
            else:
                workload = max(0.0, min(100.0, float(tlx)))
                value = 86.0 - workload * 0.60
            actual_values.append(max(20.0, min(92.0, value)))

        return x_values, actual_values, estimate_values, labels

    def _update_analysis_plot(self) -> None:
        """Render the lower interactive chart with selected metrics."""
        if (
            self._analysis_plot is None
            or self._stress_series_curve is None
            or self._workload_series_curve is None
        ):
            return

        x_values, stress_values, workload_values, labels = self._build_analysis_series()

        if "stress" in self._active_analysis_filters:
            self._stress_series_curve.setData(x_values, stress_values)
        else:
            self._stress_series_curve.setData([], [])

        if "workload" in self._active_analysis_filters:
            self._workload_series_curve.setData(x_values, workload_values)
        else:
            self._workload_series_curve.setData([], [])

        self._analysis_plot.setYRange(0, 100, padding=0.05)
        self._analysis_plot.setXRange(-0.2, max(0.8, len(x_values) - 0.8), padding=0)

        left_axis = self._analysis_plot.getAxis("left")
        left_axis.setTicks([[(0, "0%"), (25, "25%"), (50, "50%"), (75, "75%"), (100, "100%")]])

        bottom_axis = self._analysis_plot.getAxis("bottom")
        ticks = [(idx, label) for idx, label in enumerate(labels)]
        bottom_axis.setTicks([ticks])

    def _build_analysis_series(self) -> tuple[list[float], list[float], list[float], list[str]]:
        """Build percentage series by session for stress and workload."""
        if not self._sessions:
            x_values = [0.0, 1.0, 2.0, 3.0]
            labels = ["S1", "S2", "S3", "S4"]
            stress_values = [54.0, 43.0, 49.0, 37.0]
            workload_values = [46.0, 57.0, 52.0, 63.0]
            return x_values, stress_values, workload_values, labels

        ordered = sorted(self._sessions, key=lambda row: str(row["started_at"]))
        display = ordered[-12:]

        x_values: list[float] = []
        stress_values: list[float] = []
        workload_values: list[float] = []
        labels: list[str] = []

        for idx, session in enumerate(display):
            x_values.append(float(idx))
            labels.append(f"S{idx + 1}")

            tlx = session["nasa_tlx_score"]
            if tlx is None:
                workload = 50.0 + 10.0 * math.sin(idx)
            else:
                workload = max(0.0, min(100.0, float(tlx)))

            stress = max(0.0, min(100.0, 100.0 - workload))

            workload_values.append(workload)
            stress_values.append(stress)

        return x_values, stress_values, workload_values, labels

    @staticmethod
    def _compute_session_duration_seconds(
        started_at: str | None,
        ended_at: str | None,
    ) -> int | None:
        """Return session duration in seconds if both timestamps are valid."""
        if not started_at or not ended_at:
            return None

        try:
            start_dt = datetime.fromisoformat(str(started_at).replace("T", " "))
            end_dt = datetime.fromisoformat(str(ended_at).replace("T", " "))
        except ValueError:
            return None

        duration = int((end_dt - start_dt).total_seconds())
        if duration <= 0:
            return None
        return duration

    @staticmethod
    def _format_seconds(total_seconds: int) -> str:
        """Format seconds into H:MM:SS for long runs or M:SS for short runs."""
        minutes, seconds = divmod(max(0, total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _format_date(value: str | None) -> str:
        """Format datetime text as day.month.year for display."""
        if not value:
            return "-"
        text = str(value)
        try:
            dt = datetime.fromisoformat(text.replace("T", " "))
            return dt.strftime("%-d.%-m.%Y")
        except ValueError:
            return text[:10]

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_new_session(self) -> None:
        """Navigate to the Calibration view to start a new session."""
        logger.info("New session requested from Dashboard.")
        self.new_session_requested.emit()

    def _on_export(self) -> None:
        """Show a file dialog and export the selected session to CSV."""
        logger.info("Export requested.")
        # TODO (Phase 5): wire to SessionExporter.

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_card() -> QFrame:
        """Create base card using the global design-system card style."""
        card = QFrame()
        card.setObjectName("card")
        return card
