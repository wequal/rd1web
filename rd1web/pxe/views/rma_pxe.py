from django.shortcuts import render
from django.http import JsonResponse
from ..form import RmaForm
import subprocess
import re
from fabric import Connection
from django.contrib.auth.decorators import login_required
from ..models import PxeEntry

remote_dict = {
    'rma': Connection(host="root@172.31.32.24", connect_kwargs={"password": "superrd1"}),

}


@login_required
def rma_pxe(request):
    result = {}
    if request.method == "POST":
        bound_form = RmaForm(request.POST)
        if bound_form.is_valid():
            base_sn = bound_form.cleaned_data.get('base_sn', '')
            rma_number = bound_form.cleaned_data.get('rma_number', '')
            mac= [x.strip().replace(":","").replace("-","").lower() for x in bound_form.cleaned_data['mac'].splitlines() if x!='']
            tests = bound_form.cleaned_data.get('tests', '')
            cooling = bound_form.cleaned_data.get('cooling', '')
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
                        remote_dict['rma'].run(f"rm -f /var/www/pxe/boot/{formatted_mac}-boot.ipxe")
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

            elif base_sn and rma_number and mac:
                result['actions']=[]
                for x in mac:
                    obj,created = PxeEntry.objects.update_or_create(
                        mac=x,
                        defaults={'parameters': {'base_sn': base_sn, 'rma_number': rma_number, 'tests': tests},'image':image},
                    )
                    action = "Created" if created else "Updated"
                    result['actions'].append(f"{action} entry for MAC: {x} | Image: {image} | Parameters: base_sn={base_sn}, rma_number={rma_number}, tests={tests}, cooling={cooling}")
                    remote_dict['rma'].run(f"/srv/share/scripts/rma_pxe_generation {x} {image} {base_sn} {rma_number} {tests} {cooling}")

            form=RmaForm()
        else:
            form = RmaForm()
            form._errors = bound_form.errors
            form.data = {}
            form.cleaned_data = {}
    else:
        form=RmaForm()
    
    
    return render(request,'features/rma_pxe.html',{'form':form,'result':result})    