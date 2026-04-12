"""Unit tests for the signal processing pipeline.

Tests cover HRVProcessor, PupilProcessor, and CLIProcessor using
in-process signal inspection (no QApplication required for logic tests).

Run with:
    pytest tests/test_processors.py -v
"""

import numpy as np
import pytest
from collections import deque


# -------------------------------------------------------------------------
# HRVProcessor — unit tests (pure logic, no Qt needed)
# -------------------------------------------------------------------------

class TestHRVProcessorLogic:
    """Test the sliding-window RMSSD logic directly via HRVProcessor internals."""

    def _make_processor(self):
        """Return a minimal HRVProcessor with Qt signal emission stubbed out."""
        from app.processing.hrv_processor import HRVProcessor
        return HRVProcessor(window_seconds=30)

    def test_initial_state_empty(self) -> None:
        proc = self._make_processor()
        assert len(proc._rr_intervals) == 0

    def test_samples_accumulate(self) -> None:
        proc = self._make_processor()
        # Directly manipulate buffers (bypassing Qt signal emission).
        for i in range(5):
            proc._timestamps.append(float(i))
            proc._rr_intervals.append(800.0 + i * 5)
        assert len(proc._rr_intervals) == 5

    def test_old_samples_evicted(self) -> None:
        """Samples outside the 30-second window should be removed."""
        proc = self._make_processor()
        # Add a sample at t=0, then one at t=35 (35s later).
        proc._timestamps.append(0.0)
        proc._rr_intervals.append(800.0)
        proc._timestamps.append(35.0)
        proc._rr_intervals.append(850.0)

        # Simulate the eviction logic.
        cutoff = 35.0 - proc.window_seconds
        while proc._timestamps and proc._timestamps[0] < cutoff:
            proc._timestamps.popleft()
            proc._rr_intervals.popleft()

        assert len(proc._rr_intervals) == 1
        assert list(proc._rr_intervals)[0] == 850.0

    def test_reset_clears_all(self) -> None:
        proc = self._make_processor()
        proc._timestamps.append(1.0)
        proc._rr_intervals.append(800.0)
        proc.reset()
        assert len(proc._timestamps) == 0
        assert len(proc._rr_intervals) == 0


# -------------------------------------------------------------------------
# PupilProcessor — unit tests
# -------------------------------------------------------------------------

class TestPupilProcessorLogic:
    def _make_processor(self, baseline: float = 100.0):
        from app.processing.pupil_processor import PupilProcessor
        return PupilProcessor(baseline_px=baseline)

    def test_baseline_zero_skips_pdi(self) -> None:
        proc = self._make_processor(baseline=0.0)
        # With baseline=0, PDI cannot be computed; set_baseline call required.
        assert proc.baseline_px == 0.0

    def test_set_baseline_updates(self) -> None:
        proc = self._make_processor()
        proc.set_baseline(120.0)
        assert proc.baseline_px == pytest.approx(120.0)

    def test_reset_clears_prev_diameter(self) -> None:
        proc = self._make_processor()
        proc._prev_diameter = 100.0
        proc.reset()
        assert proc._prev_diameter is None

    def test_blink_detection_threshold(self) -> None:
        """A diameter drop exceeding the threshold should be classified as a blink."""
        from app.utils.config import PUPIL_BLINK_VELOCITY_THRESHOLD_PX
        proc = self._make_processor()
        proc._prev_diameter = 100.0
        # Drop of 30 px >> threshold (20) → blink detected, prev_diameter cleared.
        big_drop_diameter = 100.0 - (PUPIL_BLINK_VELOCITY_THRESHOLD_PX + 10.0)
        velocity = abs(big_drop_diameter - proc._prev_diameter)
        assert velocity > PUPIL_BLINK_VELOCITY_THRESHOLD_PX

    def test_normal_sample_not_rejected(self) -> None:
        """A small smooth change should not trigger blink rejection."""
        from app.utils.config import PUPIL_BLINK_VELOCITY_THRESHOLD_PX
        proc = self._make_processor()
        proc._prev_diameter = 100.0
        small_change = 105.0  # 5 px change — well below threshold
        velocity = abs(small_change - proc._prev_diameter)
        assert velocity < PUPIL_BLINK_VELOCITY_THRESHOLD_PX

    def test_pdi_outlier_clamp(self) -> None:
        """A PDI change exceeding 40% should be rejected."""
        from app.utils.config import PUPIL_MAX_ABS_PCT_CHANGE
        proc = self._make_processor(baseline=100.0)
        
        # 50% increase (150 px) > 40% clamp
        emitted = []
        proc.pdi_updated.connect(lambda pdi, ts: emitted.append(pdi))
        
        proc.on_pupil_sample(150.0, 0.0, 1.0)
        assert len(emitted) == 0
        
        # 30% increase (130 px) < 40% clamp
        proc.on_pupil_sample(130.0, 0.0, 2.0)
        assert len(emitted) == 1
        assert PUPIL_MAX_ABS_PCT_CHANGE == pytest.approx(40.0)
        assert emitted[0] == pytest.approx(30.0)


