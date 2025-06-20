import os
import shutil
import logging
import datetime
from zoneinfo import ZoneInfo
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

logger = logging.getLogger(__name__)

BASE_DIR = '/srv/log'
ARCHIVE_DIR = os.path.join(BASE_DIR, 'archive')

@login_required
@require_POST
def archive_system(request, folder_name):
    """Move the system log folder to /srv/log/archive with timestamp suffix (LA time)."""
    src_path = os.path.join(BASE_DIR, folder_name)
    if not os.path.exists(src_path):
        return JsonResponse({'success': False, 'error': 'Source folder not found'}, status=404)

    # Ensure archive directory exists
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    # Current time in America/Los_Angeles
    tz = ZoneInfo('America/Los_Angeles')
    ts = datetime.datetime.now(tz).strftime('%Y-%m-%d_%H-%M-%S')
    dest_name = f"{folder_name}_{ts}"
    dest_path = os.path.join(ARCHIVE_DIR, dest_name)

    try:
        shutil.move(src_path, dest_path)
        logger.info('Archived %s to %s', src_path, dest_path)
        return JsonResponse({'success': True, 'dest': dest_name})
    except Exception as exc:
        logger.exception('Failed to archive %s', folder_name)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500) 