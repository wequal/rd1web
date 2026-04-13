"""
RD1 Statistics Module

Strict-fail variant of RMA statistics:
- Any fail occurrence marks a test as failed (even if a later run passed).
- FD2 individual sub-test items are parsed and stored per GPU SKU.
- AMD GPUs: only gpu_detection and agfhc_test are tracked (no ECC/DCGM/FD2).

All code here is independent from rma_statistics.py.
"""

import os
import re
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from .models import Rd1TestStatistic

logger = logging.getLogger(__name__)

from .local_config import RMA_BASE_DIR, RMA_GB_BASE_DIR

# GPU families treated as AMD — only gpu_detection and agfhc_test apply
AMD_GPU_PREFIXES = ('MI',)

# Regex to identify a GPU model as AMD
_AMD_RE = re.compile(r'^MI', re.IGNORECASE)


def _is_amd(gpu_model):
    return bool(_AMD_RE.match(gpu_model or ''))


# ---------------------------------------------------------------------------
# Strict-fail parse helpers
# ---------------------------------------------------------------------------

def _strict(has_fail, has_pass):
    """Return 'fail' if any fail found, 'pass' if pass found, else 'unknown'."""
    if has_fail:
        return 'fail'
    if has_pass:
        return 'pass'
    return 'unknown'


def _parse_fd2_items(fd2_section):
    """
    Parse individual sub-test results from the FD2 log section.

    Strategy: split the section on 'Testing <name>' boundaries; for each
    chunk that follows a 'Testing' line, look for PASSED / FAILED / PASS /
    FAIL keywords to determine the result of that item.

    Returns:
        dict: { item_name_lower: 'pass'/'fail'/'unknown', ... }
    """
    items = {}
    # Find every "Testing <name>" occurrence
    test_lines = list(re.finditer(r'Testing\s+(\S+)', fd2_section))
    if not test_lines:
        return items

    for idx, match in enumerate(test_lines):
        item_name = match.group(1)
        start = match.end()
        end = test_lines[idx + 1].start() if idx + 1 < len(test_lines) else len(fd2_section)
        chunk = fd2_section[start:end]

        has_fail = bool(re.search(r'\bFAILED?\b', chunk, re.IGNORECASE))
        has_pass = bool(re.search(r'\bPASSED?\b', chunk, re.IGNORECASE))
        items[item_name.lower()] = _strict(has_fail, has_pass)

    return items


