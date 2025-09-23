from django.contrib import admin
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from .models import PxeEntry, ArpScanResult, RmaTestingDb


@admin.register(PxeEntry)
class PxeEntryAdmin(admin.ModelAdmin):
    """Enhanced admin interface for PXE entries"""
    list_display = ('mac', 'image', 'created_at')
    search_fields = ('mac', 'image', 'parameters')
    list_filter = ('image', 'created_at')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


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


# Enhance the default User admin interface for easier permission management
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

class CustomUserAdmin(BaseUserAdmin):
    """Enhanced User admin with easier permission management"""
    
    def save_model(self, request, obj, form, change):
        """Custom save logic for user permissions"""
        super().save_model(request, obj, form, change)
        
        # If this is a new user, the signal will handle default permissions
        # If it's an existing user being modified, we don't need to do anything special here
        pass
    
    def get_fieldsets(self, request, obj=None):
        """Enhanced fieldsets for better permission management"""
        fieldsets = super().get_fieldsets(request, obj)
        
        if obj and request.user.is_superuser:
            # Add a custom section showing app-specific permissions
            app_permissions_section = (
                'RD1 Web Application Permissions', {
                    'fields': (),
                    'description': '''
                    <strong>Default Permissions (Auto-granted to new users):</strong><br/>
                    • can_use_dashboard - Access to overview and basic features<br/>
                    • can_use_system_management - System Overview, PXE Boot Manager<br/>
                    • can_use_tools - IPMI Tool, MAC to IP<br/>
                    • can_view_rma_logs - RMA Logs (read-only)<br/><br/>
                    
                    <strong>Admin-Only Permissions (Manual approval required):</strong><br/>
                    • can_access_rma_pxe - RMA GPU TEST (RMA PXE functionality)<br/>
                    • can_access_rma_testing_db - RMA Testing DB<br/><br/>
                    
                    Use the "User permissions" section below to grant admin-only permissions.
                    '''
                }
            )
            fieldsets = fieldsets + (app_permissions_section,)
        
        return fieldsets

# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)