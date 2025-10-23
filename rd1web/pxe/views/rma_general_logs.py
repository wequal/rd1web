from django.shortcuts import render
from django.http import HttpResponse, Http404, JsonResponse
from django.contrib.auth.decorators import login_required, permission_required
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
import asyncio

logger = logging.getLogger(__name__)
RMA_GENERAL_BASE_DIR = '/srv/rma-b31-general/'

# Cache timeout settings
RMA_GENERAL_CACHE_TIMEOUT = 30  # 30 seconds cache for basic directory listings
RMA_GENERAL_DETAILS_CACHE_TIMEOUT = 60  # 1 minute cache for directory details

def get_rma_host_ip():
    """Extract RMA host IP from remote_config"""
    from ..remote_config import remote_dict
    rma_host = remote_dict['rma'].host
    # Extract IP from format like "root@10.4.4.140"
    if '@' in rma_host:
        return rma_host.split('@')[1]
    return rma_host

@login_required
@permission_required('pxe.can_view_rma_general_logs', raise_exception=True)
def rma_general_log(request, path=""):
    """
    RMA General Logs view - displays RMA directories from /srv/srvrma-b31-general/
    Supports browsing RMA directories with pattern {sys_sn}_{rma_number}
    """
    if path:
        # If path is provided, use the existing log browser functionality
        return rma_general_log_browser(request, path)
    
    # Check if this is an AJAX request for lazy loading
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return rma_general_log_ajax(request)
    
    # Get search query from request
    search_query = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)
    
    # Check if cache refresh is requested
    refresh_cache = request.GET.get('refresh', 'false').lower() == 'true'
    if refresh_cache:
        cache.delete('rma_general_directories_basic_v2')
    
    # Get all RMA directories BASIC INFO ONLY (super fast - just listdir + stat)
    all_rma_directories = get_rma_general_directories_basic()
    
    # Filter directories based on search query
    if search_query:
        filtered_directories = []
        for rma_dir in all_rma_directories:
            # Search in sys_sn or rma_number
            if (search_query.lower() in rma_dir['sys_sn'].lower() or 
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
    
    # Main RMA general logs page - show RMA directories
    context = {
        'page_title': 'RMA General Logs',
        'page_obj': page_obj,
        'rma_directories': page_directories_with_stats,
        'search_query': search_query,
        'total_directories': len(all_rma_directories),
        'filtered_count': len(rma_directories),
        'paginator': paginator,
        'page_number': page_number
    }
    
    return render(request, 'features/rma_general_logs.html', context)

@login_required
@permission_required('pxe.can_view_rma_general_logs', raise_exception=True)
def rma_general_log_ajax(request):
    """
    AJAX endpoint for lazy loading RMA General directories
    """
    try:
        search_query = request.GET.get('search', '').strip()
        page_number = request.GET.get('page', 1)
        
        # Check if cache refresh is requested
        refresh_cache = request.GET.get('refresh', 'false').lower() == 'true'
        if refresh_cache:
            cache.delete('rma_general_directories_basic_v2')
        
        # Get all RMA directories BASIC INFO ONLY (super fast)
        all_rma_directories = get_rma_general_directories_basic()
        
        # Filter directories based on search query
        if search_query:
            filtered_directories = []
            for rma_dir in all_rma_directories:
                # Search in sys_sn or rma_number
                if (search_query.lower() in rma_dir['sys_sn'].lower() or 
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
                'sys_sn': rma_dir['sys_sn'],
                'rma_number': rma_dir['rma_number'],
                'test_details': rma_dir.get('test_details', {}),
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
        logger.error(f"Error in RMA General AJAX request: {e}")
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


def get_rma_general_directories_basic():
    """
    Get BASIC list of RMA General directories (fast - only name, sys_sn, rma_number, mtime)
    Does NOT load test_status (use load_directory_details_batch for those)
    
    Returns:
        list: List of dictionaries with basic directory info
    """
    # Check cache first
    cache_key = "rma_general_directories_basic_v2"
    cached_dirs = cache.get(cache_key)
    
    if cached_dirs is not None:
        return cached_dirs
    
    rma_directories = []
    
    try:
        # Check if local directory exists
        if not os.path.exists(RMA_GENERAL_BASE_DIR):
            logger.warning(f"RMA General base directory does not exist: {RMA_GENERAL_BASE_DIR}")
            return []
        
        # List directories locally
        try:
            items = os.listdir(RMA_GENERAL_BASE_DIR)
        except Exception as e:
            logger.error(f"Cannot list local RMA General directory: {e}")
            return []
        
        # Pattern to match {sys_sn}_{rma_number}
        pattern = re.compile(r'^(.+)_(.+)$')
        
        # Process local directory items - BASIC INFO ONLY
        for item in items:
            item_path = os.path.join(RMA_GENERAL_BASE_DIR, item)
            
            # Skip non-directories
            if not os.path.isdir(item_path):
                continue
                
            # Check if it matches pattern
            if pattern.match(item):
                match = pattern.match(item)
                sys_sn, rma_number = match.groups()
                
                try:
                    # Get basic directory stats locally
                    stat_info = os.stat(item_path)
                    mtime = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    mtime = 'Unknown'
                
                # Store ONLY basic info - no file reads
                rma_directories.append({
                    'name': item,
                    'sys_sn': sys_sn,
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
        cache.set(cache_key, rma_directories, RMA_GENERAL_CACHE_TIMEOUT)
        
    except Exception as e:
        logger.error(f"Error scanning RMA General directories: {e}")
        return []
    
    return rma_directories


def load_directory_details_batch(directory_names):
    """
    Load details (test_status) for a batch of directories
    Uses individual caching for each directory's details
    
    Args:
        directory_names (list): List of directory names to load details for
        
    Returns:
        dict: Dictionary mapping directory name to its details
    """
    details_map = {}
    
    for dir_name in directory_names:
        # Check cache first
        cache_key = f"rma_general_details_{dir_name}"
        cached_details = cache.get(cache_key)
        
        if cached_details is not None:
            details_map[dir_name] = cached_details
            continue
        
        # Load details if not cached
        try:
            test_details = get_test_status(dir_name)
            
            details = {
                'test_details': test_details,
                'details_loaded': True,
            }
            
            # Cache for 1 minute
            cache.set(cache_key, details, RMA_GENERAL_DETAILS_CACHE_TIMEOUT)
            details_map[dir_name] = details
            
        except Exception as e:
            logger.warning(f"Error loading details for {dir_name}: {e}")
            # Return minimal details on error
            details = {
                'test_details': {'Overall': 'Unknown'},
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
        cache_key = f"rma_general_details_{dir_name}"
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
                # Run test status loading in thread pool
                test_details_task = asyncio.to_thread(get_test_status, dir_name)
                
                # Wait for completion
                test_details = await test_details_task
                
                # Handle exceptions
                if isinstance(test_details, Exception):
                    logger.warning(f"Error loading test_status for {dir_name}: {test_details}")
                    test_details = {'Overall': 'Unknown'}
                
                details = {
                    'test_details': test_details,
                    'details_loaded': True,
                }
                
                # Cache for 1 minute
                cache.set(f"rma_general_details_{dir_name}", details, RMA_GENERAL_DETAILS_CACHE_TIMEOUT)
                
                return dir_name, details
                
            except Exception as e:
                logger.error(f"Unexpected error loading details for {dir_name}: {e}")
                return dir_name, {
                    'test_details': {'Overall': 'Unknown'},
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

def get_test_status(directory_name):
    """
    Get test status from test_status.txt file in RMA General directory
    
    Args:
        directory_name (str): The RMA directory name
        
    Returns:
        dict: Dictionary of test details with individual test statuses
    """
    try:
        # Read test_status.txt from the local directory
        status_file_path = os.path.join(RMA_GENERAL_BASE_DIR, directory_name, "test_status.txt")
        
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

def format_size(size):
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

@login_required
@permission_required('pxe.can_view_rma_general_logs', raise_exception=True)
def rma_general_log_browser(request, path=""):
    """
    Browse RMA General directory contents
    """
    decoded_path = unquote(path)
    # Construct remote path
    remote_path = os.path.normpath(os.path.join(RMA_GENERAL_BASE_DIR, decoded_path))

    # Security check - ensure path stays within RMA_GENERAL_BASE_DIR
    if not remote_path.startswith(RMA_GENERAL_BASE_DIR):
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
                "apache_download_url": f"http://{get_rma_host_ip()}/general/{item_path}" if not is_dir else None,
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
    current_dir = os.path.basename(remote_path) if remote_path != RMA_GENERAL_BASE_DIR else "RMA General Logs"

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
    
    return render(request, "features/rma_general_logs_browser.html", {
        "items": items,
        "current_path": "/" + decoded_path.strip("/"),
        "current_dir": current_dir,
        "parent": parent_path,
        "breadcrumb_parts": breadcrumb_parts,
        "is_root": remote_path == RMA_GENERAL_BASE_DIR,
        "total_size": format_size(total_size),
        "file_count": file_count,
        "dir_count": dir_count,
        "rma_host_ip": get_rma_host_ip(),
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
@permission_required('pxe.can_view_rma_general_logs', raise_exception=True)
def rma_general_view_file(request, path):
    """
    View RMA General files for viewing and downloading
    """
    # Construct remote path
    remote_path = os.path.normpath(os.path.join(RMA_GENERAL_BASE_DIR, path))

    # Security check
    if not remote_path.startswith(RMA_GENERAL_BASE_DIR):
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
            
            apache_url = f"http://{get_rma_host_ip()}/general/{path}"
            
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
            apache_url = f"http://{get_rma_host_ip()}/general/{path}"
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

