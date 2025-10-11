from django.contrib import admin
from django.contrib.auth.models import User, Permission
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.utils.html import format_html
from django.db.models import Count, Sum, Q, Case, When, Value, IntegerField
from django.db import models
from django.utils import timezone
from datetime import timedelta
import zoneinfo
from django import forms
from .models import UserSession, UserActivity, UserStats
import logging

logger = logging.getLogger(__name__)

class UserSessionInline(admin.TabularInline):
    model = UserSession
    extra = 0
    readonly_fields = ('session_key', 'ip_address', 'user_agent', 'login_time', 'last_activity', 'logout_time', 'session_duration')
    fields = ('session_key', 'ip_address', 'login_time', 'last_activity', 'logout_time', 'is_active', 'session_duration')
    
    def session_duration(self, obj):
        if obj.logout_time:
            duration = obj.logout_time - obj.login_time
        else:
            duration = timezone.now() - obj.login_time
        return str(duration).split('.')[0]  # Remove microseconds
    session_duration.short_description = 'Duration'

class UserActivityInline(admin.TabularInline):
    model = UserActivity
    extra = 0
    readonly_fields = ('action', 'description', 'url_path', 'ip_address', 'timestamp', 'success')
    fields = ('timestamp', 'action', 'description', 'url_path', 'success')
    ordering = ['-timestamp']

@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'ip_address', 'login_time', 'last_activity', 'logout_time', 'is_active', 'session_duration_display', 'is_currently_active')
    list_filter = ('is_active', 'login_time', 'logout_time')
    search_fields = ('user__username', 'ip_address', 'user_agent')
    readonly_fields = ('session_key', 'user_agent', 'session_duration_display')
    date_hierarchy = 'login_time'
    
    def session_duration_display(self, obj):
        duration = obj.session_duration
        return str(duration).split('.')[0]  # Remove microseconds
    session_duration_display.short_description = 'Session Duration'
    
    def is_currently_active(self, obj):
        active = obj.is_currently_active
        color = 'green' if active else 'red'
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            'Active' if active else 'Inactive'
        )
    is_currently_active.short_description = 'Currently Active'

@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'description_short', 'url_path_short', 'ip_address', 'timestamp', 'success_display')
    # list_filter removed - no sidebar filters for cleaner look
    search_fields = ('user__username', 'description', 'url_path', 'ip_address')
    date_hierarchy = 'timestamp'
    readonly_fields = ('user', 'session', 'action', 'description', 'url_path', 'ip_address', 'user_agent', 'timestamp', 'success')
    list_per_page = 30  # Show 30 records per page
    
    def description_short(self, obj):
        return obj.description[:50] + '...' if len(obj.description) > 50 else obj.description
    description_short.short_description = 'Description'
    
    def url_path_short(self, obj):
        return obj.url_path[:30] + '...' if len(obj.url_path) > 30 else obj.url_path
    url_path_short.short_description = 'URL Path'
    
    def success_display(self, obj):
        color = 'green' if obj.success else 'red'
        icon = '✓' if obj.success else '✗'
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            icon
        )
    success_display.short_description = 'Success'
    
    # Custom views for different time periods
    def changelist_view(self, request, extra_context=None):
        # Get current date in LA timezone
        now = timezone.now()
        la_tz = zoneinfo.ZoneInfo('America/Los_Angeles')
        today = now.astimezone(la_tz).date()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        # Calculate statistics (exclude 'devin' user from statistics)
        daily_stats = UserActivity.objects.filter(
            timestamp__date=today
        ).exclude(user__username='devin').values('action').annotate(count=Count('id')).order_by('-count')
        
        weekly_stats = UserActivity.objects.filter(
            timestamp__date__gte=week_start
        ).exclude(user__username='devin').values('action').annotate(count=Count('id')).order_by('-count')
        
        monthly_stats = UserActivity.objects.filter(
            timestamp__date__gte=month_start
        ).exclude(user__username='devin').values('action').annotate(count=Count('id')).order_by('-count')
        
        # Totals
        daily_total = sum(item['count'] for item in daily_stats)
        weekly_total = sum(item['count'] for item in weekly_stats)
        monthly_total = sum(item['count'] for item in monthly_stats)

        # Prepare serializable data for charts (list of [label, count])
        daily_chart_data = list(daily_stats)
        weekly_chart_data = list(weekly_stats)
        monthly_chart_data = list(monthly_stats)
        
        # User activity summary (exclude 'devin' user)
        user_daily = UserActivity.objects.filter(
            timestamp__date=today
        ).exclude(user__username='devin').values('user__username').annotate(count=Count('id')).order_by('-count')[:10]
        
        user_weekly = UserActivity.objects.filter(
            timestamp__date__gte=week_start
        ).exclude(user__username='devin').values('user__username').annotate(count=Count('id')).order_by('-count')[:10]
        
        user_monthly = UserActivity.objects.filter(
            timestamp__date__gte=month_start
        ).exclude(user__username='devin').values('user__username').annotate(count=Count('id')).order_by('-count')[:10]
        
        extra_context = extra_context or {}
        extra_context.update({
            'daily_stats': daily_stats,
            'weekly_stats': weekly_stats,
            'monthly_stats': monthly_stats,
            'daily_total': daily_total,
            'weekly_total': weekly_total,
            'monthly_total': monthly_total,
            'daily_chart_data': daily_chart_data,
            'weekly_chart_data': weekly_chart_data,
            'monthly_chart_data': monthly_chart_data,
            'user_daily': user_daily,
            'user_weekly': user_weekly,
            'user_monthly': user_monthly,
            'today': today,
            'week_start': week_start,
            'month_start': month_start,
        })
        
        return super().changelist_view(request, extra_context=extra_context)

