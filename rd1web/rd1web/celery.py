"""
Celery configuration for rd1web project
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rd1web.settings')

app = Celery('rd1web')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps
app.autodiscover_tasks()

# Configure periodic tasks
app.conf.beat_schedule = {
    'prewarm-rma-directory-cache-every-30-seconds': {
        'task': 'pxe.tasks.prewarm_rma_directory_cache',
        'schedule': 30.0,  # Every 30 seconds
    },
    'prewarm-rma-details-cache-every-1-minute': {
        'task': 'pxe.tasks.prewarm_rma_details_cache',
        'schedule': 60.0,  # Every 1 minute
    },
    'scan-rma-statistics-every-hour': {
        'task': 'pxe.tasks.scan_rma_statistics',
        'schedule': 3600.0,  # Every 1 hour
    },
}

# Celery configuration
app.conf.update(
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='America/Los_Angeles',
    enable_utc=True,
    
    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=300,  # 5 minutes hard limit
    task_soft_time_limit=240,  # 4 minutes soft limit
    
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    
    # Result backend settings
    result_expires=3600,  # 1 hour
    result_backend_transport_options={'master_name': 'mymaster'},
)

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery"""
    print(f'Request: {self.request!r}')

