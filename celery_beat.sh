#!/bin/bash
# Celery Beat Scheduler Startup Script for RD1Web
# This script starts the Celery Beat scheduler for periodic tasks

# Change to the project directory
cd "$(dirname "$0")/rd1web" || exit 1

# Activate virtual environment
source ../venv/bin/activate

# Set Django settings module
export DJANGO_SETTINGS_MODULE='rd1web.settings'

# Start Celery Beat
# -A: Application
# -l: Log level (info, debug, warning, error)
# --scheduler: Scheduler backend (default is database, can use django_celery_beat for DB-backed scheduling)

echo "Starting Celery Beat Scheduler..."
echo "=========================================="
echo "Project: RD1Web"
echo "Django Settings: $DJANGO_SETTINGS_MODULE"
echo "Log Level: INFO"
echo "Schedule:"
echo "  - Pre-warm RMA directory cache: every 30 seconds"
echo "  - Pre-warm RMA details cache: every 1 minute"
echo "=========================================="

celery -A rd1web beat \
    --loglevel=info \
    --logfile=../celery_beat.log \
    --pidfile=../celery_beat.pid \
    --schedule=../celerybeat-schedule.db

# Note: For production, consider using a process manager like systemd or supervisor
# Example systemd service file would be placed in /etc/systemd/system/celery-beat.service

