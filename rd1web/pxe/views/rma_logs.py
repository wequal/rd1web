from django.shortcuts import render, redirect
from django.http import HttpResponse, Http404, FileResponse, JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.template import Template, Context
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.urls import reverse
from urllib.parse import quote, unquote
from datetime import datetime
import mimetypes
import csv
import os
import logging
import re
import io
import threading
import asyncio
import time
import json
from asgiref.sync import sync_to_async
from ..remote_config import remote_dict
from ..utils import render_markdown_as_html

logger = logging.getLogger(__name__)

# Import configuration from local_config
try:
    from ..local_config import (
        RMA_BASE_DIR,
        TEMP_ZIPS_DIR,
        RMA_GB_BASE_DIR,
        TEMP_ZIPS_GB_DIR,
        RMA_CACHE_TIMEOUT,
        RMA_DETAILS_CACHE_TIMEOUT,
        RMA_STATS_CACHE_TIMEOUT,
        ZIP_TASK_TIMEOUT,
        DEPLOYMENT_LOCATION,
    )
    
    # Try to import remote_download separately
    try:
        from ..local_config import remote_download
    except ImportError:
        remote_download = None

    # Optional feature flag
    try:
        from ..local_config import AI_log_analyzer
    except ImportError:
        AI_log_analyzer = False
        
    logger.info("RMA logs using configuration from local_config.py")
except ImportError:
    # Fallback to defaults if local_config doesn't exist
    logger.warning("local_config.py not found, using default RMA configuration")
    RMA_BASE_DIR = '/srv/rma-b31'
    TEMP_ZIPS_DIR = '/srv/rma-b31/.TempZips'
    RMA_GB_BASE_DIR = '/srv/rma/gb'
    TEMP_ZIPS_GB_DIR = '/srv/rma/gb/.TempZips'
    RMA_CACHE_TIMEOUT = 30  # 30 seconds cache for basic directory listings
    RMA_DETAILS_CACHE_TIMEOUT = 60  # 1 minute cache for directory details
    RMA_STATS_CACHE_TIMEOUT = 300  # 5 minutes cache for file stats
    ZIP_TASK_TIMEOUT = 3600  # 1 hour timeout for zip creation tasks
    remote_download = None
    AI_log_analyzer = False

from ..ai_summary import generate_ai_summary_markdown


def _resolve_rma_context(base: str | None):
    """
    Resolve base-specific paths and cache namespace.

    base:
      - None / 'main': use RMA_BASE_DIR + TEMP_ZIPS_DIR
      - 'gb': use RMA_GB_BASE_DIR + TEMP_ZIPS_GB_DIR
    """
    if (base or 'main') == 'gb':
        return {
            'base': 'gb',
            'base_dir': RMA_GB_BASE_DIR,
            'temp_zips_dir': TEMP_ZIPS_GB_DIR,
            'cache_ns': 'rma_gb',
        }
    return {
        'base': 'main',
        'base_dir': RMA_BASE_DIR,
        'temp_zips_dir': TEMP_ZIPS_DIR,
        'cache_ns': 'rma',
    }


def _generate_ai_summary_task(task_id: str, target_dir: str, analysis_url: str | None = None):
    cache_key = f'ai_summary_task_{task_id}'
    try:
        cache.set(
            cache_key,
            {
                'status': 'processing',
                'progress': 15,
                'message': 'Analyzing folder logs with AI...',
                'report_path': None,
                'error': None,
            },
            1800,
        )

        markdown_content = generate_ai_summary_markdown(target_dir, analysis_url=analysis_url)

        cache.set(
            cache_key,
            {
                'status': 'processing',
                'progress': 85,
                'message': 'Writing AI report file...',
                'report_path': None,
                'error': None,
            },
            1800,
        )

        # Capture parent dir mtime so we can restore it after writing (avoids skewing
        # RMA statistics and directory listing when AI summary runs).
        orig_atime = orig_mtime = None
        try:
            orig_stat = os.stat(target_dir)
            orig_atime, orig_mtime = orig_stat.st_atime, orig_stat.st_mtime
        except OSError:
            pass

        try:
            report_dir = os.path.join(target_dir, "AI_Report")
            os.makedirs(report_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_filename = f"AI_Report_{timestamp}.md"
            report_full_path = os.path.join(report_dir, report_filename)

            with open(report_full_path, "w", encoding="utf-8") as out:
                out.write(markdown_content)
        finally:
            if orig_mtime is not None:
                try:
                    os.utime(target_dir, (orig_atime, orig_mtime))
                except OSError:
                    pass

        cache.set(
            cache_key,
            {
                'status': 'completed',
                'progress': 100,
                'message': 'AI summary report generated successfully.',
                'report_path': report_full_path,
                'error': None,
            },
            1800,
        )
    except Exception as exc:
        logger.exception("AI summary generation failed for %s: %s", target_dir, exc)
        err_msg = str(exc)
        cache.set(
            cache_key,
            {
                'status': 'failed',
                'progress': 0,
                'message': f'Failed to generate AI summary: {err_msg}',
                'report_path': None,
                'error': err_msg,
            },
            1800,
        )

class TimeoutError(Exception):
    """Custom timeout exception"""
    pass

def run_local_command(command, timeout_seconds=60):
    """
    Run a local command using subprocess instead of remote connection
    Returns (result, success, error_message)
    """
    import subprocess
    
    class LocalResult:
        def __init__(self, returncode, stdout, stderr):
            self.return_code = returncode
            self.stdout = stdout
            self.stderr = stderr
    
    try:
        # Run command locally with timeout
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=timeout_seconds
        )
        
        local_result = LocalResult(result.returncode, result.stdout, result.stderr)
        success = result.returncode == 0
        error = result.stderr if not success else None
        
        return local_result, success, error
        
    except subprocess.TimeoutExpired:
        return None, False, f"Command timed out after {timeout_seconds} seconds"
    except Exception as e:
        logger.error(f"Local command failed: {command}, Error: {e}")
        return None, False, str(e)

def run_with_timeout(func, timeout_seconds=60):
    """
    Run a function with a timeout using threading instead of signals
    Returns (result, success, error_message)
    """
    result = [None]
    exception = [None]
    
    def target():
        try:
            result[0] = func()
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout_seconds)
    
    if thread.is_alive():
        # Thread is still running, timeout occurred
        return None, False, f"Operation timed out after {timeout_seconds} seconds"
    elif exception[0] is not None:
        # Exception occurred in the thread
        return None, False, str(exception[0])
    else:
        # Success
        return result[0], True, None

def get_rma_host_ip():
    """Extract RMA host IP from local_config REMOTE_SERVERS using DEPLOYMENT_LOCATION"""
    try:
        # Try to read from local_config REMOTE_SERVERS first
        from ..local_config import REMOTE_SERVERS, DEPLOYMENT_LOCATION
        deployment_key = DEPLOYMENT_LOCATION
        if deployment_key in REMOTE_SERVERS:
            rma_host = REMOTE_SERVERS[deployment_key]['host']
            # Extract IP from format like "root@10.4.4.140"
            if '@' in rma_host:
                return rma_host.split('@')[1]
            return rma_host
    except (ImportError, KeyError, AttributeError):
        pass
    
    # Fallback: try remote_dict if available (for backward compatibility)
    try:
        from ..local_config import DEPLOYMENT_LOCATION
        deployment_key = DEPLOYMENT_LOCATION
        if deployment_key in remote_dict and hasattr(remote_dict[deployment_key], 'host'):
            rma_host = remote_dict[deployment_key].host
            if '@' in rma_host:
                return rma_host.split('@')[1]
            return rma_host
    except (KeyError, AttributeError, ImportError):
        pass
    
    # Final fallback - use default IP
    logger.warning("Could not get RMA host IP from config, using default")
    return '10.4.4.80'  # Default RMA host IP

def get_apache_url(path):
    """
    Construct Apache URL with port 8888
    If URL contains :80, replace with :8888, otherwise add :8888
    """
    base_url = f"http://{get_rma_host_ip()}"
    # Replace :80 with :8888 if present, otherwise add :8888
    if ':80' in base_url:
        base_url = base_url.replace(':80', ':8888')
    elif ':' not in base_url.split('//')[1]:  # No port specified (defaults to 80)
        base_url = f"{base_url}:8888"
    return f"{base_url}/{path}"

def cleanup_old_temp_zips(temp_zips_dir=None):
    """
    Remove temporary zip files older than 1 hour from the temp directory
    """
    temp_zips_dir = temp_zips_dir or TEMP_ZIPS_DIR
    try:
        # Create temp directory if it doesn't exist
        if not os.path.exists(temp_zips_dir):
            os.makedirs(temp_zips_dir, exist_ok=True)
            logger.info(f"Created temp zips directory: {temp_zips_dir}")
            return
        
        current_time = time.time()
        one_hour_ago = current_time - 3600  # 1 hour in seconds
        
        # Iterate through files in temp directory
        for filename in os.listdir(temp_zips_dir):
            if not filename.endswith('.zip'):
                continue
            
            file_path = os.path.join(temp_zips_dir, filename)
            
            try:
                # Get file modification time
                file_mtime = os.path.getmtime(file_path)
                
                # Remove if older than 1 hour
                if file_mtime < one_hour_ago:
                    os.remove(file_path)
                    logger.info(f"Removed old temp zip: {filename}")
            except Exception as e:
                logger.warning(f"Error removing temp zip {filename}: {e}")
                
    except Exception as e:
        logger.error(f"Error cleaning up temp zips: {e}")

