from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import asyncio
import subprocess
from ..form import IpmiForm, FirmwareUploadForm, UniquePasswordForm
import logging
from .unique_password import handle_unique_password_request

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
    ipmi_form = IpmiForm(request.POST or None)
    firmware_form = FirmwareUploadForm(request.POST or None, request.FILES or None)
    unique_password_form = UniquePasswordForm(request.POST or None)
    task_id = None
    
    if request.method == "POST":
        operation_type = request.POST.get('operation_type')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if operation_type == 'unique_password':
            # Handle unique password lookup using the new module
            response = handle_unique_password_request(request)
            if is_ajax:
                return response
            result['password_result'] = response.content

        elif operation_type == 'ipmi_command' and ipmi_form.is_valid():
            bmc_ip = [x.strip() for x in ipmi_form.cleaned_data['bmc_ip'].split('\n') if x.strip()]
            command = ipmi_form.cleaned_data['command']
            user = ipmi_form.cleaned_data.get('user', 'ADMIN')
            pwd = [x.strip() for x in ipmi_form.cleaned_data.get('pwd', '').split('\n')] if ipmi_form.cleaned_data.get('pwd') else [''] * len(bmc_ip)

            if len(pwd) == 1 and len(bmc_ip) > 1:
                pwd = pwd * len(bmc_ip)

            try:
                output = asyncio.run(run_all_ipmitool(bmc_ip, user, pwd, command))
                result['ipmi_output'] = {ip: out for ip, out in output}
            except Exception as e:
                logger.error(f"Error running IPMI command: {str(e)}")
                result['error'] = str(e)

        elif operation_type == 'firmware_update' and firmware_form.is_valid():
            # Handle firmware update logic here
            pass

    context = {
        'ipmi_form': ipmi_form,
        'firmware_form': firmware_form,
        'unique_password_form': unique_password_form,
        'result': result,
        'task_id': task_id,
    }
    
    return render(request, 'features/ipmitool.html', context)