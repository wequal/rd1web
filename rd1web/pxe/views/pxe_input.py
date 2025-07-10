from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required
from pxe.form import *
from ..models import PxeEntry
import os
from fabric import Connection
import asyncio

remote_dict = {
    'us_b3': Connection(host="root@172.31.60.129", connect_kwargs={"password": "superrd1"}),
    'us_b1': Connection(host="root@172.31.58.142", connect_kwargs={"password": "superrd1"}),
    'tw': Connection(host="root@10.135.179.104", connect_kwargs={"password": "superrd1"})
}

@login_required
def pxe_input(request):
    result = {}
    if request.method == "POST":
        bound_form = PxeForm(request.POST)
        if bound_form.is_valid():
            # Build parameters from form data
            parameters = bound_form.build_parameters_string()
            mac= [x.strip().replace(":","").replace("-","").lower() for x in bound_form.cleaned_data['mac'].splitlines() if x!='']
            location = bound_form.cleaned_data.get('location', '')
            image = bound_form.cleaned_data.get('image', '')
            remove=bound_form.cleaned_data.get('remove', False)
            check=bound_form.cleaned_data.get('check', False)
            
        
            if remove:
                result['actions']=[]
                for x in mac:
                    formatted_mac = '-'.join(x[i:i+2] for i in range(0, len(x), 2))
                    deleted,_= PxeEntry.objects.filter(mac=x).delete()
                    if deleted:
                        result['actions'].append(f"Deleted entry for MAC: {x}")
                        remote_dict[location].run(f"rm -f /var/www/pxe/boot/{formatted_mac}-boot.ipxe")
                    else:
                        result['actions'].append(f"No entry found to delete for MAC: {x}")
            
            
            elif check:
                result['check']=[]
                for x in mac:
                    try:
                        entry=PxeEntry.objects.get(mac=x)
                        result['check'].append(f"MAC: {entry.mac} | Image: {entry.image} | Parameters: {entry.parameters}")
                    except PxeEntry.DoesNotExist:
                        result['check'].append(f"MAC: {x} not found in database")

            elif parameters and mac:
                result['actions']=[]
                for x in mac:
                    obj,created = PxeEntry.objects.update_or_create(
                        mac=x,
                        defaults={'parameters':parameters,'image':image},
                    )
                    action = "Created" if created else "Updated"
                    result['actions'].append(f"{action} entry for MAC: {x} | Image: {image} | Parameters: {parameters}")
                    remote_dict[location].run(f"/srv/share/scripts/pxe_generation {x} {image} {parameters}")

            form=PxeForm()
        else:
            form = PxeForm()
            form._errors = bound_form.errors
            form.data = {}
            form.cleaned_data = {}
    else:
        form=PxeForm()
    
    
    return render(request,'features/pxe.html',{'form':form,'result':result})