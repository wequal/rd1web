from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required
import asyncio
import subprocess
from ..form import IpmiForm

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

@login_required
def ipmitool(request):
    result = {}
    if request.method == "POST":
        form = IpmiForm(request.POST)
        if form.is_valid():
            bmc_ip = [x.strip() for x in form.cleaned_data['bmc_ip'].splitlines() if x!='']
            command = form.cleaned_data['command']
            user= form.cleaned_data['user']
            pwd= [x.strip() for x in form.cleaned_data['pwd'].splitlines() if x!='']
            results = asyncio.run(run_all_ipmitool(bmc_ip, user, pwd, command))
            result = dict(results)
    else:
        form=IpmiForm()
    return render(request,'features/ipmitool.html',{'form':form,'result':result})