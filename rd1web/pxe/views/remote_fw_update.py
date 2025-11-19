import json
import logging
import os
import requests
import threading
import time
import redis
from django.conf import settings
from django.http import JsonResponse
import urllib3

# Suppress InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
redis_client = redis.StrictRedis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)

# BKC File Mapping - matches RmaForm image choices from form.py
ECO_BKC_FILE = {
    "ubuntu2204-x86-rma": None,  # H100/200 - uses firmware inventory system, not BKC files
    "ubuntu2204-b200-rma": None,  # B200 - uses firmware inventory system, not BKC files
    "ubuntu2204-mi300x": '/share/mi3xx/AMD_MI300X_01.25.03.12.76.pldm',
    "ubuntu2204-mi325x": '/share/mi3xx/AMD_MI325X_01.25.03.03.76.pldm',
    "ubuntu2204-mi355x": '/share/mi3xx/AMD_MI350_355H_01.25.11.02.76.pldm'
}

# Credentials
BMC_USER = "root"
BMC_PASSWORD = "Golden@1234"

def update_task_status(task_id, status, percent=0, message=""):
    """Update task status in Redis"""
    data = {
        "status": status,
        "percent": percent,
        "message": message
    }
    redis_client.set(f"remote_fw_update:{task_id}", json.dumps(data), ex=3600)

