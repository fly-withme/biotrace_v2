"""Calibration view — breathing-guided baseline measurement.

Redesigned to match the BioTrace design system:
- Centered layout with animated breathing orb
- "BASELINE CALIBRATION" small-caps heading
- "Breath in • Breath out" breathing guidance text
- Single "Start" CTA → begins baseline recording
- "Start Session" CTA on completion → emits ``proceed_to_live``
- Back arrow (top-left) → emits ``close_requested``

User flow
---------
New Session (Dashboard header) → CalibrationView opens →
user breathes, clicks Start → 60 s baseline records →
clicks "Start Session" → ``proceed_to_live`` → LiveView

Dependency injection: call ``bind_session_manager()`` once after
the view is added to the QStackedWidget.
"""

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QSize,
    QTimer,
    Qt,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QBrush, QColor, QPainter, QRadialGradient
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import (
    CALIBRATION_CTA_HEIGHT,
    CALIBRATION_CTA_WIDTH,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_FONT,
    COLOR_FONT_MUTED,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_SUCCESS,
    FONT_BODY,
    FONT_BODY_LARGE,
    FONT_CAPTION,
    FONT_SMALL,
    FONT_TITLE,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_4,
    get_icon,
)
from app.utils.config import CALIBRATION_DURATION_SECONDS
from app.utils.logger import get_logger

logger = get_logger(__name__)

_INHALE_SECONDS: int = 4
_EXHALE_SECONDS: int = 4


