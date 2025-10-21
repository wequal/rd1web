from django.shortcuts import render
from django.http import JsonResponse
from ..form import RmaForm
from fabric import Connection
from django.contrib.auth.decorators import login_required, permission_required
from ..models import PxeEntry, RmaTestingDb, FirmwareFile
from ..remote_config import remote_dict, async_rma
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

def get_lan_macs(bmc_ip):
    try:
        entry = RmaTestingDb.objects.get(bmc_ip=bmc_ip)
        return [entry.lan0_mac, entry.lan1_mac]
    except RmaTestingDb.DoesNotExist:
        return None, None

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
@permission_required('pxe.can_access_rma_pxe', raise_exception=True)
def get_eco_numbers_api(request, image_type):
    """API endpoint to get available ECO numbers for a specific image type"""
    try:
        # Map image type to product types
        product_types = []
        if image_type == 'ubuntu2204-x86-rma':
            # H100/200 images
            product_types = ['H100_AC', 'H100_LC', 'H200_AC', 'H200_LC']
        elif image_type == 'ubuntu2204-b200-rma':
            # B200 images
            product_types = ['B200_AC', 'B200_LC']
        
        if not product_types:
            return JsonResponse({
                'success': True,
                'eco_numbers': []
            })
        
        # Query distinct ECO numbers for the product types
        eco_numbers = FirmwareFile.objects.filter(
            product_type__in=product_types
        ).values_list('eco_number', flat=True).distinct().order_by('eco_number')
        
        # Convert to list and return as JSON
        eco_list = list(eco_numbers)
        
        # Debug logging - show ECO breakdown by product type
        logger.info(f"ECO API called: image_type={image_type}, product_types={product_types}")
        for pt in product_types:
            pt_ecos = list(FirmwareFile.objects.filter(product_type=pt).values_list('eco_number', flat=True).distinct())
            pt_count = FirmwareFile.objects.filter(product_type=pt).count()
            logger.info(f"  {pt}: {pt_count} files, ECO numbers: {pt_ecos}")
        
        logger.info(f"Combined distinct ECO numbers: {eco_list} (total: {len(eco_list)})")
        
        # Also log all files to see what's in there
        all_files = FirmwareFile.objects.filter(product_type__in=product_types).values('product_type', 'eco_number', 'file_type', 'filename')
        logger.info(f"All firmware files in database for {product_types}:")
        for f in all_files:
            logger.info(f"  - {f['product_type']}/{f['eco_number']}/{f['file_type']}: {f['filename']}")
        
        return JsonResponse({
            'success': True,
            'eco_numbers': eco_list,
            'debug': {
                'product_types': product_types,
                'count': len(eco_list)
            }
        })
    except Exception as e:
        logger.error(f"Error fetching ECO numbers for {image_type}: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@permission_required('pxe.can_access_rma_pxe', raise_exception=True)
def rma_pxe(request):
    result = {}
    if request.method == "POST":
        bound_form = RmaForm(request.POST, user=request.user)
        if bound_form.is_valid():
            base_sn = bound_form.cleaned_data.get('base_sn', '')
            rma_number = bound_form.cleaned_data.get('rma_number', '')
            bmc_ip = bound_form.cleaned_data.get('bmc_ip', '')
            tests = bound_form.cleaned_data.get('tests', [])
            image = bound_form.cleaned_data.get('image', '')
            remove=bound_form.cleaned_data.get('remove', False)
            check=bound_form.cleaned_data.get('check', False)
            fw_update=bound_form.cleaned_data.get('fw_update', False)
            eco_number = bound_form.cleaned_data.get('eco_number', '')
            
            # Debug logging
            logger.info(f"RMA PXE form submitted: base_sn={base_sn}, rma_number={rma_number}, bmc_ip={bmc_ip}, tests={tests}, fw_update={fw_update}, eco_number={eco_number}, remove={remove}, check={check}")
            
            # Build tests parameter including fw_update and eco_number
            tests_list = list(tests) if tests else []
            if fw_update:
                tests_list.append('fw_update')
                if eco_number:
                    tests_list.append(f'eco_number={eco_number}')
            tests_param = " ".join(tests_list) if tests_list else " "
            
            logger.info(f"Built tests_param: {tests_param}")
            
            macs = get_lan_macs(bmc_ip)
            macs= [x.strip().replace(":","").replace("-","").lower() for x in macs if x!='']
            
            logger.info(f"Retrieved MACs: {macs}")

            
        
            if remove:
                result['actions']=[]
                for x in macs:
                    formatted_mac = '-'.join(x[i:i+2] for i in range(0, len(x), 2))
                    deleted,_= PxeEntry.objects.filter(mac=x).delete()
                    if deleted:
                        result['actions'].append(f"Deleted entry for MAC: {x}")
                        # Use sync RMA command with async wrapper
                        success, error = run_rma_command_sync(
                            f"rm -f /var/www/pxe/boot/{formatted_mac}-boot.ipxe"
                        )
                        if not success:
                            result['actions'].append(f"Warning: Failed to delete PXE boot file for {x}: {error}")
                    else:
                        result['actions'].append(f"No entry found to delete for MAC: {x}")
            
            
            elif check:
                result['check']=[]
                for x in macs:
                    try:
                        entry=PxeEntry.objects.get(mac=x)
                        result['check'].append(f"MAC: {entry.mac} | Image: {entry.image} | Parameters: {entry.parameters}")
                    except PxeEntry.DoesNotExist:
                        result['check'].append(f"MAC: {x} not found in database")

            elif base_sn and rma_number and macs:
                logger.info(f"Executing PXE generation for {len(macs)} MACs")
                result['actions']=[]
                for x in macs:
                    # Build parameters dict
                    params = {
                        'base_sn': base_sn, 
                        'rma_number': rma_number, 
                        'tests': " ".join(tests) if tests else " ",
                        'fw_update': fw_update
                    }
                    if eco_number:
                        params['eco_number'] = eco_number
                    
                    obj,created = PxeEntry.objects.update_or_create(
                        mac=x,
                        defaults={'parameters': params,'image':image},
                    )
                    action = "Created" if created else "Updated"
                    result['actions'].append(f"{action} entry for MAC: {x} | Image: {image} | Parameters: base_sn={base_sn}, rma_number={rma_number}, tests={tests_param}")
                    
                    # Use sync RMA command with async wrapper for PXE generation
                    success, error = run_rma_command_sync(
                        f"/srv/share/scripts/rma_pxe_generation {x} {image} {base_sn} {rma_number} {tests_param}",
                        timeout=60  # Longer timeout for script execution
                    )
                    if not success:
                        result['actions'].append(f"Warning: Failed to generate PXE config for {x}: {error}")

            form=RmaForm(user=request.user)
        else:
            # Form validation failed
            logger.error(f"RMA PXE form validation failed: {bound_form.errors}")
            form = RmaForm(user=request.user)
            form._errors = bound_form.errors
            form.data = {}
            form.cleaned_data = {}
    else:
        form=RmaForm(user=request.user)
    
    # Get all golden numbers for status display
    golden_entries = RmaTestingDb.objects.all().order_by('golden_number')
    
    # Check if user has force unlink permission
    can_force_unlink = request.user.has_perm('pxe.can_force_unlink_golden')
    
    return render(request,'features/rma_pxe.html',{
        'form':form,
        'result':result,
        'golden_entries': golden_entries,
        'can_force_unlink': can_force_unlink
    })    