def parse_rd1_results_log(log_content, gpu_model='Unknown'):
    """
    Parse test_results.log with strict fail logic.

    Strict means: if ANY fail pattern is found, that test is 'fail' —
    regardless of whether a later pass pattern also exists.

    For AMD GPUs only gpu_detection and agfhc_test are populated.

    Args:
        log_content (str): Full content of test_results.log
        gpu_model (str): Normalised GPU model string

    Returns:
        dict: {
            gpu_detection: pass/fail/unknown,
            ecc_error: pass/fail/unknown,          # NVIDIA only
            dcgm_test: pass/fail/unknown,           # NVIDIA only
            dcgm_r4_test: pass/fail/unknown,        # NVIDIA only
            fd2_test: pass/fail/unknown,            # NVIDIA only
            fd2_items: {item: pass/fail/unknown},   # NVIDIA only
            agfhc_test: pass/fail/unknown,
        }
    """
    results = {
        'gpu_detection': 'unknown',
        'ecc_error': 'unknown',
        'dcgm_test': 'unknown',
        'dcgm_r4_test': 'unknown',
        'fd2_test': 'unknown',
        'fd2_items': {},
        'agfhc_test': 'unknown',
    }

    if not log_content:
        return results

    amd = _is_amd(gpu_model)

    # --- GPU Detection (both NVIDIA and AMD) ---
    nvidia_fail = bool(re.search(r'Error: GPU count is not 8', log_content))
    nvidia_pass = bool(re.search(r'GPU count is 8', log_content))
    amd_fail = bool(re.search(r'0 GPUs detected', log_content))
    amd_pass = bool(re.search(r'8 GPUs detected', log_content))
    results['gpu_detection'] = _strict(nvidia_fail or amd_fail, nvidia_pass or amd_pass)

    # --- AGFHC Test (both NVIDIA and AMD) ---
    agfhc_unable = (
        bool(re.search(r'unable to run AGFHC', log_content, re.IGNORECASE))
        or bool(re.search(r'AGFHC Unable to Run', log_content, re.IGNORECASE))
    )
    agfhc_fail_code = bool(re.search(r'Program exiting with return code AGFHC_\w+ \[(?!0\])', log_content))
    agfhc_pass = bool(re.search(r'Program exiting with return code AGFHC_SUCCESS \[0\]', log_content))
    results['agfhc_test'] = _strict(agfhc_unable or agfhc_fail_code, agfhc_pass)

    if amd:
        # AMD: leave ECC / DCGM / FD2 as unknown, we are done
        return results

    # --- ECC Error (NVIDIA only) ---
    ecc_fail = bool(re.search(r'ECC error detected on GPU', log_content))
    ecc_pass = bool(re.search(r'No ECC error', log_content))
    results['ecc_error'] = _strict(ecc_fail, ecc_pass)

    # --- DCGM Test (NVIDIA only, strict: any fail = fail) ---
    dcgm_fail = bool(re.search(r'DCGM (LC|AC) test Failed', log_content))
    dcgm_pass = bool(re.search(r'DCGM (LC|AC) test Finished', log_content))
    results['dcgm_test'] = _strict(dcgm_fail, dcgm_pass)

    # --- DCGM R4 Test (NVIDIA only) ---
    dcgm_r4_fail = bool(re.search(r'DCGM_R4 Failed', log_content))
    dcgm_r4_pass = bool(re.search(r'DCGM_R4 Passed', log_content))
    results['dcgm_r4_test'] = _strict(dcgm_r4_fail, dcgm_r4_pass)

    # --- FD2 Test (NVIDIA only) ---
    fd2_fail = bool(re.search(r'Field Diagnostic level 2 test Failed', log_content))
    fd2_pass = bool(re.search(r'Field Diagnostic level 2 test Finished', log_content))
    results['fd2_test'] = _strict(fd2_fail, fd2_pass)

    # --- FD2 individual items ---
    # Extract all FD2 sections (there can be multiple runs in the same log)
    fd2_section_pattern = re.compile(
        r'Starting Field Diagnostic level 2 test.*?'
        r'Field Diagnostic level 2 test (?:Finished|Failed)',
        re.DOTALL,
    )
    fd2_sections = fd2_section_pattern.findall(log_content)

    if fd2_sections:
        # Accumulate per-item results across all FD2 sections; any fail wins
        combined_items = {}
        for section in fd2_sections:
            section_items = _parse_fd2_items(section)
            for item, result in section_items.items():
                existing = combined_items.get(item, 'unknown')
                if existing == 'fail' or result == 'fail':
                    combined_items[item] = 'fail'
                elif existing == 'pass' or result == 'pass':
                    combined_items[item] = 'pass'
                else:
                    combined_items[item] = 'unknown'
        results['fd2_items'] = combined_items

    return results


# ---------------------------------------------------------------------------
# GPU model normalisation (own copy, independent from rma_statistics.py)
# ---------------------------------------------------------------------------

def normalize_gpu_model(gpu_model):
    if not gpu_model:
        return 'Unknown'
    if gpu_model in ('MI325DLC', 'MI325X'):
        return 'MI325'
    return gpu_model


def parse_sys_info_file(sys_info_path):
    try:
        if not os.path.exists(sys_info_path):
            return 'Unknown'
        with open(sys_info_path, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'GPU_Model:\s*(\S+)', content)
        if match:
            return normalize_gpu_model(match.group(1).strip())
        return 'Unknown'
    except Exception as e:
        logger.warning(f"Error parsing sys_info.txt at {sys_info_path}: {e}")
        return 'Unknown'


# ---------------------------------------------------------------------------
# Directory scanner
# ---------------------------------------------------------------------------

