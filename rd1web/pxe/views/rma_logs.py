from django.shortcuts import render
from django.http import HttpResponse, Http404, FileResponse, JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.template import Template, Context
from django.core.cache import cache
from urllib.parse import unquote
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
from asgiref.sync import sync_to_async
from ..remote_config import remote_dict

logger = logging.getLogger(__name__)
RMA_BASE_DIR = '/srv/rma-b31'
TEMP_ZIPS_DIR = '/srv/rma-b31/.TempZips'

# Cache timeout settings (shorter for faster new directory detection)
RMA_CACHE_TIMEOUT = 30  # 30 seconds cache for basic directory listings
RMA_DETAILS_CACHE_TIMEOUT = 60  # 1 minute cache for directory details (test_status, gpu_model, golden_number)
RMA_STATS_CACHE_TIMEOUT = 300  # 5 minutes cache for file stats
ZIP_TASK_TIMEOUT = 3600  # 1 hour timeout for zip creation tasks

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
    """Extract RMA host IP from remote_config"""
    rma_host = remote_dict['rma'].host
    # Extract IP from format like "root@10.4.4.140"
    if '@' in rma_host:
        return rma_host.split('@')[1]
    return rma_host

def cleanup_old_temp_zips():
    """
    Remove temporary zip files older than 1 hour from the temp directory
    """
    try:
        # Create temp directory if it doesn't exist
        if not os.path.exists(TEMP_ZIPS_DIR):
            os.makedirs(TEMP_ZIPS_DIR, exist_ok=True)
            logger.info(f"Created temp zips directory: {TEMP_ZIPS_DIR}")
            return
        
        current_time = time.time()
        one_hour_ago = current_time - 3600  # 1 hour in seconds
        
        # Iterate through files in temp directory
        for filename in os.listdir(TEMP_ZIPS_DIR):
            if not filename.endswith('.zip'):
                continue
            
            file_path = os.path.join(TEMP_ZIPS_DIR, filename)
            
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

def create_temp_zip(source_dir, dir_name):
    """
    Create a temporary zip file of a directory using system zip command (much faster)
    
    Args:
        source_dir (str): Full path to the directory to zip
        dir_name (str): Name of the directory (used for zip filename)
        
    Returns:
        str: Filename of the created zip file, or None on error
    """
    import subprocess
    
    try:
        # Clean up old zips first
        cleanup_old_temp_zips()
        
        # Create temp directory if it doesn't exist
        if not os.path.exists(TEMP_ZIPS_DIR):
            os.makedirs(TEMP_ZIPS_DIR, exist_ok=True)
            logger.info(f"Created temp zips directory: {TEMP_ZIPS_DIR}")
        
        # Generate unique filename with timestamp
        timestamp = int(time.time())
        zip_filename = f"{dir_name}_{timestamp}.zip"
        zip_path = os.path.join(TEMP_ZIPS_DIR, zip_filename)
        
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

