import json
import subprocess
import requests
import warnings
import asyncio
import websockets
import threading
import time
import pty
import os
import select
import termios
import struct
import fcntl
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from pxe.utils import get_system_sysconfig
import logging
from pxe.sol_session import SOLSession

# Suppress SSL warnings for BMC connections
from urllib3.exceptions import InsecureRequestWarning
warnings.filterwarnings('ignore', category=InsecureRequestWarning)

# Set up logging
logger = logging.getLogger(__name__)

BASE_DIR = '/srv/log'

# Global dictionary to store active SOL sessions
active_sol_sessions = {}

async def handle_websocket_sol(websocket, path):
    """Handle WebSocket connections for SOL sessions"""
    try:
        # Extract folder_name from path
        path_parts = path.strip('/').split('/')
        if len(path_parts) < 2 or path_parts[0] != 'sol':
            await websocket.close(code=4000, reason="Invalid path")
            return
        
        folder_name = path_parts[1]
        
        # Get system configuration
        sysconfig = get_system_sysconfig(folder_name)
        if not sysconfig or 'bmc_ip' not in sysconfig:
            await websocket.close(code=4001, reason="BMC IP not found")
            return
        
        bmc_ip = sysconfig['bmc_ip']
        bmc_user = sysconfig.get('bmc_user', 'ADMIN')
        bmc_pwd = sysconfig.get('bmc_unique_pwd', 'ADMIN')
        
        # Create SOL session
        sol_session = SOLSession(folder_name, bmc_ip, bmc_user, bmc_pwd)
        
        if not sol_session.start_sol_process():
            await websocket.close(code=4002, reason="Failed to start SOL process")
            return
        
        # Store the session
        session_id = f"{folder_name}_{id(websocket)}"
        active_sol_sessions[session_id] = sol_session
        sol_session.websocket = websocket
        
        logger.info(f"WebSocket SOL session started for {folder_name}")
        
        # Send initial connection message
        await websocket.send(json.dumps({
            'type': 'info',
            'message': f'SOL session connected to {bmc_ip}\r\nUse ~. to exit SOL session\r\nUse ~? for help\r\n\r\n'
        }))
        
        # Start reading from SOL process in a separate task
        async def read_sol_output():
            while sol_session.running:
                try:
                    output = sol_session.read_from_sol()
                    if output:
                        await websocket.send(json.dumps({
                            'type': 'output',
                            'data': output
                        }))
                    await asyncio.sleep(0.01)  # Small delay to prevent busy waiting
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    logger.error(f"Error reading SOL output: {str(e)}")
                    break
        
        # Start the read task
        read_task = asyncio.create_task(read_sol_output())
        
        # Handle incoming WebSocket messages
        async for message in websocket:
            try:
                data = json.loads(message)
                
                if data.get('type') == 'input':
                    input_data = data.get('data', '')
                    sol_session.write_to_sol(input_data)
                elif data.get('type') == 'resize':
                    # Handle terminal resize
                    rows = data.get('rows', 24)
                    cols = data.get('cols', 80)
                    if sol_session.master_fd:
                        try:
                            # Set terminal size
                            winsize = struct.pack('HHHH', rows, cols, 0, 0)
                            fcntl.ioctl(sol_session.master_fd, termios.TIOCSWINSZ, winsize)
                        except:
                            pass
                            
            except json.JSONDecodeError:
                logger.error("Invalid JSON received from WebSocket")
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {str(e)}")
                break
        
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"WebSocket connection closed for {folder_name}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        # Clean up
        if 'session_id' in locals() and session_id in active_sol_sessions:
            active_sol_sessions[session_id].cleanup()
            del active_sol_sessions[session_id]
        
        if 'read_task' in locals():
            read_task.cancel()

def check_ipmitool_available():
    """Check if ipmitool is installed and available"""
    try:
        result = subprocess.run(['which', 'ipmitool'], 
                              capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False

def check_xterm_available():
    """Check if xterm is installed and available"""
    try:
        result = subprocess.run(['which', 'xterm'], 
                              capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False

def check_display_available():
    """Check if DISPLAY environment variable is set (X11 available)"""
    return 'DISPLAY' in os.environ

def launch_xterm_sol(bmc_ip, bmc_user, bmc_pwd, folder_name):
    """Launch xterm with SOL session"""
    try:
        # Create the ipmitool SOL command
        sol_command = f"ipmitool -I lanplus -H {bmc_ip} -U {bmc_user} -P {bmc_pwd} sol activate"
        
        # Create xterm command with title and execute SOL
        xterm_title = f"SOL Session - {folder_name} ({bmc_ip})"
        xterm_command = [
            'xterm',
            '-title', xterm_title,
            '-geometry', '100x30',
            '-fg', 'green',
            '-bg', 'black',
            '-e', 'bash', '-c', 
            f'echo "Starting SOL session for {folder_name}..."; '
            f'echo "BMC: {bmc_ip}"; '
            f'echo "User: {bmc_user}"; '
            f'echo ""; '
            f'echo "Use ~. to exit SOL session"; '
            f'echo "Use ~? for help"; '
            f'echo ""; '
            f'sleep 2; '
            f'{sol_command}; '
            f'echo ""; '
            f'echo "SOL session ended. Press any key to close..."; '
            f'read -n 1'
        ]
        
        # Launch xterm in background
        process = subprocess.Popen(
            xterm_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid  # Create new process group
        )
        
        logger.info(f"Launched xterm SOL session for {folder_name} with PID: {process.pid}")
        return process.pid
        
    except Exception as e:
        logger.error(f"Failed to launch xterm SOL session: {str(e)}")
        raise

@login_required
@require_http_methods(["GET"])
def sol_terminal(request, folder_name):
    """Render the SOL terminal page"""
    try:
        # Get system configuration for validation
        sysconfig = get_system_sysconfig(folder_name)
        if not sysconfig or 'bmc_ip' not in sysconfig:
            return render(request, 'sol_terminal.html', {
                'error': 'BMC IP not found in system configuration',
                'folder_name': folder_name
            })
        
        # Check if ipmitool is available
        if not check_ipmitool_available():
            return render(request, 'sol_terminal.html', {
                'error': 'ipmitool is not installed or not available on this system',
                'folder_name': folder_name
            })
        
        context = {
            'folder_name': folder_name,
            'bmc_ip': sysconfig['bmc_ip'],
            'bmc_user': sysconfig.get('bmc_user', 'ADMIN'),
            'websocket_url': f"ws://{request.get_host()}/ws/sol/{folder_name}/",
            'system_name': folder_name.upper()
        }
        
        return render(request, 'sol_terminal.html', context)
        
    except Exception as e:
        logger.exception(f"Error rendering SOL terminal for {folder_name}")
        return render(request, 'sol_terminal.html', {
            'error': f'Internal error: {str(e)}',
            'folder_name': folder_name
        })

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