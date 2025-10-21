# RMA Firmware Update ECO Number Implementation

**Date:** October 21, 2025  
**Status:** ✅ COMPLETED

## Overview
Added firmware update checkbox and single ECO number dropdown to the RMA GPU Test page. The implementation allows users to select ONE ECO number from the Firmware Inventory based on the selected image type (H100/200 or B200). The fw_update and eco_number are included in the tests parameter for the PXE boot script.

## Changes Made

### 1. Form Updates (`rd1web/pxe/form.py`)
**Lines Modified:** 259-262

Added the following fields to `RmaForm`:
- `fw_update` - BooleanField checkbox for enabling firmware update
- `eco_number` - Single ChoiceField for ECO number selection

The ECO field is optional and has empty initial choices that are populated dynamically via AJAX based on the selected image type.

### 2. API Endpoint (`rd1web/pxe/views/rma_pxe.py`)
**Lines Added:** 45-82

Created `get_eco_numbers_api` function:
- Accepts `image_type` parameter (e.g., 'ubuntu2204-x86-rma', 'ubuntu2204-b200-rma')
- Maps image type to relevant product types:
  - `ubuntu2204-x86-rma` → H100_AC, H100_LC, H200_AC, H200_LC
  - `ubuntu2204-b200-rma` → B200_AC, B200_LC
- Queries `FirmwareFile` model for distinct ECO numbers across all relevant product types
- Returns combined JSON response with list of available ECO numbers
- Includes error handling and logging
- Protected with `@login_required` and `@permission_required` decorators

### 3. View Logic Updates (`rd1web/pxe/views/rma_pxe.py`)
**Lines Modified:** 76-92, 124-150

Updated `rma_pxe` function to:
- Extract `fw_update` checkbox value from form
- Extract `eco_number` single field value from form
- Build `tests_param` by combining tests, fw_update, and eco_number:
  - If fw_update is checked, append "fw_update" to tests
  - If eco_number is selected, append "eco_number={number}" to tests
- Store fw_update (boolean) and eco_number in PxeEntry.parameters JSONField
- Pass combined tests_param to PXE generation script

**Command format:**
```bash
# With firmware update and ECO number:
/srv/share/scripts/rma_pxe_generation {mac} {image} {base_sn} {rma_number} default fw_update eco_number=27370

# Without firmware update:
/srv/share/scripts/rma_pxe_generation {mac} {image} {base_sn} {rma_number} default

# With firmware update but no ECO:
/srv/share/scripts/rma_pxe_generation {mac} {image} {base_sn} {rma_number} default fw_update
```

Where:
- `fw_update` = literal text "fw_update" (only when checkbox is checked)
- `eco_number=27370` = literal text with just the ECO number value

### 4. URL Registration (`rd1web/pxe/urls.py`)
**Lines Added:** 95-96

Added API endpoint:
```python
path('api/rma/eco-numbers/<str:image_type>/', get_eco_numbers_api, name='rma_eco_numbers_api')
```

### 5. Template Updates (`rd1web/templates/features/rma_pxe.html`)
**Lines Modified:** 177-194 (UI), 679-745 (JavaScript)

#### UI Components:
- Added fw_update checkbox after Tests section (no icons, clean layout)
- Created collapsible ECO Number section (single dropdown) that shows when fw_update is checked AND image is H100/200 or B200
- Single ECO dropdown field populated based on selected image type
- Styled consistently with existing form elements
- Clean labels without icons for better readability

#### JavaScript Functionality:
- `updateEcoSection()` - Shows/hides ECO section based on fw_update checkbox AND selected image:
  - Only shows when fw_update is checked AND image is either:
    - `ubuntu2204-x86-rma` (H100/200)
    - `ubuntu2204-b200-rma` (B200)
  - Hides for MI300X, MI325X, MI355X images
- `loadEcoNumbers(imageType)` - Fetches combined ECO numbers from API and populates single dropdown
  - Makes async fetch request to `/api/rma/eco-numbers/{image_type}/`
  - Returns ECO numbers from all relevant product types for that image
  - Clears and repopulates select options
  - Adds placeholder "-- Select ECO Number --" option
  - Handles errors gracefully

## Database Storage

Firmware update and ECO number are stored in `PxeEntry.parameters` JSONField:
```json
{
  "base_sn": "SN123456",
  "rma_number": "RMA789",
  "tests": "default",
  "fw_update": true,
  "eco_number": "27370"
}
```

Or when fw_update is false:
```json
{
  "base_sn": "SN123456",
  "rma_number": "RMA789",
  "tests": "default",
  "fw_update": false
}
```

