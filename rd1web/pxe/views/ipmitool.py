from django.shortcuts import render
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
import asyncio
import subprocess
from ..form import IpmiForm, UniquePasswordForm
import logging
from .unique_password import handle_unique_password_request
try:
    from .. import local_config
except ImportError:
    local_config = None

logger = logging.getLogger(__name__)

def cmdline(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode('utf-8').strip()
        return output
    except subprocess.CalledProcessError as e:
        return e.output.decode('utf-8').strip() if e.output else f"Command failed with return code {e.returncode}"

async def run_ipmitool(ip,user,pwd,command):
    cmd_1 = f"ipmitool -I lanplus -C 3 -H {ip} -U {user} -P {pwd} {command}"
    cmd_2 = f"ipmitool -H {ip} -U {user} -P {pwd} {command}"
    cmd_3 = f"ipmitool -I lanplus -C 17 -H {ip} -U {user} -P {pwd} {command}"
    
    output = await asyncio.to_thread(cmdline, cmd_1)

    if "Unable to establish IPMI v2" in output:
        output = await asyncio.to_thread(cmdline, cmd_2)
    elif "Unable to establish IPMI v1.5" in output:
        output = await asyncio.to_thread(cmdline, cmd_3)
    return ip, output

async def run_all_ipmitool(bmc_ip,user,pwd,command):
    tasks=[run_ipmitool(x,user,pwd[i],command) for i,x in enumerate(bmc_ip)]
    return await asyncio.gather(*tasks)


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
            unique_password_form = UniquePasswordForm(request.POST)
        else:
            # Default to IPMI form (operation_type is None or 'ipmi')
            ipmi_form = IpmiForm(request.POST, rma=is_rma, user=request.user)
            unique_password_form = UniquePasswordForm()
    else:
        # GET request - initialize empty forms
        ipmi_form = IpmiForm(rma=is_rma, user=request.user)
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

        else:
            # Handle regular IPMI commands (default case, operation_type == 'ipmi', or None)
            if ipmi_form.is_valid():
                bmc_ip_raw = ipmi_form.cleaned_data['bmc_ip']
                
                # In RMA mode, bmc_ip is a single text input
                # In non-RMA mode, it's a textarea with newline-separated IPs
                if is_rma:
                    bmc_ip = [bmc_ip_raw.strip()] if bmc_ip_raw.strip() else []
                else:
                    # Check if bmc_ip is a list (from MultipleChoiceField/textarea split) or single string
                    if isinstance(bmc_ip_raw, list):
                        bmc_ip = [x.strip() for x in bmc_ip_raw if x.strip()]
                    else:
                         # Handle textarea (newline separated)
                        bmc_ip = [x.strip() for x in bmc_ip_raw.split('\n') if x.strip()]
                
                # Only proceed if we have valid BMC IP(s)
                if bmc_ip:
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
        'unique_password_form': unique_password_form,
        'result': result,
        'task_id': task_id,
        'is_rma': is_rma,
    }
    
    return render(request, 'features/ipmitool.html', context)