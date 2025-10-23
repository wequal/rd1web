from django.shortcuts import render
from django.http import JsonResponse
from ..form import RmaGeneralForm
from django.contrib.auth.decorators import login_required, permission_required
from ..models import PxeEntry
from ..remote_config import remote_dict, async_rma
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

def run_rma_command_sync(command, timeout=30):
    """Helper function to run RMA commands using async wrapper in sync context"""
    import asyncio
    
    async def _run_async():
        return await async_rma.run_async(command, timeout=timeout, hide=True, warn=True)
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result, success, error = loop.run_until_complete(_run_async())
            if success:
                logger.info(f"RMA command succeeded: {command}")
                return True, None
            else:
                logger.error(f"RMA command failed: {command}, Error: {error}")
                return False, error
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"RMA command exception: {command}, Error: {e}")
        return False, str(e)

@login_required
@permission_required('pxe.can_access_rma_general_test', raise_exception=True)
def rma_general_test(request):
    result = {}
    if request.method == "POST":
        bound_form = RmaGeneralForm(request.POST)
        if bound_form.is_valid():
            system_sn = bound_form.cleaned_data.get('system_sn', '')
            rma_number = bound_form.cleaned_data.get('rma_number', '')
            nic_mac = bound_form.cleaned_data.get('nic_mac', '')  # Already normalized by clean method
            image = bound_form.cleaned_data.get('image', '')
            remove = bound_form.cleaned_data.get('remove', False)
            check = bound_form.cleaned_data.get('check', False)
            
            # Debug logging
            logger.info(f"RMA General TEST form submitted: system_sn={system_sn}, rma_number={rma_number}, nic_mac={nic_mac}, image={image}, remove={remove}, check={check}")
            
            if remove:
                result['actions'] = []
                if nic_mac:
                    formatted_mac = '-'.join(nic_mac[i:i+2] for i in range(0, len(nic_mac), 2))
                    deleted, _ = PxeEntry.objects.filter(mac=nic_mac).delete()
                    if deleted:
                        result['actions'].append(f"Deleted entry for MAC: {nic_mac}")
                        # Delete PXE boot file on remote server
                        success, error = run_rma_command_sync(
                            f"rm -f /var/www/pxe/boot/{formatted_mac}-boot.ipxe"
                        )
                        if not success:
                            result['actions'].append(f"Warning: Failed to delete PXE boot file for {nic_mac}: {error}")
                    else:
                        result['actions'].append(f"No entry found to delete for MAC: {nic_mac}")
                else:
                    result['actions'].append("No MAC address provided")
            
            elif check:
                result['check'] = []
                if nic_mac:
                    try:
                        entry = PxeEntry.objects.get(mac=nic_mac)
                        result['check'].append(f"MAC: {entry.mac} | Image: {entry.image} | Parameters: {entry.parameters}")
                    except PxeEntry.DoesNotExist:
                        result['check'].append(f"MAC: {nic_mac} not found in database")
                else:
                    result['check'].append("No MAC address provided")
            
            elif system_sn and rma_number and nic_mac:
                logger.info(f"Executing PXE generation for MAC: {nic_mac}")
                result['actions'] = []
                
                # Build parameters dict with sys_sn instead of base_sn
                params = {
                    'sys_sn': system_sn,
                    'rma_number': rma_number,
                    'tests': 'default'
                }
                
                obj, created = PxeEntry.objects.update_or_create(
                    mac=nic_mac,
                    defaults={'parameters': params, 'image': image},
                )
                action = "Created" if created else "Updated"
                result['actions'].append(f"{action} entry for MAC: {nic_mac} | Image: {image} | Parameters: sys_sn={system_sn}, rma_number={rma_number}, tests=default")
                
                # Use sync RMA command with async wrapper for PXE generation
                # Note: Pass sys_sn= prefix as part of the command to script
                success, error = run_rma_command_sync(
                    f"/srv/share/scripts/rma_pxe_general_generation {nic_mac} {image} {system_sn} {rma_number} default",
                    timeout=60  # Longer timeout for script execution
                )
                if not success:
                    result['actions'].append(f"Warning: Failed to generate PXE config for {nic_mac}: {error}")
            
            form = RmaGeneralForm()
        else:
            # Form validation failed
            logger.error(f"RMA General TEST form validation failed: {bound_form.errors}")
            form = RmaGeneralForm()
            form._errors = bound_form.errors
            form.data = {}
            form.cleaned_data = {}
    else:
        form = RmaGeneralForm()
    
    return render(request, 'features/rma_general_test.html', {
        'form': form,
        'result': result
    })

