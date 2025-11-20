from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
import asyncio
import subprocess
from ..form import IpmiForm, FirmwareUploadForm, UniquePasswordForm
import logging
from .unique_password import handle_unique_password_request
from .firmware_update import perform_sequential_updates, system_reset_sync, determine_firmware_type
import json
import os
import uuid
import threading
import redis
import time
try:
    from .. import local_config
except ImportError:
    local_config = None

logger = logging.getLogger(__name__)
redis_client = redis.StrictRedis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)

def cmdline(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode('utf-8').strip()
        return output
    except subprocess.CalledProcessError as e:
        return e.output.decode('utf-8').strip() if e.output else f"Command failed with return code {e.returncode}"

async def run_ipmitool(ip,user,pwd,command):
    cmd_1 = f"ipmitool -I lanplus -C 3 -H {ip} -U {user} -P {pwd} {command}"
    cmd_2 = f"ipmitool -H {ip} -U {user} -P {pwd} {command}"
    
    output = await asyncio.to_thread(cmdline, cmd_1)

    if "Unable to establish IPMI v2" in output:
        output = await asyncio.to_thread(cmdline, cmd_2)
    return ip, output

async def run_all_ipmitool(bmc_ip,user,pwd,command):
    tasks=[run_ipmitool(x,user,pwd[i],command) for i,x in enumerate(bmc_ip)]
    return await asyncio.gather(*tasks)

def run_firmware_update_sequence(sequence_id, bmc_ip, credentials, firmware_files):
    """Wrapper function to run sequential updates and handle final reset."""
    try:
        perform_sequential_updates(sequence_id, bmc_ip, credentials, firmware_files)

        # After updates, check if a reset is needed
        status_raw = redis_client.get(f"firmware_sequence:{sequence_id}")
        if status_raw:
            sequence_status = json.loads(status_raw)
            # Only reset if the flag is set and no errors have occurred
            if sequence_status.get('needs_reset') and 'error' not in sequence_status:
                # Update overall status to inform the user about the incoming reset
                sequence_status['overall_status'] = "Updates complete, initiating system reset..."
                redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(sequence_status), ex=3600)
                
                # Wait a moment for the status to be picked up by the frontend
                time.sleep(3) 

                system_reset_sync(bmc_ip, credentials)

    except Exception as e:
        logger.error(f"Error in firmware update thread for sequence {sequence_id}: {e}")
        # Attempt to retrieve current status to append the error
        try:
            status_raw = redis_client.get(f"firmware_sequence:{sequence_id}")
            if status_raw:
                error_status = json.loads(status_raw)
                error_status['error'] = str(e)
                redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(error_status), ex=3600)
        except Exception as redis_e:
            logger.error(f"Could not update Redis with final error state: {redis_e}")


