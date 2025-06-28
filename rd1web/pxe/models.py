from django.db import models

# Create your models here.

class PxeEntry(models.Model):
    mac = models.CharField(max_length=32,unique=True)
    parameters = models.TextField()
    image= models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.mac


class ArpScanResult(models.Model):
    ip_address = models.GenericIPAddressField(unique=True)
    mac_address = models.CharField(max_length=18)
    hostname = models.CharField(max_length=255, blank=True, null=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    subnet_source = models.CharField(max_length=50, default='local', help_text='Source subnet: local, remote, etc.')
    scan_interface = models.CharField(max_length=20, default='eno1', help_text='Network interface used for scanning')
    
    class Meta:
        ordering = ['subnet_source', 'ip_address']
    
    def __str__(self):
        return f"{self.ip_address} ({self.mac_address}) [{self.subnet_source}]"