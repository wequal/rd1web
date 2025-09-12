from django.shortcuts import render
from django.http import HttpResponse, Http404, FileResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from urllib.parse import unquote
from datetime import datetime
import mimetypes
import os
import logging
import re

logger = logging.getLogger(__name__)
RMA_BASE_DIR = '/srv/rma'

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
    
    # Get all RMA directories
    all_rma_directories = get_rma_directories()
    
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
    
    # Main RMA logs page - show RMA directories
    context = {
        'page_title': 'RMA Logs',
        'page_obj': page_obj,
        'rma_directories': page_obj.object_list,
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
    search_query = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)
    
    # Get all RMA directories
    all_rma_directories = get_rma_directories()
    
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
    
    # Prepare data for JSON response
    directories_data = []
    for rma_dir in page_obj.object_list:
        directories_data.append({
            'name': rma_dir['name'],
            'base_sn': rma_dir['base_sn'],
            'rma_number': rma_dir['rma_number'],
            'file_count': rma_dir['file_count'],
            'total_size': rma_dir['total_size'],
            'mtime': rma_dir['mtime'],
            'path': rma_dir['path'],
            'error': rma_dir.get('error', None)
        })
    
    return JsonResponse({
        'directories': directories_data,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
        'current_page': page_obj.number,
        'total_pages': paginator.num_pages,
        'total_directories': len(all_rma_directories),
        'filtered_count': len(rma_directories),
        'start_index': page_obj.start_index() if page_obj.object_list else 0,
        'end_index': page_obj.end_index() if page_obj.object_list else 0
    })

def get_rma_directories():
    """
    Get list of RMA directories from /srv/rma matching pattern {base_sn}_{rma_number}
    """
    rma_directories = []
    
    try:
        if not os.path.exists(RMA_BASE_DIR):
            logger.warning(f"RMA base directory does not exist: {RMA_BASE_DIR}")
            return rma_directories
        
        # Pattern to match {base_sn}_{rma_number}
        # base_sn could be alphanumeric, rma_number should be numeric
        pattern = re.compile(r'^(.+)_([0-9]+)$')
        
        for item in os.listdir(RMA_BASE_DIR):
            full_path = os.path.join(RMA_BASE_DIR, item)
            
            if os.path.isdir(full_path):
                match = pattern.match(item)
                if match:
                    base_sn, rma_number = match.groups()
                    
                    try:
                        # Get directory stats
                        stat = os.stat(full_path)
                        
                        # Count files in the directory
                        file_count = 0
                        total_size = 0
                        try:
                            for file_item in os.listdir(full_path):
                                file_path = os.path.join(full_path, file_item)
                                if os.path.isfile(file_path):
                                    file_count += 1
                                    total_size += os.path.getsize(file_path)
                        except PermissionError:
                            pass
                        
                        rma_directories.append({
                            'name': item,
                            'base_sn': base_sn,
                            'rma_number': rma_number,
                            'path': item,
                            'full_path': full_path,
                            'file_count': file_count,
                            'total_size': format_size(total_size),
                            'mtime': datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            'exists': True
                        })
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Cannot access RMA directory {full_path}: {e}")
                        rma_directories.append({
                            'name': item,
                            'base_sn': base_sn,
                            'rma_number': rma_number,
                            'path': item,
                            'full_path': full_path,
                            'file_count': 0,
                            'total_size': '0 B',
                            'mtime': 'Unknown',
                            'exists': True,
                            'error': str(e)
                        })
        
        # Sort by RMA number (newest first), then by base_sn
        rma_directories.sort(key=lambda x: (int(x['rma_number']), x['base_sn']), reverse=True)
        
    except Exception as e:
        logger.error(f"Error scanning RMA directories: {e}")
    
    return rma_directories

