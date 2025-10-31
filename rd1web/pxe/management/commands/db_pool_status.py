# File: rd1web/pxe/management/commands/db_pool_status.py

from django.core.management.base import BaseCommand
from django.db import connection
import datetime

class Command(BaseCommand):
    help = 'Monitor PostgreSQL connection pool status'

    def add_arguments(self, parser):
        parser.add_argument(
            '--watch',
            action='store_true',
            help='Continuously monitor (refresh every 5 seconds)',
        )

    def handle(self, *args, **options):
        import time
        
        try:
            while True:
                self.show_pool_status()
                
                if not options['watch']:
                    break
                    
                time.sleep(5)
                self.stdout.write('\n' + '='*80 + '\n')
                
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('\n\nMonitoring stopped.'))

    def show_pool_status(self):
        with connection.cursor() as cursor:
            # Connection count by state
            cursor.execute("""
                SELECT 
                    state,
                    count(*) as count,
                    round(avg(EXTRACT(EPOCH FROM (now() - state_change))), 2) as avg_seconds_in_state
                FROM pg_stat_activity 
                WHERE datname = %s
                GROUP BY state
                ORDER BY count DESC;
            """, [connection.settings_dict['NAME']])
            
            self.stdout.write(self.style.SUCCESS(f'\n📊 Connection Pool Status - {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'))
            self.stdout.write('-' * 80)
            
            results = cursor.fetchall()
            if results:
                self.stdout.write(f"{'State':<20} {'Count':<10} {'Avg Duration (s)':<20}")
                self.stdout.write('-' * 80)
                for state, count, avg_duration in results:
                    self.stdout.write(f"{state or 'NULL':<20} {count:<10} {avg_duration or 0:<20}")
            
            # Total connections vs limit
            cursor.execute("""
                SELECT 
                    (SELECT count(*) FROM pg_stat_activity WHERE datname = %s) as current,
                    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_conn,
                    (SELECT setting::int FROM pg_settings WHERE name = 'superuser_reserved_connections') as reserved
            """, [connection.settings_dict['NAME']])
            
            current, max_conn, reserved = cursor.fetchone()
            available = max_conn - reserved
            usage_percent = (current / available * 100) if available > 0 else 0
            
            self.stdout.write('\n📈 Pool Capacity:')
            self.stdout.write(f"   Current: {current} / {available} available ({usage_percent:.1f}% used)")
            self.stdout.write(f"   Max Total: {max_conn} ({reserved} reserved for superuser)")
            
            # Warning thresholds
            if usage_percent > 80:
                self.stdout.write(self.style.ERROR(f'\n⚠️  WARNING: Connection pool usage is HIGH ({usage_percent:.1f}%)'))
            elif usage_percent > 60:
                self.stdout.write(self.style.WARNING(f'\n⚡ NOTICE: Connection pool usage is moderate ({usage_percent:.1f}%)'))
            
            # Long-running queries
            cursor.execute("""
                SELECT 
                    pid,
                    usename,
                    application_name,
                    state,
                    EXTRACT(EPOCH FROM (now() - query_start)) as duration_seconds,
                    left(query, 100) as query_preview
                FROM pg_stat_activity 
                WHERE datname = %s 
                  AND state != 'idle'
                  AND query_start < now() - interval '10 seconds'
                ORDER BY duration_seconds DESC
                LIMIT 10;
            """, [connection.settings_dict['NAME']])
            
            long_queries = cursor.fetchall()
            if long_queries:
                self.stdout.write('\n⏱️  Long-Running Queries (>10s):')
                self.stdout.write('-' * 80)
                for pid, user, app, state, duration, query in long_queries:
                    self.stdout.write(f"   PID {pid}: {duration:.1f}s - {state}")
                    self.stdout.write(f"      {query[:80]}...")