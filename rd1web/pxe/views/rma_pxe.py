from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from ..form import RmaForm, PcieGpuForm, GbGpuForm
from fabric import Connection
from django.contrib.auth.decorators import login_required, permission_required
from ..models import PxeEntry, RmaTestingDb, RmaGbDb, FirmwareFile
from ..remote_config import remote_dict, async_rma
import asyncio
import json
import ast
import logging
import uuid
import threading
import os
import subprocess
from datetime import datetime
from .remote_fw_update import run_remote_fw_update_task

logger = logging.getLogger(__name__)

# Import configuration from local_config
try:
    from ..local_config import RMA_PXE_GENERATION_SCRIPT, PXE_BOOT_PATH, RMA_BASE_DIR
    logger.info("RMA PXE using configuration from local_config.py")
except ImportError:
    # Fallback to defaults if local_config doesn't exist
    logger.warning("local_config.py not found, using default RMA PXE paths")
    RMA_PXE_GENERATION_SCRIPT = '/srv/share/scripts/rma_pxe_generation'
    PXE_BOOT_PATH = '/var/www/pxe/boot/'
    RMA_BASE_DIR = '/srv/rma'


def get_bmc_password_for_hmc_log(bmc_ip: str, bmc_user: str = "root", operation_type: str = "rma") -> str:
    """
    Get BMC password from RMA DB by BMC IP.
    Raises ValueError if not found or password is empty.
    """
    if operation_type == "gb":
        entry = RmaGbDb.objects.filter(bmc_ip=bmc_ip).first()
        not_found_msg = "RMA GB DB"
    else:
        entry = RmaTestingDb.objects.filter(bmc_ip=bmc_ip).first()
        not_found_msg = "RMA Testing DB"

    if entry is None:
        raise ValueError(
            f"BMC IP {bmc_ip} not found in {not_found_msg}. Please add the entry first."
        )
    if not (entry.bmc_password or "").strip():
        raise ValueError(
            f"BMC IP {bmc_ip} has no password set in {not_found_msg}. Please update the entry."
        )
    return entry.bmc_password.strip()


def collect_hmc_log_to_rma_folder(base_sn: str, rma_number: str, bmc_ip: str, operation_type: str = "gb") -> str:
    """
    Collect HMC event log via SSH to BMC (root user) and save under:
      {RMA_BASE_DIR}/{base_sn}_{rma_number}/HMC_logs/hmc_event_log_{timestamp}.log
    Returns the relative browse path for redirect: "{dir}/HMC_logs"
    """
    dir_name = f"{base_sn}_{rma_number}"
    target_dir = os.path.join(RMA_BASE_DIR, dir_name)
    hmc_dir = os.path.join(target_dir, "HMC_logs")
    os.makedirs(hmc_dir, exist_ok=True)

    bmc_user = "root"
    bmc_password = get_bmc_password_for_hmc_log(bmc_ip=bmc_ip, bmc_user=bmc_user, operation_type=operation_type)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(hmc_dir, f"hmc_event_log_{timestamp}.log")

    remote_url = "http://172.31.13.251/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries"
    cmd = [
        "sshpass", "-p", bmc_password,
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        f"{bmc_user}@{bmc_ip}",
        "curl", "-k", "-X", "GET", remote_url,
    ]

    with open(out_file, "wb") as f:
        completed = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=False, timeout=120)
    if completed.returncode != 0:
        err = completed.stderr.decode(errors="ignore") if isinstance(completed.stderr, (bytes, bytearray)) else str(completed.stderr)
        raise RuntimeError(f"HMC Log collection failed (exit {completed.returncode}): {err}")

    return f"{dir_name}/HMC_logs"

def normalize_mac_for_pxe(mac):
    """Normalize MAC to 12 hex chars (lowercase), or None if invalid/empty."""
    if not mac:
        return None
    normalized = mac.strip().replace(":", "").replace("-", "").lower()
    if len(normalized) != 12:
        return None
    return normalized

def get_lan_macs(bmc_ip):
    try:
        entry = RmaTestingDb.objects.get(bmc_ip=bmc_ip)
        return [entry.lan0_mac, entry.lan1_mac]
    except RmaTestingDb.DoesNotExist:
        return None, None