def create_zip_async(task_id, source_dir, dir_name):
    """
    Create zip in background thread and update task status in cache
    
    Args:
        task_id (str): Unique task identifier
        source_dir (str): Full path to directory to zip
        dir_name (str): Name of the directory
    """
    try:
        logger.info(f"Starting async zip creation for task {task_id}: {dir_name}")
        
        # Update status to processing
        task_data = cache.get(f'zip_task_{task_id}')
        if task_data:
            task_data['status'] = 'processing'
            cache.set(f'zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
        
        # Create the zip file
        zip_filename = create_temp_zip(source_dir, dir_name)
        
        if zip_filename:
            # Update status to completed
            task_data = cache.get(f'zip_task_{task_id}')
            if task_data:
                task_data['status'] = 'completed'
                task_data['zip_filename'] = zip_filename
                cache.set(f'zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
            logger.info(f"Async zip creation completed for task {task_id}: {zip_filename}")
        else:
            # Update status to failed
            task_data = cache.get(f'zip_task_{task_id}')
            if task_data:
                task_data['status'] = 'failed'
                task_data['error'] = 'Failed to create zip file'
                cache.set(f'zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
            logger.error(f"Async zip creation failed for task {task_id}")
            
    except Exception as e:
        # Update status to failed
        task_data = cache.get(f'zip_task_{task_id}')
        if task_data:
            task_data['status'] = 'failed'
            task_data['error'] = str(e)
            cache.set(f'zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
        logger.error(f"Exception in async zip creation for task {task_id}: {e}")

@login_required
def rma_download_folder_async(request, path):
    """
    Start async zip creation and return task ID immediately
    Returns JSON with task_id for polling
    """
    import uuid
    
    decoded_path = unquote(path)
    remote_path = os.path.normpath(os.path.join(RMA_BASE_DIR, decoded_path))

    # Security check
    if not remote_path.startswith(RMA_BASE_DIR):
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
        cache.set(f'zip_task_{task_id}', task_data, ZIP_TASK_TIMEOUT)
        
        # Get directory name
        dir_name = os.path.basename(remote_path)
        
        # Start zip creation in background thread
        thread = threading.Thread(
            target=create_zip_async,
            args=(task_id, remote_path, dir_name),
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
def rma_download_folder_status(request, task_id):
    """
    Check status of async zip creation task from cache
    Returns JSON with status and download URL when ready
    """
    try:
        # Get task from cache
        task = cache.get(f'zip_task_{task_id}')
        
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
            apache_url = f"http://{get_rma_host_ip()}/.TempZips/{zip_filename}"
            response_data['download_url'] = apache_url
            # Cache will auto-expire after ZIP_TASK_TIMEOUT
            
        elif status == 'failed':
            # Zip creation failed
            response_data['error'] = task.get('error', 'Unknown error')
            # Optionally delete failed task immediately
            cache.delete(f'zip_task_{task_id}')
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error checking task status {task_id}: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required  
def rma_log(request, path=""):
    """
    RMA Logs view - displays RMA directories from /srv/rma
    Supports browsing RMA directories with pattern {base_sn}_{rma_number}
    """
    if path:
        # If path is provided, use the existing log browser functionality
        return rma_log_browser(request, path)
    
    # Check if this is an AJAX request for lazy loading
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return rma_log_ajax(request)
    
    # Get search query from request
    search_query = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)
    
    # Check if cache refresh is requested
    refresh_cache = request.GET.get('refresh', 'false').lower() == 'true'
    if refresh_cache:
        from django.core.cache import cache
        cache.delete('rma_directories_basic_v2')
    
    # Get all RMA directories BASIC INFO ONLY (super fast - just listdir + stat)
    all_rma_directories = get_rma_directories_basic()
    
    # Filter directories based on search query
    if search_query:
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
    details_map = load_directory_details_batch_optimized(page_dir_names)
    
    # Merge details into page directories
    page_directories_with_stats = []
    for rma_dir in page_directories:
        dir_name = rma_dir['name']
        if dir_name in details_map:
            rma_dir.update(details_map[dir_name])
        page_directories_with_stats.append(rma_dir)
    
    # Main RMA logs page - show RMA directories
    context = {
        'page_title': 'RMA Logs',
        'page_obj': page_obj,
        'rma_directories': page_directories_with_stats,
        'search_query': search_query,
        'total_directories': len(all_rma_directories),
        'filtered_count': len(rma_directories),
        'paginator': paginator,
        'page_number': page_number
    }
    
    return render(request, 'features/rma_logs.html', context)

@login_required
def rma_log_ajax(request):
    """
    AJAX endpoint for lazy loading RMA directories
    """
    try:
        search_query = request.GET.get('search', '').strip()
        page_number = request.GET.get('page', 1)
        
        # Check if cache refresh is requested
        refresh_cache = request.GET.get('refresh', 'false').lower() == 'true'
        if refresh_cache:
            from django.core.cache import cache
            cache.delete('rma_directories_basic_v2')
        
        # Get all RMA directories BASIC INFO ONLY (super fast)
        all_rma_directories = get_rma_directories_basic()
        
        # Filter directories based on search query
        if search_query:
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
        details_map = load_directory_details_batch_optimized(page_dir_names)
        
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


def get_rma_directories_basic():
    """
    Get BASIC list of RMA directories (fast - only name, base_sn, rma_number, mtime)
    Does NOT load test_status, gpu_model, or golden_number (use load_directory_details_batch for those)
    
    Returns:
        list: List of dictionaries with basic directory info
    """
    # Check cache first
    cache_key = "rma_directories_basic_v2"
    cached_dirs = cache.get(cache_key)
    
    if cached_dirs is not None:
        return cached_dirs
    
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
        
        # Process local directory items - BASIC INFO ONLY
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


def load_directory_details_batch(directory_names):
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
    details_map = {}
    
    # Batch query BOTH testers AND golden numbers at once to prevent connection pool exhaustion
    tester_map, golden_map = get_all_rma_data_batch(directory_names)
    
    for dir_name in directory_names:
        # Check cache first
        cache_key = f"rma_details_{dir_name}"
        cached_details = cache.get(cache_key)
        
        if cached_details is not None:
            details_map[dir_name] = cached_details
            continue
        
        # Load details if not cached
        try:
            test_details = get_test_status(dir_name)
            gpu_model = get_gpu_model(dir_name)
            golden_number = golden_map.get(dir_name, 'N/A')  # Use batch lookup instead of individual query
            tester_name = tester_map.get(dir_name, 'N/A')  # Use batch lookup instead of individual query
            
            details = {
                'test_details': test_details,
                'gpu_model': gpu_model,
                'golden_number': golden_number,
                'tester_name': tester_name,
                'details_loaded': True,
            }
            
            # Cache for 1 minute
            cache.set(cache_key, details, RMA_DETAILS_CACHE_TIMEOUT)
            details_map[dir_name] = details
            
        except Exception as e:
            logger.warning(f"Error loading details for {dir_name}: {e}")
            # Return minimal details on error
            details = {
                'test_details': {'Overall': 'Unknown'},
                'gpu_model': 'Unknown',
                'golden_number': 'N/A',
                'tester_name': 'N/A',
                'details_loaded': True,
                'error': str(e),
            }
            details_map[dir_name] = details
    
    return details_map


async def async_load_directory_details_batch(directory_names, max_concurrent=10):
    """
    Load details ASYNC for a batch of directories with concurrent file I/O
    Much faster than sync version when loading multiple directories
    
    Args:
        directory_names (list): List of directory names to load details for
        max_concurrent (int): Maximum number of concurrent operations
        
    Returns:
        dict: Dictionary mapping directory name to its details
    """
    details_map = {}
    uncached_dirs = []
    
    # First pass: Check cache (sync, very fast)
    for dir_name in directory_names:
        cache_key = f"rma_details_{dir_name}"
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
                test_details_task = asyncio.to_thread(get_test_status, dir_name)
                gpu_model_task = asyncio.to_thread(get_gpu_model, dir_name)
                golden_number_task = asyncio.to_thread(get_golden_number, dir_name)
                tester_name_task = asyncio.to_thread(get_tester_name, dir_name)
                
                # Wait for all four to complete
                test_details, gpu_model, golden_number, tester_name = await asyncio.gather(
                    test_details_task,
                    gpu_model_task,
                    golden_number_task,
                    tester_name_task,
                    return_exceptions=True
                )
                
                # Handle exceptions
                if isinstance(test_details, Exception):
                    logger.warning(f"Error loading test_status for {dir_name}: {test_details}")
                    test_details = {'Overall': 'Unknown'}
                
                if isinstance(gpu_model, Exception):
                    logger.warning(f"Error loading gpu_model for {dir_name}: {gpu_model}")
                    gpu_model = 'Unknown'
                
                if isinstance(golden_number, Exception):
                    logger.warning(f"Error loading golden_number for {dir_name}: {golden_number}")
                    golden_number = 'N/A'
                
                if isinstance(tester_name, Exception):
                    logger.warning(f"Error loading tester_name for {dir_name}: {tester_name}")
                    tester_name = 'N/A'
                
                details = {
                    'test_details': test_details,
                    'gpu_model': gpu_model,
                    'golden_number': golden_number,
                    'tester_name': tester_name,
                    'details_loaded': True,
                }
                
                # Cache for 1 minute
                cache.set(f"rma_details_{dir_name}", details, RMA_DETAILS_CACHE_TIMEOUT)
                
                return dir_name, details
                
            except Exception as e:
                logger.error(f"Unexpected error loading details for {dir_name}: {e}")
                return dir_name, {
                    'test_details': {'Overall': 'Unknown'},
                    'gpu_model': 'Unknown',
                    'golden_number': 'N/A',
                    'tester_name': 'N/A',
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


def load_directory_details_batch_optimized(directory_names):
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
                async_load_directory_details_batch(directory_names)
            )
            return details_map
        finally:
            loop.close()
    except Exception as e:
        logger.warning(f"Async loading failed, falling back to sync: {e}")
        # Fall back to sync version
        return load_directory_details_batch(directory_names)


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

def parse_sys_info_file(directory_name):
    """
    Parse sys_info.txt file to extract GPU model and BMC IP
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        dict: Dictionary with 'gpu_model' and 'bmc_ip' keys, or None if file doesn't exist
    """
    try:
        sys_info_file_path = os.path.join(RMA_BASE_DIR, directory_name, "sys_info.txt")
        
        if not os.path.exists(sys_info_file_path):
            return None
        
        result = {'gpu_model': None, 'bmc_ip': None}
        
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
            
            return result
            
        except Exception as e:
            logger.warning(f"Error reading sys_info.txt for {directory_name}: {e}")
            return None
            
    except Exception as e:
        logger.warning(f"Error accessing sys_info.txt for {directory_name}: {e}")
        return None

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

def get_gpu_model(directory_name):
    """
    Get GPU model from sys_info.txt (primary) or gpu_model.txt (fallback) file in RMA directory
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        str: GPU model string or 'Unknown' if not found
    """
    try:
        # Primary source: sys_info.txt
        sys_info = parse_sys_info_file(directory_name)
        if sys_info and sys_info.get('gpu_model'):
            return sys_info['gpu_model']
        
        # Fallback: gpu_model.txt
        gpu_model_file_path = os.path.join(RMA_BASE_DIR, directory_name, "gpu_model.txt")
        
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

def get_golden_number(directory_name):
    """
    Get golden number from RMA Testing DB by reading BMC IP from sys_info.txt (primary) or bmc_ip.txt (fallback)
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        str: Golden number or 'N/A' if not found
    """
    try:
        # Check cache first
        cache_key = f"rma_golden_{directory_name}"
        cached_golden = cache.get(cache_key)
        if cached_golden is not None:
            return cached_golden
        
        bmc_ip = None
        
        # Primary source: sys_info.txt
        sys_info = parse_sys_info_file(directory_name)
        if sys_info and sys_info.get('bmc_ip'):
            bmc_ip = sys_info['bmc_ip']
        
        # Fallback: bmc_ip.txt
        if not bmc_ip:
            bmc_ip_file_path = os.path.join(RMA_BASE_DIR, directory_name, "bmc_ip.txt")
            
            if os.path.exists(bmc_ip_file_path):
                try:
                    with open(bmc_ip_file_path, 'r', encoding='utf-8') as f:
                        bmc_ip = f.read().strip()
                except Exception as e:
                    logger.warning(f"Error reading BMC IP file for {directory_name}: {e}")
        
        # Query database if we have BMC IP
        if bmc_ip:
            # Import RmaTestingDb model
            from ..models import RmaTestingDb
            from django.db import connection
            
            # Query database for matching BMC IP
            try:
                rma_entry = RmaTestingDb.objects.filter(bmc_ip=bmc_ip).first()
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

def get_all_rma_data_batch(directory_names):
    """
    Get BOTH golden numbers AND tester names for multiple directories in a SINGLE database query.
    This prevents connection pool exhaustion by batching all queries together.
    
    Args:
        directory_names (list): List of RMA directory names
        
    Returns:
        tuple: (tester_map, golden_map) - two dictionaries mapping directory_name -> value
    """
    from ..models import RmaTestingDb
    from django.db import connection
    
    tester_map = {}
    golden_map = {}
    bmc_ip_to_dirs = {}  # Map BMC IP to list of directory names
    
    # Step 1: Collect all BMC IPs from all directories and check cache
    for dir_name in directory_names:
        # Check cache first
        cached_tester = cache.get(f"rma_tester_{dir_name}")
        cached_golden = cache.get(f"rma_golden_{dir_name}")
        
        if cached_tester is not None and cached_golden is not None:
            tester_map[dir_name] = cached_tester
            golden_map[dir_name] = cached_golden
            continue
        
        # Get BMC IP for this directory
        bmc_ip = None
        
        # Try sys_info.txt first
        try:
            sys_info = parse_sys_info_file(dir_name)
            if sys_info and sys_info.get('bmc_ip'):
                bmc_ip = sys_info['bmc_ip']
        except Exception:
            pass
        
        # Try bmc_ip.txt as fallback
        if not bmc_ip:
            bmc_ip_file_path = os.path.join(RMA_BASE_DIR, dir_name, "bmc_ip.txt")
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
            # Single query for all BMC IPs
            entries = RmaTestingDb.objects.filter(
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
                    cache.set(f"rma_tester_{dir_name}", tester, RMA_DETAILS_CACHE_TIMEOUT)
                    cache.set(f"rma_golden_{dir_name}", golden, RMA_DETAILS_CACHE_TIMEOUT)
                    
        except Exception as e:
            logger.warning(f"Error in batch RMA data query: {e}")
        finally:
            # Explicitly close connection to prevent pool exhaustion
            connection.close()
    
    # Step 4: Fill in N/A for directories without data
    for dir_name in directory_names:
        if dir_name not in tester_map:
            tester_map[dir_name] = 'N/A'
            cache.set(f"rma_tester_{dir_name}", 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
        if dir_name not in golden_map:
            golden_map[dir_name] = 'N/A'
            cache.set(f"rma_golden_{dir_name}", 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
    
    return tester_map, golden_map


def get_tester_name(directory_name):
    """
    Get tester name from RMA Testing DB by reading BMC IP and finding linked user
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        str: Tester username or 'N/A' if not found
    """
    try:
        # Check cache first
        cache_key = f"rma_tester_{directory_name}"
        cached_tester = cache.get(cache_key)
        if cached_tester is not None:
            return cached_tester
        
        bmc_ip = None
        
        # Primary source: sys_info.txt
        sys_info = parse_sys_info_file(directory_name)
        if sys_info and sys_info.get('bmc_ip'):
            bmc_ip = sys_info['bmc_ip']
        
        # Fallback: bmc_ip.txt
        if not bmc_ip:
            bmc_ip_file_path = os.path.join(RMA_BASE_DIR, directory_name, "bmc_ip.txt")
            
            if os.path.exists(bmc_ip_file_path):
                try:
                    with open(bmc_ip_file_path, 'r', encoding='utf-8') as f:
                        bmc_ip = f.read().strip()
                except Exception as e:
                    logger.warning(f"Error reading BMC IP file for {directory_name}: {e}")
        
        # Query database if we have BMC IP
        if bmc_ip:
            # Import RmaTestingDb model
            from ..models import RmaTestingDb
            from django.db import connection
            
            # Query database for matching BMC IP
            try:
                rma_entry = RmaTestingDb.objects.filter(bmc_ip=bmc_ip).select_related('linked_user').first()
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

def get_test_status(directory_name):
    """
    Get test status from test_status.txt file in RMA directory
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        dict: Dictionary of test details with individual test statuses
    """
    try:
        # Read test_status.txt from the local directory
        status_file_path = os.path.join(RMA_BASE_DIR, directory_name, "test_status.txt")
        
        if os.path.exists(status_file_path):
            try:
                with open(status_file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                test_details = parse_test_status_content(content)
                
                if test_details:
                    return test_details
                else:
                    return {'Overall': 'No Status'}
            except Exception as e:
                logger.warning(f"Error reading test status file for {directory_name}: {e}")
                return {'Overall': 'Unknown'}
        else:
            # File doesn't exist
            return {'Overall': 'No Status'}
            
    except Exception as e:
        logger.warning(f"Error reading test status for {directory_name}: {e}")
        return {'Overall': 'Unknown'}




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
def rma_log_browser(request, path=""):
    """
    Browse RMA directory contents from remote host
    """
    decoded_path = unquote(path)
    # Construct remote path
    remote_path = os.path.normpath(os.path.join(RMA_BASE_DIR, decoded_path))

    # Security check - ensure path stays within RMA_BASE_DIR
    if not remote_path.startswith(RMA_BASE_DIR):
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
                "apache_download_url": f"http://{get_rma_host_ip()}/{item_path}" if not is_dir else None,
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
    current_dir = os.path.basename(remote_path) if remote_path != RMA_BASE_DIR else "RMA Logs"

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
        sys_info = parse_sys_info_file(dir_name)
        if sys_info and sys_info.get('gpu_model'):
            gpu_model = sys_info['gpu_model'].upper()
            # Excluded GPU models for MI3XX ALL LOG
            excluded_models = ['H100', 'H200', 'B200', 'B300', 'GB200', 'GB300']
            
            # Check if GPU model is NOT in excluded list
            if not any(excluded in gpu_model for excluded in excluded_models):
                show_mi3xx_button = True
    
    return render(request, "features/rma_logs_browser.html", {
        "items": items,
        "current_path": "/" + decoded_path.strip("/"),
        "current_dir": current_dir,
        "parent": parent_path,
        "breadcrumb_parts": breadcrumb_parts,
        "is_root": remote_path == RMA_BASE_DIR,
        "total_size": format_size(total_size),
        "file_count": file_count,
        "dir_count": dir_count,
        "rma_host_ip": get_rma_host_ip(),
        "show_mi3xx_button": show_mi3xx_button,
        "base_sn": base_sn,
        "rma_number": rma_number,
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
def rma_view_file(request, path):
    """
    View RMA files from remote host for viewing only
    Downloads are handled directly via Apache2 server on RMA host
    """
    # Construct remote path
    remote_path = os.path.normpath(os.path.join(RMA_BASE_DIR, path))

    # Security check
    if not remote_path.startswith(RMA_BASE_DIR):
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
        
        # For downloads, proxy through Django with minimal memory usage
        if download_requested:
            # Stream file from Apache2 with proper download headers (minimal memory approach)
            import requests
            from django.http import StreamingHttpResponse
            
            apache_url = f"http://{get_rma_host_ip()}/{path}"
            
            try:
                # Head request to get file size first
                head_response = requests.head(apache_url, timeout=30)
                head_response.raise_for_status()
                
                # Get file from Apache2 with streaming
                file_response = requests.get(apache_url, stream=True, timeout=300)
                file_response.raise_for_status()
                
                # Create streaming response with download headers
                def file_generator():
                    for chunk in file_response.iter_content(chunk_size=8192):
                        yield chunk
                
                # Determine content type from Apache response
                content_type = file_response.headers.get('content-type', 'application/octet-stream')
                
                response = StreamingHttpResponse(file_generator(), content_type='application/octet-stream')
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                response['Content-Length'] = head_response.headers.get('content-length', '')
                response['Cache-Control'] = 'no-cache'
                
                return response
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error downloading file from Apache2: {e}")
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

        # For binary files, redirect to Apache2 for direct serving/viewing
        else:
            apache_url = f"http://{get_rma_host_ip()}/{path}"
            from django.shortcuts import redirect
            return redirect(apache_url)
            
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

def collect_mi3xx_alllog_task(task_id, dir_name, base_sn, rma_number, bmc_ip):
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
        
        # Create Python script with progress reporting
        remote_script = f'''#!/usr/bin/env python3
import requests
import sys
from time import sleep
import urllib3
import json
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

bmc_ip = "{bmc_ip}"
base_sn = "{base_sn}"
rma_number = "{rma_number}"
timestamp = "{timestamp}"
task_id = "{task_id}"
user = "ADMIN"
pwd = "Golden@1234"
log_path = "/srv/rma"

# Progress file for tracking
progress_file = f"/tmp/mi3xx_progress_{{task_id}}.json"

def update_progress(percent, message):
    try:
        with open(progress_file, 'w') as f:
            json.dump({{"progress": percent, "message": message}}, f)
    except:
        pass

update_progress(0, "Initiating log collection from BMC...")

# Step 1: Initiate log collection
collect_url = f"https://{{bmc_ip}}/redfish/v1/Systems/UBB/LogServices/DiagLogs/Actions/LogService.CollectDiagnosticData"
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
alllog_file_name = f"{{base_sn}}_ALLLOG_{{timestamp}}.tar.gz"
alllog_file_path = f"{{log_path}}/{{base_sn}}_{{rma_number}}/{{alllog_file_name}}"

try:
    log_resp = requests.get(f"https://{{bmc_ip}}{{download_uri}}", auth=(user, pwd), verify=False, stream=True, timeout=300)
    log_resp.raise_for_status()
    
    with open(alllog_file_path, 'wb') as f:
        for chunk in log_resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    
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
                filename = None
                for line in result.stdout.split('\n'):
                    if line.startswith('SUCCESS:'):
                        filename = line.replace('SUCCESS:', '').strip()
                        break
                
                cache.set(f'mi3xx_task_{task_id}', {
                    'status': 'completed',
                    'progress': 100,
                    'message': f'Successfully saved: {filename}',
                    'filename': filename,
                    'error': None
                }, 1800)
                logger.info(f"Successfully collected MI3XX ALL LOG: {filename}")
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
def rma_collect_mi3xx_alllog(request, path):
    """
    Start async MI3XX ALL LOG collection and return task ID immediately
    """
    import uuid
    
    decoded_path = unquote(path)
    
    # Extract base_sn and rma_number from path
    pattern = re.compile(r'^(.+)_(.+)$')
    dir_name = decoded_path.strip('/')
    match = pattern.match(dir_name)
    
    if not match:
        return JsonResponse({'success': False, 'error': 'Invalid directory pattern'}, status=400)
    
    base_sn, rma_number = match.groups()

    try:
        # Read BMC IP from sys_info.txt (local copy)
        sys_info = parse_sys_info_file(dir_name)
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
            args=(task_id, dir_name, base_sn, rma_number, bmc_ip),
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
def rma_collect_mi3xx_alllog_status(request, task_id):
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
def rma_download_folder(request, path):
    """
    Download RMA folder as a zip file
    Creates a temporary zip file and redirects to Apache server for direct download
    """
    from django.shortcuts import redirect
    
    decoded_path = unquote(path)
    # Construct directory path
    remote_path = os.path.normpath(os.path.join(RMA_BASE_DIR, decoded_path))

    # Security check - ensure path stays within RMA_BASE_DIR
    if not remote_path.startswith(RMA_BASE_DIR):
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
        zip_filename = create_temp_zip(remote_path, dir_name)
        
        if zip_filename is None:
            raise Http404("Failed to create zip file")
        
        # Generate Apache URL for direct download
        apache_url = f"http://{get_rma_host_ip()}/.TempZips/{zip_filename}"
        
        logger.info(f"Redirecting to Apache for folder download: {apache_url}")
        
        # Redirect to Apache server for direct download
        return redirect(apache_url)
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error preparing folder download for {remote_path}: {e}")
        raise Http404(f"Cannot prepare folder for download: {str(e)}")