from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt
import json

from ..models import RmaTestingDb
from ..form import RmaTestingDbForm, RmaTestingDbSearchForm


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
    paginator = Paginator(queryset, 25)  # Show 25 entries per page
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
    length = int(request.GET.get('length', 25))
    
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