def get_gb_lan_macs(bmc_ip):
    """GB GPU TEST uses only LAN0 MAC from RmaGbDb."""
    try:
        entry = RmaGbDb.objects.get(bmc_ip=bmc_ip)
        return [entry.lan0_mac]
    except RmaGbDb.DoesNotExist:
        return None

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

def remove_pxe_entries_and_boot_files(macs):
    """
    Remove PXE DB entries and remote iPXE boot files for provided MACs.

    Returns a list of human-readable action/warning strings.
    """
    actions = []

    # Ensure PXE_BOOT_PATH has trailing slash for string concat
    pxe_boot_path = PXE_BOOT_PATH if PXE_BOOT_PATH.endswith("/") else f"{PXE_BOOT_PATH}/"

    for mac in macs or []:
        normalized_mac = normalize_mac_for_pxe(mac)
        if not normalized_mac:
            actions.append(f"Skipped invalid/empty MAC: {mac}")
            continue

        formatted_mac = "-".join(
            normalized_mac[i:i + 2] for i in range(0, len(normalized_mac), 2)
        )

        deleted, _ = PxeEntry.objects.filter(mac=normalized_mac).delete()
        if deleted:
            actions.append(f"Deleted entry for MAC: {normalized_mac}")
            success, error = run_rma_command_sync(
                f"rm -f {pxe_boot_path}{formatted_mac}-boot.ipxe"
            )
            if not success:
                actions.append(
                    f"Warning: Failed to delete PXE boot file for {normalized_mac}: {error}"
                )
        else:
            actions.append(f"No entry found to delete for MAC: {normalized_mac}")

    return actions

