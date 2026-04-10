"""Live feedback view — real-time biofeedback during a training session.

Layout & user flow
------------------
The user arrives here directly from CalibrationView (after baseline is done
and MainWindow calls ``session_manager.start_session()``).  There is no
"Start Session" button — the session is already running on arrival.

Toolbar (always visible):
    ● LIVE SESSION  |  [Biofeedback]  [Camera + Bio]  |  00:00  PAUSE  END SESSION

Mode Biofeedback (default, index 0 in the mode stack):
    Top row: CORE STATE SYNTHESIS (circular gauges, 40 %) +
             SYNCHRONIZED STATE TIMELINE (live chart, 60 %)
    Bottom row: 4 metric cards — PUPIL DILATION · HRV (RMSSD) · TASK SPEED · ACCURACY

Mode Camera + Bio (index 1 in the mode stack):
    Full-screen camera feed with a minimal recording control bar.

Dependency injection: call ``bind_session_manager()`` once after construction.
"""

import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QSize
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import (
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_DANGER,
    COLOR_FONT,
    COLOR_FONT_MUTED,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_SUBTLE,
    COLOR_SUCCESS,
    COLOR_WARNING,
    FONT_CAPTION,
    FONT_HEADING_2,
    FONT_METRIC_XL,
    FONT_SMALL,
    FONT_SUBTITLE,
    FONT_TITLE,
    FONT_DISPLAY,
    RADIUS_LG,
    SPACE_4,
    SPACE_3,
    SPACE_2,
    SPACE_1,
    CHART_HEIGHT_TIMELINE,
    get_icon,
)

# Sensor status badge colours
_SENSOR_CONNECTED_BG    = COLOR_SUCCESS   # #22C55E green fill
_SENSOR_DISCONNECTED_BG = "#E5E7EB"       # light gray fill
from app.ui.widgets.donut_gauge import DonutGauge
from app.ui.widgets.live_chart import LiveChart
from app.ui.widgets.metric_card import MetricCard
from app.ui.widgets.video_feed import VideoFeed
from app.utils.config import CAMERA_INDEX, CLI_THRESHOLD_HIGH, CLI_THRESHOLD_LOW, USE_EYE_TRACKER
from app.utils.config import VIDEO_RECORDINGS_DIR
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Chart trace colours (from design.md)
_COLOR_RMSSD = "#22C55E"
_COLOR_PDI   = "#A78BFA"
_COLOR_CLI   = "#3B579F"

# Mode indices in the QStackedWidget
_MODE_BIOFEEDBACK = 0   # data-only (default)
_MODE_CAMERA      = 1   # camera + data overlay


