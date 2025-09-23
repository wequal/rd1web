import json
import os
import re
from django.shortcuts import render, get_object_or_404
from django.http import Http404
from django.contrib.auth.decorators import login_required, permission_required
from datetime import datetime

BASE_DIR = '/srv/log'

def parse_lscpu(content):
    """Parse lscpu output into structured data"""
    data = {}
    for line in content.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            data[key.strip()] = value.strip()
    return data

def parse_lsblk(content):
    """Parse lsblk output into structured data"""
    lines = content.strip().split('\n')
    if not lines:
        return []
    
    devices = []
    for line in lines[1:]:  # Skip header
        parts = line.split()
        if len(parts) >= 6:
            devices.append({
                'name': parts[0],
                'maj_min': parts[1],
                'rm': parts[2],
                'size': parts[3],
                'ro': parts[4],
                'type': parts[5],
                'mountpoint': parts[6] if len(parts) > 6 else ''
            })
    return devices

def parse_display_info(content):
    """Parse display file for system information"""
    data = {}
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        if 'BMC:' in line:
            data['bmc_version'] = line.split('BMC:')[1].strip()
        elif 'BIOS:' in line:
            data['bios_version'] = line.split('BIOS:')[1].strip()
        elif 'CPLD' in line and 'CPLD_ID:' in line:
            data['cpld_version'] = line.split('CPLD_ID:')[1].strip()
        elif 'FPGA' in line and 'motherboard:' in line:
            data['fpga_version'] = line.split('motherboard:')[1].strip()
    
    return data

def parse_sysconfig(sysconfig_content):
    """Parse sysconfig file to extract BMC and network information"""
    config_info = {}
    
    if not sysconfig_content:
        return config_info
    
    lines = sysconfig_content.split('\n')
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Parse key=value pairs
        if '=' in line:
            key, value = line.split('=', 1)
            config_info[key.strip()] = value.strip()
    
    return config_info

def get_file_content(file_path):
    """Safely read file content"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except:
        return None

def get_json_content(file_path):
    """Safely read JSON file content"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None

def parse_fru_content(fru_content):
    """Parse FRU content into structured data - improved version"""
    fru_info = {}
    
    if not fru_content:
        return fru_info
    
    lines = fru_content.split('\n')
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Parse key-value pairs separated by ':'
        if ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                
                # Skip empty or meaningless values
                if value and value.lower() not in ['n/a', 'not available', 'unknown', '', 'not specified', 'to be filled by o.e.m.']:
                    fru_info[key] = value
    
    return fru_info

def determine_test_type_from_folder_name(folder_name):
    """Determine test type from folder name prefix"""
    folder_lower = folder_name.lower()
    
    if folder_lower.startswith('burnin-'):
        return 'BurnIn'
    elif folder_lower.startswith('dc-'):
        return 'DC'
    elif folder_lower.startswith('ac-'):
        return 'AC'
    else:
        return 'Unknown'

def extract_mac_from_folder_name(folder_name):
    """Extract MAC address from folder name"""
    # Remove test type prefix and extract MAC
    if folder_name.startswith('burnin-'):
        return folder_name[7:]  # Remove 'burnin-'
    elif folder_name.startswith('dc-'):
        return folder_name[3:]  # Remove 'dc-'
    elif folder_name.startswith('ac-'):
        return folder_name[3:]  # Remove 'ac-'
    else:
        return folder_name

def parse_tests_file(tests_content):
    """Parse the tests file to get current test status for BurnIn"""
    test_status = {}
    current_tests = set()
    
    if not tests_content:
        return test_status, current_tests
    
    lines = tests_content.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Parse format: "MM/DD/YYYY HH:MM:SS TestName Start/End"
        parts = line.split()
        if len(parts) >= 4:
            test_name = parts[2].upper()
            action = parts[3].upper()
            
            if action == 'START':
                current_tests.add(test_name)
                test_status[test_name] = 'RUNNING'
            elif action == 'END':
                if test_name in current_tests:
                    current_tests.remove(test_name)
                    test_status[test_name] = 'COMPLETED'
    
    return test_status, current_tests

