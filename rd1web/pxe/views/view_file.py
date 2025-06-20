import mimetypes
from django.http import FileResponse, Http404, HttpResponse
from django.contrib.auth.decorators import login_required
import os

BASE_DIR = '/srv/log'

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
            text_chars = bytearray({7,8,9,10,12,13,27} | set(range(0x20, 0x100)) - {0x7f})
            
            # Count non-text characters
            non_text_chars = chunk.translate(None, text_chars)
            
            # If less than 30% are non-text characters, consider it text
            if len(non_text_chars) / len(chunk) < 0.30:
                return True
            
            return False
    except:
        return False

@login_required
def view_file(request, path):
    full_path = os.path.normpath(os.path.join(BASE_DIR, path))

    if not full_path.startswith(BASE_DIR) or not os.path.exists(full_path):
        raise Http404("File does not exist")

    if os.path.isdir(full_path):
        raise Http404("Requested path is a directory")

    # Get file extension
    _, ext = os.path.splitext(full_path)
    ext = ext.lower()

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

    # Handle text files with proper encoding
    if content_type and content_type.startswith('text/'):
        try:
            # Try UTF-8 first
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            response = HttpResponse(content, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="{os.path.basename(full_path)}"'
            response['Cache-Control'] = 'no-cache'
            return response
        except UnicodeDecodeError:
            # If UTF-8 fails, try latin-1
            try:
                with open(full_path, 'r', encoding='latin-1') as f:
                    content = f.read()
                response = HttpResponse(content, content_type='text/plain; charset=latin-1')
                response['Content-Disposition'] = f'inline; filename="{os.path.basename(full_path)}"'
                response['Cache-Control'] = 'no-cache'
                return response
            except:
                # If all text reading fails, treat as binary
                content_type = 'application/octet-stream'

    # Handle binary files or when text reading failed
    try:
        file = open(full_path, 'rb')
        response = FileResponse(file, content_type=content_type)
        response['Content-Disposition'] = f'inline; filename="{os.path.basename(full_path)}"'
        response['Cache-Control'] = 'no-cache'
        return response
    except Exception as e:
        raise Http404(f"Cannot read file: {str(e)}")
