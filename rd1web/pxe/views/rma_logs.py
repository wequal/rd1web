from django.shortcuts import render
from django.http import HttpResponse, Http404
import os
import logging

logger = logging.getLogger(__name__)

def rma_log(request):
    """
    RMA Logs view - displays RMA-related log files
    Simple template-based log viewer for RMA activities
    """
    context = {
        'page_title': 'RMA Logs',
        'logs_available': check_rma_logs_availability(),
        'recent_logs': get_recent_rma_logs()
    }
    
    return render(request, 'features/rma_logs.html', context)

def check_rma_logs_availability():
    """
    Check if RMA log directories and files exist
    """
    rma_log_paths = [
        '/var/log/rma/',
        '/var/log/pxe/',
        '/var/log/syslog',
        '/var/log/messages'
    ]
    
    available_logs = []
    for path in rma_log_paths:
        if os.path.exists(path):
            if os.path.isdir(path):
                # Count files in directory
                try:
                    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
                    available_logs.append({
                        'path': path,
                        'type': 'directory',
                        'file_count': len(files),
                        'exists': True
                    })
                except PermissionError:
                    available_logs.append({
                        'path': path,
                        'type': 'directory',
                        'file_count': 0,
                        'exists': True,
                        'error': 'Permission denied'
                    })
            else:
                # Single file
                try:
                    stat = os.stat(path)
                    available_logs.append({
                        'path': path,
                        'type': 'file',
                        'size': stat.st_size,
                        'exists': True
                    })
                except PermissionError:
                    available_logs.append({
                        'path': path,
                        'type': 'file',
                        'size': 0,
                        'exists': True,
                        'error': 'Permission denied'
                    })
        else:
            available_logs.append({
                'path': path,
                'type': 'unknown',
                'exists': False
            })
    
    return available_logs

def get_recent_rma_logs():
    """
    Get recent RMA-related log entries
    """
    recent_logs = []
    
    try:
        # Try to get recent RMA-related entries from syslog
        import subprocess
        cmd = "grep -i 'rma\\|pxe' /var/log/syslog 2>/dev/null | tail -20"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split('\n')
            for line in lines[-10:]:  # Last 10 entries
                recent_logs.append(line.strip())
        else:
            recent_logs.append("No recent RMA logs found in syslog")
            
    except Exception as e:
        logger.error(f"Error getting recent RMA logs: {e}")
        recent_logs.append(f"Error reading logs: {str(e)}")
    
    return recent_logs