def scan_rd1_directory(dir_name, base_dir=None, base='main'):
    """
    Scan a single RMA directory and update/create an Rd1TestStatistic record.

    Returns:
        tuple: (success: bool, message: str)
    """
    if base_dir is None:
        base_dir = RMA_BASE_DIR

    try:
        pattern = re.compile(r'^(.+)_(.+)$')
        match = pattern.match(dir_name)
        if not match:
            return False, f"Directory name doesn't match pattern: {dir_name}"

        base_sn, rma_number = match.groups()

        dir_path = os.path.join(base_dir, dir_name)
        if not os.path.exists(dir_path):
            return False, f"Directory not found (base={base}): {dir_path}"

        try:
            dir_path_resolved = os.path.realpath(dir_path)
        except OSError:
            dir_path_resolved = dir_path

        # Resolve effective base (handles symlinks from main → gb)
        try:
            gb_base_resolved = os.path.realpath(RMA_GB_BASE_DIR)
        except OSError:
            gb_base_resolved = RMA_GB_BASE_DIR

        if dir_path_resolved == gb_base_resolved or dir_path_resolved.startswith(gb_base_resolved + os.sep):
            effective_base = 'gb'
        else:
            effective_base = base

        test_results_path = os.path.join(dir_path_resolved, 'test_results.log')
        sys_info_path = os.path.join(dir_path_resolved, 'sys_info.txt')

        if not os.path.exists(test_results_path):
            return False, f"test_results.log not found (base={base}): {dir_name}"

        try:
            dir_mtime = os.path.getmtime(dir_path_resolved)
        except Exception as e:
            return False, f"Cannot get mtime for directory: {e}"

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

        try:
            test_date = timezone.make_aware(datetime.fromtimestamp(dir_mtime))
        except Exception:
            test_date = timezone.now()

        gpu_model = parse_sys_info_file(sys_info_path)

        existing = Rd1TestStatistic.objects.filter(
            base=effective_base,
            directory_name=dir_name,
            file_mtime=file_mtime,
        ).first()

        if existing:
            updates_needed = []
            try:
                log_content = get_log_content()
            except Exception as e:
                return False, f"Cannot read test_results.log: {e}"

            new_results = parse_rd1_results_log(log_content, gpu_model)

            if new_results != existing.test_results:
                existing.test_results = new_results
                updates_needed.append('test_results')
            if existing.test_date != test_date:
                existing.test_date = test_date
                updates_needed.append('test_date')
            if existing.gpu_model != gpu_model:
                existing.gpu_model = gpu_model
                updates_needed.append('gpu_model')
            if existing.base_sn != base_sn:
                existing.base_sn = base_sn
                updates_needed.append('base_sn')
            if existing.rma_number != rma_number:
                existing.rma_number = rma_number
                updates_needed.append('rma_number')

            if updates_needed:
                existing.file_mtime = file_mtime
                existing.save(update_fields=list(set(updates_needed + ['file_mtime', 'updated_at'])))
                return True, f"Updated existing record for: {dir_name}"
            return True, f"Skipped (already recorded): {dir_name}"

        try:
            log_content = get_log_content()
        except Exception as e:
            return False, f"Cannot read test_results.log: {e}"

        test_results = parse_rd1_results_log(log_content, gpu_model)

        Rd1TestStatistic.objects.update_or_create(
            base=effective_base,
            directory_name=dir_name,
            file_mtime=file_mtime,
            defaults={
                'base_sn': base_sn,
                'rma_number': rma_number,
                'gpu_model': gpu_model,
                'test_date': test_date,
                'test_results': test_results,
            },
        )

        return True, f"Updated: {dir_name} ({gpu_model})"

    except Exception as e:
        logger.error(f"Error scanning directory {dir_name}: {e}")
        return False, f"Error: {str(e)}"


def scan_all_rd1_directories():
    """
    Scan both RMA_BASE_DIR and RMA_GB_BASE_DIR and populate Rd1TestStatistic.

    Returns:
        dict: {total, processed, skipped, errors, error_messages}
    """
    stats = {
        'total': 0,
        'processed': 0,
        'skipped': 0,
        'errors': 0,
        'error_messages': [],
    }

    scan_targets = [
        (RMA_BASE_DIR, 'main'),
        (RMA_GB_BASE_DIR, 'gb'),
    ]

    pattern = re.compile(r'^(.+)_(.+)$')

    try:
        for base_dir, base_label in scan_targets:
            if not os.path.exists(base_dir):
                logger.warning(f"RD1 statistics: skipping {base_label!r} — not found: {base_dir}")
                continue
            logger.info(f"RD1 statistics: scanning base={base_label!r} path={base_dir}")
            try:
                items = os.listdir(base_dir)
            except Exception as e:
                logger.error(f"Cannot list directory {base_dir}: {e}")
                stats['error_messages'].append(f"{base_dir}: {e}")
                continue

            for item in items:
                item_path = os.path.join(base_dir, item)
                if not os.path.isdir(item_path):
                    continue
                if not pattern.match(item):
                    continue

                stats['total'] += 1
                success, message = scan_rd1_directory(item, base_dir=base_dir, base=base_label)

                if success:
                    if 'Skipped' in message:
                        stats['skipped'] += 1
                    else:
                        stats['processed'] += 1
                else:
                    stats['errors'] += 1
                    stats['error_messages'].append(message)
                    logger.warning(f"Scan error: {message}")

        logger.info(
            f"RD1 statistics scan complete: {stats['processed']} processed, "
            f"{stats['skipped']} skipped, {stats['errors']} errors out of {stats['total']} total"
        )
    except Exception as e:
        logger.error(f"Error in scan_all_rd1_directories: {e}")
        stats['error_messages'].append(str(e))

    return stats


