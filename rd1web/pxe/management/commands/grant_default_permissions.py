from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Permission
from django.contrib.contenttypes.models import ContentType
from pxe.models import PxeEntry


class Command(BaseCommand):
    help = 'Grant default permissions to all existing users'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
    
    def handle(self, *args, **options):
        """Grant default permissions to all existing users"""
        
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Get the content type for PxeEntry model (where our permissions are defined)
        try:
            content_type = ContentType.objects.get_for_model(PxeEntry)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error getting content type: {e}'))
            return
        
        # Define default permissions that should be auto-granted
        default_permissions = [
            'can_use_dashboard',
            'can_use_system_management', 
            'can_use_tools',
            'can_view_rma_logs',
        ]
        
        self.stdout.write(f'Processing {User.objects.count()} users...')
        
        # Grant default permissions to all existing users
        users_updated = 0
        permissions_granted = 0
        
        for user in User.objects.all():
            user_permissions_granted = 0
            
            for perm_codename in default_permissions:
                try:
                    permission = Permission.objects.get(
                        content_type=content_type,
                        codename=perm_codename
                    )
                    
                    # Check if user already has this permission
                    if not user.has_perm(f'pxe.{perm_codename}'):
                        if not dry_run:
                            user.user_permissions.add(permission)
                        
                        self.stdout.write(
                            f'{"[DRY RUN] " if dry_run else ""}Granted permission '
                            f'"{perm_codename}" to user "{user.username}"'
                        )
                        user_permissions_granted += 1
                        permissions_granted += 1
                    else:
                        self.stdout.write(
                            f'User "{user.username}" already has permission "{perm_codename}"'
                        )
                        
                except Permission.DoesNotExist:
                    self.stdout.write(
                        self.style.ERROR(f'Permission "{perm_codename}" not found')
                    )
            
            if user_permissions_granted > 0:
                users_updated += 1
        
        # Summary
        self.stdout.write('')
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'DRY RUN COMPLETE: Would grant {permissions_granted} permissions to {users_updated} users'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully granted {permissions_granted} permissions to {users_updated} users'
                )
            )
            
        self.stdout.write('')
        self.stdout.write('Permission Summary:')
        self.stdout.write('  Default Permissions (auto-granted):')
        for perm in default_permissions:
            self.stdout.write(f'    - {perm}')
        self.stdout.write('')
        self.stdout.write('  Admin-Only Permissions (manual approval required):')
        self.stdout.write('    - can_access_rma_pxe (SXM GPU TEST)')
        self.stdout.write('    - can_access_rma_testing_db (RMA Testing DB)')
