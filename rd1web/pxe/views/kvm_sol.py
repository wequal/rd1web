import json
import subprocess
import requests
import warnings
import os
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from pxe.utils import get_system_sysconfig
import logging
from pxe.sol_session import SOLSession
from django.contrib import messages

# Suppress SSL warnings for BMC connections
from urllib3.exceptions import InsecureRequestWarning
warnings.filterwarnings('ignore', category=InsecureRequestWarning)

# Set up logging
logger = logging.getLogger(__name__)

BASE_DIR = '/srv/log'

# Global dictionary to store active SOL sessions
active_sol_sessions = {}

# Legacy WebSocket SOL handler - no longer used since SOL is handled by consumers.py

def check_ipmitool_available():
    """Check if ipmitool is installed and available"""
    try:
        result = subprocess.run(['which', 'ipmitool'], 
                              capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False

# Legacy xterm SOL functions - removed since SOL now uses WebSocket approach
        logger.error(f"Failed to launch xterm SOL session: {str(e)}")
        raise

@login_required
@require_http_methods(["GET"])
def sol_terminal(request, folder_name):
    """Render SOL terminal page for WebSocket-based SOL sessions"""
    try:
        logger.info(f"SOL terminal page request for folder: {folder_name}")
        
        # Get BMC IP for display purposes
        sysconfig = get_system_sysconfig(folder_name)
        bmc_ip = 'Unknown'
        if sysconfig and 'bmc_ip' in sysconfig:
            bmc_ip = sysconfig['bmc_ip']
        
        # Construct WebSocket URL
        # Use request.is_secure() to determine ws:// or wss://
        ws_scheme = 'wss' if request.is_secure() else 'ws'
        ws_url = f"{ws_scheme}://{request.get_host()}/ws/sol/{folder_name}/"
        
        context = {
            'folder_name': folder_name,
            'system_name': folder_name, # Use folder_name as system_name
            'bmc_ip': bmc_ip,
            'page_title': f'SOL Terminal - {folder_name}',
            'websocket_url': ws_url,
        }
        
        return render(request, 'sol_terminal.html', context)
        
    except Exception as e:
        logger.exception(f"Error rendering SOL terminal for {folder_name}")
        messages.error(request, f'Error loading SOL terminal: {str(e)}')
        return redirect('index')

@login_required
@require_http_methods(["GET"])
def kvm_viewer(request, folder_name):
    """Get KVM URL and redirect directly to BMC iKVM interface"""
    try:
        logger.info(f"KVM viewer request for folder: {folder_name}")
        
        # Get system configuration
        sysconfig = get_system_sysconfig(folder_name)
        if not sysconfig or 'bmc_ip' not in sysconfig:
            logger.error(f"BMC IP not found in sysconfig for {folder_name}")
            messages.error(request, 'BMC IP not found in system configuration')
            return redirect('index')
        
        bmc_ip = sysconfig['bmc_ip']
        bmc_user = sysconfig.get('bmc_user', 'ADMIN')
        bmc_pwd = sysconfig.get('bmc_unique_pwd', 'ADMIN')
        
        # Get KVM URL using Redfish API
        try:
            redfish_url = f"https://{bmc_ip}/redfish/v1/Managers/1/Oem/Supermicro/IKVM"
            response = requests.get(
                redfish_url,
                auth=(bmc_user, bmc_pwd),
                verify=False,
                timeout=10
            )
            
            if response.status_code == 200:
                ikvm_data = response.json()
                ikvm_uri = ikvm_data.get('URI', '')
                if ikvm_uri:
                    full_kvm_url = f"https://{bmc_ip}{ikvm_uri}"
                    logger.info(f"KVM viewer loaded for {folder_name}: {full_kvm_url}")
                    return redirect(full_kvm_url)
                    
        except Exception as e:
            logger.error(f"Error getting KVM URL: {str(e)}")
        
        # Fallback to direct BMC access
        fallback_url = f"https://{bmc_ip}"
        logger.info(f"Using fallback BMC URL for {folder_name}: {fallback_url}")
        return redirect(fallback_url)
        
    except Exception as e:
        logger.exception(f"Error in KVM viewer for {folder_name}")
        messages.error(request, f'Error accessing KVM: {str(e)}')
        return redirect('index')

@login_required
@require_http_methods(["GET"])
def get_kvm_url(request, folder_name):
    """Get KVM URL using Redfish API"""
    try:
        logger.info(f"KVM request for folder: {folder_name}")
        
        sysconfig = get_system_sysconfig(folder_name)
        if not sysconfig or 'bmc_ip' not in sysconfig:
            logger.error(f"BMC IP not found in sysconfig for {folder_name}")
            return JsonResponse({
                'success': False,
                'error': 'BMC IP not found in sysconfig',
                'error_type': 'config_error'
            })
        
        bmc_ip = sysconfig['bmc_ip']
        bmc_user = sysconfig.get('bmc_user', 'ADMIN')
        bmc_pwd = sysconfig.get('bmc_unique_pwd', 'ADMIN')
        
        logger.info(f"Attempting KVM connection to BMC: {bmc_ip}")
        
        # Make Redfish API call to get IKVM URL
        redfish_url = f"https://{bmc_ip}/redfish/v1/Managers/1/Oem/Supermicro/IKVM"
        
        try:
            # Disable SSL verification for BMC connections
            response = requests.get(
                redfish_url,
                auth=(bmc_user, bmc_pwd),
                verify=False,
                timeout=10
            )
            
            logger.info(f"Redfish API response status: {response.status_code}")
            
            if response.status_code == 200:
                ikvm_data = response.json()
                logger.info(f"IKVM response data: {ikvm_data}")
                
                # Extract the URI from the response (note: field is "URI" not "URL")
                ikvm_url = ikvm_data.get('URI', '')
                if ikvm_url:
                    full_kvm_url = f"https://{bmc_ip}{ikvm_url}"
                    logger.info(f"Generated KVM URL: {full_kvm_url}")
                    return JsonResponse({
                        'success': True,
                        'kvm_url': full_kvm_url,
                        'bmc_ip': bmc_ip
                    })
                else:
                    logger.error("KVM URI not found in Redfish response")
                    return JsonResponse({
                        'success': False,
                        'error': 'KVM URI not found in response',
                        'error_type': 'redfish_error'
                    })
            else:
                logger.error(f"Redfish API failed: {response.status_code} - {response.text}")
                return JsonResponse({
                    'success': False,
                    'error': f'Redfish API call failed with status {response.status_code}',
                    'details': response.text[:200],  # Limit error message length
                    'error_type': 'redfish_api_error'
                })
                
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to BMC: {bmc_ip}")
            return JsonResponse({
                'success': False,
                'error': f'Timeout connecting to BMC {bmc_ip}. BMC may be unreachable.',
                'error_type': 'timeout_error'
            })
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error to BMC: {bmc_ip}")
            return JsonResponse({
                'success': False,
                'error': f'Cannot connect to BMC {bmc_ip}. Check network connectivity.',
                'error_type': 'connection_error'
            })
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error to BMC {bmc_ip}: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to connect to BMC: {str(e)}',
                'error_type': 'request_error'
            })
            
    except Exception as e:
        logger.exception(f"Unexpected error in get_kvm_url for {folder_name}")
        return JsonResponse({
            'success': False,
            'error': f'Internal error: {str(e)}',
            'error_type': 'internal_error'
        })

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def start_sol_session(request, folder_name):
    """Start SOL session - now returns URL to SOL terminal page"""
    try:
        logger.info(f"SOL request for folder: {folder_name}")
        
        # Check if ipmitool is available
        if not check_ipmitool_available():
            logger.error("ipmitool not found on system")
            return JsonResponse({
                'success': False,
                'error': 'ipmitool is not installed or not available on this system',
                'error_type': 'dependency_error'
            })
        
        sysconfig = get_system_sysconfig(folder_name)
        if not sysconfig or 'bmc_ip' not in sysconfig:
            logger.error(f"BMC IP not found in sysconfig for {folder_name}")
            return JsonResponse({
                'success': False,
                'error': 'BMC IP not found in sysconfig',
                'error_type': 'config_error'
            })
        
        bmc_ip = sysconfig['bmc_ip']
        bmc_user = sysconfig.get('bmc_user', 'ADMIN')
        
        # Generate URL for SOL terminal page
        sol_terminal_url = reverse('sol_terminal', kwargs={'folder_name': folder_name})
        
        response_data = {
            'success': True,
            'sol_terminal_url': sol_terminal_url,
            'bmc_ip': bmc_ip,
            'bmc_user': bmc_user,
            'folder_name': folder_name,
            'message': 'SOL terminal URL generated successfully'
        }
        
        logger.info(f"SOL terminal URL generated for {folder_name}: {sol_terminal_url}")
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.exception(f"Unexpected error in start_sol_session for {folder_name}")
        return JsonResponse({
            'success': False,
            'error': f'Internal error: {str(e)}',
            'error_type': 'internal_error'
        })

