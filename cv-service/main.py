"""
CV Service — Main Entry Point (MediaPipe CPU version)
Captures webcam frames, runs MediaPipe Pose inference, analyses posture,
and publishes structured JSON events to Kafka.
"""

import json
import logging
import math
import os
import time
import datetime

import cv2
import numpy as np
import mediapipe as mp
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

# ─── Configuration ───────────────────────────────────────────────────────────
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "posture-events")
WEBCAM_INDEX = os.getenv("WEBCAM_INDEX", "0")
FRAME_SKIP = int(os.getenv("FRAME_SKIP", "2"))  # process 1 in N frames
NECK_ANGLE_THRESH = float(
    os.getenv("NECK_ANGLE_THRESH", "155")
)  
USER_ID = os.getenv("USER_ID", "USER-001")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [CV-SERVICE] %(message)s")
log = logging.getLogger(__name__)

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils


def wait_for_kafka(broker: str, retries: int = 15, delay: int = 5) -> KafkaProducer:
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=[broker],
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            log.info("Connected to Kafka at %s", broker)
            return producer
        except NoBrokersAvailable:
            log.warning(
                "Kafka not ready (attempt %d/%d). Retrying in %ds…",
                attempt,
                retries,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError("Could not connect to Kafka after %d attempts" % retries)


def angle_between(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    ba = a - b
    bc = c - b
    cos_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    return math.degrees(math.acos(np.clip(cos_angle, -1.0, 1.0)))


def get_landmark_coords(landmark, w, h):
    return np.array([landmark.x * w, landmark.y * h]), landmark.visibility


def classify_posture(landmarks, w: int, h: int) -> tuple[str, float]:
    l_ear, l_ear_v = get_landmark_coords(
        landmarks.landmark[mp_pose.PoseLandmark.LEFT_EAR], w, h
    )
    r_ear, r_ear_v = get_landmark_coords(
        landmarks.landmark[mp_pose.PoseLandmark.RIGHT_EAR], w, h
    )
    ear, ear_v = (l_ear, l_ear_v) if l_ear_v > r_ear_v else (r_ear, r_ear_v)

    l_sh, l_sh_v = get_landmark_coords(
        landmarks.landmark[mp_pose.PoseLandmark.LEFT_SHOULDER], w, h
    )
    r_sh, r_sh_v = get_landmark_coords(
        landmarks.landmark[mp_pose.PoseLandmark.RIGHT_SHOULDER], w, h
    )
    sh, sh_v = (l_sh, l_sh_v) if l_sh_v > r_sh_v else (r_sh, r_sh_v)

    l_hip, l_hip_v = get_landmark_coords(
        landmarks.landmark[mp_pose.PoseLandmark.LEFT_HIP], w, h
    )
    r_hip, r_hip_v = get_landmark_coords(
        landmarks.landmark[mp_pose.PoseLandmark.RIGHT_HIP], w, h
    )
    hip, hip_v = (l_hip, l_hip_v) if l_hip_v > r_hip_v else (r_hip, r_hip_v)

    if ear_v < 0.15 or sh_v < 0.15:
        return "UNKNOWN", 0.0

    if hip_v < 0.15:
        hip = np.array([sh[0], sh[1] + 100])
        hip_v = 1.0

    neck_angle = angle_between(ear, sh, hip)
    state = "UPRIGHT" if neck_angle >= NECK_ANGLE_THRESH else "SLOUCHING"
    return state, round(neck_angle, 1)


def classify_activity(landmarks, w: int, h: int, prev_wrist_pos: dict) -> str:
    l_wrist, l_wrist_v = get_landmark_coords(
        landmarks.landmark[mp_pose.PoseLandmark.LEFT_WRIST], w, h
    )
    r_wrist, r_wrist_v = get_landmark_coords(
        landmarks.landmark[mp_pose.PoseLandmark.RIGHT_WRIST], w, h
    )

    if l_wrist_v < 0.2 and r_wrist_v < 0.2:
        return "AWAY"

    l_prev = prev_wrist_pos.get("left", l_wrist)
    r_prev = prev_wrist_pos.get("right", r_wrist)

    l_delta = np.linalg.norm(l_wrist - l_prev)
    r_delta = np.linalg.norm(r_wrist - r_prev)
    movement = max(l_delta, r_delta)

    prev_wrist_pos["left"] = l_wrist
    prev_wrist_pos["right"] = r_wrist

    if movement > 50:
        return "STRETCHING"
    elif movement > 5:
        return "TYPING"
    else:
        return "RESTING"


def draw_overlay(
    frame: np.ndarray, landmarks, posture: str, activity: str, analytics: dict
) -> np.ndarray:
    annotated = frame.copy()
    if landmarks:
        mp_drawing.draw_landmarks(annotated, landmarks, mp_pose.POSE_CONNECTIONS)

    color = (0, 255, 0) if posture == "UPRIGHT" else (0, 0, 255)
    h_img, w_img = annotated.shape[:2]

    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (w_img, 115), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, annotated, 0.4, 0, annotated)

    cv2.putText(
        annotated,
        f"Posture : {posture}",
        (10, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        color,
        2,
    )
    cv2.putText(
        annotated,
        f"Activity: {activity}",
        (10, 56),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (255, 255, 255),
        2,
    )
    cv2.putText(
        annotated,
        f"Good%   : {analytics['good_posture_percent']:.1f}%",
        (10, 84),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (255, 200, 0),
        2,
    )
    cv2.putText(
        annotated,
        f"Tracked : {analytics['total_tracked_seconds']:.0f}s",
        (10, 112),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (200, 200, 200),
        2,
    )
    return annotated


def main():
    log.info("Opening video source: %s", WEBCAM_INDEX)
    source = int(WEBCAM_INDEX) if str(WEBCAM_INDEX).isdigit() else WEBCAM_INDEX
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        log.error(
            "Cannot open video source '%s'. "
            "If running in Docker without a webcam, set WEBCAM_INDEX to a video file path "
            "(e.g. WEBCAM_INDEX=/data/test.mp4) and mount it as a volume.",
            source,
        )
        raise RuntimeError("Cannot open video source: %s" % source)

    producer = wait_for_kafka(KAFKA_BROKER)

    frame_id = 0
    total_tracked_seconds = 0.0
    total_good_seconds = 0.0
    total_bad_seconds = 0.0
    prev_wrist_pos = {}
    start_time = time.time()
    prev_frame_time = start_time

    log.info("Starting inference loop…")

    with mp_pose.Pose(
        min_detection_confidence=0.5, min_tracking_confidence=0.5
    ) as pose:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_id += 1
            now = time.time()
            dt = now - prev_frame_time
            prev_frame_time = now

            if frame_id % FRAME_SKIP != 0:
                continue

            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(image_rgb)
            h, w, _ = frame.shape

            presence = "INACTIVE"
            posture_state = "UNKNOWN"
            neck_angle = 0.0
            activity = "AWAY"

            if results.pose_landmarks:
                presence = "ACTIVE"
                posture_state, neck_angle = classify_posture(
                    results.pose_landmarks, w, h
                )
                activity = classify_activity(
                    results.pose_landmarks, w, h, prev_wrist_pos
                )

                total_tracked_seconds += dt
                if posture_state == "UPRIGHT":
                    total_good_seconds += dt
                elif posture_state == "SLOUCHING":
                    total_bad_seconds += dt

            good_pct = (
                (total_good_seconds / total_tracked_seconds * 100)
                if total_tracked_seconds > 0
                else 0.0
            )

            analytics = {
                "total_tracked_seconds": round(total_tracked_seconds, 2),
                "total_good_posture_seconds": round(total_good_seconds, 2),
                "total_bad_posture_seconds": round(total_bad_seconds, 2),
                "good_posture_percent": round(good_pct, 1),
            }

            elapsed_ms = int((now - start_time) * 1000)
            ts_str = str(datetime.timedelta(milliseconds=elapsed_ms))[:-3]

            payload = {
                "frame_id": frame_id,
                "user_id": USER_ID,
                "timestamp": ts_str,
                "status": {
                    "presence": presence,
                    "current_activity": activity,
                    "posture_state": posture_state,
                    "neck_angle": neck_angle,
                },
                "time_analytics": analytics,
            }

            producer.send(KAFKA_TOPIC, payload)

            if os.getenv("DISPLAY"):
                annotated = draw_overlay(
                    frame, results.pose_landmarks, posture_state, activity, analytics
                )
                cv2.imshow("Posture Monitor — CV Service", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    cap.release()
    producer.flush()
    producer.close()
    cv2.destroyAllWindows()
    log.info("CV service shut down.")


if __name__ == "__main__":
    main()
