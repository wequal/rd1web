from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
import json
import logging

from ..models import RmaTestingDb
from ..form import RmaTestingDbForm, RmaTestingDbSearchForm
from ..remote_config import remote_dict
from .rma_pxe import remove_pxe_entries_and_boot_files
from ..models import RmaGbDb

logger = logging.getLogger(__name__)

def change(golden_number, bmc_mac, bmc_ip):
    remote_dict['rma'].run(f"/srv/share/scripts/rma/rma_fixed_ip {golden_number} {bmc_mac} {bmc_ip} change")

def delete(golden_number, bmc_mac, bmc_ip):
    remote_dict['rma'].run(f"/srv/share/scripts/rma/rma_fixed_ip {golden_number} {bmc_mac} {bmc_ip} delete")
    


@login_required
@permission_required('pxe.can_access_rma_testing_db', raise_exception=True)
def rma_testing_db_list(request):
    """Main view for RMA Testing DB page with search and pagination"""
    
    # Handle search
    search_form = RmaTestingDbSearchForm(request.GET)
    queryset = RmaTestingDb.objects.all()
    
    if search_form.is_valid():
        search_query = search_form.cleaned_data.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(bmc_mac__icontains=search_query) |
                Q(bmc_ip__icontains=search_query) |
                Q(bmc_password__icontains=search_query) |
                Q(lan0_mac__icontains=search_query) |
                Q(lan1_mac__icontains=search_query) |
                Q(golden_number__icontains=search_query)
            )
    
    # Pagination
    paginator = Paginator(queryset, 20)  # Show 20 entries per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Create empty form for adding new entries
    add_form = RmaTestingDbForm()
    
    context = {
        'entries': page_obj,
        'search_form': search_form,
        'add_form': add_form,
        'total_entries': queryset.count(),
    }
    
    return render(request, 'features/rma_testing_db.html', context)


@login_required
@permission_required('pxe.can_access_rma_testing_db', raise_exception=True)
@require_http_methods(["POST"])
def rma_testing_db_add(request):
    """Add new RMA Testing DB entry"""
    
    form = RmaTestingDbForm(request.POST)
    
    if form.is_valid():
        try:
            entry = form.save()
            transaction.commit(change(entry.golden_number, entry.bmc_mac, entry.bmc_ip))
            messages.success(request, f'Successfully added RMA entry for BMC MAC: {entry.bmc_mac}')
            return JsonResponse({
                'success': True,
                'message': 'Entry added successfully',
                'entry': {
                    'id': entry.id,
                    'bmc_mac': entry.bmc_mac,
                    'bmc_ip': entry.bmc_ip,
                    'bmc_password': entry.bmc_password,
                    'lan0_mac': entry.lan0_mac,
                    'lan1_mac': entry.lan1_mac,
                    'golden_number': entry.golden_number,
                }
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error adding entry: {str(e)}'
            })
    else:
        return JsonResponse({
            'success': False,
            'message': 'Form validation failed',
            'errors': form.errors
        })


@login_required
@permission_required('pxe.can_access_rma_testing_db', raise_exception=True)
@require_http_methods(["POST"])
def rma_testing_db_edit(request, entry_id):
    """Edit existing RMA Testing DB entry"""
    
    entry = get_object_or_404(RmaTestingDb, id=entry_id)
    form = RmaTestingDbForm(request.POST, instance=entry)
    
    if form.is_valid():
        try:
            updated_entry = form.save()
            transaction.commit(change(updated_entry.golden_number, updated_entry.bmc_mac, updated_entry.bmc_ip))
            messages.success(request, f'Successfully updated RMA entry for BMC MAC: {updated_entry.bmc_mac}')
            return JsonResponse({
                'success': True,
                'message': 'Entry updated successfully',
                'entry': {
                    'id': updated_entry.id,
                    'bmc_mac': updated_entry.bmc_mac,
                    'bmc_ip': updated_entry.bmc_ip,
                    'bmc_password': updated_entry.bmc_password,
                    'lan0_mac': updated_entry.lan0_mac,
                    'lan1_mac': updated_entry.lan1_mac,
                    'golden_number': updated_entry.golden_number,
                }
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error updating entry: {str(e)}'
            })
    else:
        return JsonResponse({
            'success': False,
            'message': 'Form validation failed',
            'errors': form.errors
        })


@login_required
@permission_required('pxe.can_access_rma_testing_db', raise_exception=True)
@require_http_methods(["POST"])
def rma_testing_db_delete(request, entry_id):
    """Delete RMA Testing DB entry"""
    
    entry = get_object_or_404(RmaTestingDb, id=entry_id)
    
    try:
        bmc_mac = entry.bmc_mac
        entry.delete()
        transaction.commit(delete(entry.golden_number, entry.bmc_mac, entry.bmc_ip))
        messages.success(request, f'Successfully deleted RMA entry for BMC MAC: {bmc_mac}')
        return JsonResponse({
            'success': True,
            'message': 'Entry deleted successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error deleting entry: {str(e)}'
        })


