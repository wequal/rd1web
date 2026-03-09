#!/usr/bin/env python3
"""
Script to run the Django development server with ASGI support for WebSocket functionality.
This enables the SOL terminal feature with real-time WebSocket communication.
Configured to work with Nginx reverse proxy setup.
Supports multiple workers for better concurrent SOL session handling
"""

import os
import sys
import django
import signal
import time
import argparse
import json
from pathlib import Path
from django.core.management import execute_from_command_line
from django.conf import settings

# Import configuration from local_config
try:
    from pxe.local_config import WEB_APP_PORT, DATABASE_CONFIG
    host_ip = DATABASE_CONFIG['HOST']
    print(f"✓ Using configuration from local_config.py (Port: {WEB_APP_PORT})")
except ImportError:
    # Fallback to defaults if local_config doesn't exist
    from pxe.remote_config import remote_dict
    host_ip = remote_dict['us_b3'].host.split('@')[-1] if '@' in remote_dict['us_b3'].host else remote_dict['us_b3'].host
    WEB_APP_PORT = 5003
    print("⚠ local_config.py not found, using default configuration")

# Global list to track worker processes
worker_processes = []

def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    print(f"\n🛑 Received signal {sig}, shutting down workers...")
    for process in worker_processes:
        if process.poll() is None:  # Process is still running
            print(f"   Terminating worker PID {process.pid}")
            process.terminate()
    
    # Wait for processes to terminate gracefully
    for process in worker_processes:
        try:
            process.wait(timeout=5)
        except:
            # Force kill if doesn't terminate gracefully
            process.kill()
    
    print("🛑 All workers stopped")
    sys.exit(0)

