#!/usr/bin/env python3
"""
Views for displaying MAC-IP results from multiple subnets.
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count
from ..models import ArpScanResult
from ..background_tasks import mac_ip_task


@login_required
def mac_ip_results(request):
    """Display MAC-IP scan results from multiple subnets"""
    # Get filter parameters
    search_query = request.GET.get('search', '')
    show_inactive = request.GET.get('show_inactive', 'false') == 'true'
    subnet_filter = request.GET.get('subnet_filter', 'all')
    
    # Build queryset
    queryset = ArpScanResult.objects.all()
    
    if not show_inactive:
        queryset = queryset.filter(is_active=True)
    
    if subnet_filter != 'all':
        queryset = queryset.filter(subnet_source=subnet_filter)
    
    if search_query:
        queryset = queryset.filter(
            Q(ip_address__icontains=search_query) |
            Q(mac_address__icontains=search_query) |
            Q(hostname__icontains=search_query)
        )
    
    queryset = queryset.order_by('subnet_source', '-is_active', 'ip_address')
    
    # Pagination
    paginator = Paginator(queryset, 50)  # Show 50 results per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get task status
    task_status = mac_ip_task.get_status()
    
    # Get subnet statistics
    subnet_stats = ArpScanResult.objects.values('subnet_source').annotate(
        total=Count('id'),
        active=Count('id', filter=Q(is_active=True)),
        inactive=Count('id', filter=Q(is_active=False))
    ).order_by('subnet_source')
    
    # Get available subnet choices for filter dropdown
    available_subnets = list(ArpScanResult.objects.values_list('subnet_source', flat=True).distinct())
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'show_inactive': show_inactive,
        'subnet_filter': subnet_filter,
        'available_subnets': available_subnets,
        'task_status': task_status,
        'subnet_stats': subnet_stats,
        'total_count': queryset.count(),
        'active_count': ArpScanResult.objects.filter(is_active=True).count(),
        'inactive_count': ArpScanResult.objects.filter(is_active=False).count(),
    }
    
    return render(request, 'features/mac_ip_results.html', context)


@login_required
def mac_ip_api(request):
    """API endpoint for MAC-IP scan data from multiple subnets"""
    if request.method == 'GET':
        # Get filter parameters
        subnet_filter = request.GET.get('subnet', 'all')
        limit = min(int(request.GET.get('limit', 50)), 200)  # Max 200 results
        
        # Build queryset for recent results
        queryset = ArpScanResult.objects.filter(is_active=True)
        if subnet_filter != 'all':
            queryset = queryset.filter(subnet_source=subnet_filter)
            
        recent_results = queryset.order_by('subnet_source', 'ip_address')[:limit]
        
        # Get subnet statistics
        subnet_stats = {}
        for subnet_data in ArpScanResult.objects.values('subnet_source').annotate(
            total=Count('id'),
            active=Count('id', filter=Q(is_active=True)),
            inactive=Count('id', filter=Q(is_active=False))
        ):
            subnet_name = subnet_data['subnet_source']
            subnet_stats[subnet_name] = {
                'total': subnet_data['total'],
                'active': subnet_data['active'],
                'inactive': subnet_data['inactive']
            }
        
        data = {
            'task_status': mac_ip_task.get_status(),
            'results': [
                {
                    'ip_address': result.ip_address,
                    'mac_address': result.mac_address,
                    'hostname': result.hostname,
                    'subnet_source': result.subnet_source,
                    'scan_interface': result.scan_interface,
                    'first_seen': result.first_seen.isoformat(),
                    'last_seen': result.last_seen.isoformat(),
                    'is_active': result.is_active
                }
                for result in recent_results
            ],
            'counts': {
                'total': ArpScanResult.objects.count(),
                'active': ArpScanResult.objects.filter(is_active=True).count(),
                'inactive': ArpScanResult.objects.filter(is_active=False).count(),
                'by_subnet': subnet_stats
            },
            'filter': {
                'subnet': subnet_filter,
                'limit': limit
            }
        }
        
        return JsonResponse(data)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405) 