@login_required
@permission_required('pxe.can_access_rma_testing_db', raise_exception=True)
@require_http_methods(["GET"])
def rma_testing_db_get(request, entry_id):
    """Get single RMA Testing DB entry (for editing)"""
    
    entry = get_object_or_404(RmaTestingDb, id=entry_id)
    
    return JsonResponse({
        'success': True,
        'entry': {
            'id': entry.id,
            'bmc_mac': entry.bmc_mac,
            'bmc_ip': entry.bmc_ip,
            'bmc_password': entry.bmc_password,
            'lan0_mac': entry.lan0_mac,
            'lan1_mac': entry.lan1_mac,
            'golden_number': entry.golden_number,
        }
    })


@login_required
@permission_required('pxe.can_access_rma_testing_db', raise_exception=True)
@require_http_methods(["GET"])
def rma_testing_db_api(request):
    """API endpoint for DataTables or AJAX requests"""
    
    # Get query parameters
    search_value = request.GET.get('search[value]', '')
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 20))
    
    # Build queryset
    queryset = RmaTestingDb.objects.all()
    
    if search_value:
        queryset = queryset.filter(
            Q(bmc_mac__icontains=search_value) |
            Q(bmc_ip__icontains=search_value) |
            Q(bmc_password__icontains=search_value) |
            Q(lan0_mac__icontains=search_value) |
            Q(lan1_mac__icontains=search_value) |
            Q(golden_number__icontains=search_value)
        )
    
    total_records = RmaTestingDb.objects.count()
    filtered_records = queryset.count()
    
    # Apply pagination
    entries = queryset[start:start + length]
    
    # Format data for DataTables
    data = []
    for entry in entries:
        data.append({
            'id': entry.id,
            'bmc_mac': entry.bmc_mac,
            'bmc_ip': entry.bmc_ip,
            'bmc_password': entry.bmc_password,
            'lan0_mac': entry.lan0_mac,
            'lan1_mac': entry.lan1_mac,
            'golden_number': entry.golden_number,
        })
    
    return JsonResponse({
        'draw': int(request.GET.get('draw', 1)),
        'recordsTotal': total_records,
        'recordsFiltered': filtered_records,
        'data': data
    })


@login_required
@permission_required('pxe.can_access_rma_pxe', raise_exception=True)
@require_http_methods(["POST"])
def golden_link(request, entry_id):
    """API endpoint to link a golden number to the current user"""
    try:
        operation_type = request.GET.get('operation_type', 'rma')
        if operation_type == 'gb':
            entry = RmaGbDb.objects.get(id=entry_id)
        else:
            entry = RmaTestingDb.objects.get(id=entry_id)
        
        # Check if already linked
        if entry.linked_user is not None:
            return JsonResponse({
                'success': False,
                'error': f'Golden number "{entry.golden_number}" is already linked to {entry.linked_user.username}'
            })
        
        # Link to current user and set linked_at timestamp
        entry.linked_user = request.user
        entry.linked_at = timezone.now()
        entry.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully linked golden number "{entry.golden_number}"'
        })
        
    except (RmaTestingDb.DoesNotExist, RmaGbDb.DoesNotExist):
        return JsonResponse({
            'success': False,
            'error': 'Golden number entry not found'
        })
    except Exception as e:
        logger.error(f"Error linking golden number: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@permission_required('pxe.can_access_rma_pxe', raise_exception=True)
@require_http_methods(["POST"])
def golden_unlink(request, entry_id):
    """API endpoint to unlink a golden number"""
    try:
        operation_type = request.GET.get('operation_type', 'rma')
        if operation_type == 'gb':
            entry = RmaGbDb.objects.get(id=entry_id)
        else:
            entry = RmaTestingDb.objects.get(id=entry_id)
        
        # Check if not linked
        if entry.linked_user is None:
            return JsonResponse({
                'success': False,
                'error': 'Golden number is not linked to any user'
            })
        
        # Check permissions: only the linked user or users with force_unlink permission can unlink
        can_force_unlink = request.user.has_perm('pxe.can_force_unlink_golden')
        if entry.linked_user != request.user and not can_force_unlink:
            return JsonResponse({
                'success': False,
                'error': 'You do not have permission to unlink this golden number'
            })
        
        # Save current tester before unlinking
        if entry.linked_user:
            entry.last_tester = entry.linked_user.username
        
        # Unlink the golden number and clear linked_at timestamp
        entry.linked_user = None
        entry.linked_at = None
        entry.save()

        # Also remove PXE configuration (DB + PXE server boot files) for this golden's LAN MACs
        if operation_type == 'gb':
            cleanup_actions = remove_pxe_entries_and_boot_files([entry.lan0_mac])
        else:
            cleanup_actions = remove_pxe_entries_and_boot_files([entry.lan0_mac, entry.lan1_mac])
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully unlinked golden number "{entry.golden_number}"',
            'cleanup_actions': cleanup_actions,
        })
        
    except (RmaTestingDb.DoesNotExist, RmaGbDb.DoesNotExist):
        return JsonResponse({
            'success': False,
            'error': 'Golden number entry not found'
        })
    except Exception as e:
        logger.error(f"Error unlinking golden number: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
