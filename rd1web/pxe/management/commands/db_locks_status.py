from django.core.management.base import BaseCommand
from django.db import connection
import datetime

class Command(BaseCommand):
    help = 'Monitor PostgreSQL lock contention and blocking queries'

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
                self.show_locks_status()
                
                if not options['watch']:
                    break
                    
                time.sleep(5)
                self.stdout.write('\n' + '='*80 + '\n')
                
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('\n\nMonitoring stopped.'))

    def show_locks_status(self):
        with connection.cursor() as cursor:
            # Check for blocking locks
            cursor.execute("""
                SELECT 
                    blocked_locks.pid AS blocked_pid,
                    blocked_activity.usename AS blocked_user,
                    blocking_locks.pid AS blocking_pid,
                    blocking_activity.usename AS blocking_user,
                    blocked_activity.query AS blocked_statement,
                    blocking_activity.query AS blocking_statement,
                    blocked_activity.application_name AS blocked_app,
                    blocking_activity.application_name AS blocking_app,
                    EXTRACT(EPOCH FROM (now() - blocked_activity.query_start)) as blocked_duration
                FROM pg_catalog.pg_locks blocked_locks
                JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
                JOIN pg_catalog.pg_locks blocking_locks 
                    ON blocking_locks.locktype = blocked_locks.locktype
                    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
                    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
                    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
                    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
                    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
                    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
                    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
                    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
                    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
                    AND blocking_locks.pid != blocked_locks.pid
                JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
                WHERE NOT blocked_locks.granted;
            """)
            
            self.stdout.write(self.style.SUCCESS(f'\n🔒 Lock Contention Status - {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'))
            self.stdout.write('-' * 80)
            
            blocking_results = cursor.fetchall()
            
            if blocking_results:
                self.stdout.write(self.style.ERROR('\n⚠️  LOCK CONTENTION DETECTED!\n'))
                for row in blocking_results:
                    blocked_pid, blocked_user, blocking_pid, blocking_user, blocked_stmt, blocking_stmt, blocked_app, blocking_app, duration = row
                    
                    self.stdout.write(self.style.ERROR(f'Blocked PID {blocked_pid} ({blocked_user}/{blocked_app}) waiting for PID {blocking_pid} ({blocking_user}/{blocking_app})'))
                    self.stdout.write(f'  Duration: {duration:.1f}s')
                    self.stdout.write(f'  Blocked query: {blocked_stmt[:100]}...')
                    self.stdout.write(f'  Blocking query: {blocking_stmt[:100]}...\n')
            else:
                self.stdout.write(self.style.SUCCESS('✅ No lock contention detected'))
            
            # Show all active locks for the database
            cursor.execute("""
                SELECT 
                    l.locktype,
                    l.mode,
                    l.granted,
                    a.pid,
                    a.usename,
                    a.application_name,
                    a.state,
                    EXTRACT(EPOCH FROM (now() - a.query_start)) as duration,
                    left(a.query, 80) as query_preview
                FROM pg_locks l
                JOIN pg_stat_activity a ON l.pid = a.pid
                WHERE a.datname = %s
                    AND a.state != 'idle'
                ORDER BY duration DESC
                LIMIT 10;
            """, [connection.settings_dict['NAME']])
            
            active_locks = cursor.fetchall()
            
            if active_locks:
                self.stdout.write('\n📋 Active Locks (top 10):')
                self.stdout.write('-' * 80)
                self.stdout.write(f"{'Type':<12} {'Mode':<20} {'Granted':<8} {'PID':<8} {'User':<12} {'Duration(s)':<12}")
                self.stdout.write('-' * 80)
                
                for locktype, mode, granted, pid, user, app, state, duration, query in active_locks:
                    granted_str = '✓' if granted else '✗'
                    self.stdout.write(f"{locktype:<12} {mode:<20} {granted_str:<8} {pid:<8} {user:<12} {duration:.1f}")
                    if not granted:
                        self.stdout.write(self.style.WARNING(f"  Waiting: {query[:60]}..."))
            
            # Show lock summary
            cursor.execute("""
                SELECT 
                    locktype,
                    mode,
                    granted,
                    count(*) as count
                FROM pg_locks l
                JOIN pg_stat_activity a ON l.pid = a.pid
                WHERE a.datname = %s
                GROUP BY locktype, mode, granted
                ORDER BY count DESC;
            """, [connection.settings_dict['NAME']])
            
            lock_summary = cursor.fetchall()
            
            if lock_summary:
                self.stdout.write('\n📊 Lock Summary:')
                self.stdout.write('-' * 80)
                self.stdout.write(f"{'Lock Type':<15} {'Mode':<25} {'Granted':<10} {'Count':<10}")
                self.stdout.write('-' * 80)
                
                for locktype, mode, granted, count in lock_summary:
                    granted_str = 'Yes' if granted else 'No'
                    style = self.style.SUCCESS if granted else self.style.ERROR
                    self.stdout.write(style(f"{locktype:<15} {mode:<25} {granted_str:<10} {count:<10}"))

