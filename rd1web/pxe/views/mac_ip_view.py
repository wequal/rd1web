#!/usr/bin/env python3
"""
Views for displaying MAC-IP results from multiple subnets.
"""

from __future__ import annotations
import logging
import threading
import time
import json
import requests
import subprocess
import os
import re
import tempfile
from django.shortcuts import render
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count, Value
from django.db.models.functions import Replace
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
from ..models import ArpScanResult

logger = logging.getLogger(__name__)

# Subnet configurations for network scanning
SUBNET_CONFIGS = {
    'local': {
        'interface': 'eno1np0',
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
        if not acquire_scan_lock(subnet_name):
            logger.warning(f"Scan already in progress for {subnet_name}, skipping")
            update_scan_status(subnet_name, {'error': "Another scan is already in progress"})
            return
        
        logger.info(f"Starting manual scan for {subnet_name} network")

        processed_hosts = []
        
        # Data Gathering Phase
        if subnet_config['scan_method'] == 'fastapi':
            api_url = subnet_config.get('api_url')
            if not api_url:
                raise Exception("No API URL configured")
                
            response = requests.get(api_url, timeout=300)
            response.raise_for_status()
            hosts = response.json().get('hosts', [])
            
            for host in hosts:
                ip = host.get('IP Address')
                mac = host.get('MAC Address')
                hostname = host.get('Hostname', '(Unknown)')
                if ip and mac:
                    processed_hosts.append({'ip': ip, 'mac': mac, 'hostname': hostname})
        
        else:  # arp-scan method
            output_file = None
            try:
                with tempfile.NamedTemporaryFile(mode='w+', delete=False, prefix=f"ip_{subnet_name}_", suffix=".tmp") as f:
                    output_file = f.name
                    command = f'arp-scan -I {subnet_config["interface"]} {subnet_config["network"]}'
                    result = subprocess.run(
                        command.split(),
                        stdout=f,
                        stderr=subprocess.PIPE,
                        timeout=300,
                        text=True
                    )
                    if result.returncode != 0:
                        raise Exception(f"Arp-scan failed with exit code {result.returncode}: {result.stderr}")
                
                if os.path.getsize(output_file) > 0:
                    with open(output_file, 'r') as f:
                        for line in f:
                            if not line or line.startswith('Interface:') or line.startswith('Starting') or 'packets' in line:
                                continue
                            match = re.match(r'^(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:-]+)\s*(.*?)$', line)
                            if match:
                                ip = match.group(1)
                                mac = match.group(2)
                                hostname = match.group(3).strip()
                                processed_hosts.append({'ip': ip, 'mac': mac, 'hostname': hostname})
            finally:
                if output_file and os.path.exists(output_file):
                    os.remove(output_file)

        # Data Processing and Database Update Phase
        current_macs = set()
        to_create = []
        to_update = []
        
        # Pre-fetch existing results for this subnet to optimize
        existing_results = {
            result.mac_address: result 
            for result in ArpScanResult.objects.filter(subnet_source=subnet_name)
        }

        # Keep track of MACs processed in this scan to handle duplicates from the scanner
        processed_macs_in_scan = set()

        for host in processed_hosts:
            ip_address = host['ip']
            mac_raw = host['mac']
            hostname = host['hostname'] or None
            
            # Normalize MAC address to a consistent format
            normalized_mac = mac_raw.replace(':', '').replace('-', '').lower()
            if len(normalized_mac) != 12 or not all(c in '0123456789abcdef' for c in normalized_mac):
                logger.warning(f"Skipping invalid MAC address found in scan: {mac_raw}")
                continue
            mac_address = ':'.join(normalized_mac[i:i+2] for i in range(0, 12, 2))
            
            # If we've already processed this MAC in this scan, skip it
            if mac_address in processed_macs_in_scan:
                continue
            processed_macs_in_scan.add(mac_address)
            
            current_macs.add(mac_address)
            
            if hostname in ['(Unknown)', '(unknown)']:
                hostname = None

            instance_data = {
                'ip_address': ip_address,
                'hostname': hostname,
                'is_active': True,
                'last_seen': timezone.now(),
                'subnet_source': subnet_name,
                'scan_interface': subnet_config['interface']
            }
            
            existing = existing_results.get(mac_address)
            if existing:
                # Check for changes before adding to update list
                if (existing.ip_address != ip_address or
                    existing.hostname != hostname or
                    not existing.is_active):
                    for key, value in instance_data.items():
                        setattr(existing, key, value)
                    to_update.append(existing)
                else:
                    # Even if no data changed, we should update the last_seen timestamp
                    existing.last_seen = instance_data['last_seen']
                    to_update.append(existing)
            else:
                to_create.append(ArpScanResult(mac_address=mac_address, **instance_data))
        
        # Bulk database operations
        with transaction.atomic():
            if to_create:
                ArpScanResult.objects.bulk_create(to_create, batch_size=500)
            if to_update:
                update_fields = ['ip_address', 'hostname', 'is_active', 'last_seen', 'scan_interface']
                ArpScanResult.objects.bulk_update(to_update, update_fields, batch_size=500)
            
            # Mark entries not in the current scan as inactive
            if current_macs:
                ArpScanResult.objects.filter(
                    is_active=True, subnet_source=subnet_name
                ).exclude(mac_address__in=current_macs).update(is_active=False)

        logger.info(f"Manual scan completed successfully for {subnet_name} - {len(to_create)} new, {len(to_update)} updated")
        release_scan_lock(subnet_name)
            
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
@permission_required('pxe.can_use_tools', raise_exception=True)
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
        # =============================================================================
        # ENHANCED SEARCH FUNCTIONALITY
        # =============================================================================
        # This section implements flexible search across IP addresses, hostnames, and 
        # MAC addresses with support for multiple formats and multiple search terms.
        
        # Base query for searching IP addresses and hostnames
        # Uses case-insensitive 'icontains' to match partial strings anywhere in the field
        base_query = Q(ip_address__icontains=search_query) | Q(hostname__icontains=search_query)
        
        # Initialize empty MAC address query - will be built up with OR conditions
        mac_query = Q()
        
        # =============================================================================
        # MULTIPLE MAC ADDRESS SUPPORT
        # =============================================================================
        # Parse search input to support multiple MAC addresses separated by spaces or commas
        # Examples: "00:09:0f:09:ac:12 00090f09ac13" or "mac1,mac2,mac3"
        search_terms = [term.strip() for term in search_query.replace(',', ' ').split() if term.strip()]
        
        # Process each individual search term to build comprehensive MAC query
        for term in search_terms:
            # =============================================================================
            # DIRECT MAC ADDRESS MATCHING
            # =============================================================================
            # First, search against the stored MAC address format directly
            # This preserves exact matching for users who know the stored format (with colons)
            # Example: searching "00:09" will match "00:09:0f:09:ac:12"
            mac_query |= Q(mac_address__icontains=term)
            
            # =============================================================================
            # FLEXIBLE MAC FORMAT NORMALIZATION
            # =============================================================================
            # Remove all non-hex characters to create a normalized search term
            # This enables searching across different MAC address formats:
            # - "00:09:0f:09:ac:12" -> "00090f09ac12"
            # - "0009-0f-09-ac-12" -> "00090f09ac12" 
            # - "00090f09ac12"      -> "00090f09ac12"
            normalized_search = re.sub(r'[^a-fA-F0-9]', '', term).lower()
            
            # Only perform normalized search if we have meaningful content (min 2 hex chars)
            if normalized_search and len(normalized_search) >= 2:
                # =============================================================================
                # DATABASE-LEVEL MAC NORMALIZATION
                # =============================================================================
                # Use Django's Replace function to normalize stored MAC addresses at database level
                # This creates a temporary field that removes both colons and dashes for comparison
                # Nested Replace calls: first removes ':', then removes '-' from the result
                # Stored "00:09:0f:09:ac:12" becomes "00090f09ac12" for comparison
                queryset = queryset.annotate(
                    normalized_mac=Replace(Replace('mac_address', Value(':'), Value('')), Value('-'), Value(''))
                )
                # Add this normalized comparison to our MAC query with OR logic
                mac_query |= Q(normalized_mac__icontains=normalized_search)

        # =============================================================================
        # FINAL QUERY COMBINATION
        # =============================================================================
        # Combine all search conditions with OR logic:
        # (IP matches OR hostname matches) OR (any MAC format matches)
        queryset = queryset.filter(base_query | mac_query)

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