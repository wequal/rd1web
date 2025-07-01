from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class UserSession(models.Model):
    """Track user login sessions"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_sessions')
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    login_time = models.DateTimeField(default=timezone.now)
    last_activity = models.DateTimeField(default=timezone.now)
    logout_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField()
    
    class Meta:
        ordering = ['-login_time']
        verbose_name = "User Session"
        verbose_name_plural = "User Sessions"
        indexes = [
            models.Index(fields=['session_key', 'user', 'is_active']),  # For session lookups
            models.Index(fields=['user', 'is_active']),  # For user session queries
            models.Index(fields=['last_activity']),  # For activity-based queries
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.login_time.strftime('%Y-%m-%d %H:%M')}"
    
    @property
    def session_duration(self):
        """Calculate session duration"""
        end_time = self.logout_time or timezone.now()
        return end_time - self.login_time
    
    @property
    def is_currently_active(self):
        """Check if session is currently active (within last 30 minutes)"""
        if not self.is_active:
            return False
        return (timezone.now() - self.last_activity).seconds < 1800  # 30 minutes

class UserActivity(models.Model):
    """Track user activities and page visits"""
    ACTION_CHOICES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('page_view', 'Page View'),
        ('pxe_config', 'PXE Configuration'),
        ('system_view', 'System Details View'),
        ('ipmitool_use', 'IPMI Tool Usage'),
        ('log_view', 'Log File View'),
        ('file_view', 'File View'),
        ('kvm_access', 'KVM Access'),
        ('sol_access', 'SOL Access'),
        ('password_change', 'Password Change'),
        ('profile_view', 'Profile View'),
        ('admin_access', 'Admin Panel Access'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    session = models.ForeignKey(UserSession, on_delete=models.CASCADE, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    description = models.TextField(blank=True)
    url_path = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(default=timezone.now)
    success = models.BooleanField()
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = "User Activity"
        verbose_name_plural = "User Activities"
        indexes = [
            models.Index(fields=['user', 'timestamp']),  # For user activity queries
            models.Index(fields=['action', 'timestamp']),  # For action-based queries
            models.Index(fields=['timestamp']),  # For time-based queries
            models.Index(fields=['user', 'action']),  # For user-action queries
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.get_action_display()} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"

class UserStats(models.Model):
    """Aggregate user statistics for performance"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='stats')
    total_logins = models.PositiveIntegerField(default=0)
    total_page_views = models.PositiveIntegerField(default=0)
    total_session_time = models.DurationField(default=timezone.timedelta)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_activity_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "User Statistics"
        verbose_name_plural = "User Statistics"
        indexes = [
            models.Index(fields=['user']),  # For user stats lookups
            models.Index(fields=['last_activity_date']),  # For activity-based queries
        ]
    
    def __str__(self):
        return f"{self.user.username} - Stats"
