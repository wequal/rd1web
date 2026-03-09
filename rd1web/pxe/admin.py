from django.contrib import admin
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from .models import PxeEntry, ArpScanResult, RmaTestingDb, FirmwareFile


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
    
    list_display = ('bmc_mac', 'bmc_ip', 'bmc_password_short', 'lan0_mac', 'lan1_mac', 'golden_number', 'is_golden', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('bmc_mac', 'bmc_ip', 'bmc_password', 'lan0_mac', 'lan1_mac', 'golden_number')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('bmc_mac',)
    
    fieldsets = (
        ('BMC Configuration', {
            'fields': ('bmc_mac', 'bmc_ip', 'bmc_password')
        }),
        ('Network Configuration', {
            'fields': ('lan0_mac', 'lan1_mac', 'golden_number', 'is_golden')
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


@admin.register(FirmwareFile)
class FirmwareFileAdmin(admin.ModelAdmin):
    """Admin interface for Firmware Inventory"""
    
    list_display = ('product_type', 'eco_number', 'file_type', 'filename', 'file_size_display', 'uploaded_by', 'uploaded_at')
    list_filter = ('product_type', 'file_type', 'uploaded_at')
    search_fields = ('product_type', 'eco_number', 'file_type', 'filename')
    readonly_fields = ('uploaded_at', 'updated_at', 'file_size')
    ordering = ('-uploaded_at',)
    
    fieldsets = (
        ('Firmware Information', {
            'fields': ('product_type', 'eco_number', 'file_type')
        }),
        ('File Details', {
            'fields': ('filename', 'file_path', 'file_size')
        }),
        ('Tracking', {
            'fields': ('uploaded_by', 'uploaded_at', 'updated_at')
        })
    )
    
    def file_size_display(self, obj):
        """Display human-readable file size"""
        return obj.get_file_size_display()
    file_size_display.short_description = "File Size"
    
    def has_view_permission(self, request, obj=None):
        """Only superusers can view Firmware Files in admin"""
        return request.user.is_superuser
    
    def has_add_permission(self, request):
        """Only superusers can add Firmware Files in admin"""
        return request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        """Only superusers can modify Firmware Files in admin"""
        return request.user.is_superuser
    
    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete Firmware Files in admin"""
        return request.user.is_superuser


# Create a simpler User admin that doesn't cause TooManyFieldsSent error
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.admin import SimpleListFilter
from django import forms

class RD1PermissionFilter(SimpleListFilter):
    """Filter users by RD1 Web App permissions"""
    title = 'RD1 Web App Access'
    parameter_name = 'rd1_access'

    def lookups(self, request, model_admin):
        return (
            ('rma_pxe', 'Has RMA PXE Access'),
            ('rma_testing_db', 'Has RMA Testing DB Access'),
            ('default_only', 'Default Permissions Only'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'rma_pxe':
            return queryset.filter(user_permissions__codename='can_access_rma_pxe').distinct()
        elif self.value() == 'rma_testing_db':
            return queryset.filter(user_permissions__codename='can_access_rma_testing_db').distinct()
        elif self.value() == 'default_only':
            # Users who don't have admin-only permissions
            return queryset.exclude(
                user_permissions__codename__in=['can_access_rma_pxe', 'can_access_rma_testing_db']
            ).distinct()

class CustomUserForm(forms.ModelForm):
    """Custom form that only shows essential permissions to prevent TooManyFieldsSent error"""
    
    # Create custom fields for RD1 permissions
    rma_pxe_access = forms.BooleanField(
        required=False,
        label='RMA PXE Access (SXM GPU TEST)',
        help_text='Grant access to RMA PXE management features'
    )
    rma_testing_db_access = forms.BooleanField(
        required=False,
        label='RMA Testing DB Access',
        help_text='Grant access to RMA Testing Database'
    )
    firmware_inventory_access = forms.BooleanField(
        required=False,
        label='Firmware Inventory Access',
        help_text='Grant access to Firmware Inventory management'
    )
    
    class Meta:
        model = User
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Remove the problematic user_permissions field that causes TooManyFieldsSent
        if 'user_permissions' in self.fields:
            del self.fields['user_permissions']
        
        # If editing an existing user, populate the custom fields
        if self.instance.pk:
            try:
                self.fields['rma_pxe_access'].initial = self.instance.has_perm('pxe.can_access_rma_pxe')
                self.fields['rma_testing_db_access'].initial = self.instance.has_perm('pxe.can_access_rma_testing_db')
                self.fields['firmware_inventory_access'].initial = self.instance.has_perm('pxe.can_access_firmware_inventory')
            except Exception:
                pass
    
    def save(self, commit=True):
        user = super().save(commit=commit)
        
        if commit:
            # Handle RMA PXE permission
            try:
                rma_pxe_perm = Permission.objects.get(
                    content_type__app_label='pxe',
                    codename='can_access_rma_pxe'
                )
                if self.cleaned_data.get('rma_pxe_access'):
                    user.user_permissions.add(rma_pxe_perm)
                else:
                    user.user_permissions.remove(rma_pxe_perm)
            except Permission.DoesNotExist:
                pass
            
            # Handle RMA Testing DB permission
            try:
                rma_testing_db_perm = Permission.objects.get(
                    content_type__app_label='pxe',
                    codename='can_access_rma_testing_db'
                )
                if self.cleaned_data.get('rma_testing_db_access'):
                    user.user_permissions.add(rma_testing_db_perm)
                else:
                    user.user_permissions.remove(rma_testing_db_perm)
            except Permission.DoesNotExist:
                pass
            
            # Handle Firmware Inventory permission
            try:
                firmware_inventory_perm = Permission.objects.get(
                    content_type__app_label='pxe',
                    codename='can_access_firmware_inventory'
                )
                if self.cleaned_data.get('firmware_inventory_access'):
                    user.user_permissions.add(firmware_inventory_perm)
                else:
                    user.user_permissions.remove(firmware_inventory_perm)
            except Permission.DoesNotExist:
                pass
        
        return user

class CustomUserAdmin(BaseUserAdmin):
    """Enhanced User admin with RD1 Web App permission management"""
    
    form = CustomUserForm
    list_filter = BaseUserAdmin.list_filter + (RD1PermissionFilter,)
    
    def get_fieldsets(self, request, obj=None):
        """Use standard fieldsets with custom RD1 permission fields"""
        fieldsets = list(super().get_fieldsets(request, obj))
        
        if obj and request.user.is_superuser:
            # Replace the Permissions section with our custom RD1 permissions
            new_fieldsets = []
            for name, options in fieldsets:
                if name == 'Permissions':
                    # Custom permissions section
                    new_fieldsets.append((
                        'Permissions', {
                            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups')
                        }
                    ))
                    # Add RD1 Web App permissions section
                    new_fieldsets.append((
                        'RD1 Web App Permissions', {
                            'fields': ('rma_pxe_access', 'rma_testing_db_access', 'firmware_inventory_access'),
                            'description': '''
                            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0;">
                                <h4>RD1 Web Application Access Control:</h4>
                                
                                <p><strong>✅ Default Access (Automatic):</strong><br/>
                                All users automatically have: Dashboard, System Management, Tools, RMA Logs</p>
                                
                                <p><strong>🔒 Admin-Only Access (Manual):</strong><br/>
                                Use the checkboxes below to grant special administrative access.</p>
                            </div>
                            '''
                        }
                    ))
                else:
                    new_fieldsets.append((name, options))
            
            return new_fieldsets
        
        return fieldsets

# Note: User admin registration moved to authentication/admin.py to avoid conflicts