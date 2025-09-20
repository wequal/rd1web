from django.contrib import admin
from .models import PxeEntry, ArpScanResult, RmaTestingDb

# Register your models here.
admin.site.register(PxeEntry)


@admin.register(ArpScanResult)
class ArpScanResultAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'mac_address', 'hostname', 'is_active', 'first_seen', 'last_seen')
    list_filter = ('is_active', 'first_seen', 'last_seen')
    search_fields = ('ip_address', 'mac_address', 'hostname')
    readonly_fields = ('first_seen', 'last_seen')
    ordering = ('ip_address',)
    
    def get_queryset(self, request):
        """Override to show active entries first"""
        qs = super().get_queryset(request)
        return qs.order_by('-is_active', 'ip_address')


@admin.register(RmaTestingDb)
class RmaTestingDbAdmin(admin.ModelAdmin):
    """Admin interface for RMA Testing DB"""
    
    list_display = ('bmc_mac', 'bmc_ip', 'bmc_password_short', 'lan0_mac', 'lan1_mac', 'golden_number', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('bmc_mac', 'bmc_ip', 'bmc_password', 'lan0_mac', 'lan1_mac', 'golden_number')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('bmc_mac',)
    
    fieldsets = (
        ('BMC Configuration', {
            'fields': ('bmc_mac', 'bmc_ip', 'bmc_password')
        }),
        ('Network Configuration', {
            'fields': ('lan0_mac', 'lan1_mac', 'golden_number')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def bmc_password_short(self, obj):
        """Display shortened password for security"""
        if obj.bmc_password:
            return f"{obj.bmc_password[:8]}..."
        return ""
    bmc_password_short.short_description = "BMC Password"
    
    def has_view_permission(self, request, obj=None):
        """Only superusers can view RMA Testing DB in admin"""
        return request.user.is_superuser
    
    def has_add_permission(self, request):
        """Only superusers can add RMA Testing DB entries in admin"""
        return request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        """Only superusers can modify RMA Testing DB entries in admin"""
        return request.user.is_superuser
    
    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete RMA Testing DB entries in admin"""
        return request.user.is_superuser