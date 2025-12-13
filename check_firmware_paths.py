#!/usr/bin/env python3
"""
Script to check FirmwareFile database records for path issues
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'rd1web'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rd1web.settings')
django.setup()

from pxe.models import FirmwareFile

def main():
    print("=" * 80)
    print("FirmwareFile Database Path Check")
    print("=" * 80)
    
    # Get all records
    total = FirmwareFile.objects.count()
    print(f"\nTotal FirmwareFile records: {total}")
    
    # Check for old paths
    old_paths = FirmwareFile.objects.filter(file_path__startswith='/srv/firmwareinventory')
    old_count = old_paths.count()
    
    # Check for new paths
    new_paths = FirmwareFile.objects.filter(file_path__startswith='/srv/share/firmwareinventory')
    new_count = new_paths.count()
    
    # Check for other paths
    other_paths = FirmwareFile.objects.exclude(
        file_path__startswith='/srv/firmwareinventory'
    ).exclude(
        file_path__startswith='/srv/share/firmwareinventory'
    )
    other_count = other_paths.count()
    
    print(f"\nPath Statistics:")
    print(f"  Records with old path (/srv/firmwareinventory): {old_count}")
    print(f"  Records with new path (/srv/share/firmwareinventory): {new_count}")
    print(f"  Records with other paths: {other_count}")
    
    # Show sample old paths
    if old_count > 0:
        print(f"\n{'=' * 80}")
        print(f"Sample records with OLD paths (showing first 20):")
        print(f"{'=' * 80}")
        print(f"{'ID':<6} {'Product':<12} {'ECO':<15} {'Type':<12} {'File Exists':<12} {'Path'}")
        print("-" * 80)
        for f in old_paths[:20]:
            exists = "YES" if os.path.exists(f.file_path) else "NO"
            print(f"{f.id:<6} {f.product_type:<12} {f.eco_number:<15} {f.file_type:<12} {exists:<12} {f.file_path}")
        
        if old_count > 20:
            print(f"\n... and {old_count - 20} more records with old paths")
    
    # Show sample new paths
    if new_count > 0:
        print(f"\n{'=' * 80}")
        print(f"Sample records with NEW paths (showing first 10):")
        print(f"{'=' * 80}")
        print(f"{'ID':<6} {'Product':<12} {'ECO':<15} {'Type':<12} {'File Exists':<12} {'Path'}")
        print("-" * 80)
        for f in new_paths[:10]:
            exists = "YES" if os.path.exists(f.file_path) else "NO"
            print(f"{f.id:<6} {f.product_type:<12} {f.eco_number:<15} {f.file_type:<12} {exists:<12} {f.file_path}")
    
    # Show other paths if any
    if other_count > 0:
        print(f"\n{'=' * 80}")
        print(f"Records with OTHER paths (showing first 10):")
        print(f"{'=' * 80}")
        print(f"{'ID':<6} {'Product':<12} {'ECO':<15} {'Type':<12} {'File Exists':<12} {'Path'}")
        print("-" * 80)
        for f in other_paths[:10]:
            exists = "YES" if os.path.exists(f.file_path) else "NO"
            print(f"{f.id:<6} {f.product_type:<12} {f.eco_number:<15} {f.file_type:<12} {exists:<12} {f.file_path}")
    
    # Check file existence for old paths
    if old_count > 0:
        print(f"\n{'=' * 80}")
        print("File Existence Check for OLD paths:")
        print(f"{'=' * 80}")
        existing_count = sum(1 for f in old_paths if os.path.exists(f.file_path))
        missing_count = old_count - existing_count
        print(f"  Files that exist at old path: {existing_count}")
        print(f"  Files missing at old path: {missing_count}")
        
        # Check if they exist at new path
        print(f"\nChecking if files exist at NEW path location:")
        migrated_count = 0
        for f in old_paths[:50]:  # Check first 50
            old_path = f.file_path
            new_path = old_path.replace('/srv/firmwareinventory', '/srv/share/firmwareinventory', 1)
            if os.path.exists(new_path):
                migrated_count += 1
        
        if migrated_count > 0:
            print(f"  Found {migrated_count} files that exist at new path location")
    
    print(f"\n{'=' * 80}")
    print("Summary:")
    print(f"{'=' * 80}")
    if old_count > 0:
        print(f"⚠️  WARNING: {old_count} records still have old paths and need migration")
    else:
        print("✓ All records have correct paths")
    
    print(f"\n{'=' * 80}")

if __name__ == '__main__':
    main()

