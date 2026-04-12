"""Real-time eye tracker driver using the PuRe algorithm via USB camera.

This sensor captures frames from a dedicated USB camera, detects the pupil
using the PuRe (Santini et al., 2018) algorithm, and emits raw diameter
measurements in pixels.
"""

import sys
import time
import cv2
import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app.hardware.base_sensor import BaseSensor
from app.utils.config import EYE_TRACKER_CAMERA_INDEX, EYE_PUPIL_DETECTION_ZOOM
from app.utils.logger import get_logger

logger = get_logger(__name__)


class _PupilWorker(QThread):
    """Background thread for camera capture and pupil detection.

    Uses the pypupilext (PuRe) detector with ROI optimization and
    center-position smoothing.
    """
    raw_pupil_received = pyqtSignal(float, float, float)
    connection_status_changed = pyqtSignal(bool, str)

    def __init__(self, camera_index: int) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._running = True

    def run(self) -> None:
        """Main detection loop."""
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            if sys.platform == "darwin":
                msg = (
                    f"Eye tracker camera (index {self._camera_index}) could not be opened. "
                    "On macOS this is usually a camera permission issue. "
                    "Fix: System Settings → Privacy & Security → Camera → "
                    "enable access for Terminal (or VS Code), then restart the app."
                )
            else:
                msg = (
                    f"Eye tracker camera (index {self._camera_index}) not found or could not be opened. "
                    "Check that the USB eye tracker is connected and no other app is using it."
                )
            logger.error(msg)
            self.connection_status_changed.emit(False, msg)
            return

        self.connection_status_changed.emit(True, "Eye tracker connected")

        try:
            import pypupilext as pp  # type: ignore
            detector = pp.PuRe()
            using_fallback = False
        except ImportError:
            logger.warning("pypupilext not found. Using simple OpenCV fallback for pupil detection.")

            class DummyPupil:
                def __init__(self, cx, cy, diameter, is_valid, meta=None):
                    self.center = (cx, cy)
                    self._diameter = diameter
                    self._valid = is_valid
                    self.meta = meta or {}

                def valid(self, conf):
                    return self._valid

                def diameter(self):
                    return self._diameter

            class FallbackPuRe:
                def __init__(self):
                    self._prev_center = None
                    self._prev_diameter = None
                    self._frame_index = 0
                    self._jump_candidate = None
                    self._jump_candidate_count = 0

                def runWithConfidence(self, gray_img):
                    self._frame_index += 1

                    # Contrast enhancement for low-contrast IR / USB eye cameras.
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                    gray_img = clahe.apply(gray_img)

                    blurred = cv2.GaussianBlur(gray_img, (7, 7), 0)
                    _, thresh = cv2.threshold(
                        blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
                    )

                    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                    mask = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
                    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

                    contours, _ = cv2.findContours(
                        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )

                    h, w = gray_img.shape
                    img_area = float(h * w)

                    # Tune these bounds to your setup if needed.
                    min_area = max(20.0, img_area * 0.00015)
                    max_area = img_area * 0.04

                    frame_center = (float(w) / 2.0, float(h) / 2.0)
                    target = self._prev_center if self._prev_center is not None else frame_center
                    prev_d = self._prev_diameter

                    best = None
                    best_score = -1.0

                    for cnt in contours:
                        area = float(cv2.contourArea(cnt))
                        if area < min_area or area > max_area:
                            continue

                        perimeter = float(cv2.arcLength(cnt, True))
                        if perimeter <= 0.0:
                            continue

                        circularity = float((4.0 * np.pi * area) / (perimeter * perimeter))
                        if circularity < 0.45:
                            continue

                        if len(cnt) >= 5:
                            (cx, cy), (axis_a, axis_b), _angle = cv2.fitEllipse(cnt)
                            major = float(max(axis_a, axis_b))
                            minor = float(min(axis_a, axis_b))
                            if major <= 0.0 or minor <= 0.0:
                                continue
                            diameter = (major + minor) / 2.0
                            aspect = minor / major
                        else:
                            (cx, cy), radius = cv2.minEnclosingCircle(cnt)
                            diameter = float(radius) * 2.0
                            aspect = 1.0

                        if diameter < 5.0 or diameter > float(min(h, w)) * 0.18:
                            continue
                        if aspect < 0.55:
                            continue

                        cnt_mask = np.zeros_like(gray_img, dtype=np.uint8)
                        cv2.drawContours(cnt_mask, [cnt], -1, 255, -1)
                        mean_intensity = float(cv2.mean(blurred, mask=cnt_mask)[0])
                        darkness = max(0.0, min(1.0, (255.0 - mean_intensity) / 255.0))

                        dist = float(np.hypot(cx - target[0], cy - target[1]))
                        center_penalty = min(1.0, dist / max(1.0, np.hypot(w, h)))

                        area_score = min(1.0, area / (img_area * 0.02))

                        if prev_d is not None and prev_d > 0.0:
                            diameter_ratio = diameter / prev_d
                            diameter_jump_penalty = min(1.0, abs(np.log(max(diameter_ratio, 1e-6))) / np.log(2.0))
                            diameter_consistency = 1.0 - diameter_jump_penalty
                        else:
                            diameter_ratio = 1.0
                            diameter_consistency = 0.5

                        score = (
                            2.0 * circularity
                            + 1.8 * aspect
                            + 1.0 * darkness
                            + 1.4 * (1.0 - center_penalty)
                            + 1.1 * diameter_consistency
                            + 0.3 * area_score
                        )

                        candidate = {
                            "cx": float(cx),
                            "cy": float(cy),
                            "diameter": float(diameter),
                            "area": float(area),
                            "circularity": float(circularity),
                            "aspect": float(aspect),
                            "darkness": float(darkness),
                            "score": float(score),
                            "diameter_ratio": float(diameter_ratio),
                            "frame_index": int(self._frame_index),
                        }

                        if score > best_score:
                            best_score = score
                            best = candidate

                    if best is None:
                        return DummyPupil(
                            frame_center[0],
                            frame_center[1],
                            0.0,
                            False,
                            meta={"method": "fallback", "status": "none"},
                        )

                    # Temporal plausibility check: reject impossible single-frame jumps.
                    accept = True
                    if prev_d is not None and prev_d > 0.0:
                        ratio = best["diameter"] / prev_d
                        if ratio > 1.6 or ratio < 0.62:
                            accept = False

                            jump_signature = (
                                round(best["cx"], 1),
                                round(best["cy"], 1),
                                round(best["diameter"], 1),
                            )

                            if self._jump_candidate == jump_signature:
                                self._jump_candidate_count += 1
                            else:
                                self._jump_candidate = jump_signature
                                self._jump_candidate_count = 1

                            # Only accept a large change if it persists for multiple frames.
                            if self._jump_candidate_count >= 3:
                                accept = True

                            if self._frame_index % 90 == 0:
                                logger.info(
                                    "Fallback rejected jump candidate: d=%.2f prev=%.2f ratio=%.2f area=%.1f circ=%.2f aspect=%.2f score=%.2f",
                                    best["diameter"],
                                    prev_d,
                                    ratio,
                                    best["area"],
                                    best["circularity"],
                                    best["aspect"],
                                    best["score"],
                                )
                        else:
                            self._jump_candidate = None
                            self._jump_candidate_count = 0

                    if not accept:
                        return DummyPupil(
                            target[0],
                            target[1],
                            float(prev_d if prev_d is not None else 0.0),
                            False,
                            meta={"method": "fallback", "status": "jump_rejected"},
                        )

                    self._prev_center = (best["cx"], best["cy"])
                    self._prev_diameter = best["diameter"]

                    return DummyPupil(
                        best["cx"],
                        best["cy"],
                        best["diameter"],
                        True,
                        meta={
                            "method": "fallback",
                            "status": "ok",
                            "area": best["area"],
                            "circularity": best["circularity"],
                            "aspect": best["aspect"],
                            "darkness": best["darkness"],
                            "score": best["score"],
                            "diameter_ratio": best["diameter_ratio"],
                            "frame_index": best["frame_index"],
                        },
                    )

            detector = FallbackPuRe()
            using_fallback = True

        # Detection state
        last_good_center = None
        last_good_diameter = None
        last_good_time = 0.0
        smoothed_center = None
        smoothed_diameter = None

        # Hyperparameters
        roi_size = 96
        bootstrap_roi_size = 96
        alpha = 0.3
        diameter_alpha = 0.22
        confidence_threshold = 0.35
        hold_time = 0.5  # seconds to hold position during blinks/loss

        if using_fallback:
            logger.info(
                "Fallback detector measurement: fitted ellipse/enclosing-circle diameter in px."
            )

        logger.info("Pupil detection worker started.")

        while self._running:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Pupil worker: failed to capture frame.")
                break

            gray_native = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            zoom_factor = max(1.0, float(EYE_PUPIL_DETECTION_ZOOM))
            zoom_x1 = 0
            zoom_y1 = 0

            if zoom_factor > 1.0:
                h_native, w_native = gray_native.shape
                crop_w = max(16, int(round(w_native / zoom_factor)))
                crop_h = max(16, int(round(h_native / zoom_factor)))
                zoom_x1 = max(0, (w_native - crop_w) // 2)
                zoom_y1 = max(0, (h_native - crop_h) // 2)
                zoom_x2 = min(w_native, zoom_x1 + crop_w)
                zoom_y2 = min(h_native, zoom_y1 + crop_h)
                gray_crop = gray_native[zoom_y1:zoom_y2, zoom_x1:zoom_x2]
                gray = cv2.resize(
                    gray_crop, (w_native, h_native), interpolation=cv2.INTER_LINEAR
                )
            else:
                gray = gray_native

            h, w = gray.shape
            pupil = None
            cx, cy = 0.0, 0.0

            # 1. Try ROI optimization
            if last_good_center is not None:
                cx_zoom = (last_good_center[0] - zoom_x1) * zoom_factor
                cy_zoom = (last_good_center[1] - zoom_y1) * zoom_factor
                cx_roi, cy_roi = int(cx_zoom), int(cy_zoom)
                x1 = max(0, cx_roi - roi_size)
                x2 = min(w, cx_roi + roi_size)
                y1 = max(0, cy_roi - roi_size)
                y2 = min(h, cy_roi + roi_size)

                gray_roi = gray[y1:y2, x1:x2]
                pupil_roi = detector.runWithConfidence(gray_roi)

                if pupil_roi.valid(confidence_threshold):
                    px, py = pupil_roi.center
                    cx, cy = px + x1, py + y1
                    pupil = pupil_roi

            # 2. Bootstrap in a center ROI
            if pupil is None:
                cx_mid, cy_mid = w // 2, h // 2
                x1 = max(0, cx_mid - bootstrap_roi_size)
                x2 = min(w, cx_mid + bootstrap_roi_size)
                y1 = max(0, cy_mid - bootstrap_roi_size)
                y2 = min(h, cy_mid + bootstrap_roi_size)
                gray_bootstrap = gray[y1:y2, x1:x2]
                pupil_bootstrap = detector.runWithConfidence(gray_bootstrap)

                if pupil_bootstrap.valid(confidence_threshold):
                    px, py = pupil_bootstrap.center
                    cx, cy = px + x1, py + y1
                    pupil = pupil_bootstrap

            # 3. Final fallback to full frame
            if pupil is None:
                pupil_full = detector.runWithConfidence(gray)
                if pupil_full.valid(confidence_threshold):
                    cx, cy = pupil_full.center
                    pupil = pupil_full

            # 4. Process detection
            now = time.time()
            if pupil is not None:
                diameter = float(pupil.diameter())

                # Convert coordinates/diameter from zoomed frame back to native pixels.
                cx = zoom_x1 + (cx / zoom_factor)
                cy = zoom_y1 + (cy / zoom_factor)
                diameter = diameter / zoom_factor

                # Center smoothing
                if smoothed_center is None:
                    smoothed_center = (cx, cy)
                else:
                    sx = alpha * cx + (1 - alpha) * smoothed_center[0]
                    sy = alpha * cy + (1 - alpha) * smoothed_center[1]
                    smoothed_center = (sx, sy)

                cx, cy = smoothed_center

                # Diameter smoothing
                if smoothed_diameter is None:
                    smoothed_diameter = diameter
                else:
                    smoothed_diameter = (
                        diameter_alpha * diameter
                        + (1.0 - diameter_alpha) * smoothed_diameter
                    )

                diameter = float(smoothed_diameter)

                last_good_center = (cx, cy)
                last_good_diameter = diameter
                last_good_time = now

                self.raw_pupil_received.emit(float(diameter), 0.0, now)

                if using_fallback:
                    meta = getattr(pupil, "meta", {})
                    frame_idx = int(meta.get("frame_index", 0))
                    if frame_idx > 0 and frame_idx % 120 == 0:
                        logger.info(
                            "Fallback pupil measure: d=%.2f px cx=%.1f cy=%.1f area=%.1f circ=%.2f aspect=%.2f ratio=%.2f score=%.2f",
                            float(diameter),
                            float(cx),
                            float(cy),
                            float(meta.get("area", 0.0)),
                            float(meta.get("circularity", 0.0)),
                            float(meta.get("aspect", 0.0)),
                            float(meta.get("diameter_ratio", 1.0)),
                            float(meta.get("score", 0.0)),
                        )

            elif last_good_center is not None and (now - last_good_time) < hold_time:
                # Brief blink/loss: hold state briefly
                pass
            else:
                last_good_center = None
                last_good_diameter = None
                smoothed_center = None
                smoothed_diameter = None

            self.msleep(33)

        cap.release()
        logger.info("Pupil detection worker stopped.")

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._running = False
        self.wait()


class EyeTrackerSensor(BaseSensor):
    """Real eye tracker driver using the PuRe algorithm.

    Signals:
        raw_pupil_received (float, float, float):
            Emitted with ``(left_px, right_px, timestamp_s)``.
        connection_status_changed (bool, str):
            Emitted when the camera is opened or lost.
    """
    raw_pupil_received = pyqtSignal(float, float, float)
    connection_status_changed = pyqtSignal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: _PupilWorker | None = None

    def start(self) -> None:
        """Start the camera capture and detection thread."""
        if self._worker and self._worker.isRunning():
            return

        self._worker = _PupilWorker(camera_index=EYE_TRACKER_CAMERA_INDEX)
        self._worker.raw_pupil_received.connect(self.raw_pupil_received)
        self._worker.connection_status_changed.connect(self.connection_status_changed)
        self._worker.start()
        logger.info("EyeTrackerSensor started.")

    def stop(self) -> None:
        """Stop the background thread and release resources."""
        if self._worker:
            self._worker.stop()
            self._worker = None
        logger.info("EyeTrackerSensor stopped.")