## User Flow

1. User navigates to RMA GPU TEST page
2. Fills in Base SN, RMA Number, and selects BMC IP
3. Selects Image type (H100/200 or B200)
4. Selects tests (default, DCGM, etc.)
5. Checks "Firmware Update" checkbox
6. ECO Number section appears (only for H100/200 or B200 images)
7. Single ECO dropdown is auto-populated from Firmware Inventory via API
   - For H100/200: Shows combined ECO numbers from H100_AC, H100_LC, H200_AC, H200_LC
   - For B200: Shows combined ECO numbers from B200_AC, B200_LC
8. User selects ONE ECO number from dropdown
9. On form submission:
   - Form data validated
   - fw_update and eco_number stored in database
   - tests parameter includes selected tests + "fw_update" + "eco_number={number}"
   - PXE boot script receives: `/srv/share/scripts/rma_pxe_generation {mac} {image} {base_sn} {rma_number} {tests_with_fw_and_eco}`
   - PXE boot configuration created with firmware update parameters

## Integration Points

### With Firmware Inventory
- Fetches available ECO numbers from `FirmwareFile` model
- Accepts image_type and maps to relevant product types:
  - `ubuntu2204-x86-rma` → Queries H100_AC, H100_LC, H200_AC, H200_LC
  - `ubuntu2204-b200-rma` → Queries B200_AC, B200_LC
- Returns combined distinct ECO numbers ordered alphabetically

### With PXE Boot System and Database
**✅ Values are passed to BOTH locations:**

1. **Database Storage (PxeEntry.parameters)** - Lines 128-135:
   ```python
   params = {
       'base_sn': base_sn,
       'rma_number': rma_number,
       'tests': " ".join(tests) if tests else " ",
       'fw_update': fw_update  # Stores actual boolean value
   }
   if eco_number:
       params['eco_number'] = eco_number
   ```

2. **PXE Boot Script Parameters** - Lines 86-92, 145-146:
   ```python
   # Build tests parameter including fw_update and eco_number
   tests_list = list(tests) if tests else []
   if fw_update:
       tests_list.append('fw_update')
       if eco_number:
           tests_list.append(f'eco_number={eco_number}')
   tests_param = " ".join(tests_list) if tests_list else " "
   
   # Command execution
   /srv/share/scripts/rma_pxe_generation {mac} {image} {base_sn} {rma_number} {tests_param}
   ```

**Example Commands:**

With fw_update checked and ECO number "27370":
```bash
/srv/share/scripts/rma_pxe_generation 0cc47a758abd ubuntu2204-x86-rma SN123 RMA456 default fw_update eco_number=27370
```

With fw_update checked but no ECO:
```bash
/srv/share/scripts/rma_pxe_generation 0cc47a758abd ubuntu2204-x86-rma SN123 RMA456 default fw_update
```

Without fw_update:
```bash
/srv/share/scripts/rma_pxe_generation 0cc47a758abd ubuntu2204-x86-rma SN123 RMA456 default
```

## Testing Considerations

1. **API Endpoint:** 
   - Test `/api/rma/eco-numbers/ubuntu2204-x86-rma/` returns combined H100/H200 ECO list
   - Test `/api/rma/eco-numbers/ubuntu2204-b200-rma/` returns B200 ECO list
2. **Form Validation:** Ensure optional ECO field doesn't cause validation errors
3. **Dynamic UI:** 
   - Verify ECO dropdown shows only when fw_update checked AND image is H100/200 or B200
   - Verify correct ECO numbers populate based on image type
4. **Database Storage:** 
   - Confirm fw_update boolean stored correctly
   - Confirm eco_number stored when selected
5. **Script Integration:** 
   - Verify PXE generation script receives tests param with fw_update and eco_number appended
   - Verify command format: `{tests} fw_update eco_number={number}`

## Files Modified

1. `/home/devin/rd1web-dev/rd1web/pxe/form.py`
2. `/home/devin/rd1web-dev/rd1web/pxe/views/rma_pxe.py`
3. `/home/devin/rd1web-dev/rd1web/pxe/urls.py`
4. `/home/devin/rd1web-dev/rd1web/templates/features/rma_pxe.html`

## Future Enhancements

- Add validation to require ECO selection when fw_update is checked
- Cache ECO numbers to reduce API calls
- Add loading indicators while fetching ECO numbers
- Display ECO number descriptions/metadata if available
- Add ability to filter ECO numbers by date or other criteria

