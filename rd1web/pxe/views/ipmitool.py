from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import asyncio
import subprocess
from ..form import IpmiForm,FirmwareUploadForm
from .firmware_update import perform_firmware_update
import os
import logging
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
    cmd_1 = f"ipmitool -I lanplus -H {ip} -U {user} -P {pwd} {command}"
    cmd_2 = f"ipmitool -H {ip} -U {user} -P {pwd} {command}"

    try:
        output = await asyncio.to_thread(cmdline, cmd_1)
    except Exception as e:
        output = await asyncio.to_thread(cmdline, cmd_2)

    return ip, output

async def run_all_ipmitool(bmc_ip,user,pwd,command):
    tasks=[run_ipmitool(x,user,pwd[i],command) for i,x in enumerate(bmc_ip)]
    return await asyncio.gather(*tasks)





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