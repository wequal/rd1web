import os
import logging
from .views.system_details import get_file_content, parse_sysconfig

logger = logging.getLogger(__name__)
BASE_DIR = '/srv/log'


def get_system_sysconfig(folder_name: str):
    """Return parsed sysconfig for *folder_name* or *None* if missing."""
    log_dir = os.path.join(BASE_DIR, folder_name)
    if not os.path.exists(log_dir):
        logger.error("Log directory not found: %s", log_dir)
        return None

    sysconfig_path = os.path.join(log_dir, 'sysconfig')
    sysconfig_content = get_file_content(sysconfig_path)
    if not sysconfig_content:
        logger.error("Failed to read sysconfig file: %s", sysconfig_path)
        return None

    config = parse_sysconfig(sysconfig_content)
    logger.info("Loaded sysconfig for %s: BMC IP = %s", folder_name, config.get('bmc_ip', 'N/A'))
    return config 