from django.apps import AppConfig
import logging
import os

logger = logging.getLogger(__name__)

class PxeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pxe'
    
    def ready(self):
        """Called when Django app is ready"""
        # Import signals to register them
        from . import signals
        
        # Only run in main process (not during migrations, etc.)
        if os.environ.get('RUN_MAIN') or os.environ.get('DJANGO_SETTINGS_MODULE'):
            try:
                logger.info("PXE app ready - Manual scanning mode enabled, signals registered")
            except Exception as e:
                logger.error(f"Failed to initialize PXE app: {str(e)}")
                # Don't fail app startup if initialization fails