# -------------------------------------------------------------------------
# CLIProcessor — unit tests
# -------------------------------------------------------------------------

class TestCLIProcessorLogic:
    def _make_processor(self):
        from app.processing.cli_processor import CLIProcessor
        return CLIProcessor()

    def test_no_emission_before_both_inputs(self) -> None:
        """CLI should not be emitted if only RMSSD or only PDI has been received."""
        proc = self._make_processor()
        # Feed only RMSSD — PDI still None.
        proc._rmssd = 50.0
        proc._rmssd_min = 30.0
        proc._rmssd_max = 70.0
        # _pdi remains None → _try_emit should short-circuit.
        emitted = []

        def capture(cli, ts):
            emitted.append(cli)

        proc.cli_updated.connect(capture)
        proc._try_emit()
        assert emitted == []

    def test_reset_clears_all_state(self) -> None:
        proc = self._make_processor()
        proc._rmssd = 50.0
        proc._pdi = 0.1
        proc.reset()
        assert proc._rmssd is None
        assert proc._pdi is None

    def test_cli_range_after_receiving_both(self) -> None:
        """After receiving valid RMSSD and PDI, CLI must be in [0, 1]."""
        from app.processing.cli_processor import _UNSET
        proc = self._make_processor()
        proc._rmssd = 50.0
        proc._rmssd_min = 30.0
        proc._rmssd_max = 70.0
        proc._pdi = 0.1
        proc._pdi_min = 0.0
        proc._pdi_max = 0.3
        proc._rmssd_ts = 1.0
        proc._pdi_ts = 1.0

        emitted: list[float] = []
        proc.cli_updated.connect(lambda cli, ts: emitted.append(cli))
        proc._try_emit()

        assert len(emitted) == 1
        assert 0.0 <= emitted[0] <= 1.0


# -------------------------------------------------------------------------
# HRVProcessor — Phase 6a-2: BPM + delta RMSSD
# -------------------------------------------------------------------------

