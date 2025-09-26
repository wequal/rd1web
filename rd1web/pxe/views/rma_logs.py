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
import time
from ..remote_config import remote_dict, async_rma
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)
RMA_BASE_DIR = '/srv/rma-b31'

# Cache timeout settings (shorter for faster new directory detection)
RMA_CACHE_TIMEOUT = 60  # 1 minute cache for directory listings
RMA_STATS_CACHE_TIMEOUT = 300  # 5 minutes cache for file stats

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
        cache.delete('rma_directories_basic')
    
    # Get all RMA directories (fast mode for initial load)
    all_rma_directories = get_rma_directories(include_stats=False, include_status=True)
    
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
    
    # Use page directories as-is (status already loaded)
    page_directories_with_stats = list(page_obj.object_list)
    
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
            cache.delete('rma_directories_basic')
        
        # Get all RMA directories (fast mode for initial load)
        all_rma_directories = get_rma_directories(include_stats=False, include_status=True)
        
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
        
        # Use page directories as-is (status already loaded)
        page_directories_with_stats = list(page_obj.object_list)
        
        # Prepare data for JSON response
        directories_data = []
        for rma_dir in page_directories_with_stats:
            directories_data.append({
                'name': rma_dir['name'],
                'base_sn': rma_dir['base_sn'],
                'rma_number': rma_dir['rma_number'],
                'test_details': rma_dir.get('test_details', {}),
                'gpu_model': rma_dir.get('gpu_model', 'Unknown'),
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

async def get_rma_directories_async(include_stats=False, include_status=False):
    """
    Get list of RMA directories from local /srv/rma-b31 matching pattern {base_sn}_{rma_number} (ASYNC VERSION)
    
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
                            test_details = await get_test_status_async(item)
                        
                        # Get GPU model
                        gpu_model = await get_gpu_model_async(item)
                        
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
                            'gpu_model': gpu_model
                        })
                    except Exception as e:
                        logger.warning(f"Cannot access local RMA directory {item}: {e}")
                        
                        # Get test status if requested (even for errored directories)
                        test_details = {}
                        if include_status:
                            test_details = await get_test_status_async(item)
                        
                        # Get GPU model (even for errored directories)
                        gpu_model = await get_gpu_model_async(item)
                        
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
                            'gpu_model': gpu_model
                        })
            
            # Sort by RMA number (newest first), then by base_sn
            def sort_key(x):
                try:
                    return (int(x['rma_number']), x['base_sn'])
                except ValueError:
                    return (x['rma_number'], x['base_sn'])
            
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
        rma_directories = await load_directory_stats_async(rma_directories)
    
    return rma_directories

def get_rma_directories(include_stats=False, include_status=False):
    """
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
                            'gpu_model': gpu_model
                        })
                    except Exception as e:
                        logger.warning(f"Cannot access local RMA directory {item}: {e}")
                        
                        # Get test status if requested (even for errored directories)
                        test_details = {}
                        if include_status:
                            test_details = get_test_status(item)
                        
                        # Get GPU model (even for errored directories)
                        gpu_model = get_gpu_model(item)
                        
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
                            'gpu_model': gpu_model
                        })
            
            # Sort by RMA number (newest first), then by base_sn
            def sort_key(x):
                try:
                    return (int(x['rma_number']), x['base_sn'])
                except ValueError:
                    return (x['rma_number'], x['base_sn'])
            
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

async def load_directory_stats_async(directories, max_concurrent=5):
    """
    Load file count and size stats for directories asynchronously.
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
                for root, dirs, files in os.walk(item_path):
                    file_count += len(files)
                
                # Calculate size locally (only if file count is reasonable)
                if file_count > 0 and file_count < 10000:  # Skip size calc for very large directories
                    for root, dirs, files in os.walk(item_path):
                        for file in files:
                            try:
                                file_path = os.path.join(root, file)
                                total_size += os.path.getsize(file_path)
                            except (OSError, IOError):
                                pass  # Skip files that can't be accessed
                
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
    Get GPU model from gpu_model.txt file in RMA directory
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        str: GPU model string or 'Unknown' if not found
    """
    try:
        # Read gpu_model.txt from the local directory
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

async def get_gpu_model_async(directory_name):
    """
    Get GPU model from gpu_model.txt file in RMA directory (ASYNC VERSION)
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        str: GPU model string or 'Unknown' if not found
    """
    try:
        # Read gpu_model.txt from the local directory
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

async def get_test_status_async(directory_name):
    """
    Get test status from test_status.txt file in RMA directory (ASYNC VERSION)
    
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
        "rma_host_ip": get_rma_host_ip()
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