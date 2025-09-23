from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User, Permission
from django.contrib.contenttypes.models import ContentType
from .models import PxeEntry
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=User)
def assign_default_permissions(sender, instance, created, **kwargs):
    """
    Automatically assign default permissions to new users.
    This ensures new users have access to basic features while
    admin-only features (RMA PXE, RMA Testing DB) require manual approval.
    """
    if created:  # Only for newly created users
        try:
            # Get the content type for PxeEntry model (where our permissions are defined)
            content_type = ContentType.objects.get_for_model(PxeEntry)
            
            # Define default permissions that should be auto-granted
            default_permissions = [
                'can_use_dashboard',
                'can_use_system_management', 
                'can_use_tools',
                'can_view_rma_logs',
            ]
            
            # Grant default permissions to the new user
            for perm_codename in default_permissions:
                try:
                    permission = Permission.objects.get(
                        content_type=content_type,
                        codename=perm_codename
                    )
                    instance.user_permissions.add(permission)
                    logger.info(f"Granted permission '{perm_codename}' to new user '{instance.username}'")
                except Permission.DoesNotExist:
                    logger.warning(f"Permission '{perm_codename}' not found for user '{instance.username}'")
            
            logger.info(f"Successfully assigned default permissions to new user: {instance.username}")
            
        except Exception as e:
            logger.error(f"Error assigning permissions to user '{instance.username}': {e}")
