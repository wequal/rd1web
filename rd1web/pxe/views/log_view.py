import os
from django.shortcuts import render
from datetime import datetime
from django.http import Http404
from django.contrib.auth.decorators import login_required
from urllib.parse import unquote

BASE_DIR = "/srv/log"

def format_size(size):
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

@login_required
def log_view(request, path=""):
    decoded_path = unquote(path)
    abs_path = os.path.normpath(os.path.join(BASE_DIR, decoded_path))

    if not abs_path.startswith(BASE_DIR):
        raise Http404("Access denied")

    if not os.path.exists(abs_path):
        raise Http404("Directory does not exist")

    items = []
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
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "path": item_path,
            }
            
            if is_dir:
                dirs.append(item)
            else:
                files.append(item)
        
        # Sort directories and files separately
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())
        
        # Combine sorted lists with directories first
        items = dirs + files
        
    except Exception:
        raise Http404("Cannot read directory")

    # Get current directory name
    current_dir = os.path.basename(abs_path) if abs_path != BASE_DIR else "Logs"

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

    return render(request, "features/show_logs.html", {
        "items": items,
        "current_path": "/" + decoded_path.strip("/"),
        "current_dir": current_dir,
        "parent": parent_path,
        "breadcrumb_parts": breadcrumb_parts,
        "is_root": abs_path == BASE_DIR
    })
