import json
import logging
import os
import time

import psycopg2
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

# ─── Configuration ───────────────────────────────────────────────────────────
KAFKA_BROKER  = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_TOPIC   = os.getenv("KAFKA_TOPIC", "posture-events")
KAFKA_GROUP   = os.getenv("KAFKA_GROUP", "posture-consumer-group")
PG_DSN        = os.getenv(
    "PG_DSN",
    "host=postgres port=5432 dbname=posture user=postgres password=postgres"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [CONSUMER] %(message)s")
log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS posture_events (
    id                        SERIAL PRIMARY KEY,
    ingested_at               TIMESTAMPTZ DEFAULT NOW(),
    frame_id                  INTEGER,
    user_id                   TEXT,
    event_timestamp           TEXT,
    presence                  TEXT,
    current_activity          TEXT,
    posture_state             TEXT,
    neck_angle                FLOAT,
    total_tracked_seconds     FLOAT,
    total_good_posture_seconds FLOAT,
    total_bad_posture_seconds  FLOAT,
    good_posture_percent      FLOAT
);
"""

INSERT_SQL = """
INSERT INTO posture_events (
    frame_id, user_id, event_timestamp,
    presence, current_activity, posture_state, neck_angle,
    total_tracked_seconds, total_good_posture_seconds,
    total_bad_posture_seconds, good_posture_percent
) VALUES (
    %(frame_id)s, %(user_id)s, %(event_timestamp)s,
    %(presence)s, %(current_activity)s, %(posture_state)s, %(neck_angle)s,
    %(total_tracked_seconds)s, %(total_good_posture_seconds)s,
    %(total_bad_posture_seconds)s, %(good_posture_percent)s
);
"""


def wait_for_postgres(dsn: str, retries: int = 20, delay: int = 4):
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(dsn)
            log.info("Connected to PostgreSQL.")
            return conn
        except psycopg2.OperationalError as e:
            log.warning("PostgreSQL not ready (%d/%d): %s", attempt, retries, e)
            time.sleep(delay)
    raise RuntimeError("Cannot connect to PostgreSQL.")


def wait_for_kafka(broker: str, topic: str, group: str, retries: int = 20, delay: int = 4) -> KafkaConsumer:
    for attempt in range(1, retries + 1):
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=[broker],
                group_id=group,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            )
            log.info("Connected to Kafka at %s, topic=%s", broker, topic)
            return consumer
        except NoBrokersAvailable:
            log.warning("Kafka not ready (%d/%d). Retrying in %ds…", attempt, retries, delay)
            time.sleep(delay)
    raise RuntimeError("Cannot connect to Kafka.")


def main():
    conn     = wait_for_postgres(PG_DSN)
    cursor   = conn.cursor()
    cursor.execute(DDL)
    conn.commit()
    log.info("Table ensured.")

    consumer = wait_for_kafka(KAFKA_BROKER, KAFKA_TOPIC, KAFKA_GROUP)

    log.info("Listening for messages…")
    for message in consumer:
        event = message.value
        try:
            status    = event.get("status", {})
            analytics = event.get("time_analytics", {})

            row = {
                "frame_id"                  : event.get("frame_id"),
                "user_id"                   : event.get("user_id"),
                "event_timestamp"           : event.get("timestamp"),
                "presence"                  : status.get("presence"),
                "current_activity"          : status.get("current_activity"),
                "posture_state"             : status.get("posture_state"),
                "neck_angle"                : status.get("neck_angle", 0.0),
                "total_tracked_seconds"     : analytics.get("total_tracked_seconds", 0.0),
                "total_good_posture_seconds": analytics.get("total_good_posture_seconds", 0.0),
                "total_bad_posture_seconds" : analytics.get("total_bad_posture_seconds", 0.0),
                "good_posture_percent"      : analytics.get("good_posture_percent", 0.0),
            }

            cursor.execute(INSERT_SQL, row)
            conn.commit()
            log.debug("Inserted frame_id=%s", row["frame_id"])
        except Exception as e:
            log.error("Failed to insert event: %s — %s", event, e)
            conn.rollback()


if __name__ == "__main__":
    main()
