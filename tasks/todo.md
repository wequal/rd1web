# RMA Logs Enhancement - Task Plan

## Overview
Add sys_info.txt parsing for BMC IP and GPU model, add Tester column, and remove refresh button.

## Tasks

- [x] 1. Create function to parse sys_info.txt for BMC IP and GPU model
  - [x] 1.1 Add `parse_sys_info_file()` function to extract GPU_Model and BMC_IP
  - [x] 1.2 Add `get_bmc_ip_from_sys_info()` function (primary source)
  - [x] 1.3 Add `get_gpu_model_from_sys_info()` function (primary source)

- [x] 2. Update existing functions to use sys_info.txt as primary source
  - [x] 2.1 Update `get_gpu_model()` to check sys_info.txt first, fallback to gpu_model.txt
  - [x] 2.2 Update `get_golden_number()` to check sys_info.txt for BMC IP first, fallback to bmc_ip.txt

- [x] 3. Add tester name functionality
  - [x] 3.1 Add `get_tester_name()` function to extract linked_user from RmaTestingDb
  - [x] 3.2 Update `load_directory_details_batch()` to include tester
  - [x] 3.3 Update `async_load_directory_details_batch()` to include tester

- [x] 4. Update template to add Tester column
  - [x] 4.1 Add Tester column header between GPU Model and Golden
  - [x] 4.2 Add tester data in table rows
  - [x] 4.3 Update JavaScript to handle tester data

- [x] 5. Remove refresh button
  - [x] 5.1 Remove refresh button HTML from template
  - [x] 5.2 Remove refresh button JavaScript functionality

## Files Modified
- `rd1web/pxe/views/rma_logs.py` - Add new functions and update existing ones
- `rd1web/templates/features/rma_logs.html` - Add Tester column and remove refresh button

## Implementation Summary

### 1. New sys_info.txt Parsing (Lines 791-838)
- Added `parse_sys_info_file()` function to parse sys_info.txt format:
  ```
  GPU_Model: MI325X
  BMC_IP: 10.10.10.22
  ```
- Returns dictionary with `gpu_model` and `bmc_ip` keys

### 2. Updated get_gpu_model() (Lines 900-937)
- Now checks sys_info.txt first (primary source)
- Falls back to gpu_model.txt if sys_info.txt not available
- Preserves backward compatibility

### 3. Updated get_golden_number() (Lines 939-1001)
- Now checks sys_info.txt for BMC IP first (primary source)
- Falls back to bmc_ip.txt if sys_info.txt not available
- Queries RmaTestingDb to get golden number from BMC IP

### 4. New get_tester_name() Function (Lines 1003-1065)
- Reads BMC IP from sys_info.txt (primary) or bmc_ip.txt (fallback)
- Queries RmaTestingDb to find linked_user
- Returns username or 'N/A' if not found
- Includes caching for performance

### 5. Updated Batch Loading Functions
- `load_directory_details_batch()` - Added tester_name to details
- `async_load_directory_details_batch()` - Added tester_name_task for concurrent loading
- Updated AJAX response to include tester_name data

### 6. Template Changes
- Removed refresh button from page header
- Added "Tester" column between "GPU Model" and "Golden"
- Updated table headers in both server-side and AJAX-generated HTML
- Updated JavaScript to display tester_name badge with bg-info styling
- Removed `refreshData()` function and related event listeners

## Impact
- ✅ Minimal code changes
- ✅ Preserves backward compatibility
- ✅ No database changes required
- ✅ Adds useful tester information
- ✅ Cleaner UI without unnecessary refresh button
