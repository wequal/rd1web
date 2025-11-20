from django.shortcuts import render
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
import requests
import json
import logging
from ..remote_config import remote_dict

logger = logging.getLogger(__name__)

# Import configuration from local_config
try:
    from ..local_config import RMA_DHCP_LEASES_API, REMOTE_SERVERS, DEPLOYMENT_LOCATION
    # Extract RMA host from REMOTE_SERVERS (format: root@10.4.4.80)
    rma_host = REMOTE_SERVERS[DEPLOYMENT_LOCATION]['host'].split('@')[-1]
    dhcp_api_port = RMA_DHCP_LEASES_API['port']
    dhcp_api_endpoint = RMA_DHCP_LEASES_API['endpoint']
    dhcp_api_timeout = RMA_DHCP_LEASES_API['timeout']
    logger.info(f"RMA DHCP Leases using configuration: {rma_host}:{dhcp_api_port}{dhcp_api_endpoint}")
except ImportError:
    # Fallback to defaults if local_config doesn't exist
    logger.warning("local_config.py not found, using default RMA DHCP API configuration")
    rma_host = remote_dict['rma'].host.split('@')[-1] if '@' in remote_dict['rma'].host else remote_dict['rma'].host
    dhcp_api_port = 8000
    dhcp_api_endpoint = '/leases'
    dhcp_api_timeout = 10


@login_required
@permission_required('pxe.can_access_rma_dhcp_leases', raise_exception=True)
def rma_dhcp_leases(request):
    """Main view for RMA DHCP Leases page"""
    
    # Try to fetch leases data on initial load
    leases_data = fetch_dhcp_leases()
    
    context = {
        'leases': leases_data.get('leases', []) if leases_data else [],
        'error_message': leases_data.get('error') if leases_data and 'error' in leases_data else None,
        'api_endpoint': f'http://{rma_host}:{dhcp_api_port}{dhcp_api_endpoint}'
    }
    
    return render(request, 'features/rma_dhcp_leases.html', context)


@login_required
@permission_required('pxe.can_access_rma_dhcp_leases', raise_exception=True)
@require_http_methods(["GET"])
def rma_dhcp_leases_refresh(request):
    """AJAX endpoint to refresh DHCP leases data"""
    
    leases_data = fetch_dhcp_leases()
    
    if leases_data and 'error' not in leases_data:
        return JsonResponse({
            'success': True,
            'leases': leases_data.get('leases', []),
            'message': f'Successfully fetched {len(leases_data.get("leases", []))} DHCP leases'
        })
    else:
        error_msg = leases_data.get('error', 'Unknown error occurred') if leases_data else 'Failed to fetch data'
        return JsonResponse({
            'success': False,
            'error': error_msg,
            'leases': []
        })


def fetch_dhcp_leases():
    """
    Fetch DHCP leases from the external API
    Returns dict with 'leases' key on success, or 'error' key on failure
    """
    try:
        # Make API request with timeout
        response = requests.get(
            f'http://{rma_host}:{dhcp_api_port}{dhcp_api_endpoint}',
            timeout=dhcp_api_timeout,
            headers={'Content-Type': 'application/json'}
        )
        
        # Check if request was successful
        response.raise_for_status()
        
        # Parse JSON response
        data = response.json()
        
        # Validate response structure
        if not isinstance(data, dict) or 'leases' not in data:
            logger.error(f"Invalid API response structure: {data}")
            return {'error': 'Invalid response format from DHCP server'}
        
        if not isinstance(data['leases'], list):
            logger.error(f"Leases is not a list: {data['leases']}")
            return {'error': 'Invalid leases data format'}
        
        # Validate each lease entry
        valid_leases = []
        for lease in data['leases']:
            if not isinstance(lease, dict):
                logger.warning(f"Skipping invalid lease entry: {lease}")
                continue
                
            # Ensure required fields exist
            if 'mac' not in lease or 'ip' not in lease or 'hostname' not in lease:
                logger.warning(f"Skipping lease with missing fields: {lease}")
                continue
                
            # Clean up hostname display
            hostname = lease['hostname']
            if hostname == '-NA-' or not hostname or hostname.strip() == '':
                hostname = 'N/A'
                
            valid_leases.append({
                'mac': lease['mac'].upper(),  # Normalize MAC to uppercase
                'ip': lease['ip'],
                'hostname': hostname
            })
        
        logger.info(f"Successfully fetched {len(valid_leases)} DHCP leases")
        return {'leases': valid_leases}
        
    except requests.exceptions.Timeout:
        error_msg = f'Request timeout - DHCP server did not respond within {dhcp_api_timeout} seconds'
        logger.error(error_msg)
        return {'error': error_msg}
        
    except requests.exceptions.ConnectionError:
        error_msg = f'Connection error - Unable to connect to DHCP server at {rma_host}:{dhcp_api_port}'
        logger.error(error_msg)
        return {'error': error_msg}
        
    except requests.exceptions.HTTPError as e:
        error_msg = f'HTTP error - Server returned {e.response.status_code}'
        logger.error(f"{error_msg}: {e}")
        return {'error': error_msg}
        
    except json.JSONDecodeError:
        error_msg = 'Invalid JSON response from DHCP server'
        logger.error(error_msg)
        return {'error': error_msg}
        
    except Exception as e:
        error_msg = f'Unexpected error: {str(e)}'
        logger.error(f"Unexpected error fetching DHCP leases: {e}")
        return {'error': error_msg}
