from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
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
            ('can_view_rma_statistics', 'Can view RMA statistics'),
            # Admin-only permissions (require manual approval)
            ('can_access_rma_pxe', 'Can access RMA PXE management'),
            ('can_access_rma_dhcp_leases', 'Can access RMA DHCP Leases'),
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
    linked_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_golden_numbers',
        help_text='User currently linked to this golden number',
        verbose_name='Linked User'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_tester = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        help_text='Last user who was linked to this golden number',
        verbose_name='Last Tester'
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['bmc_mac']
        verbose_name = 'RMA Testing DB Entry'
        verbose_name_plural = 'RMA Testing DB Entries'
        permissions = [
            ('can_access_rma_testing_db', 'Can access RMA Testing DB'),
            ('can_force_unlink_golden', 'Can force unlink any golden number'),
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


class RmaTestStatistic(models.Model):
    """
    RMA Test Statistics model for tracking GPU test failures
    Stores parsed test results from test_results.log files
    """
    directory_name = models.CharField(
        max_length=255,
        unique=True,
        help_text='RMA directory name (e.g., 1660224656070_XD250311087)',
        verbose_name='Directory Name'
    )
    base_sn = models.CharField(
        max_length=100,
        help_text='Base serial number parsed from directory name',
        verbose_name='Base SN'
    )
    rma_number = models.CharField(
        max_length=100,
        help_text='RMA number parsed from directory name',
        verbose_name='RMA Number'
    )
    gpu_model = models.CharField(
        max_length=100,
        default='Unknown',
        help_text='GPU model from sys_info.txt (e.g., H100, A100)',
        verbose_name='GPU Model'
    )
    test_date = models.DateTimeField(
        help_text='Directory modification time for time grouping',
        verbose_name='Test Date',
        db_index=True
    )
    test_results = models.JSONField(
        default=dict,
        help_text='Test results: {gpu_detection: pass/fail, ecc_error: pass/fail, ...}',
        verbose_name='Test Results'
    )
    file_mtime = models.FloatField(
        help_text='test_results.log file modification time for change detection',
        verbose_name='File Mtime'
    )
    last_scanned = models.DateTimeField(
        auto_now=True,
        help_text='When this directory was last scanned',
        verbose_name='Last Scanned'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-test_date']
        verbose_name = 'RMA Test Statistic'
        verbose_name_plural = 'RMA Test Statistics'
        indexes = [
            models.Index(fields=['test_date']),
            models.Index(fields=['gpu_model']),
            models.Index(fields=['test_date', 'gpu_model']),
        ]
    
    def __str__(self):
        return f"RMA Stats: {self.directory_name} ({self.gpu_model})"
    
    def has_any_failure(self):
        """Check if any test failed"""
        if not self.test_results:
            return False
        return any(result == 'fail' for result in self.test_results.values())
    
    def get_failure_count(self):
        """Count number of failed tests"""
        if not self.test_results:
            return 0
        return sum(1 for result in self.test_results.values() if result == 'fail')