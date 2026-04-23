# Computer Vision Posture Monitoring System

A real-time posture monitoring system that uses computer vision to detect slouching and sends alerts via Kafka to a PostgreSQL database, with a Streamlit dashboard for visualization.

## Overview

This system monitors user posture in real-time using a webcam and MediaPipe pose detection. It tracks:
- Posture state (UPRIGHT/SLOUCHING/UNKNOWN)
- Neck angle
- Activity type (TYPING/RESTING/STRETCHING/AWAY)
- Time spent in good/bad posture

## Architecture

```
Webcam -> CV Service -> Kafka -> Consumer -> PostgreSQL -> UI
```

### Services

| Service | Description |
|---------|------------|
| cv-service | Captures webcam, detects pose, sends to Kafka |
| consumer-service | Reads from Kafka, saves to PostgreSQL |
| ui-service | Streamlit dashboard for visualization |

## Requirements

- Python 3.10+
- Kafka (local or Docker)
- PostgreSQL (local or Docker)
- Webcam (for cv-service)

## Setup

### 1. Start Kafka (Docker)

```bash
docker run -d --name posture-kafka -p 9092:9092 -v kafka_data:/var/lib/kafka/data apache/kafka:latest
```

Wait ~25 seconds for Kafka to start, then create topic:

```bash
docker exec posture-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic posture-events --partitions 1 --replication-factor 1
```

### 2. Setup PostgreSQL

Create database:

```bash
psql -h localhost -p 5432 -U your_username -d postgres -c "CREATE DATABASE posture;"
```

### 3. Install Python Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r cv-service/requirements.txt
pip install -r consumer-service/requirements.txt
pip install -r ui-service/requirements.txt
```

## Running

### Using the run script

```bash
./run.sh all          
./run.sh cv-service   
./run.sh consumer    
./run.sh ui          
```


Access at: http://localhost:8501

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| KAFKA_BROKER | localhost:9092 | Kafka broker address |
| KAFKA_TOPIC | posture-events | Kafka topic |
| KAFKA_GROUP | posture-consumer-group | Consumer group |
| PG_DSN | host=localhost port=5432 dbname=posture user=postgres password=postgres | PostgreSQL connection string |
| WEBCAM_INDEX | 0 | Webcam device index or video file path |
| FRAME_SKIP | 2 | Process every N frames |
| NECK_ANGLE_THRESH | 155 | Neck angle threshold (degrees) |
| USER_ID | USER-001 | User identifier |

## Database Schema

```sql
CREATE TABLE posture_events (
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
```
