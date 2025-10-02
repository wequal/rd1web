#!/bin/bash
# Celery Worker Startup Script for RD1Web
# This script starts the Celery worker for background task processing

# Change to the project directory
cd "$(dirname "$0")/rd1web" || exit 1

# Activate virtual environment
source ../venv/bin/activate

# Set Django settings module
export DJANGO_SETTINGS_MODULE='rd1web.settings'

# Start Celery worker
# -A: Application
# -l: Log level (info, debug, warning, error)
# --concurrency: Number of worker processes (adjust based on your CPU cores)
# --max-tasks-per-child: Restart worker after N tasks to prevent memory leaks
# --time-limit: Hard time limit for tasks (seconds)

echo "Starting Celery Worker..."
echo "=========================================="
echo "Project: RD1Web"
echo "Django Settings: $DJANGO_SETTINGS_MODULE"
echo "Log Level: INFO"
echo "Concurrency: 2 workers"
echo "=========================================="

celery -A rd1web worker \
    --loglevel=info \
    --concurrency=2 \
    --max-tasks-per-child=1000 \
    --time-limit=300 \
    --soft-time-limit=240 \
    --logfile=../celery_worker.log \
    --pidfile=../celery_worker.pid

# Note: For production, consider using a process manager like systemd or supervisor
# Example systemd service file would be placed in /etc/systemd/system/celery-worker.service