def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rd1web.settings')
    
    # Calculate base directory (same as settings.py BASE_DIR)
    # run_server.py is in rd1web/, so parent is the project root
    BASE_DIR = Path(__file__).resolve().parent
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='RD1 Web Server with multi-worker support')
    parser.add_argument('--workers', '-w', type=int, default=1, 
                       help='Number of Daphne workers to start (default: 1, recommended: 4)')
    parser.add_argument('--start-port', type=int, default=8000,
                       help='Starting port for workers (default: 8000)')
    parser.add_argument('--rd1pxe', type=str, default=None,
                       help='First parameter for hiding sidebar sections (when equal to mac2ip)')
    parser.add_argument('--mac2ip', type=str, default=None,
                       help='Second parameter for hiding sidebar sections (when equal to rd1pxe)')
    parser.add_argument('--no-celery', action='store_true',
                       help='Disable automatic Celery worker startup')
    parser.add_argument('--no-celery-beat', action='store_true',
                       help='Disable automatic Celery beat scheduler startup')
    parser.add_argument('command', nargs='?', default=None,
                       help='Django management command (runserver, migrate, etc.)')
    
    # Parse known args to handle Django commands
    args, unknown = parser.parse_known_args()
    
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    
    # Check if we have the required packages
    try:
        import channels
        import websockets
        import daphne
        print("✓ Django Channels, WebSocket, and Daphne support available")
        print("✓ SOL terminal functionality will be enabled")
    except ImportError as e:
        print(f"⚠ Warning: Missing required packages for SOL terminal: {e}")
        print("⚠ Install with: pip install channels websockets daphne")
        print("⚠ SOL terminal may not work properly")
    
    # Check Redis connection for caching and performance
    try:
        import redis
        import django_redis
        
        # Test Redis connection
        from django.core.cache import cache
        cache.set('health_check', 'ok', 10)
        if cache.get('health_check') == 'ok':
            print("✓ Redis cache connection successful")
            print("✓ High-performance user tracking enabled")
            cache.delete('health_check')
        else:
            raise Exception("Cache test failed")
            
    except ImportError as e:
        print(f"⚠ Warning: Redis packages not installed: {e}")
        print("⚠ Install with: pip install redis django-redis hiredis")
        print("⚠ Performance optimizations will be limited")
    except Exception as e:
        print(f"⚠ Warning: Redis connection failed: {e}")
        print("⚠ Make sure Redis server is running: sudo systemctl start redis")
        print("⚠ Performance optimizations will be limited")
    
    # Handle Django management commands
    if args.command or len(unknown) > 0:
        # Pass through Django commands (migrate, collectstatic, etc.)
        django_args = [sys.argv[0]]
        if args.command:
            django_args.append(args.command)
        django_args.extend(unknown)
        
        if args.command == 'runserver':
            print("⚠ Warning: Using Django's runserver has limited WebSocket support")
            print("⚠ For full SOL terminal functionality, use without 'runserver' command")
        
        execute_from_command_line(django_args)
        return
    
    # Write sidebar hide parameters to config file
    config_file = BASE_DIR / 'sidebar_hide_config.json'
    sidebar_config = {
        'rd1pxe': args.rd1pxe,
        'mac2ip': args.mac2ip
    }
    with open(config_file, 'w') as f:
        json.dump(sidebar_config, f)
    
    # Server configuration for Nginx proxy setup
    host = '127.0.0.1'  # Local only - Nginx will handle external requests
    start_port = args.start_port
    workers = args.workers
    
    # Validate worker count
    if workers < 1:
        workers = 1
    elif workers > 8:
        print("⚠ Warning: More than 8 workers may cause performance issues")
        print("⚠ Recommended: 2-6 workers depending on your server specs")
    
    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"🚀 Starting {workers} Django/Daphne worker(s)")
    print(f"🔧 Using timeout settings: HTTP=120s, App Close=60s, WebSocket Handshake=10s")
    print(f"✓ SOL terminal functionality will be enabled")
    print(f"⚡ Redis caching: User tracking optimized for high performance")
    print(f"🌐 Nginx should proxy external requests from port 80 to these backends")
    print(f"📁 Public access via: http://{host_ip}/ (through Nginx)")
    print(f"🔌 WebSocket SOL terminals: ws://{host_ip}/ws/sol/<folder_name>/ (through Nginx)")
    print(f"⚡ Static files served directly by Nginx for better performance")
    print()
    
    # Calculate expected capacity
    sol_capacity = workers * 10  # Estimate 10 SOL sessions per worker
    print(f"📊 Expected capacity: {sol_capacity}-{sol_capacity*2} concurrent SOL sessions")
    print(f"💾 Memory usage: ~{workers * 50}-{workers * 100}MB for workers")
    print()
    
    # Start worker processes
    import subprocess
    
    for worker_id in range(workers):
        port = start_port + worker_id
        
        # Daphne command for each worker
        daphne_command = [
            'daphne',
            '-b', host,
            '-p', str(port),
            '-t', '120',
            '--application-close-timeout', '60', 
            '--websocket_connect_timeout', '10',
            'rd1web.asgi:application'
        ]
        
        try:
            print(f"🔄 Starting worker {worker_id + 1}/{workers} on {host}:{port}")
            worker_env = os.environ.copy()
            # Set environment variable to identify worker
            
            worker_env['DAPHNE_WORKER_ID'] = str(worker_id)
            worker_env['DAPHNE_WORKER_PORT'] = str(port)
            
            process = subprocess.Popen(daphne_command, env=worker_env)
            worker_processes.append(process)
            time.sleep(0.5)  # Small delay between worker starts
        except Exception as e:
            print(f"❌ Error starting worker {worker_id + 1}: {e}")
            # Cleanup already started workers
            signal_handler(signal.SIGTERM, None)
            sys.exit(1)
    
    print()
    print(f"✅ All {workers} Daphne workers started successfully!")
    print(f"🔗 Nginx upstream should include ports: {start_port}-{start_port + workers - 1}")
    print()
    
    # Start Celery worker if enabled
    celery_worker_process = None
    celery_beat_process = None
    
    if not args.no_celery:
        try:
            print("🔄 Starting Celery worker...")
            # Get parent directory (project root)
            project_root = BASE_DIR.parent
            celery_worker_cmd = [
                'celery', '-A', 'rd1web', 'worker',
                '--loglevel=info',
                '--concurrency=2',
                '--max-tasks-per-child=1000',
                '--time-limit=300',
                '--soft-time-limit=240',
                '--logfile=' + str(project_root / 'celery_worker.log'),
                '--pidfile=' + str(project_root / 'celery_worker.pid')
            ]
            
            celery_env = os.environ.copy()
            celery_env['DJANGO_SETTINGS_MODULE'] = 'rd1web.settings'
            
            celery_worker_process = subprocess.Popen(
                celery_worker_cmd,
                cwd=str(BASE_DIR),
                env=celery_env
            )
            worker_processes.append(celery_worker_process)
            time.sleep(1)  # Give Celery time to start
            print("✅ Celery worker started (PID: {})".format(celery_worker_process.pid))
        except Exception as e:
            print(f"⚠ Warning: Failed to start Celery worker: {e}")
            print("⚠ Celery tasks will run synchronously (fallback mode)")
    
    # Start Celery beat if enabled
    if not args.no_celery_beat and not args.no_celery:
        try:
            print("🔄 Starting Celery beat scheduler...")
            project_root = BASE_DIR.parent
            celery_beat_cmd = [
                'celery', '-A', 'rd1web', 'beat',
                '--loglevel=info',
                '--logfile=' + str(project_root / 'celery_beat.log'),
                '--pidfile=' + str(project_root / 'celery_beat.pid'),
                '--schedule=' + str(project_root / 'celerybeat-schedule.db')
            ]
            
            celery_env = os.environ.copy()
            celery_env['DJANGO_SETTINGS_MODULE'] = 'rd1web.settings'
            
            celery_beat_process = subprocess.Popen(
                celery_beat_cmd,
                cwd=str(BASE_DIR),
                env=celery_env
            )
            worker_processes.append(celery_beat_process)
            time.sleep(1)
            print("✅ Celery beat started (PID: {})".format(celery_beat_process.pid))
        except Exception as e:
            print(f"⚠ Warning: Failed to start Celery beat: {e}")
            print("⚠ Periodic tasks will not run automatically")
    
    print()
    print("📋 Worker Status:")
    for i, process in enumerate(worker_processes):
        if i < workers:
            port = start_port + i
            status = "RUNNING" if process.poll() is None else "STOPPED"
            print(f"   Daphne Worker {i+1}: {host}:{port} - {status} (PID: {process.pid})")
        elif process == celery_worker_process:
            status = "RUNNING" if process.poll() is None else "STOPPED"
            print(f"   Celery Worker: {status} (PID: {process.pid})")
        elif process == celery_beat_process:
            status = "RUNNING" if process.poll() is None else "STOPPED"
            print(f"   Celery Beat: {status} (PID: {process.pid})")
    
    print()
    print("🎯 Load balancing: Nginx will distribute requests across all workers")
    if not args.no_celery:
        print("⚡ Celery: Background tasks enabled")
    print("💡 Tip: Monitor with 'ps aux | grep daphne' and 'ps aux | grep celery'")
    print("🛑 Press Ctrl+C to stop all workers")
    print()
    
    # Monitor worker processes (warn once per dead worker to avoid spam)
    warned_dead = set()
    try:
        while True:
            time.sleep(5)
            dead_workers = []
            for i, process in enumerate(worker_processes):
                if process.poll() is not None:
                    dead_workers.append(i)
            newly_dead = [i for i in dead_workers if i not in warned_dead]
            if newly_dead:
                warned_dead.update(newly_dead)
                labels = [f"Daphne {i+1}" if i < workers else ("Celery" if worker_processes[i] == celery_worker_process else "Celery Beat") for i in newly_dead]
                print(f"⚠ Warning: Worker(s) {labels} have stopped (port in use or crash; check logs)")
            if len(dead_workers) == len(worker_processes):
                print("❌ All workers have stopped")
                break
                
    except KeyboardInterrupt:
        print("\n🛑 Shutdown requested by user")
    finally:
        signal_handler(signal.SIGTERM, None)

if __name__ == '__main__':
    main() 