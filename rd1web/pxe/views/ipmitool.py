from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import asyncio
import subprocess
from ..form import IpmiForm,FirmwareUploadForm
import requests
import json
import os
import logging
import time
# Set up logging
logger = logging.getLogger(__name__)

def cmdline(cmd):
    """Execute command line and return output"""
    try:
        output = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
        return output
    except subprocess.CalledProcessError as e:
        return e.output.decode('utf-8').strip() if e.output else f"Command failed with return code {e.returncode}"

async def run_ipmitool(ip,user,pwd,command):
    cmd = f"ipmitool -I lanplus -H {ip} -U {user} -P {pwd} {command}"
    output = await asyncio.to_thread(cmdline, cmd)
    return ip, output

async def run_all_ipmitool(bmc_ip,user,pwd,command):
    tasks=[run_ipmitool(x,user,pwd[i],command) for i,x in enumerate(bmc_ip)]
    return await asyncio.gather(*tasks)

def test_endpoint_exists(url, credentials):
    """Test if a Redfish endpoint exists"""
    try:
        logger.info(f"Testing endpoint: {url}")
        response = requests.get(
            url, 
            auth=(credentials['username'], credentials['password']), 
            verify=False,
            timeout=30
        )
        logger.info(f"Response status code: {response.status_code}")
        if response.status_code != 200:
            logger.info(f"Response content: {response.text[:200]}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error testing endpoint {url}: {str(e)}")
        return False

def discover_cpld_endpoint(ip_address, credentials):
    """Try different CPLD endpoint patterns"""
    base_url = f"https://{ip_address}/redfish/v1/UpdateService/FirmwareInventory/"
    logger.info(f"Discovering CPLD endpoint at {base_url}")
    
    # Try common CPLD endpoint variations
    cpld_endpoints = [
        "Motherboard_CPLD_Misc",
        "CPLD_Motherboard_Misc",
        "Motherboard_CPLD_1", 
        "MainBoard_CPLD",
        "CPLD_Motherboard",
    ]
    
    for endpoint in cpld_endpoints:
        full_url = base_url + endpoint
        try:
            if test_endpoint_exists(full_url, credentials):
                logger.info(f"Found CPLD endpoint: {endpoint} at {ip_address}")
                return f"/redfish/v1/UpdateService/FirmwareInventory/{endpoint}"
        except Exception as e:
            logger.error(f"Error checking CPLD endpoint {endpoint}: {str(e)}")
            continue
    
    logger.warning(f"No CPLD endpoint found at {ip_address}")
    return None

def perform_system_reset(ip_address, credentials, reset_type="ForceRestart"):
    """Perform system reset after firmware update"""
    try:
        url = f"https://{ip_address}/redfish/v1/Systems/1/Actions/ComputerSystem.Reset"
        data = {"ResetType": reset_type}
        
        response = requests.post(
            url,
            json=data,
            auth=(credentials['username'], credentials['password']),
            verify=False,
            timeout=30
        )
        
        if response.status_code in [200, 202, 204]:
            logger.info(f"System reset initiated successfully with type: {reset_type}")
            return True
        else:
            logger.error(f"System reset failed with status {response.status_code}. Response: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error during system reset: {str(e)}")
        return False

