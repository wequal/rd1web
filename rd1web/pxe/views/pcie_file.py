import os
import logging
from django.http import HttpResponse, Http404
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.encoding import smart_str

# Set up logging
logger = logging.getLogger(__name__)

BASE_DIR = '/srv/log'

@login_required
@require_http_methods(["GET"])
def serve_pcie_file(request, folder_name, pcie_file):
    """Serve PCIe device files from the pcie folder"""
    try:
        # Construct the file path
        pcie_dir = os.path.join(BASE_DIR, folder_name, 'pcie')
        file_path = os.path.join(pcie_dir, pcie_file)
        
        # Security check: ensure the file is within the pcie directory
        if not os.path.abspath(file_path).startswith(os.path.abspath(pcie_dir)):
            logger.warning(f"Attempted path traversal attack: {file_path}")
            raise Http404("File not found")
        
        # Check if file exists
        if not os.path.isfile(file_path):
            logger.warning(f"PCIe file not found: {file_path}")
            raise Http404("PCIe device file not found")
        
        # Read and serve the file
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            # Set appropriate headers
            response = HttpResponse(content, content_type='text/plain; charset=utf-8')
            response['Content-Disposition'] = f'inline; filename="{smart_str(pcie_file)}"'
            
            logger.info(f"Served PCIe file: {file_path}")
            return response
            
        except Exception as e:
            logger.error(f"Error reading PCIe file {file_path}: {str(e)}")
            raise Http404("Error reading PCIe device file")
            
    except Http404:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error serving PCIe file {folder_name}/{pcie_file}")
        raise Http404("Error accessing PCIe device file") 