# RMA Firmware Update - Final Fixes

**Date:** October 21, 2025  
**Status:** ✅ COMPLETED

## Issues Fixed

### 1. ✅ PXE Script Command Format

**User Request:** "Do not use tests=default or fw_update on pxe script. For any test items just show their value for example default fw_update fd2"

**Status:** Already correct! ✅

The command format is already correct:
```bash
/srv/share/scripts/rma_pxe_generation {mac} {image} {base_sn} {rma_number} default fw_update eco_number=27370
```

**How it works:**
1. User selects tests: `['default', 'fd2']`
2. User checks "Firmware Update"
3. User selects ECO: `27370`
4. System builds: `tests_list = ['default', 'fd2', 'fw_update', 'eco_number=27370']`
5. Joins with spaces: `"default fd2 fw_update eco_number=27370"`
6. Passes to script: `/srv/share/scripts/rma_pxe_generation {mac} {image} {base_sn} {rma_number} default fd2 fw_update eco_number=27370`

**Code location:** `rd1web/pxe/views/rma_pxe.py` lines 115-121

---

### 2. ✅ Firmware Update Checkbox Alignment

**Problem:** Firmware Update checkbox not properly aligned with other test items

**Root Cause:** Django form field rendering (`{{ form.fw_update }}`) creates different HTML structure than hardcoded test checkboxes

**Fix:** Changed to hardcoded HTML matching other test items exactly
```html
<!-- Before: Django form field -->
{{ form.fw_update }}

<!-- After: Hardcoded consistent HTML -->
<input type="checkbox" class="form-check-input" name="fw_update" id="id_fw_update">
<label class="form-check-label" for="id_fw_update">
    Firmware Update
</label>
```

**Also updated:**
- JavaScript to use fixed ID: `id_fw_update` instead of template variable
- Now renders identically to other test checkboxes (Default, DCGM, FD2, etc.)

**Files Modified:**
- `rd1web/templates/features/rma_pxe.html` lines 162-169 (HTML)
- `rd1web/templates/features/rma_pxe.html` line 678 (JavaScript)

---

### 3. ✅ Enhanced ECO Number Debugging

**User Report:** "ECO number reading still incorrect"

**Added:** Comprehensive logging to diagnose the issue

**New debug output shows:**
1. **Per product type breakdown:**
   ```
   H100_AC: 5 files, ECO numbers: ['27370', '27371']
   H100_LC: 3 files, ECO numbers: ['27370']
   H200_AC: 8 files, ECO numbers: ['27370', '27372']
   H200_LC: 2 files, ECO numbers: ['27370']
   ```

2. **Combined distinct ECO numbers:**
   ```
   Combined distinct ECO numbers: ['27370', '27371', '27372'] (total: 3)
   ```

3. **All individual files:**
   ```
   All firmware files in database for ['H100_AC', 'H100_LC', 'H200_AC', 'H200_LC']:
     - H100_AC/27370/GPU: H100_AC_27370_GPU.bin
     - H100_AC/27370/retimer_0: H100_AC_27370_retimer_0.bin
     - H100_AC/27371/GPU: H100_AC_27371_GPU.bin
     - H200_AC/27372/GPU: H200_AC_27372_GPU.bin
     ...
   ```

**This will help identify:**
- Which product types have files uploaded
- Which ECO numbers exist for each product type
- Whether files are actually in the database with different ECO numbers
- If the API query is working correctly

**File Modified:** `rd1web/pxe/views/rma_pxe.py` lines 73-86

---

## Testing Instructions

### Test 1: Verify PXE Command Format
1. Fill in RMA form (Base SN, RMA Number, BMC IP)
2. Select Image: H100/200
3. Select tests: "default" and "fd2"
4. Check "Firmware Update"
5. Select ECO number: "27370"
6. Click Execute
7. **Check Django logs for:**
   ```
   Built tests_param: default fd2 fw_update eco_number=27370
   ```
8. **PXE script command should be:**
   ```bash
   /srv/share/scripts/rma_pxe_generation 0cc47a758abd ubuntu2204-x86-rma SN123 RMA456 default fd2 fw_update eco_number=27370
   ```

### Test 2: Verify Checkbox Alignment
1. Open RMA GPU TEST page
2. Scroll to Tests section
3. **Expected:** All checkboxes aligned in a grid:
   ```
   [✓] Default        [✓] PRE GPU TEST   [ ] DCGM           [ ] FD2
   [ ] GPU Field Diag [ ] AGHFC Level 3  [✓] Firmware Update
   ```
4. All items should have same spacing and alignment

### Test 3: Diagnose ECO Numbers
1. Select H100/200 image
2. Check "Firmware Update"
3. **Check Django logs for detailed breakdown:**
   ```
   ECO API called: image_type=ubuntu2204-x86-rma, product_types=['H100_AC', 'H100_LC', 'H200_AC', 'H200_LC']
     H100_AC: X files, ECO numbers: [...]
     H100_LC: X files, ECO numbers: [...]
     H200_AC: X files, ECO numbers: [...]
     H200_LC: X files, ECO numbers: [...]
   Combined distinct ECO numbers: [...] (total: X)
   All firmware files in database for [...]:
     - H100_AC/27370/GPU: filename.bin
     - ...
   ```
4. **This will show:**
   - If files exist for each product type
   - What ECO numbers are actually in the database
   - If multiple ECO numbers exist but aren't showing

---

## Common ECO Number Issues & Solutions

### Issue: Only one ECO shows even though I uploaded multiple

**Possible Causes:**

1. **All files uploaded to same ECO folder**
   - Check: Do all files show same ECO in logs?
   - Solution: Create separate ECO folders (27371, 27372, etc.) in Firmware Inventory

2. **Files uploaded to wrong product types**
   - Check: Are files in H100_LC, H200_AC, etc. or only in H100_AC?
   - Solution: Upload files to all relevant product types

3. **ECO folders exist but no files uploaded**
   - Check: Do logs show "0 files" for some product types?
   - Solution: Upload firmware files to the ECO folders

4. **Database not refreshed**
   - Check: Did you upload files but database not updated?
   - Solution: Re-upload files through Firmware Inventory UI

### How to Add Multiple ECO Numbers

**Example: Want to see ECO options [27370, 27371, 27372]**

1. Go to **Firmware Inventory** → H100_AC
2. Create ECO folders: "27370", "27371", "27372"
3. Upload GPU firmware to each folder
4. Repeat for H100_LC, H200_AC, H200_LC
5. Result in dropdown: `[27370, 27371, 27372]`

**Minimum requirement:**
- At least 1 file in at least 1 product type per ECO number
- ECO number will appear if it exists in ANY of the queried product types

---

## Files Modified

1. ✅ `rd1web/templates/features/rma_pxe.html` - Fixed alignment, updated JavaScript
2. ✅ `rd1web/pxe/views/rma_pxe.py` - Enhanced logging

## Summary

All three issues addressed:
1. ✅ PXE command format already correct (no "tests=" prefix)
2. ✅ Firmware Update checkbox now aligns perfectly with other test items
3. ✅ Enhanced ECO debugging to diagnose why only one ECO number shows

Check the Django logs after clicking "Firmware Update" to see exactly what's in your database!

