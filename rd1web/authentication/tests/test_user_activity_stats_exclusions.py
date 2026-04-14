from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from authentication.admin import USER_ACTIVITY_STATS_EXCLUDED_USERNAMES
from authentication.models import UserActivity


class UserActivityStatsExclusionsTests(TestCase):
    def test_daily_stats_query_excludes_configured_usernames(self):
        User.objects.create_user('devin', 'devin@example.com', 'pw')
        User.objects.create_user('test', 'test@example.com', 'pw')
        alice = User.objects.create_user('alice', 'alice@example.com', 'pw')

        now = timezone.localtime()
        today = now.date()
        for username in ('devin', 'test', 'alice'):
            user = User.objects.get(username=username)
            UserActivity.objects.create(
                user=user,
                action='page_view',
                ip_address='127.0.0.1',
                success=True,
                timestamp=now,
            )

        self.assertIn('devin', USER_ACTIVITY_STATS_EXCLUDED_USERNAMES)
        self.assertIn('test', USER_ACTIVITY_STATS_EXCLUDED_USERNAMES)

        qs = UserActivity.objects.filter(timestamp__date=today).exclude(
            user__username__in=USER_ACTIVITY_STATS_EXCLUDED_USERNAMES
        )
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.get().user, alice)