@login_required
@require_http_methods(["GET"])
def get_system_network_info(request, folder_name):
    """Get system network information (BMC IP, LAN IP)"""
    try:
        logger.info(f"Network info request for folder: {folder_name}")
        
        sysconfig = get_system_sysconfig(folder_name)
        if not sysconfig:
            logger.error(f"Sysconfig not found for {folder_name}")
            return JsonResponse({
                'success': False,
                'error': 'Sysconfig not found',
                'error_type': 'config_error'
            })
        
        response_data = {
            'success': True,
            'bmc_ip': sysconfig.get('bmc_ip', 'N/A'),
            'lan_ip': sysconfig.get('bootip', 'N/A'),
            'bmc_user': sysconfig.get('bmc_user', 'N/A')
        }
        
        logger.info(f"Network info retrieved for {folder_name}: {response_data}")
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.exception(f"Unexpected error in get_system_network_info for {folder_name}")
        return JsonResponse({
            'success': False,
            'error': f'Internal error: {str(e)}',
            'error_type': 'internal_error'
        })

@login_required
@require_http_methods(["GET"])
def debug_system_info(request, folder_name):
    """Debug endpoint to check system configuration and dependencies"""
    try:
        debug_info = {
            'folder_name': folder_name,
            'base_dir': BASE_DIR,
            'system_checks': {}
        }
        
        # Check if log directory exists
        log_dir = os.path.join(BASE_DIR, folder_name)
        debug_info['log_dir'] = log_dir
        debug_info['system_checks']['log_dir_exists'] = os.path.exists(log_dir)
        
        if os.path.exists(log_dir):
            debug_info['system_checks']['log_dir_contents'] = os.listdir(log_dir)
        
        # Check sysconfig
        sysconfig_path = os.path.join(log_dir, 'sysconfig')
        debug_info['sysconfig_path'] = sysconfig_path
        debug_info['system_checks']['sysconfig_exists'] = os.path.exists(sysconfig_path)
        
        if os.path.exists(sysconfig_path):
            sysconfig_content = get_system_sysconfig(folder_name)
            if sysconfig_content:
                sysconfig = sysconfig_content
                debug_info['sysconfig'] = sysconfig
                debug_info['system_checks']['has_bmc_ip'] = 'bmc_ip' in sysconfig
            else:
                debug_info['system_checks']['sysconfig_readable'] = False
        
        # Check ipmitool
        debug_info['system_checks']['ipmitool_available'] = check_ipmitool_available()
        
        # Check active SOL sessions
        debug_info['active_sol_sessions'] = len(active_sol_sessions)
        
        logger.info(f"Debug info for {folder_name}: {debug_info}")
        return JsonResponse(debug_info)
        
    except Exception as e:
        logger.exception(f"Error in debug_system_info for {folder_name}")
        return JsonResponse({
            'success': False,
            'error': f'Debug error: {str(e)}',
            'error_type': 'internal_error'
        }) 