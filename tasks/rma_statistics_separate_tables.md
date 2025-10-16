# RMA Statistics - Separate Tables for NVIDIA and AMD GPUs

## Date: October 15, 2025

## Changes Implemented

### 1. ✅ Added MI Model GPU Detection Pattern
**File:** `rd1web/pxe/rma_statistics.py`

Added GPU detection for AMD MI series GPUs:
- **Pattern for fail:** `0 GPUs detected`
- **Pattern for pass:** `8 GPUs detected`

This is in addition to existing NVIDIA patterns:
- **Pattern for fail:** `Error: GPU count is not 8`
- **Pattern for pass:** `GPU count is 8`

### Updated Detection Logic
```python
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
```

### 2. ✅ Separated GPU Breakdown into Two Tables
**File:** `rd1web/templates/features/rma_statistics.html`

Created two distinct breakdown tables:

#### Table 1: NVIDIA GPU Models (H/B Series)
- **Header Color:** Blue (Primary)
- **Models Included:** H100, H200, B200, etc.
- **Tests Shown:**
  - GPU Detection ✅
  - ECC Error ✅
  - DCGM Test ✅
  - FD2 Test ✅
  - AGFHC Test ✅

#### Table 2: AMD GPU Models (MI Series)
- **Header Color:** Green (Success)
- **Models Included:** MI325, MI300X, MI355, etc.
- **Tests Shown:**
  - GPU Detection ✅ (with AMD-specific patterns)
  - AGFHC Test ✅

### 3. ✅ Test Filtering by GPU Type

**NVIDIA GPUs (H/B):**
- All 5 tests are relevant and displayed
- Uses NVIDIA-specific GPU detection patterns

**AMD GPUs (MI):**
- Only GPU Detection and AGFHC tests are relevant
- ECC Error, DCGM, and FD2 tests are NVIDIA-specific and NOT shown
- Uses AMD-specific GPU detection patterns

## Current GPU Model Distribution

```
NVIDIA Models:
  H100:  54 records
  H200:  11 records
  B200:   1 record
  Total:  66 records (54.1%)

AMD Models:
  MI325:  13 records (combined from MI325DLC + MI325X)
  MI300X:  2 records
  MI355:   1 record
  Total:  16 records (13.1%)

Filtered (Hidden):
  Unknown: 38 records
  unknown:  1 record
  BMC_IP::  1 record
  Total:   40 records (32.8%)
```

## Detection Patterns

### NVIDIA GPU Detection
**Log Patterns:**
```
[2025-10-14 15:40:57] Error: GPU count is not 8  ← FAIL
[2025-10-15 10:49:10] GPU count is 8             ← PASS
```

### AMD GPU Detection
**Log Patterns:**
```
[2025-10-13 10:52:35] 0 GPUs detected  ← FAIL
[Future pattern]      8 GPUs detected  ← PASS
```

## Test Relevance by GPU Type

### NVIDIA (H/B Series) - All Tests
| Test | Relevant | Description |
|------|----------|-------------|
| GPU Detection | ✅ Yes | NVIDIA pattern detection |
| ECC Error | ✅ Yes | NVIDIA memory error checking |
| DCGM Test | ✅ Yes | NVIDIA Data Center GPU Manager |
| FD2 Test | ✅ Yes | NVIDIA Field Diagnostic Level 2 |
| AGFHC Test | ✅ Yes | Hardware Function Check |

### AMD (MI Series) - Selective Tests
| Test | Relevant | Description |
|------|----------|-------------|
| GPU Detection | ✅ Yes | AMD pattern detection (0/8 GPUs) |
| ECC Error | ❌ No | NVIDIA-specific test |
| DCGM Test | ❌ No | NVIDIA-specific tool |
| FD2 Test | ❌ No | NVIDIA-specific diagnostic |
| AGFHC Test | ✅ Yes | Hardware Function Check |

## UI Layout

