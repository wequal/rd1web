#!/usr/bin/env python3
"""
Script to run the Django development server with ASGI support for WebSocket functionality.
This enables the SOL terminal feature with real-time WebSocket communication.
"""

import os
import sys
import django
from django.core.management import execute_from_command_line
from django.conf import settings

def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rd1web.settings')
    
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
    
    # Server configuration
    host = '172.31.60.129'
    port = 80
    
    # Check for command line arguments
    if len(sys.argv) == 1:
        # Use Daphne for ASGI support instead of Django's runserver
        print(f"Starting Django ASGI server with Daphne for WebSocket support...")
        print(f"SOL terminals will be available at ws://{host}:{port}/ws/sol/<folder_name>/")
        print(f"Access the web interface at http://{host}:{port}/")
        print(f"Note: Port {port} requires root privileges. Run with sudo if needed.")
        
        # Run with Daphne
        os.system(f'daphne -b {host} -p {port} rd1web.asgi:application')
    elif sys.argv[1] == 'runserver':
        # If explicitly asked for runserver, warn about WebSocket limitations
        print("⚠ Warning: Using Django's runserver may have limited WebSocket support")
        print("⚠ For full SOL terminal functionality, use 'python3 run_server.py' without arguments")
        execute_from_command_line(sys.argv)
    else:
        # Pass through other Django commands
        execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main() 