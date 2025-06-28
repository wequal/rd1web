from django.contrib import admin
from .models import PxeEntry, ArpScanResult

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