class CountdownRing(QWidget):
    """Compact circular countdown indicator used in calibration header."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress: float = 1.0
        self.setFixedSize(36, 36)

    def set_progress(self, progress: float) -> None:
        """Set normalized remaining progress (1.0 full to 0.0 empty)."""
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(4, 4, -4, -4)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_BORDER))
        painter.drawEllipse(rect)

        span = int(360 * 16 * self._progress)
        if span > 0:
            painter.setBrush(QColor(COLOR_PRIMARY))
            painter.drawPie(rect, 90 * 16, -span)


# ---------------------------------------------------------------------------
# BreathingOrb — animated sphere widget
# ---------------------------------------------------------------------------

class BreathingOrb(QWidget):
    """Animated 3D-looking breathing orb.

    Pulses between a resting size and an expanded size using a
    QPropertyAnimation on the custom ``orb_radius`` property, guiding the
    user's breathing rhythm (inhale = expand, exhale = contract).

    The sphere uses a QRadialGradient to simulate a light source in the
    top-left quadrant, giving a glossy 3D appearance.
    """

    _FIXED_SIZE: int = 280   # widget canvas size in pixels
    _PREVIEW_RADIUS_MIN: float = 84.0
    _PREVIEW_RADIUS_MAX: float = 116.0
    _ACTIVE_RADIUS_MIN: float = 72.0
    _ACTIVE_RADIUS_MAX: float = 128.0

    phase_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._radius: float = self._PREVIEW_RADIUS_MIN
        self._preview_mode: bool = True
        self.setFixedSize(self._FIXED_SIZE, self._FIXED_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        # Inhale: expand over 4 s
        self._inhale = QPropertyAnimation(self, b"orb_radius", self)
        self._inhale.setDuration(_INHALE_SECONDS * 1000)
        self._inhale.setEasingCurve(QEasingCurve.Type.Linear)

        # Exhale: contract over 4 s
        self._exhale = QPropertyAnimation(self, b"orb_radius", self)
        self._exhale.setDuration(_EXHALE_SECONDS * 1000)
        self._exhale.setEasingCurve(QEasingCurve.Type.Linear)

        self._apply_animation_profile()

        # Chain: inhale finished → start exhale, exhale finished → start inhale
        self._inhale.finished.connect(self._start_exhale)
        self._exhale.finished.connect(self._start_inhale)

    # ── Public API ──────────────────────────────────────────────────────

    def start_animation(self) -> None:
        """Begin the breathing pulse animation."""
        self._start_inhale()

    def restart_from_inhale(self) -> None:
        """Reset orb to initial size and restart from inhale phase."""
        self._inhale.stop()
        self._exhale.stop()
        start_radius = self._PREVIEW_RADIUS_MIN if self._preview_mode else self._ACTIVE_RADIUS_MIN
        self._set_orb_radius(start_radius)
        self._start_inhale()

    def stop_animation(self) -> None:
        """Stop the breathing pulse animation and reset radius."""
        self._inhale.stop()
        self._exhale.stop()

    def set_preview_mode(self, enabled: bool) -> None:
        """Toggle simplified preview rendering (no glow/shadow)."""
        self._preview_mode = enabled
        self._apply_animation_profile()
        self.update()

    def _apply_animation_profile(self) -> None:
        """Apply mode-specific radius range while keeping 4s inhale/exhale timing."""
        if self._preview_mode:
            radius_min = self._PREVIEW_RADIUS_MIN
            radius_max = self._PREVIEW_RADIUS_MAX
        else:
            radius_min = self._ACTIVE_RADIUS_MIN
            radius_max = self._ACTIVE_RADIUS_MAX

        self._inhale.setDuration(_INHALE_SECONDS * 1000)
        self._inhale.setStartValue(radius_min)
        self._inhale.setEndValue(radius_max)

        self._exhale.setDuration(_EXHALE_SECONDS * 1000)
        self._exhale.setStartValue(radius_max)
        self._exhale.setEndValue(radius_min)

    def _start_inhale(self) -> None:
        """Start inhale phase and notify listeners."""
        self.phase_changed.emit("inhale")
        self._inhale.start()

    def _start_exhale(self) -> None:
        """Start exhale phase and notify listeners."""
        self.phase_changed.emit("exhale")
        self._exhale.start()

    # ── Qt property (required for QPropertyAnimation) ───────────────────

    def _get_orb_radius(self) -> float:
        return self._radius

    def _set_orb_radius(self, r: float) -> None:
        self._radius = r
        self.update()  # triggers paintEvent

    orb_radius = pyqtProperty(float, _get_orb_radius, _set_orb_radius)

    # ── Painting ─────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        cx: float = self.width() / 2
        cy: float = self.height() / 2
        r: float = self._radius

        # No extra background layers behind the orb to avoid visible artifacts while scaling.

        # Sphere body. Preview mode uses a softer, flatter fill to avoid border-like edges.
        if self._preview_mode:
            sphere = QRadialGradient(QPointF(cx - r * 0.15, cy - r * 0.18), r * 1.35)
            sphere.setColorAt(0.00, QColor(178, 198, 238))
            sphere.setColorAt(0.55, QColor(126, 154, 215))
            sphere.setColorAt(1.00, QColor(88, 118, 188))
            painter.setBrush(QBrush(sphere))
            painter.drawEllipse(QPointF(cx, cy), r, r)
        else:
            highlight_x = cx - r * 0.32
            highlight_y = cy - r * 0.38
            sphere = QRadialGradient(QPointF(highlight_x, highlight_y), r * 1.6)
            sphere.setColorAt(0.00, QColor(214, 224, 248))
            sphere.setColorAt(0.18, QColor(162, 184, 232))
            sphere.setColorAt(0.42, QColor(103, 133, 202))
            sphere.setColorAt(0.72, QColor(59, 87, 159))
            sphere.setColorAt(1.00, QColor(18, 38, 104))

            painter.setBrush(QBrush(sphere))
            painter.drawEllipse(QPointF(cx, cy), r, r)

        painter.end()


# ---------------------------------------------------------------------------
# CalibrationView
# ---------------------------------------------------------------------------

class CalibrationView(QWidget):
    """Breathing-guided baseline calibration screen.

    Presents a calming, minimal UI that guides the user through a
    resting baseline measurement before a live session.

    Signals:
        proceed_to_live:
            Emitted when the user clicks "Start Session" after a successful
            baseline recording.  ``MainWindow`` listens and navigates to
            ``LiveView``, then calls ``session_manager.start_session()``.
        close_requested:
            Emitted when the user clicks the back arrow (top-left).
            ``MainWindow`` listens and navigates back to the Dashboard.
    """

    proceed_to_live = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_manager = None

        self._baseline_remaining: int = CALIBRATION_DURATION_SECONDS
        self._recording: bool = False
        self._complete: bool = False
        self._computed_rmssd: float = 0.0
        self._computed_pupil: float = 0.0

        # 1-second tick during baseline recording
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)

        self._prestart_timer = QTimer(self)
        self._prestart_timer.setInterval(1000)
        self._prestart_timer.timeout.connect(self._tick_prestart_countdown)
        self._prestart_remaining: int = 0
        self._prestart_active: bool = False

        self._build_ui()
        self._orb.start_animation()

    # ------------------------------------------------------------------
    # Dependency injection
    # ------------------------------------------------------------------

    def bind_session_manager(self, session_manager) -> None:
        """Inject the SessionManager.

        Args:
            session_manager: A :class:`~app.core.session.SessionManager` instance.
        """
        self._session_manager = session_manager
        session_manager.calibration_complete.connect(self._on_calibration_complete)
        logger.info("CalibrationView bound to SessionManager.")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        root.setSpacing(SPACE_2)

        # ── Header (dashboard style) ───────────────────────────────────
        header_row = QHBoxLayout()
        header_row.addStretch()

        skip_btn = QPushButton()
        skip_btn.setIcon(get_icon("ph.fast-forward-fill", color=COLOR_FONT_MUTED))
        skip_btn.setIconSize(QSize(16, 16))
        skip_btn.setFixedSize(36, 36)
        skip_btn.setToolTip("Skip calibration")
        skip_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLOR_BORDER};
                border-radius: 18px;
            }}
            QPushButton:hover {{
                background: {COLOR_BORDER};
            }}
            """
        )
        skip_btn.clicked.connect(self._on_skip_calibration)
        header_row.addWidget(skip_btn)

        self._restart_btn = QPushButton()
        self._restart_btn.setIcon(get_icon("ph.arrow-counter-clockwise-fill", color=COLOR_FONT_MUTED))
        self._restart_btn.setIconSize(QSize(16, 16))
        self._restart_btn.setFixedSize(36, 36)
        self._restart_btn.setToolTip("Restart calibration")
        self._restart_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLOR_BORDER};
                border-radius: 18px;
            }}
            QPushButton:hover {{
                background: {COLOR_BORDER};
            }}
            """
        )
        self._restart_btn.clicked.connect(self._restart_baseline)
        self._restart_btn.hide()
        header_row.addWidget(self._restart_btn)

        self._countdown_ring = CountdownRing()
        self._countdown_ring.setToolTip("Calibration timer")
        self._countdown_ring.hide()
        header_row.addWidget(self._countdown_ring)
        root.addLayout(header_row)

        root.addStretch(1)

        # ── Centered content column ─────────────────────────────────────
        center_col = QVBoxLayout()
        center_col.setSpacing(0)
        center_col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        center_col.addSpacing(SPACE_2)

        # Breathing orb
        self._orb = BreathingOrb()
        self._orb.phase_changed.connect(self._on_orb_phase_changed)
        center_col.addWidget(self._orb, alignment=Qt.AlignmentFlag.AlignHCenter)
        center_col.addSpacing(SPACE_4)

        # Breath guidance text
        self._breath_label = QLabel("Press Start")
        self._breath_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._breath_label.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {FONT_TITLE}px; "
            "font-weight: 600; letter-spacing: 1px;"
        )
        center_col.addWidget(self._breath_label)
        center_col.addSpacing(SPACE_2)

        # Status / instruction text
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            f"color: {COLOR_FONT_MUTED}; font-size: {FONT_CAPTION}px;"
        )
        center_col.addWidget(self._status_label)
        center_col.addSpacing(SPACE_3)

        # CTA button — dark pill style
        self._cta_btn = QPushButton("  Start")
        self._cta_btn.setIcon(get_icon("ph.play-fill", color="#FFFFFF"))
        self._cta_btn.setIconSize(QSize(16, 16))
        self._cta_btn.setFixedSize(CALIBRATION_CTA_WIDTH, CALIBRATION_CTA_HEIGHT)
        self._cta_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cta_btn.clicked.connect(self._on_cta_clicked)
        self._apply_cta_style_start()
        center_col.addWidget(self._cta_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addLayout(center_col)
        root.addStretch(1)

    def _format_baseline_value_lines(self) -> tuple[str, str]:
        """Return two formatted baseline value lines without dummy values."""
        if self._computed_rmssd > 0.0:
            rmssd_line = f"Baseline RMSSD: {self._computed_rmssd:.2f} ms"
        else:
            rmssd_line = "Baseline RMSSD: Not available"

        if self._computed_pupil > 0.0:
            pupil_line = f"Baseline pupil: {self._computed_pupil:.3f} px"
        else:
            pupil_line = "Baseline pupil: Not available"

        return rmssd_line, pupil_line

    def _show_baseline_popup(self) -> None:
        """Show a popup card with computed baseline values after calibration."""
        rmssd_line, pupil_line = self._format_baseline_value_lines()

        popup = QDialog(self)
        popup.setModal(True)
        popup.setWindowTitle("Calibration Complete")
        popup.setMinimumWidth(360)

        layout = QVBoxLayout(popup)
        layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        layout.setSpacing(SPACE_2)

        headline = QLabel("Calibration successful")
        headline.setStyleSheet(
            f"color: {COLOR_SUCCESS}; font-size: {FONT_TITLE}px; font-weight: 700;"
        )
        layout.addWidget(headline)

        rmssd_label = QLabel(rmssd_line)
        rmssd_label.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {FONT_BODY_LARGE}px; font-weight: 500;"
        )
        layout.addWidget(rmssd_label)

        pupil_label = QLabel(pupil_line)
        pupil_label.setStyleSheet(
            f"color: {COLOR_FONT}; font-size: {FONT_BODY_LARGE}px; font-weight: 500;"
        )
        layout.addWidget(pupil_label)

        next_btn = QPushButton("Next")
        next_btn.clicked.connect(popup.accept)
        layout.addWidget(next_btn, alignment=Qt.AlignmentFlag.AlignRight)

        if popup.exec() == QDialog.DialogCode.Accepted:
            self.proceed_to_live.emit()

    # ------------------------------------------------------------------
    # CTA button styling
    # ------------------------------------------------------------------

    def _apply_cta_style_start(self) -> None:
        """Dark navy pill — used for the initial 'Start' state."""
        cta_radius = CALIBRATION_CTA_HEIGHT // 2
        self._cta_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {COLOR_FONT};
                color: #FFFFFF;
                border: none;
                border-radius: {cta_radius}px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {COLOR_PRIMARY};
            }}
            QPushButton:disabled {{
                background: #A8B4CE;
            }}
            """
        )

    def _apply_cta_style_complete(self) -> None:
        """Primary blue pill — used after baseline is complete."""
        cta_radius = CALIBRATION_CTA_HEIGHT // 2
        self._cta_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {COLOR_PRIMARY};
                color: #FFFFFF;
                border: none;
                border-radius: {cta_radius}px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {COLOR_PRIMARY_HOVER};
            }}
            """
        )

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _on_skip_calibration(self) -> None:
        """Skip calibration and proceed directly to live session."""
        self._prestart_timer.stop()
        self._prestart_active = False
        self._countdown_timer.stop()

        if self._session_manager is not None and self._recording:
            elapsed = CALIBRATION_DURATION_SECONDS - self._baseline_remaining
            try:
                rmssd, pupil = self._session_manager.end_calibration(duration_seconds=elapsed)
                self._computed_rmssd = rmssd
                self._computed_pupil = pupil
            except Exception:
                logger.exception("Failed to end calibration during skip.")

        self._recording = False
        self._complete = False
        self._countdown_ring.hide()
        self._countdown_ring.set_progress(1.0)
        self.proceed_to_live.emit()

    def _on_close(self) -> None:
        """Stop all timers and emit close_requested → back to Dashboard."""
        self._prestart_timer.stop()
        self._prestart_active = False
        self._countdown_timer.stop()
        if self._session_manager and self._recording:
            # Abort calibration gracefully.
            try:
                self._session_manager.end_calibration(
                    duration_seconds=CALIBRATION_DURATION_SECONDS - self._baseline_remaining
                )
            except Exception:
                pass
        self.close_requested.emit()

    # ------------------------------------------------------------------
    # CTA handler
    # ------------------------------------------------------------------

    def _on_cta_clicked(self) -> None:
        if self._complete:
            # Proceed to live view.
            self.proceed_to_live.emit()
        else:
            if self._recording or self._prestart_active:
                return
            self._start_prestart_countdown()

    def _start_prestart_countdown(self) -> None:
        """Show a 3-2-1 countdown before baseline recording starts."""
        self._prestart_active = True
        self._prestart_remaining = 3
        self._cta_btn.setEnabled(False)
        self._breath_label.setText(f"Calibration starting in {self._prestart_remaining}")
        self._status_label.setText("")
        self._prestart_timer.start()

    def _tick_prestart_countdown(self) -> None:
        """Advance the pre-start countdown every second."""
        self._prestart_remaining -= 1
        if self._prestart_remaining > 0:
            self._breath_label.setText(f"Calibration starting in {self._prestart_remaining}")
            return

        self._prestart_timer.stop()
        self._prestart_active = False
        self._start_baseline()

    # ------------------------------------------------------------------
    # Baseline recording
    # ------------------------------------------------------------------

    def _start_baseline(self) -> None:
        """Begin the 60-second resting baseline measurement."""
        self._prestart_timer.stop()
        self._prestart_active = False
        self._recording = True
        self._complete = False
        self._baseline_remaining = CALIBRATION_DURATION_SECONDS
        self._countdown_ring.show()
        self._countdown_ring.set_progress(1.0)
        self._restart_btn.show()
        self._orb.set_preview_mode(False)
        self._orb.restart_from_inhale()

        # During active recording the main CTA is hidden; only header restart is available.
        self._cta_btn.hide()
        self._status_label.setText("")

        if self._session_manager is not None:
            self._session_manager.start_calibration()

        self._countdown_timer.start()
        logger.info("Calibration baseline recording started.")

    def _restart_baseline(self) -> None:
        """Restart baseline recording from 0 when user clicks Restart."""
        if not self._recording:
            return

        self._countdown_timer.stop()
        self._baseline_remaining = CALIBRATION_DURATION_SECONDS
        self._countdown_ring.show()
        self._countdown_ring.set_progress(1.0)
        self._restart_btn.show()
        self._orb.set_preview_mode(False)
        self._orb.restart_from_inhale()
        self._status_label.setText("")

        if self._session_manager is not None:
            self._session_manager.start_calibration()

        self._countdown_timer.start()
        logger.info("Calibration baseline restarted by user.")

    def _tick_countdown(self) -> None:
        """Called every second during baseline recording."""
        self._baseline_remaining -= 1
        progress = self._baseline_remaining / CALIBRATION_DURATION_SECONDS
        self._countdown_ring.set_progress(progress)
        if self._baseline_remaining > 0:
            self._status_label.setText("")
        else:
            self._countdown_timer.stop()
            self._finish_baseline()

    def _finish_baseline(self) -> None:
        """Compute baseline values and transition to 'Start Session' state."""
        if self._session_manager is not None:
            rmssd, pupil = self._session_manager.end_calibration(
                duration_seconds=CALIBRATION_DURATION_SECONDS
            )
            self._computed_rmssd = rmssd
            self._computed_pupil = pupil

        self._recording = False
        self._complete = True
        self._breath_label.setText("Press Start")
        self._status_label.setText("Ready to begin")
        self._restart_btn.hide()
        self._orb.set_preview_mode(True)
        self._countdown_ring.hide()
        self._countdown_ring.set_progress(1.0)
        self._show_baseline_popup()

        self._cta_btn.show()
        self._cta_btn.setEnabled(True)
        self._cta_btn.setText("  Start Session")
        self._cta_btn.setIcon(get_icon("ph.play-fill", color="#FFFFFF"))
        self._apply_cta_style_complete()
        logger.info(
            "Calibration complete. RMSSD=%.2f ms, pupil=%.3f px",
            self._computed_rmssd, self._computed_pupil,
        )

    # ------------------------------------------------------------------
    # SessionManager signal slot
    # ------------------------------------------------------------------

    @pyqtSlot(float, float)
    def _on_calibration_complete(self, rmssd: float, pupil_px: float) -> None:
        """Receive baseline values pushed by SessionManager after computation.

        Args:
            rmssd: Resting RMSSD baseline in milliseconds.
            pupil_px: Resting pupil diameter baseline in pixels.
        """
        self._computed_rmssd = rmssd
        self._computed_pupil = pupil_px
        logger.info(
            "CalibrationView received baseline: RMSSD=%.2f ms, pupil=%.3f px",
            rmssd, pupil_px,
        )

    # ------------------------------------------------------------------
    # Reset (called by MainWindow before each new session)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Return to initial state for a fresh calibration run."""
        self._prestart_timer.stop()
        self._prestart_active = False
        self._countdown_timer.stop()
        self._baseline_remaining = CALIBRATION_DURATION_SECONDS
        self._recording = False
        self._complete = False
        self._computed_rmssd = 0.0
        self._computed_pupil = 0.0
        self._restart_btn.hide()
        self._orb.set_preview_mode(True)
        self._countdown_ring.hide()
        self._countdown_ring.set_progress(1.0)
        self._breath_label.setText("Press Start")
        self._status_label.setText("")
        self._cta_btn.show()
        self._cta_btn.setText("  Start")
        self._cta_btn.setIcon(get_icon("ph.play-fill", color="#FFFFFF"))
        self._cta_btn.setEnabled(True)
        self._apply_cta_style_start()
        logger.debug("CalibrationView reset.")

    def _on_orb_phase_changed(self, phase: str) -> None:
        """Update breath guidance text to match orb animation phase."""
        if not self._recording:
            return

        if phase == "inhale":
            self._breath_label.setText("Breath in")
        elif phase == "exhale":
            self._breath_label.setText("Breath out")