@login_required
@permission_required('pxe.can_use_tools', raise_exception=True)
def ipmitool(request):
    result = {}
    task_id = None
    
    # Check for RMA configuration
    try:
        is_rma = getattr(local_config, 'RMA', False)
    except NameError:
        is_rma = False
        
    # Initialize forms based on operation type
    if request.method == "POST":
        operation_type = request.POST.get('operation_type')
        
        if operation_type == 'unique_password':
            ipmi_form = IpmiForm(rma=is_rma, user=request.user)
            firmware_form = FirmwareUploadForm(rma=is_rma, user=request.user)
            unique_password_form = UniquePasswordForm(request.POST)
        elif operation_type == 'firmware':
            ipmi_form = IpmiForm(rma=is_rma, user=request.user)
            firmware_form = FirmwareUploadForm(request.POST, request.FILES, rma=is_rma, user=request.user)
            unique_password_form = UniquePasswordForm()
        else:
            # Default to IPMI form (operation_type is None or 'ipmi')
            ipmi_form = IpmiForm(request.POST, rma=is_rma, user=request.user)
            firmware_form = FirmwareUploadForm(rma=is_rma, user=request.user)
            unique_password_form = UniquePasswordForm()
    else:
        # GET request - initialize empty forms
        ipmi_form = IpmiForm(rma=is_rma, user=request.user)
        firmware_form = FirmwareUploadForm(rma=is_rma, user=request.user)
        unique_password_form = UniquePasswordForm()
    
    if request.method == "POST":
        operation_type = request.POST.get('operation_type')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if operation_type == 'unique_password':
            # Handle unique password lookup using the new module
            response = handle_unique_password_request(request)
            if is_ajax:
                return response
            result['password_result'] = response.content

        elif operation_type == 'firmware' and firmware_form.is_valid():
            try:
                bmc_ip = firmware_form.cleaned_data['bmc_ip']
                # Handle custom IP in RMA mode
                if bmc_ip == '__custom__':
                    bmc_ip = firmware_form.cleaned_data.get('bmc_ip_custom', '').strip()
                    if not bmc_ip:
                        raise ValueError('Custom BMC IP is required when "Custom IP..." is selected')
                user = firmware_form.cleaned_data.get('user', 'ADMIN')
                pwd = firmware_form.cleaned_data.get('pwd', '')
                uploaded_files = firmware_form.cleaned_data['firmware_file']

                os.makedirs('/tmp/firmware', exist_ok=True)
                
                firmware_files = []
                for firmware_file in uploaded_files:
                    unique_filename = f"{uuid.uuid4()}_{firmware_file.name}"
                    temp_file_path = os.path.join('/tmp/firmware', unique_filename)
                    with open(temp_file_path, 'wb+') as f:
                        for chunk in firmware_file.chunks():
                            f.write(chunk)
                    firmware_files.append((firmware_file.name, temp_file_path))
                
                credentials = {'username': user, 'password': pwd}
                sequence_id = str(uuid.uuid4())

                # Create initial status in Redis immediately to prevent race condition
                initial_status = {
                    'needs_reset': False,
                    'overall_status': '',
                    'files': {
                        os.path.basename(file_path): {
                            'original_name': original_name,
                            'status': 'Pending',
                            'progress': 0,
                            'type': determine_firmware_type(original_name)
                        } for original_name, file_path in firmware_files
                    }
                }
                redis_client.set(f"firmware_sequence:{sequence_id}", json.dumps(initial_status), ex=3600)

                # Start the update process in a background thread
                thread = threading.Thread(
                    target=run_firmware_update_sequence,
                    args=(sequence_id, bmc_ip, credentials, firmware_files)
                )
                thread.daemon = True
                thread.start()
                
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'sequence_id': sequence_id,
                        'bmc_ip': bmc_ip,
                        'user': user,
                        'pwd': pwd,
                    })
                else:
                    result['upload_result'] = {'sequence_id': sequence_id}
                    
            except Exception as e:
                logger.error(f"Error in firmware update: {str(e)}")
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'error': str(e)
                    })
                else:
                    result['error'] = str(e)

        else:
            # Handle regular IPMI commands (default case, operation_type == 'ipmi', or None)
            if ipmi_form.is_valid():
                bmc_ip = []
                bmc_ip_raw = ipmi_form.cleaned_data['bmc_ip']
                # Handle custom IP in RMA mode
                if bmc_ip_raw == '__custom__':
                    bmc_ip_custom = ipmi_form.cleaned_data.get('bmc_ip_custom', '').strip()
                    if not bmc_ip_custom:
                        result['error'] = 'Custom BMC IP is required when "Custom IP..." is selected'
                    else:
                        bmc_ip = [bmc_ip_custom]
                else:
                    # Check if bmc_ip is a list (from MultipleChoiceField/textarea split) or single string
                    if isinstance(bmc_ip_raw, list):
                        bmc_ip = [x.strip() for x in bmc_ip_raw if x.strip()]
                    else:
                         # Handle both textarea (newline separated) and Select (single value)
                        bmc_ip = [x.strip() for x in bmc_ip_raw.split('\n') if x.strip()]
                
                # Only proceed if we have valid BMC IP(s) and no error
                if 'error' not in result and bmc_ip:
                    command = ipmi_form.cleaned_data['command']
                    user = ipmi_form.cleaned_data.get('user', 'ADMIN')
                    
                    pwd_raw = ipmi_form.cleaned_data.get('pwd', '')
                    if isinstance(pwd_raw, list):
                        pwd = [x.strip() for x in pwd_raw if x.strip()]
                    else:
                        pwd = [x.strip() for x in pwd_raw.split('\n')] if pwd_raw else [''] * len(bmc_ip)

                    if len(pwd) == 1 and len(bmc_ip) > 1:
                        pwd = pwd * len(bmc_ip)

                    try:
                        output = asyncio.run(run_all_ipmitool(bmc_ip, user, pwd, command))
                        result = {ip: out for ip, out in output}
                    except Exception as e:
                        logger.error(f"Error running IPMI command: {str(e)}")
                        result['error'] = str(e)

    # Prepare context
    context = {
        'form': ipmi_form,
        'firmware_form': firmware_form,
        'unique_password_form': unique_password_form,
        'result': result,
        'task_id': task_id,
        'is_rma': is_rma,
    }
    
    if is_rma:
        from ..models import RmaTestingDb
        context['golden_entries'] = RmaTestingDb.objects.all().order_by('golden_number')
        context['can_force_unlink'] = request.user.has_perm('pxe.can_force_unlink_golden')
    
    return render(request, 'features/ipmitool.html', context)

def get_firmware_sequence_status(request):
    """API endpoint to get the status of a firmware update sequence."""
    sequence_id = request.GET.get('sequence_id')
    if not sequence_id:
        return JsonResponse({'success': False, 'error': 'sequence_id is required'})

    status_raw = redis_client.get(f"firmware_sequence:{sequence_id}")
    if status_raw:
        status_data = json.loads(status_raw)
        status_data['success'] = True
        return JsonResponse(status_data)
    else:
        return JsonResponse({'success': False, 'error': 'Status not found for the given sequence_id'})