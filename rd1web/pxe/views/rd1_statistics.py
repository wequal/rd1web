"""
RD1 Statistics Views

Views for the RD1 Statistic page — strict fail counting with per-item FD2 breakdown.
Independent from rma_statistics views.
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, permission_required
from datetime import datetime
from django.utils import timezone
import logging

from ..rd1_statistics import (
    get_weekly_statistics,
    get_monthly_statistics,
    get_yearly_statistics,
    get_week_by_offset,
    get_month_by_offset,
    get_year_by_offset,
    scan_all_rd1_directories,
)

logger = logging.getLogger(__name__)


@login_required
@permission_required('pxe.can_view_rd1_statistics', raise_exception=True)
def rd1_statistics(request):
    """
    Main RD1 statistics page.
    Strict fail counting — any failure in the log counts, even if later passed.
    Shows weekly / monthly / yearly breakdown with per-GPU-SKU FD2 item detail.
    """
    period = request.GET.get('period', 'weekly')
    week_offset = int(request.GET.get('week_offset', 0))
    month_offset = int(request.GET.get('month_offset', 0))
    year_offset = int(request.GET.get('year_offset', 0))
    year = request.GET.get('year', None)
    month = request.GET.get('month', None)

    if period == 'monthly':
        if not year and not month:
            year, month = get_month_by_offset(month_offset)
        elif year and month:
            year = int(year)
            month = int(month)
        else:
            now = timezone.now()
            year, month = now.year, now.month
        stats = get_monthly_statistics(year, month)
        period_display = datetime(year, month, 1).strftime('%B %Y')

    elif period == 'yearly':
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

    context = {
        'page_title': 'RD1 Statistics',
        'period': period,
        'period_display': period_display,
        'week_offset': week_offset,
        'month_offset': month_offset,
        'year_offset': year_offset,
        'stats': stats,
        'year': year if period in ('monthly', 'yearly') else None,
        'month': month if period == 'monthly' else None,
    }

    return render(request, 'features/rd1_statistics.html', context)


@login_required
@permission_required('pxe.can_view_rd1_statistics', raise_exception=True)
def rd1_statistics_api(request):
    """
    JSON API for RD1 statistics — used by AJAX period navigation.
    """
    try:
        period = request.GET.get('period', 'weekly')
        week_offset = int(request.GET.get('week_offset', 0))
        year = request.GET.get('year', None)
        month = request.GET.get('month', None)

        if period == 'monthly':
            if year and month:
                year, month = int(year), int(month)
            else:
                now = timezone.now()
                year, month = now.year, now.month
            stats = get_monthly_statistics(year, month)

        elif period == 'yearly':
            year = int(year) if year else timezone.now().year
            stats = get_yearly_statistics(year)

        else:
            start_date, end_date = get_week_by_offset(week_offset)
            stats = get_weekly_statistics(start_date, end_date)

        # Serialise datetime objects for JSON
        if 'start_date' in stats:
            stats['start_date'] = stats['start_date'].isoformat()
        if 'end_date' in stats:
            stats['end_date'] = stats['end_date'].isoformat()

        return JsonResponse({'success': True, 'stats': stats})

    except Exception as e:
        logger.error(f"Error in rd1_statistics_api: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@permission_required('pxe.can_view_rd1_statistics', raise_exception=True)
def rd1_trigger_scan(request):
    """
    Manually trigger an RD1 statistics scan (admin use).
    Tries Celery first; falls back to synchronous scan.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'}, status=405)

    try:
        from ..tasks import scan_rd1_statistics

        try:
            task = scan_rd1_statistics.delay()
            return JsonResponse({
                'success': True,
                'message': 'RD1 scan task queued successfully',
                'task_id': str(task.id),
            })
        except Exception as celery_error:
            logger.warning(f"Celery unavailable, running RD1 scan synchronously: {celery_error}")
            stats = scan_all_rd1_directories()
            return JsonResponse({
                'success': True,
                'message': 'RD1 scan completed synchronously',
                'stats': stats,
            })

    except Exception as e:
        logger.error(f"Error triggering RD1 scan: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
