import json
import logging
import urllib.parse
import uuid
import requests
from django.shortcuts import render
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from urllib3.exceptions import InsecureRequestWarning
from django.conf import settings

# Suppress unverified HTTPS warnings when talking to BMC
import warnings
warnings.filterwarnings('ignore', category=InsecureRequestWarning)

logger = logging.getLogger(__name__)

###############################################################################
# Views                                                                      #
###############################################################################

@login_required
@require_http_methods(["GET"])
def remote_control(request):
    """Render the Remote Control landing page containing the form."""
    return render(request, 'features/remote_control.html')


# ---------------------------------------------------------------------------
# KVM                                                                          
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def remote_kvm(request):
    """Return the BMC IKVM URL for the provided credentials."""
    try:
        data = json.loads(request.body.decode())
    except Exception:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON payload',
            'error_type': 'payload_error'
        })

    bmc_ip = data.get('bmc_ip')
    bmc_user = data.get('username', 'ADMIN')
    bmc_pwd = data.get('password', '')

    if not (bmc_ip and bmc_pwd):
        return JsonResponse({
            'success': False,
            'error': 'bmc_ip and password are required',
            'error_type': 'param_error'
        })

    logger.info("Remote KVM request – IP=%s user=%s", bmc_ip, bmc_user)

    redfish_url = f"https://{bmc_ip}/redfish/v1/Managers/1/Oem/Supermicro/IKVM"

    try:
        response = requests.get(
            redfish_url,
            auth=(bmc_user, bmc_pwd),
            verify=False,
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        logger.error("Redfish request failed: %s", exc)
        return JsonResponse({
            'success': False,
            'error': f'Failed to contact BMC: {exc}',
            'error_type': 'connection_error'
        })

    if response.status_code != 200:
        return JsonResponse({
            'success': False,
            'error': f'Redfish API error (status {response.status_code})',
            'details': response.text[:200],
            'error_type': 'redfish_error'
        })

    ikvm_url = response.json().get('URI')
    if not ikvm_url:
        return JsonResponse({
            'success': False,
            'error': 'KVM URI not present in Redfish response',
            'error_type': 'redfish_parse_error'
        })

    full_url = f"https://{bmc_ip}{ikvm_url}"
    return JsonResponse({'success': True, 'kvm_url': full_url})


# ---------------------------------------------------------------------------
# SOL                                                                          
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def remote_start_sol(request):
    """Return a URL to the web-based SOL console for the provided BMC."""
    try:
        data = json.loads(request.body.decode())
    except Exception:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON payload',
            'error_type': 'payload_error'
        })

    bmc_ip = data.get('bmc_ip')
    bmc_user = data.get('username', 'ADMIN')
    bmc_pwd = data.get('password', '')

    if not (bmc_ip and bmc_pwd):
        return JsonResponse({
            'success': False,
            'error': 'bmc_ip and password are required',
            'error_type': 'param_error'
        })

    # Build a signed/encoded query string so we don't expose passwords in clear
    # This is still plain text but at least URL-safe. Consider switching to
    # Django sessions if stronger security is needed.
    query = urllib.parse.urlencode({
        'bmc_ip': bmc_ip,
        'bmc_user': bmc_user,
        'bmc_pwd': bmc_pwd,
        'session': uuid.uuid4().hex[:8],
    })

    sol_url = reverse('remote_sol_terminal') + f'?{query}'
    return JsonResponse({'success': True, 'sol_terminal_url': sol_url})


@login_required
@require_http_methods(["GET"])
def remote_sol_terminal(request):
    """Render the SOL terminal page for Remote Control.

    Expects *bmc_ip*, *bmc_user*, *bmc_pwd* query parameters.
    """
    bmc_ip = request.GET.get('bmc_ip')
    bmc_user = request.GET.get('bmc_user', 'ADMIN')
    bmc_pwd = request.GET.get('bmc_pwd', '')
    session_id = request.GET.get('session', 'remote')

    if not (bmc_ip and bmc_pwd):
        return render(request, 'sol_terminal.html', {
            'error': 'Missing connection parameters',
            'folder_name': session_id,
        })

    # Build websocket URL using proper scheme
    ws_scheme = "wss" if request.is_secure() else "ws"
    websocket_url = ws_scheme + "://" + request.get_host() + "/ws/remote-sol/?" + urllib.parse.urlencode({
        'bmc_ip': bmc_ip,
        'bmc_user': bmc_user,
        'bmc_pwd': bmc_pwd,
        'session': session_id,
    })

    context = {
        'folder_name': session_id,
        'bmc_ip': bmc_ip,
        'bmc_user': bmc_user,
        'websocket_url': websocket_url,
        'system_name': bmc_ip,
    }
    return render(request, 'sol_terminal.html', context) 