from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
import logging
import re
import requests
import xml.etree.ElementTree as ET
from ..form import UniquePasswordForm

logger = logging.getLogger(__name__)

def normalize_mac_address(mac_address):
    """Normalize MAC address to format without separators"""
    # Remove any separators and convert to lowercase
    mac = re.sub(r'[^a-fA-F0-9]', '', mac_address.lower())
    if len(mac) != 12:
        raise ValueError("Invalid MAC address length")
    return mac

def get_unique_password(bmc_mac):
    """Get unique password from Supermicro API"""
    try:
        # Normalize MAC address
        normalized_mac = normalize_mac_address(bmc_mac)
        
        # Supermicro API endpoint
        api_url = f"https://wcfds.supermicro.com:33330/prnstd006/IpmiMacVerif.svc/IpmiMacInfo/TrgtMac={normalized_mac}"
        
        # Make API request
        response = requests.get(api_url)
        
        if response.status_code == 200:
            # Parse XML response
            xml_str = response.text
            root = ET.fromstring(xml_str)
            
            # Extract values using XML namespaces
            ns = {'ns': 'http://schemas.datacontract.org/2004/07/'}
            
            # Find elements with safe None handling
            password_elem = root.find('.//ns:DefPasswd', ns)
            proc_msg_elem = root.find('.//ns:ProcMsg', ns)
            proc_st_elem = root.find('.//ns:ProcSt', ns)
            
            # Extract text values safely
            password = password_elem.text if password_elem is not None else None
            proc_msg = proc_msg_elem.text if proc_msg_elem is not None else None
            proc_st = proc_st_elem.text if proc_st_elem is not None else None
            
            if proc_st == 'S' and password:
                return {
                    'success': True,
                    'password': password,
                    'message': proc_msg or 'Password retrieved successfully'
                }
            else:
                return {
                    'success': False,
                    'message': proc_msg or 'Failed to retrieve password from Supermicro API'
                }
        else:
            return {
                'success': False,
                'message': f'API request failed with status code: {response.status_code}'
            }
            
    except ValueError as e:
        return {
            'success': False,
            'message': str(e)
        }
    except ET.ParseError as e:
        logger.error(f"Error parsing XML response: {str(e)}")
        return {
            'success': False,
            'message': 'Failed to parse API response'
        }
    except Exception as e:
        logger.error(f"Error in unique password lookup: {str(e)}")
        return {
            'success': False,
            'message': 'An unexpected error occurred'
        }

@login_required
def handle_unique_password_request(request):
    """Handle unique password lookup request"""
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Only POST method is allowed'})
        
    unique_password_form = UniquePasswordForm(request.POST)
    
    if not unique_password_form.is_valid():
        return JsonResponse({
            'success': False,
            'message': 'Invalid form data'
        })
        
    try:
        bmc_mac = unique_password_form.cleaned_data['bmc_mac']
        password_result = get_unique_password(bmc_mac)
        return JsonResponse(password_result)
        
    except Exception as e:
        logger.error(f"Error in unique password lookup: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'An unexpected error occurred'
        }) 