def perform_firmware_update(ip_address, credentials, firmware_type, file_path):
    """Convert curl command to requests"""
    
    # Determine target endpoint
    target_map = {
        'BIOS': '/redfish/v1/UpdateService/FirmwareInventory/BIOS',
        'BMC': '/redfish/v1/UpdateService/FirmwareInventory/BMC',
        'CPLD': discover_cpld_endpoint(ip_address, credentials),
        'FPGA': '/redfish/v1/UpdateService/FirmwareInventory/Motherboard_FPGA'
    }
    
    # Validate target endpoint exists
    target_endpoint = target_map.get(firmware_type)
    if not target_endpoint:
        error_msg = f"No endpoint found for firmware type: {firmware_type}"
        if firmware_type == 'CPLD':
            error_msg = "No CPLD endpoint found on BMC. Please verify BMC firmware version and CPLD support."
        logger.error(f"{error_msg} for BMC: {ip_address}")
        raise ValueError(error_msg)
    
    url = f"https://{ip_address}/redfish/v1/UpdateService/upload"
    
    # Prepare multipart form data with firmware-specific parameters
    update_params = {
        "Targets": [target_endpoint],
        "@Redfish.OperationApplyTime": "Immediate"
    }
    
    # Add firmware-specific parameters
    if firmware_type == 'BIOS':
        update_params["Oem"] = {
            "Supermicro": {
                "BIOS": {
                    "PreserveME": False,
                    "PreserveNVRAM": False,
                    "PreserveSMBIOS": False,
                    "BackupBIOS": False
                }
            }
        }
    elif firmware_type == 'BMC':
        update_params["Oem"] = {
            "Supermicro": {
                "BMC": {
                    "PreserveCfg": False,
                    "PreserveSdr": False,
                    "PreserveSsl": False,
                    "BackupBMC": False
                }
            }
        }
    
    logger.info(f"Initiating {firmware_type} update for BMC {ip_address} using endpoint {target_endpoint}")
    logger.debug(f"Update parameters: {json.dumps(update_params, indent=2)}")
    
    with open(file_path, 'rb') as f:
        files = {
            'UpdateParameters': (None, json.dumps(update_params)),
            'UpdateFile': (os.path.basename(file_path), f)
        }
    
        try:
            response = requests.post(
                url,
                files=files,
                auth=(credentials['username'], credentials['password']),
                verify=False,
                timeout=300
            )
            
            # Accept both 200 and 202 as success
            # 200 = Synchronous completion
            # 202 = Accepted for async processing
            if response.status_code not in [200, 202]:
                error_msg = f"Firmware update request failed with status {response.status_code}"
                logger.error(f"{error_msg}. Response: {response.text}")
                raise ValueError(error_msg)
            
            response_data = response.json()
            logger.info(f"Firmware update initiated successfully. Task ID: {response_data.get('Id')}")
            
            # Return immediately with task info and firmware type for frontend handling
            response_data['firmware_type'] = firmware_type
            return response_data
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error during firmware update: {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

def firmware_status(ip_address, credentials, task_id):
    """Get firmware update task status"""
    try:
        url = f"https://{ip_address}/redfish/v1/TaskService/Tasks/{task_id}"
        response = requests.get(
            url, 
            auth=(credentials['username'], credentials['password']),
            verify=False,
            timeout=30
        )
        
        if response.status_code == 200:
            return {
                'success': True,
                'data': response.json()
            }
        else:
            return {
                'success': False,
                'error': f'HTTP error {response.status_code}'
            }
            
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': str(e)
        }