@admin.register(UserStats)
class UserStatsAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_logins', 'total_page_views', 'total_session_time_display', 'last_login_ip', 'last_activity_date')
    readonly_fields = ('user', 'total_logins', 'total_page_views', 'total_session_time_display', 'last_login_ip', 'last_activity_date', 'created_at', 'updated_at')
    search_fields = ('user__username', 'last_login_ip')
    list_filter = ('last_activity_date', 'created_at')
    
    def total_session_time_display(self, obj):
        return str(obj.total_session_time).split('.')[0]  # Remove microseconds
    total_session_time_display.short_description = 'Total Session Time'

class CustomUserForm(BaseUserChangeForm):
    """Custom form that filters user_permissions to only show RD1 Web App permissions"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter user_permissions to only show RD1 Web App functional permissions
        # Exclude Django's auto-generated CRUD permissions (add_, change_, delete_, view_)
        if 'user_permissions' in self.fields:
            # Only show permissions that start with 'can_' (our custom RD1 permissions)
            # Exclude the old singular DHCP permission (it was renamed to plural)
            rd1_permissions = Permission.objects.filter(
                content_type__app_label='pxe',
                codename__startswith='can_'
            ).exclude(
                codename='can_access_rma_dhcp_lease'  # Old singular version, exclude it
            ).select_related('content_type')
            
            # Define custom ordering: Default permissions first, then admin-only permissions
            default_perms_order = [
                'can_use_dashboard',
                'can_use_system_management',
                'can_use_tools',
                'can_view_rma_logs',
            ]
            admin_perms_order = [
                'can_access_rma_pxe',
                'can_access_rma_dhcp_leases',
                'can_access_rma_testing_db',
                'can_force_unlink_golden',
            ]
            
            # Create ordering map
            ordering_map = {codename: idx for idx, codename in enumerate(default_perms_order + admin_perms_order)}
            
            # Sort permissions by custom order
            sorted_perms = sorted(
                rd1_permissions,
                key=lambda p: ordering_map.get(p.codename, 999)
            )
            
            # Set the queryset to our sorted permissions
            # Django's filter_horizontal will preserve the order of the queryset
            perm_ids = [p.id for p in sorted_perms]
            
            # Use Case/When to maintain custom sort order in the queryset
            preserved_order = Case(
                *[When(pk=pk, then=pos) for pos, pk in enumerate(perm_ids)],
                output_field=IntegerField()
            )
            
            self.fields['user_permissions'].queryset = Permission.objects.filter(
                id__in=perm_ids
            ).order_by(preserved_order)
            
            # Improve the label to be more descriptive
            self.fields['user_permissions'].label = 'RD1 Web App Permissions'
            self.fields['user_permissions'].help_text = (
                'Select permissions for this user. '
                'Default permissions (Dashboard, System Management, Tools, RMA Logs) are auto-granted to new users. '
                'Admin-only permissions (RMA PXE, DHCP Leases, Testing DB, Force Unlink) require manual assignment.'
            )

# Extend the default User admin to include activity tracking
class UserAdmin(BaseUserAdmin):
    """Custom User admin with paginated sessions and activities"""
    
    form = CustomUserForm
    change_form_template = 'admin/auth/user/change_form.html'
    readonly_fields = ('last_login', 'date_joined')
    filter_horizontal = ('user_permissions',)
    
    def get_fieldsets(self, request, obj=None):
        """Override fieldsets to clean up permissions and make dates readonly"""
        if not obj:
            return self.add_fieldsets
        
        # Customize the fieldsets for existing users
        return (
            (None, {'fields': ('username', 'password')}),
            ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
            ('Permissions', {
                'fields': ('is_active', 'is_staff', 'is_superuser', 'user_permissions'),
                'description': '''
                <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0;">
                    <p><strong>RD1 Web App Permissions:</strong></p>
                    <p>Use the dual-listbox below to grant RD1 Web App permissions to this user.</p>
                    <p><strong>✅ Default Permissions (Auto-granted to all users):</strong><br/>
                    Dashboard, System Management, Tools, RMA Logs</p>
                    <p><strong>🔒 Admin-Only Permissions (Manual):</strong><br/>
                    RMA PXE Access, RMA DHCP Leases, RMA Testing DB, Force Unlink Golden</p>
                </div>
                '''
            }),
            ('Important dates', {
                'fields': ('last_login', 'date_joined'),
            }),
        )
    
    def change_view(self, request, object_id, form_url='', extra_context=None):
        """Override change_view to add paginated sessions and activities"""
        extra_context = extra_context or {}
        
        # Get the user object
        try:
            user = User.objects.get(pk=object_id)
        except User.DoesNotExist:
            return super().change_view(request, object_id, form_url, extra_context)
        
        # Pagination for sessions (10 per page)
        sessions_page = request.GET.get('sessions_page', 1)
        try:
            sessions_page = int(sessions_page)
        except (ValueError, TypeError):
            sessions_page = 1
        
        sessions_per_page = 10
        sessions_queryset = UserSession.objects.filter(user=user).order_by('-login_time')
        sessions_total = sessions_queryset.count()
        sessions_start = (sessions_page - 1) * sessions_per_page
        sessions_end = sessions_start + sessions_per_page
        sessions = sessions_queryset[sessions_start:sessions_end]
        
        # Calculate pagination info for sessions
        sessions_total_pages = (sessions_total + sessions_per_page - 1) // sessions_per_page
        sessions_has_previous = sessions_page > 1
        sessions_has_next = sessions_page < sessions_total_pages
        sessions_previous_page = sessions_page - 1 if sessions_has_previous else None
        sessions_next_page = sessions_page + 1 if sessions_has_next else None
        
        # Pagination for activities (10 per page)
        activities_page = request.GET.get('activities_page', 1)
        try:
            activities_page = int(activities_page)
        except (ValueError, TypeError):
            activities_page = 1
        
        activities_per_page = 10
        activities_queryset = UserActivity.objects.filter(user=user).order_by('-timestamp')
        activities_total = activities_queryset.count()
        activities_start = (activities_page - 1) * activities_per_page
        activities_end = activities_start + activities_per_page
        activities = activities_queryset[activities_start:activities_end]
        
        # Calculate pagination info for activities
        activities_total_pages = (activities_total + activities_per_page - 1) // activities_per_page
        activities_has_previous = activities_page > 1
        activities_has_next = activities_page < activities_total_pages
        activities_previous_page = activities_page - 1 if activities_has_previous else None
        activities_next_page = activities_page + 1 if activities_has_next else None
        
        # Add to context
        extra_context.update({
            'user_sessions': sessions,
            'sessions_page': sessions_page,
            'sessions_total': sessions_total,
            'sessions_total_pages': sessions_total_pages,
            'sessions_has_previous': sessions_has_previous,
            'sessions_has_next': sessions_has_next,
            'sessions_previous_page': sessions_previous_page,
            'sessions_next_page': sessions_next_page,
            'user_activities': activities,
            'activities_page': activities_page,
            'activities_total': activities_total,
            'activities_total_pages': activities_total_pages,
            'activities_has_previous': activities_has_previous,
            'activities_has_next': activities_has_next,
            'activities_previous_page': activities_previous_page,
            'activities_next_page': activities_next_page,
        })
        
        return super().change_view(request, object_id, form_url, extra_context)

# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