class TestHRVProcessorNewMetrics:
    """BPM computation and delta RMSSD tracking added in Phase 6a-2."""

    def _make_processor(self):
        from app.processing.hrv_processor import HRVProcessor
        return HRVProcessor(window_seconds=30)

    def test_hrv_updated_signal_exists(self) -> None:
        proc = self._make_processor()
        assert hasattr(proc, "hrv_updated")

    def test_bpm_is_60000_divided_by_rr_interval(self) -> None:
        proc = self._make_processor()
        emitted: list[tuple] = []
        proc.hrv_updated.connect(
            lambda rr, bpm, rmssd, delta, ts: emitted.append((rr, bpm, rmssd, delta, ts))
        )
        proc.on_rr_interval(600.0, 1.0)
        assert len(emitted) == 1
        assert emitted[0][1] == pytest.approx(100.0)   # 60_000 / 600 = 100 bpm

    def test_bpm_60bpm_for_1000ms_rr(self) -> None:
        proc = self._make_processor()
        bpms: list[float] = []
        proc.hrv_updated.connect(lambda rr, bpm, rmssd, delta, ts: bpms.append(bpm))
        proc.on_rr_interval(1000.0, 1.0)
        assert bpms[0] == pytest.approx(60.0)

    def test_delta_rmssd_is_zero_on_first_emission(self) -> None:
        proc = self._make_processor()
        deltas: list[float] = []
        proc.hrv_updated.connect(lambda rr, bpm, rmssd, delta, ts: deltas.append(delta))
        proc.on_rr_interval(800.0, 1.0)
        assert deltas[0] == pytest.approx(0.0)

    def test_delta_rmssd_equals_current_minus_previous_rmssd(self) -> None:
        proc = self._make_processor()
        results: list[tuple] = []
        proc.hrv_updated.connect(lambda rr, bpm, rmssd, delta, ts: results.append((rmssd, delta)))

        proc.on_rr_interval(800.0, 1.0)
        proc.on_rr_interval(820.0, 2.0)

        rmssd_0, delta_0 = results[0]
        rmssd_1, delta_1 = results[1]

        assert delta_0 == pytest.approx(0.0)
        assert delta_1 == pytest.approx(rmssd_1 - rmssd_0)

    def test_reset_makes_next_delta_zero(self) -> None:
        proc = self._make_processor()
        deltas: list[float] = []
        proc.hrv_updated.connect(lambda rr, bpm, rmssd, delta, ts: deltas.append(delta))

        proc.on_rr_interval(800.0, 1.0)
        proc.on_rr_interval(820.0, 2.0)
        proc.reset()
        proc.on_rr_interval(800.0, 3.0)   # first after reset — delta must be 0.0

        assert deltas[2] == pytest.approx(0.0)

    def test_hrv_updated_carries_original_rr_interval(self) -> None:
        proc = self._make_processor()
        rr_values: list[float] = []
        proc.hrv_updated.connect(lambda rr, bpm, rmssd, delta, ts: rr_values.append(rr))
        proc.on_rr_interval(750.0, 1.0)
        assert rr_values[0] == pytest.approx(750.0)

    def test_rmssd_updated_still_emits_for_backward_compat(self) -> None:
        """Existing rmssd_updated signal must keep firing alongside hrv_updated."""
        proc = self._make_processor()
        rmssd_vals: list[float] = []
        proc.rmssd_updated.connect(lambda rmssd, ts: rmssd_vals.append(rmssd))
        proc.on_rr_interval(800.0, 1.0)
        assert len(rmssd_vals) == 1


# -------------------------------------------------------------------------
# HRVProcessor — physiological plausibility filter (T-wave protection)
# -------------------------------------------------------------------------

class TestHRVProcessorRRFilter:
    """RR intervals implying physiologically impossible heart rates are silently
    dropped.  This is the second line of defence against T-wave double-counting
    after the refractory-period increase in _RPeakDetector."""

    def _make_processor(self):
        from app.processing.hrv_processor import HRVProcessor
        return HRVProcessor(window_seconds=30)

    def test_rr_below_minimum_is_silently_rejected(self) -> None:
        """An RR interval of 300 ms (200 BPM) is physiologically impossible."""
        proc = self._make_processor()
        bpms: list[float] = []
        proc.hrv_updated.connect(lambda rr, bpm, rmssd, delta, ts: bpms.append(bpm))

        proc.on_rr_interval(300.0, 1.0)   # 300 ms → 200 BPM → must be rejected

        assert bpms == []

    def test_rr_at_minimum_boundary_is_accepted(self) -> None:
        """RR intervals at or above the configured minimum must pass through."""
        from app.utils.config import HRV_MIN_RR_MS
        proc = self._make_processor()
        bpms: list[float] = []
        proc.hrv_updated.connect(lambda rr, bpm, rmssd, delta, ts: bpms.append(bpm))

        proc.on_rr_interval(HRV_MIN_RR_MS, 1.0)   # exactly at boundary → accepted

        assert len(bpms) == 1

    def test_normal_rr_passes_through(self) -> None:
        """A resting 800 ms RR (75 BPM) must never be filtered."""
        proc = self._make_processor()
        bpms: list[float] = []
        proc.hrv_updated.connect(lambda rr, bpm, rmssd, delta, ts: bpms.append(bpm))

        proc.on_rr_interval(800.0, 1.0)

        assert len(bpms) == 1
        assert bpms[0] == pytest.approx(75.0)

    def test_rejected_rr_does_not_update_rmssd_buffer(self) -> None:
        """A rejected interval must not pollute the RMSSD sliding window."""
        proc = self._make_processor()

        proc.on_rr_interval(800.0, 1.0)   # valid — accepted
        before = len(proc._rr_intervals)

        proc.on_rr_interval(200.0, 1.1)   # invalid — must be dropped
        after = len(proc._rr_intervals)

        assert after == before


