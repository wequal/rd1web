"""
Context processors for template context variables.
"""

from django.conf import settings


def sidebar_hide(request):
    """
    Context processor that determines if system management sections should be hidden.
    - If RD1PXE equals "on", hide System Management section
    - If MAC2IP equals "on", hide MAC to IP link
    """
    # Check if rd1pxe parameter equals "on" to hide System Management
    hide_system_management = (settings.RD1PXE is not None and 
                              settings.RD1PXE.lower() == "on")
    
    # Check if mac2ip parameter equals "on" to hide MAC to IP link
    hide_mac_to_ip = (settings.MAC2IP is not None and 
                      settings.MAC2IP.lower() == "on")
    
    return {
        'hide_system_management': hide_system_management,
        'hide_mac_to_ip': hide_mac_to_ip,
    }