class ModeSwitcher(QWidget):
    """Integrated mode switcher with icons and a sliding highlight.
    
    Shows both 'Biofeedback' and 'Camera' positions as distinct targets
    to feel more like a physical switch between two modes than a binary toggle.
    """
    toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked: bool = False
        
        # Theme properties
        self._active_icon_color = "#FFFFFF"
        self._inactive_icon_color = COLOR_PRIMARY
        
        self.setFixedSize(100, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Background track
        self._track = QFrame(self)
        self._track.setGeometry(0, 0, 100, 36)
        
        # Static Icons (Visible when not covered by thumb)
        self._bio_icon = QLabel(self)
        self._bio_icon.move(12, 9)
        
        self._cam_icon = QLabel(self)
        self._cam_icon.move(70, 9)

        # Sliding thumb
        self._thumb = QFrame(self)
        self._thumb.setFixedSize(44, 28)
        
        # Active icon on top of the thumb
        self._active_icon = QLabel(self._thumb)
        self._active_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._active_icon.setFixedSize(44, 28)
        
        # Set default theme (will be updated by set_theme)
        self.set_theme(False)
        self._update_visuals()

    def isChecked(self) -> bool:
        """Return current checked state (True = Camera mode)."""
        return self._checked

    def setChecked(self, checked: bool) -> None:
        """Set checked state and update visuals without emitting signal."""
        if self._checked != checked:
            self._checked = checked
            self._update_visuals()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            # Click detection: if on left half, set bio; if on right half, set cam
            new_state = event.pos().x() > self.width() // 2
            if new_state != self._checked:
                self._checked = new_state
                self._update_visuals()
                self.toggled.emit(self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def _update_visuals(self) -> None:
        """Move the thumb and update icon visibility/color."""
        if self._checked:
            self._thumb.move(52, 4)
            self._active_icon.setPixmap(get_icon("ph.video-camera", color=self._active_icon_color).pixmap(18, 18))
            self._cam_icon.hide()
            self._bio_icon.show()
        else:
            self._thumb.move(4, 4)
            self._active_icon.setPixmap(get_icon("ph.activity", color=self._active_icon_color).pixmap(18, 18))
            self._bio_icon.hide()
            self._cam_icon.show()

    def set_theme(self, is_video: bool) -> None:
        """Update track and icon colors for the current theme.

        is_video: True if white theme (for camera), False for standard theme.
        """
        if is_video:
            # Video View Style: White track, Blue thumb, White active icon, Blue inactive icons
            track_bg = "#FFFFFF"
            track_border = "transparent"
            thumb_bg = COLOR_PRIMARY
            self._active_icon_color = "#FFFFFF"
            self._inactive_icon_color = COLOR_PRIMARY
        else:
            # Dashboard View Style: Light track, Blue thumb, White active icon, Muted inactive icons
            track_bg = COLOR_PRIMARY_SUBTLE
            track_border = COLOR_BORDER
            thumb_bg = COLOR_PRIMARY
            self._active_icon_color = "#FFFFFF"
            self._inactive_icon_color = COLOR_FONT_MUTED

        self._track.setStyleSheet(
            f"background-color: {track_bg}; border: 1px solid {track_border}; border-radius: 18px;"
        )
        self._bio_icon.setPixmap(get_icon("ph.activity", color=self._inactive_icon_color).pixmap(18, 18))
        self._cam_icon.setPixmap(get_icon("ph.video-camera", color=self._inactive_icon_color).pixmap(18, 18))
        self._thumb.setStyleSheet(f"background-color: {thumb_bg}; border-radius: 14px;")
        
        self._update_visuals()



class LiveView(QWidget):
    """Real-time biofeedback view during an active training session.

    This view does NOT own a ``SessionManager``.  After construction,
    ``MainWindow`` calls ``bind_session_manager()`` to wire signals.

    The session always starts externally (via ``MainWindow._on_proceed_to_live``).
    The only session control available here is END SESSION.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_active: bool = False
        self._elapsed_seconds: int = 0
        self._session_manager = None
        self._session_id: int | None = None
        self._recording_path: Path | None = None
        self._current_camera_index: int = CAMERA_INDEX
        self._has_pupil_baseline: bool = False  # True once calibration sets a baseline
        self._pdi_min_seen: float = float("inf")
        self._pdi_max_seen: float = float("-inf")

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)

        self._build_ui()
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """Add keyboard shortcuts for easy view and source switching."""
        # Toggle between Biofeedback and Camera + Bio modes (Hotkey: C)
        self._mode_toggle_shortcut = QShortcut(QKeySequence("C"), self)
        self._mode_toggle_shortcut.activated.connect(
            self._toggle_mode_via_shortcut
        )
        
        # Switch camera source (Hotkey: S)
        self._source_toggle_shortcut = QShortcut(QKeySequence("S"), self)
        self._source_toggle_shortcut.activated.connect(self._on_switch_camera)

    def _toggle_mode_via_shortcut(self) -> None:
        """Cycle mode when shortcut is pressed."""
        new_state = not self._mode_switcher.isChecked()
        self._mode_switcher.setChecked(new_state)
        self._set_mode(_MODE_CAMERA if new_state else _MODE_BIOFEEDBACK)

    # ------------------------------------------------------------------
    # SessionManager binding (called by MainWindow after construction)
    # ------------------------------------------------------------------

    def bind_session_manager(self, session_manager) -> None:
        """Inject the SessionManager and wire its signals to this view.

        Args:
            session_manager: A :class:`~app.core.session.SessionManager` instance.
        """
        self._session_manager = session_manager
        session_manager.rmssd_updated.connect(self.on_rmssd_updated)
        session_manager.pdi_updated.connect(self.on_pdi_updated)
        session_manager.cli_updated.connect(self.on_cli_updated)
        session_manager.bpm_updated.connect(self.on_bpm_updated)
        session_manager.hrv_connection_changed.connect(self._on_hrv_connection_changed)
        session_manager.eye_connection_changed.connect(self._on_eye_connection_changed)
        session_manager.calibration_complete.connect(self._on_calibration_complete)
        session_manager.session_started.connect(self._on_session_started)
        session_manager.session_ended.connect(self._on_session_ended)
        session_manager.session_paused.connect(self._on_session_paused)
        session_manager.session_resumed.connect(self._on_session_resumed)

        logger.info("LiveView bound to SessionManager.")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Layered layout: Toolbar floats over the Mode Stack
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Base: Mode stack
        self._mode_stack = QStackedWidget()
        self._mode_stack.addWidget(self._build_mode_biofeedback())  # index 0
        self._mode_stack.addWidget(self._build_mode_camera())       # index 1
        self._mode_stack.setCurrentIndex(_MODE_BIOFEEDBACK)
        layout.addWidget(self._mode_stack, 0, 0)

        # Overlay: Top toolbar
        toolbar_container = QWidget()
        toolbar_container.setObjectName("live_toolbar")
        toolbar_container.setFixedHeight(80)
        toolbar_container.setStyleSheet(
            f"#live_toolbar {{ background: transparent; border: none; }}"
        )
        toolbar_container.setLayout(self._build_toolbar())
        layout.addWidget(toolbar_container, 0, 0, Qt.AlignmentFlag.AlignTop)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(SPACE_3, 0, SPACE_3, 0)
        row.setSpacing(SPACE_2)

        # ── Left: title + sensor status badges ────────────────────────────
        self._live_label = QLabel("LIVE SESSION")
        self._live_label.setStyleSheet(
            f"font-size: {FONT_SMALL}px; font-weight: 700; letter-spacing: 1.5px;"
        )
        row.addWidget(self._live_label)

        row.addSpacing(SPACE_2)

        self._ecg_badge = self._make_status_badge("ph.heartbeat-fill")
        row.addWidget(self._ecg_badge)

        self._eye_badge = self._make_status_badge("ph.eye-fill")
        row.addWidget(self._eye_badge)

        row.addSpacing(SPACE_1)

        row.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        # ── Center: dashboard/camera toggle switch ───────────────────────
        self._mode_switcher = ModeSwitcher(self)
        self._mode_switcher.toggled.connect(self._on_mode_switch_toggled)
        row.addWidget(self._mode_switcher)

        row.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        # ── Right: session controls ─────────────────────────────────────
        # Pause button (fully round)
        self._pause_btn = QPushButton()
        self._pause_btn.setIconSize(QSize(18, 18))
        self._pause_btn.setFixedSize(44, 44)
        self._pause_btn.setCheckable(True)
        self._pause_btn.clicked.connect(self._toggle_pause)
        row.addWidget(self._pause_btn)

        # END SESSION button
        self._end_btn = QPushButton(" END SESSION")
        self._end_btn.setIconSize(QSize(16, 16))
        self._end_btn.setFixedHeight(40)
        self._end_btn.setMinimumWidth(130)
        self._end_btn.clicked.connect(self._end_session)
        row.addWidget(self._end_btn)

        # Initialize with bio theme (dark blue)
        self._update_toolbar_theme(is_video=False)

        return row

    def _update_toolbar_theme(self, is_video: bool) -> None:
        """Update toolbar colors based on current mode.
        
        is_video: True if Camera view (white), False if Bio view (dark blue).
        """
        if is_video:
            text_color = "#FFFFFF"
            border_color = "rgba(255, 255, 255, 0.4)"
            hover_bg = "rgba(255, 255, 255, 0.1)"
            btn_bg = "#FFFFFF"
            btn_text = COLOR_PRIMARY
        else:
            text_color = COLOR_PRIMARY
            border_color = COLOR_BORDER
            hover_bg = COLOR_PRIMARY_SUBTLE
            btn_bg = COLOR_PRIMARY
            btn_text = "#FFFFFF"

        # 1. Update Title
        self._live_label.setStyleSheet(
            f"color: {text_color}; font-size: {FONT_SMALL}px; "
            "font-weight: 700; letter-spacing: 1.5px;"
        )

        # 2. Update Mode Switcher
        self._mode_switcher.set_theme(is_video)

        # 3. Update Pause Button
        if is_video:
            pause_bg = "#FFFFFF"
            pause_icon_color = COLOR_PRIMARY
            pause_border = "none"
            pause_hover = COLOR_PRIMARY_SUBTLE
            pause_checked_bg = COLOR_PRIMARY
            pause_checked_icon = "#FFFFFF"
        else:
            pause_bg = "transparent"
            pause_icon_color = COLOR_PRIMARY
            pause_border = f"2px solid {COLOR_BORDER}"
            pause_hover = COLOR_PRIMARY_SUBTLE
            pause_checked_bg = COLOR_WARNING
            pause_checked_icon = "#FFFFFF"

        is_paused = self._pause_btn.isChecked()
        current_icon = "ph.play-fill" if is_paused else "ph.pause-fill"
        current_color = pause_checked_icon if is_paused else pause_icon_color
        
        self._pause_btn.setIcon(get_icon(current_icon, color=current_color))
        self._pause_btn.setStyleSheet(
            f"QPushButton {{ background-color: {pause_bg}; border: {pause_border}; border-radius: 22px; outline: none; }}"
            f"QPushButton:hover {{ background-color: {pause_hover}; }}"
            f"QPushButton:checked {{ background-color: {pause_checked_bg}; border-color: {pause_checked_bg}; }}"
        )

        # 4. Update End Button
        self._end_btn.setIcon(get_icon("ph.stop-circle-fill", color=btn_text))
        self._end_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {btn_text};
                border: none;
                border-radius: 20px;
                padding: 0 18px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {hover_bg if not is_video else COLOR_PRIMARY_SUBTLE};
            }}
            """
        )

    def _on_mode_switch_toggled(self, checked: bool) -> None:
        """Switch view mode when the center toggle changes."""
        self._set_mode(_MODE_CAMERA if checked else _MODE_BIOFEEDBACK)

    # ------------------------------------------------------------------
    # Mode Biofeedback — data-only (default)
    # ------------------------------------------------------------------

    def _build_mode_biofeedback(self) -> QWidget:
        """Build the Biofeedback (data-only) mode layout.

        Top row:
            - CORE STATE SYNTHESIS: two circular/gauge metric cards (40 %)
            - SYNCHRONIZED STATE TIMELINE: scrolling line chart (60 %)
        Bottom row:
            - 4 metric cards: PUPIL DILATION · HRV (RMSSD) · TASK SPEED · ACCURACY
        """
        widget = QWidget()
        outer = QVBoxLayout(widget)
        # Add 80px margin to top to clear the floating toolbar
        outer.setContentsMargins(SPACE_3, 80, SPACE_3, SPACE_2)
        outer.setSpacing(SPACE_2)

        # ── Top row (Single Card) ───────────────────────────────────────
        top_card = self._make_card()
        top_row_layout = QHBoxLayout(top_card)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(0)

        # Left: Core State Synthesis panel (2/5 width)
        core_widget = QWidget()
        core_layout = QVBoxLayout(core_widget)
        core_layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        core_layout.setSpacing(SPACE_1)

        core_header = QHBoxLayout()
        core_title = QLabel("CORE STATE SYNTHESIS")
        core_title.setStyleSheet(
            f"color: {COLOR_FONT_MUTED}; font-size: {FONT_CAPTION}px; "
            "font-weight: 700; letter-spacing: 2px;"
        )
        core_header.addWidget(core_title)
        core_header.addStretch()
        info_icon = QLabel()
        info_icon.setPixmap(get_icon("ph.info-fill", color=COLOR_FONT_MUTED).pixmap(14, 14))
        core_header.addWidget(info_icon)
        core_layout.addLayout(core_header)

        gauges_col = QVBoxLayout()
        gauges_col.setSpacing(SPACE_2)

        # Cognitive Workload Gauge
        self._workload_gauge, workload_panel = self._make_gauge_panel(
            title="COGNITIVE WORKLOAD",
            accent=COLOR_PRIMARY,
            track=COLOR_PRIMARY_SUBTLE
        )
        gauges_col.addWidget(workload_panel)

        # Physical Stress Gauge
        self._stress_gauge, stress_panel = self._make_gauge_panel(
            title="PHYSICAL STRESS",
            accent=_COLOR_CLI,
            track="#E5E7EB"
        )
        gauges_col.addWidget(stress_panel)
        core_layout.addLayout(gauges_col, stretch=1)

        top_row_layout.addWidget(core_widget, stretch=1)

        # Vertical Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {COLOR_BORDER};")
        top_row_layout.addWidget(divider)

        # Right: Synchronized State Timeline panel (3/5 width)
        timeline_widget = QWidget()
        timeline_layout = QVBoxLayout(timeline_widget)
        timeline_layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        timeline_layout.setSpacing(SPACE_1)

        tl_header = QHBoxLayout()
        tl_title = QLabel("SYNCHRONIZED STATE TIMELINE (REAL-TIME)")
        tl_title.setStyleSheet(
            f"color: {COLOR_FONT_MUTED}; font-size: {FONT_CAPTION}px; "
            "font-weight: 700; letter-spacing: 2px;"
        )
        tl_header.addWidget(tl_title)
        tl_header.addSpacing(SPACE_2)

        # Window duration selector buttons
        self._window_group = QButtonGroup(self)
        self._window_group.setExclusive(True)
        
        for label, seconds in [("1m", 60), ("3m", 180), ("5m", 300)]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedSize(42, 24)
            btn.setChecked(seconds == 180) # Default
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {COLOR_BORDER};
                    border-radius: 4px;
                    color: {COLOR_FONT_MUTED};
                    font-size: 10px;
                    font-weight: 700;
                    padding: 0;
                }}
                QPushButton:checked {{
                    background: {COLOR_PRIMARY};
                    border-color: {COLOR_PRIMARY};
                    color: #FFFFFF;
                }}
                QPushButton:hover:!checked {{
                    border-color: {COLOR_PRIMARY};
                }}
                """
            )
            btn.clicked.connect(lambda _, s=seconds: self._timeline_chart.set_window_seconds(s))
            self._window_group.addButton(btn)
            tl_header.addWidget(btn)

        tl_header.addStretch()

        # Legend dots
        for label_text, color in [("WORKLOAD", _COLOR_RMSSD), ("STRESS", _COLOR_CLI)]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 9px;")
            tl_header.addWidget(dot)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"color: {COLOR_FONT_MUTED}; font-size: {FONT_CAPTION}px; font-weight: 600;"
            )
            tl_header.addWidget(lbl)

        timeline_layout.addLayout(tl_header)

        self._timeline_chart = LiveChart(
            series=["WORKLOAD", "STRESS"],
            colours=[_COLOR_RMSSD, _COLOR_CLI],
            y_label="INDEX (%)",
            y_range=(0.0, 1.0),
            window_seconds=180,
            transparent=True,
        )
        self._timeline_chart.setMinimumHeight(CHART_HEIGHT_TIMELINE)
        timeline_layout.addWidget(self._timeline_chart, stretch=1)

        top_row_layout.addWidget(timeline_widget, stretch=2)
        outer.addWidget(top_card, stretch=1)

        # ── Bottom row: 4 metric cards ──────────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(SPACE_2)

        self._pupil_card = MetricCard(
            name="PUPIL DILATION",
            unit="px",
            decimals=1,
        )
        self._bpm_card = MetricCard(
            name="HEART RATE",
            unit="bpm",
            decimals=0,
            window_seconds=60.0,
        )
        self._rmssd_card = MetricCard(
            name="HRV (RMSSD)",
            unit="ms",
            decimals=1,
            window_seconds=60.0,
        )
        self._speed_card = MetricCard(
            name="TASK SPEED",
            unit="s",
            decimals=0,
            show_sparkline=False,
        )
        self._accuracy_card = MetricCard(
            name="ACCURACY",
            unit="%",
            decimals=1,
        )

        for card in (self._pupil_card, self._bpm_card, self._rmssd_card,
                     self._speed_card, self._accuracy_card):
            card.setObjectName("card")
            card.setStyleSheet("background-color: transparent;")
            bottom_row.addWidget(card, stretch=1)

        outer.addLayout(bottom_row, stretch=1)
        return widget

    # ------------------------------------------------------------------
    # Mode Camera + Bio — full-screen camera with overlay
    # ------------------------------------------------------------------

    def _build_mode_camera(self) -> QWidget:
        """Build the Camera + Bio mode layout.

        Camera feed fills the area with a transparent HUD overlay.
        Metrics are positioned in a bottom row of equally sized cards.
        """
        widget = QWidget()
        widget.setStyleSheet("background: #000000;")

        # Layering: use QGridLayout to stack HUD on top of VideoFeed
        layout = QGridLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Base: Video feed
        self._video_feed = VideoFeed()
        layout.addWidget(self._video_feed, 0, 0)

        # HUD Overlay
        hud = QWidget()
        hud.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hud_layout = QVBoxLayout(hud)
        # Top margin of 100px to clear the floating toolbar
        hud_layout.setContentsMargins(SPACE_3, 100, SPACE_3, SPACE_3)
        hud_layout.addStretch(1)

        # Bottom HUD Container (Single card for all metrics)
        hud_container = QFrame()
        hud_container.setStyleSheet(
            f"background-color: rgba(255, 255, 255, 0.12); "
            f"border: none; "
            f"border-radius: {RADIUS_LG}px;"
        )
        bottom_row = QHBoxLayout(hud_container)
        bottom_row.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        bottom_row.setSpacing(SPACE_2)

        # ── 1. TIME Section ────────────────────────────────────────
        time_sec = QVBoxLayout()
        time_sec.setSpacing(SPACE_1)
        time_title = QLabel("SESSION TIME")
        time_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_title.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        time_sec.addWidget(time_title)

        self._cam_timer_lbl = QLabel("00:00")
        self._cam_timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_timer_lbl.setStyleSheet(
            f"color: #FFFFFF; font-size: {FONT_DISPLAY}px; font-weight: 800;"
        )
        time_sec.addWidget(self._cam_timer_lbl)
        bottom_row.addLayout(time_sec, stretch=1)

        # ── 2. COGNITIVE LOAD Section ──────────────────────────────
        cog_sec = QVBoxLayout()
        cog_sec.setSpacing(SPACE_1)
        cog_title = QLabel("COGNITIVE LOAD")
        cog_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cog_title.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        cog_sec.addWidget(cog_title)

        self._cam_workload_gauge = DonutGauge(
            value=0.0,
            accent_color=COLOR_PRIMARY,
            track_color="rgba(255, 255, 255, 0.15)",
            center_text="—",
            size=120,
            text_color="#FFFFFF"
        )
        cog_sec.addWidget(self._cam_workload_gauge, alignment=Qt.AlignmentFlag.AlignCenter)
        bottom_row.addLayout(cog_sec, stretch=1)

        # ── 3. PHYSICAL STRESS Section ─────────────────────────────
        stress_sec = QVBoxLayout()
        stress_sec.setSpacing(SPACE_1)
        stress_title = QLabel("PHYSICAL STRESS")
        stress_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stress_title.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        stress_sec.addWidget(stress_title)

        self._cam_stress_gauge = DonutGauge(
            value=0.0,
            accent_color=_COLOR_CLI,
            track_color="rgba(255, 255, 255, 0.15)",
            center_text="—",
            size=120,
            text_color="#FFFFFF"
        )
        stress_sec.addWidget(self._cam_stress_gauge, alignment=Qt.AlignmentFlag.AlignCenter)
        bottom_row.addLayout(stress_sec, stretch=1)

        # ── 4. HEART RATE Section ──────────────────────────────────
        hr_sec = QVBoxLayout()
        hr_sec.setSpacing(SPACE_1)
        hr_title = QLabel("HEART RATE")
        hr_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hr_title.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        hr_sec.addWidget(hr_title)

        hr_inner = QVBoxLayout()
        hr_inner.setSpacing(0)
        hr_inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        heart_container = QHBoxLayout()
        heart_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heart_container.setSpacing(SPACE_1)

        heart_icon = QLabel()
        heart_icon.setPixmap(get_icon("ph.heartbeat-fill", color=_COLOR_CLI).pixmap(24, 24))
        heart_container.addWidget(heart_icon)

        self._cam_bpm_lbl = QLabel("—")
        self._cam_bpm_lbl.setStyleSheet(
            f"color: #FFFFFF; font-size: {FONT_METRIC_XL}px; font-weight: 800;"
        )
        heart_container.addWidget(self._cam_bpm_lbl)
        
        hr_inner.addLayout(heart_container)
        bpm_unit = QLabel("BPM")
        bpm_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bpm_unit.setStyleSheet("color: rgba(255, 255, 255, 0.3); font-size: 10px; font-weight: 700;")
        hr_inner.addWidget(bpm_unit)

        hr_sec.addLayout(hr_inner)
        bottom_row.addLayout(hr_sec, stretch=1)

        hud_layout.addWidget(hud_container)
        layout.addWidget(hud, 0, 0)
        return widget

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _end_session(self) -> None:
        """End the current session via SessionManager."""
        if self._session_manager is not None:
            # Stop recording and capture the path.
            path = self._stop_camera_recording()
            self._session_manager.set_recording_path(path)

            self._session_manager.end_session()

    def _toggle_pause(self) -> None:
        """Toggle session pause state via SessionManager."""
        if self._session_manager is None:
            return

        if self._pause_btn.isChecked():
            self._session_manager.pause_session()
        else:
            self._session_manager.resume_session()

    @pyqtSlot(int)
    def _on_session_paused(self, _session_id: int) -> None:
        """Called when the session is paused."""
        self._clock_timer.stop()
        self._pause_btn.setChecked(True)
        is_video = self._mode_stack.currentIndex() == _MODE_CAMERA
        self._update_toolbar_theme(is_video)
        logger.info("LiveView: session paused UI updated.")

    @pyqtSlot(int)
    def _on_session_resumed(self, _session_id: int) -> None:
        """Called when the session is resumed."""
        self._clock_timer.start()
        self._pause_btn.setChecked(False)
        is_video = self._mode_stack.currentIndex() == _MODE_CAMERA
        self._update_toolbar_theme(is_video)
        logger.info("LiveView: session resumed UI updated.")

    def cleanup(self) -> None:
        """Stop background activity before the view is destroyed."""
        self._video_feed.stop()

    @pyqtSlot(int)
    def _on_session_started(self, session_id: int) -> None:
        """Called when SessionManager emits ``session_started``."""
        logger.info("LiveView: session %d started.", session_id)
        self._session_id = session_id
        self._session_active = True
        self._has_pupil_baseline = False  # reset — calibration may not have produced one
        self._pdi_min_seen = float("inf")
        self._pdi_max_seen = float("-inf")
        self._reset_widgets()
        self._start_clock()

        # Always start the feed first (feed must be active before recording can begin),
        # then start recording — the camera runs in the background regardless of which
        # display mode (Biofeedback vs Camera+Bio) is currently selected.
        self._video_feed.start(camera_index=self._current_camera_index)
        self._start_camera_recording()

    @pyqtSlot(int)
    def _on_session_ended(self, session_id: int) -> None:
        """Called when SessionManager emits ``session_ended``.

        MainWindow also listens to this signal and navigates to the
        Post-Session view — no navigation logic belongs here.
        """
        logger.info("LiveView: session %d ended.", session_id)
        self._stop_camera_recording()
        self._session_active = False
        self._stop_clock()
        self._video_feed.stop()
        self._session_id = None

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------

    def _start_clock(self) -> None:
        self._elapsed_seconds = 0
        self._cam_timer_lbl.setText("00:00")
        self._clock_timer.start()

    def _stop_clock(self) -> None:
        self._clock_timer.stop()

    def _tick_clock(self) -> None:
        self._elapsed_seconds += 1
        m = self._elapsed_seconds // 60
        s = self._elapsed_seconds % 60

        # Update TASK SPEED card with duration in seconds
        self._speed_card.set_value(float(self._elapsed_seconds))

        # Update camera overlay timer label
        time_str = f"{m:02d}:{s:02d}"
        self._cam_timer_lbl.setText(time_str)

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _set_mode(self, index: int) -> None:
        """Switch between Biofeedback and Camera+Bio modes.

        Args:
            index: ``_MODE_BIOFEEDBACK`` (0) or ``_MODE_CAMERA`` (1).
        """
        self._mode_stack.setCurrentIndex(index)
        self._mode_switcher.setChecked(index == _MODE_CAMERA)
        
        # Update toolbar colors for the new mode
        self._update_toolbar_theme(is_video=(index == _MODE_CAMERA))

        # The camera feed and recording run continuously for the whole session
        # regardless of display mode.  Only the *display panel* switches here —
        # never touch the feed or recording lifecycle on a mode switch.

        logger.info(
            "Live view mode: %s",
            "Biofeedback" if index == _MODE_BIOFEEDBACK else "Camera + Bio",
        )

    def _on_switch_camera(self) -> None:
        """Cycle through external USB camera indices (1 -> 2 -> 1).

        Index 0 is intentionally excluded — it maps to the built-in laptop
        camera, which is never used by BioTrace.
        """
        self._current_camera_index = 2 if self._current_camera_index == 1 else 1

        if self._session_active:
            # Re-start feed and recording on new camera index (feed always runs during session).
            self._stop_camera_recording()
            self._video_feed.start(camera_index=self._current_camera_index)
            self._start_camera_recording()
            
        logger.info("Switched to camera index %d", self._current_camera_index)

    # ------------------------------------------------------------------
    # Public data-update slots (called via SessionManager signals)
    # ------------------------------------------------------------------

    @pyqtSlot(float, float)
    def on_rmssd_updated(self, rmssd: float, timestamp: float) -> None:
        """Receive RMSSD update and refresh all relevant widgets.

        Args:
            rmssd: RMSSD in milliseconds.
            timestamp: Unix timestamp of the sample.
        """
        self._rmssd_card.set_value(rmssd, timestamp)

        # Map RMSSD to a 0–100 stress percentage for the gauge cards.
        # RMSSD 20 ms → high stress (100 %), RMSSD 80 ms → low stress (0 %).
        stress_pct = max(0.0, min(100.0, (1.0 - (rmssd - 20.0) / 60.0) * 100.0))
        self._stress_gauge.set_value(stress_pct / 100.0, f"{stress_pct:.0f}%")
        self._cam_stress_gauge.set_value(stress_pct / 100.0, f"{stress_pct:.0f}%")
        
        # Feed the timeline chart.
        self._timeline_chart.append("STRESS", timestamp, stress_pct / 100.0)

    @pyqtSlot(float, float)
    def on_pdi_updated(self, pdi: float, timestamp: float) -> None:
        """Receive PDI update (or raw diameter) and refresh pupil dilation card.

        When a calibration baseline exists, ``pdi`` is the Pupil Dilation Index
        (dimensionless) and is displayed scaled to a %-like index.
        Before calibration, ``pdi`` carries the raw diameter in px so that the
        live view shows sensor activity even without a baseline.

        Args:
            pdi: PDI ratio (with baseline) or raw diameter in px (without baseline).
            timestamp: Unix timestamp of the sample.
        """
        if self._has_pupil_baseline:
            self._pupil_card.set_value(pdi * 100.0, timestamp)  # display as %-like index
        else:
            self._pupil_card.set_value(pdi, timestamp)  # raw diameter in px

        # Track running min/max for workload normalization.
        self._pdi_min_seen = min(self._pdi_min_seen, pdi)
        self._pdi_max_seen = max(self._pdi_max_seen, pdi)

        pdi_range = self._pdi_max_seen - self._pdi_min_seen
        if pdi_range > 0.0:
            workload = (pdi - self._pdi_min_seen) / pdi_range
            workload_pct = workload * 100.0
            self._workload_gauge.set_value(workload, f"{workload_pct:.0f}%")
            self._cam_workload_gauge.set_value(workload, f"{workload_pct:.0f}%")
            self._timeline_chart.append("WORKLOAD", timestamp, workload)

    @pyqtSlot(float, float)
    def _on_calibration_complete(self, _baseline_rmssd: float, baseline_pupil_px: float) -> None:
        """Record whether a valid pupil baseline was established."""
        self._has_pupil_baseline = baseline_pupil_px > 0.0
        logger.info(
            "LiveView: calibration complete — pupil baseline %.2f px (has_baseline=%s).",
            baseline_pupil_px, self._has_pupil_baseline,
        )

    @pyqtSlot(float, float)
    def on_cli_updated(self, cli: float, timestamp: float) -> None:
        """Receive CLI update and refresh all cognitive load displays.

        Args:
            cli: Cognitive Load Index in [0.0, 1.0].
            timestamp: Unix timestamp of the sample.
        """
        workload_pct = cli * 100.0
        self._workload_gauge.set_value(cli, f"{workload_pct:.0f}%")
        self._cam_workload_gauge.set_value(cli, f"{workload_pct:.0f}%")
        
        self._timeline_chart.append("WORKLOAD", timestamp, cli)

    @pyqtSlot(float, float)
    def on_bpm_updated(self, bpm: float, _timestamp: float) -> None:
        """Receive instantaneous BPM and update the heart rate card.

        Args:
            bpm: Beats per minute derived from the latest RR interval.
            _timestamp: Unix timestamp (unused in the display layer).
        """
        self._bpm_card.set_value(bpm, _timestamp)
        self._cam_bpm_lbl.setText(f"{bpm:.0f}")

    @pyqtSlot(bool, str)
    def _on_hrv_connection_changed(self, connected: bool, _message: str) -> None:
        """Update ECG badge and clear stale heart-rate values on disconnect."""
        self._set_badge_status(self._ecg_badge, "ph.heartbeat-fill", connected)
        if not connected:
            self._bpm_card.reset()
            self._rmssd_card.reset()
            self._stress_gauge.set_value(0.0, "—")
            self._cam_stress_gauge.set_value(0.0, "—")
            self._cam_bpm_lbl.setText("—")

    @pyqtSlot(bool, str)
    def _on_eye_connection_changed(self, connected: bool, _message: str) -> None:
        """Update eye tracker badge and clear stale pupil values on disconnect."""
        self._set_badge_status(self._eye_badge, "ph.eye-fill", connected)
        if not connected:
            self._pupil_card.reset()

    # ------------------------------------------------------------------
    # Widget reset
    # ------------------------------------------------------------------

    def _reset_widgets(self) -> None:
        """Clear all metric cards and charts before a new session."""
        for card in (self._pupil_card, self._bpm_card, self._rmssd_card,
                     self._speed_card, self._accuracy_card):
            card.reset()

        self._workload_gauge.set_value(0.0, "—")
        self._stress_gauge.set_value(0.0, "—")
        self._cam_workload_gauge.set_value(0.0, "—")
        self._cam_stress_gauge.set_value(0.0, "—")

        self._timeline_chart.clear_all()

    def _start_camera_recording(self) -> None:
        """Start recording automatically for the active session."""
        if not self._session_active:
            return
        if self._video_feed.is_recording:
            return

        recordings_dir = Path(VIDEO_RECORDINGS_DIR)
        recordings_dir.mkdir(parents=True, exist_ok=True)

        session_label = self._session_id if self._session_id is not None else "unknown"
        file_name = f"session_{session_label}_{int(time.time())}.mp4"
        output_path = recordings_dir / file_name
        self._recording_path = str(output_path.absolute())

        if self._video_feed.start_recording(self._recording_path):
            logger.info("Video recording started automatically: %s", self._recording_path)
        else:
            self._recording_path = None
            logger.warning("Could not start automatic video recording.")

    def _stop_camera_recording(self) -> str | None:
        """Stop camera recording and return the absolute path to the file.

        Returns:
            The absolute path of the recording, or None if no recording was made.
        """
        path = None
        if self._video_feed.is_recording:
            self._video_feed.stop_recording()
            path = self._recording_path
            logger.info("Video recording stopped: %s", path)

        self._recording_path = None
        return path

    def _make_status_badge(self, icon_name: str) -> QFrame:
        """Create a rounded status indicator frame."""
        badge = QFrame()
        badge.setFixedSize(28, 28)
        layout = QHBoxLayout(badge)
        layout.setContentsMargins(0, 0, 0, 0)

        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        # Initial state: disconnected (transparent)
        self._set_badge_status(badge, icon_name, connected=False)
        return badge

    def _set_badge_status(self, badge: QFrame, icon_name: str, connected: bool) -> None:
        """Apply the connected/disconnected style to a status badge."""
        if connected:
            bg = COLOR_SUCCESS
            border = "none"
            color = "#FFFFFF"
        else:
            bg = "transparent"
            border = f"2px solid {COLOR_BORDER}"
            color = COLOR_FONT_MUTED

        badge.setStyleSheet(
            f"background: {bg}; border: {border}; border-radius: 14px;"
        )

        # Find the icon label within the layout
        icon_lbl = badge.findChild(QLabel)
        if icon_lbl:
            icon_lbl.setPixmap(get_icon(icon_name, color=color).pixmap(14, 14))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_gauge_panel(
        self, 
        title: str, 
        accent: str, 
        track: str
    ) -> tuple[DonutGauge, QWidget]:
        """Create a vertical panel containing a donut gauge and a title.
        
        This panel has no background or border as requested.
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0) # Minimal spacing to bring label closer

        # Add stretch at top to move the chart downwards
        layout.addStretch(1)

        gauge = DonutGauge(value=0.0, accent_color=accent, track_color=track, center_text="—", size=180)
        layout.addWidget(gauge, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(SPACE_2) # Exactly 16px space

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {FONT_SMALL}px; font-weight: 700; letter-spacing: 1.5px;"
        )
        layout.addWidget(title_lbl)
        
        # Balance with a bit of space at the bottom (but less than top stretch)
        layout.addSpacing(SPACE_1)

        return gauge, panel

    @staticmethod
    def _make_card() -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet("background-color: transparent;")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return card
