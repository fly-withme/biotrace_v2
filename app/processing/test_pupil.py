import cv2
import pypupilext as pp
import time
import csv

cap = cv2.VideoCapture(0)
detector = pp.PuRe()

baseline_values = []
baseline_duration = 3
start_time = time.time()
baseline_diameter = None

percent_history = []
window_size = 10

last_good_center = None
last_good_diameter = None
last_good_time = 0
hold_time = 0.5

smoothed_center = None
alpha = 0.3   # less rigid

roi_size = 160  # bigger search area

file = open("pupil_data.csv", "w", newline="")
writer = csv.writer(file)
writer.writerow(["time", "diameter", "percent_change_raw", "percent_change_smoothed"])

while True:
    ret, frame = cap.read()
    if not ret:
        print("No frame received")
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    h, w = gray.shape
    pupil = None

    # First try ROI if we already know roughly where the pupil is
    if last_good_center is not None:
        cx_roi, cy_roi = int(last_good_center[0]), int(last_good_center[1])

        x1 = max(0, cx_roi - roi_size)
        x2 = min(w, cx_roi + roi_size)
        y1 = max(0, cy_roi - roi_size)
        y2 = min(h, cy_roi + roi_size)

        gray_roi = gray[y1:y2, x1:x2]
        pupil_roi = detector.runWithConfidence(gray_roi)

        if pupil_roi.valid(0.35):
            px, py = pupil_roi.center
            px += x1
            py += y1
            pupil = pupil_roi
            cx, cy = px, py

    # Fallback: if ROI fails, search full frame
    if pupil is None:
        pupil_full = detector.runWithConfidence(gray)
        if pupil_full.valid(0.35):
            pupil = pupil_full
            cx, cy = pupil.center

    display_text = "Collecting baseline..."

    if pupil is not None:
        diameter = pupil.diameter()
        elapsed = time.time() - start_time

        if smoothed_center is None:
            smoothed_center = (cx, cy)
        else:
            sx = int(alpha * cx + (1 - alpha) * smoothed_center[0])
            sy = int(alpha * cy + (1 - alpha) * smoothed_center[1])
            smoothed_center = (sx, sy)

        cx, cy = smoothed_center

        last_good_center = (cx, cy)
        last_good_diameter = diameter
        last_good_time = time.time()

        if elapsed < baseline_duration:
            baseline_values.append(diameter)
            display_text = f"Collecting baseline... {baseline_duration - elapsed:.1f}s"

        else:
            if baseline_diameter is None and len(baseline_values) > 0:
                baseline_diameter = sum(baseline_values) / len(baseline_values)
                print(f"Baseline diameter: {baseline_diameter:.2f}")

            if baseline_diameter is not None:
                percent_change = ((diameter - baseline_diameter) / baseline_diameter) * 100

                if -40 < percent_change < 40:
                    percent_history.append(percent_change)

                    if len(percent_history) > window_size:
                        percent_history.pop(0)

                    smoothed_change = sum(percent_history) / len(percent_history)

                    display_text = f"Change: {smoothed_change:+.2f}%"
                    print(f"Raw: {percent_change:+.2f}% | Smoothed: {smoothed_change:+.2f}%")

                    writer.writerow([time.time(), diameter, percent_change, smoothed_change])

        cv2.circle(frame, (int(cx), int(cy)), int(diameter / 2), (0, 255, 0), 2)

        x1 = max(0, int(cx - roi_size))
        x2 = min(w, int(cx + roi_size))
        y1 = max(0, int(cy - roi_size))
        y2 = min(h, int(cy + roi_size))
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 1)

    else:
        if last_good_center is not None and (time.time() - last_good_time) < hold_time:
            cx, cy = last_good_center
            cv2.circle(frame, (int(cx), int(cy)), int(last_good_diameter / 2), (0, 255, 0), 2)

    cv2.putText(
        frame,
        display_text,
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 0),
        2
    )

    cv2.imshow("Endoscope Eye Tracker", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
file.close()
cv2.destroyAllWindows()