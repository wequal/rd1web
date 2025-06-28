from django.apps import AppConfig
import logging
import os
import sys

logger = logging.getLogger(__name__)

class PxeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pxe'
    
    def ready(self):
        """Called when Django app is ready - start background tasks here"""
        # Only start background tasks in the main process (not during migrations, etc.)
        if os.environ.get('RUN_MAIN') or os.environ.get('DJANGO_SETTINGS_MODULE'):
            try:
                # Only the first worker (worker ID 0) should run background tasks
                worker_id = os.environ.get('DAPHNE_WORKER_ID', '0')
                
                if worker_id == '0':
                    from .background_tasks import mac_ip_task
                    
                    # Start the multi-subnet scanner
                    # It will scan both local (172.31.0.0/16) and remote (10.135.0.0/16) subnets
                    mac_ip_task.start()
                    
                    logger.info("PXE app ready - Multi-subnet scanner started (primary worker)")
                else:
                    logger.info(f"PXE app ready - Multi-subnet scanner skipped (worker {worker_id})")
                
            except Exception as e:
                logger.error(f"Failed to start multi-subnet scanner: {str(e)}")
                # Don't fail app startup if background task fails to start
