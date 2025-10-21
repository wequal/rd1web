# RMA Firmware Update Fixes

**Date:** October 21, 2025  
**Status:** ✅ FIXED

## Issues Fixed

### 1. ✅ Form Validation Error (Execute Button Not Working)

**Problem:**
```
ERROR RMA PXE form validation failed: Select a valid choice. 27370 is not one of the available choices.
```

**Root Cause:**
- `eco_number` was a `ChoiceField` with empty choices
- Choices were only populated via JavaScript on the frontend
- When form submitted, Django validated the value must be in choices list
- Since choices were empty on server side, validation failed

**Fix:**
- Changed `eco_number` from `ChoiceField` to `CharField`
- Still uses `Select` widget for dropdown UI
- Django no longer validates against a choices list
- Form now accepts any ECO number value

**File Modified:** `rd1web/pxe/form.py` (line 262)

### 2. ✅ UI Alignment Issue

**Problem:**
- Firmware Update checkbox not aligned with other test items
- GPUDiag, Level 3, and Firmware Update were outside the row container

**Root Cause:**
- HTML structure was broken
- First 4 test items (Default, PRE GPU TEST, DCGM, FD2) were inside `<div class="row">`
- Last 3 items (GPUDiag, Level 3, Firmware Update) were outside the row
- Missing proper closing tags

**Fix:**
- Properly nested ALL test items inside the row div
- Now all 7 items are in the same grid:
  1. Default (col-md-3)
  2. PRE GPU TEST (col-md-3)
  3. DCGM (col-md-3)
  4. FD2 (col-md-3)
  5. GPU Field Diag (col-md-3)
  6. AGHFC Level 3 (col-md-3)
  7. **Firmware Update (col-md-3)** ← Now properly aligned

**File Modified:** `rd1web/templates/features/rma_pxe.html` (lines 108-183)

## ECO Numbers Explanation

### Why Only One ECO Number Shows?

**From the logs:**
```
INFO ECO API called: image_type=ubuntu2204-x86-rma, product_types=['H100_AC', 'H100_LC', 'H200_AC', 'H200_LC'], eco_count=1, eco_numbers=['27370']
INFO Database has 18 firmware files for product_types ['H100_AC', 'H100_LC', 'H200_AC', 'H200_LC']
```

**Analysis:**
- API correctly queries 4 product types: H100_AC, H100_LC, H200_AC, H200_LC ✅
- Database has 18 firmware files for these products ✅
- API returns only 1 **DISTINCT** ECO number: "27370" ✅

**This is CORRECT behavior!**

The query uses `.distinct()` which removes duplicates:
```python
FirmwareFile.objects.filter(
    product_type__in=product_types
).values_list('eco_number', flat=True).distinct()
```

**What this means:**
- All 18 firmware files use the same ECO number (27370)
- The dropdown correctly shows only unique ECO numbers
- **To see multiple ECO options, upload firmware files with different ECO numbers**

### How to Add More ECO Numbers

1. Go to **Firmware Inventory** page
2. Select a product type (e.g., H100_LC, H200_AC, B200_AC)
3. Create a **new ECO folder** with a different number (e.g., "27371", "27372")
4. Upload firmware files to that ECO folder
5. Refresh RMA GPU TEST page
6. The new ECO numbers will appear in the dropdown

**Example:**
```
Current: 18 files with ECO 27370
         └─ Dropdown shows: [27370]

After adding:
├─ ECO 27370: 18 files (H100_AC, H100_LC, H200_AC, H200_LC)
├─ ECO 27371: 2 files (H100_LC, H200_AC)
└─ ECO 27372: 5 files (B200_AC, B200_LC)

Dropdown will show: [27370, 27371, 27372]
```

## Testing

### Test Form Submission
1. Fill in Base SN and RMA Number
2. Select BMC IP
3. Select Image (H100/200 or B200)
4. Select tests (e.g., "default")
5. Check "Firmware Update"
6. Select ECO number from dropdown
7. Click "Execute"
8. **Expected:** Form submits successfully, no validation errors
9. **Check Django logs for:**
   ```
   RMA PXE form submitted: base_sn=..., fw_update=True, eco_number=27370
   Built tests_param: default fw_update eco_number=27370
   Executing PXE generation for X MACs
   ```

### Test UI Alignment
1. Open RMA GPU TEST page
2. Scroll to Tests section
3. **Expected:** All checkboxes (Default, PRE GPU TEST, DCGM, FD2, GPU Field Diag, AGHFC Level 3, Firmware Update) are aligned in a grid
4. Each item should be in a column with equal spacing

### Test ECO Numbers
1. Select H100/200 image
2. Check "Firmware Update"
3. ECO dropdown appears
4. **Check browser console for:**
   ```
   Loading ECO numbers for image type: ubuntu2204-x86-rma
   ECO API response: {success: true, eco_numbers: ['27370'], debug: {...}}
   Found 1 ECO numbers: ['27370']
   Debug info: {product_types: ['H100_AC', 'H100_LC', 'H200_AC', 'H200_LC'], count: 1}
   ```
5. **Check Django logs for:**
   ```
   ECO API called: image_type=ubuntu2204-x86-rma, product_types=['H100_AC', 'H100_LC', 'H200_AC', 'H200_LC'], eco_count=1, eco_numbers=['27370']
   Database has 18 firmware files for product_types ['H100_AC', 'H100_LC', 'H200_AC', 'H200_LC']
   ```

## Files Modified

1. ✅ `rd1web/pxe/form.py` - Changed eco_number to CharField
2. ✅ `rd1web/templates/features/rma_pxe.html` - Fixed HTML structure for alignment

## Summary

**All issues are now fixed:**
- ✅ Form validation error resolved - execute button works
- ✅ UI alignment fixed - Firmware Update checkbox aligns with other tests
- ✅ ECO numbers working correctly - showing distinct values from database

**ECO numbers appear limited because:**
- All uploaded firmware files have the same ECO number
- Need to upload files with different ECO numbers to see more options
- The system is working as designed

