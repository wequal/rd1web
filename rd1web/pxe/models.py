from django.db import models
from django.core.exceptions import ValidationError
import re

# Create your models here.

class PxeEntry(models.Model):
    mac = models.CharField(max_length=32,unique=True)
    parameters = models.TextField()
    image= models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = [
            # Default permissions (auto-granted to new users)
            ('can_use_dashboard', 'Can use dashboard and overview'),
            ('can_use_system_management', 'Can use system management features'),
            ('can_use_tools', 'Can use tools and utilities'),
            ('can_view_rma_logs', 'Can view RMA logs'),
            # Admin-only permissions (require manual approval)
            ('can_access_rma_pxe', 'Can access RMA PXE management'),
        ]

    def __str__(self):
        return self.mac


class ArpScanResult(models.Model):
    ip_address = models.GenericIPAddressField()
    mac_address = models.CharField(max_length=18)
    hostname = models.CharField(max_length=255, blank=True, null=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    subnet_source = models.CharField(max_length=50, default='local', help_text='Source subnet: local, remote, etc.')
    scan_interface = models.CharField(max_length=20, default='eno1', help_text='Network interface used for scanning')
    
    class Meta:
        ordering = ['subnet_source', 'ip_address']
        unique_together = ('mac_address', 'subnet_source')
    
    def __str__(self):
        return f"{self.ip_address} ({self.mac_address}) [{self.subnet_source}]"


def validate_mac_address(value):
    """Validate MAC address format (xx:xx:xx:xx:xx:xx)"""
    if not value:
        return
    
    # MAC address pattern: xx:xx:xx:xx:xx:xx (case insensitive)
    mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
    
    if not mac_pattern.match(value):
        raise ValidationError(
            'Invalid MAC address format. Use format: xx:xx:xx:xx:xx:xx or xx-xx-xx-xx-xx-xx'
        )


class RmaTestingDb(models.Model):
    """RMA Testing Database model for storing BMC and network configuration"""
    
    bmc_mac = models.CharField(
        max_length=17, 
        unique=True,
        validators=[validate_mac_address],
        help_text='BMC MAC address (format: xx:xx:xx:xx:xx:xx)',
        verbose_name='BMC MAC Address'
    )
    bmc_ip = models.GenericIPAddressField(
        help_text='BMC IP address',
        verbose_name='BMC IP Address'
    )
    bmc_password = models.CharField(
        max_length=255,
        help_text='BMC unique password',
        verbose_name='BMC Password'
    )
    lan0_mac = models.CharField(
        max_length=17,
        validators=[validate_mac_address],
        help_text='LAN0 MAC address (format: xx:xx:xx:xx:xx:xx)',
        verbose_name='LAN0 MAC Address'
    )
    lan1_mac = models.CharField(
        max_length=17,
        validators=[validate_mac_address],
        help_text='LAN1 MAC address (format: xx:xx:xx:xx:xx:xx)',
        verbose_name='LAN1 MAC Address'
    )
    golden_number = models.CharField(
        max_length=100,
        default='',
        blank=True,
        help_text='Golden Number identifier',
        verbose_name='Golden Number'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['bmc_mac']
        verbose_name = 'RMA Testing DB Entry'
        verbose_name_plural = 'RMA Testing DB Entries'
        permissions = [
            ('can_access_rma_testing_db', 'Can access RMA Testing DB'),
        ]
    
    def clean(self):
        """Additional validation for the model"""
        super().clean()
        
        # Normalize MAC addresses to lowercase with colons
        if self.bmc_mac:
            self.bmc_mac = self._normalize_mac(self.bmc_mac)
        if self.lan0_mac:
            self.lan0_mac = self._normalize_mac(self.lan0_mac)
        if self.lan1_mac:
            self.lan1_mac = self._normalize_mac(self.lan1_mac)
            
        # Check for duplicate MAC addresses across different fields
        macs = [self.bmc_mac, self.lan0_mac, self.lan1_mac]
        if len(set(macs)) != len(macs):
            raise ValidationError('MAC addresses must be unique across BMC, LAN0, and LAN1')
    
    def _normalize_mac(self, mac):
        """Normalize MAC address to lowercase with colons"""
        if not mac:
            return mac
        # Remove any existing separators and normalize
        clean_mac = re.sub(r'[:-]', '', mac.upper())
        # Add colons back
        return ':'.join(clean_mac[i:i+2] for i in range(0, 12, 2)).lower()
    
    def save(self, *args, **kwargs):
        """Override save to ensure clean() is called"""
        self.clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"RMA Entry: {self.bmc_mac} ({self.bmc_ip})"