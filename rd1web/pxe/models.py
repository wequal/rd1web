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
    updated_at = models.DateTimeField(auto_now=True)

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
            ('can_access_rma_general_test', 'Can access RMA General TEST'),
            ('can_view_rma_general_logs', 'Can view RMA General logs'),
            ('can_access_rma_dhcp_leases', 'Can access RMA DHCP Leases'),
            ('can_access_firmware_inventory', 'Can access Firmware Inventory'),
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
    linked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp when the golden number was linked to current user',
        verbose_name='Linked At'
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
            ('can_view_golden_test_setting', 'Can view golden unit test setting'),
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
        db_index=True,
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
        unique_together = [['directory_name', 'file_mtime']]
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


class FirmwareFile(models.Model):
    """
    Firmware Inventory model for tracking uploaded firmware files
    Organizes firmware by product type and ECO number
    """
    PRODUCT_CHOICES = [
        ('H100_AC', 'H100_AC'),
        ('H100_LC', 'H100_LC'),
        ('H200_AC', 'H200_AC'),
        ('H200_LC', 'H200_LC'),
        ('B200_AC', 'B200_AC'),
        ('B200_LC', 'B200_LC'),
        ('B300_AC', 'B300_AC'),
        ('B300_LC', 'B300_LC'),
    ]
    
    FILE_TYPE_CHOICES = [
        ('GPU', 'GPU'),
        ('retimer_0', 'Retimer 0'),
        ('retimer_1', 'Retimer 1'),
        ('retimer_2', 'Retimer 2'),
        ('retimer_3', 'Retimer 3'),
        ('retimer_4', 'Retimer 4'),
        ('retimer_5', 'Retimer 5'),
        ('retimer_6', 'Retimer 6'),
        ('retimer_7', 'Retimer 7'),
    ]
    
    product_type = models.CharField(
        max_length=20,
        choices=PRODUCT_CHOICES,
        help_text='Product type (e.g., H100_AC, B200_LC)',
        verbose_name='Product Type'
    )
    eco_number = models.CharField(
        max_length=100,
        help_text='ECO number (free text)',
        verbose_name='ECO Number'
    )
    file_type = models.CharField(
        max_length=20,
        choices=FILE_TYPE_CHOICES,
        help_text='Firmware file type (GPU or retimer)',
        verbose_name='File Type'
    )
    filename = models.CharField(
        max_length=255,
        help_text='Stored filename',
        verbose_name='Filename'
    )
    original_filename = models.CharField(
        max_length=255,
        help_text='Original uploaded filename',
        verbose_name='Original Filename',
        default='',
        blank=True
    )
    file_path = models.CharField(
        max_length=512,
        help_text='Full path to the firmware file',
        verbose_name='File Path'
    )
    file_size = models.BigIntegerField(
        help_text='File size in bytes',
        verbose_name='File Size'
    )
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_firmware_files',
        help_text='User who uploaded this file',
        verbose_name='Uploaded By'
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        help_text='When this file was uploaded',
        verbose_name='Uploaded At'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text='Last update time',
        verbose_name='Updated At'
    )
    
    class Meta:
        ordering = ['product_type', 'eco_number', 'file_type']
        verbose_name = 'Firmware File'
        verbose_name_plural = 'Firmware Files'
        unique_together = ('product_type', 'eco_number', 'file_type')
        indexes = [
            models.Index(fields=['product_type', 'eco_number']),
            models.Index(fields=['uploaded_by']),
            models.Index(fields=['uploaded_at']),
        ]
    
    def __str__(self):
        return f"{self.product_type}/{self.eco_number}/{self.file_type} - {self.filename}"
    
    def get_file_size_display(self):
        """Return human-readable file size"""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"