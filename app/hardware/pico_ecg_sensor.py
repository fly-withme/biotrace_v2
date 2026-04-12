"""Pi Pico ECG sensor driver for BioTrace.

Reads raw ECG samples from a Raspberry Pi Pico running YLab Zero
CircuitPython firmware over USB serial, detects R-peaks in real time, and
emits RR intervals matching the :class:`~app.hardware.mock_sensors.MockHRVSensor`
signal contract.

The Pi Pico runs ``sensory.print()`` in its Active state, producing one line
per sample interval in the format::

    Yeda0:(0.00234,) MOI0:(0.0,) MOI1:(1.0,)

The ``Yeda`` sensor is configured with ``reciprocal=True`` on the device,
meaning the transmitted value is ``1 / adc_voltage``.  This driver inverts it
back to the original ECG signal before performing R-peak detection.

R-peak detection algorithm
--------------------------
A simple threshold + refractory period detector is used, optimised for
reliability over accuracy given the 150 Hz sample rate:

1. **Adaptive amplitude**: a running maximum over a sliding window of
   ``PICO_RPEAK_AMPLITUDE_WINDOW`` samples tracks the signal envelope.
2. **Threshold crossing**: a peak candidate is triggered when the signal
   *falls* below ``PICO_RPEAK_THRESHOLD_FACTOR × adaptive_amplitude``
   after having been above it (falling-edge trigger ensures we capture
   the true peak, not the upstroke).
3. **Refractory period**: any candidate within
   ``PICO_RPEAK_REFRACTORY_SAMPLES`` samples of the previous accepted peak
   is discarded (prevents double-counting).

RR interval derivation
----------------------
Each accepted peak pair yields one RR interval::

    RR_ms = (sample_index_diff / PICO_ECG_SAMPLE_RATE_HZ) × 1000

This value — together with the wall-clock timestamp — is emitted via
``raw_rr_interval_received``.

Usage::

    from app.hardware.pico_ecg_sensor import PicoECGSensor

    sensor = PicoECGSensor(port="/dev/tty.usbmodem101")
    sensor.raw_rr_interval_received.connect(hrv_processor.on_rr_interval)
    sensor.connection_status_changed.connect(handle_status)
    sensor.start()
    # … later …
    sensor.stop()
"""