def create_temp_zip(source_dir, dir_name, temp_zips_dir=None):
    """
    Create a temporary zip file of a directory using system zip command (much faster)
    
    Args:
        source_dir (str): Full path to the directory to zip
        dir_name (str): Name of the directory (used for zip filename)
        
    Returns:
        str: Filename of the created zip file, or None on error
    """
    import subprocess
    temp_zips_dir = temp_zips_dir or TEMP_ZIPS_DIR
    
    try:
        # Clean up old zips first
        cleanup_old_temp_zips(temp_zips_dir=temp_zips_dir)
        
        # Create temp directory if it doesn't exist
        if not os.path.exists(temp_zips_dir):
            os.makedirs(temp_zips_dir, exist_ok=True)
            logger.info(f"Created temp zips directory: {temp_zips_dir}")
        
        # Generate unique filename with timestamp
        timestamp = int(time.time())
        zip_filename = f"{dir_name}_{timestamp}.zip"
        zip_path = os.path.join(temp_zips_dir, zip_filename)
        
        # Create zip file using system zip command (2-5x faster than Python zipfile)
        logger.info(f"Creating zip file: {zip_path} from {source_dir}")
        
        # Change to parent directory so zip contains proper directory structure
        parent_dir = os.path.dirname(source_dir)
        target_dir = os.path.basename(source_dir)
        
        # Use system zip command with fast compression
        # -r = recursive, -q = quiet, -1 = fast compression
        result = subprocess.run(
            ['zip', '-r', '-q', '-1', zip_path, target_dir],
            cwd=parent_dir,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode != 0:
            logger.error(f"Zip command failed: {result.stderr}")
            return None
        
        logger.info(f"Successfully created zip file: {zip_filename}")
        return zip_filename
        
    except subprocess.TimeoutExpired:
        logger.error(f"Zip creation timed out for {dir_name}")
        return None
    except Exception as e:
        logger.error(f"Error creating temp zip for {dir_name}: {e}")
        return None

def create_zip_async(task_id, source_dir, dir_name, temp_zips_dir=None, cache_ns: str = "rma"):
    """
    Create zip in background thread and update task status in cache
    
    Args:
        task_id (str): Unique task identifier
        source_dir (str): Full path to directory to zip
        dir_name (str): Name of the directory
    """
    temp_zips_dir = temp_zips_dir or TEMP_ZIPS_DIR
    try:
        logger.info(f"Starting async zip creation for task {task_id}: {dir_name}")
        
        # Update status to processing
        task_data = cache.get(f'{cache_ns}_zip_task_{task_id}')
        if task_data:
            task_data['status'] = 'processing'
            cache.set(f'{cache_ns}_zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
        
        # Create the zip file
        zip_filename = create_temp_zip(source_dir, dir_name, temp_zips_dir=temp_zips_dir)
        
        if zip_filename:
            # Update status to completed
            task_data = cache.get(f'{cache_ns}_zip_task_{task_id}')
            if task_data:
                task_data['status'] = 'completed'
                task_data['zip_filename'] = zip_filename
                cache.set(f'{cache_ns}_zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
            logger.info(f"Async zip creation completed for task {task_id}: {zip_filename}")
        else:
            # Update status to failed
            task_data = cache.get(f'{cache_ns}_zip_task_{task_id}')
            if task_data:
                task_data['status'] = 'failed'
                task_data['error'] = 'Failed to create zip file'
                cache.set(f'{cache_ns}_zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
            logger.error(f"Async zip creation failed for task {task_id}")
            
    except Exception as e:
        # Update status to failed
        task_data = cache.get(f'{cache_ns}_zip_task_{task_id}')
        if task_data:
            task_data['status'] = 'failed'
            task_data['error'] = str(e)
            cache.set(f'{cache_ns}_zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
        logger.error(f"Exception in async zip creation for task {task_id}: {e}")

@login_required
def rma_download_folder_async(request, path, base=None):
    """
    Start async zip creation and return task ID immediately
    Returns JSON with task_id for polling
    """
    import uuid
    ctx = _resolve_rma_context(base)
    base_dir = ctx["base_dir"]
    temp_zips_dir = ctx["temp_zips_dir"]
    cache_ns = ctx["cache_ns"]
    
    decoded_path = unquote(path)
    remote_path = os.path.normpath(os.path.join(base_dir, decoded_path))

    # Security check
    if not remote_path.startswith(base_dir):
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)

    try:
        # Check if directory exists
        if not os.path.exists(remote_path):
            return JsonResponse({'success': False, 'error': 'Directory does not exist'}, status=404)
        
        if not os.path.isdir(remote_path):
            return JsonResponse({'success': False, 'error': 'Path is not a directory'}, status=400)

        # Generate unique task ID
        task_id = str(uuid.uuid4())
        
        # Initialize task tracking in cache
        task_data = {
            'status': 'initializing',
            'zip_filename': None,
            'error': None,
            'created_at': time.time()
        }
        cache.set(f'{cache_ns}_zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
        
        # Get directory name
        dir_name = os.path.basename(remote_path)
        
        # Start zip creation in background thread
        thread = threading.Thread(
            target=create_zip_async,
            args=(task_id, remote_path, dir_name, temp_zips_dir, cache_ns),
            daemon=True
        )
        thread.start()
        
        logger.info(f"Started async zip creation task {task_id} for {dir_name}")
        
        return JsonResponse({
            'success': True,
            'task_id': task_id,
            'folder_name': dir_name
        })
        
    except Exception as e:
        logger.error(f"Error starting async zip creation: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def rma_download_folder_status(request, task_id, base=None):
    """
    Check status of async zip creation task from cache
    Returns JSON with status and download URL when ready
    """
    ctx = _resolve_rma_context(base)
    cache_ns = ctx["cache_ns"]
    try:
        # Get task from cache
        task = cache.get(f'{cache_ns}_zip_task_{task_id}')
        
        if not task:
            return JsonResponse({'success': False, 'error': 'Task not found'}, status=404)
        
        status = task['status']
        
        response_data = {
            'success': True,
            'status': status
        }
        
        if status == 'completed':
            # Zip is ready, return download URL
            zip_filename = task['zip_filename']
            from django.urls import reverse
            download_zip_url_name = 'rma_gb_download_zip' if ctx["base"] == 'gb' else 'rma_download_zip'
            django_url = reverse(download_zip_url_name, kwargs={'zip_filename': zip_filename})
            response_data['download_url'] = django_url
            # Cache will auto-expire after ZIP_TASK_TIMEOUT
            
        elif status == 'failed':
            # Zip creation failed
            response_data['error'] = task.get('error', 'Unknown error')
            # Optionally delete failed task immediately
            cache.delete(f'{cache_ns}_zip_task_{task_id}')
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error checking task status {task_id}: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def _is_safe_gpu_sn_query(query: str) -> bool:
    """
    Basic guardrails: GPU SN is treated as a plain substring for filename/path matching.
    """
    if not query:
        return False
    # Avoid unbounded/abusive scans
    return len(query) <= 64


def find_rma_dirs_by_gpu_sn(gpu_sn_query: str, base_dir=None, cache_ns: str = "rma"):
    """
    Find top-level RMA directories whose descendant filenames contain the provided GPU SN substring.

    Returns:
        set[str]: set of top-level directory names (e.g. {"RR35B_RR35B"})
    """
    base_dir = base_dir or RMA_BASE_DIR
    if not _is_safe_gpu_sn_query(gpu_sn_query):
        return set()

    query = gpu_sn_query.strip()
    if not query:
        return set()

    cache_key = f"{cache_ns}_gpu_sn_match_{query}"
    cached = cache.get(cache_key)
    if cached is not None:
        # Stored as list for cache safety
        return set(cached)

    def _escape_find_name_fragment(text: str) -> str:
        """
        Escape special glob chars for GNU find -name pattern matching.
        (find -name uses shell-style patterns, not regex)
        """
        return re.sub(r'([\\*\?\[\]])', r'\\\1', text)

    def _dir_has_filename_match(full_path: str, dir_name: str) -> bool:
        """
        Fast path: use system `find` to locate any filename containing query, early-exit on first match.
        Falls back to os.walk if `find` isn't available or errors.
        """
        try:
            import subprocess

            # Ex: *1324323021977*  (escaped for find's glob matching)
            pattern = f"*{_escape_find_name_fragment(query)}*"

            # Skip .TempZips subtree, then look for any file with name match and stop at first hit.
            # Note: `find` exits 0 even if no match; we rely on stdout content.
            cmd = [
                "find",
                full_path,
                "(",
                "-path",
                "*/.TempZips/*",
                "-o",
                "-name",
                ".TempZips",
                ")",
                "-prune",
                "-o",
                "-type",
                "f",
                "-name",
                pattern,
                "-print",
                "-quit",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return bool(result.stdout and result.stdout.strip())
        except Exception:
            # Fallback: pure Python walk (slower)
            try:
                for root, dirs, files in os.walk(full_path):
                    dirs[:] = [d for d in dirs if d not in {'.TempZips'}]
                    for filename in files:
                        if query in filename:
                            return True
            except Exception as e:
                logger.warning(f"GPU SN scan error for {dir_name}: {e}")
            return False

    all_rma_directories = get_rma_directories_basic(base_dir=base_dir, cache_ns=cache_ns)

    # Parallelize by top-level directory (IO-bound); keep concurrency modest to avoid disk thrash.
    try:
        import concurrent.futures

        max_workers = 8

        def _scan_one(rma_dir):
            dir_name = rma_dir.get('name')
            full_path = rma_dir.get('full_path')
            if not dir_name or not full_path or not os.path.isdir(full_path):
                return None
            return dir_name if _dir_has_filename_match(full_path, dir_name) else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = executor.map(_scan_one, all_rma_directories)
            matched_dirs = {r for r in results if r}
    except Exception as e:
        # Safety fallback: serial scan
        logger.warning(f"GPU SN parallel scan fallback to serial: {e}")
        matched_dirs = set()
        for rma_dir in all_rma_directories:
            dir_name = rma_dir.get('name')
            full_path = rma_dir.get('full_path')
            if not dir_name or not full_path or not os.path.isdir(full_path):
                continue
            if _dir_has_filename_match(full_path, dir_name):
                matched_dirs.add(dir_name)

    # Cache for 5 minutes to reduce filesystem load
    cache.set(cache_key, list(matched_dirs), 300)
    return matched_dirs


@login_required  
def rma_log(request, path="", base=None):
    """
    RMA Logs view - displays RMA directories from /srv/rma
    Supports browsing RMA directories with pattern {base_sn}_{rma_number}
    """
    ctx = _resolve_rma_context(base)
    base_dir = ctx["base_dir"]
    cache_ns = ctx["cache_ns"]

    if path:
        # If path is provided, use the existing log browser functionality
        return rma_log_browser(request, path, base=ctx["base"])
    
    # Check if this is an AJAX request for lazy loading
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return rma_log_ajax(request, base=ctx["base"])
    
    # Get search query from request
    search_query = request.GET.get('search', '').strip()
    search_mode = request.GET.get('search_mode', 'basic').strip() or 'basic'
    page_number = request.GET.get('page', 1)
    
    # Check if cache refresh is requested
    refresh_cache = request.GET.get('refresh', 'false').lower() == 'true'
    if refresh_cache:
        from django.core.cache import cache
        cache.delete(f'{cache_ns}_directories_basic_v2')
    
    # Get all RMA directories BASIC INFO ONLY (super fast - just listdir + stat)
    all_rma_directories = get_rma_directories_basic(base_dir=base_dir, cache_ns=cache_ns)
    
    # Filter directories based on search query
    if search_query and search_mode == 'gpu_sn':
        matched = find_rma_dirs_by_gpu_sn(search_query, base_dir=base_dir, cache_ns=cache_ns)
        rma_directories = [d for d in all_rma_directories if d.get('name') in matched]
    elif search_query:
        filtered_directories = []
        for rma_dir in all_rma_directories:
            # Search in base_sn or rma_number
            if (search_query.lower() in rma_dir['base_sn'].lower() or
                search_query in rma_dir['rma_number']):
                filtered_directories.append(rma_dir)
        rma_directories = filtered_directories
    else:
        rma_directories = all_rma_directories
    
    # Paginate the results
    paginator = Paginator(rma_directories, 20)  # Show 20 directories per page
    
    try:
        page_obj = paginator.get_page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.get_page(1)
    except EmptyPage:
        page_obj = paginator.get_page(paginator.num_pages)
    
    # LAZY LOAD: Load details only for the current page (20 items) with ASYNC optimization
    page_directories = list(page_obj.object_list)
    page_dir_names = [d['name'] for d in page_directories]
    
    # Load details for visible directories (uses async internally for better performance)
    details_map = load_directory_details_batch_optimized(page_dir_names, base_dir=base_dir, cache_ns=cache_ns)
    
    # Merge details into page directories
    page_directories_with_stats = []
    for rma_dir in page_directories:
        dir_name = rma_dir['name']
        if dir_name in details_map:
            rma_dir.update(details_map[dir_name])
        page_directories_with_stats.append(rma_dir)
    
    # Main RMA logs page - show RMA directories
    if ctx["base"] == "gb":
        context = {
            'page_title': 'RMA GB Logs',
            'overview_url_name': 'rma_gb_log',
            'browse_url_name': 'rma_gb_log_browse',
            'view_url_name': 'rma_gb_view_file',
            'delete_url_name': 'rma_gb_delete_file',
            'download_folder_url_name': 'rma_gb_download_folder',
            'download_folder_async_url_name': 'rma_gb_download_folder_async',
            'download_folder_status_base_path': '/rma/gb-download-folder-status/',
            'download_zip_url_name': 'rma_gb_download_zip',
            'collect_mi3xx_alllog_base_path': '/rma/gb-collect-mi3xx-alllog',
            'show_sys_sn_column': True,
            'page_obj': page_obj,
            'rma_directories': page_directories_with_stats,
            'search_query': search_query,
            'search_mode': search_mode,
            'total_directories': len(all_rma_directories),
            'filtered_count': len(rma_directories),
            'paginator': paginator,
            'page_number': page_number,
        }
    else:
        context = {
            'page_title': 'RMA Logs',
            'overview_url_name': 'rma_log',
            'browse_url_name': 'rma_log_browse',
            'view_url_name': 'rma_view_file',
            'delete_url_name': 'rma_delete_file',
            'download_folder_url_name': 'rma_download_folder',
            'download_folder_async_url_name': 'rma_download_folder_async',
            'download_folder_status_base_path': '/rma/download-folder-status/',
            'download_zip_url_name': 'rma_download_zip',
            'collect_mi3xx_alllog_base_path': '/rma/collect-mi3xx-alllog',
            'show_sys_sn_column': False,
            'page_obj': page_obj,
            'rma_directories': page_directories_with_stats,
            'search_query': search_query,
            'search_mode': search_mode,
            'total_directories': len(all_rma_directories),
            'filtered_count': len(rma_directories),
            'paginator': paginator,
            'page_number': page_number,
        }
    
    return render(request, 'features/rma_logs.html', context)

@login_required
def rma_log_ajax(request, base=None):
    """
    AJAX endpoint for lazy loading RMA directories
    """
    ctx = _resolve_rma_context(base)
    base_dir = ctx["base_dir"]
    cache_ns = ctx["cache_ns"]
    try:
        search_query = request.GET.get('search', '').strip()
        search_mode = request.GET.get('search_mode', 'basic').strip() or 'basic'
        page_number = request.GET.get('page', 1)
        
        # Check if cache refresh is requested
        refresh_cache = request.GET.get('refresh', 'false').lower() == 'true'
        if refresh_cache:
            from django.core.cache import cache
            cache.delete(f'{cache_ns}_directories_basic_v2')
        
        # Get all RMA directories BASIC INFO ONLY (super fast)
        all_rma_directories = get_rma_directories_basic(base_dir=base_dir, cache_ns=cache_ns)
        
        # Filter directories based on search query
        if search_query and search_mode == 'gpu_sn':
            matched = find_rma_dirs_by_gpu_sn(search_query, base_dir=base_dir, cache_ns=cache_ns)
            rma_directories = [d for d in all_rma_directories if d.get('name') in matched]
        elif search_query:
            filtered_directories = []
            for rma_dir in all_rma_directories:
                # Search in base_sn or rma_number
                if (search_query.lower() in rma_dir['base_sn'].lower() or
                    search_query in rma_dir['rma_number']):
                    filtered_directories.append(rma_dir)
            rma_directories = filtered_directories
        else:
            rma_directories = all_rma_directories
        
        # Paginate the results
        paginator = Paginator(rma_directories, 20)  # Show 20 directories per page
        
        try:
            page_obj = paginator.get_page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.get_page(1)
        except EmptyPage:
            page_obj = paginator.get_page(paginator.num_pages)
        
        # LAZY LOAD: Load details only for the current page (20 items) with ASYNC optimization
        page_directories = list(page_obj.object_list)
        page_dir_names = [d['name'] for d in page_directories]
        
        # Load details for visible directories (uses async internally for better performance)
        details_map = load_directory_details_batch_optimized(page_dir_names, base_dir=base_dir, cache_ns=cache_ns)
        
        # Merge details into page directories
        page_directories_with_stats = []
        for rma_dir in page_directories:
            dir_name = rma_dir['name']
            if dir_name in details_map:
                rma_dir.update(details_map[dir_name])
            page_directories_with_stats.append(rma_dir)
        
        # Prepare data for JSON response
        directories_data = []
        for rma_dir in page_directories_with_stats:
            directories_data.append({
                'name': rma_dir['name'],
                'base_sn': rma_dir['base_sn'],
                'rma_number': rma_dir['rma_number'],
                'sys_sn': rma_dir.get('sys_sn', 'N/A'),
                'test_details': rma_dir.get('test_details', {}),
                'gpu_model': rma_dir.get('gpu_model', 'Unknown'),
                'golden_number': rma_dir.get('golden_number', 'N/A'),
                'tester_name': rma_dir.get('tester_name', 'N/A'),
                'mtime': rma_dir['mtime'],
                'path': rma_dir['path'],
                'error': rma_dir.get('error', None)
            })
        
        response_data = {
            'success': True,
            'directories': directories_data,
            'search_mode': search_mode,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'total_directories': len(all_rma_directories),
            'filtered_count': len(rma_directories),
            'start_index': page_obj.start_index() if page_obj.object_list else 0,
            'end_index': page_obj.end_index() if page_obj.object_list else 0
        }
        
        return JsonResponse(response_data, safe=False)
        
    except Exception as e:
        logger.error(f"Error in RMA AJAX request: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'directories': [],
            'has_next': False,
            'has_previous': False,
            'current_page': 1,
            'total_pages': 1,
            'total_directories': 0,
            'filtered_count': 0,
            'start_index': 0,
            'end_index': 0
        }, status=500)


def get_rma_directories_basic(base_dir=None, cache_ns: str = "rma"):
    """
    Get BASIC list of RMA directories (fast - only name, base_sn, rma_number, mtime)
    Does NOT load test_status, gpu_model, or golden_number (use load_directory_details_batch for those)
    
    Returns:
        list: List of dictionaries with basic directory info
    """
    base_dir = base_dir or RMA_BASE_DIR
    # Check cache first
    cache_key = f"{cache_ns}_directories_basic_v2"
    cached_dirs = cache.get(cache_key)
    
    if cached_dirs is not None:
        return cached_dirs
    
    rma_directories = []
    
    try:
        # Check if local directory exists
        if not os.path.exists(base_dir):
            logger.warning(f"RMA base directory does not exist: {base_dir}")
            return []
        
        # List directories locally
        try:
            items = os.listdir(base_dir)
        except Exception as e:
            logger.error(f"Cannot list local RMA directory: {e}")
            return []
        
        # Pattern to match {base_sn}_{rma_number}
        pattern = re.compile(r'^(.+)_(.+)$')
        
        # Process local directory items - BASIC INFO ONLY
        for item in items:
            item_path = os.path.join(base_dir, item)
            
            # Skip non-directories
            if not os.path.isdir(item_path):
                continue
                
            # Check if it matches pattern
            if pattern.match(item):
                match = pattern.match(item)
                base_sn, rma_number = match.groups()
                
                try:
                    # Get basic directory stats locally
                    stat_info = os.stat(item_path)
                    mtime = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    mtime = 'Unknown'
                
                # Store ONLY basic info - no file reads or DB queries
                rma_directories.append({
                    'name': item,
                    'base_sn': base_sn,
                    'rma_number': rma_number,
                    'path': item,
                    'full_path': item_path,
                    'mtime': mtime,
                    'exists': True,
                    # Details will be loaded separately
                    'details_loaded': False,
                })
        
        # Sort by modified time (newest first), then by RMA number
        def sort_key(x):
            try:
                if x['mtime'] != 'Unknown':
                    mtime_dt = datetime.strptime(x['mtime'], "%Y-%m-%d %H:%M:%S")
                    return (mtime_dt, int(x['rma_number']) if x['rma_number'].isdigit() else x['rma_number'])
                else:
                    return (datetime.min, int(x['rma_number']) if x['rma_number'].isdigit() else x['rma_number'])
            except (ValueError, TypeError):
                return (datetime.min, x['rma_number'])
        
        rma_directories.sort(key=sort_key, reverse=True)
        
        # Cache the basic directory listing (30 seconds)
        cache.set(cache_key, rma_directories, RMA_CACHE_TIMEOUT)
        
    except Exception as e:
        logger.error(f"Error scanning RMA directories: {e}")
        return []
    
    return rma_directories


def load_directory_details_batch(directory_names, base_dir=None, cache_ns: str = "rma"):
    """
    Load details (test_status, gpu_model, golden_number) for a batch of directories
    Uses individual caching for each directory's details
    
    SYNC VERSION - For compatibility with Celery tasks
    For better performance in views, use async_load_directory_details_batch()
    
    Args:
        directory_names (list): List of directory names to load details for
        
    Returns:
        dict: Dictionary mapping directory name to its details
    """
    base_dir = base_dir or RMA_BASE_DIR
    details_map = {}
    
    # Batch query BOTH testers AND golden numbers at once to prevent connection pool exhaustion
    tester_map, golden_map = get_all_rma_data_batch(directory_names, base_dir=base_dir, cache_ns=cache_ns)
    
    for dir_name in directory_names:
        # Check cache first
        cache_key = f"{cache_ns}_details_{dir_name}"
        cached_details = cache.get(cache_key)
        
        if cached_details is not None:
            details_map[dir_name] = cached_details
            continue
        
        # Load details if not cached
        try:
            test_details = get_test_status(dir_name, base_dir=base_dir)
            gpu_model = get_gpu_model(dir_name, base_dir=base_dir, cache_ns=cache_ns)
            golden_number = golden_map.get(dir_name, 'N/A')  # Use batch lookup instead of individual query
            tester_name = tester_map.get(dir_name, 'N/A')  # Use batch lookup instead of individual query
            sys_sn = get_system_sn(dir_name, base_dir=base_dir, cache_ns=cache_ns)
            
            details = {
                'test_details': test_details,
                'gpu_model': gpu_model,
                'golden_number': golden_number,
                'tester_name': tester_name,
                'sys_sn': sys_sn,
                'details_loaded': True,
            }
            
            # Cache for 1 minute
            cache.set(cache_key, details, RMA_DETAILS_CACHE_TIMEOUT)
            details_map[dir_name] = details
            
        except Exception as e:
            logger.warning(f"Error loading details for {dir_name}: {e}")
            # Return minimal details on error
            details = {
                'test_details': {'N/A': 'Unknown'},
                'gpu_model': 'Unknown',
                'golden_number': 'N/A',
                'tester_name': 'N/A',
                'sys_sn': 'N/A',
                'details_loaded': True,
                'error': str(e),
            }
            details_map[dir_name] = details
    
    return details_map


async def async_load_directory_details_batch(directory_names, base_dir=None, cache_ns: str = "rma", max_concurrent=10):
    """
    Load details ASYNC for a batch of directories with concurrent file I/O
    Much faster than sync version when loading multiple directories
    
    Args:
        directory_names (list): List of directory names to load details for
        max_concurrent (int): Maximum number of concurrent operations
        
    Returns:
        dict: Dictionary mapping directory name to its details
    """
    base_dir = base_dir or RMA_BASE_DIR
    details_map = {}
    uncached_dirs = []
    
    # First pass: Check cache (sync, very fast)
    for dir_name in directory_names:
        cache_key = f"{cache_ns}_details_{dir_name}"
        cached_details = cache.get(cache_key)
        
        if cached_details is not None:
            details_map[dir_name] = cached_details
        else:
            uncached_dirs.append(dir_name)
    
    if not uncached_dirs:
        return details_map
    
    # Second pass: Load uncached details concurrently
    # Use semaphore to limit concurrent operations
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def load_single_directory_details(dir_name):
        """Load details for a single directory asynchronously"""
        async with semaphore:
            try:
                # Run all four operations concurrently
                test_details_task = asyncio.to_thread(get_test_status, dir_name, base_dir)
                gpu_model_task = asyncio.to_thread(get_gpu_model, dir_name, base_dir, cache_ns)
                golden_number_task = asyncio.to_thread(get_golden_number, dir_name, base_dir, cache_ns)
                tester_name_task = asyncio.to_thread(get_tester_name, dir_name, base_dir, cache_ns)
                sys_sn_task = asyncio.to_thread(get_system_sn, dir_name, base_dir, cache_ns)
                
                # Wait for all four to complete
                test_details, gpu_model, golden_number, tester_name, sys_sn = await asyncio.gather(
                    test_details_task,
                    gpu_model_task,
                    golden_number_task,
                    tester_name_task,
                    sys_sn_task,
                    return_exceptions=True
                )
                
                # Handle exceptions
                if isinstance(test_details, Exception):
                    logger.warning(f"Error loading test_status for {dir_name}: {test_details}")
                    test_details = {'N/A': 'Unknown'}
                
                if isinstance(gpu_model, Exception):
                    logger.warning(f"Error loading gpu_model for {dir_name}: {gpu_model}")
                    gpu_model = 'Unknown'
                
                if isinstance(golden_number, Exception):
                    logger.warning(f"Error loading golden_number for {dir_name}: {golden_number}")
                    golden_number = 'N/A'
                
                if isinstance(tester_name, Exception):
                    logger.warning(f"Error loading tester_name for {dir_name}: {tester_name}")
                    tester_name = 'N/A'

                if isinstance(sys_sn, Exception):
                    logger.warning(f"Error loading sys_sn for {dir_name}: {sys_sn}")
                    sys_sn = 'N/A'
                
                details = {
                    'test_details': test_details,
                    'gpu_model': gpu_model,
                    'golden_number': golden_number,
                    'tester_name': tester_name,
                    'sys_sn': sys_sn,
                    'details_loaded': True,
                }
                
                # Cache for 1 minute
                cache.set(f"{cache_ns}_details_{dir_name}", details, RMA_DETAILS_CACHE_TIMEOUT)
                
                return dir_name, details
                
            except Exception as e:
                logger.error(f"Unexpected error loading details for {dir_name}: {e}")
                return dir_name, {
                    'test_details': {'N/A': 'Unknown'},
                    'gpu_model': 'Unknown',
                    'golden_number': 'N/A',
                    'tester_name': 'N/A',
                    'sys_sn': 'N/A',
                    'details_loaded': True,
                    'error': str(e),
                }
    
    # Load all uncached directories concurrently
    tasks = [load_single_directory_details(dir_name) for dir_name in uncached_dirs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Collect results
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Task failed: {result}")
            continue
        dir_name, details = result
        details_map[dir_name] = details
    
    return details_map


def load_directory_details_batch_optimized(directory_names, base_dir=None, cache_ns: str = "rma"):
    """
    Optimized wrapper that uses async loading if possible, falls back to sync
    This is the recommended function to use in views
    
    Args:
        directory_names (list): List of directory names to load details for
        
    Returns:
        dict: Dictionary mapping directory name to its details
    """
    try:
        # Try to use async version for better performance
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            details_map = loop.run_until_complete(
                async_load_directory_details_batch(directory_names, base_dir=base_dir, cache_ns=cache_ns)
            )
            return details_map
        finally:
            loop.close()
    except Exception as e:
        logger.warning(f"Async loading failed, falling back to sync: {e}")
        # Fall back to sync version
        return load_directory_details_batch(directory_names, base_dir=base_dir, cache_ns=cache_ns)


def get_rma_directories(include_stats=False, include_status=False):
    """
    DEPRECATED: Use get_rma_directories_basic() + load_directory_details_batch() for better performance
    
    Get list of RMA directories from local /srv/rma-b31 matching pattern {base_sn}_{rma_number}
    
    Args:
        include_stats (bool): Whether to include file count and size stats (slower)
        include_status (bool): Whether to include test status from test_status.txt
    """
    # Check cache first for basic directory listing
    cache_key = f"rma_directories_basic"
    cached_dirs = cache.get(cache_key)
    
    if cached_dirs is None:
        rma_directories = []
        
        try:
            # Check if local directory exists
            if not os.path.exists(RMA_BASE_DIR):
                logger.warning(f"RMA base directory does not exist: {RMA_BASE_DIR}")
                return []
            
            # List directories locally
            try:
                items = os.listdir(RMA_BASE_DIR)
            except Exception as e:
                logger.error(f"Cannot list local RMA directory: {e}")
                return []
            
            # Pattern to match {base_sn}_{rma_number}
            pattern = re.compile(r'^(.+)_(.+)$')
            
            # Process local directory items
            for item in items:
                item_path = os.path.join(RMA_BASE_DIR, item)
                
                # Skip non-directories
                if not os.path.isdir(item_path):
                    continue
                    
                # Check if it matches pattern
                if pattern.match(item):
                    match = pattern.match(item)
                    base_sn, rma_number = match.groups()
                    
                    try:
                        # Get basic directory stats locally
                        try:
                            stat_info = os.stat(item_path)
                            mtime = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            mtime = 'Unknown'
                        
                        # Get test status if requested
                        test_details = {}
                        if include_status:
                            test_details = get_test_status(item)
                        
                        # Get GPU model
                        gpu_model = get_gpu_model(item)
                        
                        # Get golden number
                        golden_number = get_golden_number(item)
                        
                        rma_directories.append({
                            'name': item,
                            'base_sn': base_sn,
                            'rma_number': rma_number,
                            'path': item,
                            'full_path': item_path,
                            'file_count': 0,  # Will be loaded separately if needed
                            'total_size': '0 B',  # Will be loaded separately if needed
                            'mtime': mtime,
                            'exists': True,
                            'stats_loaded': False,
                            'test_details': test_details,
                            'gpu_model': gpu_model,
                            'golden_number': golden_number
                        })
                    except Exception as e:
                        logger.warning(f"Cannot access local RMA directory {item}: {e}")
                        
                        # Get test status if requested (even for errored directories)
                        test_details = {}
                        if include_status:
                            test_details = get_test_status(item)
                        
                        # Get GPU model (even for errored directories)
                        gpu_model = get_gpu_model(item)
                        
                        # Get golden number (even for errored directories)
                        golden_number = get_golden_number(item)
                        
                        rma_directories.append({
                            'name': item,
                            'base_sn': base_sn,
                            'rma_number': rma_number,
                            'path': item,
                            'full_path': item_path,
                            'file_count': 0,
                            'total_size': '0 B',
                            'mtime': 'Unknown',
                            'exists': True,
                            'error': str(e),
                            'stats_loaded': False,
                            'test_details': test_details,
                            'gpu_model': gpu_model,
                            'golden_number': golden_number
                        })
            
            # Sort by modified time (newest first), then by RMA number
            def sort_key(x):
                try:
                    # Parse mtime string to datetime for proper sorting
                    # mtime format is "YYYY-MM-DD HH:MM:SS"
                    if x['mtime'] != 'Unknown':
                        mtime_dt = datetime.strptime(x['mtime'], "%Y-%m-%d %H:%M:%S")
                        return (mtime_dt, int(x['rma_number']) if x['rma_number'].isdigit() else x['rma_number'])
                    else:
                        # Put unknown dates at the end
                        return (datetime.min, int(x['rma_number']) if x['rma_number'].isdigit() else x['rma_number'])
                except (ValueError, TypeError):
                    # Fallback to original sorting if mtime parsing fails
                    return (datetime.min, x['rma_number'])
            
            rma_directories.sort(key=sort_key, reverse=True)
            
            # Cache the basic directory listing
            cache.set(cache_key, rma_directories, RMA_CACHE_TIMEOUT)
            
        except Exception as e:
            logger.error(f"Error scanning remote RMA directories: {e}")
            return []
    else:
        rma_directories = cached_dirs
    
    # If stats are requested, load them for visible directories only
    if include_stats:
        rma_directories = load_directory_stats(rma_directories)
    
    return rma_directories


def load_directory_stats(directories, max_concurrent=5):
    """
    Load file count and size stats for directories.
    Only loads stats for directories that don't have them cached.
    """
    try:
        for i, rma_dir in enumerate(directories):
            # Limit concurrent operations to prevent overwhelming the system
            if i >= max_concurrent:
                break
                
            if rma_dir.get('stats_loaded', False):
                continue
                
            item = rma_dir['name']
            cache_key = f"rma_stats_{item}"
            cached_stats = cache.get(cache_key)
            
            if cached_stats:
                rma_dir.update(cached_stats)
                rma_dir['stats_loaded'] = True
                continue
            
            # Load stats locally
            file_count = 0
            total_size = 0
            
            try:
                item_path = os.path.join(RMA_BASE_DIR, item)
                
                # Count files locally
                def count_files():
                    count = 0
                    for root, dirs, files in os.walk(item_path):
                        count += len(files)
                    return count
                
                file_count_result, success, error = run_with_timeout(count_files, 30)
                if success:
                    file_count = file_count_result
                else:
                    logger.warning(f"File count timeout for {item}: {error}")
                
                # Calculate size locally (only if file count succeeded)
                if file_count > 0 and file_count < 10000:  # Skip size calc for very large directories
                    def calc_size():
                        size = 0
                        for root, dirs, files in os.walk(item_path):
                            for file in files:
                                try:
                                    file_path = os.path.join(root, file)
                                    size += os.path.getsize(file_path)
                                except (OSError, IOError):
                                    pass  # Skip files that can't be accessed
                        return size
                    
                    size_result, success, error = run_with_timeout(calc_size, 60)
                    if success:
                        total_size = size_result
                    else:
                        logger.warning(f"Size calculation timeout for {item}: {error}")
                        total_size = 0  # Use placeholder for large directories
                
            except (ValueError, AttributeError) as e:
                logger.warning(f"Error calculating stats for {item}: {e}")
            
            # Update directory with stats
            stats = {
                'file_count': file_count,
                'total_size': format_size(total_size) if total_size > 0 else ('Large directory' if file_count > 10000 else '0 B'),
                'stats_loaded': True
            }
            
            rma_dir.update(stats)
            
            # Cache the stats
            cache.set(cache_key, stats, RMA_STATS_CACHE_TIMEOUT)
            
    except Exception as e:
        logger.error(f"Error loading directory stats: {e}")
    
    return directories

def format_size(size):
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

def parse_sys_info_file(directory_name, base_dir=None, cache_ns: str = "rma"):
    """
    Parse sys_info.txt file to extract GPU model, BMC IP, and System SN.
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        dict: Dictionary with 'gpu_model', 'bmc_ip', and 'sys_sn' keys, or None if file doesn't exist
    """
    base_dir = base_dir or RMA_BASE_DIR
    cache_key = f"{cache_ns}_sys_info_{directory_name}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        sys_info_file_path = os.path.join(base_dir, directory_name, "sys_info.txt")
        
        if not os.path.exists(sys_info_file_path):
            return None
        
        result = {'gpu_model': None, 'bmc_ip': None, 'sys_sn': None}
        
        try:
            with open(sys_info_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse line by line
            for line in content.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Parse "KEY: VALUE" format
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == 'GPU_Model':
                        result['gpu_model'] = value if value else None
                    elif key == 'BMC_IP':
                        result['bmc_ip'] = value if value else None
                    elif key == 'SYS_SN':
                        result['sys_sn'] = value if value else None
            
            cache.set(cache_key, result, RMA_DETAILS_CACHE_TIMEOUT)
            return result
            
        except Exception as e:
            logger.warning(f"Error reading sys_info.txt for {directory_name}: {e}")
            return None
            
    except Exception as e:
        logger.warning(f"Error accessing sys_info.txt for {directory_name}: {e}")
        return None


def get_system_sn(directory_name, base_dir=None, cache_ns: str = "rma"):
    """
    Get System SN from sys_info.txt (SYS_SN: ...)
    """
    try:
        sys_info = parse_sys_info_file(directory_name, base_dir=base_dir, cache_ns=cache_ns)
        if sys_info and sys_info.get("sys_sn"):
            return sys_info["sys_sn"]
    except Exception:
        pass
    return "N/A"

def parse_test_status_content(content):
    """
    Parse test status content to extract individual test items and their statuses
    
    Args:
        content (str): Content of the test_status.txt file
        
    Returns:
        dict: Dictionary of {test_name: status} pairs
    """
    test_details = {}
    
    if not content:
        return test_details
    
    lines = content.strip().split('\n')
    
    # First pass: collect all test names and their statuses
    raw_tests = {}
    
    # Handle different formats
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Format 1: "TestName: STATUS" or "TestName STATUS"
        if ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                test_name = parts[0].strip()
                status = parts[1].strip().upper()
                raw_tests[test_name] = status
        elif ' ' in line:
            # Format 2: "TestName STATUS" (space separated)
            parts = line.split()
            if len(parts) >= 2:
                test_name = parts[0].strip()
                status = parts[1].strip().upper()
                raw_tests[test_name] = status
        else:
            # Format 3: Single line with overall status
            status = line.upper()
            test_name = 'Overall'
            raw_tests[test_name] = status
    
    # Second pass: determine display names based on status
    for test_name, status in raw_tests.items():
        display_name = test_name
        
        # Add "Running" prefix only if status shows running AND there's no passed/failed status for this test
        if status in ['RUNNING', 'IN PROGRESS', 'TESTING']:
            # Check if this test has passed/failed status - if not, add Running prefix
            if status not in ['PASSED', 'FAILED', 'COMPLETED', 'SUCCESS', 'ERROR', 'FAIL']:
                display_name = f'Running {test_name}'
        
        test_details[display_name] = status
    
    return test_details

def get_gpu_model(directory_name, base_dir=None, cache_ns: str = "rma"):
    """
    Get GPU model from sys_info.txt (primary) or gpu_model.txt (fallback) file in RMA directory
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        str: GPU model string or 'Unknown' if not found
    """
    base_dir = base_dir or RMA_BASE_DIR
    try:
        # Primary source: sys_info.txt
        sys_info = parse_sys_info_file(directory_name, base_dir=base_dir, cache_ns=cache_ns)
        if sys_info and sys_info.get('gpu_model'):
            return sys_info['gpu_model']
        
        # Fallback: gpu_model.txt
        gpu_model_file_path = os.path.join(base_dir, directory_name, "gpu_model.txt")
        
        if os.path.exists(gpu_model_file_path):
            try:
                with open(gpu_model_file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                
                if content:
                    return content
                else:
                    return 'Unknown'
            except Exception as e:
                logger.warning(f"Error reading GPU model file for {directory_name}: {e}")
                return 'Unknown'
        else:
            # File doesn't exist
            return 'Unknown'
            
    except Exception as e:
        logger.warning(f"Error reading GPU model for {directory_name}: {e}")
        return 'Unknown'

def get_golden_number(directory_name, base_dir=None, cache_ns: str = "rma"):
    """
    Get golden number from RMA Testing DB by reading BMC IP from sys_info.txt (primary) or bmc_ip.txt (fallback)
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        str: Golden number or 'N/A' if not found
    """
    base_dir = base_dir or RMA_BASE_DIR
    try:
        # Check cache first
        cache_key = f"{cache_ns}_golden_{directory_name}"
        cached_golden = cache.get(cache_key)
        if cached_golden is not None:
            return cached_golden
        
        bmc_ip = None
        
        # Primary source: sys_info.txt
        sys_info = parse_sys_info_file(directory_name, base_dir=base_dir, cache_ns=cache_ns)
        if sys_info and sys_info.get('bmc_ip'):
            bmc_ip = sys_info['bmc_ip']
        
        # Fallback: bmc_ip.txt
        if not bmc_ip:
            bmc_ip_file_path = os.path.join(base_dir, directory_name, "bmc_ip.txt")
            
            if os.path.exists(bmc_ip_file_path):
                try:
                    with open(bmc_ip_file_path, 'r', encoding='utf-8') as f:
                        bmc_ip = f.read().strip()
                except Exception as e:
                    logger.warning(f"Error reading BMC IP file for {directory_name}: {e}")
        
        # Query database if we have BMC IP
        if bmc_ip:
            # Use RMA Testing DB for main logs, RMA GB DB for GB logs
            from ..models import RmaTestingDb, RmaGbDb
            from django.db import connection
            
            # Query database for matching BMC IP
            try:
                model = RmaGbDb if cache_ns == "rma_gb" else RmaTestingDb
                rma_entry = model.objects.filter(bmc_ip=bmc_ip).first()
                if rma_entry and rma_entry.golden_number:
                    golden_number = rma_entry.golden_number
                    # Cache the result for 1 minute
                    cache.set(cache_key, golden_number, RMA_DETAILS_CACHE_TIMEOUT)
                    return golden_number
                else:
                    # IP found but no golden number or entry not found
                    cache.set(cache_key, 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
                    return 'N/A'
            except Exception as e:
                logger.warning(f"Error querying RMA Testing DB for {directory_name}: {e}")
                cache.set(cache_key, 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
                return 'N/A'
            finally:
                # Always close connection to prevent pool exhaustion
                connection.close()
        else:
            cache.set(cache_key, 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
            return 'N/A'
            
    except Exception as e:
        logger.warning(f"Error getting golden number for {directory_name}: {e}")
        return 'N/A'

def get_all_rma_data_batch(directory_names, base_dir=None, cache_ns: str = "rma"):
    """
    Get BOTH golden numbers AND tester names for multiple directories in a SINGLE database query.
    This prevents connection pool exhaustion by batching all queries together.
    
    Args:
        directory_names (list): List of RMA directory names
        
    Returns:
        tuple: (tester_map, golden_map) - two dictionaries mapping directory_name -> value
    """
    base_dir = base_dir or RMA_BASE_DIR
    from ..models import RmaTestingDb, RmaGbDb
    from django.db import connection
    
    tester_map = {}
    golden_map = {}
    bmc_ip_to_dirs = {}  # Map BMC IP to list of directory names
    
    # Step 1: Collect all BMC IPs from all directories and check cache
    for dir_name in directory_names:
        # Check cache first
        cached_tester = cache.get(f"{cache_ns}_tester_{dir_name}")
        cached_golden = cache.get(f"{cache_ns}_golden_{dir_name}")
        
        if cached_tester is not None and cached_golden is not None:
            tester_map[dir_name] = cached_tester
            golden_map[dir_name] = cached_golden
            continue
        
        # Get BMC IP for this directory
        bmc_ip = None
        
        # Try sys_info.txt first
        try:
            sys_info = parse_sys_info_file(dir_name, base_dir=base_dir, cache_ns=cache_ns)
            if sys_info and sys_info.get('bmc_ip'):
                bmc_ip = sys_info['bmc_ip']
        except Exception:
            pass
        
        # Try bmc_ip.txt as fallback
        if not bmc_ip:
            bmc_ip_file_path = os.path.join(base_dir, dir_name, "bmc_ip.txt")
            if os.path.exists(bmc_ip_file_path):
                try:
                    with open(bmc_ip_file_path, 'r', encoding='utf-8') as f:
                        bmc_ip = f.read().strip()
                except Exception:
                    pass
        
        # Store mapping if we found a BMC IP
        if bmc_ip:
            if bmc_ip not in bmc_ip_to_dirs:
                bmc_ip_to_dirs[bmc_ip] = []
            bmc_ip_to_dirs[bmc_ip].append(dir_name)
    
    # Step 2: Query database ONCE for all BMC IPs - get BOTH tester and golden number
    if bmc_ip_to_dirs:
        try:
            model = RmaGbDb if cache_ns == "rma_gb" else RmaTestingDb
            # Single query for all BMC IPs
            entries = model.objects.filter(
                bmc_ip__in=bmc_ip_to_dirs.keys()
            ).select_related('linked_user')
            
            # Step 3: Build lookup dictionaries for BOTH tester and golden number
            for entry in entries:
                bmc_ip = entry.bmc_ip
                
                # Determine tester name
                if entry.linked_user:
                    tester = entry.linked_user.username
                elif hasattr(entry, 'last_tester') and entry.last_tester:
                    tester = entry.last_tester
                else:
                    tester = 'N/A'
                
                # Get golden number
                golden = entry.golden_number if entry.golden_number else 'N/A'
                
                # Apply to all directories with this BMC IP
                for dir_name in bmc_ip_to_dirs[bmc_ip]:
                    tester_map[dir_name] = tester
                    golden_map[dir_name] = golden
                    # Cache both results
                    cache.set(f"{cache_ns}_tester_{dir_name}", tester, RMA_DETAILS_CACHE_TIMEOUT)
                    cache.set(f"{cache_ns}_golden_{dir_name}", golden, RMA_DETAILS_CACHE_TIMEOUT)
                    
        except Exception as e:
            logger.warning(f"Error in batch RMA data query: {e}")
        finally:
            # Explicitly close connection to prevent pool exhaustion
            connection.close()
    
    # Step 4: Fill in N/A for directories without data
    for dir_name in directory_names:
        if dir_name not in tester_map:
            tester_map[dir_name] = 'N/A'
            cache.set(f"{cache_ns}_tester_{dir_name}", 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
        if dir_name not in golden_map:
            golden_map[dir_name] = 'N/A'
            cache.set(f"{cache_ns}_golden_{dir_name}", 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
    
    return tester_map, golden_map


def get_tester_name(directory_name, base_dir=None, cache_ns: str = "rma"):
    """
    Get tester name from RMA Testing DB by reading BMC IP and finding linked user
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        str: Tester username or 'N/A' if not found
    """
    base_dir = base_dir or RMA_BASE_DIR
    try:
        # Check cache first
        cache_key = f"{cache_ns}_tester_{directory_name}"
        cached_tester = cache.get(cache_key)
        if cached_tester is not None:
            return cached_tester
        
        bmc_ip = None
        
        # Primary source: sys_info.txt
        sys_info = parse_sys_info_file(directory_name, base_dir=base_dir, cache_ns=cache_ns)
        if sys_info and sys_info.get('bmc_ip'):
            bmc_ip = sys_info['bmc_ip']
        
        # Fallback: bmc_ip.txt
        if not bmc_ip:
            bmc_ip_file_path = os.path.join(base_dir, directory_name, "bmc_ip.txt")
            
            if os.path.exists(bmc_ip_file_path):
                try:
                    with open(bmc_ip_file_path, 'r', encoding='utf-8') as f:
                        bmc_ip = f.read().strip()
                except Exception as e:
                    logger.warning(f"Error reading BMC IP file for {directory_name}: {e}")
        
        # Query database if we have BMC IP
        if bmc_ip:
            # Use RMA Testing DB for main logs, RMA GB DB for GB logs
            from ..models import RmaTestingDb, RmaGbDb
            from django.db import connection
            
            # Query database for matching BMC IP
            try:
                model = RmaGbDb if cache_ns == "rma_gb" else RmaTestingDb
                rma_entry = model.objects.filter(bmc_ip=bmc_ip).select_related('linked_user').first()
                # Show current tester if linked, otherwise show last tester
                if rma_entry and rma_entry.linked_user:
                    tester_name = rma_entry.linked_user.username  # Current tester
                    # Cache the result for 1 minute
                    cache.set(cache_key, tester_name, RMA_DETAILS_CACHE_TIMEOUT)
                    return tester_name
                elif rma_entry and hasattr(rma_entry, 'last_tester') and rma_entry.last_tester:
                    tester_name = rma_entry.last_tester  # Last tester
                    # Cache the result for 1 minute
                    cache.set(cache_key, tester_name, RMA_DETAILS_CACHE_TIMEOUT)
                    return tester_name
                else:
                    # No current or last tester
                    cache.set(cache_key, 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
                    return 'N/A' 
            except Exception as e:
                logger.warning(f"Error querying RMA Testing DB for tester of {directory_name}: {e}")
                cache.set(cache_key, 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
                return 'N/A'
            finally:
                # Always close connection to prevent pool exhaustion
                connection.close()
        else:
            cache.set(cache_key, 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
            return 'N/A'
            
    except Exception as e:
        logger.warning(f"Error getting tester name for {directory_name}: {e}")
        return 'N/A'

def get_test_status(directory_name, base_dir=None):
    """
    Get test status from test_status.txt file in RMA directory
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        dict: Dictionary of test details with individual test statuses
    """
    base_dir = base_dir or RMA_BASE_DIR
    try:
        # Read test_status.txt from the local directory
        status_file_path = os.path.join(base_dir, directory_name, "test_status.txt")
        
        if os.path.exists(status_file_path):
            try:
                with open(status_file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                test_details = parse_test_status_content(content)
                
                if test_details:
                    return test_details
                else:
                    return {'N/A': 'No Status'}
            except Exception as e:
                logger.warning(f"Error reading test status file for {directory_name}: {e}")
                return {'N/A': 'Unknown'}
        else:
            # File doesn't exist
            return {'N/A': 'No Status'}
            
    except Exception as e:
        logger.warning(f"Error reading test status for {directory_name}: {e}")
        return {'N/A': 'Unknown'}




def get_file_extension(filename):
    """Extract and format file extension for display"""
    if '.' not in filename:
        return 'Text file'
    
    ext = filename.split('.')[-1].upper()
    if ext in ['LOG', 'TXT']:
        return 'Log file'
    elif ext in ['CSV']:
        return 'CSV file'
    elif ext in ['JSON']:
        return 'JSON file'
    elif ext in ['PY']:
        return 'Python file'
    elif ext in ['JS']:
        return 'JavaScript file'
    elif ext in ['PDF']:
        return 'PDF file'
    elif ext in ['ZIP', 'TAR', 'GZ']:
        return 'Archive file'
    elif ext in ['JPG', 'JPEG', 'PNG', 'GIF']:
        return 'Image file'
    elif ext in ['XML']:
        return 'XML file'
    elif ext in ['HTML', 'HTM']:
        return 'HTML file'
    elif ext in ['SH']:
        return 'Shell script'
    elif ext in ['CFG', 'CONF', 'CONFIG']:
        return 'Config file'
    else:
        return f'{ext} file'

@login_required
def rma_log_browser(request, path="", base=None):
    """
    Browse RMA directory contents from remote host
    """
    ctx = _resolve_rma_context(base)
    base_dir = ctx["base_dir"]
    cache_ns = ctx["cache_ns"]
    decoded_path = unquote(path)
    # Construct remote path
    remote_path = os.path.normpath(os.path.join(base_dir, decoded_path))

    # Security check - ensure path stays within RMA_BASE_DIR
    if not remote_path.startswith(base_dir):
        raise Http404("Access denied")

    items = []
    total_size = 0
    file_count = 0
    dir_count = 0
    
    try:
        # Check if local directory exists
        if not os.path.exists(remote_path):
            raise Http404("Directory does not exist")

        # List directory contents locally
        try:
            dir_items = os.listdir(remote_path)
        except Exception as e:
            raise Http404(f"Cannot read directory: {e}")
        
        # Separate directories and files
        dirs = []
        files = []
        
        # Process directory items
        for name in dir_items:
            if name in ['.', '..']:
                continue
                
            item_full_path = os.path.join(remote_path, name)
            
            try:
                # Get file/directory stats
                stat_info = os.stat(item_full_path)
                is_dir = os.path.isdir(item_full_path)
                size = stat_info.st_size if not is_dir else 0
                
                # Format modification time
                mtime = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                
            except Exception as e:
                logger.warning(f"Cannot stat {item_full_path}: {e}")
                # Use defaults if stat fails
                is_dir = os.path.isdir(item_full_path)
                size = 0
                mtime = "Unknown"

            # relative path for URL reversing
            item_path = os.path.join(decoded_path, name).strip("/")

            item = {
                "name": name,
                "is_dir": is_dir,
                "size": "-" if is_dir else format_size(size),
                "raw_size": 0 if is_dir else size,
                "mtime": mtime,
                "path": item_path,
                "file_type": "Directory" if is_dir else get_file_extension(name),
            }
            
            if is_dir:
                dirs.append(item)
                dir_count += 1
            else:
                files.append(item)
                file_count += 1
                total_size += size
        
        # Sort directories and files separately
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())
        
        # Combine sorted lists with directories first
        items = dirs + files
        
    except Exception as e:
        logger.error(f"Error browsing remote directory {remote_path}: {e}")
        raise Http404("Cannot read directory")

    # Get current directory name
    if remote_path != base_dir:
        current_dir = os.path.basename(remote_path)
    else:
        current_dir = "RMA GB Logs" if ctx["base"] == "gb" else "RMA Logs"

    # Parent directory logic
    path_parts = decoded_path.strip("/").split("/") if decoded_path.strip("/") else []
    parent_path = "/".join(path_parts[:-1]) if len(path_parts) > 1 else None

    # Prepare path parts for breadcrumb
    breadcrumb_parts = []
    current_build = ""
    for part in path_parts:
        if part:  # Only add non-empty parts
            current_build = os.path.join(current_build, part).strip("/")
            breadcrumb_parts.append({
                "name": part,
                "path": current_build
            })

    # Check if current directory is an RMA directory and determine if MI3XX button should be shown
    show_mi3xx_button = False
    base_sn = None
    rma_number = None
    
    # Pattern to match {base_sn}_{rma_number}
    pattern = re.compile(r'^(.+)_(.+)$')
    dir_name = os.path.basename(remote_path)
    
    if pattern.match(dir_name):
        match = pattern.match(dir_name)
        base_sn, rma_number = match.groups()
        
        # Read GPU model from sys_info.txt
        sys_info = parse_sys_info_file(dir_name, base_dir=base_dir, cache_ns=cache_ns)
        if sys_info and sys_info.get('gpu_model'):
            gpu_model = sys_info['gpu_model'].upper()
            # Excluded GPU models for MI3XX ALL LOG
            excluded_models = ['H100', 'H200', 'B200', 'B300', 'GB200', 'GB300']
            
            # Check if GPU model is NOT in excluded list
            if not any(excluded in gpu_model for excluded in excluded_models):
                show_mi3xx_button = True
    
    if ctx["base"] == "gb":
        overview_url_name = "rma_gb_log"
        browse_url_name = "rma_gb_log_browse"
        view_url_name = "rma_gb_view_file"
        delete_url_name = "rma_gb_delete_file"
        download_folder_url_name = "rma_gb_download_folder"
        download_folder_async_url_name = "rma_gb_download_folder_async"
        download_folder_status_base_path = "/rma/gb-download-folder-status/"
        collect_mi3xx_alllog_base_path = "/rma/gb-collect-mi3xx-alllog"
        collect_mi3xx_alllog_status_base_path = "/rma/gb-collect-mi3xx-alllog-status/"
        ai_summary_base_path = "/rma/gb-generate-ai-summary/"
        ai_summary_status_base_path = "/rma/gb-generate-ai-summary-status/"
    else:
        overview_url_name = "rma_log"
        browse_url_name = "rma_log_browse"
        view_url_name = "rma_view_file"
        delete_url_name = "rma_delete_file"
        download_folder_url_name = "rma_download_folder"
        download_folder_async_url_name = "rma_download_folder_async"
        download_folder_status_base_path = "/rma/download-folder-status/"
        collect_mi3xx_alllog_base_path = "/rma/collect-mi3xx-alllog"
        collect_mi3xx_alllog_status_base_path = "/rma/collect-mi3xx-alllog-status/"
        ai_summary_base_path = "/rma/generate-ai-summary/"
        ai_summary_status_base_path = "/rma/generate-ai-summary-status/"

    # AI Summary: show button and redirect URL only in parent folder (one path segment)
    show_ai_summary_button = bool(AI_log_analyzer) and (len(path_parts) == 1)
    if len(path_parts) == 1:
        ai_summary_report_path = (decoded_path.strip("/") + "/AI_Report").replace("//", "/")
        ai_summary_redirect_url = reverse(browse_url_name, kwargs={"path": ai_summary_report_path})
    else:
        ai_summary_redirect_url = ""

    return render(request, "features/rma_logs_browser.html", {
        "items": items,
        "current_path": "/" + decoded_path.strip("/"),
        "current_dir": current_dir,
        "parent": parent_path,
        "breadcrumb_parts": breadcrumb_parts,
        "is_root": remote_path == base_dir,
        "total_size": format_size(total_size),
        "file_count": file_count,
        "dir_count": dir_count,
        "rma_host_ip": get_rma_host_ip(),
        "show_mi3xx_button": show_mi3xx_button,
        "base_sn": base_sn,
        "rma_number": rma_number,
        "overview_url_name": overview_url_name,
        "browse_url_name": browse_url_name,
        "view_url_name": view_url_name,
        "delete_url_name": delete_url_name,
        "download_folder_url_name": download_folder_url_name,
        "download_folder_async_url_name": download_folder_async_url_name,
        "download_folder_status_base_path": download_folder_status_base_path,
        "collect_mi3xx_alllog_base_path": collect_mi3xx_alllog_base_path,
        "collect_mi3xx_alllog_status_base_path": collect_mi3xx_alllog_status_base_path,
        "show_ai_summary_button": show_ai_summary_button,
        "ai_summary_base_path": ai_summary_base_path,
        "ai_summary_status_base_path": ai_summary_status_base_path,
        "ai_summary_redirect_url": ai_summary_redirect_url,
    })

def render_csv_as_html(file_content, filename):
    """Convert CSV file content to HTML table display"""
    try:
        # Try to detect CSV format and read the content
        f = io.StringIO(file_content)
        # Sample the first few lines to detect delimiter
        sample = f.read(1024)
        f.seek(0)
        
        # Try to detect delimiter
        sniffer = csv.Sniffer()
        delimiter = ','  # Default to comma
        
        try:
            dialect = sniffer.sniff(sample, delimiters=',;\t|')
            delimiter = dialect.delimiter
        except:
            # If sniffing fails, try to guess based on file extension and content
            if filename.lower().endswith('.tsv'):
                delimiter = '\t'
            elif '\t' in sample and sample.count('\t') > sample.count(','):
                delimiter = '\t'
            elif ';' in sample and sample.count(';') > sample.count(','):
                delimiter = ';'
            elif '|' in sample and sample.count('|') > sample.count(','):
                delimiter = '|'
        
        # Read CSV data
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)
        
        if not rows:
            return "<p>Empty CSV file</p>"
        
        # Build HTML table
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>{{ filename }}</title>
            <meta charset="utf-8">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    margin: 20px;
                    background-color: #f8f9fa;
                }
                .container {
                    max-width: 100%;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    overflow: hidden;
                }
                .header {
                    background: #007bff;
                    color: white;
                    padding: 15px 20px;
                    margin: 0;
                }
                .table-container {
                    overflow-x: auto;
                    max-height: 80vh;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 13px;
                }
                th {
                    background-color: #f8f9fa;
                    border: 1px solid #dee2e6;
                    padding: 8px 12px;
                    text-align: left;
                    font-weight: 600;
                    position: sticky;
                    top: 0;
                    z-index: 10;
                }
                td {
                    border: 1px solid #dee2e6;
                    padding: 6px 12px;
                    white-space: nowrap;
                }
                tr:nth-child(even) {
                    background-color: #f8f9fa;
                }
                tr:hover {
                    background-color: #e3f2fd;
                }
                .info {
                    padding: 15px 20px;
                    background: #f8f9fa;
                    border-top: 1px solid #dee2e6;
                    font-size: 14px;
                    color: #6c757d;
                }
                .download-link {
                    display: inline-block;
                    margin-top: 10px;
                    padding: 8px 16px;
                    background: #28a745;
                    color: white;
                    text-decoration: none;
                    border-radius: 4px;
                    font-size: 14px;
                }
                .download-link:hover {
                    background: #218838;
                    color: white;
                    text-decoration: none;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1 class="header">{{ filename }}</h1>
                <div class="table-container">
                    <table>
                        {% if header_row %}
                        <thead>
                            <tr>
                                {% for header in header_row %}
                                <th>{{ header|default:"Column "|add:forloop.counter }}</th>
                                {% endfor %}
                            </tr>
                        </thead>
                        {% endif %}
                        <tbody>
                            {% for row in data_rows %}
                            <tr>
                                {% for cell in row %}
                                <td>{{ cell|default:"" }}</td>
                                {% endfor %}
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="info">
                    <strong>File Info:</strong> {{ row_count }} rows, {{ col_count }} columns
                    <br>
                    <a href="?download=1" class="download-link">Download Original CSV</a>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Prepare template context
        header_row = rows[0] if rows else []
        data_rows = rows[1:] if len(rows) > 1 else []
        
        # If first row doesn't look like headers, treat it as data
        if header_row and all(cell.isdigit() or not cell.strip() for cell in header_row):
            data_rows = rows
            header_row = None
        
        context = {
            'filename': filename,
            'header_row': header_row,
            'data_rows': data_rows,
            'row_count': len(rows),
            'col_count': len(rows[0]) if rows else 0,
        }
        
        # Render template
        template = Template(html_template)
        return template.render(Context(context))
        
    except Exception as e:
        return f"<p>Error reading CSV file: {str(e)}</p>"

@login_required
def rma_view_file(request, path, base=None):
    """
    View RMA files from remote host for viewing only
    Downloads are handled directly via Apache2 server on RMA host
    """
    ctx = _resolve_rma_context(base)
    base_dir = ctx["base_dir"]
    # Construct remote path
    remote_path = os.path.normpath(os.path.join(base_dir, path))

    # Security check
    if not remote_path.startswith(base_dir):
        raise Http404("Access denied")

    # Get filename
    filename = os.path.basename(remote_path)
    
    try:
        # Check if local file exists and is not a directory
        if not os.path.exists(remote_path):
            raise Http404("File does not exist")
        
        if not os.path.isfile(remote_path):
            raise Http404("Path is not a file")

        # Check if download is requested FIRST - before doing any heavy operations
        download_requested = request.GET.get('download', 'false').lower() == 'true'
        
        # For downloads, serve through Django from local disk
        if download_requested:
            # For GB logs, path doesn't include "gb/" prefix, so remote Apache redirect would be wrong.
            if remote_download and ctx["base"] != "gb":
                # Use remote Apache download
                apache_url = f"http://{remote_download}/{path}"
                return redirect(apache_url)

            # Stream file from local disk with proper download headers
            try:
                # Determine content type
                _, ext = os.path.splitext(remote_path)
                ext = ext.lower()
                content_type, _ = mimetypes.guess_type(remote_path)
                if content_type is None:
                    content_type = 'application/octet-stream'
                
                # Use FileResponse for efficient streaming from local disk
                response = FileResponse(
                    open(remote_path, 'rb'),
                    content_type=content_type,
                    as_attachment=True,
                    filename=filename
                )
                response['Cache-Control'] = 'no-cache'
                
                return response
                
            except Exception as e:
                logger.error(f"Error downloading file from local disk: {e}")
                raise Http404(f"Cannot download file: {str(e)}")

        # For viewing only - continue with file size checks and content reading
        # Get file size locally
        try:
            file_size = os.path.getsize(remote_path)
        except Exception as e:
            raise Http404(f"Cannot access file: {e}")

        # For viewing, check file size to prevent serving extremely large files
        if file_size > 100 * 1024 * 1024:  # 100MB
            raise Http404("File too large to display. Use download option to get the file.")

        # Get file extension
        _, ext = os.path.splitext(remote_path)
        ext = ext.lower()

        # Read file content locally
        try:
            with open(remote_path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
        except Exception as e:
            logger.error(f"Error reading local file {remote_path}: {e}")
            raise Http404(f"Cannot read file content: {str(e)}")

        # Handle CSV and TSV files specially for viewing
        if ext in ['.csv', '.tsv']:
            # Display as HTML table
            html_content = render_csv_as_html(file_content, filename)
            response = HttpResponse(html_content, content_type='text/html; charset=utf-8')
            response['Cache-Control'] = 'no-cache'
            return response

        # Handle .md files: render as markdown HTML
        if ext == '.md':
            html_content = render_markdown_as_html(file_content, filename)
            response = HttpResponse(html_content, content_type='text/html; charset=utf-8')
            response['Cache-Control'] = 'no-cache'
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            return response

        # Determine content type
        content_type = None
        
        if not ext:
            # No extension - check if it's likely text based on content
            content_type = 'text/plain; charset=utf-8' if is_text_content(file_content) else 'application/octet-stream'
        elif ext in ['.txt', '.log', '.md', '.py', '.js', '.css', '.html', '.xml', '.json', '.yaml', '.yml', '.conf', '.cfg', '.ini', '.sh', '.bash']:
            content_type = 'text/plain; charset=utf-8'
        elif ext in ['.jpg', '.jpeg']:
            content_type = 'image/jpeg'
        elif ext == '.png':
            content_type = 'image/png'
        elif ext == '.gif':
            content_type = 'image/gif'
        elif ext == '.svg':
            content_type = 'image/svg+xml'
        elif ext == '.pdf':
            content_type = 'application/pdf'
        else:
            # Use mimetypes as fallback
            content_type, _ = mimetypes.guess_type(remote_path)
            if content_type is None:
                content_type = 'text/plain; charset=utf-8' if is_text_content(file_content) else 'application/octet-stream'
        
        # For text files, serve content directly for viewing
        if content_type and content_type.startswith('text/'):
            response = HttpResponse(file_content, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            response['Cache-Control'] = 'no-cache'
            return response

        # For binary files, serve through Django from local disk
        else:
            try:
                # Use FileResponse for efficient streaming from local disk
                response = FileResponse(
                    open(remote_path, 'rb'),
                    content_type=content_type,
                    filename=filename
                )
                response['Content-Disposition'] = f'inline; filename="{filename}"'
                response['Cache-Control'] = 'no-cache'
                return response
            except Exception as e:
                logger.error(f"Error serving binary file from local disk: {e}")
                raise Http404(f"Cannot serve file: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error viewing remote file {remote_path}: {e}")
        raise Http404(f"Cannot access file: {str(e)}")

def is_text_content(content):
    """Determine if content is text based on its string content"""
    try:
        # If content is already a string, it's likely text
        if isinstance(content, str):
            return True
        
        # If content is bytes, check for binary indicators
        if isinstance(content, bytes):
            # Check for null bytes (common in binary files)
            if b'\x00' in content[:8192]:
                return False
            
            # Try to decode as UTF-8
            try:
                content.decode('utf-8')
                return True
            except UnicodeDecodeError:
                return False
        
        return True
    except:
        return False

def is_text_file(file_path):
    """Determine if a file is a text file by examining its content"""
    try:
        with open(file_path, 'rb') as f:
            # Read first 8192 bytes to check for binary content
            chunk = f.read(8192)
            if not chunk:
                return True  # Empty file, treat as text
            
            # Check for null bytes (common in binary files)
            if b'\x00' in chunk:
                return False
            
            # Check if most characters are printable ASCII or common whitespace/control chars
            # Allow common text characters: printable ASCII + common whitespace/control
            text_chars = bytes({7,8,9,10,12,13,27} | set(range(0x20, 0x100)) - {0x7f})
            
            # Count non-text characters
            non_text_chars = chunk.translate(None, text_chars)
            
            # If less than 30% are non-text characters, consider it text
            if len(non_text_chars) / len(chunk) < 0.30:
                return True
            
            return False
    except:
        return False


@login_required
@require_POST
def rma_delete_file(request, path, base=None):
    """
    Delete a specific RMA file from local disk.

    Security rules:
    - target must resolve within RMA_BASE_DIR
    - only allow deleting the exact filename: nvidia_fw_update
    """
    ctx = _resolve_rma_context(base)
    base_dir = ctx["base_dir"]
    decoded_path = unquote(path).lstrip("/")
    target_path = os.path.normpath(os.path.join(base_dir, decoded_path))

    # Security check - ensure path stays within RMA_BASE_DIR
    if not target_path.startswith(base_dir):
        raise Http404("Access denied")

    # Only allow deleting the exact target filename
    if os.path.basename(target_path) != "nvidia_fw_update":
        raise Http404("File not allowed")

    try:
        if not os.path.exists(target_path):
            raise Http404("File does not exist")
        if not os.path.isfile(target_path):
            raise Http404("Path is not a file")

        os.remove(target_path)
        logger.info(f"Deleted RMA file: {target_path} (user={request.user})")
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error deleting RMA file {target_path}: {e}")
        raise Http404("Cannot delete file")

    # Redirect back to the parent folder listing
    parent_rel = os.path.dirname(decoded_path.strip("/"))
    if parent_rel:
        browse_url_name = "rma_gb_log_browse" if ctx["base"] == "gb" else "rma_log_browse"
        return redirect(browse_url_name, path=parent_rel)
    overview_url_name = "rma_gb_log" if ctx["base"] == "gb" else "rma_log"
    return redirect(overview_url_name)

def monitor_remote_progress(task_id, progress_file, rma_remote, stop_event):
    """
    Monitor remote progress file and update cache
    """
    import json
    
    while not stop_event.is_set():
        try:
            # Read progress file from remote server
            result = rma_remote.run(f"cat {progress_file} 2>/dev/null", hide=True, warn=True)
            
            if result.ok and result.stdout.strip():
                try:
                    progress_data = json.loads(result.stdout)
                    
                    # Update cache with progress from remote server
                    task_data = cache.get(f'mi3xx_task_{task_id}')
                    if task_data and task_data['status'] == 'processing':
                        task_data['progress'] = progress_data.get('progress', 0)
                        task_data['message'] = progress_data.get('message', 'Processing...')
                        cache.set(f'mi3xx_task_{task_id}', task_data, 1800)
                        # Don't log every update to reduce noise
                except json.JSONDecodeError:
                    pass  # Invalid JSON, skip this update
        except Exception as e:
            pass  # Silently skip errors during monitoring
        
        # Check every 2 seconds
        time.sleep(2)

def get_gpu_model_from_image(image_value):
    """
    Map image value to GPU model label
    
    Args:
        image_value (str): Image value from form (e.g., 'ubuntu2204-x86-rma')
        
    Returns:
        str: GPU model label (e.g., 'H100/200') or None if not found
    """
    image_to_gpu_map = {
        'ubuntu2204-x86-rma': 'H100/200',
        'ubuntu2204-b200-rma': 'B200',
        'ubuntu2204-gb200': 'GB200',
        'ubuntu2204-mi300x': 'MI300X',
        'ubuntu2204-mi325x': 'MI325X',
        'ubuntu2204-mi355x': 'MI355X',
    }
    return image_to_gpu_map.get(image_value)

def sanitize_notice_for_filename(notice):
    """
    Sanitize a user-provided notice string so it's safe to embed in filenames.

    Rules:
    - Convert whitespace to underscores
    - Keep only A-Z a-z 0-9 _ -
    - Strip leading/trailing underscores
    """
    if not notice:
        return ''
    notice = re.sub(r'\s+', '_', str(notice).strip())
    notice = re.sub(r'[^A-Za-z0-9_-]', '', notice)
    notice = notice.strip('_')
    return notice


def _mi3xx_update_task_cache(task_id, progress=None, message=None):
    """
    Best-effort helper to update the MI3XX task cache during post-processing.
    """
    try:
        task_data = cache.get(f'mi3xx_task_{task_id}')
        if not task_data:
            return
        if progress is not None:
            task_data['progress'] = progress
        if message:
            task_data['message'] = message
        cache.set(f'mi3xx_task_{task_id}', task_data, 1800)
    except Exception:
        # Cache updates are non-critical
        pass


def _mi3xx_locate_local_alllog_tar(dir_name, tar_filename):
    """
    Try to locate the downloaded ALLLOG tarball on the local filesystem.
    """
    import glob

    candidates = [
        os.path.join(RMA_BASE_DIR, dir_name, tar_filename),
        os.path.join("/srv/rma", dir_name, tar_filename),
    ]
    for p in candidates:
        try:
            if os.path.exists(p) and os.path.isfile(p):
                return p
        except Exception:
            continue

    # Fallback: search by name under the expected directory
    try:
        pattern = os.path.join(RMA_BASE_DIR, dir_name, tar_filename)
        matches = glob.glob(pattern)
        for p in matches:
            if os.path.exists(p) and os.path.isfile(p):
                return p
    except Exception:
        pass

    return None


def _mi3xx_postprocess_alllog_cper(
    task_id,
    dir_name,
    base_sn,
    timestamp,
    sanitized_notice,
    tar_filename,
):
    """
    Local post-processing for MI3XX ALL LOG:
    - untar the ALLLOG tarball into a temp folder
    - glob for extracted folder(s) starting with 'obmcdump'
    - collect all '*.cper' files into a list
    - run /root/addc_cdump_analyzer/cdump_analyzer.py for each cper
    - write one consolidated *_CPER_output.log next to the tar.gz
    - delete the extracted folder(s)

    Returns:
        tuple[str, str]: (output_log_filename, summary_message)
    """
    import tarfile
    import zipfile
    import glob
    import shutil
    import subprocess
    from datetime import datetime

    notice_part = f"_{sanitized_notice}" if sanitized_notice else ""
    output_log_filename = f"{base_sn}{notice_part}_ALLLOG_{timestamp}_CPER_output.log"

    tar_path = _mi3xx_locate_local_alllog_tar(dir_name, tar_filename)
    output_dir = os.path.dirname(tar_path) if tar_path else os.path.join(RMA_BASE_DIR, dir_name)
    os.makedirs(output_dir, exist_ok=True)
    output_log_path = os.path.join(output_dir, output_log_filename)

    def _safe_extract_all(tar, path):
        """
        Prevent path traversal during tar extraction.
        """
        abs_base = os.path.abspath(path)
        members = tar.getmembers()
        for m in members:
            member_path = os.path.abspath(os.path.join(path, m.name))
            if not member_path.startswith(abs_base + os.sep) and member_path != abs_base:
                raise ValueError(f"Unsafe tar member path: {m.name}")
        tar.extractall(path=path)

    extract_root = os.path.join(output_dir, f".mi3xx_alllog_extract_{timestamp}_{task_id[:8]}")
    error_count = 0

    with open(output_log_path, "w") as out:
        out.write("MI3XX ALL LOG CPER analyzer output\n")
        out.write(f"Generated: {datetime.now().isoformat()}\n")
        out.write(f"RMA Dir: {dir_name}\n")
        out.write(f"Tarball: {tar_filename}\n")
        out.write("\n")

        if not tar_path:
            out.write("ERROR: ALLLOG tarball not found on local filesystem.\n")
            out.write(f"Looked for: {os.path.join(RMA_BASE_DIR, dir_name, tar_filename)}\n")
            out.write(f"Also checked: {os.path.join('/srv/rma', dir_name, tar_filename)}\n")
            return output_log_filename, "CPER analysis failed: tarball not found locally"

        def _extract_archive(archive_path: str, dest_dir: str) -> None:
            """
            Extract ALLLOG archive to dest_dir.
            Supports: zip, tar (compressed or uncompressed).
            """
            if zipfile.is_zipfile(archive_path):
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(dest_dir)
                return
            if tarfile.is_tarfile(archive_path):
                # Use r:* to auto-detect compression (or none)
                with tarfile.open(archive_path, mode="r:*") as tf:
                    _safe_extract_all(tf, dest_dir)
                return
            raise ValueError("Unsupported archive format (not zip/tar)")

        try:
            _mi3xx_update_task_cache(task_id, 90, "Uncompressing ALLLOG archive...")
            os.makedirs(extract_root, exist_ok=True)
            _extract_archive(tar_path, extract_root)
            # Store full folder name(s) matching obmcdump*
            obmcdump_glob = glob.glob(
                os.path.join(extract_root, "**", "obmcdump*"), recursive=True
            )
            obmcdump_dirs = [p for p in obmcdump_glob if os.path.isdir(p)]

            out.write("Extracted obmcdump folders:\n")
            for p in obmcdump_dirs:
                out.write(f"- {p}\n")
            out.write("\n")

            cper_files = []
            for d in obmcdump_dirs:
                cper_files.extend(glob.glob(os.path.join(d, "**", "*.cper"), recursive=True))
            cper_files = sorted(set(cper_files))

            out.write("CPER files discovered:\n")
            for p in cper_files:
                out.write(f"- {p}\n")
            out.write("\n")

            if not cper_files:
                out.write("WARNING: No .cper files found under obmcdump* folders.\n")
                _mi3xx_update_task_cache(task_id, 99, "No CPER files found; cleanup in progress...")
                return output_log_filename, "No CPER files found; wrote CPER output log"

            analyzer_dir = "/root/addc_cdump_analyzer"
            analyzer_cmd = ["python3", "cdump_analyzer.py", "-i"]

            for idx, cper_path in enumerate(cper_files, start=1):
                prog = 90 + int((idx / max(1, len(cper_files))) * 9)
                _mi3xx_update_task_cache(
                    task_id,
                    prog,
                    f"Analyzing CPER ({idx}/{len(cper_files)}): {os.path.basename(cper_path)}",
                )

                out.write("=" * 80 + "\n")
                out.write(f"CPER: {cper_path}\n")
                out.write("=" * 80 + "\n")
                try:
                    result = subprocess.run(
                        analyzer_cmd + [cper_path],
                        cwd=analyzer_dir,
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )
                    out.write(f"Return code: {result.returncode}\n")
                    if result.stdout:
                        out.write("--- STDOUT ---\n")
                        out.write(result.stdout.rstrip() + "\n")
                    if result.stderr:
                        out.write("--- STDERR ---\n")
                        out.write(result.stderr.rstrip() + "\n")
                    if result.returncode != 0:
                        error_count += 1
                        out.write("ERROR: Analyzer returned non-zero exit code.\n")
                except Exception as e:
                    error_count += 1
                    out.write(f"ERROR: Analyzer execution failed: {e}\n")
                out.write("\n")

            out.write("Summary:\n")
            out.write(f"- CPER files analyzed: {len(cper_files)}\n")
            out.write(f"- Analyzer errors: {error_count}\n")

        except Exception as e:
            out.write(f"ERROR: CPER post-processing failed: {e}\n")
            return output_log_filename, f"CPER analysis failed: {e}"
        finally:
            _mi3xx_update_task_cache(task_id, 99, "Removing extracted ALLLOG folder(s)...")
            try:
                shutil.rmtree(extract_root, ignore_errors=True)
            except Exception as e:
                out.write(f"WARNING: Cleanup failed: {e}\n")

    if error_count:
        return output_log_filename, f"CPER analysis completed with {error_count} error(s); see {output_log_filename}"
    return output_log_filename, f"CPER analysis completed; wrote {output_log_filename}"


def collect_mi3xx_alllog_task(task_id, dir_name, base_sn, rma_number, bmc_ip, image=None, notice=None):
    """
    Background task to collect MI3XX ALL LOG on remote RMA server
    """
    from datetime import datetime
    
    try:
        # Update cache to processing
        cache.set(f'mi3xx_task_{task_id}', {
            'status': 'processing',
            'progress': 0,
            'message': 'Initiating log collection from BMC...',
            'filename': None,
            'error': None
        }, 1800)  # 30 minute timeout
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Map image to GPU model if image is provided
        gpu_model = None
        if image:
            gpu_model = get_gpu_model_from_image(image)
        sanitized_notice = sanitize_notice_for_filename(notice)
        
        # Create Python script with progress reporting
        remote_script = f'''#!/usr/bin/env python3
import requests
import sys
from time import sleep
import urllib3
import json
import os
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

bmc_ip = "{bmc_ip}"
base_sn = "{base_sn}"
rma_number = "{rma_number}"
timestamp = "{timestamp}"
task_id = "{task_id}"
user = "ADMIN"
pwd = "Golden@1234"
log_path = "/srv/rma"
gpu_model = {repr(gpu_model)}
notice = {repr(sanitized_notice)}

# Progress file for tracking
progress_file = f"/tmp/mi3xx_progress_{{task_id}}.json"

def update_progress(percent, message):
    try:
        with open(progress_file, 'w') as f:
            json.dump({{"progress": percent, "message": message}}, f)
    except:
        pass

update_progress(0, "Initiating log collection from BMC...")

# Step 1: Discover collect action from DiagLogs resource, then initiate log collection
ALL_LOG_1 = "/redfish/v1/Systems/UBB/LogServices/DiagLogs/Actions/LogService.CollectDiagnosticData"
ALL_LOG_2 = "/redfish/v1/Systems/UBB/LogServices/DiagLogs/Actions/Oem/LogService.GetAllLogs"

def _mi3xx_strings_from_actions(obj, out=None):
    if out is None:
        out = []
    if isinstance(obj, dict):
        for v in obj.values():
            _mi3xx_strings_from_actions(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _mi3xx_strings_from_actions(item, out)
    elif isinstance(obj, str):
        out.append(obj)
    return out

def _mi3xx_resolve_collect_path(actions):
    if not actions:
        return None
    flat = _mi3xx_strings_from_actions(actions)
    if ALL_LOG_1 in flat:
        return ALL_LOG_1
    if ALL_LOG_2 in flat:
        return ALL_LOG_2
    return None

diag_logs_url = f"https://{{bmc_ip}}/redfish/v1/Systems/UBB/LogServices/DiagLogs"
try:
    diag_resp = requests.get(diag_logs_url, auth=(user, pwd), verify=False, timeout=10)
    diag_resp.raise_for_status()
    diag_data = diag_resp.json()
except Exception as e:
    update_progress(0, f"ERROR: Failed to read DiagLogs resource: {{e}}")
    print(f"ERROR: Failed to read DiagLogs resource: {{e}}")
    sys.exit(1)

collect_path = _mi3xx_resolve_collect_path(diag_data.get("Actions"))
if not collect_path:
    update_progress(
        0,
        "ERROR: No supported collect action in DiagLogs Actions (expected "
        + ALL_LOG_1 + " or " + ALL_LOG_2 + ")",
    )
    print("ERROR: No supported collect action in DiagLogs Actions")
    sys.exit(1)

collect_url = f"https://{{bmc_ip}}{{collect_path}}"
payload = {{"DiagnosticDataType": "OEM", "OEMDiagnosticDataType": "AllLogs"}}

try:
    response = requests.post(collect_url, json=payload, auth=(user, pwd), verify=False, timeout=30)
    response.raise_for_status()
except Exception as e:
    update_progress(0, f"ERROR: Failed to initiate: {{e}}")
    print(f"ERROR: Failed to initiate log collection: {{e}}")
    sys.exit(1)

data = response.json()
task_uri = data.get('@odata.id')

if not task_uri:
    update_progress(0, "ERROR: No task URI returned from BMC")
    print("ERROR: No task URI returned from BMC")
    sys.exit(1)

update_progress(0, "Polling BMC for task status...")

# Step 2: Poll task status
max_polls = 60
poll_count = 0

while poll_count < max_polls:
    sleep(20)
    poll_count += 1
    
    try:
        task_resp = requests.get(f"https://{{bmc_ip}}{{task_uri}}", auth=(user, pwd), verify=False, timeout=30)
        
        if task_resp.status_code != 200:
            continue

        task_data = task_resp.json()
        percent = task_data.get('PercentComplete', 0)
        state = task_data.get('TaskState', '')
        
        # Show actual BMC percentage
        update_progress(percent, f"BMC collecting logs: {{state}}")

        if state.lower() == "completed" and percent == 100:
            break
        elif state.lower() in ["exception", "killed", "cancelled"]:
            update_progress(0, f"ERROR: Task failed: {{state}}")
            print(f"ERROR: Task failed or aborted: {{state}}")
            sys.exit(1)
            
    except Exception as e:
        continue

if poll_count >= max_polls:
    update_progress(0, "ERROR: Task timeout - exceeded 20 minutes")
    print("ERROR: Task timeout - exceeded 20 minutes")
    sys.exit(1)

# Step 3: Extract download location from headers
headers = task_data.get('Payload', {{}}).get('HttpHeaders', [])
location = None

for header in headers:
    if header.lower().startswith('location:'):
        location = header.split(':', 1)[1].strip()
        break

if not location:
    update_progress(0, "ERROR: No download location in task response")
    print("ERROR: No download location in task response")
    sys.exit(1)

# Step 4: Get entry data to find download URI
entry_url = f"https://{{bmc_ip}}{{location}}"

try:
    entry_resp = requests.get(entry_url, auth=(user, pwd), verify=False, timeout=30)
    entry_resp.raise_for_status()
except Exception as e:
    update_progress(0, f"ERROR: Failed to get entry data: {{e}}")
    print(f"ERROR: Failed to get entry data: {{e}}")
    sys.exit(1)

entry_data = entry_resp.json()
download_uri = entry_data.get('AdditionalDataURI')

if not download_uri:
    update_progress(0, "ERROR: No download URI found")
    print("ERROR: No download URI found")
    sys.exit(1)

# Step 5: Download the log file
notice_part = "_" + notice if notice else ""
alllog_file_name = f"{{base_sn}}{{notice_part}}_ALLLOG_{{timestamp}}.tar.gz"
alllog_file_path = f"{{log_path}}/{{base_sn}}_{{rma_number}}/{{alllog_file_name}}"

try:
    log_resp = requests.get(f"https://{{bmc_ip}}{{download_uri}}", auth=(user, pwd), verify=False, stream=True, timeout=300)
    log_resp.raise_for_status()
    
    with open(alllog_file_path, 'wb') as f:
        for chunk in log_resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    
    # Step 6: Create sys_info.txt if GPU model is provided
    if gpu_model:
        sys_info_dir = os.path.dirname(alllog_file_path)
        sys_info_path = os.path.join(sys_info_dir, "sys_info.txt")
        try:
            with open(sys_info_path, 'w') as f:
                f.write(f"GPU_Model: {{gpu_model}}\\n")
                f.write(f"BMC_IP: {{bmc_ip}}\\n")
        except Exception as e:
            # Non-fatal error, log but don't fail the entire process
            print(f"WARNING: Failed to create sys_info.txt: {{e}}")
    
    update_progress(100, f"Successfully saved: {{alllog_file_name}}")
    print(f"SUCCESS: {{alllog_file_name}}")
    
except Exception as e:
    update_progress(0, f"ERROR: Failed to download: {{e}}")
    print(f"ERROR: Failed to download log file: {{e}}")
    sys.exit(1)
'''
        
        # Get remote connection (Fabric)
        rma_remote = remote_dict.get('rma')
        if not rma_remote:
            cache.set(f'mi3xx_task_{task_id}', {
                'status': 'failed',
                'progress': 0,
                'message': 'Remote RMA server not configured',
                'filename': None,
                'error': 'Remote RMA server not configured'
            }, 1800)
            return
        
        remote_script_path = f"/tmp/mi3xx_alllog_{base_sn}_{timestamp}.py"
        progress_file = f"/tmp/mi3xx_progress_{task_id}.json"
        
        try:
            # Write script to remote server
            rma_remote.run(f"cat > {remote_script_path} << 'EOF'\n{remote_script}\nEOF", hide=True)
            rma_remote.run(f"chmod +x {remote_script_path}", hide=True)
            
            # Start progress monitoring thread
            stop_event = threading.Event()
            monitor_thread = threading.Thread(
                target=monitor_remote_progress,
                args=(task_id, progress_file, rma_remote, stop_event),
                daemon=True
            )
            monitor_thread.start()
            logger.info(f"Started progress monitoring thread for task {task_id}")
            
            # Execute script on remote server
            logger.info(f"Executing MI3XX ALL LOG collection script on remote server (task {task_id})")
            result = rma_remote.run(f"python3 {remote_script_path}", hide=True, warn=True, timeout=1300)
            
            # Stop progress monitoring
            stop_event.set()
            monitor_thread.join(timeout=5)  # Wait max 5 seconds for thread to stop
            
            # Clean up remote files
            rma_remote.run(f"rm -f {remote_script_path}", hide=True, warn=True)
            rma_remote.run(f"rm -f {progress_file}", hide=True, warn=True)
            
            logger.info(f"Remote script completed for task {task_id}")
            
            # Check if successful
            if result.ok and "SUCCESS:" in result.stdout:
                tar_filename = None
                for line in result.stdout.split('\n'):
                    if line.startswith('SUCCESS:'):
                        tar_filename = line.replace('SUCCESS:', '').strip()
                        break

                _mi3xx_update_task_cache(task_id, 90, "Starting CPER post-processing...")
                output_log_filename, summary_msg = _mi3xx_postprocess_alllog_cper(
                    task_id=task_id,
                    dir_name=dir_name,
                    base_sn=base_sn,
                    timestamp=timestamp,
                    sanitized_notice=sanitized_notice,
                    tar_filename=tar_filename or "",
                )

                cache.set(
                    f'mi3xx_task_{task_id}',
                    {
                        'status': 'completed',
                        'progress': 100,
                        'message': summary_msg,
                        'filename': output_log_filename,
                        'error': None,
                    },
                    1800,
                )
                logger.info(
                    f"MI3XX ALL LOG collected: {tar_filename}; CPER output: {output_log_filename}"
                )
            else:
                error_msg = 'Unknown error'
                for line in result.stdout.split('\n'):
                    if line.startswith('ERROR:'):
                        error_msg = line.replace('ERROR:', '').strip()
                        break
                if error_msg == 'Unknown error' and result.stderr:
                    error_msg = result.stderr.strip()
                
                cache.set(f'mi3xx_task_{task_id}', {
                    'status': 'failed',
                    'progress': 0,
                    'message': error_msg,
                    'filename': None,
                    'error': error_msg
                }, 1800)
                logger.error(f"MI3XX ALL LOG collection failed for task {task_id}: {error_msg}")
                
        except Exception as e:
            logger.error(f"Error executing remote script for task {task_id}: {e}")
            try:
                rma_remote.run(f"rm -f {remote_script_path}", hide=True, warn=True)
                rma_remote.run(f"rm -f {progress_file}", hide=True, warn=True)
            except:
                pass
            cache.set(f'mi3xx_task_{task_id}', {
                'status': 'failed',
                'progress': 0,
                'message': f'Remote execution failed: {str(e)}',
                'filename': None,
                'error': str(e)
            }, 1800)
        
    except Exception as e:
        logger.error(f"Error in MI3XX ALL LOG task {task_id}: {e}")
        cache.set(f'mi3xx_task_{task_id}', {
            'status': 'failed',
            'progress': 0,
            'message': str(e),
            'filename': None,
            'error': str(e)
        }, 1800)

@login_required
def rma_collect_mi3xx_alllog(request, path, base=None):
    """
    Start async MI3XX ALL LOG collection and return task ID immediately
    """
    import uuid
    
    decoded_path = unquote(path)
    ctx = _resolve_rma_context(base)
    base_dir = ctx["base_dir"]
    cache_ns = ctx["cache_ns"]
    
    # Extract base_sn and rma_number from path
    pattern = re.compile(r'^(.+)_(.+)$')
    dir_name = decoded_path.strip('/')
    match = pattern.match(dir_name)
    
    if not match:
        return JsonResponse({'success': False, 'error': 'Invalid directory pattern'}, status=400)
    
    base_sn, rma_number = match.groups()

    try:
        # Read BMC IP from sys_info.txt (local copy)
        sys_info = parse_sys_info_file(dir_name, base_dir=base_dir, cache_ns=cache_ns)
        if not sys_info or not sys_info.get('bmc_ip'):
            return JsonResponse({'success': False, 'error': 'BMC IP not found in sys_info.txt'}, status=400)
        
        bmc_ip = sys_info['bmc_ip']
        
        logger.info(f"Starting async MI3XX ALL LOG collection for {dir_name} at BMC IP: {bmc_ip}")
        
        # Generate unique task ID
        task_id = str(uuid.uuid4())
        
        # Initialize task in cache
        cache.set(f'mi3xx_task_{task_id}', {
            'status': 'initializing',
            'progress': 0,
            'message': 'Preparing to collect logs...',
            'filename': None,
            'error': None
        }, 1800)
        
        # Start background thread
        thread = threading.Thread(
            target=collect_mi3xx_alllog_task,
            args=(task_id, dir_name, base_sn, rma_number, bmc_ip, None, None),
            daemon=True
        )
        thread.start()
        
        return JsonResponse({
            'success': True,
            'task_id': task_id,
            'message': 'Log collection started'
        })
        
    except Exception as e:
        logger.error(f"Error starting MI3XX ALL LOG collection: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def rma_collect_mi3xx_alllog_from_form(request, base=None):
    """
    Start async MI3XX ALL LOG collection using Base SN, RMA Number, and BMC IP
    provided directly from the SXM GPU TEST form instead of an existing RMA
    logs directory.
    """
    import uuid
    import json

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        ctx = _resolve_rma_context(base)
        base_dir = ctx["base_dir"]

        if request.content_type == 'application/json':
            try:
                payload = json.loads(request.body.decode('utf-8'))
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)
        else:
            payload = request.POST

        base_sn = (payload.get('base_sn') or '').strip()
        rma_number = (payload.get('rma_number') or '').strip()
        bmc_ip = (payload.get('bmc_ip') or '').strip()
        image = (payload.get('image') or '').strip()
        notice = (payload.get('notice') or '').strip()

        if not base_sn or not rma_number or not bmc_ip:
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Base SN, RMA Number, and BMC IP are required for All Log collection.'
                },
                status=400,
            )

        dir_name = f"{base_sn}_{rma_number}"
        local_dir_path = os.path.join(base_dir, dir_name)

        # Ensure the target directory exists under RMA_BASE_DIR
        try:
            os.makedirs(local_dir_path, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create RMA directory {local_dir_path}: {e}")
            return JsonResponse(
                {'success': False, 'error': f'Failed to prepare RMA directory: {e}'},
                status=500,
            )

        logger.info(
            f"Starting async MI3XX ALL LOG collection from form for {dir_name} at BMC IP: {bmc_ip}"
        )

        # Generate unique task ID
        task_id = str(uuid.uuid4())

        # Initialize task in cache
        cache.set(
            f'mi3xx_task_{task_id}',
            {
                'status': 'initializing',
                'progress': 0,
                'message': 'Preparing to collect logs...',
                'filename': None,
                'error': None,
            },
            1800,
        )

        # Start background thread using the existing collection task
        thread = threading.Thread(
            target=collect_mi3xx_alllog_task,
            args=(task_id, dir_name, base_sn, rma_number, bmc_ip, image, notice),
            daemon=True,
        )
        thread.start()

        return JsonResponse(
            {
                'success': True,
                'task_id': task_id,
                'message': 'Log collection started',
            }
        )

    except Exception as e:
        logger.error(f"Error starting MI3XX ALL LOG collection from form: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def rma_collect_mi3xx_alllog_status(request, task_id, base=None):
    """
    Check status of MI3XX ALL LOG collection task
    """
    try:
        task_data = cache.get(f'mi3xx_task_{task_id}')
        
        if not task_data:
            return JsonResponse({'success': False, 'error': 'Task not found'}, status=404)
        
        return JsonResponse({
            'success': True,
            'status': task_data['status'],
            'progress': task_data['progress'],
            'message': task_data['message'],
            'filename': task_data.get('filename'),
            'error': task_data.get('error')
        })
        
    except Exception as e:
        logger.error(f"Error checking task status {task_id}: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def rma_generate_ai_summary(request, path="", base=None):
    """
    Start async AI summary generation for the current folder.
    """
    import uuid

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    if not AI_log_analyzer:
        return JsonResponse({'success': False, 'error': 'AI Summary feature is disabled.'}, status=403)

    decoded_path = unquote(path or "").strip("/")
    ctx = _resolve_rma_context(base)
    log_base_path = "rma/gb-logs" if ctx["base"] == "gb" else "rma/logs"
    quoted_path = quote(decoded_path, safe="/")
    if quoted_path:
        analysis_url = f"{request.scheme}://{request.get_host()}/{log_base_path}/{quoted_path}/"
    else:
        analysis_url = f"{request.scheme}://{request.get_host()}/{log_base_path}/"
    base_dir = ctx["base_dir"]
    target_dir = os.path.normpath(os.path.join(base_dir, decoded_path))
    full_log_path = target_dir

    if not full_log_path.startswith(base_dir):
        raise Http404("Access denied")

    if not os.path.exists(full_log_path) or not os.path.isdir(full_log_path):
        raise Http404("Directory does not exist")

    try:
        task_id = str(uuid.uuid4())
        cache.set(
            f'ai_summary_task_{task_id}',
            {
                'status': 'initializing',
                'progress': 0,
                'message': 'Preparing AI summary generation...',
                'report_path': None,
                'error': None,
            },
            1800,
        )

        thread = threading.Thread(
            target=_generate_ai_summary_task,
            args=(task_id, full_log_path, analysis_url),
            daemon=True,
        )
        thread.start()

        return JsonResponse(
            {
                'success': True,
                'task_id': task_id,
                'message': 'AI summary generation started.',
            }
        )
    except Exception as exc:
        logger.error(f"Error starting AI summary generation for {full_log_path}: {exc}")
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

@login_required
def rma_generate_ai_summary_status(request, task_id, base=None):
    """
    Check status of AI summary generation task.
    """
    try:
        task_data = cache.get(f'ai_summary_task_{task_id}')
        if not task_data:
            return JsonResponse({'success': False, 'error': 'Task not found'}, status=404)

        status = task_data.get('status')
        error = task_data.get('error')

        return JsonResponse(
            {
                'success': True,
                'status': status,
                'progress': task_data.get('progress', 0),
                'message': task_data.get('message', ''),
                'report_path': task_data.get('report_path'),
                'error': error,
            }
        )
    except Exception as exc:
        logger.error("Error checking AI summary task status %s: %s", task_id, exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

@login_required
def rma_download_zip(request, zip_filename, base=None):
    """
    Serve zip file from TEMP_ZIPS_DIR through Django
    """
    ctx = _resolve_rma_context(base)
    temp_zips_dir = ctx["temp_zips_dir"]
    # Security check - ensure filename is safe (no path traversal)
    if '..' in zip_filename or '/' in zip_filename or '\\' in zip_filename:
        raise Http404("Invalid filename")
    
    # Construct full path to zip file
    zip_path = os.path.normpath(os.path.join(temp_zips_dir, zip_filename))
    
    # Security check - ensure path stays within TEMP_ZIPS_DIR
    if not zip_path.startswith(temp_zips_dir):
        raise Http404("Access denied")
    
    try:
        # Check if file exists
        if not os.path.exists(zip_path):
            raise Http404("Zip file does not exist")
        
        if not os.path.isfile(zip_path):
            raise Http404("Path is not a file")
        
        # Use FileResponse for efficient streaming from local disk
        response = FileResponse(
            open(zip_path, 'rb'),
            content_type='application/zip',
            as_attachment=True,
            filename=zip_filename
        )
        response['Cache-Control'] = 'no-cache'
        
        return response
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error serving zip file {zip_filename}: {e}")
        raise Http404(f"Cannot serve zip file: {str(e)}")

@login_required
def rma_download_folder(request, path, base=None):
    """
    Download RMA folder as a zip file
    Creates a temporary zip file and serves through Django
    """
    from django.shortcuts import redirect
    from django.urls import reverse
    ctx = _resolve_rma_context(base)
    base_dir = ctx["base_dir"]
    temp_zips_dir = ctx["temp_zips_dir"]
    
    decoded_path = unquote(path)
    # Construct directory path
    remote_path = os.path.normpath(os.path.join(base_dir, decoded_path))

    # Security check - ensure path stays within RMA_BASE_DIR
    if not remote_path.startswith(base_dir):
        raise Http404("Access denied")

    try:
        # Check if directory exists and is actually a directory
        if not os.path.exists(remote_path):
            raise Http404("Directory does not exist")
        
        if not os.path.isdir(remote_path):
            raise Http404("Path is not a directory")

        # Get directory name for zip filename
        dir_name = os.path.basename(remote_path)
        
        # Create temporary zip file
        zip_filename = create_temp_zip(remote_path, dir_name, temp_zips_dir=temp_zips_dir)
        
        if zip_filename is None:
            raise Http404("Failed to create zip file")
        
        # Generate Django URL for download
        download_zip_url_name = 'rma_gb_download_zip' if ctx["base"] == 'gb' else 'rma_download_zip'
        django_url = reverse(download_zip_url_name, kwargs={'zip_filename': zip_filename})
        
        logger.info(f"Redirecting to Django for folder download: {django_url}")
        
        # Redirect to Django view for download
        return redirect(django_url)
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error preparing folder download for {remote_path}: {e}")
        raise Http404(f"Cannot prepare folder for download: {str(e)}")