"""
RMA Statistics Module

Contains functions for:
- Parsing test_results.log files
- Scanning RMA directories
- Aggregating statistics by time period
"""

import os
import re
import logging
import json
from datetime import datetime, timedelta
from django.db.models import Count, Q
from django.utils import timezone
from .models import RmaTestStatistic

logger = logging.getLogger(__name__)

# Debug logging helper
DEBUG_LOG_PATH = '/home/devin/rd1web-dev/.cursor/debug.log'
def _debug_log(hypothesis_id, location, message, data=None):
    try:
        log_entry = {
            'sessionId': 'debug-session',
            'runId': 'run1',
            'hypothesisId': hypothesis_id,
            'location': location,
            'message': message,
            'data': data or {},
            'timestamp': int(datetime.now().timestamp() * 1000)
        }
        with open(DEBUG_LOG_PATH, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception:
        pass  # Silently fail if logging fails

# Import configuration from local_config (required, no fallback)
from .local_config import RMA_BASE_DIR
logger.info("RMA statistics using RMA_BASE_DIR from local_config.py")


def parse_test_results_log(log_content):
    """
    Parse test_results.log content to determine test results
    
    Logic: If BOTH pass and fail patterns exist for a test, consider it PASSED
    (the final result wins - if it eventually passed, don't count as failure)
    
    Args:
        log_content (str): Content of test_results.log file
        
    Returns:
        dict: Test results with keys: gpu_detection, ecc_error, dcgm_test, fd2_test, agfhc_test
              Values: 'pass', 'fail', or 'unknown'
    """
    results = {
        'gpu_detection': 'unknown',
        'ecc_error': 'unknown',
        'dcgm_test': 'unknown',
        'dcgm_r4_test': 'unknown',
        'fd2_test': 'unknown',
        'agfhc_test': 'unknown',
    }
    
    if not log_content:
        return results
    
    # GPU Detection
    # For NVIDIA (H/B models): "Error: GPU count is not 8" vs "GPU count is 8"
    has_nvidia_gpu_fail = bool(re.search(r'Error: GPU count is not 8', log_content))
    has_nvidia_gpu_pass = bool(re.search(r'GPU count is 8', log_content))
    
    # For AMD (MI models): "0 GPUs detected" vs "8 GPUs detected"
    has_amd_gpu_fail = bool(re.search(r'0 GPUs detected', log_content))
    has_amd_gpu_pass = bool(re.search(r'8 GPUs detected', log_content))
    
    # Combine both patterns
    has_gpu_fail = has_nvidia_gpu_fail or has_amd_gpu_fail
    has_gpu_pass = has_nvidia_gpu_pass or has_amd_gpu_pass
    
    if has_gpu_pass and has_gpu_fail:
        results['gpu_detection'] = 'pass'  # Final result wins
    elif has_gpu_pass:
        results['gpu_detection'] = 'pass'
    elif has_gpu_fail:
        results['gpu_detection'] = 'fail'
    
    # ECC Error
    has_ecc_fail = bool(re.search(r'ECC error detected on GPU', log_content))
    has_ecc_pass = bool(re.search(r'No ECC error', log_content))
    
    if has_ecc_pass and has_ecc_fail:
        results['ecc_error'] = 'pass'  # Final result wins
    elif has_ecc_pass:
        results['ecc_error'] = 'pass'
    elif has_ecc_fail:
        results['ecc_error'] = 'fail'
    
    # DCGM Test - use last occurrence to determine final result
    dcgm_fail_matches = list(re.finditer(r'DCGM (LC|AC) test Failed', log_content))
    dcgm_pass_matches = list(re.finditer(r'DCGM (LC|AC) test Finished', log_content))
    
    if dcgm_fail_matches or dcgm_pass_matches:
        # Get position of last fail and last pass
        last_fail_pos = dcgm_fail_matches[-1].start() if dcgm_fail_matches else -1
        last_pass_pos = dcgm_pass_matches[-1].start() if dcgm_pass_matches else -1
        
        # Whichever comes last in the log is the final result
        if last_fail_pos > last_pass_pos:
            results['dcgm_test'] = 'fail'
        elif last_pass_pos > last_fail_pos:
            results['dcgm_test'] = 'pass'
    
    # DCGM R4 Test - use last occurrence to determine final result
    dcgm_r4_fail_matches = list(re.finditer(r'DCGM_R4 Failed', log_content))
    dcgm_r4_pass_matches = list(re.finditer(r'DCGM_R4 Passed', log_content))
    
    if dcgm_r4_fail_matches or dcgm_r4_pass_matches:
        # Get position of last fail and last pass
        last_fail_pos = dcgm_r4_fail_matches[-1].start() if dcgm_r4_fail_matches else -1
        last_pass_pos = dcgm_r4_pass_matches[-1].start() if dcgm_r4_pass_matches else -1
        
        # Whichever comes last in the log is the final result
        if last_fail_pos > last_pass_pos:
            results['dcgm_r4_test'] = 'fail'
        elif last_pass_pos > last_fail_pos:
            results['dcgm_r4_test'] = 'pass'
    
    # Field Diagnostic Level 2 Test
    has_fd2_fail = bool(re.search(r'Field Diagnostic level 2 test Failed', log_content))
    has_fd2_pass = bool(re.search(r'Field Diagnostic level 2 test Finished', log_content))
    
    if has_fd2_pass and has_fd2_fail:
        results['fd2_test'] = 'pass'  # Final result wins
    elif has_fd2_pass:
        results['fd2_test'] = 'pass'
    elif has_fd2_fail:
        results['fd2_test'] = 'fail'
    
    # AGFHC Test
    # Check for success: AGFHC_SUCCESS [0]
    has_agfhc_pass = bool(re.search(r'Program exiting with return code AGFHC_SUCCESS \[0\]', log_content))
    
    # Check for failure patterns (case-insensitive):
    # - "AGFHC Unable to Run"
    # - "unable to run AGFHC"
    # - Any AGFHC return code that's not [0]
    has_agfhc_unable = bool(re.search(r'unable to run AGFHC', log_content, re.IGNORECASE)) or \
                       bool(re.search(r'AGFHC Unable to Run', log_content, re.IGNORECASE))
    has_agfhc_fail_code = bool(re.search(r'Program exiting with return code AGFHC_\w+ \[(?!0\])', log_content))
    
    if has_agfhc_unable or has_agfhc_fail_code:
        results['agfhc_test'] = 'fail'
    elif has_agfhc_pass:
        results['agfhc_test'] = 'pass'
    else:
        # If no pattern found, mark as unknown (not necessarily a fail)
        results['agfhc_test'] = 'unknown'
    
    return results


def normalize_gpu_model(gpu_model):
    """
    Normalize GPU model names for consistent grouping
    
    Args:
        gpu_model (str): Original GPU model name
        
    Returns:
        str: Normalized GPU model name
    """
    if not gpu_model:
        return 'Unknown'
    
    # Combine MI325DLC and MI325X into MI325
    if gpu_model in ['MI325DLC', 'MI325X']:
        return 'MI325'
    
    return gpu_model


def parse_sys_info_file(sys_info_path):
    """
    Parse sys_info.txt to extract GPU model
    
    Args:
        sys_info_path (str): Path to sys_info.txt file
        
    Returns:
        str: GPU model or 'Unknown' (normalized)
    """
    try:
        if not os.path.exists(sys_info_path):
            return 'Unknown'
        
        with open(sys_info_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for GPU_Model: line
        match = re.search(r'GPU_Model:\s*(\S+)', content)
        if match:
            raw_model = match.group(1).strip()
            return normalize_gpu_model(raw_model)
        
        return 'Unknown'
    except Exception as e:
        logger.warning(f"Error parsing sys_info.txt at {sys_info_path}: {e}")
        return 'Unknown'


def scan_rma_directory(dir_name):
    """
    Scan a single RMA directory and update/create database record
    
    Args:
        dir_name (str): Directory name (e.g., "1660224656070_XD250311087")
        
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        # Parse directory name
        pattern = re.compile(r'^(.+)_(.+)$')
        match = pattern.match(dir_name)
        
        if not match:
            return False, f"Directory name doesn't match pattern: {dir_name}"
        
        base_sn, rma_number = match.groups()
        
        # Construct paths
        dir_path = os.path.join(RMA_BASE_DIR, dir_name)
        test_results_path = os.path.join(dir_path, 'test_results.log')
        sys_info_path = os.path.join(dir_path, 'sys_info.txt')
        
        # Check if directory exists
        if not os.path.exists(dir_path):
            return False, f"Directory not found: {dir_path}"
        
        # Check if test_results.log exists
        test_log_exists = os.path.exists(test_results_path)
        # #region agent log
        _debug_log('H2', 'rma_statistics.py:225', 'test_results.log exists check', {'dir_name': dir_name, 'exists': test_log_exists, 'path': test_results_path})
        # #endregion
        if not test_log_exists:
            return False, f"test_results.log not found in {dir_name}"
        
        # Get directory mtime for test_date
        try:
            dir_mtime = os.path.getmtime(dir_path)
        except Exception as e:
            return False, f"Cannot get mtime for directory: {e}"
        
        # Get test_results.log mtime for change detection
        try:
            file_mtime = os.path.getmtime(test_results_path)
        except Exception as e:
            return False, f"Cannot get mtime for test_results.log: {e}"
        
        log_content_cache = None

        def get_log_content():
            nonlocal log_content_cache
            if log_content_cache is None:
                with open(test_results_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content_cache = f.read()
            return log_content_cache
        
        # Use directory mtime for test_date
        try:
            test_date = datetime.fromtimestamp(dir_mtime)
            # Make it timezone aware
            test_date = timezone.make_aware(test_date)
            # #region agent log
            _debug_log('H5', 'rma_statistics.py:253', 'test_date calculated', {'dir_name': dir_name, 'test_date': test_date.isoformat(), 'dir_mtime': dir_mtime})
            # #endregion
        except Exception as e:
            logger.warning(f"Cannot get directory mtime, using current time: {e}")
            test_date = timezone.now()
            # #region agent log
            _debug_log('H5', 'rma_statistics.py:256', 'test_date fallback to now', {'dir_name': dir_name, 'test_date': test_date.isoformat()})
            # #endregion
        
        # Get GPU model
        gpu_model = parse_sys_info_file(sys_info_path)
        
        # Check if this directory already has a record with same file_mtime
        existing_record = RmaTestStatistic.objects.filter(
            directory_name=dir_name,
            file_mtime=file_mtime
        ).first()
        
        if existing_record:
            updates_needed = []
            
            # Always evaluate the latest log content so semantic changes (same mtime) are detected
            try:
                log_content = get_log_content()
            except Exception as e:
                return False, f"Cannot read test_results.log: {e}"
            
            new_test_results = parse_test_results_log(log_content)
            
            if new_test_results != existing_record.test_results:
                existing_record.test_results = new_test_results
                updates_needed.append('test_results')
            
            if existing_record.test_date != test_date:
                existing_record.test_date = test_date
                updates_needed.append('test_date')
            
            if existing_record.gpu_model != gpu_model:
                existing_record.gpu_model = gpu_model
                updates_needed.append('gpu_model')
            
            if existing_record.base_sn != base_sn:
                existing_record.base_sn = base_sn
                updates_needed.append('base_sn')
            
            if existing_record.rma_number != rma_number:
                existing_record.rma_number = rma_number
                updates_needed.append('rma_number')
            
            if updates_needed:
                # file_mtime might remain unchanged but keep it in sync regardless
                existing_record.file_mtime = file_mtime
                existing_record.save(update_fields=list(set(updates_needed + ['file_mtime', 'updated_at'])))
                return True, f"Updated existing record for: {dir_name}"
            else:
                return True, f"Skipped (already recorded): {dir_name}"
        
        # Read test_results.log
        try:
            log_content = get_log_content()
        except Exception as e:
            return False, f"Cannot read test_results.log: {e}"
        
        # Parse test results
        test_results = parse_test_results_log(log_content)
        
        # Create or update record - ensure only one record per directory
        # #region agent log
        _debug_log('H5', 'rma_statistics.py:316', 'About to create/update DB record', {
            'dir_name': dir_name,
            'test_date': test_date.isoformat(),
            'gpu_model': gpu_model,
            'file_mtime': file_mtime
        })
        # #endregion
        obj, created = RmaTestStatistic.objects.update_or_create(
            directory_name=dir_name,
            defaults={
                'base_sn': base_sn,
                'rma_number': rma_number,
                'gpu_model': gpu_model,
                'test_date': test_date,
                'test_results': test_results,
                'file_mtime': file_mtime,
            }
        )
        # #region agent log
        _debug_log('H5', 'rma_statistics.py:328', 'DB record created/updated', {
            'dir_name': dir_name,
            'created': created,
            'record_id': obj.id if obj else None,
            'test_date': obj.test_date.isoformat() if obj else None
        })
        # #endregion
        
        return True, f"Updated: {dir_name} ({gpu_model})"
        
    except Exception as e:
        logger.error(f"Error scanning directory {dir_name}: {e}")
        return False, f"Error: {str(e)}"


def scan_all_rma_directories():
    """
    Scan all RMA directories and update statistics database
    Uses directory modification time for test_date
    Only creates new records when test_results.log changes
    
    Returns:
        dict: Statistics about the scan (processed, skipped, errors)
    """
    # #region agent log
    _debug_log('H1,H2,H3,H4', 'rma_statistics.py:335', 'scan_all_rma_directories ENTRY', {'rma_base_dir': RMA_BASE_DIR})
    # #endregion
    stats = {
        'total': 0,
        'processed': 0,
        'skipped': 0,
        'errors': 0,
        'error_messages': [],
    }
    
    try:
        # Check if RMA base directory exists
        dir_exists = os.path.exists(RMA_BASE_DIR)
        # #region agent log
        _debug_log('H3', 'rma_statistics.py:354', 'Directory exists check', {'exists': dir_exists, 'path': RMA_BASE_DIR})
        # #endregion
        if not dir_exists:
            logger.error(f"RMA base directory not found: {RMA_BASE_DIR}")
            # #region agent log
            _debug_log('H3', 'rma_statistics.py:356', 'Directory not found - returning early', {})
            # #endregion
            return stats
        
        # Get all directories
        try:
            items = os.listdir(RMA_BASE_DIR)
            # #region agent log
            _debug_log('H1,H2', 'rma_statistics.py:360', 'Directory listing result', {'item_count': len(items), 'sample_items': items[:5] if items else []})
            # #endregion
        except Exception as e:
            logger.error(f"Cannot list RMA directory: {e}")
            # #region agent log
            _debug_log('H3', 'rma_statistics.py:362', 'Directory listing failed', {'error': str(e)})
            # #endregion
            return stats
        
        # Pattern to match {base_sn}_{rma_number}
        pattern = re.compile(r'^(.+)_(.+)$')
        
        total_dirs = 0
        total_files = 0
        non_matching = 0
        matching = 0
        
        # Process each directory
        for item in items:
            item_path = os.path.join(RMA_BASE_DIR, item)
            
            # Skip non-directories
            is_dir = os.path.isdir(item_path)
            if not is_dir:
                total_files += 1
                continue
            
            total_dirs += 1
            
            # Check if it matches pattern
            matches_pattern = bool(pattern.match(item))
            # #region agent log
            _debug_log('H1', 'rma_statistics.py:377', 'Pattern match check', {'item': item, 'matches': matches_pattern})
            # #endregion
            if not matches_pattern:
                non_matching += 1
                continue
            
            matching += 1
            stats['total'] += 1
            
            # Scan directory
            # #region agent log
            _debug_log('H2,H4', 'rma_statistics.py:383', 'About to scan directory', {'dir_name': item})
            # #endregion
            success, message = scan_rma_directory(item)
            # #region agent log
            _debug_log('H2,H4', 'rma_statistics.py:385', 'Directory scan result', {'dir_name': item, 'success': success, 'message': message})
            # #endregion
            
            if success:
                if 'Skipped' in message:
                    stats['skipped'] += 1
                else:
                    stats['processed'] += 1
            else:
                stats['errors'] += 1
                stats['error_messages'].append(message)
                logger.warning(f"Scan error: {message}")
        
        # #region agent log
        _debug_log('H1,H2,H3,H4', 'rma_statistics.py:395', 'Scan summary', {
            'total_items': len(items),
            'total_dirs': total_dirs,
            'total_files': total_files,
            'matching_pattern': matching,
            'non_matching': non_matching,
            'processed': stats['processed'],
            'skipped': stats['skipped'],
            'errors': stats['errors']
        })
        # #endregion
        logger.info(f"RMA statistics scan complete: {stats['processed']} processed, "
                   f"{stats['skipped']} skipped, {stats['errors']} errors out of {stats['total']} total")
        
    except Exception as e:
        logger.error(f"Error in scan_all_rma_directories: {e}")
        # #region agent log
        _debug_log('H4', 'rma_statistics.py:399', 'Exception in scan_all_rma_directories', {'error': str(e), 'type': type(e).__name__})
        # #endregion
        stats['error_messages'].append(str(e))
    
    # #region agent log
    _debug_log('H1,H2,H3,H4', 'rma_statistics.py:402', 'scan_all_rma_directories EXIT', {'stats': stats})
    # #endregion
    return stats


def get_current_week_range():
    """
    Get the current week's date range (Monday to Sunday)
    
    Returns:
        tuple: (start_date, end_date) as datetime objects
    """
    today = timezone.now().date()
    # Get Monday of current week (weekday 0 is Monday)
    start_date = today - timedelta(days=today.weekday())
    # Get Sunday of current week
    end_date = start_date + timedelta(days=6)
    
    # Convert to datetime at start/end of day
    start_datetime = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    end_datetime = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
    
    return start_datetime, end_datetime


def get_week_by_offset(offset=0):
    """
    Get week date range by offset from current week
    
    Args:
        offset (int): Week offset (0 = current week, -1 = last week, 1 = next week)
        
    Returns:
        tuple: (start_date, end_date) as datetime objects
    """
    start_date, end_date = get_current_week_range()
    
    # Apply offset
    start_date = start_date + timedelta(weeks=offset)
    end_date = end_date + timedelta(weeks=offset)
    
    return start_date, end_date


def get_month_by_offset(offset=0):
    """
    Get month and year by offset from current month
    
    Args:
        offset (int): Month offset (0 = current month, -1 = last month, 1 = next month)
        
    Returns:
        tuple: (year, month) as integers
    """
    now = timezone.now()
    current_year = now.year
    current_month = now.month
    
    # Calculate target month and year
    target_month = current_month + offset
    target_year = current_year
    
    # Handle year boundaries
    while target_month > 12:
        target_month -= 12
        target_year += 1
    
    while target_month < 1:
        target_month += 12
        target_year -= 1
    
    return target_year, target_month


def get_year_by_offset(offset=0):
    """
    Get year by offset from current year
    
    Args:
        offset (int): Year offset (0 = current year, -1 = last year, 1 = next year)
        
    Returns:
        int: Target year
    """
    now = timezone.now()
    return now.year + offset


def get_weekly_statistics(start_date, end_date):
    """
    Get statistics for a specific week
    
    Counts unique RMA directories (one per directory name, uses most recent record)
    
    Args:
        start_date (datetime): Week start date
        end_date (datetime): Week end date
        
    Returns:
        dict: Statistics with total unique RMAs and GPU model breakdown
    """
    # #region agent log
    _debug_log('H5,H6', 'rma_statistics.py:493', 'get_weekly_statistics ENTRY', {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat()
    })
    # #endregion
    
    # Get all records in the date range
    # #region agent log
    total_db_records = RmaTestStatistic.objects.count()
    _debug_log('H6', 'rma_statistics.py:502', 'Total records in DB', {'count': total_db_records})
    # #endregion
    
    all_records = RmaTestStatistic.objects.filter(
        test_date__gte=start_date,
        test_date__lte=end_date
    ).order_by('directory_name', '-file_mtime', '-test_date', '-updated_at')
    
    # #region agent log
    filtered_count = all_records.count()
    _debug_log('H5,H6', 'rma_statistics.py:505', 'Filtered records by date range', {
        'filtered_count': filtered_count,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat()
    })
    # #endregion
    
    # Get unique directories (most recent record for each directory)
    seen_directories = set()
    unique_records = []
    
    for record in all_records:
        if record.directory_name not in seen_directories:
            seen_directories.add(record.directory_name)
            unique_records.append(record)
    
    total_units = len(unique_records)
    
    # #region agent log
    _debug_log('H5,H6', 'rma_statistics.py:516', 'Unique records after deduplication', {
        'unique_count': total_units,
        'sample_dirs': [r.directory_name for r in unique_records[:5]]
    })
    # #endregion
    
    # Initialize counters
    total_failures = {
        'gpu_detection': 0,
        'ecc_error': 0,
        'dcgm_test': 0,
        'dcgm_r4_test': 0,
        'fd2_test': 0,
        'agfhc_test': 0,
    }
    
    # Breakdown by GPU model
    gpu_breakdown = {}
    
    # Process each unique record
    for record in unique_records:
        gpu_model = record.gpu_model
        
        # Initialize GPU model entry if not exists
        if gpu_model not in gpu_breakdown:
            gpu_breakdown[gpu_model] = {
                'count': 0,
                'failures': {
                    'gpu_detection': 0,
                    'ecc_error': 0,
                    'dcgm_test': 0,
                    'dcgm_r4_test': 0,
                    'fd2_test': 0,
                    'agfhc_test': 0,
                }
            }
        
        gpu_breakdown[gpu_model]['count'] += 1
        
        # Count failures
        for test_type, result in record.test_results.items():
            if result == 'fail':
                total_failures[test_type] += 1
                gpu_breakdown[gpu_model]['failures'][test_type] += 1
    
    result = {
        'start_date': start_date,
        'end_date': end_date,
        'total_units': total_units,
        'total_failures': total_failures,
        'gpu_breakdown': gpu_breakdown,
    }
    # #region agent log
    _debug_log('H5,H6', 'rma_statistics.py:563', 'get_weekly_statistics EXIT', {
        'total_units': total_units,
        'gpu_breakdown_keys': list(gpu_breakdown.keys()) if gpu_breakdown else []
    })
    # #endregion
    return result


def get_monthly_statistics(year, month):
    """
    Get statistics for a specific month
    
    Args:
        year (int): Year
        month (int): Month (1-12)
        
    Returns:
        dict: Statistics with total failures and GPU model breakdown
    """
    # Get start and end of month
    start_date = timezone.make_aware(datetime(year, month, 1))
    
    # Get last day of month
    if month == 12:
        end_date = timezone.make_aware(datetime(year + 1, 1, 1)) - timedelta(seconds=1)
    else:
        end_date = timezone.make_aware(datetime(year, month + 1, 1)) - timedelta(seconds=1)
    
    # Reuse weekly statistics logic
    stats = get_weekly_statistics(start_date, end_date)
    stats['year'] = year
    stats['month'] = month
    
    return stats


def get_yearly_statistics(year):
    """
    Get statistics for a specific year
    
    Args:
        year (int): Year
        
    Returns:
        dict: Statistics with total failures and GPU model breakdown
    """
    # Get start and end of year
    start_date = timezone.make_aware(datetime(year, 1, 1))
    end_date = timezone.make_aware(datetime(year + 1, 1, 1)) - timedelta(seconds=1)
    
    # Reuse weekly statistics logic
    stats = get_weekly_statistics(start_date, end_date)
    stats['year'] = year
    
    return stats