### Before (Single Table)
```
┌──────────────────────────────────────┐
│  GPU Model Breakdown                 │
├──────────────────────────────────────┤
│ Model | GPU | ECC | DCGM | FD2 | ... │
│ H100  |  5  |  2  |  1   |  3  | ... │
│ MI325 |  2  |  0  |  0   |  0  | ... │ ← Confusing: 0s not meaningful
└──────────────────────────────────────┘
```

### After (Separate Tables)
```
┌──────────────────────────────────────┐
│  NVIDIA GPU Models (H/B Series)      │ ← Blue header
├──────────────────────────────────────┤
│ Model | GPU | ECC | DCGM | FD2 | ... │
│ H100  |  5  |  2  |  1   |  3  | ... │
│ H200  |  1  |  0  |  0   |  1  | ... │
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│  AMD GPU Models (MI Series)          │ ← Green header
├──────────────────────────────────────┤
│ Model | GPU | AGFHC |                │ ← Only relevant tests
│ MI325 |  2  |   3   |                │
│ MI300X|  0  |   0   |                │
└──────────────────────────────────────┘
```

## Benefits

### 1. Clarity
- ✅ Each table shows only relevant tests for that GPU type
- ✅ No confusing "0" values for non-applicable tests
- ✅ Clear visual separation between NVIDIA and AMD

### 2. Accuracy
- ✅ AMD GPU detection now works correctly
- ✅ Proper patterns for each vendor
- ✅ No false negatives from vendor-specific tests

### 3. Maintainability
- ✅ Easy to add new GPU models
- ✅ Easy to adjust which tests apply to which vendor
- ✅ Clear code organization

## Verification

### MI Model with GPU Detection Failure
```bash
Directory: 692504100882_XD250827122
GPU Model: MI325
GPU Detection: fail  ✅ (correctly detected "0 GPUs detected")
AGFHC: fail          ✅ (unable to run)
```

### NVIDIA Model with Multiple Tests
```bash
Directory: 1660224656070_XD250311087
GPU Model: H100
GPU Detection: pass  ✅
ECC Error: pass      ✅
DCGM Test: pass      ✅
FD2 Test: pass       ✅
AGFHC: unknown       ✅
```

## Files Modified

1. **`rd1web/pxe/rma_statistics.py`**
   - Added AMD GPU detection patterns
   - Combined NVIDIA and AMD pattern checks
   - Maintains backward compatibility

2. **`rd1web/templates/features/rma_statistics.html`**
   - Split single table into two separate tables
   - NVIDIA table: Shows all 5 tests
   - AMD table: Shows only GPU Detection and AGFHC
   - Different header colors for visual distinction

## Database Impact

- **Records rescanned:** 122 directories
- **New detection applied:** AMD GPU detection now active
- **MI model failures detected:** 1+ records with GPU detection failures
- **No data loss:** All existing data preserved and updated

## Future Considerations

### Adding New GPU Models

**NVIDIA/Intel (H/B/X series):**
- Automatically included in NVIDIA table
- All 5 tests shown

**AMD (MI series):**
- Automatically included in AMD table
- Only GPU Detection and AGFHC shown

### Adding New Tests

**Vendor-specific tests:**
- Add to appropriate table only
- Update test relevance documentation

**Universal tests:**
- Can be added to both tables
- Update both table headers

## Summary

✅ **Separate Tables:** NVIDIA and AMD GPUs now have dedicated breakdown tables
✅ **AMD GPU Detection:** Added detection for "0 GPUs detected" / "8 GPUs detected" patterns
✅ **Test Filtering:** ECC/DCGM/FD2 only shown for NVIDIA; only GPU Detection + AGFHC for AMD
✅ **Visual Distinction:** Blue header for NVIDIA, Green header for AMD
✅ **Cleaner UI:** No more confusing "0" values for non-applicable tests
✅ **Data Rescanned:** All 122 records updated with new logic

---

**Status:** ✅ COMPLETE - GPU breakdown now properly separated by vendor with relevant tests only

