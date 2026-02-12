"""
Celery tasks for RMA logs cache pre-warming and background operations
"""
import logging
from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=True, max_retries=3)
def prewarm_rma_directory_cache(self):
    """
    Pre-warm the RMA directory basic info cache
    Runs every 30 seconds to keep the cache fresh
    
    This task loads only basic directory info (name, base_sn, rma_number, mtime)
    which is very fast (just os.listdir + os.stat)
    """
    try:
        # Import here to avoid circular imports
        from .views.rma_logs import get_rma_directories_basic
        
        logger.info("Starting RMA directory cache pre-warming...")
        
        # This will populate the cache if expired
        directories = get_rma_directories_basic()
        
        dir_count = len(directories)
        logger.info(f"RMA directory cache pre-warmed successfully: {dir_count} directories")
        
        return {
            'status': 'success',
            'directory_count': dir_count,
        }
        
    except Exception as e:
        logger.error(f"Error pre-warming RMA directory cache: {e}")
        # Retry up to 3 times with exponential backoff
        raise self.retry(exc=e, countdown=60)  # Retry after 1 minute


@shared_task(bind=True, ignore_result=True, max_retries=3)
def prewarm_rma_details_cache(self):
    """
    Pre-warm the RMA directory details cache for recently modified directories
    Runs every 1 minute to keep details fresh
    
    This task loads details (test_status, gpu_model, golden_number) for:
    - The 40 most recently modified directories (covers 2 pages)
    - Prioritizes frequently accessed directories
    """
    try:
        # Import here to avoid circular imports
        from .views.rma_logs import get_rma_directories_basic, load_directory_details_batch
        
        logger.info("Starting RMA details cache pre-warming...")
        
        # Get basic directory list (should be cached)
        directories = get_rma_directories_basic()
        
        if not directories:
            logger.warning("No RMA directories found for details pre-warming")
            return {'status': 'no_directories'}
        
        # Pre-warm details for the 40 most recently modified directories (2 pages worth)
        # These are the most likely to be viewed
        top_directories = directories[:40]
        dir_names = [d['name'] for d in top_directories]
        
        logger.info(f"Pre-warming details for {len(dir_names)} recent directories...")
        
        # Load details (will use cache if available, populate if not)
        details_map = load_directory_details_batch(dir_names)
        
        prewarmed_count = len(details_map)
        logger.info(f"RMA details cache pre-warmed successfully: {prewarmed_count} directories")
        
        return {
            'status': 'success',
            'prewarmed_count': prewarmed_count,
            'total_directories': len(directories),
        }
        
    except Exception as e:
        logger.error(f"Error pre-warming RMA details cache: {e}")
        # Retry up to 3 times with exponential backoff
        raise self.retry(exc=e, countdown=120)  # Retry after 2 minutes


@shared_task(bind=True, ignore_result=True)
def clear_rma_cache(self):
    """
    Clear all RMA-related cache entries
    Useful for manual cache refresh or maintenance
    """
    try:
        logger.info("Clearing RMA cache...")
        
        # Clear basic directory cache
        cache.delete('rma_directories_basic_v2')
        
        # Clear old cache keys for compatibility
        cache.delete('rma_directories_basic')
        
        # Note: Individual detail caches will expire naturally
        # We don't clear them here to avoid cache stampede
        
        logger.info("RMA cache cleared successfully")
        
        return {'status': 'success'}
        
    except Exception as e:
        logger.error(f"Error clearing RMA cache: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True, ignore_result=True)
def health_check(self):
    """
    Celery health check task
    Returns basic system information
    """
    import os
    import psutil
    
    try:
        # Get system stats
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        # Check if RMA directory is accessible
        from .views.rma_logs import RMA_BASE_DIR
        rma_accessible = os.path.exists(RMA_BASE_DIR)
        
        # Check cache connectivity
        cache_working = False
        try:
            cache.set('celery_health_check', 'ok', 10)
            cache_working = cache.get('celery_health_check') == 'ok'
        except:
            pass
        
        result = {
            'status': 'healthy',
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'rma_directory_accessible': rma_accessible,
            'cache_working': cache_working,
        }
        
        logger.info(f"Celery health check: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Celery health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
        }


@shared_task(bind=True, ignore_result=True, max_retries=3)
def scan_rma_statistics(self):
    """
    Scan RMA directories and update statistics database
    Runs every hour to track test failures with minimal overhead
    
    Uses smart scanning - only processes directories where test_results.log has changed
    """
    try:
        logger.info("Starting RMA statistics scan...")
        
        # Import here to avoid circular imports
        from .rma_statistics import scan_all_rma_directories
        
        # Perform scan
        stats = scan_all_rma_directories()
        
        logger.info(f"RMA statistics scan completed: {stats['processed']} processed, "
                   f"{stats['skipped']} skipped, {stats['errors']} errors out of {stats['total']} total")
        
        return {
            'status': 'success',
            'stats': stats,
        }
        
    except Exception as e:
        logger.error(f"Error in RMA statistics scan: {e}")
        # Retry up to 3 times with exponential backoff
        raise self.retry(exc=e, countdown=300)  # Retry after 5 minutes

