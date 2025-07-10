from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import requests
import json
import os
import logging
from requests.auth import HTTPBasicAuth
import time
import redis
from django.conf import settings

# Set up logging
logger = logging.getLogger(__name__)

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

def determine_firmware_type(filename):
    """Determine firmware type from filename"""
    filename = filename.upper()
    if 'BMC' in filename:
        return 'BMC'
    elif 'BIOS' in filename:
        return 'BIOS'
    elif 'CPLD' in filename:
        return 'CPLD'
    elif 'FPGA' in filename:
        return 'FPGA'
    return None

def sort_firmware_files(files):
    """Sort firmware files in correct update order: BMC, BIOS, CPLD, FPGA"""
    order = {'BMC': 0, 'BIOS': 1, 'CPLD': 2, 'FPGA': 3}
    def get_order(file_tuple):
        firmware_type = determine_firmware_type(file_tuple[0])
        # Always return an integer - 999 for unknown types
        return order[firmware_type] if firmware_type in order else 999
    return sorted(files, key=get_order)

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

def perform_sequential_updates(sequence_id, ip_address, credentials, firmware_files):
    """Perform firmware updates in sequence and update status in Redis."""
    redis_client = redis.StrictRedis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)
    
    # The initial status is now set in the main view. This function just updates it.
    
    # Sort files
    sorted_files = sort_firmware_files(firmware_files)
    
    needs_reset = False
    
    for original_name, file_path in sorted_files:
        firmware_type = determine_firmware_type(original_name)
        if not firmware_type:
            logger.warning(f"Could not determine firmware type for {original_name}, skipping.")
            continue

        try:
            # Update file status to 'Updating'
            current_status = json.loads(redis_client.get(f"firmware_sequence:{sequence_id}"))
            current_status['files'][os.path.basename(file_path)]['status'] = 'Updating'
            redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(current_status), ex=3600)

            # Start firmware update
            update_result = perform_firmware_update(ip_address, credentials, firmware_type, file_path)
            
            task_id = update_result.get('Id')
            if not task_id:
                raise ValueError("Redfish task ID not found in response.")

            # Poll for task completion
            while True:
                status_result = firmware_status(ip_address, credentials, task_id)
                if not status_result['success']:
                    raise ValueError(f"Failed to get task status: {status_result.get('error')}")

                task_data = status_result['data']
                progress = task_data.get('PercentComplete', 0)
                task_state = task_data.get('TaskState')

                # Update progress in Redis
                current_status = json.loads(redis_client.get(f"firmware_sequence:{sequence_id}"))
                current_status['files'][os.path.basename(file_path)]['progress'] = progress
                redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(current_status), ex=3600)

                if task_state == 'Completed':
                    break
                elif task_state in ['Exception', 'Killed', 'Cancelled']:
                    error_message = task_data.get('Messages', [{}])[0].get('Message', f'Task failed with state: {task_state}')
                    raise ValueError(error_message)

                time.sleep(5) # Poll every 5 seconds

            # Update file status to 'Completed'
            current_status = json.loads(redis_client.get(f"firmware_sequence:{sequence_id}"))
            current_status['files'][os.path.basename(file_path)]['status'] = 'Completed'
            current_status['files'][os.path.basename(file_path)]['progress'] = 100
            redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(current_status), ex=3600)

            if firmware_type in ['BIOS', 'CPLD', 'FPGA']:
                needs_reset = True

            # Wait for 3 minutes after BMC update and check reachability
            if firmware_type == 'BMC':
                current_status = json.loads(redis_client.get(f"firmware_sequence:{sequence_id}"))
                current_status['files'][os.path.basename(file_path)]['status'] = 'BMC Rebooting (3 min wait)'
                redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(current_status), ex=3600)
                time.sleep(180)

                # Check if BMC is back online by testing a known Redfish endpoint
                logger.info(f"Checking if BMC {ip_address} is back online after update...")
                redfish_base_url = f"https://{ip_address}/redfish/v1/"
                is_reachable = test_endpoint_exists(redfish_base_url, credentials)
                
                current_status = json.loads(redis_client.get(f"firmware_sequence:{sequence_id}"))
                if is_reachable:
                    logger.info(f"BMC {ip_address} is reachable after update.")
                    current_status['files'][os.path.basename(file_path)]['status'] = 'Completed'
                else:
                    logger.error(f"BMC {ip_address} is unreachable after update.")
                    error_msg = f"BMC {ip_address} did not come back online after 3 minutes."
                    current_status['files'][os.path.basename(file_path)]['status'] = 'Failed (BMC Unreachable)'
                    current_status['error'] = error_msg
                    redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(current_status), ex=3600)
                    raise ValueError(error_msg)
                
                redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(current_status), ex=3600)


        except Exception as e:
            logger.error(f"Error updating {firmware_type} from {original_name}: {e}")
            # Update status for the failed file
            current_status = json.loads(redis_client.get(f"firmware_sequence:{sequence_id}"))
            current_status['files'][os.path.basename(file_path)]['status'] = 'Failed'
            current_status['error'] = str(e)
            redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(current_status), ex=3600)
            return # Stop the sequence on failure

        finally:
            # Clean up temp file
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning(f"Could not remove temp file {file_path}: {e}")
    
    # Mark the sequence as needing a reset if applicable
    if needs_reset:
        final_status = json.loads(redis_client.get(f"firmware_sequence:{sequence_id}"))
        final_status['needs_reset'] = True
        redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(final_status), ex=3600)
        
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
        
        result = system_reset_sync(bmc_ip, {'username': username, 'password': password}, reset_type)
        return JsonResponse(result)
            
    except Exception as e:
        logger.error(f"Error during system reset: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }) 

def system_reset_sync(bmc_ip, credentials, reset_type='ForceRestart'):
    """Synchronous function to perform system reset"""
    url = f"https://{bmc_ip}/redfish/v1/Systems/1/Actions/ComputerSystem.Reset"
    reset_data = {"ResetType": reset_type}
    
    try:
        response = requests.post(
            url,
            json=reset_data,
            auth=(credentials['username'], credentials['password']),
            verify=False,
            timeout=30
        )
        
        if response.status_code in [200, 202, 204]:
            return {
                'success': True,
                'message': 'System reset initiated successfully'
            }
        else:
            return {
                'success': False,
                'error': f"System reset failed with status {response.status_code}. Response: {response.text}"
            }
            
    except Exception as e:
        logger.error(f"Error during system_reset_sync: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def get_firmware_info(bmc_ip, bmc_user, bmc_password):
    """Get firmware information from BMC via Redfish"""
    try:
        fw_info = {}
        fw_base_url = f"https://{bmc_ip}/redfish/v1/UpdateService/FirmwareInventory"
        
        # Get firmware inventory list
        fw_response = requests.get(
            fw_base_url, 
            auth=HTTPBasicAuth(bmc_user, bmc_password), 
            verify=False,
            timeout=30
        ).json()
        
        # Get details for each firmware component
        for member in fw_response.get("Members", []):
            fw_url = f"https://{bmc_ip}{member['@odata.id']}"
            fw_resp = requests.get(
                fw_url, 
                auth=HTTPBasicAuth(bmc_user, bmc_password), 
                verify=False,
                timeout=30
            )
            fw_data = fw_resp.json()   
            name = fw_data.get("Name")
            version = fw_data.get("Version")
            if name and version:
                fw_info[name] = version
                
        return {
            'success': True,
            'firmware_info': fw_info
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error getting firmware info from {bmc_ip}: {str(e)}")
        return {
            'success': False,
            'error': f'Network error: {str(e)}'
        }
    except Exception as e:
        logger.error(f"Error getting firmware info from {bmc_ip}: {str(e)}")
        return {
            'success': False,
            'error': f'Error: {str(e)}'
        }

@login_required
def get_firmware_info_view(request):
    """Django view to get firmware information"""
    if request.method != "POST":
        return JsonResponse({'success': False, 'error': 'Only POST method is allowed'})
        
    try:
        data = json.loads(request.body)
        bmc_ip = data.get('bmc_ip')
        username = data.get('username')
        password = data.get('password')
        
        if not all([bmc_ip, username, password]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters (bmc_ip, username, password)'
            })
        
        result = get_firmware_info(bmc_ip, username, password)
        return JsonResponse(result)
        
    except Exception as e:
        logger.error(f"Error in get_firmware_info_view: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }) 