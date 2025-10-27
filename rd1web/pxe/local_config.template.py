"""
Template for local_config.py
Copy this file to local_config.py and customize for your deployment location

Usage:
    cp local_config.template.py local_config.py
    # Then edit local_config.py with your location-specific settings
"""

# ============================================================================
# DEPLOYMENT LOCATION
# ============================================================================
DEPLOYMENT_LOCATION = 'CHANGE_ME'  # Options: 'us_b3', 'us_b1', 'tw', or your custom location

# ============================================================================
# FILE SYSTEM PATHS
# ============================================================================
# Base directory where RMA test results are stored
RMA_BASE_DIR = '/srv/rma-b31'

# Temporary directory for zip file creation
TEMP_ZIPS_DIR = '/srv/rma-b31/.TempZips'

# Path to RMA PXE generation script
RMA_PXE_GENERATION_SCRIPT = '/srv/share/scripts/rma_pxe_generation'

# Path to PXE boot configuration files
PXE_BOOT_PATH = '/var/www/pxe/boot/'

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================
DATABASE_CONFIG = {
    'NAME': 'pxe_db',           # Database name
    'USER': 'your_db_user',     # Database username
    'PASSWORD': 'your_db_pass', # Database password
    'HOST': '127.0.0.1',        # Database host IP (change per location)
    'PORT': '5432',             # PostgreSQL port
}

# ============================================================================
# REMOTE SERVER CONNECTIONS
# ============================================================================
# SSH connections to remote servers
# Format: 'user@ip_address'
REMOTE_SERVERS = {
    'rma': {
        'host': 'root@10.4.4.80',       # RMA server
        'password': 'your_password',
        'timeout': 30,
    },
    'us_b3': {
        'host': 'root@172.31.56.135',   # US B3 location
        'password': 'your_password',
        'timeout': 30,
    },
    'us_b1': {
        'host': 'root@172.31.58.142',   # US B1 location
        'password': 'your_password',
        'timeout': 30,
    },
    'tw': {
        'host': 'root@10.135.179.104',  # Taiwan location
        'password': 'your_password',
        'timeout': 30,
    },
}

# ============================================================================
# RMA DHCP LEASES API CONFIGURATION
# ============================================================================
# Configuration for fetching DHCP leases from RMA server
# The host is automatically extracted from REMOTE_SERVERS['rma']['host']
RMA_DHCP_LEASES_API = {
    'port': 8000,           # FastAPI port on RMA server
    'endpoint': '/leases',  # API endpoint path
    'timeout': 10,          # Request timeout in seconds
}

# ============================================================================
# NETWORK SCANNING CONFIGURATION
# ============================================================================
# Configuration for network scanning in different locations
SUBNET_CONFIGS = {
    'local': {
        'interface': 'eno1np0',         # Network interface for scanning
        'network': '172.31.0.0/16',     # Subnet to scan
        'description': 'US Network',
        'scan_method': 'arp-scan',      # Use local arp-scan command
        'ui_name': 'us'                 # Display name in UI
    },
    'remote': {
        'interface': 'eno1',            # Remote network interface
        'network': '10.135.0.0/16',     # Remote subnet
        'description': 'TW Network',
        'scan_method': 'fastapi',       # Use remote FastAPI endpoint
        'api_url': 'http://10.135.179.104:8000/scan',  # Remote scan API
        'ui_name': 'tw'                 # Display name in UI
    }
}

# ============================================================================
# SERVICE CONFIGURATION
# ============================================================================
# Port for Django web application
WEB_APP_PORT = 5003

# Redis configuration for caching and Celery
REDIS_HOST = 'localhost'
REDIS_PORT = 6379

# ============================================================================
# DJANGO SETTINGS
# ============================================================================
# Django secret key - GENERATE A NEW ONE FOR PRODUCTION!
# You can generate a new key with:
#   python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
SECRET_KEY = 'CHANGE_ME_TO_A_RANDOM_SECRET_KEY'

# Timezone for your location
TIME_ZONE = 'America/Los_Angeles'  # Change to your timezone

# Debug mode - ALWAYS set to False in production
DEBUG = False

# ============================================================================
# CACHE AND TIMEOUT SETTINGS
# ============================================================================
# Cache timeouts for RMA operations (in seconds)
RMA_CACHE_TIMEOUT = 30           # Basic directory listings
RMA_DETAILS_CACHE_TIMEOUT = 60   # Directory details
RMA_STATS_CACHE_TIMEOUT = 300    # File statistics (5 minutes)
ZIP_TASK_TIMEOUT = 3600          # Zip creation timeout (1 hour)

