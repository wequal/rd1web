# Firmware Inventory - Final Updates

## Changes Implemented

### 1. Updated Retimer Fields ✅

**Previous:** GPU + Retimer 5 + Retimer 0, 4, 6, 7 (creates 5 files total)

**New:** GPU + Retimer 5 + Retimer 0, 1, 2, 3, 4, 6, 7 (creates 9 files total)

**Upload Fields for H100/H200 AC/LC:**
- GPU Firmware (single file)
- Retimer 5 Firmware (single file)
- Retimer 0, 1, 2, 3, 4, 6, 7 Firmware (one file → creates 7 copies)

**Files Modified:**
- `rd1web/pxe/form.py` - Changed field name from `retimer_0_4_6_7_file` to `retimer_0_1_2_3_4_6_7_file`
- `rd1web/pxe/views/firmware_inventory.py` - Updated to create 7 files instead of 4
- `rd1web/templates/features/firmware_inventory_eco_detail.html` - Updated field reference

**Result:**
When user uploads one file to "Retimer 0, 1, 2, 3, 4, 6, 7" field, system creates:
- `{PRODUCT}_{ECO}_retimer_0.ext`
- `{PRODUCT}_{ECO}_retimer_1.ext`
- `{PRODUCT}_{ECO}_retimer_2.ext`
- `{PRODUCT}_{ECO}_retimer_3.ext`
- `{PRODUCT}_{ECO}_retimer_4.ext`
- `{PRODUCT}_{ECO}_retimer_6.ext`
- `{PRODUCT}_{ECO}_retimer_7.ext`

### 2. Added Original Filename Column ✅

**Database Changes:**
- Added `original_filename` field to `FirmwareFile` model
- Field stores the name of the file as uploaded by user
- Migration created and applied: `0020_firmwarefile_original_filename.py`

**View Changes:**
- Updated `firmware_inventory_file_upload()` to save original filename
- Both single files and combined retimer files track original name

**Template Changes:**
- Added "Original Filename" column to the firmware files table
- Displays between "Filename" and "Size" columns
- Shows "N/A" if no original filename stored (for old records)

**Table Columns Now:**
1. File Type
2. Filename (renamed: e.g., `H100_AC_27370_GPU.bin`)
3. **Original Filename** (as uploaded: e.g., `nvidia_gpu_v3.5.bin`)
4. Size
5. Uploaded By
6. Upload Date
7. Actions

### 3. Fixed Delete Button ✅

**Issue:** Delete button wasn't working because JavaScript was in non-existent `{% block extra_js %}`

**Fix:**
- Moved `deleteFile()` function out of the block
- Placed script directly inline in template (before `{% endblock %}`)
- Used vanilla JavaScript (ES5 compatible)
- Added `return false;` to button onclick handler
- Simplified template string to avoid escaping issues

**How It Works Now:**
1. User clicks "Delete" button
2. Confirmation dialog appears
3. On confirm: AJAX request sent to backend
4. File deleted from filesystem and database
5. Row removed from table
6. If table empty, page reloads to show empty state

### 4. Nginx Upload Size Fix ✅

**Issue:** 413 Request Entity Too Large error

**Fix:**
- Increased `client_max_body_size` from 100M to **500M**
- Increased timeouts from 120s to **300s** (5 minutes)
- Applied to both production (port 80) and test (port 5003) servers
- Nginx configuration tested and reloaded

**File:** `/etc/nginx/sites-available/rd1web`

## Migrations Applied

1. `pxe.0019_alter_pxeentry_options_firmwarefile` - Created FirmwareFile model
2. `authentication.0008_alter_useractivity_action` - Expanded action field length
3. `pxe.0020_firmwarefile_original_filename` - Added original_filename field

## Complete Feature Summary

### Upload Flow for H100/H200:
1. User selects 3 files maximum:
   - GPU firmware → creates 1 file
   - Retimer 5 firmware → creates 1 file
   - Retimer 0,1,2,3,4,6,7 firmware → creates 7 files
2. Total: Up to 9 firmware files from 3 uploads

### Upload Flow for B200/B300:
1. User selects 1 file:
   - GPU firmware → creates 1 file
2. Total: Up to 1 firmware file

### File Management:
- All files tracked in database with original and renamed filenames
- Files stored in `/srv/firmwareinventory/{product}/{eco}/`
- Delete removes from both filesystem and database
- Upload history tracked (who, when, file size)

## Testing Checklist

- [x] H100/H200 shows 3 upload fields (GPU, Retimer 5, Retimer 0-1-2-3-4-6-7)
- [x] B200/B300 shows 1 upload field (GPU only)
- [x] Combined retimer upload creates 7 separate files
- [x] Original filename stored and displayed in table
- [x] Delete button works correctly
- [x] Files up to 500MB can be uploaded
- [x] Proper spacing on ECO detail page (no overlap)
- [x] Modern design on main page (no icons)

## Files Modified in This Update

1. `/home/devin/rd1web-dev/rd1web/pxe/form.py`
2. `/home/devin/rd1web-dev/rd1web/pxe/views/firmware_inventory.py`
3. `/home/devin/rd1web-dev/rd1web/pxe/models.py`
4. `/home/devin/rd1web-dev/rd1web/templates/features/firmware_inventory_eco_detail.html`
5. `/etc/nginx/sites-available/rd1web`

## Status: ✅ COMPLETE

All requested features have been implemented and are ready for use!

