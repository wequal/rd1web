# Generated migration to update firmware inventory paths
# Updates file_path from /srv/firmwareinventory to /srv/share/firmwareinventory

from django.db import migrations


def update_firmware_paths(apps, schema_editor):
    """Update FirmwareFile file_path values from /srv/firmwareinventory to /srv/share/firmwareinventory"""
    FirmwareFile = apps.get_model('pxe', 'FirmwareFile')
    
    # Find all records with old path
    old_path_prefix = '/srv/firmwareinventory'
    new_path_prefix = '/srv/share/firmwareinventory'
    
    updated_count = 0
    for firmware_file in FirmwareFile.objects.filter(file_path__startswith=old_path_prefix):
        # Replace the old path prefix with the new one
        firmware_file.file_path = firmware_file.file_path.replace(
            old_path_prefix,
            new_path_prefix,
            1  # Only replace first occurrence
        )
        firmware_file.save(update_fields=['file_path'])
        updated_count += 1
    
    if updated_count > 0:
        print(f"Updated {updated_count} FirmwareFile record(s) with new path prefix")


def reverse_update_firmware_paths(apps, schema_editor):
    """Reverse migration: change paths back from /srv/share/firmwareinventory to /srv/firmwareinventory"""
    FirmwareFile = apps.get_model('pxe', 'FirmwareFile')
    
    old_path_prefix = '/srv/share/firmwareinventory'
    new_path_prefix = '/srv/firmwareinventory'
    
    updated_count = 0
    for firmware_file in FirmwareFile.objects.filter(file_path__startswith=old_path_prefix):
        firmware_file.file_path = firmware_file.file_path.replace(
            old_path_prefix,
            new_path_prefix,
            1
        )
        firmware_file.save(update_fields=['file_path'])
        updated_count += 1
    
    if updated_count > 0:
        print(f"Reverted {updated_count} FirmwareFile record(s) to old path prefix")


class Migration(migrations.Migration):

    dependencies = [
        ('pxe', '0026_alter_rmatestingdb_options'),
    ]

    operations = [
        migrations.RunPython(update_firmware_paths, reverse_update_firmware_paths),
    ]

