from django.shortcuts import render
from django.http import JsonResponse
from ..form import RmaForm
import subprocess
import re
import logging

logger = logging.getLogger(__name__)

def rma_pxe(request):
    """
    RMA PXE Boot Manager view - handles RMA-specific PXE configuration
    Similar to regular PXE but with RMA form fields
    """
    form = RmaForm()
    result = None
    
    if request.method == 'POST':
        form = RmaForm(request.POST)
        if form.is_valid():
            result = process_rma_pxe_request(form)
    
    return render(request, 'features/rma_pxe.html', {'form': form, 'result': result})

def process_rma_pxe_request(form):
    """
    Process the RMA PXE form submission
    """
    try:
        # Get form data
        base_sn = form.cleaned_data.get('base_sn')
        rma_number = form.cleaned_data.get('rma_number')
        mac_input = form.cleaned_data.get('mac', '')
        image = form.cleaned_data.get('image')
        tests = form.cleaned_data.get('tests')
        remove = form.cleaned_data.get('remove', False)
        check = form.cleaned_data.get('check', False)
        
        # Process MAC addresses
        mac_list = [line.strip() for line in mac_input.splitlines() if line.strip()]
        normalized_macs = []
        
        for mac in mac_list:
            # Normalize MAC address format
            clean_mac = re.sub(r'[:-]', '', mac.upper())
            if len(clean_mac) == 12:
                formatted_mac = ':'.join([clean_mac[i:i+2] for i in range(0, 12, 2)])
                normalized_macs.append(formatted_mac)
        
        result = {}
        
        if check:
            # Check existing PXE entries
            result['check'] = check_rma_pxe_entries(normalized_macs)
        elif remove:
            # Remove PXE entries
            result['remove'] = remove_rma_pxe_entries(normalized_macs)
        else:
            # Add/Update PXE entries
            result['add'] = add_rma_pxe_entries(normalized_macs, image, tests, base_sn, rma_number)
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing RMA PXE request: {e}")
        return {'error': [f"Error processing request: {str(e)}"]}

def check_rma_pxe_entries(mac_list):
    """
    Check if MAC addresses exist in PXE configuration
    """
    results = []
    try:
        for mac in mac_list:
            # Check if MAC exists in PXE config (using example path, adjust as needed)
            cmd = f"grep -i '{mac}' /var/lib/tftpboot/pxelinux.cfg/* 2>/dev/null || echo 'Not found'"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if "Not found" in process.stdout:
                results.append(f"{mac}: Not configured")
            else:
                results.append(f"{mac}: Configured")
                
    except Exception as e:
        logger.error(f"Error checking RMA PXE entries: {e}")
        results.append(f"Error checking entries: {str(e)}")
    
    return results

def remove_rma_pxe_entries(mac_list):
    """
    Remove MAC addresses from PXE configuration
    """
    results = []
    try:
        for mac in mac_list:
            # Remove PXE config file for MAC (adjust path as needed)
            mac_filename = mac.replace(':', '').replace('-', '').lower()
            config_path = f"/var/lib/tftpboot/pxelinux.cfg/01-{mac.replace(':', '-').lower()}"
            
            cmd = f"rm -f {config_path}"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if process.returncode == 0:
                results.append(f"{mac}: Removed successfully")
            else:
                results.append(f"{mac}: Failed to remove - {process.stderr}")
                
    except Exception as e:
        logger.error(f"Error removing RMA PXE entries: {e}")
        results.append(f"Error removing entries: {str(e)}")
    
    return results

def add_rma_pxe_entries(mac_list, image, tests, base_sn, rma_number):
    """
    Add/Update MAC addresses in PXE configuration for RMA
    """
    results = []
    try:
        for mac in mac_list:
            # Create PXE config for RMA testing
            mac_filename = mac.replace(':', '-').lower()
            config_path = f"/var/lib/tftpboot/pxelinux.cfg/01-{mac_filename}"
            
            # Build kernel parameters for RMA
            kernel_params = f"RMA_SN={base_sn} RMA_NUMBER={rma_number} TEST_TYPE={tests}"
            
            # Create PXE config content
            config_content = f"""DEFAULT {image}
LABEL {image}
    KERNEL images/{image}/vmlinuz
    APPEND initrd=images/{image}/initrd.img {kernel_params}
    IPAPPEND 2
"""
            
            # Write config file
            try:
                with open(config_path, 'w') as f:
                    f.write(config_content)
                results.append(f"{mac}: RMA PXE configured successfully")
            except PermissionError:
                # Try with sudo if permission denied
                cmd = f"echo '{config_content}' | sudo tee {config_path} > /dev/null"
                process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                
                if process.returncode == 0:
                    results.append(f"{mac}: RMA PXE configured successfully (with sudo)")
                else:
                    results.append(f"{mac}: Failed to configure - Permission denied")
                    
    except Exception as e:
        logger.error(f"Error adding RMA PXE entries: {e}")
        results.append(f"Error adding entries: {str(e)}")
    
    return results