# ---------------------------------------------------------------------------
# Time-period helpers (own copies, independent from rma_statistics.py)
# ---------------------------------------------------------------------------

def _week_range(offset=0):
    today = timezone.now().date()
    monday = today - timedelta(days=today.weekday())
    monday += timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    start = timezone.make_aware(datetime.combine(monday, datetime.min.time()))
    end = timezone.make_aware(datetime.combine(sunday, datetime.max.time()))
    return start, end


def _month_range(offset=0):
    now = timezone.now()
    month = now.month + offset
    year = now.year
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return year, month


def get_week_by_offset(offset=0):
    return _week_range(offset)


def get_month_by_offset(offset=0):
    return _month_range(offset)


def get_year_by_offset(offset=0):
    return timezone.now().year + offset


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

# Top-level test keys that are not GPU-family-specific
_NVIDIA_TESTS = ('gpu_detection', 'ecc_error', 'dcgm_test', 'dcgm_r4_test', 'fd2_test', 'agfhc_test')
_AMD_TESTS = ('gpu_detection', 'agfhc_test')

_FILTERED_GPU_MODELS = {'unknown', 'Unknown', 'BMC_IP:'}


def _get_unique_records(start_date, end_date):
    """Return one Rd1TestStatistic per (base, directory_name) — most recent mtime."""
    all_records = Rd1TestStatistic.objects.filter(
        test_date__gte=start_date,
        test_date__lte=end_date,
    ).order_by('base', 'directory_name', '-file_mtime', '-test_date', '-updated_at')

    seen = set()
    unique = []
    for rec in all_records:
        key = (rec.base, rec.directory_name)
        if key not in seen:
            seen.add(key)
            unique.append(rec)
    return unique


def _aggregate_records(unique_records):
    """
    Build aggregated statistics dict from a list of Rd1TestStatistic records.

    Returns:
        dict: {
            total_units,
            total_failures: {test_type: count},
            gpu_breakdown: {
                gpu_model: {
                    count,
                    is_amd,
                    failures: {test_type: count},
                    fd2_item_failures: {item: count},  # NVIDIA only
                }
            }
        }
    """
    total_units = len(unique_records)

    total_failures = {t: 0 for t in _NVIDIA_TESTS}
    gpu_breakdown = {}

    for rec in unique_records:
        gpu_model = rec.gpu_model
        if gpu_model in _FILTERED_GPU_MODELS:
            continue

        amd = _is_amd(gpu_model)
        tests_to_count = _AMD_TESTS if amd else _NVIDIA_TESTS

        if gpu_model not in gpu_breakdown:
            gpu_breakdown[gpu_model] = {
                'count': 0,
                'is_amd': amd,
                'failures': {t: 0 for t in _NVIDIA_TESTS},
                'fd2_item_failures': {},
            }

        gpu_breakdown[gpu_model]['count'] += 1

        for test_type in tests_to_count:
            result = rec.test_results.get(test_type, 'unknown')
            if result == 'fail':
                total_failures[test_type] += 1
                gpu_breakdown[gpu_model]['failures'][test_type] += 1

        # FD2 individual items (NVIDIA only)
        if not amd:
            fd2_items = rec.test_results.get('fd2_items', {})
            for item, result in fd2_items.items():
                if result == 'fail':
                    fd2_item_failures = gpu_breakdown[gpu_model]['fd2_item_failures']
                    fd2_item_failures[item] = fd2_item_failures.get(item, 0) + 1

    return {
        'total_units': total_units,
        'total_failures': total_failures,
        'gpu_breakdown': gpu_breakdown,
    }


def get_weekly_statistics(start_date, end_date):
    records = _get_unique_records(start_date, end_date)
    stats = _aggregate_records(records)
    stats['start_date'] = start_date
    stats['end_date'] = end_date
    return stats


def get_monthly_statistics(year, month):
    start = timezone.make_aware(datetime(year, month, 1))
    if month == 12:
        end = timezone.make_aware(datetime(year + 1, 1, 1)) - timedelta(seconds=1)
    else:
        end = timezone.make_aware(datetime(year, month + 1, 1)) - timedelta(seconds=1)
    stats = get_weekly_statistics(start, end)
    stats['year'] = year
    stats['month'] = month
    return stats


def get_yearly_statistics(year):
    start = timezone.make_aware(datetime(year, 1, 1))
    end = timezone.make_aware(datetime(year + 1, 1, 1)) - timedelta(seconds=1)
    stats = get_weekly_statistics(start, end)
    stats['year'] = year
    return stats