def format_size(size):
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


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
    Browse RMA directory contents similar to log_view functionality
    """
    decoded_path = unquote(path)
    abs_path = os.path.normpath(os.path.join(RMA_BASE_DIR, decoded_path))

    if not abs_path.startswith(RMA_BASE_DIR):
        raise Http404("Access denied")

    if not os.path.exists(abs_path):
        raise Http404("Directory does not exist")

    items = []
    total_size = 0
    file_count = 0
    dir_count = 0
    
    try:
        # Get directory contents
        contents = os.listdir(abs_path)
        
        # Separate directories and files
        dirs = []
        files = []
        
        for name in contents:
            full_path = os.path.join(abs_path, name)
            stat = os.stat(full_path)
            is_dir = os.path.isdir(full_path)

            # relative path for URL reversing
            item_path = os.path.join(decoded_path, name).strip("/")

            item = {
                "name": name,
                "is_dir": is_dir,
                "size": "-" if is_dir else format_size(stat.st_size),
                "raw_size": 0 if is_dir else stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "path": item_path,
                "file_type": "Directory" if is_dir else get_file_extension(name),
            }
            
            if is_dir:
                dirs.append(item)
                dir_count += 1
            else:
                files.append(item)
                file_count += 1
                total_size += stat.st_size
        
        # Sort directories and files separately
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())
        
        # Combine sorted lists with directories first
        items = dirs + files
        
    except Exception:
        raise Http404("Cannot read directory")

    # Get current directory name
    current_dir = os.path.basename(abs_path) if abs_path != RMA_BASE_DIR else "RMA Logs"

    # Parent directory logic
    path_parts = decoded_path.strip("/").split("/")
    parent_path = "/".join(path_parts[:-1]) if path_parts else None

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
        "is_root": abs_path == RMA_BASE_DIR,
        "total_size": format_size(total_size),
        "file_count": file_count,
        "dir_count": dir_count
    })

@login_required
def rma_view_file(request, path):
    """
    View RMA files - similar to view_file but for RMA directory
    Supports both viewing and downloading based on 'download' parameter
    """
    full_path = os.path.normpath(os.path.join(RMA_BASE_DIR, path))

    if not full_path.startswith(RMA_BASE_DIR) or not os.path.exists(full_path):
        raise Http404("File does not exist")

    if os.path.isdir(full_path):
        raise Http404("Requested path is a directory")

    # Check file size to prevent serving extremely large files
    try:
        file_size = os.path.getsize(full_path)
        # Limit to 100MB to prevent memory/timeout issues
        if file_size > 100 * 1024 * 1024:  # 100MB
            raise Http404("File too large to display")
    except OSError:
        raise Http404("Cannot access file")

    # Check if user wants to download the file
    download_mode = request.GET.get('download') == '1'

    # Get file extension
    _, ext = os.path.splitext(full_path)
    ext = ext.lower()
    filename = os.path.basename(full_path)

    # Determine content type
    content_type = None
    
    # Handle files without extensions or common text files
    if not ext:
        # No extension - check if it's a text file
        if is_text_file(full_path):
            content_type = 'text/plain; charset=utf-8'
        else:
            content_type = 'application/octet-stream'
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
    elif ext in ['.doc', '.docx']:
        content_type = 'application/msword'
    elif ext in ['.xls', '.xlsx']:
        content_type = 'application/vnd.ms-excel'
    elif ext in ['.zip', '.tar', '.gz', '.bz2']:
        content_type = 'application/octet-stream'
    else:
        # Use mimetypes as fallback
        content_type, _ = mimetypes.guess_type(full_path)
        if content_type is None:
            # Final fallback - check if it's text
            if is_text_file(full_path):
                content_type = 'text/plain; charset=utf-8'
            else:
                content_type = 'application/octet-stream'

    # If download mode is requested, always serve as attachment
    if download_mode:
        try:
            response = FileResponse(
                open(full_path, 'rb'), 
                content_type=content_type or 'application/octet-stream',
                as_attachment=True,
                filename=filename
            )
            response['Cache-Control'] = 'no-cache'
            response['Content-Length'] = file_size
            return response
        except Exception as e:
            raise Http404(f"Cannot download file: {str(e)}")

    # Handle text files with proper encoding for viewing
    if content_type and content_type.startswith('text/'):
        try:
            # Try UTF-8 first
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            response = HttpResponse(content, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            response['Cache-Control'] = 'no-cache'
            return response
        except UnicodeDecodeError:
            # If UTF-8 fails, try latin-1
            try:
                with open(full_path, 'r', encoding='latin-1') as f:
                    content = f.read()
                response = HttpResponse(content, content_type='text/plain; charset=latin-1')
                response['Content-Disposition'] = f'inline; filename="{filename}"'
                response['Cache-Control'] = 'no-cache'
                return response
            except:
                # If all text reading fails, treat as binary
                content_type = 'application/octet-stream'

    # Handle binary files or when text reading failed (for viewing)
    try:
        # For images and other binary files, serve them efficiently
        response = FileResponse(
            open(full_path, 'rb'), 
            content_type=content_type or 'application/octet-stream'
        )
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Cache-Control'] = 'no-cache'
        response['Content-Length'] = file_size
        return response
            
    except Exception as e:
        raise Http404(f"Cannot read file: {str(e)}")

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