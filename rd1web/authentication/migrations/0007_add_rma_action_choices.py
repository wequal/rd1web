# Generated manually to add RMA-related action choices to UserActivity
# Run: python manage.py migrate authentication

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0006_rename_auth_useractivity_user_timestamp_idx_authenticat_user_id_6e9168_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='useractivity',
            name='action',
            field=models.CharField(
                choices=[
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
                    ('rma_pxe', 'RMA PXE Configuration'),
                    ('rma_log_view', 'RMA Log View'),
                    ('rma_file_view', 'RMA File View'),
                    ('mac_ip_view', 'MAC-IP Scan View'),
                ], 
                max_length=20
            ),
        ),
    ]
