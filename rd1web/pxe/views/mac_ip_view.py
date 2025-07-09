#!/usr/bin/env python3
"""
Views for displaying MAC-IP results from multiple subnets.
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from ..models import ArpScanResult
import logging
import threading
import time
import json
import requests
import subprocess
import os
import re
from django.db import transaction
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Subnet configurations for network scanning
SUBNET_CONFIGS = {
    'local': {
        'interface': 'eno1',
        'network': '172.31.0.0/16',
        'description': 'US Network',
        'scan_method': 'arp-scan',  # Use arp-scan directly
        'ui_name': 'us'  # Name shown in UI
    },
    'remote': {
        'interface': 'eno1', 
        'network': '10.135.0.0/16',
        'description': 'TW Network',
        'scan_method': 'fastapi',  # Use FastAPI endpoint
        'api_url': 'http://10.135.179.104:8000/scan',
        'ui_name': 'tw'  # Name shown in UI
    }
}

# Mapping from UI names to internal subnet names
UI_TO_SUBNET_MAP = {
    'us': 'local',
    'tw': 'remote'
}

# Mapping from internal subnet names to UI names
SUBNET_TO_UI_MAP = {
    'local': 'us',
    'remote': 'tw'
}

def get_status_key(subnet_name):
    """Get Redis key for scan status"""
    return f'scan_status_{subnet_name}'

def get_lock_key(subnet_name):
    """Get Redis key for scan lock"""
    return f'scan_lock_{subnet_name}'

def update_scan_status(subnet_name, status_update):
    """Update scan status in Redis"""
    status_key = get_status_key(subnet_name)
    current_status = cache.get(status_key) or {'scanning': False, 'last_scan': None, 'error': None}
    current_status.update(status_update)
    
    # Convert datetime to ISO format for JSON serialization
    if current_status.get('last_scan'):
        if isinstance(current_status['last_scan'], str):
            # Already converted
            pass
        else:
            current_status['last_scan'] = current_status['last_scan'].isoformat()
    
    cache.set(status_key, current_status, timeout=3600)  # 1 hour timeout

def get_scan_status(subnet_name=None):
    """Get scan status from Redis"""
    if subnet_name:
        status_key = get_status_key(subnet_name)
        return cache.get(status_key) or {'scanning': False, 'last_scan': None, 'error': None}
    
    # Return all statuses
    result = {}
    for subnet in ['local', 'remote']:
        status_key = get_status_key(subnet)
        result[subnet] = cache.get(status_key) or {'scanning': False, 'last_scan': None, 'error': None}
    return result

def acquire_scan_lock(subnet_name):
    """Try to acquire a Redis-based lock for scanning a subnet"""
    lock_key = get_lock_key(subnet_name)
    if cache.add(lock_key, True, timeout=600):  # 10 minute timeout
        update_scan_status(subnet_name, {'scanning': True, 'error': None})
        return True
    return False

def release_scan_lock(subnet_name, error=None):
    """Release the Redis-based scan lock and update status"""
    lock_key = get_lock_key(subnet_name)
    cache.delete(lock_key)
    
    status_update = {
        'scanning': False,
        'last_scan': timezone.now() if not error else None
    }
    if error:
        status_update['error'] = str(error)
    update_scan_status(subnet_name, status_update)

def manual_scan_worker(subnet_name, subnet_config):
    """Worker function for manual network scanning"""
    try:
        # Try to acquire scan lock
        if not acquire_scan_lock(subnet_name):
            logger.warning(f"Scan already in progress for {subnet_name}, skipping")
            update_scan_status(subnet_name, {'error': "Another scan is already in progress"})
            return
        
        logger.info(f"Starting manual scan for {subnet_name} network")
        
        # Run the scan based on the scan method
        if subnet_config['scan_method'] == 'fastapi':
            # Make HTTP request to FastAPI endpoint
            api_url = subnet_config.get('api_url')
            if not api_url:
                raise Exception("No API URL configured")
                
            response = requests.get(api_url, timeout=300)  # 5 minute timeout
            if response.status_code != 200:
                raise Exception(f"FastAPI endpoint returned status {response.status_code}")
                
            data = response.json()
            hosts = data.get('hosts', [])
            
            # Convert FastAPI format to arp-scan format and save to file
            output_file = f"/tmp/ip_{subnet_name}"
            with open(output_file, 'w') as f:
                f.write(f"Interface: {subnet_config['interface']}, type: EN10MB\\n")
                f.write(f"Starting arp-scan 1.10.0 with {len(hosts)} hosts\\n")
                
                for host in hosts:
                    ip = host.get('IP Address', '')
                    mac = host.get('MAC Address', '')
                    hostname = host.get('Hostname', '(Unknown)')
                    
                    if ip and mac:
                        f.write(f"{ip}\\t{mac}\\t{hostname}\\n")
                
                f.write(f"\\n{len(hosts)} packets received by filter\\n")
                f.write(f"{len(hosts)} packets captured by pcap\\n")
            
            scan_success = True
            
        else:  # arp-scan method
            output_file = f"/tmp/ip_{subnet_name}"
            command = f'arp-scan -I {subnet_config["interface"]} {subnet_config["network"]}'
            
            # Run arp-scan and redirect output to file
            with open(output_file, 'w') as f:
                result = subprocess.run(
                    command.split(),
                    stdout=f,
                    stderr=subprocess.PIPE,
                    timeout=300,  # 5 minute timeout
                    text=True
                )
            
            # Check if we got output
            scan_success = os.path.exists(output_file) and os.path.getsize(output_file) > 0
            if not scan_success:
                error_msg = result.stderr if result.stderr else 'No output generated'
                raise Exception(f"Arp-scan failed: {error_msg}")
        
        # Update database with scan results
        if scan_success:
            current_ips = set()
            new_entries = 0
            updated_entries = 0
            
            with open(output_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip empty lines and header/footer lines
                    if not line or line.startswith('Interface:') or line.startswith('Starting') or line.startswith('packets'):
                        continue
                        
                    # Parse lines: IP_ADDRESS    MAC_ADDRESS    HOSTNAME
                    match = re.match(r'^(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s+([0-9a-fA-F:]{17})\\s*(.*?)$', line)
                    
                    if match:
                        ip_address = match.group(1)
                        mac_address = match.group(2).lower()
                        hostname = match.group(3).strip()
                        
                        if hostname in ['', '(Unknown)', '(unknown)']:
                            hostname = None
                            
                        current_ips.add(ip_address)
                        
                        # Update or create database entry
                        with transaction.atomic():
                            obj, created = ArpScanResult.objects.update_or_create(
                                ip_address=ip_address,
                                defaults={
                                    'mac_address': mac_address,
                                    'hostname': hostname,
                                    'is_active': True,
                                    'last_seen': timezone.now(),
                                    'subnet_source': subnet_name,
                                    'scan_interface': subnet_config['interface']
                                }
                            )
                            
                            if created:
                                new_entries += 1
                            else:
                                updated_entries += 1
            
            # Mark entries not in current scan as inactive
            if current_ips:
                with transaction.atomic():
                    inactive_entries = ArpScanResult.objects.filter(
                        is_active=True,
                        subnet_source=subnet_name
                    ).exclude(ip_address__in=current_ips)
                    
                    inactive_count = 0
                    for entry in inactive_entries:
                        entry.is_active = False
                        entry.save()
                        inactive_count += 1
            
            logger.info(f"Manual scan completed successfully for {subnet_name} - {new_entries} new, {updated_entries} updated")
            release_scan_lock(subnet_name)  # Success case
            
        # Clean up output file
        try:
            os.remove(output_file)
        except OSError:
            pass
            
    except Exception as e:
        logger.error(f"Error in manual scan for {subnet_name}: {str(e)}")
        release_scan_lock(subnet_name, error=str(e))

@login_required
@require_http_methods(["POST"])
def manual_scan(request):
    """API endpoint to trigger manual network scanning"""
    try:
        data = json.loads(request.body)
        network = data.get('network', '').lower()
        
        if network not in ['us', 'tw']:
            return JsonResponse({'error': 'Invalid network. Must be "us" or "tw"'}, status=400)
        
        # Map UI network name to internal subnet name
        subnet_source = UI_TO_SUBNET_MAP[network]
        
        # Get subnet configuration
        subnet_config = SUBNET_CONFIGS[subnet_source]
        
        # Check if scan is already running
        current_status = get_scan_status(subnet_source)
        if current_status['scanning']:
            return JsonResponse({
                'error': 'A scan is already in progress for this network',
                'network': network,
                'scanning': True
            }, status=409)
        
        # Start scanning in a separate thread
        scan_thread = threading.Thread(
            target=manual_scan_worker,
            args=(subnet_source, subnet_config),
            daemon=True
        )
        scan_thread.start()
        
        return JsonResponse({
            'success': True,
            'message': f'Started scanning {network.upper()} network',
            'network': network,
            'scanning': True
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
    except Exception as e:
        logger.error(f"Error in manual scan endpoint: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_http_methods(["GET"])
def scan_status_api(request):
    """API endpoint to check scan status"""
    network = request.GET.get('network', '').lower()
    
    if network and network not in ['us', 'tw']:
        return JsonResponse({'error': 'Invalid network. Must be "us" or "tw"'}, status=400)
    
    if network:
        # Map UI network name to internal subnet name
        subnet_source = UI_TO_SUBNET_MAP[network]
        
        # Return status for specific network
        status = get_scan_status(subnet_source)
        return JsonResponse({
            'network': network,
            'status': status
        })
    else:
        # Return status for all networks (mapped to UI names)
        result = {}
        all_status = get_scan_status()
        for subnet_source, status in all_status.items():
            ui_name = SUBNET_TO_UI_MAP[subnet_source]
            result[ui_name] = status
        
        return JsonResponse({'scan_status': result})

@login_required
def mac_ip_results(request):
    """Display MAC-IP scan results from multiple subnets"""
    # Get filter parameters
    search_query = request.GET.get('search', '')
    show_inactive = request.GET.get('show_inactive', 'false') == 'true'
    subnet_filter = request.GET.get('subnet_filter', 'all')
    
    # Build queryset
    queryset = ArpScanResult.objects.all()
    
    if not show_inactive:
        queryset = queryset.filter(is_active=True)
    
    if subnet_filter != 'all':
        queryset = queryset.filter(subnet_source=subnet_filter)
    
    if search_query:
        queryset = queryset.filter(
            Q(ip_address__icontains=search_query) |
            Q(mac_address__icontains=search_query) |
            Q(hostname__icontains=search_query)
        )
    
    queryset = queryset.order_by('subnet_source', '-is_active', 'ip_address')
    
    # Pagination
    paginator = Paginator(queryset, 50)  # Show 50 results per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get subnet statistics
    subnet_stats = ArpScanResult.objects.values('subnet_source').annotate(
        total=Count('id'),
        active=Count('id', filter=Q(is_active=True))
    ).order_by('subnet_source')
    
    # Get available subnet choices for filter dropdown
    available_subnets = list(ArpScanResult.objects.values_list('subnet_source', flat=True).distinct())
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'show_inactive': show_inactive,
        'subnet_filter': subnet_filter,
        'available_subnets': available_subnets,
        'subnet_stats': subnet_stats,
    }
    
    return render(request, 'features/mac_ip_results.html', context)


@login_required
def mac_ip_api(request):
    """API endpoint for MAC-IP scan data from multiple subnets"""
    if request.method == 'GET':
        # Get filter parameters
        subnet_filter = request.GET.get('subnet', 'all')
        limit = min(int(request.GET.get('limit', 50)), 200)  # Max 200 results
        
        # Build queryset for recent results
        queryset = ArpScanResult.objects.filter(is_active=True)
        if subnet_filter != 'all':
            queryset = queryset.filter(subnet_source=subnet_filter)
            
        recent_results = queryset.order_by('subnet_source', 'ip_address')[:limit]
        
        # Get subnet statistics
        subnet_stats = {}
        for subnet_data in ArpScanResult.objects.values('subnet_source').annotate(
            total=Count('id'),
            active=Count('id', filter=Q(is_active=True))
        ):
            subnet_name = subnet_data['subnet_source']
            subnet_stats[subnet_name] = {
                'total': subnet_data['total'],
                'active': subnet_data['active']
            }
        
        data = {
            'results': [
                {
                    'ip_address': result.ip_address,
                    'mac_address': result.mac_address,
                    'hostname': result.hostname,
                    'subnet_source': result.subnet_source,
                    'scan_interface': result.scan_interface,
                    'first_seen': result.first_seen.isoformat(),
                    'last_seen': result.last_seen.isoformat(),
                    'is_active': result.is_active
                }
                for result in recent_results
            ],
            'counts': {
                'by_subnet': subnet_stats
            },
            'filter': {
                'subnet': subnet_filter,
                'limit': limit
            }
        }
        
        return JsonResponse(data)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405) 