def filter_valid_cycles(cycles):
    """Filter out cycle 0 and invalid cycles"""
    valid_cycles = []
    for cycle_line in cycles:
        if cycle_line.strip():
            # Extract cycle number from the last part of the line
            parts = cycle_line.split()
            if len(parts) >= 3:  # Need at least date, time, and cycle number
                try:
                    cycle_num = int(parts[-1])  # Last part is the cycle number
                    if cycle_num > 0:  # Exclude cycle 0
                        valid_cycles.append(cycle_line)
                except:
                    # If we can't parse the cycle number, include it anyway
                    valid_cycles.append(cycle_line)
            else:
                valid_cycles.append(cycle_line)
    return valid_cycles

def determine_test_type_and_status(log_dir, folder_name):
    """Determine test type and status from folder name and log files"""
    test_info = {
        'test_type': 'Unknown',
        'status': 'Unknown',
        'progress': 0,
        'details': {},
        'current_tests': set()
    }
    
    # First, determine test type from folder name
    test_info['test_type'] = determine_test_type_from_folder_name(folder_name)
    
    if test_info['test_type'] == 'BurnIn':
        # Read tests file for current status
        tests_path = os.path.join(log_dir, 'tests')
        tests_content = get_file_content(tests_path)
        
        if tests_content:
            test_status, current_tests = parse_tests_file(tests_content)
            test_info['details'] = test_status
            test_info['current_tests'] = current_tests
            
            # Determine overall status
            if current_tests:
                test_info['status'] = 'RUNNING'
                test_info['current_test'] = ', '.join(current_tests)
            elif test_status:
                # Check if all tests completed
                completed_tests = [test for test, status in test_status.items() if status == 'COMPLETED']
                if completed_tests:
                    test_info['status'] = 'COMPLETED'
                else:
                    test_info['status'] = 'UNKNOWN'
            else:
                test_info['status'] = 'UNKNOWN'
        
        # Also check individual log files for more detailed status
        burnin_files = ['SAT.log', 'iperf.log', 'stress.log', 'fio.log', 'dcgm.log', 'NV_GPU.log']
        log_status = {}
        
        for test_file in burnin_files:
            test_path = os.path.join(log_dir, test_file)
            if os.path.exists(test_path):
                test_name = test_file.replace('.log', '').upper()
                content = get_file_content(test_path)
                if content:
                    lines = content.strip().split('\n')
                    last_lines = lines[-20:] if len(lines) > 20 else lines
                    
                    # Change PASS to COMPLETED for BurnIn tests
                    if any('PASS' in line.upper() or 'SUCCESS' in line.upper() for line in last_lines):
                        log_status[test_name] = 'COMPLETED'
                    elif any('FAIL' in line.upper() or 'ERROR' in line.upper() for line in last_lines):
                        log_status[test_name] = 'FAIL'
                    else:
                        log_status[test_name] = 'RUNNING'
        
        # Merge log status with tests file status
        for test_name, status in log_status.items():
            test_info['details'][test_name] = status
    
    elif test_info['test_type'] == 'DC':
        # Check DC test status
        dc_result_path = os.path.join(log_dir, 'DC_result.txt')
        cycle_count_path = os.path.join(log_dir, 'cycle_count')
        cycle_flag_path = os.path.join(log_dir, 'cycle_flag.txt')
        
        if os.path.exists(dc_result_path):
            dc_result = get_file_content(dc_result_path)
            if dc_result:
                test_info['status'] = dc_result.strip().upper()
        
        # Get cycle information - Fixed to exclude cycle 0
        if os.path.exists(cycle_count_path):
            cycle_content = get_file_content(cycle_count_path)
            if cycle_content:
                all_cycles = [line.strip() for line in cycle_content.split('\n') if line.strip()]
                # Filter out cycle 0
                valid_cycles = filter_valid_cycles(all_cycles)
                current_cycle = len(valid_cycles)  # Number of valid completed cycles
                
                total_cycles = current_cycle  # Default fallback
                if os.path.exists(cycle_flag_path):
                    cycle_flag = get_file_content(cycle_flag_path)
                    if cycle_flag:
                        try:
                            total_cycles = int(cycle_flag.strip())
                        except:
                            pass
                
                test_info['details'] = {
                    'current_cycle': current_cycle,
                    'total_cycles': total_cycles,
                    'remaining_cycles': max(0, total_cycles - current_cycle),
                    'cycles_completed': valid_cycles,
                    'all_cycles': all_cycles
                }
                
                # Fixed progress calculation: current/total * 100
                if total_cycles > 0:
                    test_info['progress'] = min(100, (current_cycle / total_cycles) * 100)
                
                # Better status determination
                if current_cycle >= total_cycles:
                    test_info['status'] = 'COMPLETED'
                elif current_cycle > 0:
                    test_info['status'] = 'RUNNING'
                else:
                    test_info['status'] = 'STARTING'
        
        if test_info['status'] == 'Unknown':
            test_info['status'] = 'RUNNING'
    
    elif test_info['test_type'] == 'AC':
        # AC test logic - similar to DC but check for AC-specific files
        # First check AC_result.txt for explicit status (similar to DC_result.txt)
        ac_result_path = os.path.join(log_dir, 'AC_result.txt')
        cycle_count_path = os.path.join(log_dir, 'cycle_count')
        cycle_flag_path = os.path.join(log_dir, 'cycle_flag.txt')
        
        if os.path.exists(ac_result_path):
            ac_result = get_file_content(ac_result_path)
            if ac_result:
                test_info['status'] = ac_result.strip().upper()
        
        # Check for cycle information similar to DC
        if os.path.exists(cycle_count_path):
            cycle_content = get_file_content(cycle_count_path)
            if cycle_content:
                all_cycles = [line.strip() for line in cycle_content.split('\n') if line.strip()]
                # Filter out cycle 0
                valid_cycles = filter_valid_cycles(all_cycles)
                current_cycle = len(valid_cycles)
                
                total_cycles = current_cycle
                if os.path.exists(cycle_flag_path):
                    cycle_flag = get_file_content(cycle_flag_path)
                    if cycle_flag:
                        try:
                            total_cycles = int(cycle_flag.strip())
                        except:
                            pass
                
                test_info['details'] = {
                    'current_cycle': current_cycle,
                    'total_cycles': total_cycles,
                    'remaining_cycles': max(0, total_cycles - current_cycle),
                    'cycles_completed': valid_cycles,
                    'all_cycles': all_cycles
                }
                
                if total_cycles > 0:
                    test_info['progress'] = min(100, (current_cycle / total_cycles) * 100)
                
                if current_cycle >= total_cycles:
                    test_info['status'] = 'COMPLETED'
                elif current_cycle > 0:
                    test_info['status'] = 'RUNNING'
                else:
                    test_info['status'] = 'STARTING'
        
        # Add additional file detection for AC tests to be more robust
        if test_info['status'] == 'Unknown':
            # Check for any AC-related log files that indicate the test is running
            ac_indicator_files = ['ac_power.log', 'pdu.log', 'power_cycle.log', 'run', 'display']
            ac_files_found = any(os.path.exists(os.path.join(log_dir, f)) for f in ac_indicator_files)
            
            if ac_files_found:
                test_info['status'] = 'RUNNING'
    
    return test_info

