"""Runtime configuration constants for BioTrace.

All thresholds, hardware settings, and algorithm weights live here.
No magic numbers anywhere else in the codebase.

To change behaviour, edit these values — no other file should need touching.
"""

# ---------------------------------------------------------------------------
# Hardware — Serial / USB
# ---------------------------------------------------------------------------

HRV_SENSOR_PORT: str = "/dev/tty.usbserial-0001"  # macOS default; override as needed
HRV_SENSOR_BAUD: int = 115200

EYE_TRACKER_PORT: str = "/dev/tty.usbserial-0002"
EYE_TRACKER_BAUD: int = 115200

# Eye tracker — USB camera (separate from endoscopy camera)
EYE_TRACKER_CAMERA_INDEX: int = 0
# Center-crop zoom used by pupil detection (1.0 disables zoom).
EYE_PUPIL_DETECTION_ZOOM: float = 1.3

CAMERA_INDEX: int = 1  # OpenCV camera index (usually 1 for external USB on laptops)

# Number of frames to attempt during camera warmup before declaring failure.
# Covers the macOS/AVFoundation delay where isOpened()=True before streaming starts.
CAMERA_WARMUP_FRAMES: int = 60  # ~2 seconds at 30 fps

# Video recording output settings.
SESSIONS_DIR: str = "sessions"
VIDEO_RECORDINGS_DIR: str = "recordings"  # legacy, replaced by session-specific subfolders
VIDEO_RECORDING_FPS_FALLBACK: float = 30.0
VIDEO_RECORDING_FOURCC: str = "mp4v"

# ---------------------------------------------------------------------------
# Hardware — Raspberry Pi Pico ECG (YLab Zero firmware)
# ---------------------------------------------------------------------------

# Set to True to use the real Pico over USB serial; False uses MockHRVSensor.
USE_PICO_ECG: bool = True

# Set to True when a real eye tracker is physically connected; False disables
# MockEyeTracker so no fake pupil/PDI/CLI data appears in the live session.
USE_EYE_TRACKER: bool = True

# USB serial port for the Pi Pico (macOS: /dev/tty.usbmodem*, Linux: /dev/ttyACM*).
PICO_ECG_PORT: str = "/dev/cu.usbmodem1101"
PICO_ECG_BAUD: int = 115200

# Yeda analog ECG sensor sample rate (set in firmware: 1.0/150 interval).
PICO_ECG_SAMPLE_RATE_HZ: int = 150

# R-peak detection: number of recent samples used to estimate signal amplitude.
PICO_RPEAK_AMPLITUDE_WINDOW: int = 150  # 1.0 s at 150 Hz

# R-peak detection: minimum samples between two accepted peaks.
# 600 ms at 150 Hz → maximum detectable HR ≈ 100 BPM.
# A longer refractory suppresses T-wave double-counting (QT interval is
# typically 350–440 ms, so T-waves arrive before this window expires).
PICO_RPEAK_REFRACTORY_SAMPLES: int = 90  # 600 ms at 150 Hz

# R-peak detection: peak threshold as a fraction of the adaptive amplitude (0–1).
# T-waves are typically 25–50 % of R-peak amplitude; 0.65 keeps a safe margin.
PICO_RPEAK_THRESHOLD_FACTOR: float = 0.65

# ---------------------------------------------------------------------------
# Signal Processing
# ---------------------------------------------------------------------------

# RMSSD sliding window duration (seconds).
RMSSD_WINDOW_SECONDS: int = 30

# Minimum number of RR intervals required before RMSSD is meaningful.
RMSSD_MIN_SAMPLES: int = 2

# Physiological plausibility filter: RR intervals below this value (ms) are
# discarded by HRVProcessor as noise or T-wave artefacts.
# 500 ms = 120 BPM — safe upper limit for resting/moderate stress states.
HRV_MIN_RR_MS: float = 500.0

# Pupil blink rejection: max drop in pixels per sample.
# Tune after testing on real hardware. Start at 20.
PUPIL_BLINK_VELOCITY_THRESHOLD_PX: float = 20.0

# Pupil outlier clamp: discard if |pupil_pct_change| exceeds this percent.
# 40 % change from baseline is treated as a physiological upper bound.
PUPIL_MAX_ABS_PCT_CHANGE: float = 40.0

# Calibration baseline recording duration (seconds).
CALIBRATION_DURATION_SECONDS: int = 60

# ---------------------------------------------------------------------------
# Cognitive Load Index (CLI)
# ---------------------------------------------------------------------------

# Weights must sum to 1.0.
CLI_WEIGHT_RMSSD: float = 0.5
CLI_WEIGHT_PDI: float = 0.5

# Alert zone thresholds (CLI range 0.0 – 1.0).
CLI_THRESHOLD_LOW: float = 0.33     # green  → yellow boundary
CLI_THRESHOLD_HIGH: float = 0.66    # yellow → red boundary

# Cognitive-load gauge scaling based on pupil % change from baseline.
COGNITIVE_LOAD_MAX_PUPIL_PCT: float = 20.0

# Stress interpretation based on relative RMSSD change from baseline.
STRESS_RMSSD_LOW_DROP_PCT: float = -10.0
STRESS_RMSSD_HIGH_DROP_PCT: float = -40.0

# ---------------------------------------------------------------------------
# Mock Sensor — development / testing
# ---------------------------------------------------------------------------

# Simulated RR interval range (milliseconds).
MOCK_RR_MIN_MS: float = 700.0
MOCK_RR_MAX_MS: float = 1000.0

# Simulated pupil diameter range (pixels/camera units).
MOCK_PUPIL_MIN_PX: float = 80.0
MOCK_PUPIL_MAX_PX: float = 160.0

# How often mock sensors emit new data (milliseconds between signals).
MOCK_EMIT_INTERVAL_MS: int = 1000   # 1 Hz for HRV
MOCK_PUPIL_INTERVAL_MS: int = 100   # 10 Hz for pupil

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH: str = "biotrace.db"

# ---------------------------------------------------------------------------
# Learning Curves
# ---------------------------------------------------------------------------

SCORE_MAX: int = 100.00          # Maximum possible performance score per session
LC_MIN_SESSIONS: int = 5     # Minimum sessions with error data before curve is fitted