def run_remote_fw_update_task(task_id, bmc_ip, image_key):
    """Background task for remote firmware update"""
    logger.info(f"Starting remote FW update task {task_id} for {bmc_ip} with image {image_key}")
    
    try:
        update_task_status(task_id, "Running", 0, "Checking UBB reachability...")
        
        # Determine BKC file path
        bkc_file_path = ECO_BKC_FILE.get(image_key)
        if bkc_file_path is None:
            # H100/200 and B200 use firmware inventory system, not BKC files
            raise ValueError(f"Remote FW update via BKC file is not supported for image: {image_key}. "
                           f"Please use firmware inventory system for H100/200 and B200 products.")
        if not bkc_file_path:
            raise ValueError(f"No BKC file configured for image: {image_key}")
            
        if not os.path.exists(bkc_file_path):
             raise ValueError(f"BKC file not found at: {bkc_file_path}")

        # Check UBB Reachability logic
        bmc_reset = 0
        ubb_reachable = False
        
        while not ubb_reachable:
            try:
                requests.get(
                    f"https://{bmc_ip}/redfish/v1/Systems/UBB", 
                    verify=False, 
                    auth=(BMC_USER, BMC_PASSWORD),
                    timeout=10
                )
                ubb_reachable = True
            except Exception as e:
                if bmc_reset <= 3:
                    msg = f"Unable to reach UBB, resetting BMC (Attempt {bmc_reset+1}/4)"
                    update_task_status(task_id, "Running", 0, msg)
                    logger.warning(f"{msg} - {str(e)}")
                    
                    cmd = f"ipmitool -H {bmc_ip} -U {BMC_USER} -P {BMC_PASSWORD} mc reset cold"
                    os.system(cmd)
                    
                    update_task_status(task_id, "Running", 0, "Cold reset BMC, waiting for 3 minutes...")
                    time.sleep(180)
                    bmc_reset += 1
                else:
                    raise Exception("Failed to reach UBB after multiple BMC resets")

        # Upload Firmware
        update_task_status(task_id, "Running", 10, "Uploading firmware file (this may take a while)...")
        url = f"https://{bmc_ip}/redfish/v1/UpdateService/upload"
        
        # Prepare files
        try:
            with open(bkc_file_path, "rb") as f:
                files = {
                    "UpdateFile": f,
                    "UpdateParameters": (
                        None,
                        '{"Targets": ["/redfish/v1/UpdateService/FirmwareInventory/bundle_active"], '
                        '"@Redfish.OperationApplyTime": "Immediate"}',
                        "application/json",
                    ),
                }
                
                try:
                    response = requests.post(
                        url,
                        files=files,
                        auth=(BMC_USER, BMC_PASSWORD),
                        verify=False,
                        timeout=600,
                    )
                    # Check for success but don't raise yet if we can recover task ID
                    if response.status_code not in [200, 202]:
                         logger.warning(f"Upload returned status {response.status_code}: {response.text}")
                         
                    task_odata_id = response.json().get("@odata.id")
                except Exception as e:
                    logger.warning(f"Upload response parsing failed or request error: {e}")
                    task_odata_id = None

                if not task_odata_id:
                    # Fallback to find task if direct response failed but task started
                    logger.info("Checking TaskService for ongoing AMD tasks...")
                    try:
                        except_task_resp = requests.get(
                            f"https://{bmc_ip}/redfish/v1/TaskService/Tasks", 
                            auth=(BMC_USER, BMC_PASSWORD), 
                            verify=False,
                            timeout=30
                        ).json()
                        
                        amd_tasks = [m["@odata.id"] for m in except_task_resp.get("Members", []) if "AMD_" in m["@odata.id"]]
                        if amd_tasks:
                             task_odata_id = sorted(amd_tasks)[-1]
                        else:
                            raise Exception("Unable to find ongoing firmware update task.")
                    except Exception as e2:
                        raise Exception(f"Failed to find firmware update task: {e2}")

            # Monitor Task
            task_url = f"https://{bmc_ip}{task_odata_id}"
            monitor = True
            state = "Unknown"
            
            while monitor:
                try:
                    task_resp = requests.get(task_url, auth=(BMC_USER, BMC_PASSWORD), verify=False, timeout=30)
                    task_data = task_resp.json()
                    state = task_data.get("TaskState", "Unknown")
                    percent = task_data.get("PercentComplete", 0)
                    
                    msg = f"TaskState: {state}, PercentComplete: {percent}%"
                    # logger.info(f"Task {task_id}: {msg}")
                    
                    # Map percent to 10-90 range for UI (upload was 0-10)
                    ui_percent = 10 + int(percent * 0.8)
                    update_task_status(task_id, "Running", ui_percent, msg)

                    if state in ["Completed", "Exception", "Killed"]:
                        monitor = False
                    
                    if monitor:
                        time.sleep(20)
                except Exception as e:
                    logger.error(f"Error monitoring task: {e}")
                    time.sleep(20)

            if state == "Completed":
                update_task_status(task_id, "Running", 95, "Firmware update completed. Checking AC cycle support...")
                
                # AC Cycle check
                url = f"https://{bmc_ip}/redfish/v1/Systems/1"
                try:
                    resp = requests.get(url, auth=(BMC_USER, BMC_PASSWORD), verify=False, timeout=60)
                    data = resp.json()
                    reset_info = data.get("Actions", {}).get("#ComputerSystem.Reset", {})
                    allowable_values = reset_info.get("ResetType@Redfish.AllowableValues", [])
                    
                    if "FullPowerCycle" in allowable_values:
                        update_task_status(task_id, "Running", 98, "AC cycle supported. Sending command...")
                        payload = {"ResetType": "FullPowerCycle"}
                        reset_resp = requests.post(
                            url + "/Actions/ComputerSystem.Reset", 
                            json=payload, 
                            auth=(BMC_USER, BMC_PASSWORD), 
                            verify=False, 
                            timeout=60
                        )
                        
                        if reset_resp.status_code in [200, 202, 204]:
                            update_task_status(task_id, "Completed", 100, "AC cycle command accepted. Update Successful.")
                        else:
                            update_task_status(task_id, "Completed", 100, f"Update complete but AC cycle failed: {reset_resp.status_code}")
                    else:
                        # Manual AC cycle required
                        update_task_status(task_id, "Completed", 100, "Update complete. FullPowerCycle not supported. Please manually AC cycle the system.")
                except Exception as e:
                    update_task_status(task_id, "Completed", 100, f"Update complete, but error checking AC cycle: {e}")

            else:
                raise Exception(f"Firmware update failed with state: {state}")

        except Exception as e:
             raise e

    except Exception as e:
        logger.error(f"Remote FW update failed for task {task_id}: {e}")
        update_task_status(task_id, "Failed", 0, f"Error: {str(e)}")


def remote_fw_status(request, task_id):
    """API to get status"""
    raw = redis_client.get(f"remote_fw_update:{task_id}")
    if raw:
        return JsonResponse(json.loads(raw))
    return JsonResponse({"status": "Unknown", "percent": 0, "message": "Task not found"})