@login_required
@permission_required('pxe.can_use_system_management', raise_exception=True)
def system_details(request, mac):
    """Display comprehensive system details for a given MAC address"""
    # The mac parameter might be the original folder name, so we need to handle both cases
    original_mac = mac
    
    # Determine log directory (check archive fallback)
    log_dir = os.path.join(BASE_DIR, mac)
    if not os.path.exists(log_dir):
        log_dir = os.path.join(BASE_DIR, 'archive', mac)
    
    # Try to find the folder - it could be the direct folder name or need reconstruction
    possible_folders = []
    
    # Try direct match first
    direct_path = log_dir
    if os.path.exists(direct_path):
        folder_name = mac
    else:
        # Look for folders containing this MAC
        if os.path.exists(log_dir):
            for item in os.listdir(log_dir):
                item_path = os.path.join(log_dir, item)
                if os.path.isdir(item_path):
                    # Extract MAC from folder name and compare
                    extracted_mac = extract_mac_from_folder_name(item)
                    if extracted_mac.lower().replace(':', '-').replace('_', '-') == mac.lower().replace(':', '-').replace('_', '-'):
                        possible_folders.append((item_path, item))
        
        if possible_folders:
            log_dir, folder_name = possible_folders[0]  # Use the first match
        else:
            raise Http404(f"System logs not found for MAC: {mac}")
    
    # Format MAC address for display
    formatted_mac = extract_mac_from_folder_name(folder_name).replace('-', ':').upper()
    
    # Relative path (within BASE_DIR) to this system's log directory
    log_path = os.path.relpath(log_dir, BASE_DIR)

    context = {
        'mac': original_mac,
        'formatted_mac': formatted_mac,
        'folder_name': folder_name,
        'log_path': log_path,
        'last_updated': None,
        'system_info': {},
        'hardware_info': {},
        'firmware_info': {},
        'cpu_info': {},
        'memory_info': {},
        'storage_info': [],
        'network_info': [],
        'pci_devices': [],

        'fru_info': {},
        'test_info': {},
        'error': None
    }
    
    try:
        # Get last update time from various files
        update_files = ['display', 'hw_info.json', 'fw_info.json', 'run']
        latest_time = None
        
        for update_file in update_files:
            file_path = os.path.join(log_dir, update_file)
            if os.path.exists(file_path):
                try:
                    stat = os.stat(file_path)
                    file_time = datetime.fromtimestamp(stat.st_mtime)
                    if latest_time is None or file_time > latest_time:
                        latest_time = file_time
                except:
                    pass
        
        context['last_updated'] = latest_time
        
        # Determine test type and status
        context['test_info'] = determine_test_type_and_status(log_dir, folder_name)
        
        # Parse sysconfig for BMC and network information
        sysconfig_path = os.path.join(log_dir, 'sysconfig')
        sysconfig_content = get_file_content(sysconfig_path)
        if sysconfig_content:
            context['sysconfig'] = parse_sysconfig(sysconfig_content)
        else:
            context['sysconfig'] = {}
        
        # Parse hardware info JSON
        hw_info_path = os.path.join(log_dir, 'hw_info.json')
        hw_info = get_json_content(hw_info_path)
        if hw_info:
            context['hardware_info'] = hw_info
        
        # Parse firmware info JSON
        fw_info_path = os.path.join(log_dir, 'fw_info.json')
        fw_info = get_json_content(fw_info_path)
        if fw_info:
            context['firmware_info'] = fw_info
        
        # Parse display info
        display_path = os.path.join(log_dir, 'display')
        display_content = get_file_content(display_path)
        if display_content:
            context['system_info'] = parse_display_info(display_content)
        
        # Parse CPU info
        lscpu_path = os.path.join(log_dir, 'sysinfo', 'lscpu.log')
        lscpu_content = get_file_content(lscpu_path)
        if lscpu_content:
            context['cpu_info'] = parse_lscpu(lscpu_content)
        
        # Parse FRU information with better error handling
        fru_path = os.path.join(log_dir, 'sysinfo', 'fru')
        fru_content = get_file_content(fru_path)
        
        context['fru_info'] = {}  # Initialize empty dict
        
        if fru_content and fru_content.strip():
            context['fru_info'] = parse_fru_content(fru_content)
        
        # If FRU is empty or not available, try dmidecode as fallback
        if not context['fru_info']:
            dmidecode_path = os.path.join(log_dir, 'sysinfo', 'dmidecode.log')
            dmidecode_content = get_file_content(dmidecode_path)
            if dmidecode_content:
                fru_info = {}
                current_section = None
                
                for line in dmidecode_content.split('\n'):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    # Look for DMI sections
                    if line.endswith('Information') and not line.startswith('\t'):
                        current_section = line
                        fru_info[current_section] = {}
                    elif current_section and line.startswith('\t') and ':' in line:
                        # Parse key-value pairs within sections
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip()
                            if value and value not in ['Not Specified', 'Not Present', 'Unknown', '', 'To Be Filled By O.E.M.']:
                                fru_info[current_section][key] = value
                
                # Only use dmidecode if we found useful information
                if any(fru_info.values()):
                    # Flatten the dmidecode structure for simpler display
                    flattened_fru = {}
                    for section, data in fru_info.items():
                        if isinstance(data, dict):
                            for key, value in data.items():
                                flattened_fru[f"{section} - {key}"] = value
                    context['fru_info'] = flattened_fru
        
        # Parse storage info from hw_info.json
        if hw_info and 'drive' in hw_info:
            storage_devices = []
            drive_data = hw_info['drive']
            
            # Handle different data structures
            if isinstance(drive_data, dict):
                # If drive_data is a dictionary, iterate over its items
                for drive_key, drive_info in drive_data.items():
                    if isinstance(drive_info, dict):
                        storage_devices.append({
                            'name': drive_key,
                            'size': drive_info.get('Capacity', drive_info.get('size', 'Unknown')),
                            'type': drive_info.get('type', 'Unknown'),
                            'model': drive_info.get('Model', drive_info.get('model', 'Unknown')),
                            'serial': drive_info.get('SN', drive_info.get('serial', 'Unknown')),
                            'interface': drive_info.get('interface', 'Unknown'),
                            'firmware': drive_info.get('FW', 'Unknown')
                        })
            elif isinstance(drive_data, list):
                # If drive_data is a list, iterate over the list
                for drive_info in drive_data:
                    if isinstance(drive_info, dict):
                        storage_devices.append({
                            'name': drive_info.get('name', 'Unknown'),
                            'size': drive_info.get('Capacity', drive_info.get('size', 'Unknown')),
                            'type': drive_info.get('type', 'Unknown'),
                            'model': drive_info.get('Model', drive_info.get('model', 'Unknown')),
                            'serial': drive_info.get('SN', drive_info.get('serial', 'Unknown')),
                            'interface': drive_info.get('interface', 'Unknown'),
                            'firmware': drive_info.get('FW', 'Unknown')
                        })
            
            context['storage_info'] = storage_devices
        
        # Parse PCI devices with proper address formatting
        lspci_path = os.path.join(log_dir, 'sysinfo', 'lspci.log')
        lspci_content = get_file_content(lspci_path)
        if lspci_content:
            pci_devices = []
            for line in lspci_content.split('\n'):
                if line.strip():
                    # Parse format: "0000:01:00.0 Ethernet controller: Intel Corporation..."
                    parts = line.split(' ', 1)
                    if len(parts) >= 2:
                        address = parts[0].strip()
                        description = parts[1].strip()
                        
                        # Normalize address format
                        if ':' in address:
                            addr_parts = address.split(':')
                            if len(addr_parts) == 3:
                                # Ensure proper formatting: 0000:01:00.0
                                domain = addr_parts[0].zfill(4)
                                bus = addr_parts[1].zfill(2)
                                device_func = addr_parts[2]
                                address = ':'.join([domain, bus, device_func])
                        
                        pci_devices.append({
                            'address': address,
                            'description': description
                        })
            context['pci_devices'] = pci_devices
        
        # Enhanced PCIe data with file paths from pcie folder
        pcie_dir = os.path.join(log_dir, 'pcie')
        if os.path.exists(pcie_dir) and 'hardware_info' in context and 'lspci' in context['hardware_info']:
            # Add file paths to existing lspci data
            for address, pci_info in context['hardware_info']['lspci'].items():
                # Check if corresponding file exists in pcie folder
                pcie_file_path = os.path.join(pcie_dir, address)
                if os.path.isfile(pcie_file_path):
                    pci_info['has_file'] = True
                    pci_info['file_url'] = f"/systems/{folder_name}/pcie/{address}"
                else:
                    pci_info['has_file'] = False
        
        # Parse USB devices
        lsusb_path = os.path.join(log_dir, 'sysinfo', 'lsusb.log')
        lsusb_content = get_file_content(lsusb_path)
        if lsusb_content:
            usb_devices = []
            for line in lsusb_content.split('\n'):
                if line.strip() and 'Bus' in line:
                    usb_devices.append(line.strip())
            context['usb_devices'] = usb_devices
        
        # Parse DC test result
        dc_result_path = os.path.join(log_dir, 'DC_result.txt')
        dc_result_content = get_file_content(dc_result_path)
        if dc_result_content:
            test_status = dc_result_content.strip().upper()
            context['test_status'] = test_status
        
        # Parse sensor data
        sdr_path = os.path.join(log_dir, 'sysinfo', 'sdr.log')
        sdr_content = get_file_content(sdr_path)
        if sdr_content:
            sensors = []
            for line in sdr_content.split('\n'):
                if line.strip() and '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 3:
                        sensors.append({
                            'name': parts[0],
                            'value': parts[1],
                            'status': parts[2] if len(parts) > 2 else 'N/A'
                        })
            context['sensors'] = sensors
        
    except Exception as e:
        context['error'] = str(e)
    
    return render(request, 'features/system_details.html', context)

