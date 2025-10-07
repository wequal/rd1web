from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
import zoneinfo
from .models import UserSession, UserActivity, UserStats

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
    list_filter = ('action', 'success', 'timestamp', 'user')
    search_fields = ('user__username', 'description', 'url_path', 'ip_address')
    date_hierarchy = 'timestamp'
    readonly_fields = ('user', 'session', 'action', 'description', 'url_path', 'ip_address', 'user_agent', 'timestamp', 'success')
    
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

# Extend the default User admin to include activity tracking
class UserAdmin(BaseUserAdmin):
    inlines = [UserSessionInline, UserActivityInline]
    
    def get_inline_instances(self, request, obj=None):
        return [inline(self.model, self.admin_site) for inline in self.inlines] if obj else []

# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
