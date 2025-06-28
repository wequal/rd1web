import mimetypes
import csv
import io
from django.http import FileResponse, Http404, HttpResponse
from django.contrib.auth.decorators import login_required
from django.template import Template, Context
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
            text_chars = bytes({7,8,9,10,12,13,27} | set(range(0x20, 0x100)) - {0x7f})
            
            # Count non-text characters
            non_text_chars = chunk.translate(None, text_chars)
            
            # If less than 30% are non-text characters, consider it text
            if len(non_text_chars) / len(chunk) < 0.30:
                return True
            
            return False
    except:
        return False

def render_csv_as_html(file_path, filename):
    """Convert CSV file to HTML table display"""
    try:
        # Try to detect CSV format and read the file
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
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
def view_file(request, path):
    full_path = os.path.normpath(os.path.join(BASE_DIR, path))

    if not full_path.startswith(BASE_DIR) or not os.path.exists(full_path):
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

    # Get file extension
    _, ext = os.path.splitext(full_path)
    ext = ext.lower()
    filename = os.path.basename(full_path)

    # Handle CSV and TSV files specially
    if ext in ['.csv', '.tsv']:
        # Check if user wants to download the original file
        if request.GET.get('download') == '1':
            # Serve as download
            try:
                file = open(full_path, 'rb')
                content_type = 'text/csv' if ext == '.csv' else 'text/tab-separated-values'
                response = FileResponse(file, content_type=content_type, as_attachment=True, filename=filename)
                return response
            except Exception as e:
                raise Http404(f"Cannot read file: {str(e)}")
        else:
            # Display as HTML table
            html_content = render_csv_as_html(full_path, filename)
            response = HttpResponse(html_content, content_type='text/html; charset=utf-8')
            response['Cache-Control'] = 'no-cache'
            return response

    # Determine content type for non-CSV files
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

    # Handle binary files or when text reading failed
    try:
        # For images and other binary files, serve them efficiently
        if content_type and (content_type.startswith('image/') or content_type.startswith('application/')):
            # Use streaming response for better performance
            response = FileResponse(
                open(full_path, 'rb'), 
                content_type=content_type,
                as_attachment=False
            )
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            
            # Add proper caching headers for images
            if content_type.startswith('image/'):
                # Disable caching for chart images, cache others
                if 'chart' in filename.lower():
                    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                    response['Pragma'] = 'no-cache'
                    response['Expires'] = '0'
                else:
                    response['Cache-Control'] = 'public, max-age=3600'  # Cache other images for 1 hour
            else:
                response['Cache-Control'] = 'no-cache'
                
            # Add content length header
            response['Content-Length'] = file_size
            
            return response
        else:
            # For other binary files, still use FileResponse but with proper headers
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
