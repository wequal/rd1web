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
from datetime import datetime, timedelta
from django.db.models import Count, Q
from django.utils import timezone
from .models import RmaTestStatistic

logger = logging.getLogger(__name__)

# Import configuration from local_config (required, no fallback)
from .local_config import RMA_BASE_DIR, RMA_GB_BASE_DIR
logger.info("RMA statistics using RMA_BASE_DIR and RMA_GB_BASE_DIR from local_config.py")


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


def scan_rma_directory(dir_name, base_dir=None, base='main'):
    """
    Scan a single RMA directory and update/create database record
    
    Args:
        dir_name (str): Directory name (e.g., "1660224656070_XD250311087")
        base_dir (str): Root path for this RMA tree (default RMA_BASE_DIR)
        base (str): Statistics base label 'main' or 'gb' for RMA_BASE_DIR / RMA_GB_BASE_DIR
        
    Returns:
        tuple: (success: bool, message: str)
    """
    if base_dir is None:
        base_dir = RMA_BASE_DIR
    try:
        # Parse directory name
        pattern = re.compile(r'^(.+)_(.+)$')
        match = pattern.match(dir_name)
        
        if not match:
            return False, f"Directory name doesn't match pattern: {dir_name}"
        
        base_sn, rma_number = match.groups()
        
        # Construct paths and resolve symlinks so we read from actual location
        dir_path = os.path.join(base_dir, dir_name)
        if not os.path.exists(dir_path):
            return False, f"Directory not found (base={base}): {dir_path}"
        try:
            dir_path_resolved = os.path.realpath(dir_path)
        except OSError:
            dir_path_resolved = dir_path
        # Attribute to gb when the resolved path is under RMA_GB_BASE_DIR (avoids double-count when main has symlinks to gb)
        try:
            gb_base_resolved = os.path.realpath(RMA_GB_BASE_DIR)
        except OSError:
            gb_base_resolved = RMA_GB_BASE_DIR
        if dir_path_resolved == gb_base_resolved or (
            dir_path_resolved.startswith(gb_base_resolved + os.sep)
        ):
            effective_base = 'gb'
        else:
            effective_base = base
        test_results_path = os.path.join(dir_path_resolved, 'test_results.log')
        sys_info_path = os.path.join(dir_path_resolved, 'sys_info.txt')
        
        if not os.path.exists(test_results_path):
            return False, (
                f"test_results.log not found (base={base}): {dir_name} "
                f"path={test_results_path}"
            )
        
        # Get directory mtime for test_date (use resolved path)
        try:
            dir_mtime = os.path.getmtime(dir_path_resolved)
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
        except Exception as e:
            logger.warning(f"Cannot get directory mtime, using current time: {e}")
            test_date = timezone.now()
        
        # Get GPU model
        gpu_model = parse_sys_info_file(sys_info_path)
        
        # Check if this directory already has a record with same file_mtime (for this base)
        existing_record = RmaTestStatistic.objects.filter(
            base=effective_base,
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
        
        # Create or update record - one record per (base, directory_name, file_mtime)
        RmaTestStatistic.objects.update_or_create(
            base=effective_base,
            directory_name=dir_name,
            file_mtime=file_mtime,
            defaults={
                'base_sn': base_sn,
                'rma_number': rma_number,
                'gpu_model': gpu_model,
                'test_date': test_date,
                'test_results': test_results,
            }
        )
        
        return True, f"Updated: {dir_name} ({gpu_model})"
        
    except Exception as e:
        logger.error(f"Error scanning directory {dir_name}: {e}")
        return False, f"Error: {str(e)}"


def scan_all_rma_directories():
    """
    Scan all RMA directories and update statistics database
    Scans both RMA_BASE_DIR (main) and RMA_GB_BASE_DIR (gb).
    Uses directory modification time for test_date
    Only creates new records when test_results.log changes
    
    Returns:
        dict: Statistics about the scan (processed, skipped, errors)
    """
    stats = {
        'total': 0,
        'processed': 0,
        'skipped': 0,
        'errors': 0,
        'error_messages': [],
    }
    
    # (base_dir, base_label) for each scan target
    scan_targets = [
        (RMA_BASE_DIR, 'main'),
        (RMA_GB_BASE_DIR, 'gb'),
    ]
    
    pattern = re.compile(r'^(.+)_(.+)$')
    
    try:
        for base_dir, base_label in scan_targets:
            if not os.path.exists(base_dir):
                logger.warning(
                    f"RMA statistics: skipping {base_label!r} scan - directory not found: {base_dir}"
                )
                continue
            logger.info(f"RMA statistics: scanning base={base_label!r} path={base_dir}")
            try:
                items = os.listdir(base_dir)
            except Exception as e:
                logger.error(f"Cannot list RMA directory {base_dir}: {e}")
                stats['error_messages'].append(f"{base_dir}: {e}")
                continue
            
            for item in items:
                item_path = os.path.join(base_dir, item)
                
                if not os.path.isdir(item_path):
                    continue
                if not pattern.match(item):
                    continue
                
                stats['total'] += 1
                success, message = scan_rma_directory(item, base_dir=base_dir, base=base_label)
                
                if success:
                    if 'Skipped' in message:
                        stats['skipped'] += 1
                    else:
                        stats['processed'] += 1
                else:
                    stats['errors'] += 1
                    stats['error_messages'].append(message)
                    logger.warning(f"Scan error: {message}")
        
        logger.info(f"RMA statistics scan complete: {stats['processed']} processed, "
                   f"{stats['skipped']} skipped, {stats['errors']} errors out of {stats['total']} total")
        
    except Exception as e:
        logger.error(f"Error in scan_all_rma_directories: {e}")
        stats['error_messages'].append(str(e))
    
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
    # Get all records in the date range (main and gb bases)
    all_records = RmaTestStatistic.objects.filter(
        test_date__gte=start_date,
        test_date__lte=end_date
    ).order_by('base', 'directory_name', '-file_mtime', '-test_date', '-updated_at')
    
    # Get unique directories (most recent record per base + directory_name)
    seen_directories = set()
    unique_records = []
    
    for record in all_records:
        key = (record.base, record.directory_name)
        if key not in seen_directories:
            seen_directories.add(key)
            unique_records.append(record)
    
    total_units = len(unique_records)
    
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
    
    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_units': total_units,
        'total_failures': total_failures,
        'gpu_breakdown': gpu_breakdown,
    }


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