@login_required
def check_firmware_status(request):
    """Endpoint to check firmware update status"""
    if request.method != "POST":
        return JsonResponse({'success': False, 'error': 'Only POST method is allowed'})
        
    try:
        data = json.loads(request.body)
        bmc_ip = data.get('bmc_ip')
        task_id = data.get('task_id')
        username = data.get('username')
        password = data.get('password')
        
        if not all([bmc_ip, task_id, username, password]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters'
            })
            
        credentials = {'username': username, 'password': password}
        status = firmware_status(bmc_ip, credentials, task_id)
        
        if status['success']:
            data = status['data']
            response_data = {
                'success': True,
                'percent_complete': data.get('PercentComplete', 0),
                'task_state': data.get('TaskState'),
                'messages': data.get('Messages', [])
            }
            
            if data.get('TaskState') in ['Exception', 'Killed', 'Cancelled']:
                response_data['error'] = data.get('Messages', [{}])[0].get('Message', 'Unknown error')
                
            return JsonResponse(response_data)
        else:
            return JsonResponse({
                'success': False,
                'error': status['error']
            })
            
    except Exception as e:
        logger.error(f"Error checking firmware status: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def system_reset(request):
    """Endpoint to perform system reset"""
    if request.method != "POST":
        return JsonResponse({'success': False, 'error': 'Only POST method is allowed'})
        
    try:
        request_data = json.loads(request.body)
        bmc_ip = request_data.get('bmc_ip')
        username = request_data.get('username')
        password = request_data.get('password')
        reset_type = request_data.get('reset_type', 'ForceRestart')
        
        if not all([bmc_ip, username, password]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters'
            })
        
        url = f"https://{bmc_ip}/redfish/v1/Systems/1/Actions/ComputerSystem.Reset"
        reset_data = {"ResetType": reset_type}
        
        response = requests.post(
            url,
            json=reset_data,
            auth=(username, password),
            verify=False,
            timeout=30
        )
        
        if response.status_code in [200, 202, 204]:
            return JsonResponse({
                'success': True,
                'message': 'System reset initiated successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': f"System reset failed with status {response.status_code}"
            })
            
    except Exception as e:
        logger.error(f"Error during system reset: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })



@login_required
def ipmitool(request):
    result = {}
    ipmi_form = IpmiForm(request.POST or None)
    firmware_form = FirmwareUploadForm(request.POST or None, request.FILES or None)
    task_id = None
    
    if request.method == "POST":
        operation_type = request.POST.get('operation_type')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if operation_type == 'firmware' and firmware_form.is_valid():
            try:
                bmc_ip = firmware_form.cleaned_data['bmc_ip']
                user = firmware_form.cleaned_data['user']
                pwd = firmware_form.cleaned_data['pwd']
                firmware_type = firmware_form.cleaned_data['firmware_type']
                firmware_file = firmware_form.cleaned_data['firmware_file']
                credentials = {'username': user, 'password': pwd}

                # Create temp directory and save file
                os.makedirs('/tmp/firmware', exist_ok=True)
                firmware_file_path = os.path.join('/tmp/firmware', firmware_file.name)
                
                try:
                    with open(firmware_file_path, 'wb') as f:
                        for chunk in firmware_file.chunks():
                            f.write(chunk)

                    # Perform update
                    upload_result = perform_firmware_update(bmc_ip, credentials, firmware_type, firmware_file_path)
                    task_id = upload_result.get('Id')
                    
                    if is_ajax:
                        return JsonResponse({
                            'success': True,
                            'task_id': task_id,
                            'bmc_ip': bmc_ip,
                            'user': user,
                            'pwd': pwd,
                            'firmware_type': firmware_type,
                            'upload_details': {
                                'id': task_id,
                                'status': upload_result.get('TaskState'),
                                'percent_complete': upload_result.get('PercentComplete', 0),
                                'messages': upload_result.get('Messages', []),
                                'start_time': upload_result.get('StartTime'),
                                'target_firmware': firmware_type,
                                'target_endpoint': upload_result.get('Targets', [])[0] if upload_result.get('Targets') else None,
                                'operation_time': upload_result.get('OperationApplyTime'),
                                'state_flags': {
                                    'is_processing': upload_result.get('TaskState') == 'Running',
                                    'has_errors': upload_result.get('TaskState') in ['Exception', 'Killed', 'Cancelled'],
                                    'is_completed': upload_result.get('TaskState') == 'Completed'
                                },
                                'raw_response': upload_result
                            }
                        })
                    
                    result['upload_result'] = upload_result
                    if not task_id:
                        result['error'] = 'No task ID returned from BMC'
                    
                except Exception as e:
                    logger.error(f"Error during firmware upload: {str(e)}")
                    if is_ajax:
                        return JsonResponse({
                            'success': False,
                            'error': str(e)
                        })
                    result['error'] = str(e)
                
                finally:
                    # Clean up temp file
                    if os.path.exists(firmware_file_path):
                        os.remove(firmware_file_path)
            
            except Exception as e:
                logger.error(f"Error in firmware update process: {str(e)}")
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'error': str(e)
                    })
                result['error'] = str(e)
        
        elif operation_type != 'firmware' and ipmi_form.is_valid():
            try:
                bmc_ip = [x.strip() for x in ipmi_form.cleaned_data['bmc_ip'].splitlines() if x!='']
                command = ipmi_form.cleaned_data['command']
                user = ipmi_form.cleaned_data['user']
                pwd = [x.strip() for x in ipmi_form.cleaned_data['pwd'].splitlines() if x!='']
                results = asyncio.run(run_all_ipmitool(bmc_ip, user, pwd, command))
                result = dict(results)
            except Exception as e:
                logger.error(f"Error executing IPMI command: {str(e)}")
                result['error'] = str(e)

    return render(request, 'features/ipmitool.html', {
        'form': ipmi_form,
        'firmware_form': firmware_form,
        'result': result,
        'task_id': task_id
    })