@login_required
@permission_required('pxe.can_access_rma_pxe', raise_exception=True)
def get_rma_info_by_bmc(request, bmc_ip):
    """API endpoint to get base_sn and rma_number by BMC IP"""
    try:
        # Get operation_type from query parameter (default to 'rma' for backward compatibility)
        operation_type = request.GET.get('operation_type', 'rma')
        # Map operation_type to form_type
        # - rma -> sxm
        # - pcie -> pcie
        # - gb -> gb
        if operation_type == 'rma':
            expected_form_type = 'sxm'
        elif operation_type == 'gb':
            expected_form_type = 'gb'
        else:
            expected_form_type = 'pcie'
        
        # Step 1: Get RMA entry (db depends on operation_type) and check if it's actively linked
        try:
            if operation_type == 'gb':
                rma_entry = RmaGbDb.objects.get(bmc_ip=bmc_ip)
            else:
                rma_entry = RmaTestingDb.objects.get(bmc_ip=bmc_ip)
            
            # Check if golden is currently linked
            if not rma_entry.linked_user:
                # Not linked to any user - skip auto-fill
                return JsonResponse({
                    'success': True,
                    'base_sn': '',
                    'rma_number': ''
                })
            
            # Check if linked_at timestamp exists
            if not rma_entry.linked_at:
                # No link timestamp - legacy record or unlinked/relinked - skip auto-fill
                return JsonResponse({
                    'success': True,
                    'base_sn': '',
                    'rma_number': ''
                })
            
            if operation_type == 'gb':
                macs = [rma_entry.lan0_mac]
            else:
                macs = [rma_entry.lan0_mac, rma_entry.lan1_mac]
            # Normalize MACs (remove colons/dashes, lowercase)
            macs = [mac.replace(':', '').replace('-', '').lower() for mac in macs if mac]
        except (RmaTestingDb.DoesNotExist, RmaGbDb.DoesNotExist):
            return JsonResponse({
                'success': True,
                'base_sn': '',
                'rma_number': ''
            })
        
        if not macs:
            return JsonResponse({
                'success': True,
                'base_sn': '',
                'rma_number': ''
            })
        
        # Step 2: Query PxeEntry for those MAC addresses created AFTER linked_at
        # This ensures we only auto-fill from PXE entries created while currently linked
        pxe_entries = PxeEntry.objects.filter(
            mac__in=macs,
            updated_at__gte=rma_entry.linked_at
        ).order_by('-updated_at')
        
        # Step 3: Filter by form_type matching the operation_type
        # For backward compatibility: if form_type is missing, treat as 'sxm' for RMA requests
        pxe_entry = None
        for entry in pxe_entries:
            params = entry.parameters
            # Try to parse parameters
            if isinstance(params, dict):
                params_dict = params
            elif isinstance(params, str):
                try:
                    params_dict = ast.literal_eval(params)
                except (ValueError, SyntaxError):
                    try:
                        params_dict = json.loads(params)
                    except json.JSONDecodeError:
                        params_dict = {}
            else:
                params_dict = {}
            
            # Get form_type from params, default to 'sxm' for backward compatibility
            form_type = params_dict.get('form_type', 'sxm') if isinstance(params_dict, dict) else 'sxm'
            
            # Match form_type with expected_form_type
            if form_type == expected_form_type:
                pxe_entry = entry
                break
        
        # Robust Fallback: If no type-specific entry found, use the most recent one overall
        if not pxe_entry and pxe_entries.exists():
            pxe_entry = pxe_entries.first()
        
        if not pxe_entry:
            # No matching PXE entries - skip auto-fill
            # Return empty structure with all expected fields
            empty_gpu_sns = {f'gpu{i}_sn': '' for i in range(1, 9)}
            empty_rgpu_sns = {f'rg{i}_sn': '' for i in range(1, 9)}
            return JsonResponse({
                'success': True,
                'base_sn': '',
                'replacement_sn': '',
                'rma_number': '',
                'notice': '',
                **empty_gpu_sns,
                **empty_rgpu_sns
            })
        
        # Step 4: Extract data from parameters field
        params = pxe_entry.parameters
        
        # Try to parse parameters (could be dict, string representation of dict, or JSON)
        if isinstance(params, dict):
            params_dict = params
        elif isinstance(params, str):
            try:
                # Try ast.literal_eval first (safer for Python dict strings)
                params_dict = ast.literal_eval(params)
            except (ValueError, SyntaxError):
                try:
                    # Fall back to JSON parsing
                    params_dict = json.loads(params)
                except json.JSONDecodeError:
                    params_dict = {}
        else:
            params_dict = {}
        
        base_sn = params_dict.get('base_sn', '') if isinstance(params_dict, dict) else ''
        replacement_sn = params_dict.get('replacement_sn', '') if isinstance(params_dict, dict) else ''
        rma_number = params_dict.get('rma_number', '') if isinstance(params_dict, dict) else ''
        notice = params_dict.get('notice', '') if isinstance(params_dict, dict) else ''
        
        # Extract GPU SNs and Replacement GPU SNs for PCIE page
        gpu_sns = {}
        rgpu_sns = {}
        if isinstance(params_dict, dict):
            for i in range(1, 9):
                gpu_sns[f'gpu{i}_sn'] = params_dict.get(f'gpu{i}_sn', '')
                rgpu_sns[f'rg{i}_sn'] = params_dict.get(f'rg{i}_sn', '')
        
        return JsonResponse({
            'success': True,
            'base_sn': base_sn,
            'replacement_sn': replacement_sn,
            'rma_number': rma_number,
            'notice': notice,
            **gpu_sns,  # Include GPU SNs directly in response
            **rgpu_sns  # Include Replacement GPU SNs directly in response
        })
        
    except Exception as e:
        logger.error(f"Error getting RMA info for BMC IP {bmc_ip}: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@permission_required('pxe.can_access_rma_pxe', raise_exception=True)
def get_pcie_models_api(request):
    """API endpoint to get available PCIE models from Firmware Inventory"""
    try:
        from .firmware_inventory import FIRMWARE_BASE_DIR
        pcie_dir = os.path.join(FIRMWARE_BASE_DIR, 'pcie')
        models = []
        if os.path.exists(pcie_dir):
            for item in os.listdir(pcie_dir):
                if os.path.isdir(os.path.join(pcie_dir, item)):
                    models.append(item)
        models.sort()
        return JsonResponse({'success': True, 'models': models})
    except Exception as e:
        logger.error(f"Error fetching PCIE models: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@permission_required('pxe.can_access_rma_pxe', raise_exception=True)
def get_pcie_eco_numbers_api(request, model):
    """API endpoint to get available ECO numbers for a specific PCIE model"""
    try:
        from .firmware_inventory import FIRMWARE_BASE_DIR
        eco_dir = os.path.join(FIRMWARE_BASE_DIR, 'pcie', model)
        eco_numbers = []
        if os.path.exists(eco_dir):
            for item in os.listdir(eco_dir):
                if os.path.isdir(os.path.join(eco_dir, item)):
                    eco_numbers.append(item)
        eco_numbers.sort()
        return JsonResponse({'success': True, 'eco_numbers': eco_numbers})
    except Exception as e:
        logger.error(f"Error fetching PCIE ECO numbers for {model}: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@permission_required('pxe.can_access_rma_pxe', raise_exception=True)
def get_eco_numbers_api(request, image_type):
    """API endpoint to get available ECO numbers for a specific image type"""
    try:
        # Get optional gpu_model and cooling from query parameters
        gpu_model = request.GET.get('gpu_model', '').lower()
        cooling = request.GET.get('cooling', '').upper()
        
        # Map image type to product types
        product_types = []
        if image_type == 'ubuntu2204-x86-rma':
            # H100/200 images - filter by gpu_model and cooling if provided
            if gpu_model and cooling:
                # Specific filtering based on both gpu_model and cooling
                product_types = [f'{gpu_model.upper()}_{cooling}']
            elif gpu_model:
                # Filter by gpu_model only
                product_types = [f'{gpu_model.upper()}_AC', f'{gpu_model.upper()}_LC']
            elif cooling:
                # Filter by cooling only
                product_types = [f'H100_{cooling}', f'H200_{cooling}']
            else:
                # No filter - show all H100/200
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
    # Get operation_type from POST (form submission) or GET (page navigation) or default to 'rma'
    if request.method == "POST":
        operation_type = request.POST.get('operation_type', 'rma')
    else:
        operation_type = request.GET.get('operation_type', 'rma')
    
    if request.method == "POST":
        if operation_type == 'pcie':
            bound_form = PcieGpuForm(request.POST, user=request.user, prefix='pcie')
        elif operation_type == 'gb':
            bound_form = GbGpuForm(request.POST, user=request.user, prefix='gb')
        else:
            bound_form = RmaForm(request.POST, user=request.user, prefix='rma')
            
        if bound_form.is_valid():
            if operation_type == 'pcie':
                rma_number = bound_form.cleaned_data.get('rma_number', '')
                bmc_ip = bound_form.cleaned_data.get('bmc_ip', '')
                image = bound_form.cleaned_data.get('image', '')
                tests = bound_form.cleaned_data.get('tests', [])
                remove = bound_form.cleaned_data.get('remove', False)
                check = bound_form.cleaned_data.get('check', False)
                fw_update = bound_form.cleaned_data.get('fw_update', False)
                dcgmr4_loop = bound_form.cleaned_data.get('dcgmr4_loop')
                
                # GPU SNs
                gpu_params = []
                params_storage = {'rma_number': rma_number, 'image': image, 'form_type': 'pcie'}
                for i in range(1, 9):
                    sn = bound_form.cleaned_data.get(f'gpu{i}_sn', '').strip()
                    gpu_params.append(f"g{i}={sn}")
                    params_storage[f'gpu{i}_sn'] = sn
                
                # Replacement GPU SNs
                for i in range(1, 9):
                    sn = bound_form.cleaned_data.get(f'rg{i}_sn', '').strip()
                    gpu_params.append(f"rg{i}={sn}")
                    params_storage[f'rg{i}_sn'] = sn
                
                tests_list = list(tests) if tests else []
                # Add 'pcie' to test parameters for PCIE GPU test
                tests_list.append('pcie')
                if fw_update:
                    tests_list.append('fw_update')
                if 'dcgm_r4' in tests:
                    tests_list.append(f"dcgmr4_loop={dcgmr4_loop or 1}")
                
                tests_list.extend(gpu_params)
                tests_param = " ".join(tests_list)
                params_storage['tests'] = tests_param
                params_storage['fw_update'] = fw_update
                if 'dcgm_r4' in tests:
                    params_storage['dcgmr4_loop'] = dcgmr4_loop or 1
                
                macs = get_lan_macs(bmc_ip)
                macs = [normalize_mac_for_pxe(x) for x in macs if x]
                macs = [x for x in macs if x]
                
                if remove:
                    result['actions'] = remove_pxe_entries_and_boot_files(macs)
                elif check:
                    result['check']=[]
                    for x in macs:
                        try:
                            entry=PxeEntry.objects.get(mac=x)
                            result['check'].append(f"MAC: {entry.mac} | Image: {entry.image} | Parameters: {entry.parameters}")
                        except PxeEntry.DoesNotExist:
                            result['check'].append(f"MAC: {x} not found in database")
                elif rma_number and macs:
                    result['actions']=[]
                    for x in macs:
                        PxeEntry.objects.update_or_create(
                            mac=x,
                            defaults={'parameters': params_storage,'image':image},
                        )
                        success, error = run_rma_command_sync(
                            f"{RMA_PXE_GENERATION_SCRIPT} '{x}' '{image}' '' '{rma_number}' '' '{tests_param}'",
                            timeout=60
                        )
                        if success:
                            result['actions'].append(f"Generated PXE for MAC: {x}")
                        else:
                            result['actions'].append(f"Failed to generate PXE for {x}: {error}")
                
                form = RmaForm(user=request.user, prefix='rma')
                pcie_form = PcieGpuForm(user=request.user, prefix='pcie')
                gb_form = GbGpuForm(user=request.user, prefix='gb')
            elif operation_type == 'gb':
                base_sn = bound_form.cleaned_data.get('base_sn', '').strip()
                rma_number = bound_form.cleaned_data.get('rma_number', '')
                bmc_ip = bound_form.cleaned_data.get('bmc_ip', '')
                tests = bound_form.cleaned_data.get('tests', [])
                image = bound_form.cleaned_data.get('image', '')
                remove = bound_form.cleaned_data.get('remove', False)
                check = bound_form.cleaned_data.get('check', False)
                notice = bound_form.cleaned_data.get('notice', '').strip()
                dcgmr4_loop = bound_form.cleaned_data.get('dcgmr4_loop')

                macs = get_gb_lan_macs(bmc_ip) or []
                macs = [normalize_mac_for_pxe(x) for x in macs if x]
                macs = [x for x in macs if x]

                # HMC Log: special exclusive action, then redirect to logs browser
                if 'hmc_log' in tests:
                    if not base_sn:
                        result['actions'] = ['Base SN is required for HMC Log.']
                    elif not rma_number:
                        result['actions'] = ['RMA Number is required for HMC Log.']
                    elif not bmc_ip:
                        result['actions'] = ['BMC IP is required for HMC Log.']
                    else:
                        try:
                            browse_path = collect_hmc_log_to_rma_folder(
                                base_sn=base_sn,
                                rma_number=rma_number,
                                bmc_ip=bmc_ip,
                                operation_type='gb',
                            )
                            return redirect(reverse('rma_log_browse', kwargs={'path': browse_path}))
                        except Exception as e:
                            logger.error(f"HMC Log collection failed: {e}")
                            result['actions'] = [f"HMC Log collection failed: {e}"]

                elif remove:
                    result['actions'] = remove_pxe_entries_and_boot_files(macs)
                elif check:
                    result['check'] = []
                    for x in macs:
                        try:
                            entry = PxeEntry.objects.get(mac=x)
                            result['check'].append(f"MAC: {entry.mac} | Image: {entry.image} | Parameters: {entry.parameters}")
                        except PxeEntry.DoesNotExist:
                            result['check'].append(f"MAC: {x} not found in database")
                elif base_sn and rma_number and macs:
                    # Build tests parameter for GB
                    tests_list = list(tests) if tests else []
                    if 'dcgm_r4' in tests:
                        tests_list.append(f"dcgmr4_loop={dcgmr4_loop or 1}")
                    if notice:
                        tests_list.append(f'notice={notice}')
                    tests_param = " ".join(tests_list) if tests_list else " "

                    result['actions'] = []
                    params = {
                        'base_sn': base_sn,
                        'rma_number': rma_number,
                        'notice': notice,
                        'tests': tests_param,
                        'dcgmr4_loop': dcgmr4_loop or 1 if 'dcgm_r4' in tests else None,
                        'form_type': 'gb',
                    }
                    for x in macs:
                        PxeEntry.objects.update_or_create(
                            mac=x,
                            defaults={'parameters': params, 'image': image},
                        )
                        success, error = run_rma_command_sync(
                            f"{RMA_PXE_GENERATION_SCRIPT} '{x}' '{image}' '{base_sn}' '{rma_number}' '' '{tests_param}'",
                            timeout=60
                        )
                        if success:
                            result['actions'].append(f"Generated PXE for MAC: {x}")
                        else:
                            result['actions'].append(f"Failed to generate PXE for {x}: {error}")

                form = RmaForm(user=request.user, prefix='rma')
                pcie_form = PcieGpuForm(user=request.user, prefix='pcie')
                gb_form = GbGpuForm(user=request.user, prefix='gb')
            else:
                # Original RMA logic
                base_sn = bound_form.cleaned_data.get('base_sn', '')
                replacement_sn = bound_form.cleaned_data.get('replacement_sn', '').strip()
                rma_number = bound_form.cleaned_data.get('rma_number', '')
                bmc_ip = bound_form.cleaned_data.get('bmc_ip', '')
                tests = bound_form.cleaned_data.get('tests', [])
                image = bound_form.cleaned_data.get('image', '')
                remove=bound_form.cleaned_data.get('remove', False)
                check=bound_form.cleaned_data.get('check', False)
                fw_update=bound_form.cleaned_data.get('fw_update', False)
                eco_number = bound_form.cleaned_data.get('eco_number', '')
                gpu_model = bound_form.cleaned_data.get('gpu_model', '')
                cooling = bound_form.cleaned_data.get('cooling', '')
                notice = bound_form.cleaned_data.get('notice', '').strip()
                dcgmr4_loop = bound_form.cleaned_data.get('dcgmr4_loop')
                
                # Debug logging
                logger.info(f"RMA PXE form submitted: base_sn={base_sn}, replacement_sn={replacement_sn}, rma_number={rma_number}, bmc_ip={bmc_ip}, tests={tests}, fw_update={fw_update}, eco_number={eco_number}, gpu_model={gpu_model}, cooling={cooling}, remove={remove}, check={check}")
                
                # Build tests parameter including fw_update, eco_number, gpu_model, cooling, and notice
                tests_list = list(tests) if tests else []
                if fw_update:
                    tests_list.append('fw_update')
                    if eco_number and eco_number.strip():
                        tests_list.append(f'eco_number={eco_number}')
                    if gpu_model and gpu_model.strip():
                        tests_list.append(f'gpu_model={gpu_model}')
                    if cooling and cooling.strip():
                        tests_list.append(f'cooling={cooling}')
                if 'dcgm_r4' in tests:
                    tests_list.append(f"dcgmr4_loop={dcgmr4_loop or 1}")
                if notice:
                    tests_list.append(f'notice={notice}')
                tests_param = " ".join(tests_list) if tests_list else " "
                
                macs = get_lan_macs(bmc_ip)
                macs = [normalize_mac_for_pxe(x) for x in macs if x]
                macs = [x for x in macs if x]
                
                # Handle Remote FW Update Test
                if 'remote_fw_update' in tests:
                    task_id = str(uuid.uuid4())
                    thread = threading.Thread(
                        target=run_remote_fw_update_task,
                        args=(task_id, bmc_ip, image)
                    )
                    thread.daemon = True
                    thread.start()
                    result['remote_fw_update_started'] = ['Remote FW update task started']
                    result['remote_fw_task_id'] = task_id
                    
                    form = RmaForm(user=request.user, prefix='rma')
                    pcie_form = PcieGpuForm(user=request.user, prefix='pcie')
                    gb_form = GbGpuForm(user=request.user, prefix='gb')
                    golden_entries = RmaTestingDb.objects.all().order_by('golden_number')
                    can_force_unlink = request.user.has_perm('pxe.can_force_unlink_golden')
                    return render(request,'features/rma_pxe.html',{
                        'form':form, 'pcie_form': pcie_form, 'operation_type': operation_type,
                        'gb_form': gb_form,
                        'result':result, 'golden_entries': golden_entries, 'can_force_unlink': can_force_unlink
                    })
            
                if remove:
                    result['actions'] = remove_pxe_entries_and_boot_files(macs)
                elif check:
                    result['check']=[]
                    for x in macs:
                        try:
                            entry=PxeEntry.objects.get(mac=x)
                            result['check'].append(f"MAC: {entry.mac} | Image: {entry.image} | Parameters: {entry.parameters}")
                        except PxeEntry.DoesNotExist:
                            result['check'].append(f"MAC: {x} not found in database")
                elif base_sn and rma_number and macs:
                    result['actions']=[]
                    for x in macs:
                        params = {
                            'base_sn': base_sn, 
                            'replacement_sn': replacement_sn,
                            'rma_number': rma_number, 
                            'tests': tests_param,
                            'fw_update': fw_update,
                            'eco_number': eco_number,
                            'gpu_model': gpu_model,
                            'cooling': cooling,
                            'notice': notice,
                            'dcgmr4_loop': dcgmr4_loop or 1 if 'dcgm_r4' in tests else None,
                            'form_type': 'sxm'
                        }
                        PxeEntry.objects.update_or_create(
                            mac=x,
                            defaults={'parameters': params,'image':image},
                        )
                        success, error = run_rma_command_sync(
                            f"{RMA_PXE_GENERATION_SCRIPT} '{x}' '{image}' '{base_sn}' '{rma_number}' '{replacement_sn}' '{tests_param}'",
                            timeout=60
                        )
                        if success:
                            result['actions'].append(f"Generated PXE for MAC: {x}")
                        else:
                            result['actions'].append(f"Failed to generate PXE for {x}: {error}")
                
                form = RmaForm(user=request.user, prefix='rma')
                pcie_form = PcieGpuForm(user=request.user, prefix='pcie')
                gb_form = GbGpuForm(user=request.user, prefix='gb')
        else:
            # Form validation failed
            logger.error(f"Form validation failed: {bound_form.errors}")
            form = RmaForm(user=request.user, prefix='rma')
            pcie_form = PcieGpuForm(user=request.user, prefix='pcie')
            gb_form = GbGpuForm(user=request.user, prefix='gb')
            if operation_type == 'pcie':
                pcie_form._errors = bound_form.errors
            elif operation_type == 'gb':
                gb_form._errors = bound_form.errors
            else:
                form._errors = bound_form.errors
    else:
        form = RmaForm(user=request.user, prefix='rma')
        pcie_form = PcieGpuForm(user=request.user, prefix='pcie')
        gb_form = GbGpuForm(user=request.user, prefix='gb')
    
    if operation_type == 'gb':
        golden_entries = RmaGbDb.objects.all().order_by('golden_number')
    else:
        golden_entries = RmaTestingDb.objects.all().order_by('golden_number')
    can_force_unlink = request.user.has_perm('pxe.can_force_unlink_golden')
    
    return render(request,'features/rma_pxe.html',{
        'form':form,
        'pcie_form': pcie_form,
        'gb_form': gb_form,
        'operation_type': operation_type,
        'result':result,
        'golden_entries': golden_entries,
        'can_force_unlink': can_force_unlink
    })

@login_required
@permission_required('pxe.can_view_golden_test_setting', raise_exception=True)
@require_http_methods(["GET"])
def golden_setting_api(request, entry_id):
    """API endpoint to get PXE setting for a golden unit"""
    try:
        operation_type = request.GET.get('operation_type', 'rma')
        if operation_type == 'gb':
            entry = RmaGbDb.objects.get(id=entry_id)
        else:
            entry = RmaTestingDb.objects.get(id=entry_id)
        
        # Helper to normalize MAC
        def normalize_mac(mac):
            if not mac: return None
            return mac.replace(':', '').replace('-', '').lower()

        # Check LAN0
        lan0 = normalize_mac(entry.lan0_mac)
        pxe_entry_0 = None
        if lan0:
            pxe_entry_0 = PxeEntry.objects.filter(mac=lan0).first()

        # Check LAN1 (not applicable for GB DB)
        pxe_entry_1 = None
        if operation_type != 'gb':
            lan1 = normalize_mac(entry.lan1_mac)
            if lan1:
                pxe_entry_1 = PxeEntry.objects.filter(mac=lan1).first()
            
        if not pxe_entry_0 and not pxe_entry_1:
            return JsonResponse({
                'success': False,
                'error': 'No PXE configuration found for this unit'
            })

        result_data = {}
        
        if pxe_entry_0:
            result_data['lan0'] = {
                'mac': entry.lan0_mac,
                'image': pxe_entry_0.image,
                'parameters': pxe_entry_0.parameters,
                'updated_at': pxe_entry_0.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            }
            
        if pxe_entry_1:
             result_data['lan1'] = {
                'mac': entry.lan1_mac,
                'image': pxe_entry_1.image,
                'parameters': pxe_entry_1.parameters,
                'updated_at': pxe_entry_1.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            }

        return JsonResponse({
            'success': True,
            'settings': result_data
        })

    except (RmaTestingDb.DoesNotExist, RmaGbDb.DoesNotExist):
        return JsonResponse({
            'success': False,
            'error': 'Golden unit not found'
        })
    except Exception as e:
        logger.error(f"Error fetching golden setting: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