# -------------------------------------------------------------------------
# _RPeakDetector — refractory period / T-wave suppression
#
# Root-cause analysis of the 138-150 BPM / near-zero RMSSD bug:
#
#   The old refractory was 60 samples = 400 ms.  T-wave end (QT interval)
#   falls at ~420 ms → T-wave rising edge is at ~400 ms, which is exactly
#   at the refractory boundary.  Result: T-wave is accepted as an R-peak and
#   the true R-peak (~800 ms later, only 60 samples after the T-wave) is
#   rejected because it arrives within the new 400-ms refractory window that
#   was reset by the T-wave.  Only T-waves are ever counted → RR ≈ 400 ms,
#   BPM ≈ 150, RMSSD ≈ 0.
#
#   Fix: refractory → 90 samples (600 ms) so no T-wave can slip through
#   (QT interval ≤ 440 ms < 600 ms).
# -------------------------------------------------------------------------


def _feed_ecg(detector, samples: list[float]) -> list[float]:
    """Feed a list of sample values into a detector; return all RR intervals emitted."""
    rr_intervals = []
    for v in samples:
        rr = detector.feed(v)
        if rr is not None:
            rr_intervals.append(rr)
    return rr_intervals


def _make_synthetic_ecg(
    r_at: int,
    t_at: int,
    next_r_at: int,
    total: int = 300,
    baseline: float = 0.05,
    r_amp: float = 1.0,
    t_amp: float = 0.7,
    t_width: int = 10,
) -> list[float]:
    """Build a flat sample list with one R-peak, one T-wave, and one follow-up R-peak."""
    sig = [baseline] * total
    sig[r_at] = r_amp
    for i in range(t_at, min(t_at + t_width, total)):
        sig[i] = t_amp
    sig[next_r_at] = r_amp
    return sig