# ------------------------------------------------------------------
# Helper to build system lists (extracted for reuse by APIs)
# ------------------------------------------------------------------

def get_systems_data():
    """Scan BASE_DIR and return dict with categorized systems."""
    systems = {
        'burnin': [],
        'dc': [],
        'ac': [],
        'other': [],
        'archive': [],
    }

    try:
        # ---------------------------------------------------------
        # Live systems (everything except archive folder)
        # ---------------------------------------------------------
        if os.path.exists(BASE_DIR):
            for item in os.listdir(BASE_DIR):
                if item == 'archive':
                    continue
                item_path = os.path.join(BASE_DIR, item)
                if not os.path.isdir(item_path):
                    continue

                mac_address = extract_mac_from_folder_name(item)

                system_info = {
                    'mac': mac_address,
                    'folder_name': item,
                    'formatted_mac': mac_address.replace('-', ':').upper(),
                    'last_updated': None,
                    'status': 'Unknown',
                    'test_type': 'Unknown',
                    'sysconfig': {},
                }

                # Determine test type, progress & status
                test_info = determine_test_type_and_status(item_path, item)
                system_info.update({
                    'test_type': test_info['test_type'],
                    'status': test_info['status'],
                    'progress': test_info['progress'],
                    'test_details': test_info['details'],
                })

                # Current BurnIn tests
                if test_info['test_type'] == 'BurnIn' and test_info.get('current_tests'):
                    system_info['current_tests'] = test_info['current_tests']
                    system_info['current_test'] = ', '.join(test_info['current_tests'])

                # Sysconfig (BMC, LAN …)
                sysconfig_path = os.path.join(item_path, 'sysconfig')
                if (syscontent := get_file_content(sysconfig_path)):
                    system_info['sysconfig'] = parse_sysconfig(syscontent)

                # Last-updated timestamp & activity status
                latest_time = None
                for fname in ['display', 'hw_info.json', 'fw_info.json', 'run']:
                    fp = os.path.join(item_path, fname)
                    if os.path.exists(fp):
                        try:
                            ts = datetime.fromtimestamp(os.stat(fp).st_mtime)
                            if not latest_time or ts > latest_time:
                                latest_time = ts
                        except Exception:
                            pass

                if latest_time:
                    system_info['last_updated'] = latest_time
                    diff = datetime.now() - latest_time
                    if diff.total_seconds() < 3600:
                        system_info['activity_status'] = 'Online'
                    elif diff.total_seconds() < 86400:
                        system_info['activity_status'] = 'Recent'
                    else:
                        system_info['activity_status'] = 'Offline'
                else:
                    system_info['activity_status'] = 'Unknown'

                # Bucket into category
                category_key = system_info['test_type'].lower()
                systems.get(category_key, systems['other']).append(system_info)

        # ---------------------------------------------------------
        # Archive systems
        # ---------------------------------------------------------
        archive_dir = os.path.join(BASE_DIR, 'archive')
        if os.path.exists(archive_dir):
            for item in os.listdir(archive_dir):
                item_path = os.path.join(archive_dir, item)
                if not os.path.isdir(item_path):
                    continue

                mac_address = extract_mac_from_folder_name(item)
                sys_info = {
                    'mac': mac_address,
                    'folder_name': item,
                    'formatted_mac': mac_address.replace('-', ':').upper(),
                    'last_updated': None,
                    'status': 'Archived',
                    'test_type': 'Archived',
                    'sysconfig': {},
                    'activity_status': 'Offline',
                }

                sc_path = os.path.join(item_path, 'sysconfig')
                if (sc_content := get_file_content(sc_path)):
                    sys_info['sysconfig'] = parse_sysconfig(sc_content)

                try:
                    sys_info['last_updated'] = datetime.fromtimestamp(os.stat(item_path).st_mtime)
                except Exception:
                    pass

                systems['archive'].append(sys_info)

    except Exception:
        pass

    # Sort by last_updated desc in each bucket
    for cat in systems:
        systems[cat].sort(key=lambda x: x['last_updated'] or datetime.min, reverse=True)

    return systems

# ------------------------------------------------------------------
# Refactored view uses reusable helper
# ------------------------------------------------------------------

@login_required
@permission_required('pxe.can_use_system_management', raise_exception=True)
def system_list(request):
    systems = get_systems_data()
    return render(request, 'features/system_list.html', {'systems': systems}) 