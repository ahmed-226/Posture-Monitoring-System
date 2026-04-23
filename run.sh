#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PATH="${SCRIPT_DIR}/venv"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if venv exists
if [ ! -d "$VENV_PATH" ]; then
    log_error "Virtual environment not found at $VENV_PATH"
    echo "Please create venv first: python -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate venv
source "$VENV_PATH/bin/activate"

# Check Kafka
log_info "Checking Kafka..."
if ! docker ps --filter "name=posture-kafka" --format "{{.Names}}" | grep -q "posture-kafka"; then
    log_warn "Kafka not running. Starting container..."
    docker run -d --name posture-kafka -p 9092:9092 -v kafka_data:/var/lib/kafka/data apache/kafka:latest
    sleep 25
    
    log_info "Creating topic..."
    docker exec posture-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic posture-events --partitions 1 --replication-factor 1 || true
fi

# Check localhost:9092 is accessible (use netcat not curl - Kafka doesn't use HTTP)
if ! nc -z localhost 9092 2>/dev/null; then
    log_error "Kafka not accessible at localhost:9092"
    exit 1
fi

log_info "Kafka is ready"

# Export env vars
export KAFKA_BROKER="localhost:9092"
export KAFKA_TOPIC="posture-events"
export KAFKA_GROUP="posture-consumer-group"
export PG_DSN="host=localhost port=5432 dbname=posture user=ahmed password=yatamomo226"
export WEBCAM_INDEX="${WEBCAM_INDEX:-0}"
export FRAME_SKIP="${FRAME_SKIP:-2}"
export NECK_ANGLE_THRESH="${NECK_ANGLE_THRESH:-155}"
export USER_ID="${USER_ID:-USER-001}"
export QT_QPA_PLATFORM="xcb"

# Parse arguments
SERVICE="${1:-all}"

case "$SERVICE" in
    cv-service|cv)
        log_info "Starting CV Service..."
        cd "$SCRIPT_DIR/cv-service"
        python main.py
        ;;
    consumer|cons)
        log_info "Starting Consumer Service..."
        cd "$SCRIPT_DIR/consumer-service"
        python main.py
        ;;
    ui|streamlit)
        log_info "Starting UI Service..."
        cd "$SCRIPT_DIR/ui-service"
        streamlit run app.py --server.port=8501 --server.address=0.0.0.0
        ;;
    all)
        log_info "Starting all services..."
        
        # Start consumer in background
        cd "$SCRIPT_DIR/consumer-service"
        python main.py &
        CONSUMER_PID=$!
        log_info "Consumer started (PID: $CONSUMER_PID)"
        
        # Start UI in background
        cd "$SCRIPT_DIR/ui-service"
        streamlit run app.py --server.port=8501 --server.address=0.0.0.0 &
        UI_PID=$!
        log_info "UI started (PID: $UI_PID)"
        
        log_info "All services started"
        log_info "UI: http://localhost:8501"
        log_info "Press Ctrl+C to stop all services"
        
        trap "kill $CONSUMER_PID $UI_PID 2>/dev/null; exit" INT TERM
        wait
        ;;
    *)
        echo "Usage: $0 [cv-service|consumer|ui|all]"
        echo ""
        echo "  cv-service  - Run CV service (needs webcam)"
        echo "  consumer   - Run consumer service"
        echo "  ui         - Run Streamlit UI"
        echo "  all        - Run all services (default)"
        exit 1
        ;;
esac