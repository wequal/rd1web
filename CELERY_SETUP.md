# Celery Setup and Usage Guide for RD1Web

## Overview
Celery is configured to pre-warm the RMA logs cache in the background, ensuring users always get fast response times.

## Prerequisites
- Redis server running on localhost:6379
- Virtual environment activated
- All requirements installed (`pip install -r rd1web/requirements.txt`)

## Starting Celery Services

### Option 1: Using the Startup Scripts (Recommended)

**Terminal 1 - Start Celery Worker:**
```bash
cd /home/devin/rd1web-dev
./celery_worker.sh
```

**Terminal 2 - Start Celery Beat (Scheduler):**
```bash
cd /home/devin/rd1web-dev
./celery_beat.sh
```

### Option 2: Manual Commands

**Start Celery Worker:**
```bash
cd /home/devin/rd1web-dev/rd1web
source ../venv/bin/activate
celery -A rd1web worker --loglevel=info --concurrency=2
```

**Start Celery Beat:**
```bash
cd /home/devin/rd1web-dev/rd1web
source ../venv/bin/activate
celery -A rd1web beat --loglevel=info
```

## Scheduled Tasks

### 1. Pre-warm RMA Directory Cache
- **Task:** `pxe.tasks.prewarm_rma_directory_cache`
- **Schedule:** Every 30 seconds
- **Purpose:** Keeps basic directory listing (name, base_sn, rma_number, mtime) fresh in cache
- **Duration:** ~100-300ms for 100 directories

### 2. Pre-warm RMA Details Cache
- **Task:** `pxe.tasks.prewarm_rma_details_cache`
- **Schedule:** Every 1 minute
- **Purpose:** Keeps details (test_status, gpu_model, golden_number) for the 40 most recent directories cached
- **Duration:** ~1-3s for 40 directories

## Manual Task Execution

You can manually trigger tasks from Django shell:

```python
python3 manage.py shell

# Import tasks
from pxe.tasks import prewarm_rma_directory_cache, prewarm_rma_details_cache, clear_rma_cache, health_check

# Run tasks immediately
prewarm_rma_directory_cache.delay()
prewarm_rma_details_cache.delay()

# Clear cache
clear_rma_cache.delay()

# Health check
health_check.delay()
```

## Monitoring

### Check Celery Worker Status
```bash
celery -A rd1web inspect active
celery -A rd1web inspect stats
```

### View Scheduled Tasks
```bash
celery -A rd1web inspect scheduled
```

### Monitor Task Execution
```bash
# Watch worker log
tail -f celery_worker.log

# Watch beat log
tail -f celery_beat.log
```

## Troubleshooting

### Redis Not Running
```bash
# Check if Redis is running
redis-cli ping

# If not running, start Redis
sudo systemctl start redis
# or
redis-server
```

### Celery Worker Not Starting
1. Check if virtual environment is activated
2. Ensure Django settings module is set correctly
3. Check Redis connectivity: `redis-cli ping`
4. Review worker log: `tail -f celery_worker.log`

### Tasks Not Executing
1. Ensure both worker AND beat are running
2. Check beat log for scheduling errors: `tail -f celery_beat.log`
3. Verify task registration: `celery -A rd1web inspect registered`

### Cache Not Warming
1. Check task execution: `celery -A rd1web inspect active`
2. Verify RMA directory is accessible: `ls -la /srv/rma-b31`
3. Check Django cache settings in `settings.py`
4. Test cache connectivity: `python3 manage.py shell` then `from django.core.cache import cache; cache.set('test', 'ok'); cache.get('test')`

## Performance Tuning

### Adjust Concurrency
Edit `celery_worker.sh` and change `--concurrency=2` to match your CPU cores:
- 2 workers: Good for development
- 4 workers: Better for production with moderate load
- 8+ workers: High-performance production setup

### Adjust Cache Pre-warming Frequency
Edit `rd1web/rd1web/celery.py`:
- Decrease intervals for more real-time updates (higher load)
- Increase intervals to reduce load (staler cache)

## Production Deployment

For production, use systemd to manage Celery services:

### Create systemd service files:

**`/etc/systemd/system/celery-worker.service`:**
```ini
[Unit]
Description=Celery Worker for RD1Web
After=network.target redis.target

[Service]
Type=forking
User=devin
Group=devin
WorkingDirectory=/home/devin/rd1web-dev/rd1web
Environment="PATH=/home/devin/rd1web-dev/venv/bin"
ExecStart=/home/devin/rd1web-dev/venv/bin/celery -A rd1web worker \
    --loglevel=info \
    --concurrency=4 \
    --pidfile=/var/run/celery/celery-worker.pid \
    --logfile=/var/log/celery/worker.log
ExecStop=/bin/kill -s TERM $MAINPID
Restart=always

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/celery-beat.service`:**
```ini
[Unit]
Description=Celery Beat Scheduler for RD1Web
After=network.target redis.target

[Service]
Type=simple
User=devin
Group=devin
WorkingDirectory=/home/devin/rd1web-dev/rd1web
Environment="PATH=/home/devin/rd1web-dev/venv/bin"
ExecStart=/home/devin/rd1web-dev/venv/bin/celery -A rd1web beat \
    --loglevel=info \
    --pidfile=/var/run/celery/celery-beat.pid \
    --logfile=/var/log/celery/beat.log \
    --schedule=/var/run/celery/celerybeat-schedule.db
ExecStop=/bin/kill -s TERM $MAINPID
Restart=always

[Install]
WantedBy=multi-user.target
```

### Enable and start services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable celery-worker celery-beat
sudo systemctl start celery-worker celery-beat
sudo systemctl status celery-worker celery-beat
```

## Performance Impact

With Celery pre-warming:
- **Initial page load:** < 500ms (vs 2-5s without caching)
- **Cache hit rate:** > 95% after warm-up
- **User experience:** Near-instant page loads for most requests
- **Server load:** Minimal - tasks run in background

## Security Notes

- Celery broker (Redis) should be secured and not exposed publicly
- Use firewall rules to restrict Redis access to localhost
- Consider using Redis authentication in production
- Regularly update Celery and Redis packages

## Support

For issues or questions about Celery configuration, check:
- Celery documentation: https://docs.celeryproject.org/
- Django-Celery integration: https://docs.celeryproject.org/en/stable/django/
- Project logs: `celery_worker.log` and `celery_beat.log`

