import os
import logging
import requests
import warnings
from typing import Optional
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings for BMC connections
warnings.filterwarnings('ignore', category=InsecureRequestWarning)

logger = logging.getLogger(__name__)

class KVMSession:
    """Simple KVM session manager that generates BMC iKVM URLs.
    
    This class provides a simple interface to get BMC iKVM URLs using the Redfish API.
    The actual KVM interface is handled by the BMC's HTML5 iKVM implementation.
    """

    def __init__(self, folder_name: str, bmc_ip: str, bmc_user: str, bmc_pwd: str) -> None:
        self.folder_name = folder_name
        self.bmc_ip = bmc_ip
        self.bmc_user = bmc_user
        self.bmc_pwd = bmc_pwd
        
        # Session state
        self.kvm_url: Optional[str] = None
        self.session_id = f"kvm_{folder_name}"
        
    def get_kvm_url(self) -> Optional[str]:
        """Get KVM URL from BMC Redfish API"""
        try:
            redfish_url = f"https://{self.bmc_ip}/redfish/v1/Managers/1/Oem/Supermicro/IKVM"
            
            response = requests.get(
                redfish_url,
                auth=(self.bmc_user, self.bmc_pwd),
                verify=False,
                timeout=10
            )
            
            if response.status_code == 200:
                ikvm_data = response.json()
                ikvm_uri = ikvm_data.get('URI', '')
                if ikvm_uri:
                    self.kvm_url = f"https://{self.bmc_ip}{ikvm_uri}"
                    logger.info(f"Retrieved KVM URL for {self.folder_name}: {self.kvm_url}")
                    return self.kvm_url
            
            logger.error(f"Failed to get KVM URL: HTTP {response.status_code}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting KVM URL for {self.folder_name}: {str(e)}")
            return None
    
    def start(self) -> bool:
        """Start KVM session (just get the URL)"""
        logger.info(f"Getting KVM URL for {self.folder_name} (BMC: {self.bmc_ip})")
        return self.get_kvm_url() is not None
    
    def get_status(self) -> dict:
        """Get session status information"""
        return {
            'session_id': self.session_id,
            'folder_name': self.folder_name,
            'bmc_ip': self.bmc_ip,
            'kvm_url': self.kvm_url,
            'running': self.kvm_url is not None
        }
    
    def cleanup(self) -> None:
        """Clean up session (nothing to clean up for simple URL-based approach)"""
        logger.info(f"KVM session cleanup for {self.folder_name} (no resources to clean)")
    
    # Legacy aliases for compatibility
    def start_kvm_process(self) -> bool:
        return self.start()
    
    def get_websocket_url(self, host: str = 'localhost') -> str:
        # Not applicable for direct BMC access
        return ""
    
    def get_kvm_websocket_url(self, host: str = 'localhost') -> str:
        # Not applicable for direct BMC access  
        return "" 