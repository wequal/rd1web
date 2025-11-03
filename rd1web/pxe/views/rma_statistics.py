"""
RMA Statistics Views

Views for displaying RMA test failure statistics
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, permission_required
from datetime import datetime, timedelta
from django.utils import timezone
import logging

from ..rma_statistics import (
    get_weekly_statistics,
    get_monthly_statistics,
    get_yearly_statistics,
    get_current_week_range,
    get_week_by_offset,
    get_month_by_offset,
    get_year_by_offset,
    scan_all_rma_directories,
)

logger = logging.getLogger(__name__)


@login_required
@permission_required('pxe.can_view_rma_statistics', raise_exception=True)
def rma_statistics(request):
    """
    Main RMA statistics page
    Shows weekly/monthly/yearly failure statistics with GPU model breakdown
    """
    # Get parameters
    period = request.GET.get('period', 'weekly')  # weekly, monthly, yearly
    week_offset = int(request.GET.get('week_offset', 0))  # For weekly navigation
    month_offset = int(request.GET.get('month_offset', 0))  # For monthly navigation
    year_offset = int(request.GET.get('year_offset', 0))  # For yearly navigation
    year = request.GET.get('year', None)
    month = request.GET.get('month', None)
    
    # Determine date range and get statistics
    if period == 'monthly':
        # Use month_offset if no explicit year/month provided
        if not year and not month:
            year, month = get_month_by_offset(month_offset)
        elif year and month:
            year = int(year)
            month = int(month)
        else:
            # Default to current month
            now = timezone.now()
            year = now.year
            month = now.month
        
        stats = get_monthly_statistics(year, month)
        period_display = f"{datetime(year, month, 1).strftime('%B %Y')}"
        
    elif period == 'yearly':
        # Use year_offset if no explicit year provided
        if not year:
            year = get_year_by_offset(year_offset)
        else:
            year = int(year)
        
        stats = get_yearly_statistics(year)
        period_display = str(year)
        
    else:  # weekly (default)
        start_date, end_date = get_week_by_offset(week_offset)
        stats = get_weekly_statistics(start_date, end_date)
        period_display = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
    
    # Filter out unwanted GPU models from breakdown
    if 'gpu_breakdown' in stats and stats['gpu_breakdown']:
        filtered_breakdown = {
            gpu_model: data 
            for gpu_model, data in stats['gpu_breakdown'].items()
            if gpu_model not in ['unknown', 'Unknown', 'BMC_IP:']
        }
        stats['gpu_breakdown'] = filtered_breakdown
    
    # Prepare context
    context = {
        'page_title': 'RMA Statistics',
        'period': period,
        'period_display': period_display,
        'week_offset': week_offset,
        'month_offset': month_offset,
        'year_offset': year_offset,
        'stats': stats,
        'year': year if period in ['monthly', 'yearly'] else None,
        'month': month if period == 'monthly' else None,
    }
    
    return render(request, 'features/rma_statistics.html', context)


@login_required
@permission_required('pxe.can_view_rma_statistics', raise_exception=True)
def rma_statistics_api(request):
    """
    API endpoint for RMA statistics
    Returns JSON data for AJAX requests
    """
    try:
        # Get parameters
        period = request.GET.get('period', 'weekly')
        week_offset = int(request.GET.get('week_offset', 0))
        year = request.GET.get('year', None)
        month = request.GET.get('month', None)
        
        # Get statistics based on period
        if period == 'monthly':
            if year and month:
                year = int(year)
                month = int(month)
            else:
                now = timezone.now()
                year = now.year
                month = now.month
            
            stats = get_monthly_statistics(year, month)
            
        elif period == 'yearly':
            if year:
                year = int(year)
            else:
                year = timezone.now().year
            
            stats = get_yearly_statistics(year)
            
        else:  # weekly
            start_date, end_date = get_week_by_offset(week_offset)
            stats = get_weekly_statistics(start_date, end_date)
        
        # Filter out unwanted GPU models from breakdown
        if 'gpu_breakdown' in stats and stats['gpu_breakdown']:
            filtered_breakdown = {
                gpu_model: data 
                for gpu_model, data in stats['gpu_breakdown'].items()
                if gpu_model not in ['unknown', 'Unknown', 'BMC_IP:']
            }
            stats['gpu_breakdown'] = filtered_breakdown
        
        # Convert datetime objects to strings for JSON
        if 'start_date' in stats:
            stats['start_date'] = stats['start_date'].isoformat()
        if 'end_date' in stats:
            stats['end_date'] = stats['end_date'].isoformat()
        
        return JsonResponse({
            'success': True,
            'stats': stats,
        })
        
    except Exception as e:
        logger.error(f"Error in rma_statistics_api: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


@login_required
@permission_required('pxe.can_view_rma_statistics', raise_exception=True)
def trigger_scan(request):
    """
    Manually trigger RMA statistics scan
    Admin use only
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'POST method required',
        }, status=405)
    
    try:
        # Trigger scan
        from ..tasks import scan_rma_statistics
        
        # Try to run async if Celery is available
        try:
            task = scan_rma_statistics.delay()
            return JsonResponse({
                'success': True,
                'message': 'Scan task queued successfully',
                'task_id': str(task.id),
            })
        except Exception as celery_error:
            # If Celery is not available, run synchronously
            logger.warning(f"Celery not available, running scan synchronously: {celery_error}")
            stats = scan_all_rma_directories()
            return JsonResponse({
                'success': True,
                'message': 'Scan completed',
                'stats': stats,
            })
            
    except Exception as e:
        logger.error(f"Error triggering scan: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)