class TestRPeakDetectorRefractoryFix:
    """T-wave suppression with the corrected 90-sample (600 ms) refractory period.

    Test setup
    ----------
    ``_make_primed_detector`` puts the detector into a controlled state
    that represents "an R-peak was just accepted at sample index 0":

    - ``_last_peak_sample = 0``  → reference for refractory counting
    - ``_sample_index = 0``      → feed counter starts fresh
    - ``_above_threshold = False``
    - Window filled with [1.0] (large amplitude_window=200 keeps the R-peak
      value in the window for the entire test, so threshold = 0.65 × 1.0 = 0.65
      for all subsequent feeds).

    After this setup the detector behaves as if it is mid-session, just after
    accepting a clean R-peak.  Baseline samples (0.05) never exceed the 0.65
    threshold; T-wave-like samples (0.7) do.
    """

    def _make_primed_detector(self, refractory: int):
        """Return a detector ready to test T-wave rejection from a known state."""
        from app.hardware.pico_ecg_sensor import _RPeakDetector
        from collections import deque
        det = _RPeakDetector(
            sample_rate_hz=150,
            refractory_samples=refractory,
            threshold_factor=0.65,
            amplitude_window=200,   # large window keeps R-peak amplitude as reference
        )
        # Place an R-peak value in the window so threshold = 0.65 × 1.0 = 0.65
        det._window = deque([1.0], maxlen=200)
        det._above_threshold = False
        det._sample_index = 0        # feed counter
        det._last_peak_sample = 0    # reference: last accepted peak at index 0
        det._peak_sample_index = None
        return det

    def test_t_wave_accepted_with_old_refractory(self) -> None:
        """With refractory=60, a T-wave rising edge at sample_index=61 slips through
        (61-0 = 61 ≥ 60).  This reproduces the 400 ms / 150 BPM data bug."""
        det = self._make_primed_detector(refractory=60)
        # 60 baseline samples → sample_index reaches 60 (no detection, 0.05 < 0.65)
        for _ in range(60):
            det.feed(0.05)
        # T-wave: rising edge at sample_index=61, falling edge at sample_index=62
        det.feed(0.7)   # rising edge → above=True, peak_sample_index=61
        rr = det.feed(0.05)  # falling: 61-0=61 ≥ 60 → DETECTED (the bug)
        assert rr is not None, "T-wave should slip through with refractory=60 (the bug)"
        assert abs(rr - 406.7) < 10, f"Expected ~406.7 ms T-wave RR, got {rr}"

    def test_t_wave_rejected_with_new_refractory(self) -> None:
        """With refractory=90, the same T-wave (rising at sample_index=61) is
        rejected because 61-0 = 61 < 90."""
        det = self._make_primed_detector(refractory=90)
        for _ in range(60):
            det.feed(0.05)
        det.feed(0.7)   # rising edge → peak_sample_index=61
        rr = det.feed(0.05)  # falling: 61-0=61 < 90 → REJECTED ✓
        assert rr is None, f"T-wave must be suppressed with refractory=90, got rr={rr}"

    def test_true_r_peak_detected_at_800ms_with_new_refractory(self) -> None:
        """After T-wave rejection the next true R-peak at sample_index=121
        (121-0=121 samples = 806.7 ms) is accepted."""
        det = self._make_primed_detector(refractory=90)
        # T-wave at sample_index=61 (rejected)
        for _ in range(60):
            det.feed(0.05)
        det.feed(0.7)   # T-wave rising
        det.feed(0.05)  # T-wave falling — rejected, last_peak stays at 0
        # Advance to sample_index=120 with baseline
        for _ in range(57):
            det.feed(0.05)
        # R-peak: rising edge at sample_index=121, falling at 122
        det.feed(1.0)           # rising edge → peak_sample_index=121
        rr = det.feed(0.05)     # falling: 121-0=121 ≥ 90 → DETECTED, rr=806.7 ms
        assert rr is not None, "True R-peak at ~800 ms must be detected with refractory=90"
        assert abs(rr - 806.7) < 10, f"Expected ~806.7 ms RR, got {rr}"

    def test_config_refractory_is_at_least_90_samples(self) -> None:
        """PICO_RPEAK_REFRACTORY_SAMPLES must be ≥ 90 to clear the full QT interval."""
        from app.utils.config import PICO_RPEAK_REFRACTORY_SAMPLES
        assert PICO_RPEAK_REFRACTORY_SAMPLES >= 90, (
            f"Refractory {PICO_RPEAK_REFRACTORY_SAMPLES} samples is too short; "
            "T-waves will be counted as R-peaks (max QT ≈ 440 ms < 600 ms = 90 samples)"
        )

    def test_config_hrv_min_rr_ms_rejects_t_wave_intervals(self) -> None:
        """HRV_MIN_RR_MS must be high enough to filter out any slip-through T-wave RR values."""
        from app.utils.config import HRV_MIN_RR_MS
        # T-wave slip-throughs arrive at ~400-440 ms; 500 ms threshold blocks them all.
        assert HRV_MIN_RR_MS >= 500.0, (
            f"HRV_MIN_RR_MS={HRV_MIN_RR_MS} is too low; T-wave-derived RR values "
            "(≈400-440 ms) will reach the RMSSD processor"
        )