import re
import time
from collections import deque

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from app.hardware.base_sensor import BaseSensor
from app.utils.config import (
    PICO_ECG_BAUD,
    PICO_ECG_PORT,
    PICO_ECG_SAMPLE_RATE_HZ,
    PICO_RPEAK_AMPLITUDE_WINDOW,
    PICO_RPEAK_REFRACTORY_SAMPLES,
    PICO_RPEAK_THRESHOLD_FACTOR,
    PICO_WALL_CONTACT_MIN_EVENT_INTERVAL_SECONDS,
    PICO_WALL_CONTACT_LOG_THROTTLE_SECONDS,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Regex to extract the first tuple-printed float from a Sensory.print() line.
# Matches patterns like:  Yeda0:(0.00234,)
_YEDA_RE = re.compile(r"Yeda\d+:\(([^,)]+),?\)")
_MOI_RE = re.compile(r"(MOI\d+):\(([^,)]+),?\)")

# USB vendor IDs that identify a Pi Pico or compatible CircuitPython device.
_PICO_VIDS: frozenset[int] = frozenset({
    0x2E8A,  # Raspberry Pi Foundation (official Pico / Pico W)
    0x239A,  # Adafruit Industries (some CircuitPython builds)
})

# Description substrings used as a fallback when VID is unavailable.
_PICO_DESC_KEYWORDS: tuple[str, ...] = ("circuitpython", "pico", "usbmodem")


def find_pico_port() -> str | None:
    """Scan connected serial ports and return the first Pi Pico device path.

    Detection priority:
    1. Match by USB vendor ID (VID 0x2E8A for Raspberry Pi, 0x239A for Adafruit).
    2. Fall back to case-insensitive description substring match for systems
       that do not report VID (e.g. some macOS USB CDC drivers).

    Returns:
        The serial device path (e.g. ``"/dev/cu.usbmodem1101"``), or ``None``
        if no compatible device is found.
    """
    for port_info in serial.tools.list_ports.comports():
        # Primary match: USB vendor ID.
        if port_info.vid in _PICO_VIDS:
            logger.info("Found Pico by VID 0x%04X on %s.", port_info.vid, port_info.device)
            return port_info.device

        # Fallback match: description substring (case-insensitive).
        desc = (port_info.description or "").lower()
        if any(kw in desc for kw in _PICO_DESC_KEYWORDS):
            logger.info(
                "Found Pico by description %r on %s.", port_info.description, port_info.device
            )
            return port_info.device

    return None


class _RPeakDetector:
    """Stateful R-peak detector for a continuous ECG sample stream.

    Implements DC-offset removal followed by a threshold + refractory period
    algorithm that requires no look-ahead, making it suitable for real-time,
    sample-by-sample processing.

    DC offset removal
    -----------------
    A slow exponential moving average (EMA) tracks the wandering baseline
    (skin–electrode impedance shift, signal offset, etc.).  Each incoming
    sample is centred around zero by subtracting this baseline estimate
    before peak detection.  This makes the algorithm robust to:

    - Large DC offsets (e.g. reciprocal-mode sensors outputting values ~20)
    - Slow baseline drift
    - Sensors with varying signal orientations

    Args:
        sample_rate_hz: Sensor sample rate in Hz.
        refractory_samples: Minimum samples between accepted peaks.
        threshold_factor: Fraction of adaptive amplitude used as the trigger
            threshold (0.0–1.0; default 0.65).
        amplitude_window: Number of recent AC samples used to estimate the
            signal amplitude (running maximum of the AC component).
    """

    # EMA alpha for baseline tracking.  At 150 Hz this adapts over ~3 s,
    # fast enough to follow electrode drift but slow enough not to follow
    # the R-peak itself.
    _DC_EMA_ALPHA: float = 0.002

    def __init__(
        self,
        sample_rate_hz: int = PICO_ECG_SAMPLE_RATE_HZ,
        refractory_samples: int = PICO_RPEAK_REFRACTORY_SAMPLES,
        threshold_factor: float = PICO_RPEAK_THRESHOLD_FACTOR,
        amplitude_window: int = PICO_RPEAK_AMPLITUDE_WINDOW,
    ) -> None:
        self._sample_rate_hz = sample_rate_hz
        self._refractory = refractory_samples
        self._threshold_factor = threshold_factor

        self._window: deque[float] = deque(maxlen=amplitude_window)
        self._above_threshold: bool = False
        self._last_peak_sample: int = -refractory_samples  # sentinel
        self._sample_index: int = 0
        self._peak_sample_index: int | None = None  # index of the pending peak
        self._dc_baseline: float | None = None       # slow-moving DC estimate

    def reset(self) -> None:
        """Reset all internal state (call between sessions)."""
        self._window.clear()
        self._above_threshold = False
        self._last_peak_sample = -self._refractory
        self._sample_index = 0
        self._peak_sample_index = None
        self._dc_baseline = None

    def feed(self, value: float) -> float | None:
        """Process one ECG sample and return an RR interval if a peak is detected.

        Applies DC baseline removal before peak detection so the algorithm
        works correctly regardless of the signal's absolute offset.

        Args:
            value: Raw ECG amplitude (after any parser-level inversion).

        Returns:
            RR interval in milliseconds if a new R-peak was detected, otherwise
            ``None``.
        """
        # ── 1. DC baseline removal ────────────────────────────────────────
        if self._dc_baseline is None:
            self._dc_baseline = value
        else:
            self._dc_baseline = (
                self._DC_EMA_ALPHA * value
                + (1.0 - self._DC_EMA_ALPHA) * self._dc_baseline
            )
        ac = value - self._dc_baseline   # zero-centred AC component

        # ── 2. Adaptive amplitude from AC window ─────────────────────────
        self._window.append(ac)
        self._sample_index += 1

        amplitude = max(self._window) if self._window else 0.0

        # Guard: if the signal is essentially flat (no meaningful peaks have
        # been seen yet), skip detection to avoid noise triggers.
        if amplitude <= 0.0:
            return None

        threshold = self._threshold_factor * amplitude
        above = ac >= threshold

        rr_ms: float | None = None

        if above and not self._above_threshold:
            # Rising edge: start tracking this excursion.
            self._above_threshold = True
            self._peak_sample_index = self._sample_index

        elif not above and self._above_threshold:
            # Falling edge: a peak occurred during the excursion.
            self._above_threshold = False

            peak_idx = self._peak_sample_index
            samples_since_last = peak_idx - self._last_peak_sample

            if samples_since_last >= self._refractory:
                rr_ms = (samples_since_last / self._sample_rate_hz) * 1000.0
                self._last_peak_sample = peak_idx
                logger.debug("R-peak at sample %d → RR = %.1f ms", peak_idx, rr_ms)

        return rr_ms


class _SerialWorker(QThread):
    """Background thread that reads lines from the Pi Pico serial port.

    Emits ``rr_interval_ready`` whenever the R-peak detector produces a new
    RR interval, and ``connection_lost`` if the serial port becomes
    unreadable.

    Args:
        port: Serial device path (e.g. ``"/dev/tty.usbmodem101"``).
        baud: Baud rate (must match CircuitPython REPL setting; typically
            115200).
        parent: Qt parent object.
    """

    rr_interval_ready = pyqtSignal(float, float)   # (rr_ms, timestamp_s)
    wall_contact_detected = pyqtSignal()
    connection_lost   = pyqtSignal(str)            # error message

    def __init__(
        self,
        port: str,
        baud: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._port = port
        self._baud = baud
        self._stop_requested = False
        self._detector = _RPeakDetector()
        self._moi_states: dict[str, bool] = {}
        self._moi_seen = False
        self._last_wall_contact_event_ts: float = 0.0
        self._last_wall_contact_log_ts: float = 0.0

    def request_stop(self) -> None:
        """Signal the read loop to exit on next iteration."""
        self._stop_requested = True

    def run(self) -> None:
        """Main thread body: open port, parse lines, detect R-peaks."""
        logger.debug("Serial worker thread %s started.", self.objectName())
        self._detector.reset()
        self._moi_states.clear()
        self._moi_seen = False
        self._last_wall_contact_event_ts = 0.0
        self._last_wall_contact_log_ts = 0.0

        import os
        if not os.path.exists(self._port):
            msg = f"Hardware not found at {self._port}."
            logger.warning(msg)
            self.connection_lost.emit(msg)
            return

        try:
            port = serial.Serial(
                self._port,
                baudrate=self._baud,
                timeout=1.0,
            )
        except serial.SerialException as exc:
            logger.error("Could not open serial port %s: %s", self._port, exc)
            self.connection_lost.emit(str(exc))
            return

        logger.info("Serial port %s opened at %d baud.", self._port, self._baud)

        _lines_received: int = 0
        _lines_matched: int = 0
        _rr_emitted: int = 0
        _WARN_INTERVAL: int = 200       # warn every N lines if still no matches
        _MOI_WARN_INTERVAL: int = 500   # warn every N lines if no MOI channel ever appears

        try:
            while not self._stop_requested:
                try:
                    raw_line = port.readline()
                except serial.SerialException as exc:
                    logger.error("Serial read error: %s", exc)
                    self.connection_lost.emit(str(exc))
                    break

                if not raw_line:
                    # Timeout with no data — keep looping.
                    continue

                try:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                except Exception:
                    continue

                if self._detect_wall_contact(line):
                    self.wall_contact_detected.emit()

                _lines_received += 1

                # Periodic warning when lines arrive but none match the parser.
                if (
                    _lines_matched == 0
                    and _lines_received > 0
                    and _lines_received % _WARN_INTERVAL == 0
                ):
                    logger.warning(
                        "Pico serial: %d lines received, 0 matched Yeda pattern. "
                        "Check that the ECG channel name in the firmware matches "
                        "'Yeda<N>:(value,)'. Raw sample logged above.",
                        _lines_received,
                    )

                if (
                    not self._moi_seen
                    and _lines_received > 0
                    and _lines_received % _MOI_WARN_INTERVAL == 0
                ):
                    logger.warning(
                        "Pico serial: %d lines received but no MOI wall-contact channel seen. "
                        "Wall-contact counting requires firmware output like 'MOI0:(0.0,)' or "
                        "'MOI1:(1.0,)' on the same serial stream.",
                        _lines_received,
                    )

                ecg_value = _parse_yeda_value(line)
                if ecg_value is None:
                    continue

                _lines_matched += 1
                if _lines_matched == 1:
                    logger.info("Pico parser: first Yeda sample matched — ECG data flowing.")

                rr_ms = self._detector.feed(ecg_value)
                if rr_ms is not None:
                    _rr_emitted += 1
                    if _rr_emitted == 1:
                        logger.info("Pico R-peak: first RR interval detected (%.1f ms).", rr_ms)
                    self.rr_interval_ready.emit(rr_ms, time.time())

        finally:
            try:
                port.close()
            except Exception:
                pass
            logger.info("Serial port %s closed.", self._port)

    def _detect_wall_contact(self, line: str) -> bool:
        """Return True once on any MOI channel low→high transition."""
        moi_values = _parse_moi_values(line)
        if not moi_values:
            return False

        self._moi_seen = True

        rising_channels: list[str] = []
        for channel, value in moi_values.items():
            is_high = value >= 0.5
            was_high = self._moi_states.get(channel, False)
            self._moi_states[channel] = is_high
            if is_high and not was_high:
                rising_channels.append(channel)

        if rising_channels:
            now = time.time()
            if now - self._last_wall_contact_event_ts < PICO_WALL_CONTACT_MIN_EVENT_INTERVAL_SECONDS:
                return False
            self._last_wall_contact_event_ts = now

            if now - self._last_wall_contact_log_ts >= PICO_WALL_CONTACT_LOG_THROTTLE_SECONDS:
                logger.info(
                    "Pico wall contact detected on %s.",
                    ", ".join(sorted(rising_channels)),
                )
                self._last_wall_contact_log_ts = now
            else:
                logger.debug(
                    "Pico wall contact detected on %s (throttled).",
                    ", ".join(sorted(rising_channels)),
                )
            return True
        return False


def _parse_yeda_value(line: str) -> float | None:
    """Extract and invert the Yeda ECG value from one ``sensory.print()`` line.

    The Pi Pico transmits ``1 / adc_voltage`` (``reciprocal=True``).  We
    invert the value back to the original ECG amplitude before peak detection.

    Args:
        line: One decoded text line from the serial port, e.g.::

            ``"Yeda0:(0.00234,) MOI0:(0.0,) MOI1:(1.0,)"``

    Returns:
        The original ECG amplitude as a float, or ``None`` if the line does
        not contain a valid Yeda reading or the value is zero (would cause
        division by zero on inversion).
    """
    match = _YEDA_RE.search(line)
    if not match:
        return None

    try:
        reciprocal_value = float(match.group(1))
    except ValueError:
        return None

    if reciprocal_value == 0.0:
        return None

    # Invert to recover original ECG orientation.
    return 1.0 / reciprocal_value


def _parse_moi_values(line: str) -> dict[str, float]:
    """Extract all MOI channel values from one serial line."""
    matches = _MOI_RE.findall(line)
    if not matches:
        return {}

    values: dict[str, float] = {}
    for channel, raw_value in matches:
        try:
            values[channel] = float(raw_value)
        except ValueError:
            continue
    return values


class PicoECGSensor(BaseSensor):
    """Real hardware ECG sensor driver for a Pi Pico running YLab Zero firmware.

    Reads raw ECG samples from the USB serial port, performs host-side R-peak
    detection, and emits RR intervals via ``raw_rr_interval_received`` —
    matching the signal contract of :class:`~app.hardware.mock_sensors.MockHRVSensor`
    so the two can be swapped without any other code changes.

    Signals:
        raw_rr_interval_received (float, float):
            Emitted with ``(rr_interval_ms, timestamp_s)`` for each detected
            R-peak pair.
        connection_status_changed (bool, str):
            Emitted when the connection state changes.  The bool is ``True``
            when connected, ``False`` on error.  The str contains a
            human-readable description.

    Args:
        port: Serial device path.  Defaults to :data:`~app.utils.config.PICO_ECG_PORT`.
        baud: Baud rate.  Defaults to :data:`~app.utils.config.PICO_ECG_BAUD`.
        parent: Qt parent object.
    """

    raw_rr_interval_received  = pyqtSignal(float, float)   # (rr_ms, timestamp_s)
    wall_contact_detected     = pyqtSignal()
    connection_status_changed = pyqtSignal(bool, str)       # (connected, message)

    def __init__(
        self,
        port: str | None = None,
        baud: int = PICO_ECG_BAUD,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if port is None:
            detected = find_pico_port()
            if detected is not None:
                self._port = detected
                logger.info("Auto-detected Pico port: %s", detected)
            else:
                self._port = PICO_ECG_PORT
                logger.warning(
                    "Pico not auto-detected; falling back to config port %s.", PICO_ECG_PORT
                )
        else:
            self._port = port
        self._baud = baud
        self._worker: _SerialWorker | None = None

    def start(self) -> None:
        """Open the serial port and begin streaming ECG data.

        Creates a background :class:`_SerialWorker` thread.  All data arrives
        via the ``raw_rr_interval_received`` signal — never by direct method
        calls — keeping the UI thread free.
        """
        if self._running:
            logger.warning("PicoECGSensor.start() called while already running.")
            return

        self._worker = _SerialWorker(self._port, self._baud, parent=None)
        self._worker.setObjectName("PicoECGSerialWorker")
        self._worker.rr_interval_ready.connect(self._on_rr_interval)
        self._worker.wall_contact_detected.connect(self.wall_contact_detected)
        self._worker.connection_lost.connect(self._on_connection_lost)
        self._worker.finished.connect(self._on_worker_finished)

        self._running = True
        self._worker.start()
        self.connection_status_changed.emit(True, f"Connected to {self._port}")
        logger.info("PicoECGSensor started on %s @ %d baud.", self._port, self._baud)

    def stop(self) -> None:
        """Stop streaming and release the serial port.

        Requests the background thread to exit and waits up to 3 seconds for
        it to finish cleanly.
        """
        if not self._running and self._worker is None:
            return

        self._running = False

        if self._worker is not None:
            # Disconnect to prevent signals during shutdown
            try:
                self._worker.rr_interval_ready.disconnect(self._on_rr_interval)
                self._worker.wall_contact_detected.disconnect(self.wall_contact_detected)
                self._worker.connection_lost.disconnect(self._on_connection_lost)
            except (TypeError, RuntimeError):
                pass

            logger.debug("Stopping PicoECG worker thread...")
            self._worker.request_stop()
            if not self._worker.wait(3000):
                logger.warning("Serial worker did not exit within 3 s — terminating.")
                self._worker.terminate()
                self._worker.wait()
            self._worker = None

        self.connection_status_changed.emit(False, "Disconnected")
        logger.info("PicoECGSensor stopped.")

    # ------------------------------------------------------------------
    # Private slots (invoked from worker thread via Qt signals)
    # ------------------------------------------------------------------

    @pyqtSlot(float, float)
    def _on_rr_interval(self, rr_ms: float, timestamp: float) -> None:
        """Forward a detected RR interval to the processing layer."""
        self.raw_rr_interval_received.emit(rr_ms, timestamp)

    @pyqtSlot(str)
    def _on_connection_lost(self, error_message: str) -> None:
        """Handle serial port loss gracefully."""
        self._running = False
        self.connection_status_changed.emit(False, f"Connection lost: {error_message}")
        logger.error("PicoECGSensor connection lost: %s", error_message)

    @pyqtSlot()
    def _on_worker_finished(self) -> None:
        """Clean up after the worker thread exits."""
        self._worker = None
        logger.debug("PicoECGSensor worker thread finished.")
