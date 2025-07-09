from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import asyncio
import subprocess
from ..form import IpmiForm, FirmwareUploadForm, UniquePasswordForm
import logging
from .unique_password import handle_unique_password_request
from .firmware_update import perform_firmware_update
import json
import os

logger = logging.getLogger(__name__)

def cmdline(cmd):
    process = subprocess.Popen(
        args=cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        universal_newlines=True
    )
    return process.communicate()[0]

async def run_ipmitool(ip,user,pwd,command):
    cmd_1 = f"ipmitool -I lanplus -H {ip} -U {user} -P {pwd} {command}"
    cmd_2 = f"ipmitool -H {ip} -U {user} -P {pwd} {command}"

    output = await asyncio.to_thread(cmdline, cmd_1)

    if "Invalid" in output or "Error" in output or "failed" in output.lower():
        output = await asyncio.to_thread(cmdline, cmd_2)
    return ip, output

async def run_all_ipmitool(bmc_ip,user,pwd,command):
    tasks=[run_ipmitool(x,user,pwd[i],command) for i,x in enumerate(bmc_ip)]
    return await asyncio.gather(*tasks)

@login_required
def ipmitool(request):
    result = {}
    task_id = None
    
    # Initialize forms based on operation type
    if request.method == "POST":
        operation_type = request.POST.get('operation_type')
        
        if operation_type == 'unique_password':
            ipmi_form = IpmiForm()
            firmware_form = FirmwareUploadForm()
            unique_password_form = UniquePasswordForm(request.POST)
        elif operation_type == 'firmware':
            ipmi_form = IpmiForm()
            firmware_form = FirmwareUploadForm(request.POST, request.FILES)
            unique_password_form = UniquePasswordForm()
        else:
            # Default to IPMI form (operation_type is None or 'ipmi')
            ipmi_form = IpmiForm(request.POST)
            firmware_form = FirmwareUploadForm()
            unique_password_form = UniquePasswordForm()
    else:
        # GET request - initialize empty forms
        ipmi_form = IpmiForm()
        firmware_form = FirmwareUploadForm()
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
            # Handle firmware update
            try:
                bmc_ip = firmware_form.cleaned_data['bmc_ip']
                user = firmware_form.cleaned_data.get('user', 'ADMIN')
                pwd = firmware_form.cleaned_data.get('pwd', '')
                firmware_type = firmware_form.cleaned_data['firmware_type']
                firmware_file = firmware_form.cleaned_data['firmware_file']
                
                # Save uploaded file temporarily
                temp_file_path = os.path.join('/tmp', firmware_file.name)
                with open(temp_file_path, 'wb') as f:
                    for chunk in firmware_file.chunks():
                        f.write(chunk)
                
                # Perform firmware update
                credentials = {'username': user, 'password': pwd}
                update_result = perform_firmware_update(bmc_ip, credentials, firmware_type, temp_file_path)
                
                # Clean up temp file
                os.remove(temp_file_path)
                
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'task_id': update_result.get('Id'),
                        'bmc_ip': bmc_ip,
                        'user': user,
                        'pwd': pwd,
                        'firmware_type': firmware_type,
                        'upload_details': update_result
                    })
                else:
                    result['upload_result'] = update_result
                    
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
                bmc_ip = [x.strip() for x in ipmi_form.cleaned_data['bmc_ip'].split('\n') if x.strip()]
                command = ipmi_form.cleaned_data['command']
                user = ipmi_form.cleaned_data.get('user', 'ADMIN')
                pwd = [x.strip() for x in ipmi_form.cleaned_data.get('pwd', '').split('\n')] if ipmi_form.cleaned_data.get('pwd') else [''] * len(bmc_ip)

                if len(pwd) == 1 and len(bmc_ip) > 1:
                    pwd = pwd * len(bmc_ip)

                try:
                    output = asyncio.run(run_all_ipmitool(bmc_ip, user, pwd, command))
                    result = {ip: out for ip, out in output}
                except Exception as e:
                    logger.error(f"Error running IPMI command: {str(e)}")
                    result['error'] = str(e)

    context = {
        'form': ipmi_form,
        'firmware_form': firmware_form,
        'unique_password_form': unique_password_form,
        'result': result,
        'task_id': task_id,
    }
    
    return render(request, 'features/ipmitool.html', context)