# Generated migration for performance optimization indexes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0001_initial'),
    ]

    operations = [
        # Add indexes to UserSession model
        migrations.AddIndex(
            model_name='usersession',
            index=models.Index(fields=['session_key', 'user', 'is_active'], name='auth_usersession_session_user_active_idx'),
        ),
        migrations.AddIndex(
            model_name='usersession',
            index=models.Index(fields=['user', 'is_active'], name='auth_usersession_user_active_idx'),
        ),
        migrations.AddIndex(
            model_name='usersession',
            index=models.Index(fields=['last_activity'], name='auth_usersession_last_activity_idx'),
        ),
        
        # Add indexes to UserActivity model
        migrations.AddIndex(
            model_name='useractivity',
            index=models.Index(fields=['user', 'timestamp'], name='auth_useractivity_user_timestamp_idx'),
        ),
        migrations.AddIndex(
            model_name='useractivity',
            index=models.Index(fields=['action', 'timestamp'], name='auth_useractivity_action_timestamp_idx'),
        ),
        migrations.AddIndex(
            model_name='useractivity',
            index=models.Index(fields=['timestamp'], name='auth_useractivity_timestamp_idx'),
        ),
        migrations.AddIndex(
            model_name='useractivity',
            index=models.Index(fields=['user', 'action'], name='auth_useractivity_user_action_idx'),
        ),
        
        # Add indexes to UserStats model
        migrations.AddIndex(
            model_name='userstats',
            index=models.Index(fields=['user'], name='auth_userstats_user_idx'),
        ),
        migrations.AddIndex(
            model_name='userstats',
            index=models.Index(fields=['last_activity_date'], name='auth_userstats_last_activity_idx'),
        ),
    ] 